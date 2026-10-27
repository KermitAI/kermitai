import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord.ext import tasks
from redbot.core import Config, commands

from .policy import is_due, parse_birthday, render_message

log = logging.getLogger("red.birthday")


class BirthdayModal(discord.ui.Modal):
    def __init__(self, cog):
        super().__init__(title="Save your birthday", timeout=300)
        self.cog = cog
        self.birthday = discord.ui.TextInput(
            label="Birthday (MM/DD, no year)", placeholder="07/24",
            min_length=3, max_length=7,
        )
        self.add_item(self.birthday)

    async def on_submit(self, interaction):
        if not await self.cog.available(interaction):
            return
        try:
            month, day = parse_birthday(self.birthday.value)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with self.cog.lock(interaction.guild.id):
            group = self.cog.config.member(interaction.user)
            old = await group.birthday()
            await group.birthday.set({
                "month": month, "day": day,
                "last_year": old.get("last_year") if old else None,
            })
        await interaction.followup.send(
            f"Your birthday is saved as {month:02d}/{day:02d}! "
            "Use this button again to change it, or use the birthday forget command to remove it.",
            ephemeral=True,
        )

    async def on_error(self, interaction, error):
        log.error("Birthday form failed", exc_info=(type(error), error, error.__traceback__))
        if interaction.response.is_done():
            await interaction.followup.send("Could not save your birthday. Please try again.", ephemeral=True)
        else:
            await interaction.response.send_message("Could not save your birthday. Please try again.", ephemeral=True)


class BirthdayView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Set my birthday", style=discord.ButtonStyle.primary,
                       custom_id="kermitai:birthday:signup:v1")
    async def signup(self, interaction, button):
        if await self.cog.available(interaction):
            await interaction.response.send_modal(BirthdayModal(self.cog))


class Birthday(commands.Cog):
    """Collect birthdays and celebrate them in a configured server channel."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=827419620503, force_registration=True)
        self.config.register_guild(
            channel_id=None, message="Happy birthday, {member}! 🎂",
            timezone="America/Toronto", hour=9,
        )
        self.config.register_member(birthday=None)
        self.locks = {}
        self.view = None

    def lock(self, guild_id):
        return self.locks.setdefault(guild_id, asyncio.Lock())

    async def cog_load(self):
        self.view = BirthdayView(self)
        self.bot.add_view(self.view)
        self.announce.start()

    def cog_unload(self):
        self.announce.cancel()
        if self.view:
            self.view.stop()

    async def red_delete_data_for_user(self, *, requester, user_id):
        for guild_id, members in (await self.config.all_members()).items():
            if user_id in members:
                async with self.lock(guild_id):
                    await self.config.member_from_ids(guild_id, user_id).clear()

    async def available(self, interaction):
        if interaction.guild is None or await self.bot.cog_disabled_in_guild(self, interaction.guild):
            await interaction.response.send_message("Birthdays are unavailable here.", ephemeral=True)
            return False
        if not await self.config.guild(interaction.guild).channel_id():
            await interaction.response.send_message("An administrator needs to set up birthdays first.", ephemeral=True)
            return False
        return True

    @commands.group()
    @commands.guild_only()
    async def birthday(self, ctx):
        """Birthday signup and announcement settings."""

    @birthday.command(name="setup")
    @commands.admin_or_permissions(manage_guild=True)
    async def birthday_setup(self, ctx, channel: discord.TextChannel, *, message: str):
        """Set the announcement channel and text. Use {member} for the birthday mention."""
        if channel.guild.id != ctx.guild.id:
            await ctx.send("Choose a channel in this server.")
            return
        permissions = channel.permissions_for(ctx.guild.me)
        if not permissions.view_channel or not permissions.send_messages:
            await ctx.send("I need View Channel and Send Messages in that channel.")
            return
        # Reserve space for a mention even if the template does not contain one.
        if (not message.strip() or len(message) > 1800
                or len(message.replace("{member}", "<@12345678901234567890>")) + 24 > 2000):
            await ctx.send("Use a message between 1 and 1,800 characters, with fewer {member} tokens if needed.")
            return
        async with self.lock(ctx.guild.id):
            await self.config.guild(ctx.guild).channel_id.set(channel.id)
            await self.config.guild(ctx.guild).message.set(message)
        await ctx.send(
            f"Birthday announcements will go to {channel.mention}. "
            "Use birthday attach with a link to one of my messages to add the signup button.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @birthday.command(name="attach")
    @commands.admin_or_permissions(manage_guild=True)
    @commands.bot_has_permissions(read_message_history=True)
    async def birthday_attach(self, ctx, message: discord.Message):
        """Attach a signup button to an existing message from this bot (pass its message link)."""
        if not message.guild or message.guild.id != ctx.guild.id or message.author.id != ctx.me.id:
            await ctx.send("Choose a message sent by me in this server.")
            return
        if not await self.config.guild(ctx.guild).channel_id():
            await ctx.send("Run birthday setup first.")
            return
        if message.components:
            await ctx.send("That message already has buttons or other components. Choose a message without them.")
            return
        try:
            await message.edit(view=self.view)
        except discord.HTTPException:
            await ctx.send("I could not edit that message. Check my access to its channel.")
            return
        await ctx.send("The birthday signup button is attached.")

    @birthday.command(name="schedule")
    @commands.admin_or_permissions(manage_guild=True)
    async def birthday_schedule(self, ctx, timezone: str, hour: int = 9):
        """Set an IANA timezone and local hour (0-23), e.g. America/Toronto 9."""
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            await ctx.send("Unknown timezone. Use a name such as America/Toronto or UTC.")
            return
        if not 0 <= hour <= 23:
            await ctx.send("Choose an hour from 0 to 23.")
            return
        async with self.lock(ctx.guild.id):
            await self.config.guild(ctx.guild).timezone.set(timezone)
            await self.config.guild(ctx.guild).hour.set(hour)
        await ctx.send(f"Birthdays will be announced at {hour:02d}:00 in {timezone}.")

    @birthday.command(name="settings")
    @commands.admin_or_permissions(manage_guild=True)
    async def birthday_settings(self, ctx):
        """Show the current birthday announcement configuration."""
        data = await self.config.guild(ctx.guild).all()
        channel = f"<#{data['channel_id']}>" if data["channel_id"] else "Not configured"
        await ctx.send(
            f"Channel: {channel}\nTime: {data['hour']:02d}:00 ({data['timezone']})\n"
            f"Message: {data['message']}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @birthday.command(name="forget")
    async def birthday_forget(self, ctx):
        """Delete your saved birthday in this server."""
        async with self.lock(ctx.guild.id):
            await self.config.member(ctx.author).clear()
        await ctx.send("Your saved birthday has been removed from this server.")

    @birthday.command(name="disable")
    @commands.admin_or_permissions(manage_guild=True)
    async def birthday_disable(self, ctx):
        """Stop announcements and signup, retaining saved birthdays."""
        async with self.lock(ctx.guild.id):
            await self.config.guild(ctx.guild).channel_id.set(None)
        await ctx.send("Birthday announcements and signup are disabled. Saved birthdays are retained.")

    @tasks.loop(minutes=1)
    async def announce(self):
        for guild in self.bot.guilds:
            try:
                async with self.lock(guild.id):
                    await self.announce_guild(guild)
            except Exception:
                log.exception("Birthday check failed in guild %s", guild.id)

    @announce.before_loop
    async def before_announce(self):
        await self.bot.wait_until_red_ready()

    async def announce_guild(self, guild):
        if guild.unavailable or await self.bot.cog_disabled_in_guild(self, guild):
            return
        settings = await self.config.guild(guild).all()
        if not settings["channel_id"]:
            return
        now = datetime.now(ZoneInfo(settings["timezone"]))
        if now.hour < settings["hour"]:
            return
        channel = guild.get_channel(settings["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return
        permissions = channel.permissions_for(guild.me)
        if not permissions.view_channel or not permissions.send_messages:
            return
        for user_id, data in (await self.config.all_members(guild)).items():
            birthday = data["birthday"]
            if not birthday or not is_due(birthday, now.date()):
                continue
            try:
                member = guild.get_member(user_id) or await guild.fetch_member(user_id)
                if member.bot:
                    continue
                await channel.send(
                    render_message(settings["message"], member),
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False, roles=False, users=[member], replied_user=False,
                    ),
                )
            except discord.NotFound:
                continue
            except discord.HTTPException:
                log.warning("Birthday announcement failed for %s in %s", user_id, guild.id, exc_info=True)
                continue
            birthday["last_year"] = now.year
            await self.config.member_from_ids(guild.id, user_id).birthday.set(birthday)
