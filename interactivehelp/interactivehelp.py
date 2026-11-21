import copy
import io
import json
import logging

import discord
from redbot.core import Config, commands
from redbot.core.commands.help import RedHelpFormatter

from .settings import DEFAULT, GROUPS, GROUP_LABELS, validate


log = logging.getLogger("red.kermitai.interactivehelp")


class HelpMenuOwnerRequired(commands.CheckFailure):
    """The caller is not the primary Red owner."""


class MenuView(discord.ui.View):
    def __init__(self, formatter, ctx, *, private=False):
        super().__init__(timeout=180)
        self.formatter = formatter
        self.ctx = ctx
        self.private = private

    async def interaction_check(self, interaction):
        if self.ctx.author.id == interaction.user.id and self.formatter.cog.active:
            return True
        await interaction.response.defer()
        return False

    async def navigate(self, interaction, page, *, private=False):
        opens_private = private and not self.private
        ctx = copy.copy(self.ctx)
        ctx.author = interaction.user
        if page[0] == "staff" and not await self.formatter.level(ctx):
            await interaction.response.defer()
            return
        if opens_private:
            await interaction.response.defer(ephemeral=True, thinking=True)
        else:
            await interaction.response.defer()
        menu = await self.formatter.cog.menu(ctx)
        kind = page[0]
        required = 1 if kind == "staff" else 0
        if kind == "group":
            required = page[1]
        if kind == "details":
            command = ctx.bot.get_command(page[1])
            if command:
                required = self.formatter.policy(command, menu)[1]
        if required > await self.formatter.level(ctx):
            if opens_private:
                await interaction.delete_original_response()
            return
        embed, view = await self.formatter.render(ctx, menu, page, private=self.private or private)
        await interaction.edit_original_response(embed=embed, view=view)

    def button(self, label, page, *, row=0, primary=False, private=False):
        style = discord.ButtonStyle.primary if primary else discord.ButtonStyle.secondary
        button = discord.ui.Button(label=label, row=row, style=style)

        async def callback(interaction):
            await self.navigate(interaction, page, private=private)

        button.callback = callback
        self.add_item(button)

    def select(self, placeholder, options, *, row=1, private=False):
        select = discord.ui.Select(
            placeholder=placeholder, row=row,
            options=[discord.SelectOption(label=label[:100], value=str(i))
                     for i, (label, _) in enumerate(options)],
        )

        async def callback(interaction):
            await self.navigate(interaction, options[int(interaction.data["values"][0])][1],
                                private=private)

        select.callback = callback
        self.add_item(select)


class InteractiveFormatter(RedHelpFormatter):
    def __init__(self, cog):
        self.cog = cog

    async def level(self, ctx):
        if await self.cog.is_primary_owner(ctx.author):
            return 4
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return 0
        if ctx.author.id == ctx.guild.owner_id:
            return 3
        roles = {role.id for role in ctx.author.roles}
        if (ctx.author.guild_permissions.administrator
                or roles.intersection(await ctx.bot.get_admin_role_ids(ctx.guild.id))):
            return 2
        return int(bool(roles.intersection(await ctx.bot.get_mod_role_ids(ctx.guild.id))))

    def policy(self, command, menu):
        chain = []
        while command:
            chain.append(command)
            command = command.parent
        level = 4 if command.cog is self.cog else 0
        hidden = False
        override = {}
        explicit_category = None
        for item in reversed(chain):
            override = menu["overrides"].get(item.qualified_name, {})
            if "category" in override:
                explicit_category = override["category"]
            privilege = getattr(getattr(item, "requires", None), "privilege_level", None)
            level = max(level, GROUPS.index(override.get("group", "public")), {
                "MOD": 1, "ADMIN": 2, "GUILD_OWNER": 3, "BOT_OWNER": 4,
            }.get(getattr(privilege, "name", ""), 0))
            hidden |= override.get("hidden", False) or item.hidden
        item = chain[0]
        if explicit_category is not None:
            return explicit_category, level, hidden, override
        for candidate in chain:
            for category in menu["categories"]:
                if candidate.qualified_name in category["commands"]:
                    return category["id"], level, hidden, override
        for category in menu["categories"]:
            if item.cog_name in category["cogs"]:
                return category["id"], level, hidden, override
        return "other", level, hidden, override

    async def visible(self, ctx, command):
        while command:
            if not command.is_enabled(ctx.guild):
                return False
            if command.cog and ctx.guild and await ctx.bot.cog_disabled_in_guild(
                command.cog, ctx.guild
            ):
                return False
            try:
                if not await command.can_see(ctx):
                    return False
            except commands.CommandError:
                return False
            command = command.parent
        return True

    async def entries(self, ctx, menu, target_level, category=None, cog=None):
        result = []
        for command in sorted(set(ctx.bot.walk_commands()), key=lambda item: item.qualified_name):
            key, level, hidden, override = self.policy(command, menu)
            if hidden or level != target_level or (category and category != key):
                continue
            if cog is not None and command.cog_name != cog:
                continue
            if await self.visible(ctx, command):
                result.append((command, override))
        return result

    def embed(self, menu, title=None, description=None):
        return discord.Embed(title=title or menu["title"], description=description,
                             colour=int(menu["colour"][1:], 16))

    async def render(self, ctx, menu, page, *, private=False):
        kind, *args = page
        view = MenuView(self, ctx, private=private)
        categories = menu["categories"] + [{"id": "other", "label": "Other Commands"}]
        labels = {category["id"]: category["label"] for category in categories}
        if kind == "home":
            lines = [menu["intro"]]
            for category in categories:
                if category.get("pinned"):
                    view.button(category["label"], ("category", category["id"], 0), primary=True,
                                private=True)
                    if category.get("description"):
                        lines.append(f"**{category['label']}** · {category['description']}")
            view.select("All Categories", [
                (category["label"], ("category", category["id"], 0)) for category in categories
            ], private=True)
            if ctx.guild:
                view.button("Staff Help", ("staff",), row=2, private=True)
            return self.embed(menu, description="\n".join(lines)), view

        if kind == "staff":
            level = await self.level(ctx)
            for index in range(4, 0, -1):
                if level >= index:
                    view.button(GROUP_LABELS[index], ("group", index, 0), primary=True)
            if level:
                return self.embed(menu, "Staff Help", "Choose a permission group."), view
        elif kind == "details":
            name, back = args
            command = ctx.bot.get_command(name)
            if command:
                _, level, hidden, override = self.policy(command, menu)
                if (not hidden and (not level or private and level <= await self.level(ctx))
                        and await self.visible(ctx, command)):
                    description = override.get("description") or command.format_help_for_context(ctx)
                    embed = self.embed(menu, command.qualified_name[:256],
                                       (description or "No description provided.")[:3400])
                    signature = self.get_command_signature(ctx, command).strip()
                    embed.add_field(name="Usage", value=discord.utils.escape_markdown(
                        signature[:950]), inline=False)
                    if override.get("example"):
                        example = override["example"].replace("[p]", ctx.clean_prefix)
                        embed.add_field(name="Example", value=example[:1000], inline=False)
                    view.button("Back", back)
                    return embed, view
        else:
            key, index = args
            level = key if kind == "group" else 0
            if not level or (private and level <= await self.level(ctx)):
                category = key if kind == "category" else None
                cog = key if kind == "cog" else None
                rows = await self.entries(ctx, menu, level, category=category, cog=cog)
                max_index = max(0, (len(rows) - 1) // 8)
                index = min(index, max_index)
                current = rows[index * 8:(index + 1) * 8]
                title = GROUP_LABELS[level] if level else labels.get(key, key)
                lines = []
                for command, override in current:
                    summary = override.get("description") or command.short_doc or "View usage"
                    lines.append(f"**{discord.utils.escape_markdown(command.qualified_name)[:180]}**"
                                 f" · {summary.splitlines()[0][:130]}")
                embed = self.embed(menu, title[:256], "\n".join(lines) or "No commands here.")
                embed.set_footer(text=f"Page {index + 1} of {max_index + 1}")
                if current:
                    view.select("Command Details", [
                        (command.qualified_name, ("details", command.qualified_name,
                                                  (kind, key, index)))
                        for command, _ in current
                    ], private=True)
                view.button("Back" if level else "Home", ("staff",) if level else ("home",))
                if index:
                    view.button("Previous", (kind, key, index - 1))
                if index < max_index:
                    view.button("Next", (kind, key, index + 1))
                return embed, view
        view.button("Home", ("home",))
        return self.embed(menu, "Help unavailable", "No matching help entry is available."), view

    async def send_help(self, ctx, help_for=None, *, from_help_command=False):
        if ctx.guild and not ctx.channel.permissions_for(ctx.me).embed_links:
            await ctx.send("Interactive help requires the Embed Links permission in this channel.")
            return
        menu = await self.cog.menu(ctx)
        target = help_for
        if isinstance(target, str):
            target = ctx.bot.get_command(" ".join(target.split())) or ctx.bot.get_cog(target)
        if isinstance(target, commands.Command):
            _, level, hidden, _ = self.policy(target, menu)
            if hidden or level > await self.level(ctx) or not await self.visible(ctx, target):
                await ctx.send("No matching help entry is available.")
                return
            # Resolve access again in the private interaction before displaying any details.
            view = MenuView(self, ctx)
            view.button("Open Command Help", ("details", target.qualified_name, ("home",)),
                        primary=True, private=True)
            await ctx.send(embed=self.embed(menu, "Command Help"), view=view)
            return
        if isinstance(target, commands.Cog):
            view = MenuView(self, ctx)
            view.button("Open Category Help", ("cog", target.qualified_name, 0),
                        primary=True, private=True)
            await ctx.send(embed=self.embed(menu, "Category Help"), view=view)
            return
        elif help_for:
            await ctx.send("No matching help entry is available.")
            return
        else:
            page = ("home",)
        embed, view = await self.render(ctx, menu, page)
        await ctx.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())


class InteractiveHelp(commands.Cog):
    """Interactive help and its owner-only server settings."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=941620174225037, force_registration=True)
        self.config.register_guild(settings={"published": DEFAULT, "draft": None, "previous": None})
        self.formatter = InteractiveFormatter(self)
        self.active = False

    async def cog_load(self):
        self.bot.set_help_formatter(self.formatter)
        self.active = True

    def cog_unload(self):
        if self.active:
            self.active = False
            if getattr(self.bot, "_help_formatter", None) is self.formatter:
                self.bot.reset_help_formatter()

    async def is_primary_owner(self, member):
        # Red keeps the configured primary owner separately from its co-owner set.
        owner_id = getattr(self.bot, "_owner_id_overwrite", None)
        if owner_id is None:
            application = self.bot.application
            owner_id = getattr(getattr(application, "owner", None), "id", None)
        return member.id == owner_id and await self.bot.is_owner(member)

    async def cog_check(self, ctx):
        if not await self.is_primary_owner(ctx.author):
            raise HelpMenuOwnerRequired()
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    async def cog_command_error(self, ctx, error):
        if isinstance(error, HelpMenuOwnerRequired):
            message = "Only the primary bot owner can manage the help menu."
        elif isinstance(error, commands.NoPrivateMessage):
            message = "Run this command in the server whose help menu you want to edit."
        elif isinstance(error, commands.UserInputError):
            prefix = ctx.clean_prefix
            command = ctx.command
            usage = f"{prefix}{command.qualified_name} {command.signature}".rstrip()
            message = f"{error}\nUsage: `{usage}`"
        elif isinstance(error, commands.DisabledCommand):
            message = "This help menu command is disabled."
        elif isinstance(error, commands.CheckFailure):
            message = "A Red permission check blocked this help menu command."
        else:
            original = getattr(error, "original", error)
            log.error("Help menu command failed", exc_info=original)
            message = "The help menu command failed. Check the Red console for details."
        await ctx.send(message, allowed_mentions=discord.AllowedMentions.none())

    async def menu(self, ctx):
        if ctx.guild:
            return (await self.settings(ctx))["published"]
        return DEFAULT

    def draft(self, state):
        return state["draft"] or state["published"]

    def settings(self, ctx):
        # Supply mapping defaults for Red’s recursive merge of saved menus.
        defaults = {"published": copy.deepcopy(DEFAULT), "draft": {}, "previous": {}}
        return self.config.guild(ctx.guild).settings(default=defaults)

    @commands.group(name="helpmenu", invoke_without_command=True)
    async def helpmenu(self, ctx):
        """Edit and publish this server's help menu."""
        prefix = ctx.clean_prefix
        if ctx.subcommand_passed and ctx.invoked_subcommand is None:
            await ctx.send(f"Unknown help menu command. Use `{prefix}helpmenu` to see the options.")
            return
        await ctx.send(
            f"**Help Menu Editor**\n"
            f"\x60{prefix}helpmenu title <text>\x60 · Set the title\n"
            f"\x60{prefix}helpmenu intro <text>\x60 · Set the introduction\n"
            f"\x60{prefix}helpmenu colour <#RRGGBB>\x60 · Set the accent\n"
            f"\x60{prefix}helpmenu category <id> <true|false> <label>\x60 · Add or rename a category\n"
            f"\x60{prefix}helpmenu assign <category> <group> <command>\x60 · Assign a command\n"
            f"\x60{prefix}helpmenu preview\x60 / \x60publish\x60 / \x60rollback\x60\n"
            f"\x60{prefix}helpmenu export [published|draft]\x60 / \x60import\x60 (attach JSON)"
        )

    async def edit_draft(self, ctx, edit):
        try:
            async with self.settings(ctx) as state:
                menu = copy.deepcopy(self.draft(state))
                edit(menu)
                state["draft"] = validate(menu)
        except ValueError as exc:
            await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
            return
        await ctx.send(
            f"Draft updated. Use `{ctx.clean_prefix}helpmenu preview` to review it "
            f"or `{ctx.clean_prefix}helpmenu publish` to make it live."
        )

    @helpmenu.command()
    async def title(self, ctx, *, title: str):
        """Set the draft title."""
        await self.edit_draft(ctx, lambda menu: menu.update(title=title))

    @helpmenu.command()
    async def intro(self, ctx, *, intro: str = ""):
        """Set or clear the draft introduction."""
        await self.edit_draft(ctx, lambda menu: menu.update(intro=intro))

    @helpmenu.command(aliases=["color"])
    async def colour(self, ctx, colour: str):
        """Set the draft accent colour."""
        await self.edit_draft(ctx, lambda menu: menu.update(colour=colour))

    @helpmenu.command()
    async def category(self, ctx, category_id: str, pinned: bool, *, label: str):
        """Add a category or change its label and pinned state."""
        def edit(menu):
            for category in menu["categories"]:
                if category["id"] == category_id:
                    category.update(label=label, pinned=pinned)
                    return
            menu["categories"].append(
                dict(id=category_id, label=label, pinned=pinned, cogs=[], commands=[])
            )

        await self.edit_draft(ctx, edit)

    @helpmenu.command()
    async def assign(self, ctx, category_id: str, group: str, *, command_name: str):
        """Assign a command to a category and set its minimum help access."""
        command = ctx.bot.get_command(command_name)
        if command is None:
            await ctx.send("That command could not be found.")
            return

        def edit(menu):
            entry = menu["overrides"].setdefault(command.qualified_name, {})
            entry.update(category=category_id, group=group)

        await self.edit_draft(ctx, edit)

    @helpmenu.command()
    async def preview(self, ctx):
        """Review the draft home screen in a DM."""
        menu = self.draft(await self.settings(ctx))
        embed, _ = await self.formatter.render(ctx, menu, ("home",))
        pinned = [cat["label"] for cat in menu["categories"] if cat["pinned"]]
        embed.add_field(name="Pinned categories", value=("\n".join(pinned) or "None"))
        embed.set_footer(text=f"Draft · {ctx.guild.name}"[:200])
        try:
            await ctx.author.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            await ctx.send("Enable DMs from this server to receive the preview.")
        else:
            await ctx.send("Draft preview sent by DM.")

    @helpmenu.command()
    async def export(self, ctx, source: str = "published"):
        """Send the published menu or draft as an editable JSON file by DM."""
        if source not in {"published", "draft"}:
            await ctx.send("Choose published or draft.")
            return
        state = await self.settings(ctx)
        data = state["published"] if source == "published" else self.draft(state)
        payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        try:
            await ctx.author.send(file=discord.File(io.BytesIO(payload), "help-menu.json"))
        except discord.Forbidden:
            await ctx.send("Enable DMs from this server to receive the export.")
        else:
            await ctx.send("JSON export sent by DM.")

    @helpmenu.command(name="import")
    async def import_menu(self, ctx):
        """Validate an attached JSON file and save it as a draft."""
        if len(ctx.message.attachments) != 1:
            await ctx.send("Attach one help-menu.json file to the command.")
            return
        attachment = ctx.message.attachments[0]
        if not attachment.filename.lower().endswith(".json") or attachment.size > 262144:
            await ctx.send("Attach a JSON file of 256 KiB or less.")
            return
        try:
            data = validate(json.loads((await attachment.read()).decode("utf-8-sig")))
        except (ValueError, RecursionError, discord.HTTPException):
            await ctx.send("The attachment could not be read as a valid version 1 menu.")
            return

        def edit(menu):
            menu.clear()
            menu.update(data)

        unknown = {name for category in data["categories"] for name in category["commands"]}
        unknown.update(data["overrides"])
        missing = sum(ctx.bot.get_command(name) is None for name in unknown)
        missing_cogs = {name for category in data["categories"] for name in category["cogs"]
                        if ctx.bot.get_cog(name) is None}
        await self.edit_draft(ctx, edit)
        if missing or missing_cogs:
            await ctx.send(f"Kept references to {missing} unavailable command(s) and "
                           f"{len(missing_cogs)} unloaded cog(s).")

    @helpmenu.command()
    async def publish(self, ctx):
        """Make the current draft live."""
        async with self.settings(ctx) as state:
            changed = bool(state["draft"])
            if changed:
                state.update(previous=state["published"], published=state["draft"], draft={})
        await ctx.send("Help menu published." if changed else "There is no draft to publish.")

    @helpmenu.command()
    async def rollback(self, ctx):
        """Restore the previous published menu."""
        async with self.settings(ctx) as state:
            changed = bool(state["previous"])
            if changed:
                state["published"], state["previous"] = state["previous"], state["published"]
        await ctx.send("Previous help menu restored." if changed else "No previous menu is saved.")

