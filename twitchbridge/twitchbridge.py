"""Owner-managed Twitch chat, shared commands and announcements."""
import asyncio
import contextlib
import time
from collections import OrderedDict

import aiohttp
import discord
from redbot.core import Config, commands

from .policy import (RecentMessages, log_line, login_name, reconnect_url, command_name,
                     chat_text, render_response, parse_command, twitch_level, command_allowed)
from .errors import BridgeError
from .community import CommunityMixin, ROLE_SCOPES, DEFAULT_SHOUTOUT
from .scopes import BOT_SCOPES, BROADCASTER_SCOPES

BASE = "https://api.twitch.tv/helix/"
AUTH = "https://id.twitch.tv/oauth2/"
SOCKET = "wss://eventsub.wss.twitch.tv/ws"
SCOPES = " ".join(sorted(BOT_SCOPES))


class TwitchBridge(CommunityMixin, commands.Cog):
    """Connect Twitch broadcasters to Discord servers (bot owner only)."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=981376420016, force_registration=True)
        self.config.register_global(bot_auth={})
        self.config.register_guild(broadcaster="", broadcaster_id="", broadcaster_auth={},
                                   chatlog=None, enabled=False, custom_commands={},
                                   announcements=None, command_prefix="!", announcement_color="primary",
                                   member_links={}, role_mappings={}, role_auth={}, roles_enabled=False,
                                   managed_roles={}, shoutout_message=DEFAULT_SHOUTOUT, shoutout_cooldown=60,
                                   link_panel={}, link_panel_label="Link Twitch account",
                                   link_panel_text="Link your Twitch account to receive your server roles.")
        self.http = None
        self.runner = None
        self.sender = None
        self.auth_tasks = {}
        self.token_lock = asyncio.Lock()
        self.settings_lock = asyncio.Lock()
        self.restart_lock = asyncio.Lock()
        self.queue = asyncio.Queue(maxsize=2000)
        self.seen = RecentMessages()
        self.status = "Not connected"
        self.delivery_status = "No messages delivered yet"
        self.dropped = 0
        self.closing = False
        self.command_queue = asyncio.Queue(maxsize=100)
        self.command_worker = None
        self.command_status = "No commands sent yet"
        self.command_dropped = 0
        self.command_locks = {}
        self.cooldowns = OrderedDict()
        self.send_lock = asyncio.Lock()
        self.last_send = 0.0
        self.pending_links = {}
        self.link_attempts = {}
        self.role_worker = None
        self.role_status = {}
        self.shoutout_cooldowns = {}
        self.link_views = {}
        self.link_modals = set()
        self.member_auth_tasks = {}
        self.pending_device_links = {}
        self.link_generation = {}
        self.role_wakeup = asyncio.Event()

    async def cog_load(self):
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        await self._restore_link_panels()
        self.sender = asyncio.create_task(self._deliver())
        self.command_worker = asyncio.create_task(self._command_loop())
        self.runner = asyncio.create_task(self._run())
        self.role_worker = asyncio.create_task(self._role_loop())

    async def cog_unload(self):
        self.closing = True
        for view in self.link_views.values():
            view.stop()
        for modal in list(self.link_modals):
            modal.stop()
        tasks = [self.runner, self.sender, self.command_worker, self.role_worker, *self.auth_tasks.values(), *self.member_auth_tasks.values()]
        for task in tasks:
            if task:
                task.cancel()
        await asyncio.gather(*(t for t in tasks if t), return_exceptions=True)
        if self.http:
            await self.http.close()

    async def red_delete_data_for_user(self, *, requester, user_id):
        for guild_id in await self.config.all_guilds():
            await self._unlink_member(guild_id, user_id)
            async with self.settings_lock:
                group = self.config.guild_from_id(guild_id)
                managed = await group.managed_roles()
                managed.pop(str(user_id), None)
                await group.managed_roles.set(managed)
        self.link_attempts = {k: v for k, v in self.link_attempts.items() if k[1] != user_id}
        self.link_generation = {k: v for k, v in self.link_generation.items() if k[1] != user_id}
        for modal in list(getattr(self, "link_modals", set())):
            if modal.user_id == user_id:
                modal.stop()
                self.link_modals.discard(modal)

    async def _request(self, method, url, **kwargs):
        try:
            async with self.http.request(method, url, **kwargs) as response:
                if response.status == 204 or response.content_length == 0:
                    return response.status, {}
                data = await response.json(content_type=None)
                return response.status, data
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            raise BridgeError("Twitch could not be reached. Retrying may help.") from None

    async def _client_id(self):
        tokens = await self.bot.get_shared_api_tokens("twitchbridge")
        client_id = tokens.get("client_id", "").strip()
        if not client_id:
            raise BridgeError("Configure the Twitch application client ID first; see the cog README.")
        return client_id

    async def _token(self):
        async with self.token_lock:
            auth = await self.config.bot_auth()
            client_id = await self._client_id()
            if not auth or auth.get("client_id") != client_id:
                raise BridgeError("Authorize the bot account with twitchset authbot.")
            if auth["expires_at"] < time.time() + 120:
                code, data = await self._request("POST", AUTH + "token", data={
                    "client_id": client_id, "grant_type": "refresh_token",
                    "refresh_token": auth["refresh_token"],
                })
                if code != 200:
                    raise BridgeError("Bot authorization expired or was revoked; run twitchset authbot.")
                auth.update(access_token=data["access_token"],
                            refresh_token=data["refresh_token"],
                            expires_at=time.time() + data["expires_in"], validated_at=0)
                # Save rotated refresh tokens before another refresh can occur.
                await self.config.bot_auth.set(auth)
            if time.time() - auth.get("validated_at", 0) >= 3600:
                code, data = await self._request("GET", AUTH + "validate", headers={
                    "Authorization": "OAuth " + auth["access_token"],
                })
                if (code != 200 or data.get("client_id") != client_id
                        or data.get("user_id") != auth["user_id"]
                        or "user:read:chat" not in data.get("scopes", [])):
                    raise BridgeError("Bot authorization is invalid; run twitchset authbot.")
                auth["scopes"] = data.get("scopes", [])
                auth["validated_at"] = time.time()
                await self.config.bot_auth.set(auth)
            return client_id, auth

    async def _restart(self):
        async with self.restart_lock:
            if self.runner:
                self.runner.cancel()
                await asyncio.gather(self.runner, return_exceptions=True)
            if not self.closing:
                self.runner = asyncio.create_task(self._run())

    async def _authorize(self, user, guild_id=None, expected=None, purpose="base"):
        """Approval link and completion messages only go to the initiating owner."""
        try:
            client_id = await self._client_id()
            requested_scopes = SCOPES if guild_id is None else " ".join(sorted(BROADCASTER_SCOPES))
            if purpose == "roles":
                cfg = await self.config.guild_from_id(guild_id).all()
                if not cfg["broadcaster_id"]:
                    raise BridgeError("Verify this server's broadcaster with twitchset authorize first.")
                requested_scopes = " ".join(sorted(BROADCASTER_SCOPES))
            code, device = await self._request("POST", AUTH + "device", data={
                "client_id": client_id, "scopes": requested_scopes,
            })
            if code != 200:
                raise BridgeError("Device authorization failed. Check the public Twitch application client ID.")
            await user.send(
                f"Authorize **{expected or 'the bot account'}** on Twitch. "
                f"Check the signed-in account before approving.\n{device['verification_uri']}\n"
                f"Code: `{device['user_code']}`. This expires shortly. Do not share this link."
            )
            interval = max(1, device["interval"])
            deadline = time.monotonic() + device["expires_in"]
            while time.monotonic() < deadline:
                await asyncio.sleep(interval)
                code, data = await self._request("POST", AUTH + "token", data={
                    "client_id": client_id, "device_code": device["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code", "scopes": requested_scopes,
                })
                if code == 200:
                    break
                message = data.get("message", data.get("error", ""))
                if message == "authorization_pending":
                    continue
                if message == "slow_down":
                    interval += 5
                    continue
                raise BridgeError("Twitch authorization was denied or expired. Start again when ready.")
            else:
                raise BridgeError("Twitch approval expired; start authorization again.")
            token_data = data
            code, identity = await self._request("GET", AUTH + "validate", headers={
                "Authorization": "OAuth " + token_data["access_token"],
            })
            if (code != 200 or identity.get("client_id") != client_id
                    or not set(requested_scopes.split()).issubset(identity.get("scopes", []))):
                raise BridgeError("Twitch could not verify this authorization.")
            if expected and identity.get("login", "").lower() != expected:
                raise BridgeError("The approved Twitch account did not match the configured broadcaster. Nothing was linked.")
            auth = {"client_id": client_id, "user_id": identity["user_id"],
                    "login": identity["login"], "access_token": token_data["access_token"],
                    "refresh_token": token_data["refresh_token"],
                    "expires_at": time.time() + token_data["expires_in"],
                    "validated_at": time.time(), "scopes": identity.get("scopes", [])}
            async with self.settings_lock:
                if guild_id is None:
                    async with self.token_lock:
                        await self.config.bot_auth.set(auth)
                else:
                    group = self.config.guild_from_id(guild_id)
                    settings = await group.all()
                    if settings["broadcaster"] != expected:
                        raise BridgeError("Server settings changed during approval; authorize again.")
                    for other_id, other in (await self.config.all_guilds()).items():
                        if other_id != guild_id and other["broadcaster_id"] == identity["user_id"]:
                            raise BridgeError("This broadcaster is already linked to another server.")
                    if purpose == "roles":
                        if settings["broadcaster_id"] != identity["user_id"]:
                            raise BridgeError("Broadcaster changed during role approval. Authorize again.")
                        await group.role_auth.set(auth)
                    else:
                        await group.broadcaster_id.set(identity["user_id"])
                        await group.broadcaster_auth.set({"client_id": client_id, "login": identity["login"]})
                        # One broadcaster approval covers all existing role mappings
                        # and the deferred redemption integration.
                        await group.role_auth.set(auth)
            await self._restart()
            await user.send(f"Twitch account `{identity['login']}` verified. Run `twitchset status` in the server.")
        except (BridgeError, discord.HTTPException) as exc:
            with contextlib.suppress(discord.HTTPException):
                await user.send(str(exc) if isinstance(exc, BridgeError) else "Enable DMs and retry authorization.")
        except (KeyError, TypeError):
            with contextlib.suppress(discord.HTTPException):
                await user.send("Twitch returned an unexpected authorization response; retry later.")

    async def _run(self):
        await self.bot.wait_until_red_ready()
        delay = 2
        while not self.closing:
            try:
                settings = await self.config.all_guilds()
                client_id = await self._client_id()
                routes = {str(gid): cfg for gid, cfg in settings.items()
                          if cfg["enabled"] and cfg["broadcaster_id"]
                          and cfg["broadcaster_auth"].get("client_id") == client_id
                          and self.bot.get_guild(gid) is not None}
                if not routes:
                    self.status = "Waiting for an authorized broadcaster and enabled setting"
                    return
                client_id, auth = await self._token()
                self.status = "Connecting"
                await self._listen(routes, client_id, auth)
                delay = 2
            except asyncio.CancelledError:
                raise
            except BridgeError as exc:
                self.status = str(exc)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError):
                self.status = "Connection interrupted; retrying"
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def _listen(self, routes, client_id, auth):
        ws = None
        replacement = None
        try:
            ws = await self.http.ws_connect(SOCKET, autoping=True)
            welcome = await ws.receive_json(timeout=15)
            session = welcome["payload"]["session"]
            if welcome["metadata"]["message_type"] != "session_welcome":
                raise BridgeError("Twitch did not send a welcome message.")
            timeout = session.get("keepalive_timeout_seconds") or 10
            for cfg in routes.values():
                code, _ = await self._request("POST", BASE + "eventsub/subscriptions", headers={
                    "Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"],
                }, json={"type": "channel.chat.message", "version": "1", "condition": {
                    "broadcaster_user_id": cfg["broadcaster_id"], "user_id": auth["user_id"],
                }, "transport": {"method": "websocket", "session_id": session["id"]}})
                if code != 202:
                    raise BridgeError(f"Twitch refused a chat subscription (HTTP {code}); check bot authorization.")
            self.status = f"Connected to {len(routes)} Twitch channel(s)"
            while True:
                message = await ws.receive_json(timeout=timeout + 5)
                kind = message["metadata"]["message_type"]
                if kind == "session_reconnect":
                    url = reconnect_url(message["payload"]["session"]["reconnect_url"])
                    # Keep the old connection alive until Twitch welcomes its replacement.
                    replacement = await self.http.ws_connect(url, autoping=True)
                    welcome = await replacement.receive_json(timeout=15)
                    if welcome["metadata"]["message_type"] != "session_welcome":
                        raise BridgeError("Twitch reconnect failed.")
                    timeout = welcome["payload"]["session"].get("keepalive_timeout_seconds") or timeout
                    await ws.close()
                    ws, replacement = replacement, None
                    # Subscriptions transfer; do not create duplicates on a handoff.
                elif kind == "revocation":
                    raise BridgeError("A Twitch subscription was revoked; check authorization.")
                elif kind == "notification":
                    self._notification(message, routes, auth["user_id"])
                # Validate at least hourly, including on quiet channels.
                await self._token()
        finally:
            if replacement is not None:
                await replacement.close()
            if ws is not None:
                await ws.close()

    def _notification(self, message, routes, bot_id):
        payload = message["payload"]
        subscription = payload.get("subscription", {})
        if subscription.get("type") != "channel.chat.message":
            return
        event = payload["event"]
        condition = subscription.get("condition", {})
        if (condition.get("user_id") != bot_id
                or condition.get("broadcaster_user_id") != event.get("broadcaster_user_id")):
            return
        if not self.seen.accept(event.get("message_id")):
            return
        for gid, cfg in routes.items():
            if cfg["broadcaster_id"] != event.get("broadcaster_user_id"):
                continue
            parsed = parse_command(event.get("message", {}).get("text", ""), cfg.get("command_prefix", "!"))
            log_event = event
            if parsed and parsed[0] == "link":
                log_event = dict(event, message={"text": "[account verification code hidden]"})
            if cfg.get("chatlog"):
                item = (int(gid), cfg["broadcaster_id"], cfg["chatlog"],
                        log_line(log_event, message["metadata"].get("message_timestamp", "")))
                try:
                    self.queue.put_nowait(item)
                except asyncio.QueueFull:
                    self.dropped += 1
            # Log bot messages, but never execute them as commands. Shared-chat
            # messages originating in another channel must not trigger commands.
            if event.get("chatter_user_id") == bot_id and (not parsed or parsed[0] != "link"):
                continue
            if event.get("source_broadcaster_user_id") not in (None, "", cfg["broadcaster_id"]):
                continue
            parsed = parse_command(event.get("message", {}).get("text", ""), cfg.get("command_prefix", "!"))
            if parsed:
                try:
                    self.command_queue.put_nowait((int(gid), cfg["broadcaster_id"], event))
                except asyncio.QueueFull:
                    self.command_dropped += 1

    async def _deliver(self):
        while True:
            guild_id, broadcaster_id, channel_id, content = await self.queue.get()
            try:
                # Recheck settings so queued logs cannot leak into a stale destination.
                cfg = await self.config.guild_from_id(guild_id).all()
                if not cfg["enabled"] or cfg["chatlog"] != channel_id or cfg["broadcaster_id"] != broadcaster_id:
                    continue
                guild = self.bot.get_guild(guild_id)
                channel = guild.get_channel(channel_id) if guild else None
                if not isinstance(channel, discord.TextChannel):
                    self.dropped += 1
                    self.delivery_status = "Log channel unavailable"
                    continue
                await channel.send(content, allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
                self.delivery_status = "Last message delivered successfully"
            except discord.HTTPException:
                self.dropped += 1
                self.delivery_status = "Discord delivery failed; check channel permissions"
            finally:
                self.queue.task_done()

    @commands.is_owner()
    @commands.guild_only()
    @commands.group(name="twitchset", invoke_without_command=True)
    async def twitchset(self, ctx):
        """Owner-only Twitch setup. Authorization links arrive by DM."""
        await ctx.send_help()

    @twitchset.command(name="link")
    async def link(self, ctx, broadcaster: str):
        """Select a broadcaster; ownership must still be authorized."""
        try:
            broadcaster = login_name(broadcaster)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        async with self.settings_lock:
            task = self.auth_tasks.get(ctx.guild.id)
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            group = self.config.guild(ctx.guild)
            await self._cleanup_roles_locked(ctx.guild, all_roles=True)
            await group.roles_enabled.set(False)
            await group.role_auth.set({})
            self.pending_links = {k: v for k, v in self.pending_links.items() if k[0] != ctx.guild.id}
            await group.broadcaster.set(broadcaster)
            await group.broadcaster_id.set("")
            await group.broadcaster_auth.set({})
            await group.enabled.set(False)
        await self._restart()
        await ctx.send(f"Broadcaster `{broadcaster}` selected. Run `{ctx.clean_prefix}twitchset authorize` to verify ownership.")

    async def _start_auth(self, ctx, key, expected=None, purpose="base"):
        task = self.auth_tasks.get(key)
        if task and not task.done():
            await ctx.send("Authorization is already pending; check your DMs.")
            return
        try:
            await self._client_id()
            await ctx.author.send("Starting Twitch authorization. The next message contains a private approval link.")
        except BridgeError as exc:
            await ctx.send(str(exc))
            return
        except discord.HTTPException:
            await ctx.send("Enable DMs from me, then retry. No approval link was posted here.")
            return
        self.auth_tasks[key] = asyncio.create_task(self._authorize(ctx.author, key, expected, purpose=purpose))
        await ctx.send("Check your DMs for the Twitch approval link.")

    @twitchset.command(name="authbot")
    async def authbot(self, ctx):
        """Authorize the dedicated Twitch bot account through a private link."""
        await self._start_auth(ctx, None)

    @twitchset.command(name="authorize")
    async def authorize(self, ctx):
        """Prove ownership of the selected broadcaster account."""
        expected = await self.config.guild(ctx.guild).broadcaster()
        if not expected:
            await ctx.send("Select a broadcaster with twitchset link first.")
            return
        await self._start_auth(ctx, ctx.guild.id, expected)

    @twitchset.command(name="chatlog")
    async def chatlog(self, ctx, channel: discord.TextChannel):
        """Choose this server's destination for Twitch chat logs."""
        if channel.guild.id != ctx.guild.id:
            await ctx.send("Choose a text channel in this server.")
            return
        perms = channel.permissions_for(ctx.guild.me)
        if not perms.view_channel or not perms.send_messages:
            await ctx.send("I need View Channel and Send Messages in that channel.")
            return
        await self.config.guild(ctx.guild).chatlog.set(channel.id)
        await self._restart()
        await ctx.send("Twitch chat-log channel saved.")

    @twitchset.command(name="enabled")
    async def enabled(self, ctx, enabled: bool):
        """Start or pause chat logging and custom commands for this server."""
        cfg = await self.config.guild(ctx.guild).all()
        if enabled and not cfg["broadcaster_id"]:
            await ctx.send("Authorize the broadcaster first.")
            return
        async with self.settings_lock:
            await self.config.guild(ctx.guild).enabled.set(enabled)
        await self._restart()
        await ctx.send("Twitch integration enabled." if enabled else "Twitch integration paused.")

    @twitchset.command(name="disconnect")
    async def disconnect(self, ctx):
        """Remove this server's Twitch mapping and log destination."""
        task = self.auth_tasks.get(ctx.guild.id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self.settings_lock:
            await self._cleanup_roles_locked(ctx.guild, all_roles=True)
            group = self.config.guild(ctx.guild)
            await group.roles_enabled.set(False)
            await group.role_auth.set({})
            self.pending_links = {k: v for k, v in self.pending_links.items() if k[0] != ctx.guild.id}
            await group.enabled.set(False)
            await group.broadcaster.set("")
            await group.broadcaster_id.set("")
            await group.broadcaster_auth.set({})
            await group.chatlog.set(None)
        await self._restart()
        await ctx.send("This server's Twitch connection was removed. Custom commands and existing Discord logs remain.")

    @twitchset.command(name="forgetbot")
    async def forgetbot(self, ctx):
        """Forget the bot token globally, stopping logging for every server."""
        task = self.auth_tasks.get(None)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self.token_lock:
            await self.config.bot_auth.set({})
        await self._restart()
        await ctx.send("Bot authorization forgotten for all servers. You may also revoke the app in Twitch Connections.")

    @twitchset.command(name="status")
    async def connection_status(self, ctx):
        """Show connection and delivery health without displaying credentials."""
        cfg = await self.config.guild(ctx.guild).all()
        auth = await self.config.bot_auth()
        await ctx.send(
            f"Broadcaster: {cfg['broadcaster'] or 'not selected'} | Verified: {bool(cfg['broadcaster_id'])}\n"
            f"Bot account: {auth.get('login', 'not authorized')} | Enabled: {cfg['enabled']}\n"
            f"Chat-log channel: {cfg['chatlog'] or 'not configured'}\n"
            f"Connection: {self.status}\nDelivery: {self.delivery_status}\n"
            f"Queued logs: {self.queue.qsize()} | Dropped logs: {self.dropped}\n"
            f"Commands: {self.command_status} | Queue: {self.command_queue.qsize()} | Dropped: {self.command_dropped}\n"
            f"Chat writing authorized: {'user:write:chat' in auth.get('scopes', [])}\n"
            f"Announcements authorized: {'moderator:manage:announcements' in auth.get('scopes', [])}",
            allowed_mentions=discord.AllowedMentions.none(),
        )


    def _command_lock(self, guild_id):
        return self.command_locks.setdefault(guild_id, asyncio.Lock())

    async def _prepare_command(self, guild_id, name, args, platform, level, user, broadcaster_id=None):
        async with self._command_lock(guild_id):
            cfg = await self.config.guild_from_id(guild_id).all()
            if not cfg["enabled"] or (broadcaster_id is not None and cfg["broadcaster_id"] != broadcaster_id):
                return None
            record = cfg.get("custom_commands", {}).get(name)
            if not record or not command_allowed(record, platform, level):
                return None
            key = (guild_id, name)
            now = time.monotonic()
            if now < self.cooldowns.get(key, 0):
                return None
            text = render_response(record["response"], user=user, args=args, channel=cfg["broadcaster"])
            self.cooldowns[key] = now + record.get("cooldown", 5)
            # Discard only expired entries; active cooldowns must not be evicted.
            for old in list(self.cooldowns):
                if self.cooldowns[old] <= now:
                    self.cooldowns.pop(old, None)
            return text

    async def _send_twitch(self, guild_id, text, expected_broadcaster=None, *, announcement=False):
        text = chat_text(text)
        # Stay below the normal 20 messages/30 sec chat limit across all channels.
        async with self.send_lock:
            await asyncio.sleep(max(0, self.last_send + 2.1 - time.monotonic()))
            cfg = await self.config.guild_from_id(guild_id).all()
            if not cfg["enabled"] or not cfg["broadcaster_id"]:
                raise BridgeError("The Twitch connection is paused or not configured.")
            if expected_broadcaster is not None and cfg["broadcaster_id"] != expected_broadcaster:
                raise BridgeError("The broadcaster changed before this message could be sent.")
            client_id, auth = await self._token()
            if cfg["broadcaster_auth"].get("client_id") != client_id:
                raise BridgeError("Authorize the broadcaster for this application first.")
            if announcement:
                if "moderator:manage:announcements" not in auth.get("scopes", []):
                    raise BridgeError("Announcements need approval. Run twitchset authbot again as Paimon's Twitch account.")
                self.last_send = time.monotonic()
                code, _ = await self._request("POST", BASE + "chat/announcements", headers={
                    "Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"],
                }, params={"broadcaster_id": cfg["broadcaster_id"], "moderator_id": auth["user_id"]},
                    json={"message": text, "color": cfg.get("announcement_color", "primary")})
                if code == 403:
                    raise BridgeError("Paimon must be a moderator in the linked Twitch channel to send announcements.")
                if code != 204:
                    raise BridgeError(f"Twitch did not accept the announcement (HTTP {code}). Check announcement authorization and moderator status.")
                self.command_status = "Last Twitch announcement sent successfully"
                return None
            if "user:write:chat" not in auth.get("scopes", []):
                raise BridgeError("Chat writing needs approval. Run twitchset authbot again as Paimon's Twitch account.")
            self.last_send = time.monotonic()
            code, data = await self._request("POST", BASE + "chat/messages", headers={
                "Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"],
            }, json={"broadcaster_id": cfg["broadcaster_id"], "sender_id": auth["user_id"], "message": text})
            # Do not retry sends automatically: a timed-out request may have succeeded.
            if code != 200:
                raise BridgeError(f"Twitch did not accept the chat request (HTTP {code}).")
            results = data.get("data", [])
            if not results or not results[0].get("is_sent"):
                raise BridgeError("Twitch dropped the message. Check moderation, duplicate text and chat restrictions.")
            self.command_status = "Last Twitch message sent successfully"
            return results[0].get("message_id")

    async def _command_loop(self):
        while True:
            guild_id, broadcaster_id, event = await self.command_queue.get()
            try:
                cfg = await self.config.guild_from_id(guild_id).all()
                parsed = parse_command(event.get("message", {}).get("text", ""), cfg.get("command_prefix", "!"))
                if not parsed:
                    continue
                if parsed[0] == "link":
                    await self._complete_member_link(guild_id, broadcaster_id, event, parsed[1].strip())
                    continue
                if parsed[0] in ("so", "shoutout"):
                    if twitch_level(event) >= 1:
                        # Recheck the queued route before resolving/sending a shoutout.
                        if cfg["broadcaster_id"] == broadcaster_id and cfg["enabled"]:
                            await self._shoutout(guild_id, parsed[1].strip(), expected_broadcaster=broadcaster_id)
                    continue
                text = await self._prepare_command(guild_id, *parsed, "twitch", twitch_level(event),
                                                   event.get("chatter_user_name", "viewer"), broadcaster_id)
                if text:
                    await self._send_twitch(guild_id, text, expected_broadcaster=broadcaster_id)
            except (BridgeError, ValueError) as exc:
                self.command_status = str(exc)
            finally:
                self.command_queue.task_done()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        if not await self.bot.message_eligible_as_command(message):
            return
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return  # Never shadow a registered Discord command.
        prefixes = await self.bot.get_valid_prefixes(message.guild)
        prefix = next((p for p in sorted(prefixes, key=len, reverse=True) if message.content.startswith(p)), None)
        parsed = parse_command(message.content, prefix)
        if not parsed:
            return
        owner = await self.bot.is_owner(message.author)
        level = 2 if owner or message.author.id == message.guild.owner_id else 0
        if level == 0 and (message.author.guild_permissions.manage_guild or await self.bot.is_mod(message.author)):
            level = 1
        try:
            text = await self._prepare_command(message.guild.id, *parsed, "discord", level, message.author.display_name)
            if text:
                await message.channel.send(text, allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
        except (ValueError, discord.HTTPException) as exc:
            self.command_status = str(exc) if isinstance(exc, ValueError) else "Discord command reply failed"

    @commands.is_owner()
    @commands.guild_only()
    @commands.group(name="twitchcommand", invoke_without_command=True)
    async def twitchcommand(self, ctx):
        """Manage this server's standalone shared commands (bot owner only)."""
        await ctx.send_help()

    @twitchcommand.command(name="add")
    async def command_add(self, ctx, name: str, *, response: str):
        """Add a Twitch command; default permission everyone, cooldown 5 seconds."""
        try:
            name, response = command_name(name), chat_text(response)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        if self.bot.get_command(name):
            await ctx.send("That name belongs to a registered Discord command; choose another name.")
            return
        async with self._command_lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).custom_commands() as records:
                if name in records:
                    await ctx.send("That command exists. Use twitchcommand edit.")
                    return
                if len(records) >= 250:
                    await ctx.send("This server already has 250 custom commands.")
                    return
                records[name] = {"response": response, "platform": "twitch", "permission": "everyone", "cooldown": 5}
        await ctx.send(f"Command `{name}` added for Twitch. Use twitchcommand platform to enable it in Discord too.")

    async def _edit_command(self, ctx, name, field, value):
        try:
            name = command_name(name)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        async with self._command_lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).custom_commands() as records:
                if name not in records:
                    await ctx.send("Command not found.")
                    return
                records[name][field] = value
        await ctx.send(f"Command `{name}` updated.")

    @twitchcommand.command(name="edit")
    async def command_edit(self, ctx, name: str, *, response: str):
        """Replace a command's response."""
        try:
            response = chat_text(response)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        await self._edit_command(ctx, name, "response", response)

    @twitchcommand.command(name="platform")
    async def command_platform(self, ctx, name: str, platform: str):
        """Choose twitch, discord, or both."""
        platform = platform.lower()
        if platform not in ("twitch", "discord", "both"):
            await ctx.send("Choose twitch, discord, or both.")
            return
        await self._edit_command(ctx, name, "platform", platform)

    @twitchcommand.command(name="permission")
    async def command_permission(self, ctx, name: str, permission: str):
        """Choose everyone, moderator, or broadcaster."""
        permission = permission.lower()
        if permission not in ("everyone", "moderator", "broadcaster"):
            await ctx.send("Choose everyone, moderator, or broadcaster.")
            return
        await self._edit_command(ctx, name, "permission", permission)

    @twitchcommand.command(name="cooldown")
    async def command_cooldown(self, ctx, name: str, seconds: int):
        """Set a server-wide command cooldown of 0-86400 seconds."""
        if not 0 <= seconds <= 86400:
            await ctx.send("Choose 0-86400 seconds.")
            return
        await self._edit_command(ctx, name, "cooldown", seconds)

    @twitchcommand.command(name="remove", aliases=["delete"])
    async def command_remove(self, ctx, name: str):
        """Delete a custom command."""
        name = name.lower().lstrip("!")
        async with self._command_lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).custom_commands() as records:
                removed = records.pop(name, None)
            self.cooldowns.pop((ctx.guild.id, name), None)
        await ctx.send("Command removed." if removed else "Command not found.")

    @twitchcommand.command(name="list")
    async def command_list(self, ctx):
        """List names, platforms, permissions and cooldowns."""
        records = await self.config.guild(ctx.guild).custom_commands()
        lines = [f"{name}: {r['platform']} | {r['permission']} | {r['cooldown']}s" for name, r in sorted(records.items())]
        if not lines:
            await ctx.send("No custom commands configured.")
        for start in range(0, len(lines), 15):
            await ctx.send("\n".join(lines[start:start + 15]), allowed_mentions=discord.AllowedMentions.none())

    @twitchset.command(name="announcements")
    async def announcement_channel(self, ctx, channel: discord.TextChannel):
        """Select this server's Discord announcement destination."""
        if channel.guild.id != ctx.guild.id:
            await ctx.send("Choose a text channel in this server.")
            return
        permissions = channel.permissions_for(ctx.guild.me)
        if not permissions.view_channel or not permissions.send_messages:
            await ctx.send("I need View Channel and Send Messages there.")
            return
        await self.config.guild(ctx.guild).announcements.set(channel.id)
        await ctx.send("Discord announcement channel saved.")

    @twitchset.command(name="prefix")
    async def twitch_prefix(self, ctx, prefix: str):
        """Choose a Twitch trigger prefix (1-5 punctuation characters)."""
        if not 1 <= len(prefix) <= 5 or any(c.isalnum() or not 33 <= ord(c) <= 126 for c in prefix):
            await ctx.send("Use 1-5 punctuation characters, such as !.")
            return
        await self.config.guild(ctx.guild).command_prefix.set(prefix)
        await self._restart()
        await ctx.send("Twitch command prefix updated.")

    @commands.is_owner()
    @commands.guild_only()
    @commands.command(name="twitchannounce")
    async def twitchannounce(self, ctx, destination: str, *, message: str):
        """Send a Twitch announcement banner and/or Discord message (owner only)."""
        destination = destination.lower()
        if destination not in ("twitch", "discord", "both"):
            await ctx.send("Choose twitch, discord, or both.")
            return
        try:
            message = chat_text(message)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        cfg = await self.config.guild(ctx.guild).all()
        results = []
        if destination in ("twitch", "both"):
            try:
                await self._send_twitch(ctx.guild.id, message, announcement=True)
                results.append("Twitch: sent")
            except BridgeError as exc:
                results.append(f"Twitch: {exc}")
        if destination in ("discord", "both"):
            channel = ctx.guild.get_channel(cfg.get("announcements")) if cfg.get("announcements") else None
            if not isinstance(channel, discord.TextChannel):
                results.append("Discord: configure twitchset announcements first")
            else:
                try:
                    await channel.send(message, allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
                    results.append("Discord: sent")
                except discord.HTTPException:
                    results.append("Discord: delivery failed; check channel permissions")
        await ctx.send("\n".join(results), allowed_mentions=discord.AllowedMentions.none())


    @twitchset.command(name="announcementcolor")
    async def announcement_color(self, ctx, color: str):
        """Choose primary, blue, green, orange, or purple for Twitch banners."""
        color = color.lower()
        if color not in ("primary", "blue", "green", "orange", "purple"):
            await ctx.send("Choose primary, blue, green, orange, or purple.")
            return
        await self.config.guild(ctx.guild).announcement_color.set(color)
        await ctx.send(f"Twitch announcement color set to {color}.")


    @twitchset.command(name="shoutoutmessage")
    async def shoutout_message(self, ctx, *, message: str):
        """Set follow-message text with {user}, {url}, and optionally {channel}."""
        try:
            message = chat_text(message)
            if "{url}" not in message:
                raise ValueError("Include {url} so the shoutout contains the Twitch link.")
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        await self.config.guild(ctx.guild).shoutout_message.set(message)
        await ctx.send("Shoutout message saved.")

    @twitchset.command(name="shoutoutcooldown")
    async def shoutout_cooldown(self, ctx, seconds: int):
        """Set the shared shoutout cooldown (0-86400 seconds)."""
        if not 0 <= seconds <= 86400:
            await ctx.send("Choose 0-86400 seconds.")
            return
        await self.config.guild(ctx.guild).shoutout_cooldown.set(seconds)
        await ctx.send("Shoutout cooldown saved.")
