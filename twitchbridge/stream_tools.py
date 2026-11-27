"""Runtime for scheduled messages, first-chat responses and chat triggers."""
import asyncio
import math
import time
from datetime import datetime
import discord

from .ads import AdsMixin, AD_DEFAULTS
from .errors import BridgeError
from .permissions import discord_access
from .response_tools import ResponseToolsMixin, word_matches
from .policy import parse_command, twitch_level, chat_text
from .tool_commands import ToolCommandsMixin

FIRST_DEFAULTS = {"enabled": False, "mode": "ever", "everyone": True, "message": "Welcome {user}!", "users": {}}
STREAK_DEFAULTS = {"enabled": False, "break_on_miss": True, "greeting_enabled": False,
                   "message": "Welcome back, {user}! Your stream streak is {streak}!"}


class StreamToolsMixin(ToolCommandsMixin, ResponseToolsMixin, AdsMixin):
    def _init_stream_tools(self):
        self.tool_locks, self.stream_locks, self.stream_cache = {}, {}, {}
        self.tool_monitor = self.tool_ticker = self.tool_sender = self.tool_chat_worker = None
        self.tools_wakeup = asyncio.Event()
        self.tool_configs = {}
        self.tool_queue = asyncio.PriorityQueue(maxsize=200)
        self.tool_chat_queue = asyncio.Queue(maxsize=500)
        self.tool_serial = 0
        self.tool_status, self.tool_dropped = {}, 0
        self.timer_due, self.trigger_due, self.presence_seen = {}, {}, {}
        self.stream_timer_claimed = set()
        self.ad_cache, self.ad_locks, self.ad_retry_after = {}, {}, {}
        self.ad_pending, self.ad_claimed = set(), set()
        self.ad_pause_until = {}

    async def _invalidate_tools_locked(self, group):
        await group.automation_revision.set((await group.automation_revision()) + 1)
        self.tools_wakeup.set()

    async def _edit_tools(self, guild, field, change):
        async with self.settings_lock:
            async with self._tool_lock(guild.id):
                group = self.config.guild(guild)
                data = await getattr(group, field)()
                change(data)
                await getattr(group, field).set(data)
                await self._invalidate_tools_locked(group)

    def _enqueue_tool(self, gid, bid, kind, name, template, *, priority=3, **context):
        self.tool_serial += 1
        payload = dict(context, guild_id=gid, broadcaster_id=bid, kind=kind, name=name, template=template, received=time.monotonic())
        try:
            self.tool_queue.put_nowait((priority, self.tool_serial, payload))
        except asyncio.QueueFull:
            self.tool_dropped += 1

    def _tool_guard_allowed(self, cfg, payload):
        if (not cfg["enabled"] or cfg["broadcaster_id"] != payload["broadcaster_id"]
                or cfg.get("automation_revision", 0) != payload.get("revision", 0)
                or time.monotonic() - payload["received"] > 60):
            return False
        kind = payload["kind"]
        if kind == "ad":
            schedule = self.ad_cache.get(payload["guild_id"], {})
            return (cfg.get("ad_settings", {}).get("enabled") and payload["guild_id"] not in self.ad_pending
                    and time.time() >= cfg.get("ad_warning_pause_until", 0)
                    and schedule.get("next_ad_at") == payload["ad_at"] and time.time() < payload["ad_at"]
                    and time.monotonic() - schedule.get("fetched", 0) < 45)
        if kind == "stream_timer":
            timer = cfg.get("timers", {}).get(payload["name"], {})
            if not timer.get("enabled") or not timer.get("per_stream", False):
                return False
        if kind == "timer" and not cfg.get("timers", {}).get(payload["name"], {}).get("enabled"):
            return False
        if kind == "trigger" and not cfg.get("chat_triggers", {}).get(payload["name"], {}).get("enabled"):
            return False
        if kind == "greeting" and not cfg.get("first_message", {}).get("enabled"):
            return False
        if kind == "streak_greeting":
            settings = cfg.get("streak_settings", {})
            if not settings.get("enabled") or not settings.get("greeting_enabled", False):
                return False
        if payload.get("session"):
            info = self.stream_cache.get(payload["guild_id"], {})
            return (info.get("broadcaster_id") == payload["broadcaster_id"] and info.get("stream") is not None and info["stream"]["id"] == payload["session"]
                    and time.monotonic() - info.get("fetched", 0) < 60)
        return True

    async def _tool_send_loop(self):
        while True:
            _, _, item = await self.tool_queue.get()
            gid = item["guild_id"]
            try:
                cfg = await self.config.guild_from_id(gid).all()
                if not self._tool_guard_allowed(cfg, item):
                    self.tool_dropped += 1
                    continue
                if item["kind"] == "owner_greeting" and not await self._owner_greeting_allowed(item):
                    self.tool_dropped += 1
                    continue
                extra = dict(item.get("extra", {}))
                if item["kind"] == "ad":
                    schedule = await self._refresh_ads(gid, expected=item["broadcaster_id"])
                    if schedule.get("next_ad_at") != item["ad_at"]:
                        self.tool_dropped += 1
                        continue
                    if not await self._reserve_ad_notice(gid, item["ad_at"], item["lead"]):
                        continue
                    extra.update(ad_seconds=max(1, math.ceil(item["ad_at"] - time.time())), ad_duration=self.ad_cache[gid].get("duration", 0))
                text = await self._render_shared(gid, item["template"], user=item.get("user", ""), args=item.get("args", ""),
                    source=item["name"], twitch_id=item.get("twitch_id"), login=item.get("login"), extra=extra, truncate=True)
                await self._send_twitch(gid, text, expected_broadcaster=item["broadcaster_id"],
                    announcement=item["kind"] == "ad" and cfg["ad_settings"].get("mode") == "announcement", automation_guard=item)
                self.tool_status[gid] = f"Last {item['kind']} message sent"
            except (BridgeError, ValueError, KeyError, TypeError) as exc:
                self.tool_dropped += 1
                self.tool_status[gid] = str(exc) if isinstance(exc, (BridgeError, ValueError)) else "Automation data is unavailable"
            finally:
                self.tool_queue.task_done()

    async def _monitor_tools_guild(self, gid, cfg):
        try:
            needed = (any(t.get("enabled") for t in cfg.get("timers", {}).values()) or cfg.get("first_message", {}).get("enabled")
                      or cfg.get("streak_settings", {}).get("enabled") or cfg.get("ad_settings", {}).get("enabled"))
            if needed:
                info = await self._stream_info(gid)
                if info["stream"] and (cfg.get("first_message", {}).get("enabled") or cfg.get("streak_settings", {}).get("enabled")):
                    await self._observe_stream(gid, info["stream"])
                if info["stream"] and cfg.get("ad_settings", {}).get("enabled"):
                    await self._refresh_ads(gid, expected=cfg["broadcaster_id"])
                elif not info["stream"]:
                    self.ad_cache.pop(gid, None)
        except (BridgeError, ValueError, KeyError, TypeError) as exc:
            self.tool_status[gid] = str(exc) if isinstance(exc, (BridgeError, ValueError)) else "Stream information unavailable"

    async def _tool_monitor_loop(self):
        await self.bot.wait_until_red_ready()
        while not self.closing:
            self.tools_wakeup.clear()
            active = {}
            for gid, cfg in (await self.config.all_guilds()).items():
                guild = self.bot.get_guild(gid)
                if cfg["enabled"] and cfg["broadcaster_id"] and guild and not await self.bot.cog_disabled_in_guild(self, guild):
                    active[gid] = cfg
            self.tool_configs = active
            await asyncio.gather(*(self._monitor_tools_guild(gid, cfg) for gid, cfg in active.items()))
            try:
                await asyncio.wait_for(self.tools_wakeup.wait(), timeout=15)
            except asyncio.TimeoutError:
                pass

    async def _claim_stream_timer(self, gid, bid, session, name, revision):
        async with self._tool_lock(gid):
            group = self.config.guild_from_id(gid)
            cfg = await group.all()
            timer = cfg.get("timers", {}).get(name, {})
            if (not cfg["enabled"] or cfg["broadcaster_id"] != bid
                    or cfg.get("automation_revision", 0) != revision
                    or not timer.get("enabled") or not timer.get("per_stream", False)):
                return None
            notices = cfg.get("stream_timer_notices", {})
            sessions = notices.setdefault(bid, {})
            names = sessions.setdefault(session, [])
            if name in names:
                return False
            names.append(name)
            while len(sessions) > 10:
                sessions.pop(next(iter(sessions)))
            while len(notices) > 10:
                notices.pop(next(iter(notices)))
            await group.stream_timer_notices.set(notices)
            return True

    async def _tick_tools(self):
        now = time.monotonic()
        for gid, cfg in list(self.tool_configs.items()):
            bid, rev = cfg["broadcaster_id"], cfg.get("automation_revision", 0)
            info = self.stream_cache.get(gid, {})
            stream = info.get("stream") if info.get("broadcaster_id") == bid and now - info.get("fetched", 0) < 60 else None
            for name, timer in cfg.get("timers", {}).items():
                if not timer.get("enabled") or (timer.get("live_only", True) and stream is None):
                    continue
                if timer.get("per_stream", False):
                    if stream is None:
                        continue
                    claim = (gid, bid, stream["id"], name)
                    if claim in self.stream_timer_claimed:
                        continue
                    try:
                        started = datetime.fromisoformat(stream["started_at"].replace("Z", "+00:00"))
                        if started.tzinfo is None:
                            continue
                        due_at = started.timestamp() + timer["seconds"]
                    except (KeyError, ValueError, TypeError):
                        continue
                    lateness = time.time() - due_at
                    if lateness < 0 or lateness > 60:
                        continue
                    claimed = await self._claim_stream_timer(gid, bid, stream["id"], name, rev)
                    if claimed is not None:
                        self.stream_timer_claimed.add(claim)
                    if claimed:
                        self._enqueue_tool(gid, bid, "stream_timer", name, timer["message"],
                                           session=stream["id"], revision=rev)
                    continue
                session = stream["id"] if timer.get("live_only", True) else None
                key = (gid, bid, rev, name, session)
                due = self.timer_due.setdefault(key, now + timer["seconds"])
                if now >= due:
                    self.timer_due[key] = now + timer["seconds"]
                    self._enqueue_tool(gid, bid, "timer", name, timer["message"], session=session, revision=rev)
            schedule = self.ad_cache.get(gid, {})
            at = schedule.get("next_ad_at", 0)
            if cfg.get("ad_settings", {}).get("enabled") and stream and schedule.get("broadcaster_id") == bid and now - schedule.get("fetched", 0) < 45 and time.time() >= max(cfg.get("ad_warning_pause_until", 0), self.ad_pause_until.get(gid, 0)):
                remaining = at - time.time()
                candidates = [lead for lead in cfg["ad_settings"].get("leads", [300])
                              if 0 < remaining <= lead and (gid, bid, at, lead) not in self.ad_claimed]
                if candidates:
                    # On late startup, send one timely warning rather than all missed thresholds.
                    lead = min(candidates)
                    self.ad_claimed.update((gid, bid, at, value) for value in candidates)
                    self._enqueue_tool(gid, bid, "ad", "ads", cfg["ad_settings"].get("message", AD_DEFAULTS["message"]),
                        priority=0, session=stream["id"], revision=rev, ad_at=at, lead=lead)
        if len(self.stream_timer_claimed) > 10000:
            active = {(gid, info.get("broadcaster_id"), info["stream"]["id"])
                      for gid, info in self.stream_cache.items() if info.get("stream")}
            self.stream_timer_claimed = {key for key in self.stream_timer_claimed if key[:3] in active}
        if len(self.timer_due) > 10000:
            self.timer_due = {k: due for k, due in self.timer_due.items() if due > now - 3600}
        if len(self.ad_claimed) > 10000:
            self.ad_claimed = {k for k in self.ad_claimed if k[2] > time.time() - 3600}

    async def _tool_tick_loop(self):
        while True:
            await self._tick_tools()
            await asyncio.sleep(0.25)

    async def _tool_chat_loop(self):
        while True:
            gid, bid, event = await self.tool_chat_queue.get()
            try:
                cfg = await self.config.guild_from_id(gid).all()
                if not cfg["enabled"] or cfg["broadcaster_id"] != bid:
                    continue
                await self._record_presence(gid, bid, event)
                text = event.get("message", {}).get("text", "")
                if parse_command(text, cfg.get("command_prefix", "!")):
                    continue
                for name, trigger in cfg.get("chat_triggers", {}).items():
                    key, now = (gid, name), time.monotonic()
                    if trigger.get("enabled") and now >= self.trigger_due.get(key, 0) and word_matches(trigger["word"], text):
                        self.trigger_due[key] = now + trigger.get("cooldown", 30)
                        self._enqueue_tool(gid, bid, "trigger", name, trigger["message"], priority=2,
                            user=event.get("chatter_user_name", "Viewer"), args=text, twitch_id=event["chatter_user_id"],
                            login=event.get("chatter_user_login"), revision=cfg.get("automation_revision", 0))
            except (BridgeError, ValueError, KeyError, TypeError) as exc:
                self.tool_status[gid] = str(exc) if isinstance(exc, (BridgeError, ValueError)) else "Chat automation unavailable"
            finally:
                self.tool_chat_queue.task_done()

    async def _todo_action(self, gid, action, text, level):
        async with self._tool_lock(gid):
            group = self.config.guild_from_id(gid)
            cfg = await group.all()
            needed = {"everyone": 1, "moderator": 1, "broadcaster": 2}[cfg.get("todo_permission", "moderator")]
            items = cfg.get("todo_items", [])
            if level < 1:
                raise BridgeError("Only moderators and the broadcaster can use the to-do list.")
            if action == "view":
                return [f"{i}. {item}" for i, item in enumerate(items, 1)] or ["The to-do list is empty."]
            if level < needed:
                raise BridgeError("You do not have permission to edit this to-do list.")
            if action == "add":
                text = chat_text(text)
                if not text or len(text) > 250 or len(items) >= 100:
                    raise ValueError("Use 1-250 characters; the list can hold 100 items.")
                items.append(text)
                reply = f"Added to-do #{len(items)}: {text}"
            elif action in ("del", "delete"):
                try:
                    index = int(text)
                except ValueError:
                    raise ValueError("Use the number shown by todo view.") from None
                if not 1 <= index <= len(items):
                    raise ValueError("That to-do number does not exist.")
                reply = f"Deleted to-do #{index}: {items.pop(index - 1)}"
            else:
                raise ValueError("Use todo add <text>, todo view, or todo del <number>.")
            await group.todo_items.set(items)
            return [reply]

    async def _discord_level(self, ctx):
        if await self.bot.is_owner(ctx.author) or ctx.author.id == ctx.guild.owner_id:
            return 2
        return 1 if await discord_access(self.bot, ctx.guild, ctx.author) else 0

    async def _tool_twitch_command(self, gid, bid, event, name, args):
        if name not in ("todo", "ads", "streak"):
            return False
        cfg = await self.config.guild_from_id(gid).all()
        if not cfg["enabled"] or cfg["broadcaster_id"] != bid:
            return True
        level = twitch_level(event)
        if name in ("todo", "ads") and level < 1:
            raise BridgeError("Only moderators and the broadcaster can use this command.")
        if name == "todo":
            parts = args.split(maxsplit=1)
            lines = await self._todo_action(gid, parts[0].lower() if parts else "view", parts[1] if len(parts) > 1 else "", level)
        elif name == "streak":
            await self._record_presence(gid, bid, event)
            data = (await self.config.guild_from_id(gid).viewer_data()).get(bid, {}).get(event["chatter_user_id"], {})
            settings = cfg.get("streak_settings", {})
            template = settings.get("message", STREAK_DEFAULTS["message"])
            lines = [await self._render_shared(gid, template, user=event.get("chatter_user_name", "Viewer"),
                source="streak", twitch_id=event["chatter_user_id"], login=event.get("chatter_user_login"),
                extra={"streak": data.get("streak", 0)}, truncate=True)]
        else:
            parts = args.split(maxsplit=1)
            action = parts[0].lower() if parts else "status"
            if action in ("run", "snooze"):
                lines = [await self._ad_action(gid, action, int(parts[1]) if len(parts) > 1 else 60, expected=bid)]
            else:
                schedule = await self._refresh_ads(gid, expected=bid)
                remaining = max(0, math.ceil(schedule.get("next_ad_at", 0) - time.time()))
                lines = [f"Next ad in {remaining} seconds. Snoozes available: {schedule.get('snooze_count', 0)}."]
        for line in lines:
            await self._send_twitch(gid, line, expected_broadcaster=bid)
        return True
