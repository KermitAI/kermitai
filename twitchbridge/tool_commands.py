"""Discord setup commands for broadcaster stream tools."""
import discord
from redbot.core import commands
from .errors import BridgeError
from .policy import chat_text
from .response_tools import tool_name


class ToolCommandsMixin:
    @commands.guild_only()
    @commands.group(name="twitchtodo", invoke_without_command=True)
    async def twitchtodo(self, ctx):
        await ctx.send_help()

    async def _todo_reply(self, ctx, action, text):
        try:
            lines = await self._todo_action(ctx.guild.id, action, text, await self._discord_level(ctx))
            for i in range(0, len(lines), 5):
                await ctx.send("\n".join(lines[i:i + 5]), allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
        except (BridgeError, ValueError) as exc:
            await ctx.send(str(exc))

    @twitchtodo.command(name="add")
    async def todo_add(self, ctx, *, text: str):
        await self._todo_reply(ctx, "add", text)

    @twitchtodo.command(name="view")
    async def todo_view(self, ctx):
        await self._todo_reply(ctx, "view", "")

    @twitchtodo.command(name="del", aliases=["delete"])
    async def todo_delete(self, ctx, number: int):
        await self._todo_reply(ctx, "del", str(number))

    @twitchtodo.command(name="permission")
    @commands.is_owner()
    async def todo_permission(self, ctx, permission: str):
        if permission not in ("everyone", "moderator", "broadcaster"):
            await ctx.send("Choose everyone, moderator, or broadcaster.")
            return
        await self.config.guild(ctx.guild).todo_permission.set(permission)
        await ctx.send("To-do editing permission saved.")

    async def _named_setting(self, ctx, field, name, key, value):
        try:
            name = tool_name(name)
            def change(data):
                if name not in data:
                    raise ValueError("Name not found.")
                data[name][key] = value
            await self._edit_tools(ctx.guild, field, change)
            await ctx.send("Setting saved.")
        except ValueError as exc:
            await ctx.send(str(exc))

    async def _named_remove(self, ctx, field, name):
        await self._edit_tools(ctx.guild, field, lambda data: data.pop(name.lower(), None))
        await ctx.send("Entry removed.")

    @commands.is_owner()
    @commands.guild_only()
    @commands.group(name="twitchtimer", invoke_without_command=True)
    async def twitchtimer(self, ctx):
        await ctx.send_help()

    @twitchtimer.command(name="add")
    async def timer_add(self, ctx, name: str, seconds: int, *, message: str):
        try:
            name, message = tool_name(name), chat_text(message)
            if not 10 <= seconds <= 86400:
                raise ValueError("Timer interval must be 10-86400 seconds.")
            def change(data):
                if name not in data and len(data) >= 50:
                    raise ValueError("A server can have 50 timers.")
                data[name] = {"seconds": seconds, "message": message, "enabled": True, "live_only": True}
            await self._edit_tools(ctx.guild, "timers", change)
            await ctx.send("Timer saved and enabled for live streams.")
        except ValueError as exc:
            await ctx.send(str(exc))

    @twitchtimer.command(name="enabled")
    async def timer_enabled(self, ctx, name: str, enabled: bool):
        await self._named_setting(ctx, "timers", name, "enabled", enabled)

    @twitchtimer.command(name="liveonly")
    async def timer_liveonly(self, ctx, name: str, enabled: bool):
        await self._named_setting(ctx, "timers", name, "live_only", enabled)

    @twitchtimer.command(name="remove")
    async def timer_remove(self, ctx, name: str):
        await self._named_remove(ctx, "timers", name)

    @twitchtimer.command(name="list")
    async def timer_list(self, ctx):
        data = await self.config.guild(ctx.guild).timers()
        for line in [f"{name}: {item['seconds']}s | enabled={item['enabled']} | live_only={item['live_only']}" for name, item in sorted(data.items())] or ["No timers configured."]:
            await ctx.send(line)

    @commands.is_owner()
    @commands.guild_only()
    @commands.group(name="twitchtrigger", invoke_without_command=True)
    async def twitchtrigger(self, ctx):
        await ctx.send_help()

    @twitchtrigger.command(name="add")
    async def trigger_add(self, ctx, name: str, word: str, *, message: str):
        try:
            name, message = tool_name(name), chat_text(message)
            if not word.strip() or len(word) > 100:
                raise ValueError("Use a word/phrase of 1-100 characters; quote phrases containing spaces.")
            def change(data):
                if name not in data and len(data) >= 50:
                    raise ValueError("A server can have 50 triggers.")
                data[name] = {"word": word, "message": message, "enabled": True, "cooldown": 30}
            await self._edit_tools(ctx.guild, "chat_triggers", change)
            await ctx.send("Chat trigger saved with a 30-second cooldown.")
        except ValueError as exc:
            await ctx.send(str(exc))

    @twitchtrigger.command(name="enabled")
    async def trigger_enabled(self, ctx, name: str, enabled: bool):
        await self._named_setting(ctx, "chat_triggers", name, "enabled", enabled)

    @twitchtrigger.command(name="cooldown")
    async def trigger_cooldown(self, ctx, name: str, seconds: int):
        if not 0 <= seconds <= 86400:
            await ctx.send("Choose 0-86400 seconds.")
            return
        await self._named_setting(ctx, "chat_triggers", name, "cooldown", seconds)

    @twitchtrigger.command(name="remove")
    async def trigger_remove(self, ctx, name: str):
        await self._named_remove(ctx, "chat_triggers", name)

    @twitchtrigger.command(name="list")
    async def trigger_list(self, ctx):
        data = await self.config.guild(ctx.guild).chat_triggers()
        for name, item in sorted(data.items()):
            await ctx.send(f"{name}: {item['word']} | enabled={item['enabled']} | {item['cooldown']}s", allowed_mentions=discord.AllowedMentions.none())
        if not data:
            await ctx.send("No triggers configured.")

    @commands.is_owner()
    @commands.guild_only()
    @commands.group(name="twitchcounter", invoke_without_command=True)
    async def twitchcounter(self, ctx):
        await ctx.send_help()

    async def _counter_set(self, ctx, name, value):
        try:
            name = tool_name(name)
            if not 0 <= value <= 1000000000:
                raise ValueError("Choose 0-1000000000.")
            keys, game, bid = await self._counter_context(ctx.guild.id, {name})
            key = keys.get(name, name)
            async with self._tool_lock(ctx.guild.id):
                group = self.config.guild(ctx.guild)
                cfg = await group.all()
                if cfg["broadcaster_id"] != bid or (name in cfg.get("game_counters", [])) != bool(keys):
                    raise BridgeError("Counter settings changed; please try again.")
                counters = await group.response_counters()
                if key not in counters and len(counters) >= 1000:
                    raise ValueError("This server already has 1000 counters.")
                counters[key] = value
                await group.response_counters.set(counters)
            await ctx.send(f"Counter {name}{' for ' + game if game else ''} set to {value}.", allowed_mentions=discord.AllowedMentions.none())
        except (ValueError, BridgeError) as exc:
            await ctx.send(str(exc))

    @twitchcounter.command(name="set")
    async def counter_set(self, ctx, name: str, value: int):
        await self._counter_set(ctx, name, value)

    @twitchcounter.command(name="reset")
    async def counter_reset(self, ctx, name: str):
        await self._counter_set(ctx, name, 0)

    @twitchcounter.command(name="pergame")
    async def counter_pergame(self, ctx, name: str, enabled: bool):
        """Keep a separate total per Twitch game; existing global totals are preserved."""
        try:
            name = tool_name(name)
            async with self._tool_lock(ctx.guild.id):
                group = self.config.guild(ctx.guild)
                cfg = await group.all()
                names = set(cfg.get("game_counters", []))
                if enabled:
                    names.add(name)
                else:
                    names.discard(name)
                await group.game_counters.set(sorted(names))
            await ctx.send(f"Counter {name}: per-game tracking {'enabled' if enabled else 'disabled'}. Existing totals preserved.")
        except ValueError as exc:
            await ctx.send(str(exc))

    @twitchcounter.command(name="view")
    async def counter_view(self, ctx, name: str):
        try:
            name = tool_name(name)
            keys, game, bid = await self._counter_context(ctx.guild.id, {name})
            data = await self.config.guild(ctx.guild).response_counters()
            await ctx.send(f"{name}{' for ' + game if game else ''}: {data.get(keys.get(name, name), 0)}",
                           allowed_mentions=discord.AllowedMentions.none())
        except (ValueError, BridgeError) as exc:
            await ctx.send(str(exc))


    @commands.is_owner()
    @commands.guild_only()
    @commands.group(name="twitchads", invoke_without_command=True)
    async def twitchads(self, ctx):
        await ctx.send_help()

    @twitchads.command(name="enabled")
    async def ads_enabled(self, ctx, enabled: bool):
        await self._edit_tools(ctx.guild, "ad_settings", lambda data: data.update(enabled=enabled))
        await ctx.send("Ad warnings enabled." if enabled else "Ad warnings disabled.")

    @twitchads.command(name="leads")
    async def ads_leads(self, ctx, *, seconds: str):
        try:
            leads = sorted({int(v) for v in seconds.replace(",", " ").split()}, reverse=True)
            if not leads or any(not 1 <= v <= 300 for v in leads):
                raise ValueError()
        except ValueError:
            await ctx.send("Provide lead times from 1-300 seconds, for example 300 60 10 1.")
            return
        await self._edit_tools(ctx.guild, "ad_settings", lambda data: data.update(leads=leads))
        await ctx.send("Ad warning lead times saved. Very short warnings are best effort.")

    @twitchads.command(name="message")
    async def ads_message(self, ctx, *, message: str):
        try:
            message = chat_text(message)
            await self._edit_tools(ctx.guild, "ad_settings", lambda data: data.update(message=message))
            await ctx.send("Ad warning message saved.")
        except ValueError as exc:
            await ctx.send(str(exc))

    @twitchads.command(name="mode")
    async def ads_mode(self, ctx, mode: str):
        if mode not in ("chat", "announcement"):
            await ctx.send("Choose chat or announcement.")
            return
        await self._edit_tools(ctx.guild, "ad_settings", lambda data: data.update(mode=mode))
        await ctx.send("Ad warning mode saved.")

    @twitchads.command(name="snooze")
    async def ads_snooze(self, ctx):
        try:
            await ctx.send(await self._ad_action(ctx.guild.id, "snooze"))
        except BridgeError as exc:
            await ctx.send(str(exc))

    @twitchads.command(name="run")
    async def ads_run(self, ctx, seconds: int = 60):
        try:
            await ctx.send(await self._ad_action(ctx.guild.id, "run", seconds))
        except (BridgeError, ValueError) as exc:
            await ctx.send(str(exc))

    @twitchads.command(name="status")
    async def ads_status(self, ctx):
        try:
            schedule = await self._refresh_ads(ctx.guild.id)
            at = schedule.get("next_ad_at", 0)
            await ctx.send(f"Next ad: <t:{at}:R>. Snoozes: {schedule.get('snooze_count', 0)}." if at else "Twitch reports no scheduled ad.")
        except BridgeError as exc:
            await ctx.send(str(exc))

    @commands.is_owner()
    @commands.guild_only()
    @commands.group(name="twitchfirst", invoke_without_command=True)
    async def twitchfirst(self, ctx):
        await ctx.send_help()

    @twitchfirst.command(name="enabled")
    async def first_enabled(self, ctx, enabled: bool):
        await self._edit_tools(ctx.guild, "first_message", lambda data: data.update(enabled=enabled))
        await ctx.send("First-message greetings enabled." if enabled else "First-message greetings disabled.")

    @twitchfirst.command(name="mode")
    async def first_mode(self, ctx, mode: str):
        if mode not in ("ever", "stream"):
            await ctx.send("Choose ever or stream.")
            return
        await self._edit_tools(ctx.guild, "first_message", lambda data: data.update(mode=mode))
        await ctx.send("Greeting mode saved.")

    @twitchfirst.command(name="everyone")
    async def first_everyone(self, ctx, enabled: bool):
        await self._edit_tools(ctx.guild, "first_message", lambda data: data.update(everyone=enabled))
        await ctx.send("Default greeting audience saved; per-user greetings still apply.")

    @twitchfirst.command(name="message")
    async def first_message(self, ctx, *, message: str):
        try:
            message = chat_text(message)
            await self._edit_tools(ctx.guild, "first_message", lambda data: data.update(message=message))
            await ctx.send("Default greeting saved.")
        except ValueError as exc:
            await ctx.send(str(exc))

    @twitchfirst.command(name="user")
    async def first_user(self, ctx, username: str, *, message: str):
        try:
            identity, message = await self._lookup_twitch(username), chat_text(message)
            await self._edit_tools(ctx.guild, "first_message", lambda data: data.setdefault("users", {}).__setitem__(identity["id"], message))
            await ctx.send("Per-user greeting saved.")
        except (BridgeError, ValueError) as exc:
            await ctx.send(str(exc))

    @twitchfirst.command(name="removeuser")
    async def first_removeuser(self, ctx, username: str):
        try:
            identity = await self._lookup_twitch(username)
            await self._edit_tools(ctx.guild, "first_message", lambda data: data.setdefault("users", {}).pop(identity["id"], None))
            await ctx.send("Per-user greeting removed.")
        except (BridgeError, ValueError) as exc:
            await ctx.send(str(exc))

    @commands.guild_only()
    @commands.group(name="twitchstreak", invoke_without_command=True)
    async def twitchstreak(self, ctx):
        await ctx.send_help()

    @twitchstreak.command(name="enabled")
    @commands.is_owner()
    async def streak_enabled(self, ctx, enabled: bool):
        await self._edit_tools(ctx.guild, "streak_settings", lambda data: data.update(enabled=enabled))
        await ctx.send("Stream streak tracking enabled." if enabled else "Stream streak tracking disabled.")

    @twitchstreak.command(name="breakonmiss")
    @commands.is_owner()
    async def streak_break(self, ctx, enabled: bool):
        await self._edit_tools(ctx.guild, "streak_settings", lambda data: data.update(break_on_miss=enabled))
        await ctx.send("Missed-stream streak policy saved.")

    async def _set_streak(self, ctx, username, value, add=False):
        try:
            identity = await self._lookup_twitch(username)
            if not 0 <= value <= 1000000000:
                raise ValueError("Choose 0-1000000000.")
            info = await self._stream_info(ctx.guild.id)
            if info["stream"]:
                await self._observe_stream(ctx.guild.id, info["stream"])
            async with self._tool_lock(ctx.guild.id):
                group = self.config.guild(ctx.guild)
                cfg = await group.all()
                bid = cfg["broadcaster_id"]
                viewers = await group.viewer_data()
                session = (await group.stream_session()).get(bid, {})
                data = viewers.setdefault(bid, {}).setdefault(identity["id"], {})
                data["streak"] = data.get("streak", 0) + value if add else value
                data["last_session"] = session.get("number", 0)
                await group.viewer_data.set(viewers)
                self.presence_seen = {k: v for k, v in self.presence_seen.items() if not (k[0] == ctx.guild.id and k[3] == identity["id"])}
            await ctx.send(f"{identity['login']} streak is now {data['streak']}.")
        except (BridgeError, ValueError) as exc:
            await ctx.send(str(exc))

    @twitchstreak.command(name="set")
    @commands.is_owner()
    async def streak_set(self, ctx, username: str, value: int):
        await self._set_streak(ctx, username, value)

    @twitchstreak.command(name="add")
    @commands.is_owner()
    async def streak_add(self, ctx, username: str, value: int):
        await self._set_streak(ctx, username, value, add=True)

    @twitchstreak.command(name="view")
    async def streak_view(self, ctx, username: str):
        try:
            identity = await self._lookup_twitch(username)
            cfg = await self.config.guild(ctx.guild).all()
            data = cfg.get("viewer_data", {}).get(cfg["broadcaster_id"], {}).get(identity["id"], {})
            await ctx.send(f"{identity['login']}: stream streak {data.get('streak', 0)}.")
        except (BridgeError, ValueError) as exc:
            await ctx.send(str(exc))

    @twitchstreak.command(name="forget")
    @commands.is_owner()
    async def streak_forget(self, ctx, username: str):
        try:
            identity = await self._lookup_twitch(username)
            await self._forget_tool_viewer(ctx.guild.id, identity["id"])
            await ctx.send("Streak and first-message data for that Twitch account were removed.")
        except (BridgeError, ValueError) as exc:
            await ctx.send(str(exc))
