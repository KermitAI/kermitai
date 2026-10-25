import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import tasks
from redbot.core import Config, commands

from .policy import format_duration, is_due, parse_duration, waiting_seconds, required_role_ids

log = logging.getLogger("red.verifykick")


class VerifyKick(commands.Cog):
    """Remove members who have not obtained the required role in time."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=827419620501, force_registration=True)
        self.config.register_guild(enabled=False, role_id=None, role_ids=None, days=7, time_seconds=None,
                                   channel_id=None, enabled_at=None)
        self._locks = {}
        self.check_members.start()

    def cog_unload(self):
        self.check_members.cancel()

    async def red_delete_data_for_user(self, *, requester, user_id):
        pass  # No per-user data is stored.

    def _lock(self, guild):
        return self._locks.setdefault(guild.id, asyncio.Lock())

    @tasks.loop(seconds=30)
    async def check_members(self):
        for guild in self.bot.guilds:
            try:
                async with self._lock(guild):
                    await self._check_guild(guild)
            except Exception:
                log.exception("VerifyKick check failed for guild %s", guild.id)

    @check_members.before_loop
    async def before_check(self):
        await self.bot.wait_until_red_ready()

    async def _check_guild(self, guild):
        settings = await self.config.guild(guild).all()
        if (not settings["enabled"] or guild.unavailable
                or await self.bot.cog_disabled_in_guild(self, guild)):
            return
        role_ids = required_role_ids(settings)
        roles = [guild.get_role(rid) for rid in role_ids]
        if not roles or any(role is None for role in roles) or not settings["enabled_at"]:
            return  # A deleted role must never cause mass kicks.
        if not guild.chunked:
            await guild.chunk(cache=True)
        start = datetime.fromtimestamp(settings["enabled_at"], timezone.utc)
        for cached in list(guild.members):
            if not is_due(cached, role_ids, waiting_seconds(settings), start, discord.utils.utcnow()):
                continue
            if await self.bot.cog_disabled_in_guild(self, guild):
                return
            try:
                # Refresh roles and membership immediately before the destructive action.
                member = await guild.fetch_member(cached.id)
                if any(guild.get_role(rid) is None for rid in role_ids):
                    return
                if not is_due(member, role_ids, waiting_seconds(settings), start, discord.utils.utcnow()):
                    continue
                await member.kick(reason=(f"VerifyKick: missing all {len(role_ids)} accepted verification roles "
                                          f"after {format_duration(waiting_seconds(settings))}"))
            except discord.NotFound:
                continue
            except discord.HTTPException:
                log.warning("Could not kick member %s in guild %s", cached.id, guild.id,
                            exc_info=True)
                continue
            channel = guild.get_channel(settings["channel_id"]) if settings["channel_id"] else None
            if channel is not None:
                try:
                    await channel.send(
                        f"{discord.utils.escape_markdown(str(member))} (ID: {member.id}) "
                        f"was kicked for having none of the accepted verification roles after "
                        f"{format_duration(waiting_seconds(settings))}.",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    log.warning("Kick succeeded but notification failed in guild %s", guild.id,
                                exc_info=True)

    @commands.group(name="verifykickset", invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def verifykickset(self, ctx):
        """Configure automatic kicks for members missing a required role."""
        await ctx.send_help()

    @verifykickset.command(name="roles", aliases=["role"])
    async def set_roles(self, ctx, *roles: discord.Role):
        """Replace accepted roles. Having ANY listed role prevents a kick."""
        if not roles:
            await ctx.send("Provide one or more roles, e.g. verifykickset roles @Member @Verified.")
            return
        if any(role.is_default() or role.managed for role in roles):
            await ctx.send("Choose assignable roles other than @everyone.")
            return
        async with self._lock(ctx.guild):
            async with self.config.guild(ctx.guild).all() as settings:
                settings["role_ids"] = list(dict.fromkeys(role.id for role in roles))
                settings["role_id"] = None
                settings["enabled"] = False
        await ctx.send("Accepted roles saved (any one is sufficient). "
                       "Run verifykickset enable when ready.")

    @verifykickset.command(name="time")
    async def set_time(self, ctx, duration: str):
        """Set the waiting period, e.g. 3m, 1h, or 5d; disables enforcement."""
        try:
            seconds = parse_duration(duration)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        await self._save_time(ctx, seconds)

    @verifykickset.command(name="days")
    async def set_days(self, ctx, days: int):
        """Legacy shortcut for setting a waiting period in days (1–365)."""
        try:
            seconds = parse_duration(f"{days}d")
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        await self._save_time(ctx, seconds)

    async def _save_time(self, ctx, seconds):
        async with self._lock(ctx.guild):
            async with self.config.guild(ctx.guild).all() as settings:
                settings["time_seconds"] = seconds
                settings["enabled"] = False
        await ctx.send(f"Waiting period saved: {format_duration(seconds)}. "
                       "Run verifykickset enable when ready.")

    @verifykickset.command(name="channel")
    async def set_channel(self, ctx, channel: discord.TextChannel = None):
        """Set the kick notification channel, or omit it to turn notifications off."""
        if channel is not None:
            permissions = channel.permissions_for(ctx.guild.me)
            if not permissions.view_channel or not permissions.send_messages:
                await ctx.send("I need View Channel and Send Messages in that channel.")
                return
        async with self._lock(ctx.guild):
            await self.config.guild(ctx.guild).channel_id.set(channel.id if channel else None)
        await ctx.send("Notification channel saved." if channel else "Kick notifications disabled.")

    @verifykickset.command(name="enable")
    @commands.bot_has_permissions(kick_members=True)
    async def enable(self, ctx):
        """Enable automatic kicks, giving existing members a full grace period."""
        if not self.bot.intents.members:
            await ctx.send("Enable the Server Members Intent for this bot first, then restart it.")
            return
        async with self._lock(ctx.guild):
            async with self.config.guild(ctx.guild).all() as settings:
                role_ids = required_role_ids(settings)
                if not role_ids or any(ctx.guild.get_role(rid) is None for rid in role_ids):
                    await ctx.send("Set valid accepted roles first with verifykickset roles.")
                    return
                if settings["enabled"]:
                    await ctx.send("VerifyKick is already enabled; the countdown is unchanged.")
                    return
                settings["enabled"] = True
                settings["enabled_at"] = discord.utils.utcnow().timestamp()
        await ctx.send("Automatic kicks enabled. Existing members receive a full waiting period. "
                       "New members' waiting periods start when they join. Checks run every 30 seconds.")

    @verifykickset.command(name="disable")
    async def disable(self, ctx):
        """Stop automatic kicks."""
        async with self._lock(ctx.guild):
            await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("Automatic kicks disabled.")

    @verifykickset.command(name="settings")
    async def show_settings(self, ctx):
        """Show the current configuration."""
        settings = await self.config.guild(ctx.guild).all()
        role_ids = required_role_ids(settings)
        role_labels = [ctx.guild.get_role(rid).mention if ctx.guild.get_role(rid)
                       else f"Deleted role ({rid})" for rid in role_ids]
        channel = ctx.guild.get_channel(settings["channel_id"]) if settings["channel_id"] else None
        await ctx.send(
            f"Enabled: {settings['enabled']}\nAccepted roles (any one): "
            f"{', '.join(role_labels) if role_labels else 'Not set'}\n"
            f"Waiting period: {format_duration(waiting_seconds(settings))}\n"
            f"Notifications: {channel.mention if channel else 'Off or channel deleted'}\n"
            "Checks: every 30 seconds",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @verifykickset.command(name="preview")
    async def preview(self, ctx):
        """Count members currently due for a kick without kicking anyone."""
        settings = await self.config.guild(ctx.guild).all()
        role_ids = required_role_ids(settings)
        if (not settings["enabled"] or not role_ids
                or any(ctx.guild.get_role(rid) is None for rid in role_ids)):
            await ctx.send("Configure and enable VerifyKick first. No members were kicked.")
            return
        if not ctx.guild.chunked:
            await ctx.guild.chunk(cache=True)
        start = datetime.fromtimestamp(settings["enabled_at"], timezone.utc)
        now = discord.utils.utcnow()
        count = sum(is_due(m, role_ids, waiting_seconds(settings), start, now)
                    for m in ctx.guild.members)
        await ctx.send(f"{count} member(s) currently meet the kick criteria. "
                       "This preview did not kick anyone. Automatic checks continue if enabled.")
