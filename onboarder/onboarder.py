import asyncio
import io
import logging
import uuid

import discord
from redbot.core import Config, commands

from .questions import QUESTIONS, FIELDS, TICKET_NOTICE, answer_text, next_step, report

log = logging.getLogger("red.onboarder")


class AnswerModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title=QUESTIONS[view.step][0], timeout=600)
        self.source = view
        for label, placeholder, required in FIELDS[view.step]:
            self.add_item(discord.ui.TextInput(
                label=label, placeholder=placeholder, required=required,
                style=discord.TextStyle.paragraph, max_length=1000,
            ))

    async def on_submit(self, interaction):
        details = {}
        for field in self.children:
            value = field.value.strip()
            if field.required and not value:
                await interaction.response.send_message("Please enter a value for every required field.", ephemeral=True)
                return
            details[field.label] = value or (
                "Use App default" if self.source.step in (2, 3, 6) else "No notification channel"
            )
        await self.source.cog.handle(interaction, self.source, "answer", details)

    async def on_error(self, interaction, error):
        log.error("Onboarder modal failed", exc_info=(type(error), error, error.__traceback__))
        if interaction.response.is_done():
            await interaction.followup.send("Could not save your answer. Please try again.", ephemeral=True)
        else:
            await interaction.response.send_message("Could not save your answer. Please try again.", ephemeral=True)


class QuestionnaireView(discord.ui.View):
    def __init__(self, cog, session):
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = session["user_id"]
        self.token = session["token"]
        self.revision = session["revision"]
        self.step = session["step"]
        if self.step == len(QUESTIONS):
            self.button("Submit answers", "submit", discord.ButtonStyle.success)
            self.button("Start over", "restart")
        elif self.step == 0:
            self.button("Enter logging channels", "form", discord.ButtonStyle.primary)
        else:
            self.button("Yes", "yes", discord.ButtonStyle.success)
            self.button("No", "no")
            if self.step in (2, 3, 6):
                self.button("Use default", "default", discord.ButtonStyle.primary)
        if self.step:
            self.button("Back", "back")
        self.button("Cancel", "cancel", discord.ButtonStyle.danger)

    def button(self, label, action, style=discord.ButtonStyle.secondary):
        button = discord.ui.Button(
            label=label, style=style,
            custom_id=f"onboarder:{self.token}:{self.revision}:{action}",
        )

        async def callback(interaction):
            await self.cog.handle(interaction, self, action)

        button.callback = callback
        self.add_item(button)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This questionnaire belongs to someone else.", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction, error, item):
        log.error("Onboarder interaction failed", exc_info=(type(error), error, error.__traceback__))
        message = "Something went wrong. Your saved progress is available; please try again."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class Onboarder(commands.Cog):
    """Collect server setup preferences through a private DM questionnaire."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=827419620502, force_registration=True)
        self.config.register_guild(channel_id=None)
        self.config.register_user(session=None)
        self.locks = {}
        self.views = {}

    def lock(self, user_id):
        return self.locks.setdefault(user_id, asyncio.Lock())

    async def cog_load(self):
        for data in (await self.config.all_users()).values():
            session = data.get("session")
            if session and session.get("message_id"):
                view = QuestionnaireView(self, session)
                self.views[session["user_id"]] = view
                self.bot.add_view(view, message_id=session["message_id"])

    def cog_unload(self):
        for view in self.views.values():
            view.stop()

    async def red_delete_data_for_user(self, *, requester, user_id):
        async with self.lock(user_id):
            await self.config.user_from_id(user_id).clear()
            view = self.views.pop(user_id, None)
            if view:
                view.stop()

    def embed(self, session):
        step = session["step"]
        embed = discord.Embed(colour=discord.Colour.green())
        if step < len(QUESTIONS):
            embed.title = f"Question {step + 1} of 9: {QUESTIONS[step][0]}"
            embed.description = QUESTIONS[step][1]
            if step in FIELDS and step != 0:
                embed.description += "\n\nChoose Yes to open a text entry form."
            if step in (2, 3, 6):
                embed.description += "\nChoose Use default, or leave the message blank in the form, to request the App's default."
        else:
            embed.title = "Review and submit"
            embed.description = "Review your answers below. The attached review contains the complete text. Use Back to change answers or Start over to begin again."
            for index, (title, _) in enumerate(QUESTIONS):
                answer = session["answers"].get(str(index))
                value = answer_text(answer) if answer else "Skipped (stream alerts declined)"
                if len(value) > 450:
                    value = value[:447] + "..."
                embed.add_field(name=f"{index + 1}. {title}", value=value, inline=False)
        embed.set_footer(text=f"Requested by {session['guild_name'][:100]} • Progress is saved until submission or cancellation")
        return embed

    async def refresh(self, session):
        view = QuestionnaireView(self, session)
        message = self.bot.get_partial_messageable(session["dm_channel_id"]).get_partial_message(session["message_id"])
        files = []
        if session["step"] == len(QUESTIONS):
            files.append(discord.File(io.BytesIO(report(session).encode("utf-8")), filename="onboarding-review.txt"))
        await message.edit(content=None, embed=self.embed(session), view=view, attachments=files,
                           allowed_mentions=discord.AllowedMentions.none())
        old = self.views.get(session["user_id"])
        if old:
            old.stop()
        self.views[session["user_id"]] = view

    def destination(self, guild_id, channel_id):
        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild and channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return None
        permissions = channel.permissions_for(guild.me)
        if not all((permissions.view_channel, permissions.send_messages, permissions.embed_links, permissions.attach_files)):
            return None
        return channel

    async def handle(self, interaction, view, action, details=None):
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("This questionnaire belongs to someone else.", ephemeral=True)
            return
        async with self.lock(view.user_id):
            group = self.config.user_from_id(view.user_id)
            session = await group.session()
            if not session or session["token"] != view.token:
                await interaction.response.send_message("This questionnaire has ended.", ephemeral=True)
                return
            if session["revision"] != view.revision:
                await interaction.response.defer()
                await self.refresh(session)
                await interaction.followup.send("Your latest question has been restored. Please use its buttons.", ephemeral=True)
                return
            if action == "form" or (action == "yes" and view.step in FIELDS):
                await interaction.response.send_modal(AnswerModal(view))
                return
            await interaction.response.defer()
            if action == "cancel":
                await group.clear()
                await interaction.edit_original_response(content="Onboarding cancelled. Your saved answers have been removed.", embed=None, view=None, attachments=[])
                self.views.pop(view.user_id, view).stop()
                return
            if action == "submit":
                channel = self.destination(session["guild_id"], session["channel_id"])
                if channel is None:
                    await interaction.followup.send("The results channel is unavailable. Your answers are saved. Ask the bot owner to restore the channel or its permissions, then retry Submit.")
                    return
                if await self.bot.cog_disabled_in_guild(self, channel.guild):
                    await interaction.followup.send("Onboarding is disabled in the requesting server. Your answers are saved; please contact the bot owner.")
                    return
                try:
                    summary = self.embed(session)
                    summary.title = "Onboarding submitted"
                    summary.description = f"Respondent: {discord.utils.escape_markdown(session['user_name'])} (ID: {session['user_id']})\nFull responses are attached."
                    await channel.send(embed=summary, file=discord.File(
                        io.BytesIO(report(session).encode("utf-8")), filename=f"onboarding-{view.user_id}.txt"),
                        allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    await interaction.followup.send("I could not deliver your answers. They are saved; please try Submit again later.")
                    return
                await group.clear()
                self.views.pop(view.user_id, view).stop()
                await interaction.edit_original_response(content="Thank you for taking the time to answer! Your responses have been submitted.", embed=None, view=None, attachments=[])
                return
            if action == "restart":
                session["answers"] = {}
                session["step"] = 0
            elif action == "back":
                previous = view.step - 1
                if previous == 6 and session["answers"].get("5", {}).get("choice") != "Yes":
                    previous -= 1
                session["step"] = max(0, previous)
            else:
                answer = {"choice": "No" if action == "no" else "Yes", "details": details or {}}
                if view.step == 0:
                    answer["choice"] = ""
                if action == "default":
                    answer["details"] = {FIELDS[view.step][0][0]: "Use App default"}
                if view.step == 7 and action == "yes":
                    answer["details"] = {"Setup": TICKET_NOTICE}
                session["answers"][str(view.step)] = answer
                if view.step == 5 and action == "no":
                    session["answers"].pop("6", None)
                session["step"] = next_step(view.step, session["answers"])
            session["revision"] += 1
            await group.session.set(session)
            await self.refresh(session)
            if view.step == 7 and action == "yes":
                await interaction.followup.send(TICKET_NOTICE)

    @commands.command()
    @commands.guild_only()
    @commands.is_owner()
    async def onboard(self, ctx, user: discord.User):
        """DM a user a setup questionnaire. Accepts a user ID or mention.

        Running this again resumes an existing questionnaire.
        """
        channel_id = await self.config.guild(ctx.guild).channel_id()
        channel = self.destination(ctx.guild.id, channel_id)
        if channel is None:
            await ctx.send("Set a results channel with `onboardset channel #channel`. I need View Channel, Send Messages, Embed Links and Attach Files there.")
            return
        if user.bot:
            await ctx.send("Please select a person rather than a bot account.")
            return
        async with self.lock(user.id):
            group = self.config.user(user)
            session = await group.session()
            if session:
                if session["guild_id"] != ctx.guild.id:
                    await ctx.send("This user already has an active questionnaire from another server.")
                    return
                session["channel_id"] = channel_id
                session["revision"] += 1
                await group.session.set(session)
                try:
                    await self.refresh(session)
                    await user.send("Your onboarding questionnaire is ready to continue above.")
                    await ctx.send("Their saved questionnaire is ready to continue.")
                    return
                except discord.NotFound:
                    pass  # Recreate a deleted questionnaire message with saved answers.
                except discord.HTTPException:
                    await ctx.send("I could not reach their DMs. Their progress is still saved.")
                    return
            else:
                session = dict(user_id=user.id, user_name=str(user), requester_id=ctx.author.id,
                               guild_id=ctx.guild.id, guild_name=ctx.guild.name,
                               channel_id=channel_id, step=0, revision=0,
                               token=uuid.uuid4().hex, answers={})
            view = QuestionnaireView(self, session)
            try:
                message = await user.send(
                    content="Please answer these questions about the bot setup you want. Your answers will be sent to the requesting server when you click Submit. You can cancel at any time.",
                    embed=self.embed(session), view=view,
                    files=[discord.File(io.BytesIO(report(session).encode("utf-8")), filename="onboarding-review.txt")] if session["step"] == len(QUESTIONS) else [],
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                view.stop()
                await ctx.send("I could not DM that user. They may need to enable DMs or share a server with me.")
                return
            session.update(message_id=message.id, dm_channel_id=message.channel.id)
            await group.session.set(session)
            old = self.views.get(user.id)
            if old:
                old.stop()
            self.views[user.id] = view
            await ctx.send("Onboarding questionnaire sent.")

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @commands.is_owner()
    async def onboardset(self, ctx):
        """Configure onboarding results."""
        await ctx.send_help()

    @onboardset.command(name="channel")
    async def set_channel(self, ctx, channel: discord.TextChannel):
        """Choose the channel for new questionnaires (use a private staff channel)."""
        if channel.guild.id != ctx.guild.id or self.destination(ctx.guild.id, channel.id) is None:
            await ctx.send("Choose a text channel in this server where I can view, send messages, embed links and attach files.")
            return
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"New onboarding responses will go to {channel.mention}. Existing questionnaires keep their destination; run onboard again for a user to update it.")

    @onboardset.command(name="show")
    async def show_settings(self, ctx):
        """Show this server's configured results channel."""
        channel_id = await self.config.guild(ctx.guild).channel_id()
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        await ctx.send(f"Results channel: {channel.mention if channel else 'Not configured or deleted'}")

    @onboardset.command(name="cancel")
    async def cancel_session(self, ctx, user: discord.User):
        """Remove a user's active questionnaire and saved answers."""
        async with self.lock(user.id):
            group = self.config.user(user)
            session = await group.session()
            if not session or session["guild_id"] != ctx.guild.id:
                await ctx.send("No active questionnaire for this user in this server.")
                return
            await group.clear()
            view = self.views.pop(user.id, None)
            if view:
                view.stop()
            try:
                message = self.bot.get_partial_messageable(session["dm_channel_id"]).get_partial_message(session["message_id"])
                await message.edit(content="This questionnaire was cancelled by the bot owner.", embed=None, view=None, attachments=[])
            except discord.HTTPException:
                pass
            await ctx.send("Questionnaire cancelled and saved answers removed.")
