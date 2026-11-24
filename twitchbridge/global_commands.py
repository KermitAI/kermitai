"""Owner-managed custom command definitions shared by all Twitch channels."""
import asyncio
import copy

from redbot.core import commands
from .policy import command_name, resolve_custom_command, template_text


class GlobalCommandsMixin:
    async def _global_records(self):
        return await self.config.global_commands()

    async def _change_global(self, ctx, change):
        if not hasattr(self, "global_commands_lock"):
            self.global_commands_lock = asyncio.Lock()
        try:
            async with self.global_commands_lock:
                async with self.config.global_commands() as records:
                    reply = change(records)
            await ctx.send(reply)
        except ValueError as exc:
            await ctx.send(str(exc))

    @commands.is_owner()
    @commands.guild_only()
    @commands.group(name="twitchglobal", invoke_without_command=True)
    async def twitchglobal(self, ctx):
        """Manage Twitch-only commands available across every linked stream."""
        await ctx.send_help()

    @twitchglobal.command(name="add")
    async def global_add(self, ctx, name: str, *, response: str):
        try:
            name, response = command_name(name), template_text(response)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        def change(records):
            if resolve_custom_command(records, name)[1] is not None:
                raise ValueError("That global command or alias already exists. Use twitchglobal edit.")
            if len(records) >= 250:
                raise ValueError("The global library already has 250 commands.")
            records[name] = {"response": response, "platform": "twitch", "permission": "everyone", "cooldown": 5}
            return f"Global command `{name}` added for all enabled linked Twitch streams. Local commands take precedence."
        await self._change_global(ctx, change)

    async def _global_setting(self, ctx, name, field, value):
        try:
            name = command_name(name)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        def change(records):
            canonical, record = resolve_custom_command(records, name)
            if record is None:
                raise ValueError("Global command not found.")
            record[field] = value
            return f"Global command `{canonical}` updated."
        await self._change_global(ctx, change)

    @twitchglobal.command(name="edit")
    async def global_edit(self, ctx, name: str, *, response: str):
        try:
            response = template_text(response)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        await self._global_setting(ctx, name, "response", response)

    @twitchglobal.command(name="preview")
    async def global_preview(self, ctx, name: str, *, args: str = ""):
        """Preview the global definition using this server's linked stream context."""
        await self._preview_custom_command(ctx, name, args, global_scope=True)

    @twitchglobal.command(name="permission")
    async def global_permission(self, ctx, name: str, permission: str):
        permission = permission.lower()
        if permission not in ("everyone", "moderator", "broadcaster"):
            await ctx.send("Choose everyone, moderator, or broadcaster.")
            return
        await self._global_setting(ctx, name, "permission", permission)

    @twitchglobal.command(name="cooldown")
    async def global_cooldown(self, ctx, name: str, seconds: int):
        if not 0 <= seconds <= 86400:
            await ctx.send("Choose 0-86400 seconds.")
            return
        await self._global_setting(ctx, name, "cooldown", seconds)

    @twitchglobal.command(name="remove", aliases=["delete"])
    async def global_remove(self, ctx, name: str):
        name = name.lower().lstrip("!")
        def change(records):
            canonical, record = resolve_custom_command(records, name)
            if record is None:
                raise ValueError("Global command not found.")
            if name != canonical:
                record["aliases"].remove(name)
                return f"Global alias `{name}` removed; its command remains."
            records.pop(canonical)
            for key in list(self.cooldowns):
                if key[1] == "global:" + canonical:
                    self.cooldowns.pop(key, None)
            return f"Global command `{canonical}` and its aliases removed."
        await self._change_global(ctx, change)

    @twitchglobal.command(name="list")
    async def global_list(self, ctx):
        records = await self._global_records()
        lines = [f"{name}: {record['permission']} | {record['cooldown']}s | aliases: {', '.join(record.get('aliases', [])) or 'none'}"
                 for name, record in sorted(records.items())]
        await self._send_command_lines(ctx, lines or ["No global commands configured."])

    @twitchglobal.group(name="alias", invoke_without_command=True)
    async def global_alias(self, ctx):
        await ctx.send_help()

    @global_alias.command(name="add")
    async def global_alias_add(self, ctx, name: str, alias: str):
        try:
            name, alias = command_name(name), command_name(alias)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        def change(records):
            canonical, record = resolve_custom_command(records, name)
            if record is None:
                raise ValueError("Global command not found.")
            if resolve_custom_command(records, alias)[1] is not None:
                raise ValueError("That global command or alias already exists.")
            aliases = record.get("aliases", [])
            if len(aliases) >= 10:
                raise ValueError("A command can have up to 10 aliases.")
            record["aliases"] = [*aliases, alias]
            return f"Global alias `{alias}` added for `{canonical}`."
        await self._change_global(ctx, change)

    @global_alias.command(name="remove", aliases=["delete"])
    async def global_alias_remove(self, ctx, alias: str):
        records = await self._global_records()
        canonical, record = resolve_custom_command(records, alias.lower().lstrip("!"))
        if record is not None and canonical == alias.lower().lstrip("!"):
            await ctx.send("That is the original command. Use twitchglobal remove to delete it.")
            return
        # Recheck inside the mutation so a concurrent remove/recreate cannot delete a primary.
        def change(records):
            name = alias.lower().lstrip("!")
            canonical, record = resolve_custom_command(records, name)
            if record is None or canonical == name:
                raise ValueError("Global alias not found.")
            record["aliases"].remove(name)
            return f"Global alias `{name}` removed."
        await self._change_global(ctx, change)

    @global_alias.command(name="list")
    async def global_alias_list(self, ctx):
        records = await self._global_records()
        await self._send_command_lines(ctx, [f"{name}: {', '.join(record.get('aliases', [])) or 'no aliases'}"
            for name, record in sorted(records.items())] or ["No global commands configured."])

    @twitchglobal.command(name="import")
    async def global_import(self, ctx, name: str):
        local = await self.config.guild(ctx.guild).custom_commands()
        canonical, record = resolve_custom_command(local, name.lower().lstrip("!"))
        if record is None:
            await ctx.send("Local custom command not found in this server.")
            return
        record = copy.deepcopy(record)
        record["platform"] = "twitch"
        def change(records):
            for candidate in [canonical, *record.get("aliases", [])]:
                command_name(candidate)
                if resolve_custom_command(records, candidate)[1] is not None:
                    raise ValueError(f"Global name `{candidate}` already exists; import cancelled.")
            if len(records) >= 250:
                raise ValueError("The global library already has 250 commands.")
            records[canonical] = record
            return f"Copied `{canonical}` into the global library. The local copy was kept and takes precedence here; remove it with twitchcommand remove when ready."
        await self._change_global(ctx, change)
