import asyncio
import copy
import io
import re
import uuid
from decimal import Decimal, InvalidOperation

import discord
from redbot.core import Config, commands


def validate(kind, value):
    value = value.strip()
    if not value:
        raise ValueError("An answer is required.")
    if kind == "number":
        try:
            if not Decimal(value).is_finite():
                raise InvalidOperation
        except InvalidOperation:
            raise ValueError("Enter a valid number.") from None
    if kind == "yesno" and value.lower() not in ("yes", "no"):
        raise ValueError("Enter yes or no.")
    return value


def position(draft):
    # Migrate drafts created by the original five-question page flow.
    return draft.get("step", min(draft.get("page", 0) * 5, len(draft["form"]["questions"]) - 1))


def questionnaire_embed(draft):
    questions = draft["form"]["questions"]
    step = position(draft)
    embed = discord.Embed(title=draft["form"]["name"], colour=discord.Colour.green())
    if step < len(questions):
        q = questions[step]
        embed.description = f"Question {step + 1} of {len(questions)}\n\n{q['text']}\n\nAnswer type: {q['type']}"
        answer = draft["answers"].get(str(step))
        if answer:
            embed.add_field(name="Saved answer", value=answer[:1024], inline=False)
    else:
        embed.description = "All questions answered. Review your responses below, then submit, save for later, or go back to edit."
        # Keep the embed bounded; the complete review is attached separately.
        for i, q in enumerate(questions[:5]):
            embed.add_field(name=q["text"], value=draft["answers"].get(str(i), "Unanswered")[:700], inline=False)
    embed.set_footer(text="Answers save after each modal. Closing a modal discards unsent text.")
    return embed


def report(draft, user_id):
    lines = [f"Form: {draft['form']['name']} ({draft['form_id']})", f"Member ID: {user_id}",
             f"Submission: {draft['token']}"]
    for i, q in enumerate(draft["form"]["questions"]):
        lines.extend((f"\n{i + 1}. {q['text']}", draft["answers"].get(str(i), "Unanswered")))
    return "\n".join(lines)


class AnswerModal(discord.ui.Modal):
    def __init__(self, view, draft):
        super().__init__(title="Answer question", timeout=600)
        self.source = view
        self.step = position(draft)
        q = draft["form"]["questions"][self.step]
        self.kind = q["type"]
        self.add_item(discord.ui.TextInput(label=q["text"],
            style=discord.TextStyle.paragraph if self.kind == "paragraph" else discord.TextStyle.short,
            required=True, max_length=4000, default=draft["answers"].get(str(self.step))))

    async def on_submit(self, interaction):
        try:
            answer = validate(self.kind, self.children[0].value)
        except ValueError as error:
            await interaction.response.send_message(f"{error} Click Answer question to retry.")
            return
        await self.source.handle(interaction, "answer", (self.step, answer))


class Controls(discord.ui.View):
    def __init__(self, cog, guild_id, user_id, draft):
        super().__init__(timeout=None)
        self.cog, self.guild_id, self.user_id = cog, guild_id, user_id
        self.token, self.step = draft["token"], position(draft)
        actions = []
        if self.step < len(draft["form"]["questions"]):
            actions.append(("Answer question", "edit"))
        else:
            actions.append(("Submit", "submit"))
        if self.step:
            actions.append(("Back", "back"))
        actions.extend((("Save for later", "save"), ("Cancel", "cancel")))
        for label, action in actions:
            button = discord.ui.Button(label=label,
                custom_id=f"forms-dm:{guild_id}:{self.token}:{self.step}:{action}",
                style=discord.ButtonStyle.success if action == "submit" else discord.ButtonStyle.secondary)
            async def callback(interaction, action=action):
                await self.handle(interaction, action)
            button.callback = callback
            self.add_item(button)

    async def handle(self, interaction, action, answer=None):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This questionnaire belongs to someone else.")
            return
        async with self.cog.lock(self.guild_id, self.user_id):
            group = self.cog.config.member_from_ids(self.guild_id, self.user_id)
            draft = await group.draft()
            if not draft or draft["token"] != self.token:
                await interaction.response.send_message("This questionnaire has ended.")
                return
            if position(draft) != self.step:
                await interaction.response.send_message("Use the latest questionnaire message or reopen the server button.")
                return
            if action == "edit":
                await interaction.response.send_modal(AnswerModal(self, draft))
                return
            await interaction.response.defer()
            if action == "cancel":
                await group.draft.clear()
                await self.cog.finish(draft, "Questionnaire cancelled. Draft deleted.")
                return
            if action == "save":
                await self.cog.finish(draft, "Progress saved. Click the original server button to resume.")
                return
            if action in ("answer", "back"):
                if action == "answer":
                    step, value = answer
                    draft["answers"][str(step)] = value
                    draft["step"] = step + 1
                else:
                    draft["step"] = max(0, position(draft) - 1)
                await group.draft.set(draft)
                await self.cog.refresh(self.guild_id, self.user_id, draft)
                return
            if any(str(i) not in draft["answers"] for i in range(len(draft["form"]["questions"]))):
                await interaction.followup.send("Please answer every question before submitting.")
                return
            guild = self.cog.bot.get_guild(self.guild_id)
            channel = guild.get_channel(draft["form"]["channel"]) if guild else None
            if not isinstance(channel, discord.TextChannel):
                await interaction.followup.send("The destination channel is unavailable. Your draft is saved.")
                return
            try:
                await channel.send(content=f"Form submission from member ID {self.user_id}",
                    file=discord.File(io.BytesIO(report(draft, self.user_id).encode()), filename="form-response.txt"),
                    allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                await interaction.followup.send("Could not deliver your response. Your draft is saved; please retry.")
                return
            await group.draft.clear()
            await self.cog.finish(draft, "Your response was submitted.")


class Launch(discord.ui.View):
    def __init__(self, cog, guild_id, form_id, label):
        super().__init__(timeout=None)
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary,
                                   custom_id=f"forms:{guild_id}:{form_id}")
        async def callback(interaction):
            if not interaction.guild or interaction.guild.id != guild_id:
                return
            await interaction.response.defer(ephemeral=True)
            async with cog.lock(guild_id, interaction.user.id):
                if form_id not in await cog.config.guild(interaction.guild).forms():
                    await interaction.followup.send("This form is unavailable.", ephemeral=True)
                    return
                group = cog.config.member_from_ids(guild_id, interaction.user.id)
                draft = await group.draft()
                different = draft and draft["form_id"] != form_id
                if not draft:
                    form = (await cog.config.guild(interaction.guild).forms()).get(form_id)
                    if not form:
                        await interaction.followup.send("This form is unavailable.", ephemeral=True)
                        return
                    draft = dict(form_id=form_id, form=copy.deepcopy(form), answers={}, step=0, token=uuid.uuid4().hex)
                try:
                    dm = await interaction.user.create_dm()
                    view = Controls(cog, guild_id, interaction.user.id, draft)
                    message = await dm.send(embed=questionnaire_embed(draft), view=view,
                                            allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    await interaction.followup.send("I couldn't send you a DM. Enable direct messages from this server and try again.", ephemeral=True)
                    return
                if draft.get("message_id"):
                    try:
                        await cog.finish(draft, "Continue in the latest questionnaire message.")
                    except discord.HTTPException:
                        pass
                draft.update(dm_channel_id=dm.id, message_id=message.id)
                await group.draft.set(draft)
                cog.views.append(view)
                if position(draft) == len(draft["form"]["questions"]):
                    await cog.refresh(guild_id, interaction.user.id, draft)
                text = "Check your DMs to continue your form."
                if different:
                    text = "You have another form in progress. Check your DMs to finish or cancel it first."
                await interaction.followup.send(text, ephemeral=True)
        button.callback = callback
        self.add_item(button)


class BuilderInputModal(discord.ui.Modal):
    def __init__(self, view, prompt):
        super().__init__(title="Form builder", timeout=300)
        self.source = view
        self.add_item(discord.ui.TextInput(label=prompt[:45], style=discord.TextStyle.short,
                                          required=True, max_length=200))

    async def on_submit(self, interaction):
        view = self.source
        if interaction.user.id != view.user_id or view.is_finished():
            await interaction.response.send_message("This builder step has ended.", ephemeral=True)
            return
        value = self.children[0].value.strip()
        if not value:
            await interaction.response.send_message("Please enter a value and try again.", ephemeral=True)
            return
        view.value = value
        for item in view.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(view=view)
        finally:
            view.stop()


class BuilderInput(discord.ui.View):
    def __init__(self, user_id, prompt):
        super().__init__(timeout=300)
        self.user_id, self.prompt = user_id, prompt
        self.value = None
        self.cancelled = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the administrator building this form can answer.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Enter answer", style=discord.ButtonStyle.primary)
    async def enter(self, interaction, button):
        await interaction.response.send_modal(BuilderInputModal(self, self.prompt))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        self.cancelled = True
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        finally:
            self.stop()


class BuilderChannel(BuilderInput):
    def __init__(self, user_id):
        super().__init__(user_id, "Response channel")
        self.remove_item(self.enter)
        select = discord.ui.ChannelSelect(placeholder="Choose the response channel",
            channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
        async def callback(interaction):
            if self.is_finished():
                await interaction.response.send_message("This step has ended.", ephemeral=True)
                return
            self.value = str(select.values[0].id)
            for item in self.children:
                item.disabled = True
            try:
                await interaction.response.edit_message(view=self)
            finally:
                self.stop()
        select.callback = callback
        self.add_item(select)


class BuilderChoice(discord.ui.View):
    """One-shot choices restricted to the administrator running the builder."""
    def __init__(self, user_id, choices):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.value = None
        for label, value in choices:
            style = discord.ButtonStyle.danger if value == "cancel" else discord.ButtonStyle.primary
            button = discord.ui.Button(label=label, style=style)
            async def callback(interaction, value=value):
                if self.value is not None:
                    await interaction.response.defer()
                    return
                self.value = value
                for item in self.children:
                    item.disabled = True
                try:
                    await interaction.response.edit_message(view=self)
                finally:
                    self.stop()
            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the administrator building this form can choose these options.", ephemeral=True)
            return False
        return True


class Forms(commands.Cog):
    """Build reusable forms and attach them to bot messages."""
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=827419620503, force_registration=True)
        self.config.register_guild(forms={}, bindings={})
        self.config.register_member(draft=None)
        self.locks, self.views, self.builders = {}, [], set()
        self.builder_messages = {}

    def lock(self, guild_id, user_id):
        return self.locks.setdefault((guild_id, user_id), asyncio.Lock())

    async def cog_load(self):
        for guild_id, data in (await self.config.all_guilds()).items():
            for message_id, binding in data["bindings"].items():
                if binding["form_id"] not in data["forms"]:
                    continue
                view = Launch(self, guild_id, binding["form_id"], binding["label"])
                self.bot.add_view(view, message_id=int(message_id))
                self.views.append(view)

        for guild_id, members in (await self.config.all_members()).items():
            for user_id, data in members.items():
                draft = data.get("draft")
                if draft and draft.get("message_id"):
                    view = Controls(self, guild_id, user_id, draft)
                    self.bot.add_view(view, message_id=draft["message_id"])
                    self.views.append(view)

    async def finish(self, draft, text):
        message = self.bot.get_partial_messageable(draft["dm_channel_id"]).get_partial_message(draft["message_id"])
        await message.edit(content=text, embed=None, view=None, attachments=[], allowed_mentions=discord.AllowedMentions.none())

    async def refresh(self, guild_id, user_id, draft):
        message = self.bot.get_partial_messageable(draft["dm_channel_id"]).get_partial_message(draft["message_id"])
        view = Controls(self, guild_id, user_id, draft)
        attachments = []
        if position(draft) == len(draft["form"]["questions"]):
            attachments.append(discord.File(io.BytesIO(report(draft, user_id).encode()), filename="form-review.txt"))
        await message.edit(content=None, embed=questionnaire_embed(draft), view=view, attachments=attachments,
                           allowed_mentions=discord.AllowedMentions.none())
        self.views.append(view)

    def cog_unload(self):
        for view in self.views:
            view.stop()

    async def red_delete_data_for_user(self, *, requester, user_id):
        for guild_id, members in (await self.config.all_members()).items():
            if user_id in members:
                async with self.lock(guild_id, user_id):
                    await self.config.member_from_ids(guild_id, user_id).clear()

    @commands.hybrid_group()
    @discord.app_commands.default_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def forms(self, ctx):
        """Create, list, resume building, and attach forms."""

    async def builder_message(self, ctx, *, embed=None, view=None, text=None):
        if text is not None:
            embed = discord.Embed(title="Form builder", description=text, colour=discord.Colour.green())
        message = self.builder_messages.get(ctx.guild.id)
        if message is None:
            message = await ctx.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            self.builder_messages[ctx.guild.id] = message
        else:
            await message.edit(content=None, embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        return message

    async def ask(self, ctx, prompt, *, channel=False):
        view = BuilderChannel(ctx.author.id) if channel else BuilderInput(ctx.author.id, prompt)
        embed = discord.Embed(title="Form builder", description=prompt, colour=discord.Colour.green())
        embed.set_footer(text="Choose a channel below. Times out after 5 minutes." if channel else "Click Enter answer to open a modal. Times out after 5 minutes.")
        message = await self.builder_message(ctx, embed=embed, view=view)
        try:
            await view.wait()
        finally:
            for item in view.children:
                item.disabled = True
            view.stop()
            try:
                await message.edit(view=view)
            except discord.HTTPException:
                pass
        if view.cancelled:
            raise asyncio.CancelledError
        if view.value is None:
            raise asyncio.TimeoutError
        return view.value

    async def choose(self, ctx, title, description, choices):
        view = BuilderChoice(ctx.author.id, choices)
        embed = discord.Embed(title=title, description=description, colour=discord.Colour.green())
        embed.set_footer(text="Choose a button below. Times out after 5 minutes.")
        message = await self.builder_message(ctx, embed=embed, view=view)
        try:
            await view.wait()
        finally:
            for item in view.children:
                item.disabled = True
            view.stop()
            try:
                await message.edit(view=view)
            except discord.HTTPException:
                pass
        if view.value is None:
            raise asyncio.TimeoutError
        if view.value == "cancel":
            raise asyncio.CancelledError
        return view.value

    @forms.command(name="create")
    async def create(self, ctx):
        """Interactively create a form."""
        await self.build(ctx)

    @forms.command(name="edit")
    async def edit(self, ctx, form_id: str):
        """Resume adding questions to a saved form."""
        await self.build(ctx, form_id)

    async def build(self, ctx, form_id=None):
        if ctx.interaction:
            await ctx.defer()
        key = ctx.guild.id
        if key in self.builders:
            await ctx.send("A form builder is already open in this server.")
            return
        self.builders.add(key)
        group = self.config.guild(ctx.guild)
        try:
            existing = await group.forms()
            if form_id:
                if form_id not in existing:
                    await self.builder_message(ctx, text="Unknown form ID.")
                    return
                form = copy.deepcopy(existing[form_id])
            else:
                name = await self.ask(ctx, "What is the form name? (1–45 characters)")
                if not 1 <= len(name) <= 45:
                    await self.builder_message(ctx, text="The name must be 1–45 characters.")
                    return
                form_id = await self.ask(ctx, "What is its unique ID? Use 1–40 lowercase letters, numbers, hyphens or underscores.")
                if not re.fullmatch(r"[a-z0-9_-]{1,40}", form_id) or form_id in existing:
                    await self.builder_message(ctx, text="Invalid or already used form ID.")
                    return
                channel_text = await self.ask(ctx, "Which text channel should receive responses?", channel=True)
                channel = await commands.TextChannelConverter().convert(ctx, channel_text)
                permissions = channel.permissions_for(ctx.guild.me)
                if not all((permissions.view_channel, permissions.send_messages, permissions.attach_files)):
                    await self.builder_message(ctx, text="I need View Channel, Send Messages, and Attach Files there.")
                    return
                form = dict(name=name, channel=channel.id, questions=[])
            while True:
                question = await self.ask(ctx, "Enter the next question (1–45 characters).")
                if not 1 <= len(question) <= 45:
                    await self.builder_message(ctx, text="Questions must be 1–45 characters. Try again.")
                    continue
                kind = await self.choose(ctx, "Choose the answer type", question, (
                    ("Short text", "short"), ("Paragraph", "paragraph"),
                    ("Number", "number"), ("Yes / No", "yesno"), ("Cancel", "cancel")))
                form["questions"].append(dict(text=question, type=kind))
                while True:
                    action = await self.choose(ctx, "Question added — next step",
                        f"Form: {form['name']} ({form_id})\nQuestions: {len(form['questions'])}\n\n"
                        f"Latest question: {question}\nAnswer type: {kind}\n\n"
                        "Save checkpoints your form and keeps the builder open. Cancel discards changes since your last save.",
                        (("Save", "save"), ("Save and exit", "save and exit"),
                         ("Add another question", "add"), ("Cancel", "cancel")))
                    if action in ("save", "save and exit"):
                        async with group.forms() as saved:
                            if form_id in saved and not existing.get(form_id):
                                await self.builder_message(ctx, text="That ID was saved by another builder. Cancelled.")
                                return
                            saved[form_id] = copy.deepcopy(form)
                        existing[form_id] = copy.deepcopy(form)
                        await self.builder_message(ctx, text=f"Saved `{form_id}` with {len(form['questions'])} questions.")
                        if action == "save and exit":
                            return
                    elif action in ("add", "add another question"):
                        break
                    else:
                        await self.builder_message(ctx, text="Choose one of the listed actions.")
        except (asyncio.TimeoutError, asyncio.CancelledError):
            await self.builder_message(ctx, text="Builder ended. Any previously saved version is retained.")
        except commands.BadArgument:
            await self.builder_message(ctx, text="That channel could not be found. Builder ended.")
        finally:
            self.builders.discard(key)
            self.builder_messages.pop(key, None)

    @forms.command(name="list")
    async def list_forms(self, ctx):
        """List saved form IDs."""
        if ctx.interaction:
            await ctx.defer()
        data = await self.config.guild(ctx.guild).forms()
        lines = [f"{key}: {form['name']} ({len(form['questions'])} questions)" for key, form in data.items()]
        if not lines:
            await ctx.send("No saved forms.")
        for line in lines:
            await ctx.send(line, allowed_mentions=discord.AllowedMentions.none())

    @forms.command(name="delete")
    async def delete(self, ctx, form_id: str):
        """Delete a saved form and remove all its attached launch buttons."""
        if ctx.interaction:
            await ctx.defer()
        if ctx.guild.id in self.builders:
            await ctx.send("Finish or cancel the open form builder before deleting a form.")
            return
        # Reserve the builder slot so an edit cannot restore the deleted form.
        self.builders.add(ctx.guild.id)
        try:
            group = self.config.guild(ctx.guild)
            bindings = await group.bindings()
            linked = {key: value for key, value in bindings.items() if value["form_id"] == form_id}
            async with group.forms() as forms:
                if form_id not in forms and not linked:
                    await ctx.send("Unknown form ID.")
                    return
                forms.pop(form_id, None)
            removed, failed = [], []
            expected_id = f"forms:{ctx.guild.id}:{form_id}"
            for message_id, binding in linked.items():
                channel_id = binding.get("channel_id")
                # Older bindings did not store channel IDs. Search accessible channels
                # once, retaining unresolved bindings so cleanup can be retried.
                if channel_id:
                    channels = [ctx.guild.get_channel_or_thread(channel_id)]
                else:
                    channels = list(ctx.guild.text_channels) + list(ctx.guild.threads)
                found = False
                inaccessible = False
                for channel in channels:
                    if channel is None:
                        continue
                    try:
                        message = await channel.fetch_message(int(message_id))
                    except discord.NotFound:
                        continue
                    except discord.HTTPException:
                        inaccessible = True
                        continue
                    found = True
                    if message.author.id != self.bot.user.id:
                        failed.append(message_id)
                        break
                    try:
                        view = discord.ui.View.from_message(message, timeout=None)
                        for item in list(view.children):
                            if getattr(item, "custom_id", None) == expected_id:
                                view.remove_item(item)
                        await message.edit(view=view if view.children else None)
                    except (discord.HTTPException, ValueError):
                        failed.append(message_id)
                    else:
                        removed.append(message_id)
                    break
                if not found:
                    if inaccessible:
                        failed.append(message_id)
                    else:
                        # Already deleted messages/channels require no cleanup.
                        removed.append(message_id)
            async with group.bindings() as saved:
                for message_id in removed:
                    saved.pop(message_id, None)
            for view in self.views[:]:
                if isinstance(view, Launch) and any(
                    getattr(item, "custom_id", None) == expected_id for item in view.children
                ):
                    view.stop()
                    self.views.remove(view)
            text = f"Deleted form `{form_id}`. Cleaned up {len(removed)} linked button(s). Existing member drafts remain available in DMs."
            if failed:
                text += f" Could not remove {len(failed)} button(s). Restore channel access and run this command again to retry."
            await ctx.send(text, allowed_mentions=discord.AllowedMentions.none())
        finally:
            self.builders.discard(ctx.guild.id)

    @forms.command(name="attach")
    async def attach(self, ctx, form_id: str, message: str, *, label: str = "Open form"):
        """Attach a form: forms attach <id> <message link> [button label]."""
        if ctx.interaction:
            await ctx.defer()
        try:
            message = await commands.MessageConverter().convert(ctx, message)
        except commands.BadArgument:
            await ctx.send("I couldn't find that message. Supply its message link or ID.")
            return
        if form_id not in await self.config.guild(ctx.guild).forms():
            await ctx.send("Unknown form ID.")
            return
        if message.guild != ctx.guild or message.author.id != self.bot.user.id:
            await ctx.send("Choose a message sent by this bot in this server.")
            return
        if message.components:
            await ctx.send("That message already has components. Choose a bot message without buttons to preserve its existing controls.")
            return
        if not 1 <= len(label) <= 80:
            await ctx.send("The button label must be 1–80 characters.")
            return
        view = Launch(self, ctx.guild.id, form_id, label)
        async with self.config.guild(ctx.guild).bindings() as bindings:
            bindings[str(message.id)] = dict(form_id=form_id, label=label, channel_id=message.channel.id)
        try:
            await message.edit(view=view)
        except discord.HTTPException:
            async with self.config.guild(ctx.guild).bindings() as bindings:
                bindings.pop(str(message.id), None)
            await ctx.send("Could not edit that message.")
            return
        self.views.append(view)
        await ctx.send("Form button attached.")

