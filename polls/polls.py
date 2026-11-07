import asyncio
import copy
import logging
import re
import time
from urllib.parse import urlparse

import discord
from redbot.core import Config, commands

log = logging.getLogger("red.kermitai.polls")
UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}


def duration(value):
    match = re.fullmatch(r"\s*(\d+)\s*(seconds?|minutes?|hours?|days?|weeks?)\s*", value.lower())
    if not match or int(match[1]) < 1:
        raise ValueError("Enter a positive duration, such as 30 seconds, 10 minutes, 2 hours, 3 days or 1 week.")
    result = int(match[1]) * UNITS[match[2].rstrip("s")]
    if result > 31536000:
        raise ValueError("Polls can run for at most 365 days.")
    return result


def poll_reference(value, guild_id):
    """Return a message ID, rejecting links to another server."""
    value = value.strip().strip("<>")
    if re.fullmatch(r"[0-9]+", value) and int(value) > 0:
        return str(int(value))
    match = re.fullmatch(r"https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/channels/([0-9]+)/([0-9]+)/([0-9]+)/?", value)
    if not match or int(match[1]) != guild_id:
        raise ValueError("Provide a poll message ID or a Discord message link from this server.")
    return str(int(match[3]))


def letter(index):
    return chr(0x1F1E6 + index)


def counts(poll):
    return [sum(i in choices for choices in poll["votes"].values()) for i in range(len(poll["answers"]))]


def poll_embed(poll, *, preview=False):
    totals = counts(poll)
    embed = discord.Embed(title=poll["question"] or "Your poll question", colour=discord.Colour.green())
    lines = [poll["description"]] if poll["description"] else []
    lines += [f"{letter(i)} - {answer}" for i, answer in enumerate(poll["answers"])]
    embed.description = "\n\n".join(lines) or "Use Question and Answer to build your poll."
    if poll.get("closed"):
        best = max(totals, default=0)
        winners = [letter(i) for i, total in enumerate(totals) if total == best]
        if best == 0:
            summary = "No votes were submitted."
        elif len(winners) > 1:
            summary = f"Tie: {' '.join(winners)} with {best} votes each."
        else:
            runner_up = max((n for n in totals if n != best), default=0)
            summary = f"Winner: {winners[0]} with {best} votes (ahead by {best - runner_up})."
        summary += "\n" + "\n".join(f"{letter(i)} — {n} vote(s)" for i, n in enumerate(totals))
        embed.add_field(name="Final results", value=summary, inline=False)
    elif poll.get("ends"):
        embed.add_field(name="Closes", value=f"<t:{int(poll['ends'])}:R>")
    if preview:
        roles = " ".join(f"<@&{r}>" for r in poll["roles"]) or "Everyone"
        embed.add_field(name="Builder settings", value=(
            f"Duration: {poll['duration']} seconds\nVotes per member: {poll['limit']}\n"
            f"Poll channel: <#{poll['channel']}>\nResults channel: <#{poll['results']}>\nAllowed roles: {roles}"), inline=False)
    embed.set_footer(text=f"Choose up to {poll['limit']} option(s). Click again to remove your vote.")
    if poll["image"]:
        embed.set_image(url=poll["image"])
    return embed


class EditModal(discord.ui.Modal):
    def __init__(self, builder, action):
        super().__init__(title=action, timeout=300)
        self.builder, self.action = builder, action
        limits = {"Question": 256, "Answer": 120, "Description": 750, "Image": 500}
        defaults = {"Question": "question", "Description": "description", "Image": "image"}
        self.input = discord.ui.TextInput(label={"Time": "Duration (e.g. 2 hours)", "Votes": "Votes per member"}.get(action, action),
            max_length=limits.get(action, 50), required=action not in ("Description", "Image"),
            default=builder.poll.get(defaults.get(action, "")) or None,
            style=discord.TextStyle.paragraph if action == "Description" else discord.TextStyle.short)
        self.add_item(self.input)

    async def on_submit(self, interaction):
        builder = self.builder
        async with builder.lock:
            if builder.is_finished():
                await interaction.response.send_message("This builder has ended.", ephemeral=True)
                return
            value = self.input.value.strip()
            try:
                if self.action == "Time":
                    builder.poll["duration"] = duration(value)
                elif self.action == "Votes":
                    if not value.isdecimal() or not 1 <= int(value) <= 25:
                        raise ValueError("Enter a number from 1 to 25.")
                    builder.poll["limit"] = int(value)
                elif self.action == "Answer":
                    if len(builder.poll["answers"]) >= 25:
                        raise ValueError("A poll can have at most 25 answers.")
                    if not value:
                        raise ValueError("An answer cannot be blank.")
                    builder.poll["answers"].append(value)
                else:
                    if self.action == "Image" and value:
                        url = urlparse(value)
                        if url.scheme not in ("http", "https") or not url.netloc:
                            raise ValueError("Enter a valid HTTP or HTTPS image URL, or leave blank to clear it.")
                    if self.action == "Question" and not value:
                        raise ValueError("A question cannot be blank.")
                    builder.poll[self.action.lower()] = value
            except ValueError as error:
                await interaction.response.send_message(str(error), ephemeral=True)
                return
            await interaction.response.defer()
            await builder.refresh()


class Picker(discord.ui.View):
    def __init__(self, builder, action):
        super().__init__(timeout=180)
        self.builder = builder
        if action == "Roles":
            select = discord.ui.RoleSelect(placeholder="Allowed roles (clear for everyone)", min_values=0, max_values=10)
        else:
            select = discord.ui.ChannelSelect(placeholder=action, channel_types=[discord.ChannelType.text])
        async def callback(interaction):
            if interaction.user.id != builder.owner:
                await interaction.response.send_message("This builder belongs to someone else.", ephemeral=True)
                return
            async with builder.lock:
                if builder.is_finished():
                    await interaction.response.send_message("This builder has ended.", ephemeral=True)
                    return
                builder.poll[{"Roles": "roles", "Poll channel": "channel", "Results channel": "results"}[action]] = (
                    [role.id for role in select.values] if action == "Roles" else select.values[0].id)
                await interaction.response.edit_message(content="Setting updated.", view=None)
                await builder.refresh()
                self.stop()
        select.callback = callback
        self.add_item(select)


class Builder(discord.ui.View):
    def __init__(self, cog, ctx):
        super().__init__(timeout=900)
        self.cog, self.ctx, self.owner = cog, ctx, ctx.author.id
        self.lock = asyncio.Lock()
        self.message = None
        self.poll = dict(question="", answers=[], description="", duration=86400, image="",
                         channel=ctx.channel.id, results=ctx.channel.id, limit=1, roles=[], votes={})
        for action in ("Question", "Answer", "Description", "Time", "Image", "Poll channel", "Results channel", "Votes", "Roles", "Remove last answer", "Create", "Exit"):
            style = discord.ButtonStyle.success if action in ("Question", "Answer", "Create") else discord.ButtonStyle.danger if action == "Exit" else discord.ButtonStyle.secondary
            button = discord.ui.Button(label=action, style=style)
            async def callback(interaction, action=action):
                async with self.lock:
                    if self.is_finished():
                        await interaction.response.send_message("This builder has ended.", ephemeral=True)
                    elif action == "Exit":
                        self.stop()
                        await interaction.response.edit_message(content="Poll builder closed.", view=None)
                    elif action == "Create":
                        await interaction.response.defer(ephemeral=True)
                        await self.cog.publish(interaction, self)
                    elif action == "Remove last answer":
                        if self.poll["answers"]:
                            self.poll["answers"].pop()
                        await interaction.response.defer()
                        await self.refresh()
                    elif action in ("Roles", "Poll channel", "Results channel"):
                        await interaction.response.send_message("Choose below.", view=Picker(self, action), ephemeral=True)
                    else:
                        await interaction.response.send_modal(EditModal(self, action))
            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner:
            return True
        await interaction.response.send_message("Only the poll creator can use this panel.", ephemeral=True)
        return False

    async def refresh(self):
        await self.message.edit(embed=poll_embed(self.poll, preview=True), allowed_mentions=discord.AllowedMentions.none())

    async def on_timeout(self):
        async with self.lock:
            if self.message:
                try:
                    await self.message.edit(content="Poll builder expired. Run pollcreate to start again.", view=None)
                except discord.HTTPException:
                    pass


class Ballot(discord.ui.View):
    def __init__(self, cog, guild_id, poll_id, poll):
        super().__init__(timeout=None)
        for i, total in enumerate(counts(poll)):
            button = discord.ui.Button(emoji=letter(i), label=str(total), custom_id=f"kermitpoll:{guild_id}:{poll_id}:{i}")
            async def callback(interaction, index=i):
                await cog.vote(interaction, guild_id, poll_id, index)
            button.callback = callback
            self.add_item(button)


class Polls(commands.Cog):
    """Create timed, role-restricted button polls."""
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=827419620504, force_registration=True)
        self.config.register_guild(polls={}, completed={})
        self.locks, self.views, self.builders = {}, {}, set()
        self.worker = None
        self.dirty = set()

    def lock(self, guild_id, poll_id):
        return self.locks.setdefault((guild_id, poll_id), asyncio.Lock())

    async def cog_load(self):
        for gid, data in (await self.config.all_guilds()).items():
            for pid, poll in data["polls"].items():
                if not poll.get("closed") and not poll.get("deleting"):
                    view = Ballot(self, gid, pid, poll)
                    self.bot.add_view(view, message_id=int(pid))
                    self.views[gid, pid] = view
                    self.dirty.add((gid, pid))
        self.worker = asyncio.create_task(self.expire())

    def cog_unload(self):
        if self.worker:
            self.worker.cancel()
        for view in list(self.views.values()) + list(self.builders):
            view.stop()

    async def save(self, gid, pid, poll):
        await self.config.guild_from_id(gid).polls.set_raw(pid, value=poll)

    async def publish(self, interaction, builder):
        poll = copy.deepcopy(builder.poll)
        if not poll["question"] or len(poll["answers"]) < 2 or poll["limit"] > len(poll["answers"]):
            await interaction.followup.send("Set a question, at least two answers, and a vote limit no greater than the answer count.", ephemeral=True)
            return
        guild = interaction.guild
        for cid in (poll["channel"], poll["results"]):
            channel = guild.get_channel(cid)
            if not isinstance(channel, discord.TextChannel):
                await interaction.followup.send("Choose available text channels.", ephemeral=True)
                return
            bot_perms = channel.permissions_for(guild.me)
            user_perms = channel.permissions_for(interaction.user)
            if not (bot_perms.view_channel and bot_perms.send_messages and bot_perms.embed_links and user_perms.view_channel and user_perms.send_messages):
                await interaction.followup.send("You and the bot need access to send messages in both channels; the bot also needs Embed Links.", ephemeral=True)
                return
        poll["ends"] = time.time() + poll["duration"]
        try:
            message = await guild.get_channel(poll["channel"]).send(embed=poll_embed(poll), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            await interaction.followup.send("Could not post the poll. Check channel permissions and retry.", ephemeral=True)
            return
        pid = str(message.id)
        async with self.lock(guild.id, pid):
            await self.save(guild.id, pid, poll)
            view = Ballot(self, guild.id, pid, poll)
            self.views[guild.id, pid] = view
            try:
                await message.edit(view=view)
            except discord.HTTPException:
                # The worker retries attaching controls to persisted polls.
                self.dirty.add((guild.id, pid))
                log.exception("Could not attach poll controls")
        builder.stop()
        self.builders.discard(builder)
        await builder.message.edit(content=f"Poll created: {message.jump_url}", view=None)
        await interaction.followup.send(f"Poll created: {message.jump_url}", ephemeral=True)

    async def vote(self, interaction, gid, pid, index):
        await interaction.response.defer(ephemeral=True)
        async with self.lock(gid, pid):
            poll = await self.config.guild_from_id(gid).polls.get_raw(pid, default=None)
            if not poll or poll.get("closed") or poll.get("deleting") or time.time() >= poll["ends"]:
                await interaction.followup.send("This poll has ended.", ephemeral=True)
                return
            if not interaction.guild or interaction.guild.id != gid or interaction.user.bot:
                return
            if poll["roles"] and not set(poll["roles"]).intersection(role.id for role in interaction.user.roles):
                await interaction.followup.send("You do not have an allowed role for this poll.", ephemeral=True)
                return
            uid = str(interaction.user.id)
            choices = poll["votes"].get(uid, [])
            if index in choices:
                choices.remove(index)
                text = "Vote removed."
            elif len(choices) >= poll["limit"]:
                await interaction.followup.send(f"You can choose at most {poll['limit']} option(s). Remove a vote first.", ephemeral=True)
                return
            else:
                choices.append(index)
                text = "Vote recorded."
            if choices:
                poll["votes"][uid] = choices
            else:
                poll["votes"].pop(uid, None)
            await self.save(gid, pid, poll)
            try:
                await self.refresh(gid, pid, poll)
            except discord.HTTPException:
                text += " The count display will refresh shortly."
            await interaction.followup.send(text, ephemeral=True)

    async def refresh(self, gid, pid, poll):
        message = self.bot.get_partial_messageable(poll["channel"]).get_partial_message(int(pid))
        self.dirty.add((gid, pid))
        old = self.views.get((gid, pid))
        view = None
        if not poll.get("closed"):
            # Reuse the registered handler. Stopping an older view after an edit
            # can unregister the new buttons because their custom IDs are equal.
            view = old
            if view is None or view.is_finished():
                view = Ballot(self, gid, pid, poll)
                self.views[gid, pid] = view
            for button, total in zip(view.children, counts(poll)):
                button.label = str(total)
        await message.edit(embed=poll_embed(poll), view=view, allowed_mentions=discord.AllowedMentions.none())
        if view is None:
            if old:
                old.stop()
            self.views.pop((gid, pid), None)
        self.dirty.discard((gid, pid))

    async def expire(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                for gid, data in (await self.config.all_guilds()).items():
                    for pid in data["polls"]:
                        async with self.lock(gid, pid):
                            poll = await self.config.guild_from_id(gid).polls.get_raw(pid, default=None)
                            if not poll:
                                continue
                            try:
                                if poll.get("deleting"):
                                    await self.delete_poll(gid, pid, poll)
                                elif poll.get("closed") or time.time() >= poll["ends"]:
                                    await self.finish_poll(gid, pid, poll)
                                elif (gid, pid) in self.dirty:
                                    await self.refresh(gid, pid, poll)
                            except discord.HTTPException:
                                log.warning("Poll %s in guild %s could not update; retrying", pid, gid)
            except Exception:
                log.exception("Poll timer failed; retrying")
            await asyncio.sleep(5)

    async def finish_poll(self, gid, pid, poll):
        """Finalize under the poll lock; saved stages make retries safe."""
        poll["closed"] = True
        await self.save(gid, pid, poll)
        if not poll.get("finalized"):
            try:
                await self.refresh(gid, pid, poll)
            except discord.NotFound:
                pass
            poll["finalized"] = True
            await self.save(gid, pid, poll)
        if not poll.get("result_message"):
            channel = self.bot.get_partial_messageable(poll["results"])
            message = await channel.send(embed=poll_embed(poll), allowed_mentions=discord.AllowedMentions.none())
            poll["result_message"] = message.id
            await self.save(gid, pid, poll)
        # Keep only message locations so completed polls can also be deleted.
        record = {key: poll[key] for key in ("channel", "results", "result_message")}
        await self.config.guild_from_id(gid).completed.set_raw(pid, value=record)
        await self.config.guild_from_id(gid).polls.clear_raw(pid)
        self.dirty.discard((gid, pid))
        view = self.views.pop((gid, pid), None)
        if view:
            view.stop()

    async def delete_poll(self, gid, pid, poll):
        """Delete messages before clearing state; missing messages count as removed."""
        for cid, mid in ((poll["channel"], int(pid)), (poll["results"], poll.get("result_message"))):
            if not mid:
                continue
            message = self.bot.get_partial_messageable(cid).get_partial_message(mid)
            try:
                await message.delete()
            except discord.NotFound:
                pass
        group = self.config.guild_from_id(gid)
        await group.polls.clear_raw(pid)
        await group.completed.clear_raw(pid)
        view = self.views.pop((gid, pid), None)
        if view:
            view.stop()
        self.dirty.discard((gid, pid))

    async def manage_poll(self, ctx, reference, *, delete=False):
        try:
            pid = poll_reference(reference, ctx.guild.id)
        except ValueError as error:
            await ctx.send(str(error))
            return
        gid = ctx.guild.id
        async with self.lock(gid, pid):
            group = self.config.guild_from_id(gid)
            poll = await group.polls.get_raw(pid, default=None)
            if not poll and delete:
                poll = await group.completed.get_raw(pid, default=None)
            if not poll:
                await ctx.send("No saved poll found with that ID in this server. It may already have ended or been deleted.")
                return
            if not delete and poll.get("deleting"):
                await ctx.send("This poll is being deleted.")
                return
            if delete:
                # Persist cancellation first so a failed deletion never publishes results.
                poll["deleting"] = True
                await self.save(gid, pid, poll)
            try:
                if delete:
                    await self.delete_poll(gid, pid, poll)
                else:
                    await self.finish_poll(gid, pid, poll)
            except discord.HTTPException:
                await ctx.send("Voting has stopped. I couldn't finish deleting the poll; I'll retry automatically. Check my channel access."
                    if delete else "Voting has stopped. I couldn't finish updating the poll or posting results; I'll retry automatically. Check my channel access.")
                return
            await ctx.send("Poll and saved voting data deleted, including its results copy if present."
                if delete else "Poll closed and final results posted.")

    @commands.hybrid_command()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @discord.app_commands.describe(poll="Poll message ID or Discord message link")
    async def pollclose(self, ctx, *, poll: str):
        """Close a poll immediately and post results. Supply its message ID or link."""
        if ctx.interaction:
            await ctx.defer()
        await self.manage_poll(ctx, poll)

    @commands.hybrid_command()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @discord.app_commands.describe(poll="Poll message ID or Discord message link")
    async def polldelete(self, ctx, *, poll: str):
        """Delete a poll and its results copy without publishing new results."""
        if ctx.interaction:
            await ctx.defer()
        await self.manage_poll(ctx, poll, delete=True)

    async def red_delete_data_for_user(self, *, requester, user_id):
        for gid, data in (await self.config.all_guilds()).items():
            for pid in data["polls"]:
                async with self.lock(gid, pid):
                    poll = await self.config.guild_from_id(gid).polls.get_raw(pid, default=None)
                    if poll and str(user_id) in poll.get("votes", {}):
                        poll["votes"].pop(str(user_id))
                        await self.save(gid, pid, poll)
                        self.dirty.add((gid, pid))

    @commands.hybrid_command()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.bot_has_permissions(embed_links=True)
    async def pollcreate(self, ctx):
        """Open a poll builder. Only the creator can operate its controls."""
        if ctx.interaction:
            await ctx.defer()
        builder = Builder(self, ctx)
        self.builders = {b for b in self.builders if not b.is_finished()}
        self.builders.add(builder)
        builder.message = await ctx.send(embed=poll_embed(builder.poll, preview=True), view=builder,
                                         allowed_mentions=discord.AllowedMentions.none())
