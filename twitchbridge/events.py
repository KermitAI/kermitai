"""Broadcaster-authorized channel events and configurable Twitch responses."""
import asyncio
import copy
import re
import string
import time

import aiohttp
import discord
from redbot.core import commands

from .errors import BridgeError
from .permissions import staff_only
from .variables import mask_extended
from .policy import RecentMessages, reconnect_url

API = "https://api.twitch.tv/helix/"
SOCKET = "wss://eventsub.wss.twitch.tv/ws"
EVENTS = {
    "follow": ("channel.follow", "2", "moderator:read:followers"),
    "subscribe": ("channel.subscribe", "1", "channel:read:subscriptions"),
    "resub": ("channel.subscription.message", "1", "channel:read:subscriptions"),
    "gift": ("channel.subscription.gift", "1", "channel:read:subscriptions"),
    "cheer": ("channel.cheer", "1", "bits:read"),
    "raid": ("channel.raid", "1", None),
}
DEFAULT_MESSAGES = {
    "follow": "Thanks for following, {user}! Welcome to {channel}!",
    "subscribe": "Thank you for the tier {tier} subscription, {user}!",
    "resub": "Welcome back, {user}! Thank you for {months} months!",
    "gift": "Thank you, {user}, for gifting {count} tier {tier} subscription(s)!",
    "cheer": "Thank you, {user}, for cheering {bits} Bits!",
    "raid": "Welcome, {user} and your {viewers} raiders! Check them out at {url}!",
}
FIELDS = {
    "follow": {"user", "channel", "url"},
    "subscribe": {"user", "channel", "url", "tier"},
    "resub": {"user", "channel", "url", "tier", "months", "message"},
    "gift": {"user", "channel", "url", "tier", "count"},
    "cheer": {"user", "channel", "url", "bits", "message"},
    "raid": {"user", "channel", "url", "viewers"},
}
for fields in FIELDS.values():
    fields.update({"game", "usergame"})

EVENT_DEFAULTS = {"enabled": False, "mode": "chat", "revision": 0,
                  "types": {kind: True for kind in EVENTS},
                  "messages": DEFAULT_MESSAGES, "cooldowns": {kind: 0 for kind in EVENTS}}
MAX_EVENT_AGE = 120


def event_kind(value):
    kind = value.lower()
    if kind not in EVENTS:
        raise ValueError("Choose follow, subscribe, resub, gift, cheer, or raid.")
    return kind


def validate_event_template(kind, template):
    if not template.strip() or len(template) > 4000:
        raise ValueError("Use a message template of 1-4000 characters.")
    try:
        masked, extended_fields = mask_extended(template)
        fields = string.Formatter().parse(masked)
        for literal, field, spec, conversion in fields:
            if field is not None and (field not in FIELDS[kind] | set(extended_fields) or spec or conversion):
                raise ValueError("Unsupported placeholder. Available: " + ", ".join(sorted(FIELDS[kind])))
    except (ValueError, KeyError):
        raise ValueError("Use plain text and these placeholders: " + ", ".join("{" + f + "}" for f in sorted(FIELDS[kind]))) from None
    return template.strip()


def render_event(kind, template, event, channel, game="Unknown game", usergame="Unknown game", extended=None):
    anonymous = bool(event.get("is_anonymous"))
    raid = kind == "raid"
    prefix = "from_broadcaster_" if raid else ""
    user = "Anonymous" if anonymous else event.get(prefix + "user_name") or event.get(prefix + "user_login") or "Viewer"
    login = "" if anonymous else event.get(prefix + "user_login", "")
    # Usernames are only used to construct Twitch URLs after strict validation.
    url = "https://twitch.tv/" + login if re.fullmatch(r"[a-zA-Z0-9_]{1,25}", login) else ""
    message = event.get("message", "")
    if isinstance(message, dict):
        message = message.get("text", "")
    values = {"user": user, "url": url, "channel": channel, "game": game, "usergame": usergame,
              "tier": {"1000": "1", "2000": "2", "3000": "3", "Prime": "Prime"}.get(event.get("tier"), "1"),
              "months": event.get("cumulative_months", 0), "count": event.get("total", 1),
              "bits": event.get("bits", 0), "viewers": event.get("viewers", 0), "message": message}
    masked, extended_fields = mask_extended(template)
    values.update({key: (extended or {}).get(raw, raw) for key, raw in extended_fields.items()})
    values = {key: " ".join("".join(c for c in str(value) if ord(c) >= 32 or c.isspace()).split())
              for key, value in values.items()}
    text = masked.format_map(values)
    text = " ".join("".join(c for c in text if ord(c) >= 32 or c.isspace()).split())
    return text[:497] + "..." if len(text) > 500 else text


def event_specs(broadcaster_id, kinds):
    result = {}
    for kind in kinds:
        topic, version, scope = EVENTS[kind]
        condition = {"to_broadcaster_user_id": broadcaster_id} if kind == "raid" else {"broadcaster_user_id": broadcaster_id}
        if kind == "follow":
            condition["moderator_user_id"] = broadcaster_id
        result[kind] = {"type": topic, "version": version, "condition": condition}
    return result


class ChannelEventsMixin:
    def _init_channel_events(self):
        self.event_supervisor = None
        self.event_sender = None
        self.event_tasks = {}
        self.event_signatures = {}
        self.events_wakeup = asyncio.Event()
        self.event_queue = asyncio.Queue(maxsize=200)
        self.event_seen = RecentMessages()
        self.event_connections = {}
        self.event_deliveries = {}
        self.event_counts = {}
        self.event_last_sent = {}

    def _event_count(self, guild_id, metric):
        counts = self.event_counts.setdefault(guild_id, {"queued": 0, "sent": 0, "dropped": 0})
        counts[metric] += 1

    async def _event_token(self, guild_id, broadcaster_id):
        async with self.settings_lock:
            cfg = await self.config.guild_from_id(guild_id).all()
            if not cfg["enabled"] or cfg["broadcaster_id"] != broadcaster_id or not cfg.get("channel_events", {}).get("enabled"):
                raise BridgeError("Channel events are paused or the broadcaster changed.")
            # Broadcaster tokens also serve role sync, but these sockets are separate
            # from bot-authorized chat sockets and cannot interrupt chat reception.
            return await self._role_token(guild_id, set())

    async def _event_supervisor_loop(self):
        await self.bot.wait_until_red_ready()
        try:
            while not self.closing:
                self.events_wakeup.clear()
                configs = await self.config.all_guilds()
                desired = {}
                for gid, cfg in configs.items():
                    settings = cfg.get("channel_events", {})
                    kinds = tuple(kind for kind in EVENTS if settings.get("types", {}).get(kind, True))
                    guild = self.bot.get_guild(gid)
                    active = (cfg["enabled"] and cfg["broadcaster_id"] and settings.get("enabled") and kinds and guild is not None)
                    if active and await self.bot.cog_disabled_in_guild(self, guild):
                        active = False
                    if active:
                        auth = cfg.get("role_auth", {})
                        signature = (cfg["broadcaster_id"], kinds, settings.get("revision", 0),
                                     auth.get("client_id"), auth.get("user_id"), tuple(sorted(auth.get("scopes", []))))
                        desired[gid] = signature
                    else:
                        self.event_connections[gid] = "Paused or no event types enabled"
                for gid, task in list(self.event_tasks.items()):
                    if desired.get(gid) != self.event_signatures.get(gid) or task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        self.event_tasks.pop(gid, None)
                        self.event_signatures.pop(gid, None)
                for gid, signature in desired.items():
                    if gid not in self.event_tasks:
                        self.event_signatures[gid] = signature
                        self.event_tasks[gid] = asyncio.create_task(self._channel_event_loop(gid, signature[0], signature[1], signature[2]))
                try:
                    await asyncio.wait_for(self.events_wakeup.wait(), timeout=30)
                except asyncio.TimeoutError:
                    pass
        finally:
            for task in self.event_tasks.values():
                task.cancel()
            await asyncio.gather(*self.event_tasks.values(), return_exceptions=True)
            self.event_tasks.clear()
            self.event_signatures.clear()

    async def _channel_event_loop(self, guild_id, broadcaster_id, kinds, revision):
        delay = 2
        while not self.closing:
            try:
                client_id, auth = await self._event_token(guild_id, broadcaster_id)
                self.event_connections[guild_id] = "Connecting"
                await self._listen_channel_events(guild_id, broadcaster_id, kinds, revision, client_id, auth)
                delay = 2
            except asyncio.CancelledError:
                raise
            except BridgeError as exc:
                self.event_connections[guild_id] = str(exc)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError):
                self.event_connections[guild_id] = "Event connection interrupted; retrying"
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def _listen_channel_events(self, guild_id, broadcaster_id, kinds, revision, client_id, auth):
        ws, replacement = None, None
        accepted, issues = {}, []
        try:
            ws = await self.http.ws_connect(SOCKET, autoping=True)
            welcome = await ws.receive_json(timeout=15)
            if welcome["metadata"]["message_type"] != "session_welcome":
                raise BridgeError("Twitch did not send an event-session welcome.")
            session = welcome["payload"]["session"]
            timeout = session.get("keepalive_timeout_seconds") or 10
            for kind, spec in event_specs(broadcaster_id, kinds).items():
                scope = EVENTS[kind][2]
                if scope and scope not in auth.get("scopes", []):
                    issues.append(f"{kind}: broadcaster approval needed")
                    continue
                code, _ = await self._request("POST", API + "eventsub/subscriptions", headers={
                    "Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"]},
                    json=dict(spec, transport={"method": "websocket", "session_id": session["id"]}))
                if code == 202:
                    accepted[kind] = spec
                else:
                    issues.append(f"{kind}: subscription refused (HTTP {code})")
            if not accepted:
                raise BridgeError("No event subscriptions active. " + "; ".join(issues))
            self.event_connections[guild_id] = f"Connected: {len(accepted)}/{len(kinds)} event types" + ("; " + "; ".join(issues) if issues else "")
            while True:
                message = await ws.receive_json(timeout=timeout + 5)
                category = message["metadata"]["message_type"]
                if category == "session_reconnect":
                    url = reconnect_url(message["payload"]["session"]["reconnect_url"])
                    replacement = await self.http.ws_connect(url, autoping=True)
                    ready = await replacement.receive_json(timeout=15)
                    if ready["metadata"]["message_type"] != "session_welcome":
                        raise BridgeError("Twitch event-session reconnect failed.")
                    timeout = ready["payload"]["session"].get("keepalive_timeout_seconds") or timeout
                    await ws.close()
                    ws, replacement = replacement, None
                elif category == "revocation":
                    raise BridgeError("An event subscription was revoked. Rechecking broadcaster approval.")
                elif category == "notification":
                    self._channel_event_notification(guild_id, broadcaster_id, revision, accepted, message)
                await self._event_token(guild_id, broadcaster_id)
        finally:
            if replacement is not None:
                await replacement.close()
            if ws is not None:
                await ws.close()

    def _channel_event_notification(self, guild_id, broadcaster_id, revision, accepted, message):
        payload = message["payload"]
        subscription = payload.get("subscription", {})
        kind = next((kind for kind, spec in accepted.items() if spec["type"] == subscription.get("type")
                     and spec["version"] == subscription.get("version")
                     and all(subscription.get("condition", {}).get(key) == value for key, value in spec["condition"].items())), None)
        if kind is None:
            return
        event = payload["event"]
        destination = event.get("to_broadcaster_user_id") if kind == "raid" else event.get("broadcaster_user_id")
        if destination != broadcaster_id:
            return
        # Bulk gift summaries are announced once, not once per recipient as well.
        if kind == "subscribe" and event.get("is_gift"):
            return
        message_id = message["metadata"].get("message_id")
        if not message_id or not self.event_seen.accept(f"{guild_id}:{subscription['type']}:{message_id}"):
            return
        try:
            self.event_queue.put_nowait((guild_id, broadcaster_id, revision, kind, time.monotonic(), copy.deepcopy(event)))
            self._event_count(guild_id, "queued")
        except asyncio.QueueFull:
            self._event_count(guild_id, "dropped")

    @staticmethod
    def _event_delivery_allowed(cfg, revision, kind, received):
        settings = cfg.get("channel_events", {})
        return (cfg["enabled"] and settings.get("enabled") and settings.get("revision", 0) == revision
                and settings.get("types", {}).get(kind, True) and time.monotonic() - received <= MAX_EVENT_AGE)

    async def _event_usergame(self, kind, template, event):
        if "{usergame}" not in template:
            return ""
        # Never resolve identity for anonymous gifts or cheers, even if present.
        uid = event.get("from_broadcaster_user_id" if kind == "raid" else "user_id")
        if event.get("is_anonymous") or not uid:
            return "Unknown game"
        try:
            client_id, auth = await self._token()
            code, body = await self._request("GET", API + "channels",
                params={"broadcaster_id": str(uid)},
                headers={"Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"]})
            if code == 200 and body.get("data"):
                return body["data"][0].get("game_name") or "Unknown game"
        except (BridgeError, aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError):
            pass
        return "Unknown game"

    async def _event_sender_loop(self):
        while True:
            guild_id, broadcaster_id, revision, kind, received, event = await self.event_queue.get()
            try:
                cfg = await self.config.guild_from_id(guild_id).all()
                if cfg["broadcaster_id"] != broadcaster_id or not self._event_delivery_allowed(cfg, revision, kind, received):
                    self._event_count(guild_id, "dropped")
                    continue
                settings = cfg["channel_events"]
                cooldown = settings.get("cooldowns", {}).get(kind, 0)
                if time.monotonic() < self.event_last_sent.get((guild_id, kind), -86400) + cooldown:
                    self._event_count(guild_id, "dropped")
                    continue
                template = settings.get("messages", {}).get(kind, DEFAULT_MESSAGES[kind])
                game = await self._template_game(guild_id, template)
                usergame = await self._event_usergame(kind, template, event)
                uid = None if event.get("is_anonymous") else event.get("from_broadcaster_user_id" if kind == "raid" else "user_id")
                extended = await self._extra_variables(guild_id, template, twitch_id=uid)
                text = render_event(kind, template, event, cfg["broadcaster"], game, usergame, extended)
                if not text:
                    raise ValueError("The event message rendered as empty text.")
                await self._send_twitch(guild_id, text, expected_broadcaster=broadcaster_id,
                    announcement=settings.get("mode", "chat") == "announcement", event_guard=(revision, kind, received))
                self.event_last_sent[(guild_id, kind)] = time.monotonic()
                self._event_count(guild_id, "sent")
                self.event_deliveries[guild_id] = f"Last {kind} message sent"
            except (BridgeError, ValueError, KeyError, TypeError) as exc:
                self._event_count(guild_id, "dropped")
                self.event_deliveries[guild_id] = str(exc) if isinstance(exc, (BridgeError, ValueError)) else "Invalid event payload or template"
            finally:
                self.event_queue.task_done()

    async def _invalidate_events_locked(self, group):
        settings = await group.channel_events()
        settings["revision"] = settings.get("revision", 0) + 1
        await group.channel_events.set(settings)
        self.events_wakeup.set()

    async def _change_events(self, guild, change):
        async with self.settings_lock:
            group = self.config.guild(guild)
            settings = await group.channel_events()
            change(settings)
            settings["revision"] = settings.get("revision", 0) + 1
            await group.channel_events.set(settings)
        self.events_wakeup.set()

    @staff_only()
    @commands.guild_only()
    @commands.group(name="twitchevents", invoke_without_command=True)
    async def twitchevents(self, ctx):
        """Configure automatic Twitch channel-event messages for this server."""
        await ctx.send_help()

    @twitchevents.command(name="enabled")
    async def events_enabled(self, ctx, enabled: bool):
        """Enable or pause this broadcaster's event messages."""
        cfg = await self.config.guild(ctx.guild).all()
        if enabled and (not cfg["enabled"] or not cfg["broadcaster_id"]):
            await ctx.send("Verify and enable the Twitch connection first.")
            return
        await self._change_events(ctx.guild, lambda data: data.update(enabled=enabled))
        await ctx.send("Channel events enabled. Check twitchevents status for authorization or subscription issues." if enabled else "Channel events paused.")

    @twitchevents.command(name="event")
    async def event_toggle(self, ctx, kind: str, enabled: bool):
        """Enable/disable follow, subscribe, resub, gift, cheer, or raid."""
        try:
            kind = event_kind(kind)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        await self._change_events(ctx.guild, lambda data: data.setdefault("types", {}).__setitem__(kind, enabled))
        await ctx.send(f"{kind} event messages {'enabled' if enabled else 'disabled'}.")

    @twitchevents.command(name="message")
    async def event_message(self, ctx, kind: str, *, message: str):
        """Set the message for one event type; preview it before enabling."""
        try:
            kind = event_kind(kind)
            message = validate_event_template(kind, message)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        await self._change_events(ctx.guild, lambda data: data.setdefault("messages", {}).__setitem__(kind, message))
        await ctx.send(f"{kind} message saved.")

    @twitchevents.command(name="mode")
    async def event_mode(self, ctx, mode: str):
        """Choose regular chat messages or native announcement banners."""
        mode = mode.lower()
        if mode not in ("chat", "announcement"):
            await ctx.send("Choose chat or announcement.")
            return
        await self._change_events(ctx.guild, lambda data: data.update(mode=mode))
        await ctx.send(f"Event message mode set to {mode}.")

    @twitchevents.command(name="cooldown")
    async def event_cooldown(self, ctx, kind: str, seconds: int):
        """Set a per-event message cooldown of 0-86400 seconds."""
        try:
            kind = event_kind(kind)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        if not 0 <= seconds <= 86400:
            await ctx.send("Choose 0-86400 seconds.")
            return
        await self._change_events(ctx.guild, lambda data: data.setdefault("cooldowns", {}).__setitem__(kind, seconds))
        await ctx.send("Event cooldown saved.")

    @twitchevents.command(name="authorize")
    async def event_authorize(self, ctx):
        """Approve this broadcaster's complete permission bundle."""
        expected = await self.config.guild(ctx.guild).broadcaster()
        if not expected:
            await ctx.send("Select a broadcaster first.")
            return
        await self._start_auth(ctx, ctx.guild.id, expected)

    @twitchevents.command(name="preview")
    async def event_preview(self, ctx, kind: str):
        """Preview example text here without posting anything in Twitch."""
        try:
            kind = event_kind(kind)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        cfg = await self.config.guild(ctx.guild).all()
        example = {"user_name": "ExampleViewer", "user_login": "exampleviewer", "tier": "1000",
                   "cumulative_months": 12, "total": 5, "bits": 100, "viewers": 20,
                   "from_broadcaster_user_name": "ExampleRaider", "from_broadcaster_user_login": "exampleraider",
                   "message": {"text": "Great stream!"} if kind == "resub" else "Great stream!"}
        template = cfg.get("channel_events", {}).get("messages", {}).get(kind, DEFAULT_MESSAGES[kind])
        game = await self._template_game(ctx.guild.id, template)
        try:
            extended = await self._extra_variables(ctx.guild.id, template)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        text = render_event(kind, template, example, cfg["broadcaster"] or "your channel", game, "Example game", extended)
        await ctx.send(f"Preview ({kind}): {text}", allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)

    @twitchevents.command(name="status")
    async def event_status(self, ctx):
        cfg = await self.config.guild(ctx.guild).all()
        settings = cfg.get("channel_events", {})
        kinds = ", ".join(kind for kind in EVENTS if settings.get("types", {}).get(kind, True)) or "none"
        counts = self.event_counts.get(ctx.guild.id, {"queued": 0, "sent": 0, "dropped": 0})
        await ctx.send(f"Enabled: {settings.get('enabled', False)} | Mode: {settings.get('mode', 'chat')}\n"
            f"Event types: {kinds}\nConnection: {self.event_connections.get(ctx.guild.id, 'Not started')}\n"
            f"Delivery: {self.event_deliveries.get(ctx.guild.id, 'No event messages sent')}\n"
            f"Since load: queued {counts['queued']}, sent {counts['sent']}, dropped {counts['dropped']}")
