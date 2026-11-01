"""First milestone: owner-managed Twitch authorization and chat logging."""
import asyncio
import contextlib
import time

import aiohttp
import discord
from redbot.core import Config, commands

from .policy import RecentMessages, log_line, login_name, reconnect_url

BASE = "https://api.twitch.tv/helix/"
AUTH = "https://id.twitch.tv/oauth2/"
SOCKET = "wss://eventsub.wss.twitch.tv/ws"
SCOPES = "user:read:chat"


class BridgeError(Exception):
    """Safe error text: never includes OAuth responses or secrets."""


class TwitchBridge(commands.Cog):
    """Connect Twitch broadcasters to Discord servers (bot owner only)."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=981376420016, force_registration=True)
        self.config.register_global(bot_auth={})
        self.config.register_guild(broadcaster="", broadcaster_id="", broadcaster_auth={},
                                   chatlog=None, enabled=False)
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

    async def cog_load(self):
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        self.sender = asyncio.create_task(self._deliver())
        self.runner = asyncio.create_task(self._run())

    async def cog_unload(self):
        self.closing = True
        tasks = [self.runner, self.sender, *self.auth_tasks.values()]
        for task in tasks:
            if task:
                task.cancel()
        await asyncio.gather(*(t for t in tasks if t), return_exceptions=True)
        if self.http:
            await self.http.close()

    async def red_delete_data_for_user(self, *, requester, user_id):
        # No member Discord IDs or member account links are stored in this milestone.
        return

    async def _request(self, method, url, **kwargs):
        try:
            async with self.http.request(method, url, **kwargs) as response:
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

    async def _authorize(self, user, guild_id=None, expected=None):
        """Approval link and completion messages only go to the initiating owner."""
        try:
            client_id = await self._client_id()
            code, device = await self._request("POST", AUTH + "device", data={
                "client_id": client_id, "scopes": SCOPES,
            })
            if code != 200:
                raise BridgeError("Device authorization failed. Check the public Twitch application client ID.")
            await user.send(
                f"Authorize **{expected or 'Paimonâ€™s bot account'}** on Twitch. "
                f"Check the signed-in account before approving.\n{device['verification_uri']}\n"
                f"Code: `{device['user_code']}`. This expires shortly. Do not share this link."
            )
            interval = max(1, device["interval"])
            deadline = time.monotonic() + device["expires_in"]
            while time.monotonic() < deadline:
                await asyncio.sleep(interval)
                code, data = await self._request("POST", AUTH + "token", data={
                    "client_id": client_id, "device_code": device["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code", "scopes": SCOPES,
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
                    or "user:read:chat" not in identity.get("scopes", [])):
                raise BridgeError("Twitch could not verify this authorization.")
            if expected and identity.get("login", "").lower() != expected:
                raise BridgeError("The approved Twitch account did not match the configured broadcaster. Nothing was linked.")
            auth = {"client_id": client_id, "user_id": identity["user_id"],
                    "login": identity["login"], "access_token": token_data["access_token"],
                    "refresh_token": token_data["refresh_token"],
                    "expires_at": time.time() + token_data["expires_in"],
                    "validated_at": time.time()}
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
                    # Broadcaster approval proves control. No broadcaster token is retained
                    # until a later milestone needs channel-specific permissions.
                    await group.broadcaster_id.set(identity["user_id"])
                    await group.broadcaster_auth.set({"client_id": client_id, "login": identity["login"]})
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
                          if cfg["enabled"] and cfg["chatlog"] and cfg["broadcaster_id"]
                          and cfg["broadcaster_auth"].get("client_id") == client_id
                          and self.bot.get_guild(gid) is not None}
                if not routes:
                    self.status = "Waiting for an authorized broadcaster, chat-log channel, and enabled setting"
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
            self.status = f"Connected; logging {len(routes)} Twitch channel(s)"
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
            item = (int(gid), cfg["broadcaster_id"], cfg["chatlog"],
                    log_line(event, message["metadata"].get("message_timestamp", "")))
            try:
                self.queue.put_nowait(item)
            except asyncio.QueueFull:
                self.dropped += 1

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
            await group.broadcaster.set(broadcaster)
            await group.broadcaster_id.set("")
            await group.broadcaster_auth.set({})
            await group.enabled.set(False)
        await self._restart()
        await ctx.send(f"Broadcaster `{broadcaster}` selected. Run `{ctx.clean_prefix}twitchset authorize` to verify ownership.")

    async def _start_auth(self, ctx, key, expected=None):
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
        self.auth_tasks[key] = asyncio.create_task(self._authorize(ctx.author, key, expected))
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
        """Start or pause logging for this server."""
        cfg = await self.config.guild(ctx.guild).all()
        if enabled and (not cfg["broadcaster_id"] or not cfg["chatlog"]):
            await ctx.send("Authorize the broadcaster and configure a chat-log channel first.")
            return
        await self.config.guild(ctx.guild).enabled.set(enabled)
        await self._restart()
        await ctx.send("Twitch logging enabled." if enabled else "Twitch logging paused.")

    @twitchset.command(name="disconnect")
    async def disconnect(self, ctx):
        """Remove this server's Twitch mapping and log destination."""
        task = self.auth_tasks.get(ctx.guild.id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.config.guild(ctx.guild).clear()
        await self._restart()
        await ctx.send("This server's Twitch connection was removed. Existing Discord logs remain.")

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
            f"Queued: {self.queue.qsize()} | Dropped since load: {self.dropped}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
