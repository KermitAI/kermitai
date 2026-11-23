"""Shared variables, counters, live stream information, and durable attendance."""
import asyncio
import re
import time
from datetime import datetime, timezone

from .errors import BridgeError
from .policy import chat_text

API = "https://api.twitch.tv/helix/"
COUNTER = re.compile(r"\{counter(?::([a-z0-9_]{1,32}))?\}")
VARIABLE = re.compile(r"\{([a-z_]+)\}")
STREAM_FIELDS = {"uptime", "title", "game", "viewers", "live"}


def tool_name(value):
    value = value.lower()
    if not re.fullmatch(r"[a-z0-9_]{1,32}", value):
        raise ValueError("Use 1-32 letters, numbers or underscores for the name.")
    return value


def word_matches(word, text):
    return bool(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text, re.IGNORECASE))


def duration_text(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m {seconds % 60}s"


def apply_response(template, values, counters, source, counter_keys=None):
    keys = {match[1] or source for match in COUNTER.finditer(template)}
    counter_keys = counter_keys or {}
    keys = {counter_keys.get(key, key) for key in keys}
    updated = dict(counters)
    for key in keys:
        updated[key] = updated.get(key, 0) + 1
    # Single-pass substitution prevents viewer input from injecting new variables.
    pattern = re.compile(r"\{counter(?::([a-z0-9_]{1,32}))?\}|\{([a-z_]+)\}")
    def replace(match):
        if match[0].startswith("{counter") and not match[2]:
            return str(updated[counter_keys.get(match[1] or source, match[1] or source)])
        return str(values.get(match[2], match[0]))
    return pattern.sub(replace, template), updated


def attendance(data, session_number, break_on_miss):
    if data.get("last_session") == session_number:
        return data.get("streak", 0)
    previous = data.get("streak", 0)
    data["streak"] = previous + 1 if not break_on_miss or data.get("last_session") == session_number - 1 else 1
    data["last_session"] = session_number
    return data["streak"]


class ResponseToolsMixin:
    def _tool_lock(self, guild_id):
        if not hasattr(self, "tool_locks"):
            self.tool_locks = {}
        return self.tool_locks.setdefault(guild_id, asyncio.Lock())

    async def _stream_info(self, guild_id, force=False):
        async with self.stream_locks.setdefault(guild_id, asyncio.Lock()):
            cfg = await self.config.guild_from_id(guild_id).all()
            bid = cfg["broadcaster_id"]
            cached = self.stream_cache.get(guild_id)
            if cached and cached["broadcaster_id"] == bid and not force and time.monotonic() - cached["fetched"] < 30:
                return cached
            if not bid:
                raise BridgeError("No Twitch broadcaster is configured.")
            client_id, auth = await self._token()
            if cfg["broadcaster_auth"].get("client_id") != client_id:
                raise BridgeError("This broadcaster needs authorization for the configured Twitch application.")
            headers = {"Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"]}
            code, body = await self._request("GET", API + "streams", headers=headers, params={"user_id": bid})
            if code != 200 or not isinstance(body.get("data"), list):
                raise BridgeError("Could not read stream information from Twitch.")
            live = body["data"][0] if body["data"] else None
            info = {"broadcaster_id": bid, "fetched": time.monotonic(), "stream": live}
            self.stream_cache[guild_id] = info
            return info

    async def _stream_values(self, guild_id):
        info = await self._stream_info(guild_id)
        stream = info["stream"]
        if stream:
            started = datetime.fromisoformat(stream["started_at"].replace("Z", "+00:00"))
            return {"live": "Live", "title": stream.get("title", ""), "game": stream.get("game_name", ""),
                    "viewers": stream.get("viewer_count", 0), "uptime": duration_text(datetime.now(timezone.utc).timestamp() - started.timestamp())}
        # Twitch's channel endpoint supplies the last configured title/game offline.
        if "offline_values" in info:
            return info["offline_values"]
        client_id, auth = await self._token()
        code, body = await self._request("GET", API + "channels", params={"broadcaster_id": info["broadcaster_id"]},
            headers={"Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"]})
        if code != 200 or not body.get("data"):
            raise BridgeError("Could not read channel title and game from Twitch.")
        channel = body["data"][0]
        values = {"live": "Offline", "uptime": "Offline", "title": channel.get("title", ""),
                  "game": channel.get("game_name", ""), "viewers": 0}
        info["offline_values"] = values
        return values

    async def _template_game(self, guild_id, template):
        """Fetch only when requested; optional enrichment must not lose an alert."""
        if "{game}" not in template:
            return ""
        try:
            return (await self._stream_values(guild_id)).get("game") or "Unknown game"
        except BridgeError:
            return "Unknown game"

    async def _counter_context(self, guild_id, names):
        cfg = await self.config.guild_from_id(guild_id).all()
        scoped = set(names) & set(cfg.get("game_counters", []))
        if not scoped:
            return {}, "", cfg["broadcaster_id"]
        # A fresh lookup prevents a recent category change using the previous game's total.
        info = await self._stream_info(guild_id, force=True)
        stream = info["stream"]
        if not stream or not stream.get("game_id"):
            raise BridgeError("Game counters require a live stream with a Twitch category selected.")
        bid = info["broadcaster_id"]
        keys = {name: f"game:{bid}:{stream['game_id']}:{name}" for name in scoped}
        return keys, stream.get("game_name", stream["game_id"]), bid

    async def _render_shared(self, guild_id, template, *, user="", args="", source="response", twitch_id=None, login=None, extra=None, truncate=False):
        values = {"user": user, "args": args, "url": "https://twitch.tv/" + login if login and re.fullmatch(r"[a-zA-Z0-9_]{1,25}", login) else "", "streak": 0}
        requested = set(VARIABLE.findall(template))
        if requested & STREAM_FIELDS:
            values.update(await self._stream_values(guild_id))
        names = {match[1] or source for match in COUNTER.finditer(template)}
        counter_keys, game, bid = await self._counter_context(guild_id, names)
        async with self._tool_lock(guild_id):
            group = self.config.guild_from_id(guild_id)
            cfg = await group.all()
            if cfg["broadcaster_id"] != bid or (names & set(cfg.get("game_counters", []))) != set(counter_keys):
                raise BridgeError("Counter settings changed; please try again.")
            if game:
                values["game"] = game
            values["channel"] = cfg["broadcaster"]
            if twitch_id and "streak" in requested:
                viewer = cfg.get("viewer_data", {}).get(cfg["broadcaster_id"], {}).get(str(twitch_id), {})
                values["streak"] = viewer.get("streak", 0)
            values.update(extra or {})
            counters = cfg.get("response_counters", {}) if COUNTER.search(template) else {}
            text, updated = apply_response(template, values, counters, source, counter_keys)
            if truncate:
                text = " ".join(text.split())[:500]
            text = chat_text(text)
            if updated != counters:
                await group.response_counters.set(updated)
            return text

    async def _observe_stream(self, guild_id, stream):
        async with self._tool_lock(guild_id):
            group = self.config.guild_from_id(guild_id)
            states = await group.stream_session()
            bid = (await group.all())["broadcaster_id"]
            state = states.get(bid, {})
            started = stream.get("started_at", "")
            if state.get("id") != stream["id"]:
                if started and state.get("started_at") and started < state["started_at"]:
                    return state
                state = {"id": stream["id"], "number": state.get("number", 0) + 1, "started_at": started}
                states[bid] = state
                await group.stream_session.set(states)
            return state

    async def _record_presence(self, guild_id, broadcaster_id, event):
        cfg = await self.config.guild_from_id(guild_id).all()
        first = cfg.get("first_message", {})
        streak = cfg.get("streak_settings", {})
        if not cfg["enabled"] or cfg["broadcaster_id"] != broadcaster_id or not (first.get("enabled") or streak.get("enabled")):
            return
        info = await self._stream_info(guild_id)
        if not info["stream"] or info["broadcaster_id"] != broadcaster_id:
            return
        stream = info["stream"]
        session = await self._observe_stream(guild_id, stream)
        uid = event["chatter_user_id"]
        key = (guild_id, broadcaster_id, stream["id"], uid, cfg.get("automation_revision", 0))
        if key in self.presence_seen:
            return
        template = None
        async with self._tool_lock(guild_id):
            group = self.config.guild_from_id(guild_id)
            latest = await group.all()
            if latest["broadcaster_id"] != broadcaster_id or not latest["enabled"] or latest.get("automation_revision", 0) != cfg.get("automation_revision", 0):
                return
            viewers = latest.get("viewer_data", {})
            data = viewers.setdefault(broadcaster_id, {}).setdefault(uid, {})
            if streak.get("enabled"):
                attendance(data, session["number"], streak.get("break_on_miss", True))
            if first.get("enabled"):
                eligible = not data.get("greeted") if first.get("mode", "ever") == "ever" else data.get("greeted_stream") != stream["id"]
                template = first.get("users", {}).get(uid)
                if template is None and first.get("everyone", True):
                    template = first.get("message", "Welcome {user}!")
                if eligible and template:
                    data["greeted"] = True
                    data["greeted_stream"] = stream["id"]
                else:
                    template = None
            await group.viewer_data.set(viewers)
            self.presence_seen[key] = None
            if len(self.presence_seen) > 20000:
                self.presence_seen.pop(next(iter(self.presence_seen)))
        if template:
            self._enqueue_tool(guild_id, broadcaster_id, "greeting", "firstmessage", template,
                user=event.get("chatter_user_name", "Viewer"), args=event.get("message", {}).get("text", ""), twitch_id=uid, login=event.get("chatter_user_login"),
                session=stream["id"], revision=cfg.get("automation_revision", 0), priority=1)

    async def _forget_tool_viewer(self, guild_id, twitch_id):
        async with self._tool_lock(guild_id):
            group = self.config.guild_from_id(guild_id)
            viewers = await group.viewer_data()
            for data in viewers.values():
                data.pop(str(twitch_id), None)
            await group.viewer_data.set(viewers)
            first = await group.first_message()
            first.setdefault("users", {}).pop(str(twitch_id), None)
            await group.first_message.set(first)
            self.presence_seen = {key: value for key, value in self.presence_seen.items() if not (key[0] == guild_id and key[3] == str(twitch_id))}
