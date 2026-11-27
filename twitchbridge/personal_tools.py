"""Owner arrival greetings and bounded, in-memory Twitch countdowns."""
import asyncio
import re
import time
import uuid

import discord
from redbot.core import commands
from .errors import BridgeError
from .permissions import staff_only
from .policy import chat_text, template_text, twitch_level

OWNER_GREETING = {"enabled": False, "message": "My owner {user} is here! Welcome back!"}
COUNTDOWN_DEFAULTS = {"enabled": True, "permission": "everyone"}


def countdown_seconds(value):
    match = re.fullmatch(r"([1-9][0-9]{0,5})([smh])", value.lower())
    if not match:
        raise ValueError("Use a duration such as 30s, 5m or 1h.")
    seconds = int(match[1]) * {"s": 1, "m": 60, "h": 3600}[match[2]]
    if seconds > 86400:
        raise ValueError("Countdowns can last at most 24 hours.")
    return seconds


class PersonalToolsMixin:
    def _init_personal_tools(self):
        self.pending_countdowns = {}

    async def _owner_greeting_allowed(self, payload):
        settings = {**OWNER_GREETING, **await self.config.owner_greeting()}
        owner = await self.config.owner_twitch()
        return (settings["enabled"] and owner.get("user_id") == payload.get("twitch_id")
                and settings["message"] == payload.get("template"))

    async def _record_owner_greeting(self, guild_id, broadcaster_id, event):
        settings = {**OWNER_GREETING, **await self.config.owner_greeting()}
        if not settings["enabled"]:
            return
        owner = await self.config.owner_twitch()
        uid = event.get("chatter_user_id")
        if not uid or uid != owner.get("user_id"):
            return
        info = await self._stream_info(guild_id)
        if info["broadcaster_id"] != broadcaster_id or not info["stream"]:
            return
        stream = info["stream"]
        async with self._tool_lock(guild_id):
            group = self.config.guild_from_id(guild_id)
            cfg = await group.all()
            if not cfg["enabled"] or cfg["broadcaster_id"] != broadcaster_id:
                return
            viewers = cfg.get("viewer_data", {})
            data = viewers.setdefault(broadcaster_id, {}).setdefault(uid, {})
            if data.get("owner_greeted_stream") == stream["id"]:
                return
            data["owner_greeted_stream"] = stream["id"]
            await group.viewer_data.set(viewers)
        self._enqueue_tool(guild_id, broadcaster_id, "owner_greeting", "ownergreeting", settings["message"],
            user=event.get("chatter_user_name", "Owner"), twitch_id=uid, login=event.get("chatter_user_login"),
            args=event.get("message", {}).get("text", ""), session=stream["id"],
            revision=cfg.get("automation_revision", 0), priority=0)

    @staff_only()
    @commands.guild_only()
    @commands.group(name="twitchcountdown", invoke_without_command=True)
    async def twitchcountdown(self, ctx):
        """Configure one-shot Twitch !timer countdowns, separate from recurring timers."""
        await ctx.send_help()

    async def _set_countdown(self, ctx, **updates):
        async with self.settings_lock:
            group = self.config.guild(ctx.guild)
            cfg = await group.all()
            settings = {**COUNTDOWN_DEFAULTS, **cfg.get("countdown_settings", {})}
            settings.update(updates)
            await group.countdown_settings.set(settings)
            if updates.get("enabled") is False:
                for key, item in list(self.pending_countdowns.items()):
                    if key[0] == ctx.guild.id:
                        item["task"].cancel()
                        self.pending_countdowns.pop(key, None)
        await ctx.send("Twitch countdown settings saved.")

    @twitchcountdown.command(name="enabled")
    async def countdown_enabled(self, ctx, enabled: bool):
        await self._set_countdown(ctx, enabled=enabled)

    @twitchcountdown.command(name="permission")
    async def countdown_permission(self, ctx, permission: str):
        permission = permission.lower()
        if permission not in ("everyone", "moderator", "broadcaster"):
            await ctx.send("Choose everyone, moderator, or broadcaster.")
            return
        await self._set_countdown(ctx, permission=permission)

    @twitchcountdown.command(name="status")
    async def countdown_status(self, ctx):
        cfg = await self.config.guild(ctx.guild).all()
        settings = {**COUNTDOWN_DEFAULTS, **cfg.get("countdown_settings", {})}
        count = sum(key[0] == ctx.guild.id for key in self.pending_countdowns)
        await ctx.send(f"Countdowns enabled: {settings['enabled']} | Permission: {settings['permission']} | Pending: {count}/20. Pending countdowns clear on bot restart/cog reload.")

    async def _run_countdown(self, key, item):
        try:
            await asyncio.sleep(max(0, item["due"] - time.monotonic()))
            cfg = await self.config.guild_from_id(key[0]).all()
            if not cfg["enabled"] or cfg["broadcaster_id"] != item["broadcaster_id"]:
                return
            if not cfg.get("countdown_settings", {}).get("enabled", True):
                return
            guild = self.bot.get_guild(key[0])
            if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
                return
            await self._send_twitch(key[0], item["text"], expected_broadcaster=item["broadcaster_id"], countdown_guard=item)
        except (BridgeError, ValueError) as exc:
            self.command_status = "Countdown delivery failed: " + str(exc)
        finally:
            if self.pending_countdowns.get(key) is item:
                self.pending_countdowns.pop(key, None)

    async def _countdown_command(self, guild_id, broadcaster_id, event, args):
        cfg = await self.config.guild_from_id(guild_id).all()
        if not cfg["enabled"] or cfg["broadcaster_id"] != broadcaster_id:
            raise BridgeError("The Twitch connection is paused or the broadcaster changed.")
        settings = {**COUNTDOWN_DEFAULTS, **cfg.get("countdown_settings", {})}
        if not settings["enabled"]:
            raise BridgeError("Countdown timers are disabled on this channel.")
        level = twitch_level(event)
        if level < {"everyone": 0, "moderator": 1, "broadcaster": 2}[settings["permission"]]:
            raise BridgeError("You do not have permission to use countdown timers here.")
        uid = event.get("chatter_user_id")
        if not uid:
            raise BridgeError("Your Twitch identity could not be determined.")
        parts = args.split(maxsplit=1)
        if not parts:
            return "Use !timer 30s <text>, !timer list, or !timer cancel <id>."
        if parts[0].lower() in ("list", "cancel"):
            owner = await self.config.owner_twitch()
            manage = level >= 1 or uid == owner.get("user_id")
            if parts[0].lower() == "list":
                entries = [f"{key[1]}: {max(0, int(item['due'] - time.monotonic()))}s"
                    for key, item in self.pending_countdowns.items() if key[0] == guild_id and (manage or item["user_id"] == uid)]
                return ("Timers: " + "; ".join(entries))[:500] if entries else "No pending timers."
            key = (guild_id, parts[1].strip() if len(parts) > 1 else "")
            item = self.pending_countdowns.get(key)
            if item is None:
                raise ValueError("Timer not found. Use !timer list.")
            if not manage and item["user_id"] != uid:
                raise BridgeError("You can only cancel your own countdowns.")
            item["task"].cancel()
            self.pending_countdowns.pop(key, None)
            return "Timer cancelled."
        seconds = countdown_seconds(parts[0])
        text = chat_text(parts[1] if len(parts) > 1 else "")
        if len(self.pending_countdowns) >= 200 or sum(k[0] == guild_id for k in self.pending_countdowns) >= 20:
            raise BridgeError("The pending timer limit has been reached.")
        if sum(k[0] == guild_id and i["user_id"] == uid for k, i in self.pending_countdowns.items()) >= 3:
            raise BridgeError("You can have at most three pending timers per channel.")
        cooldown_key = (guild_id, "countdown:" + uid)
        if time.monotonic() < self.cooldowns.get(cooldown_key, 0):
            raise BridgeError("Wait five seconds before creating another timer.")
        ident = uuid.uuid4().hex[:8]
        key = (guild_id, ident)
        while key in self.pending_countdowns:
            key = (guild_id, uuid.uuid4().hex[:8])
        item = {"user_id": uid, "broadcaster_id": broadcaster_id, "due": time.monotonic() + seconds, "text": text,
                "guild_id": guild_id, "id": key[1]}
        self.pending_countdowns[key] = item
        item["task"] = asyncio.create_task(self._run_countdown(key, item))
        self.cooldowns[cooldown_key] = time.monotonic() + 5
        return f"Timer {key[1]} set for {parts[0]}."
