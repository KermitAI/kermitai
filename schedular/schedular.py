import asyncio
import copy
import logging
import time
import uuid

import discord
from redbot.core import Config, commands

from .scheduling import daily_times, interval, next_run, zone

log = logging.getLogger("red.kermitai.schedular")


def panel(record, aid=None):
    embed = discord.Embed(title="Scheduled announcement", description=record["message"] or "Set your announcement message.", colour=discord.Colour.green())
    timing = (record["interval_label"] if record["mode"] == "interval" else ", ".join(record["times"]) + " daily (" + record["timezone"] + ")")
    embed.add_field(name="Channel", value=f"<#{record['channel']}>")
    embed.add_field(name="Schedule", value=timing, inline=False)
    embed.add_field(name="Status", value="Paused" if record["paused"] else "Enabled")
    if record.get("next") and not record["paused"]:
        embed.add_field(name="Next post", value=f"<t:{int(record['next'])}:F>", inline=False)
    if record.get("error"):
        embed.add_field(name="Last delivery error", value=record["error"], inline=False)
    embed.set_footer(text=f"ID: {aid}" if aid else "Preview • Save to activate • Mentions do not ping")
    return embed


class SettingModal(discord.ui.Modal):
    def __init__(self, view, action):
        super().__init__(title=action, timeout=300)
        self.view, self.action = view, action
        key, label, limit = {"Message": ("message", "Announcement message", 2000),
            "Interval": ("interval_label", "E.g. 15m, 2h, 3d, 1w or 15 minutes", 50),
            "Daily times": (None, "Daily times (24-hour, comma separated)", 600),
            "Timezone": ("timezone", "IANA timezone, e.g. America/Toronto", 100)}[action]
        default = view.record[key] if key else ", ".join(view.record["times"])
        self.value = discord.ui.TextInput(label=label, default=default or None, max_length=limit,
            style=discord.TextStyle.paragraph if action == "Message" else discord.TextStyle.short)
        self.add_item(self.value)

    async def on_submit(self, interaction):
        if not await self.view.interaction_check(interaction):
            return
        async with self.view.lock:
            if self.view.is_finished():
                await interaction.response.send_message("This panel has ended.", ephemeral=True)
                return
            value = self.value.value.strip()
            try:
                if self.action == "Message":
                    if not value:
                        raise ValueError("The message cannot be blank.")
                    self.view.record["message"] = value
                elif self.action == "Interval":
                    seconds = interval(value)
                    self.view.record.update(mode="interval", interval=seconds, interval_label=value)
                elif self.action == "Daily times":
                    times = daily_times(value)
                    self.view.record.update(mode="daily", times=times)
                else:
                    zone(value)
                    self.view.record["timezone"] = value
            except ValueError as error:
                await interaction.response.send_message(str(error), ephemeral=True)
                return
            await interaction.response.defer()
            await self.view.refresh()


class ChannelPicker(discord.ui.View):
    def __init__(self, builder):
        super().__init__(timeout=180)
        select = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text], placeholder="Announcement channel")
        async def choose(interaction):
            if not await builder.interaction_check(interaction):
                return
            async with builder.lock:
                if builder.is_finished():
                    await interaction.response.send_message("This panel has ended.", ephemeral=True)
                    return
                builder.record["channel"] = select.values[0].id
                await interaction.response.edit_message(content="Channel selected.", view=None)
                await builder.refresh()
                self.stop()
        select.callback = choose
        self.add_item(select)


class AnnouncementPanel(discord.ui.View):
    def __init__(self, cog, ctx, aid=None, record=None):
        super().__init__(timeout=900)
        self.cog, self.ctx, self.aid = cog, ctx, aid
        self.lock, self.message = asyncio.Lock(), None
        self.original = copy.deepcopy(record)
        self.record = copy.deepcopy(record) if record else dict(message="", channel=ctx.channel.id,
            mode="interval", interval=3600, interval_label="1 hour", times=["09:00"], timezone="UTC", paused=False)
        for action in ("Message", "Channel", "Interval", "Daily times", "Timezone", "Pause / Resume", "Save", "Delete", "Exit"):
            button = discord.ui.Button(label=action, style=discord.ButtonStyle.success if action == "Save" else discord.ButtonStyle.danger if action == "Delete" else discord.ButtonStyle.secondary)
            async def callback(interaction, action=action):
                async with self.lock:
                    if self.is_finished():
                        await interaction.response.send_message("This panel has ended.", ephemeral=True)
                    elif action == "Exit":
                        self.stop()
                        await interaction.response.edit_message(content="Panel closed. Unsaved changes discarded.", view=None)
                    elif action == "Channel":
                        await interaction.response.send_message("Choose a channel.", view=ChannelPicker(self), ephemeral=True)
                    elif action == "Pause / Resume":
                        self.record["paused"] = not self.record["paused"]
                        await interaction.response.defer()
                        await self.refresh()
                    elif action in ("Save", "Delete"):
                        await interaction.response.defer(ephemeral=True)
                        await self.cog.commit(interaction, self, delete=action == "Delete")
                    else:
                        await interaction.response.send_modal(SettingModal(self, action))
            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction):
        allowed = interaction.user.id == self.ctx.author.id and (
            interaction.user.guild_permissions.manage_guild or await self.cog.bot.is_admin(interaction.user))
        if not allowed:
            await interaction.response.send_message("Only the panel owner with Manage Server or bot admin permission can use this panel.", ephemeral=True)
        return allowed

    async def refresh(self):
        await self.message.edit(embed=panel(self.record, self.aid), allowed_mentions=discord.AllowedMentions.none())

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="Panel expired. Unsaved changes discarded.", view=None)
            except discord.HTTPException:
                pass


class DeletePicker(discord.ui.View):
    """Keep letter-to-ID mappings fixed while a deletion panel is open."""
    PAGE_SIZE = 20

    def __init__(self, cog, ctx, records):
        super().__init__(timeout=900)
        self.cog, self.ctx = cog, ctx
        self.entries = list(records.items())
        self.page, self.deleted = 0, set()
        self.lock, self.message = asyncio.Lock(), None
        self.rebuild()

    async def interaction_check(self, interaction):
        return await AnnouncementPanel.interaction_check(self, interaction)

    def visible(self):
        start = self.page * self.PAGE_SIZE
        return self.entries[start:start + self.PAGE_SIZE]

    def embed(self):
        embed = discord.Embed(title="Delete scheduled announcements",
            description="Press the matching letter to delete a schedule immediately. Previously posted messages remain.",
            colour=discord.Colour.green())
        for index, (aid, record) in enumerate(self.visible()):
            letter = chr(0x1F1E6 + index)
            title = discord.utils.escape_markdown(" ".join(record["message"].split()[:10]))
            if len(title) > 150:
                title = title[:147] + "..."
            if aid in self.deleted:
                value = "Deleted."
            else:
                timing = record["interval_label"] if record["mode"] == "interval" else ", ".join(record["times"]) + " (" + record["timezone"] + ")"
                value = f"<#{record['channel']}> • {'Paused' if record['paused'] else 'Enabled'}\n{timing[:80]}"
            embed.add_field(name=f"{letter} — {title}", value=value, inline=False)
        pages = (len(self.entries) + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        embed.set_footer(text=f"Page {self.page + 1}/{pages} • Only the panel owner can delete • Expires after 15 minutes")
        return embed

    def rebuild(self):
        self.clear_items()
        for index, (aid, record) in enumerate(self.visible()):
            button = discord.ui.Button(emoji=chr(0x1F1E6 + index),
                style=discord.ButtonStyle.danger, disabled=aid in self.deleted)
            async def callback(interaction, aid=aid, original=record):
                async with self.lock:
                    if self.is_finished():
                        await interaction.response.send_message("This panel has ended.", ephemeral=True)
                        return
                    await interaction.response.defer()
                    async with self.cog.lock(self.ctx.guild.id):
                        group = self.cog.config.guild(self.ctx.guild).announcements
                        current = await group.get_raw(aid, default=None)
                        if current is not None and any(current.get(key) != original.get(key) for key in
                                ("revision", "message", "channel", "mode", "interval", "times", "timezone", "paused")):
                            await interaction.followup.send("This announcement changed. Run schedular delete again to review it.", ephemeral=True)
                            return
                        if current is not None:
                            await group.clear_raw(aid)
                    self.deleted.add(aid)
                    self.rebuild()
                    await interaction.edit_original_response(embed=self.embed(), view=self,
                        allowed_mentions=discord.AllowedMentions.none())
            button.callback = callback
            self.add_item(button)
        for label, delta in (("Previous", -1), ("Next", 1), ("Close", 0)):
            button = discord.ui.Button(label=label, row=4,
                disabled=(delta == -1 and self.page == 0) or (delta == 1 and (self.page + 1) * self.PAGE_SIZE >= len(self.entries)))
            async def navigate(interaction, delta=delta):
                async with self.lock:
                    if self.is_finished():
                        await interaction.response.send_message("This panel has ended.", ephemeral=True)
                    elif delta == 0:
                        self.stop()
                        await interaction.response.edit_message(content="Deletion panel closed.", view=None)
                    else:
                        self.page += delta
                        self.rebuild()
                        await interaction.response.edit_message(embed=self.embed(), view=self,
                            allowed_mentions=discord.AllowedMentions.none())
            button.callback = navigate
            self.add_item(button)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="Deletion panel expired. Run schedular delete to reopen it.", view=None)
            except discord.HTTPException:
                pass


class Schedular(commands.Cog):
    """Recurring announcements configured through embeds and buttons."""
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=827419620505, force_registration=True)
        self.config.register_guild(announcements={})
        self.locks, self.panels = {}, set()
        self.worker = None

    def lock(self, gid):
        return self.locks.setdefault(gid, asyncio.Lock())

    async def cog_load(self):
        self.worker = asyncio.create_task(self.run())

    def cog_unload(self):
        if self.worker:
            self.worker.cancel()
        for view in self.panels:
            view.stop()

    async def commit(self, interaction, view, *, delete=False):
        gid = view.ctx.guild.id
        async with self.lock(gid):
            group = self.config.guild_from_id(gid).announcements
            records = await group()
            current = records.get(view.aid)
            if view.aid and (current is None or any(current.get(k) != view.original.get(k) for k in
                    ("message", "channel", "mode", "interval", "times", "timezone", "paused", "revision"))):
                await interaction.followup.send("This schedule changed or was deleted. Reopen its panel.", ephemeral=True)
                return
            if delete:
                if not view.aid:
                    await interaction.followup.send("This announcement has not been saved.", ephemeral=True)
                    return
                del records[view.aid]
            else:
                record = copy.deepcopy(view.record)
                channel = view.ctx.guild.get_channel(record["channel"])
                if not record["message"] or not isinstance(channel, discord.TextChannel):
                    await interaction.followup.send("Set a message and an available text channel first.", ephemeral=True)
                    return
                permissions = channel.permissions_for(view.ctx.guild.me)
                if not permissions.view_channel or not permissions.send_messages:
                    await interaction.followup.send("I need View Channel and Send Messages in that channel.", ephemeral=True)
                    return
                record["next"] = next_run(record, time.time())
                record["error"] = ""
                record["revision"] = uuid.uuid4().hex
                view.aid = view.aid or uuid.uuid4().hex[:12]
                records[view.aid] = record
            await group.set(records)
        view.stop()
        await view.message.edit(content="Announcement deleted." if delete else f"Announcement saved. ID: {view.aid}", view=None,
            embed=None if delete else panel(record, view.aid))
        await interaction.followup.send("Deleted." if delete else "Saved. The next post is shown in the panel.", ephemeral=True)

    async def tick(self):
        for gid in await self.config.all_guilds():
            guild = self.bot.get_guild(gid)
            if not guild or await self.bot.cog_disabled_in_guild(self, guild):
                continue
            async with self.lock(gid):
                group = self.config.guild_from_id(gid).announcements
                records = await group()
                for aid, record in records.items():
                    now = time.time()
                    if record["paused"] or record["next"] > now:
                        continue
                    # Reserve the next occurrence before delivery: no catch-up bursts or rapid retries.
                    record["next"] = next_run(record, now + 899 if record["mode"] == "daily" else now)
                    await group.set_raw(aid, value=record)
                    channel = guild.get_channel(record["channel"])
                    try:
                        if not isinstance(channel, discord.TextChannel):
                            raise ValueError("Channel missing. Select another channel and save.")
                        await channel.send(record["message"], allowed_mentions=discord.AllowedMentions.none())
                    except (discord.HTTPException, ValueError) as error:
                        record["error"] = "Unable to deliver. Check channel access and Send Messages permission." if isinstance(error, discord.HTTPException) else str(error)
                    else:
                        record["error"] = ""
                    await group.set_raw(aid, value=record)

    async def run(self):
        await self.bot.wait_until_red_ready()
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("Scheduled announcement worker failed")
            await asyncio.sleep(30)

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.bot_has_permissions(embed_links=True)
    async def schedular(self, ctx):
        """Manage scheduled announcements. Use create, list, delete or edit <ID>."""
        await ctx.send_help()

    async def open_panel(self, ctx, aid=None, record=None):
        view = AnnouncementPanel(self, ctx, aid, record)
        self.panels = {p for p in self.panels if not p.is_finished()}
        self.panels.add(view)
        view.message = await ctx.send(embed=panel(view.record, aid), view=view, allowed_mentions=discord.AllowedMentions.none())

    @schedular.command(name="create")
    async def schedular_create(self, ctx):
        """Open the announcement builder."""
        await self.open_panel(ctx)

    @schedular.command(name="edit")
    async def schedular_edit(self, ctx, announcement_id: str):
        """Edit, pause, resume or delete an announcement using its ID."""
        record = await self.config.guild(ctx.guild).announcements.get_raw(announcement_id, default=None)
        if not record:
            await ctx.send("No announcement with that ID. Use schedular list.")
            return
        await self.open_panel(ctx, announcement_id, record)

    @schedular.command(name="delete")
    async def schedular_delete(self, ctx):
        """Choose announcements to delete using letter buttons."""
        records = await self.config.guild(ctx.guild).announcements()
        if not records:
            await ctx.send("No announcements to delete.")
            return
        view = DeletePicker(self, ctx, records)
        self.panels = {p for p in self.panels if not p.is_finished()}
        self.panels.add(view)
        view.message = await ctx.send(embed=view.embed(), view=view,
            allowed_mentions=discord.AllowedMentions.none())

    @schedular.command(name="list")
    async def schedular_list(self, ctx):
        """List saved announcement IDs and their schedules."""
        records = await self.config.guild(ctx.guild).announcements()
        if not records:
            await ctx.send("No announcements yet. Use schedular create.")
        for aid, record in records.items():
            await ctx.send(embed=panel(record, aid), allowed_mentions=discord.AllowedMentions.none())

    async def red_delete_data_for_user(self, *, requester, user_id):
        # No member IDs or member-specific records are stored.
        pass
