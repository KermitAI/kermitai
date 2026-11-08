import asyncio
import re

import discord
from redbot.core import Config, commands


STYLES = {"primary": 1, "blurple": 1, "secondary": 2, "grey": 2, "gray": 2,
          "success": 3, "green": 3, "danger": 4, "red": 4}


def parse_options(value):
    """Parse named options without splitting spaces inside their values."""
    matches = list(re.finditer(r"(?<!\S)(label|style|emoji|roles):\s*", value, re.I))
    if not matches or value[:matches[0].start()].strip():
        raise ValueError("Use label: <label> [style: <style>] [emoji: <emoji>] [roles: <roles>].")
    options = {}
    for index, match in enumerate(matches):
        key = match[1].lower()
        if key in options:
            raise ValueError(f"Specify {key}: only once.")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        options[key] = value[match.end():end].strip()
    if not options.get("label"):
        raise ValueError("Provide label: <button label>.")
    options.setdefault("style", "secondary")
    options.setdefault("emoji", "none")
    if len(options["label"]) > 80:
        raise ValueError("Button labels can contain at most 80 characters.")
    if options["style"].lower() not in STYLES:
        raise ValueError("Style must be primary, secondary, success or danger (colour names also work).")
    options["style"] = STYLES[options["style"].lower()]
    return options


def append_entry(description, user_id, text):
    text = text.strip()
    if not text:
        raise ValueError("Enter some text.")
    result = f"{description}\n\n<@{user_id}> - {text}"
    if len(result) > 4096:
        raise ValueError("This entry will not fit. Shorten it or ask staff to create another embed.")
    return result


def allowed(member, roles):
    return isinstance(member, discord.Member) and (
        not roles or bool(set(roles).intersection(role.id for role in member.roles)))


class EntryModal(discord.ui.Modal):
    def __init__(self, cog, guild_id, message_id):
        super().__init__(title="Add to embed", timeout=600)
        self.cog, self.guild_id, self.message_id = cog, guild_id, message_id
        self.text = discord.ui.TextInput(label="Your contribution", style=discord.TextStyle.paragraph,
                                         max_length=4000, required=True)
        self.add_item(self.text)

    async def on_submit(self, interaction):
        await self.cog.submit(interaction, self.guild_id, self.message_id, self.text.value)


class AddButton(discord.ui.View):
    def __init__(self, cog, guild_id, message_id, settings):
        super().__init__(timeout=None)
        button = discord.ui.Button(label=settings["label"], style=discord.ButtonStyle(settings["style"]),
                                   emoji=settings["emoji"],
                                   custom_id=f"addembed:{guild_id}:{message_id}")
        async def callback(interaction):
            if not interaction.guild or interaction.guild.id != guild_id:
                await interaction.response.send_message("Use this button in its server.", ephemeral=True)
                return
            record = await cog.config.guild_from_id(guild_id).embeds.get_raw(str(message_id), default=None)
            if not record or not allowed(interaction.user, record["roles"]):
                await interaction.response.send_message("You do not have an allowed role for this embed.", ephemeral=True)
                return
            await interaction.response.send_modal(EntryModal(cog, guild_id, message_id))
        button.callback = callback
        self.add_item(button)


class AddEmbed(commands.Cog):
    """Let members contribute to persistent embeds using a button and modal."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=872641099325, force_registration=True)
        self.config.register_guild(embeds={})
        self.views = {}
        self.locks = {}

    async def cog_load(self):
        for guild_id, data in (await self.config.all_guilds()).items():
            for message_id, record in data["embeds"].items():
                view = AddButton(self, guild_id, int(message_id), record)
                self.bot.add_view(view, message_id=int(message_id))
                self.views[int(message_id)] = view

    def cog_unload(self):
        for view in self.views.values():
            view.stop()

    async def red_delete_data_for_user(self, *, requester, user_id):
        # Contributions live only in Discord messages, not in Config.
        pass

    @commands.command()
    @commands.guild_only()
    @commands.mod_or_permissions(administrator=True)
    async def addembed(self, ctx, channel: discord.TextChannel, title: str, description: str, *, options: str):
        """Create an editable embed. Quote the title and description.

        Example: .addembed #general "Community notes" "Add your ideas!" label: Add input style: success emoji: 📝
        Only label: is required. Style defaults to grey; emoji defaults to none.
        Append roles: @Role @OtherRole to restrict contributions.
        """
        if channel.guild.id != ctx.guild.id:
            await ctx.send("Choose a channel in this server.")
            return
        if not title.strip() or len(title) > 256 or not description.strip() or len(description) > 4096:
            await ctx.send("Use a title of 1–256 characters and a description of 1–4096 characters.")
            return
        author_perms = channel.permissions_for(ctx.author)
        bot_perms = channel.permissions_for(ctx.guild.me)
        if not author_perms.view_channel or not author_perms.send_messages:
            await ctx.send("You need permission to view and send messages in that channel.")
            return
        if not all((bot_perms.view_channel, bot_perms.send_messages, bot_perms.embed_links,
                    bot_perms.read_message_history)):
            await ctx.send("I need View Channel, Send Messages, Embed Links and Read Message History there.")
            return
        try:
            settings = parse_options(options)
            # Also accept trailing role mentions after emoji, as in the original command format.
            emoji_value = settings["emoji"]
            trailing = re.search(r"\s+(?=<@&\d+>)", emoji_value)
            role_value = settings.get("roles", "")
            if trailing:
                role_value = (role_value + " " + emoji_value[trailing.start():]).strip()
                emoji_value = emoji_value[:trailing.start()].strip()
            roles = []
            for token in re.findall(r"<@&\d+>|[^,\s]+", role_value):
                role = await commands.RoleConverter().convert(ctx, token)
                roles.append(role.id)
            settings = dict(label=settings["label"], style=settings["style"],
                            emoji=None if emoji_value.lower() == "none" else str(discord.PartialEmoji.from_str(emoji_value)),
                            roles=list(set(roles)), channel=channel.id)
            # Validate the component before sending anything.
            temporary = AddButton(self, ctx.guild.id, 0, settings)
            temporary.stop()
        except (ValueError, commands.BadArgument) as error:
            await ctx.send(str(error), allowed_mentions=discord.AllowedMentions.none())
            return
        try:
            message = await channel.send(embed=discord.Embed(title=title, description=description,
                                         colour=discord.Colour.green()),
                                         allowed_mentions=discord.AllowedMentions.none())
            view = AddButton(self, ctx.guild.id, message.id, settings)
            try:
                await self.config.guild(ctx.guild).embeds.set_raw(str(message.id), value=settings)
                await message.edit(view=view)
            except Exception:
                view.stop()
                await self.config.guild(ctx.guild).embeds.clear_raw(str(message.id))
                await message.delete()
                raise
            self.views[message.id] = view
        except discord.HTTPException:
            await ctx.send("Could not publish the embed. Check my channel permissions and the button emoji.")
            return
        await ctx.send(f"Embed created: {message.jump_url}")

    async def submit(self, interaction, guild_id, message_id, text):
        if not interaction.guild or interaction.guild.id != guild_id:
            await interaction.response.send_message("Use this modal in its server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        lock = self.locks.setdefault(message_id, asyncio.Lock())
        async with lock:
            record = await self.config.guild_from_id(guild_id).embeds.get_raw(str(message_id), default=None)
            try:
                member = await interaction.guild.fetch_member(interaction.user.id)
            except discord.HTTPException:
                await interaction.followup.send("Could not verify your current roles. Please try again.", ephemeral=True)
                return
            if not record or not allowed(member, record["roles"]):
                await interaction.followup.send("You do not have an allowed role for this embed.", ephemeral=True)
                return
            try:
                channel = interaction.guild.get_channel(record["channel"])
                if channel is None or not channel.permissions_for(member).view_channel:
                    await interaction.followup.send("This channel is unavailable to you.", ephemeral=True)
                    return
                message = await channel.fetch_message(message_id)
                if not message.embeds or message.author.id != self.bot.user.id:
                    await interaction.followup.send("The original embed is unavailable.", ephemeral=True)
                    return
                embed = message.embeds[0].copy()
                embed.description = append_entry(embed.description or "", member.id, text)
                await message.edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except ValueError as error:
                await interaction.followup.send(str(error), ephemeral=True)
                return
            except discord.HTTPException:
                await interaction.followup.send("Could not update the embed. Ask staff to check the message and my permissions.", ephemeral=True)
                return
        await interaction.followup.send("Your contribution was added.", ephemeral=True)
