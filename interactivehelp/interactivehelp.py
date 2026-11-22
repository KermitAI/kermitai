import asyncio
import copy
import io
import json
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass

import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.commands.help import RedHelpFormatter

from .settings import DEFAULT, GROUPS, GROUP_LABELS, validate


log = logging.getLogger("red.kermitai.interactivehelp")
CUSTOM_EMOJI_PREFIX = re.compile(r"^<a?:(?P<name>\w+):(?P<id>[0-9]{1,20})>\s*")
UNICODE_EMOJI_PREFIX = re.compile(
    r"^([\U0001F000-\U0001FAFF\u2194-\u21FF\u2300-\u23FF\u25A0-\u27BF\u2B00-\u2BFF]"
    r"(?:[\ufe0f\U0001F3FB-\U0001F3FF\u200d\U0001F000-\U0001FAFF\u2194-\u21FF"
    r"\u2300-\u23FF\u25A0-\u27BF\u2B00-\u2BFF])*)\s+"
)


class HelpMenuSettingsBusy(commands.CommandError):
    """The server settings lock could not be acquired."""


class HelpMenuOwnerRequired(commands.CheckFailure):
    """The caller is not the primary Red owner."""


@dataclass
class CustomHelpCommand:
    qualified_name: str
    cog: commands.Cog
    short_doc: str = "Server custom command"

    parent = None
    hidden = False

    @property
    def cog_name(self):
        return self.cog.qualified_name


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
        try:
            await asyncio.wait_for(
                self.show_page(interaction, ctx, page, opens_private=opens_private),
                timeout=15,
            )
        except asyncio.TimeoutError:
            log.warning("Help menu navigation timed out (%s)", page[0])
            await self.navigation_error(interaction, opens_private,
                                        "This help page took too long to load. Please try again.")
        except Exception:
            log.exception("Help menu navigation failed (%s)", page[0])
            await self.navigation_error(interaction, opens_private,
                                        "This help page couldn't load. Check the Red console for details.")

    async def navigation_error(self, interaction, opens_private, message):
        try:
            if opens_private:
                await interaction.edit_original_response(content=message, embed=None, view=None)
            else:
                await interaction.followup.send(message, ephemeral=True)
        except discord.HTTPException:
            log.warning("Could not send help menu navigation error", exc_info=True)

    async def show_page(self, interaction, ctx, page, *, opens_private):
        menu = await self.formatter.cog.menu()
        kind = page[0]
        required = 1 if kind == "staff" else 0
        if kind == "group":
            required = page[1]
        if kind == "category" and page[1] == "other":
            required = 4
        if kind == "details":
            command = await self.formatter.find_command(ctx, page[1])
            if command:
                required = self.formatter.detail_level(command, menu)
        if required and required > await self.formatter.level(ctx):
            if opens_private:
                await interaction.delete_original_response()
            return
        embed, view = await self.formatter.render(
            ctx, menu, page, private=self.private or opens_private
        )
        await interaction.edit_original_response(embed=embed, view=view)

    def component_label(self, label):
        match = CUSTOM_EMOJI_PREFIX.match(label)
        if match:
            emoji = self.ctx.bot.get_emoji(int(match["id"]))
            return label[match.end():] or match["name"], emoji if emoji and emoji.is_usable() else None

        match = UNICODE_EMOJI_PREFIX.match(label)
        if match and label[match.end():]:
            return label[match.end():], match[1]
        return label, None

    def button(self, label, page, *, row=0, primary=False, private=False):
        style = discord.ButtonStyle.primary if primary else discord.ButtonStyle.secondary
        label, emoji = self.component_label(label)
        button = discord.ui.Button(label=label, emoji=emoji, row=row, style=style)

        async def callback(interaction):
            await self.navigate(interaction, page, private=private)

        button.callback = callback
        self.add_item(button)

    def select(self, placeholder, options, *, row=1, private=False):
        select_options = []
        for index, (label, _) in enumerate(options):
            label, emoji = self.component_label(label)
            select_options.append(discord.SelectOption(label=label[:100], emoji=emoji,
                                                       value=str(index)))
        select = discord.ui.Select(placeholder=placeholder, row=row, options=select_options)

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
        level = 4 if chain[0].cog is self.cog else 0
        hidden = False
        override = {}
        explicit_category = None
        staff = menu.get("staff")
        for item in reversed(chain):
            override = menu["overrides"].get(item.qualified_name, {})
            if "category" in override:
                explicit_category = override["category"]
            privilege = getattr(getattr(item, "requires", None), "privilege_level", None)
            group = override.get("group", "public")
            if staff is not None:
                group = next((key for key, names in staff.items() if item.qualified_name in names),
                             group)
            level = max(level, GROUPS.index(group), {
                "MOD": 1, "ADMIN": 2, "GUILD_OWNER": 3, "BOT_OWNER": 4,
            }.get(getattr(privilege, "name", ""), 0))
            hidden |= override.get("hidden", False) or item.hidden
        item = chain[0]
        if staff is not None and level:
            hidden |= not any(item.qualified_name in names for names in staff.values())
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

    async def custom_commands(self, ctx):
        tags = ctx.bot.get_cog("Tags")
        get_unique_tags = getattr(tags, "get_unique_tags", None)
        if callable(get_unique_tags):
            invoke = ctx.bot.get_command("invoketag")
            if invoke is not None and invoke.cog is tags and await self.visible(ctx, invoke):
                scopes = (None, ctx.guild) if ctx.guild else (None,)
                names = {
                    name
                    for guild in scopes
                    for tag in get_unique_tags(guild)
                    for name in (tag.name, *tag.aliases)
                }
                return {name: CustomHelpCommand(name, tags, "Tag command")
                        for name in names if ctx.bot.get_command(name) is None}

        cog = ctx.bot.get_cog("CustomCommands")
        if ctx.guild is None or cog is None or await ctx.bot.cog_disabled_in_guild(cog, ctx.guild):
            return {}
        return {name: CustomHelpCommand(name, cog)
                for name in await cog.get_command_names(ctx.guild)
                if ctx.bot.get_command(name) is None}

    async def find_command(self, ctx, name):
        command = ctx.bot.get_command(name)
        return command if command is not None else (await self.custom_commands(ctx)).get(name)

    def detail_level(self, command, menu):
        category, level, _, _ = self.policy(command, menu)
        return 4 if category == "other" and level == 0 else level

    async def visible(self, ctx, command):
        if isinstance(command, CustomHelpCommand):
            return True
        target = command
        try:
            while command:
                if not command.is_enabled(ctx.guild):
                    return False
                if command.cog and ctx.guild and await ctx.bot.cog_disabled_in_guild(
                    command.cog, ctx.guild
                ):
                    return False
                if not await command.can_see(ctx):
                    return False
                command = command.parent
        except commands.CommandError:
            return False
        except Exception:
            log.exception("Could not check help visibility for %s", target.qualified_name)
            return False
        return True

    async def known_commands(self, ctx):
        registered = set(ctx.bot.walk_commands())
        custom = await self.custom_commands(ctx)
        return sorted([*registered, *custom.values()], key=lambda item: item.qualified_name)

    async def entries(self, ctx, menu, target_level, category=None, cog=None):
        result = []
        for command in await self.known_commands(ctx):
            key, level, hidden, override = self.policy(command, menu)
            if hidden or level != target_level or (category and category != key):
                continue
            if key == "other" and level == 0 and category != "other":
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
        categories = menu["categories"]
        labels = {category["id"]: category["label"] for category in categories}
        labels["other"] = "Other Commands"
        if kind == "home":
            lines = [menu["intro"]]
            for category in categories:
                if category.get("pinned"):
                    view.button(category["label"], ("category", category["id"], 0), primary=True,
                                private=True)
                    if category.get("description"):
                        lines.append(f"**{category['label']}** · {category['description']}")
            if categories:
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
            command = await self.find_command(ctx, name)
            if command:
                _, _, hidden, override = self.policy(command, menu)
                level = self.detail_level(command, menu)
                if (not hidden and (not level or private and level <= await self.level(ctx))
                        and await self.visible(ctx, command)):
                    if isinstance(command, CustomHelpCommand):
                        description = command.short_doc
                        signature = f"{ctx.clean_prefix}{command.qualified_name}"
                    else:
                        description = command.format_help_for_context(ctx)
                        signature = self.get_command_signature(ctx, command).strip()
                    description = override.get("description") or description
                    embed = self.embed(menu, command.qualified_name[:256],
                                       (description or "No description provided.")[:3400])
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
            owner_only = kind == "category" and key == "other"
            required = 4 if owner_only else level
            if not required or (private and required <= await self.level(ctx)):
                category = key if kind == "category" else None
                cog = key if kind == "cog" else None
                rows = await self.entries(ctx, menu, level, category=category, cog=cog)
                max_index = max(0, (len(rows) - 1) // 8)
                index = min(index, max_index)
                current = rows[index * 8:(index + 1) * 8]
                title = GROUP_LABELS[level] if level else labels.get(key, key)
                lines = []
                for command, override in current:
                    summary = (override.get("description") or command.short_doc or "").strip()
                    summary = summary.splitlines()[0] if summary else "View usage"
                    lines.append(f"**{discord.utils.escape_markdown(command.qualified_name)[:180]}**"
                                 f" · {summary[:130]}")
                embed = self.embed(menu, title[:256], "\n".join(lines) or "No commands here.")
                embed.set_footer(text=f"Page {index + 1} of {max_index + 1}")
                if current:
                    view.select("Command Details", [
                        (command.qualified_name, ("details", command.qualified_name,
                                                  (kind, key, index)))
                        for command, _ in current
                    ], private=True)
                if owner_only:
                    view.button("Back", ("group", 4, 0))
                elif level:
                    view.button("Back", ("staff",))
                    if level == 4:
                        view.button("Other Commands", ("category", "other", 0))
                else:
                    view.button("Home", ("home",))
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
        menu = await self.cog.menu()
        target = help_for
        if isinstance(target, str):
            target = await self.find_command(ctx, " ".join(target.split())) or ctx.bot.get_cog(target)
        if isinstance(target, (commands.Command, CustomHelpCommand)):
            _, _, hidden, _ = self.policy(target, menu)
            level = self.detail_level(target, menu)
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
    """Interactive help and its owner-only global settings."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=941620174225037, force_registration=True)
        self.config.register_global(settings={})
        self.formatter = InteractiveFormatter(self)
        self.active = False

    async def cog_load(self):
        await self.migrate_guild_menus()
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
        elif isinstance(error, HelpMenuSettingsBusy):
            message = "The help menu settings are busy. If this persists, restart Red and retry."
        elif isinstance(error, commands.NoPrivateMessage):
            message = "Run this command in any server to edit the global help menu."
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

    async def menu(self):
        return (await self.settings())["published"]

    def legacy_state(self, data):
        saved = data.get("settings", {})
        return {
            "published": saved.get("published") or DEFAULT,
            "draft": saved.get("draft") or {},
            "previous": saved.get("previous") or {},
        }

    async def migrate_guild_menus(self):
        async with self.writable_settings() as state:
            if state["migrated"]:
                return
            candidates = []
            for guild_data in (await self.config.all_guilds()).values():
                legacy = self.legacy_state(guild_data)
                if legacy["published"] != DEFAULT or legacy["draft"] or legacy["previous"]:
                    candidates.append(legacy)
            if candidates and all(candidate == candidates[0] for candidate in candidates):
                state.update(candidates[0])
            elif candidates:
                log.warning(
                    "Multiple legacy help menus differ. Use helpmenu migrate in the source "
                    "server, then publish the draft to make it global."
                )
            state["migrated"] = True

    def draft(self, state):
        return state["draft"] or state["published"]

    def settings(self, *, acquire_lock=True):
        defaults = {"published": copy.deepcopy(DEFAULT), "draft": {}, "previous": {},
                    "migrated": False}
        return self.config.settings(default=defaults, acquire_lock=acquire_lock)

    @asynccontextmanager
    async def writable_settings(self):
        lock = self.config.settings.get_lock()
        try:
            await asyncio.wait_for(lock.acquire(), timeout=10)
        except asyncio.TimeoutError as error:
            raise HelpMenuSettingsBusy() from error
        try:
            async with self.settings(acquire_lock=False) as state:
                yield state
        finally:
            lock.release()

    @app_commands.command(name="help", description="Browse the interactive help menu.")
    @app_commands.describe(command="A prefix command or tag to look up")
    async def slash_help(self, interaction: discord.Interaction, command: str = None):
        await interaction.response.defer()
        ctx = await self.bot.get_context(interaction)
        prefixes = await self.bot.get_valid_prefixes(interaction.guild)
        ctx.prefix = prefixes[0] if prefixes else ""
        await self.formatter.send_help(ctx, command, from_help_command=True)

    @commands.group(name="helpmenu", invoke_without_command=True)
    async def helpmenu(self, ctx):
        """Edit and publish the bot-wide help menu."""
        prefix = ctx.clean_prefix
        if ctx.subcommand_passed and ctx.invoked_subcommand is None:
            await ctx.send(f"Unknown help menu command. Use `{prefix}helpmenu` to see the options.")
            return
        await ctx.send(
            f"**Global Help Menu Editor**\n"
            f"\x60{prefix}helpmenu title <text>\x60 · Set the title\n"
            f"\x60{prefix}helpmenu intro <text>\x60 · Set the introduction\n"
            f"\x60{prefix}helpmenu colour <#RRGGBB>\x60 · Set the accent\n"
            f"\x60{prefix}helpmenu category <id> <true|false> <label>\x60 · Add or rename a category\n"
            f"\x60{prefix}helpmenu assign <category> <group> <command>\x60 · Assign a command\n"
            f"\x60{prefix}helpmenu preview\x60 / \x60publish\x60 / \x60rollback\x60\n"
            f"\x60{prefix}helpmenu export [published|draft]\x60 / \x60import\x60 (attach JSON)\n"
            f"\x60{prefix}helpmenu migrate [published|draft]\x60 · Stage a legacy server menu"
        )

    async def edit_draft(self, ctx, edit):
        try:
            async with self.writable_settings() as state:
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
        if group not in GROUPS:
            await ctx.send("Choose public, moderator, administrator, guild_owner, or bot_owner.")
            return
        command = await self.formatter.find_command(ctx, command_name)
        if command is None:
            await ctx.send("That command could not be found.")
            return

        def edit(menu):
            entry = menu["overrides"].setdefault(command.qualified_name, {})
            entry.update(category=category_id, group=group)
            staff = menu.get("staff")
            if staff is not None:
                for names in staff.values():
                    if command.qualified_name in names:
                        names.remove(command.qualified_name)
                if group != "public":
                    staff.setdefault(group, []).append(command.qualified_name)

        await self.edit_draft(ctx, edit)

    @helpmenu.command()
    async def preview(self, ctx):
        """Review the draft home screen in a DM."""
        menu = self.draft(await self.settings())
        embed, _ = await self.formatter.render(ctx, menu, ("home",))
        pinned = [cat["label"] for cat in menu["categories"] if cat["pinned"]]
        embed.add_field(name="Pinned categories", value=("\n".join(pinned) or "None"))
        embed.set_footer(text="Global draft")
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
        state = await self.settings()
        data = state["published"] if source == "published" else self.draft(state)
        data = copy.deepcopy(data)
        if "staff" not in data:
            staff = {group: set() for group in GROUPS[1:]}
            known = await self.formatter.known_commands(ctx)
            commands_by_name = {command.qualified_name for command in known}
            for command in known:
                _, level, hidden, _ = self.formatter.policy(command, data)
                if level and not hidden:
                    staff[GROUPS[level]].add(command.qualified_name)
            for name, override in data["overrides"].items():
                group = override.get("group", "public")
                if name not in commands_by_name and group != "public" and not override.get("hidden"):
                    staff[group].add(name)
            data["staff"] = {group: sorted(names) for group, names in staff.items()}
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
            payload = await asyncio.wait_for(attachment.read(), timeout=20)
        except asyncio.TimeoutError:
            await ctx.send("Discord took too long to download the JSON file. Attach it again and retry.")
            return
        except discord.HTTPException as error:
            log.warning("Help menu attachment download failed (HTTP %s)", error.status)
            await ctx.send(
                "Discord could not download the attachment. Attach the file directly to a new "
                "import command and try again."
            )
            return

        try:
            menu = json.loads(payload.decode("utf-8-sig"))
        except UnicodeDecodeError:
            await ctx.send("Save the JSON file as UTF-8 and try again.")
            return
        except json.JSONDecodeError as error:
            await ctx.send(
                f"Invalid JSON at line {error.lineno}, column {error.colno}. {error.msg}."
            )
            return
        except (RecursionError, ValueError):
            await ctx.send("The JSON is too deeply nested or contains a number that is too large.")
            return

        try:
            data = validate(menu)
        except ValueError as error:
            await ctx.send(f"Invalid help menu. {error}", allowed_mentions=discord.AllowedMentions.none())
            return

        def edit(menu):
            menu.clear()
            menu.update(data)

        unknown = {name for category in data["categories"] for name in category["commands"]}
        unknown.update(data["overrides"])
        for names in data.get("staff", {}).values():
            unknown.update(names)
        custom = await self.formatter.custom_commands(ctx)
        missing = sum(ctx.bot.get_command(name) is None and name not in custom for name in unknown)
        missing_cogs = {name for category in data["categories"] for name in category["cogs"]
                        if ctx.bot.get_cog(name) is None}
        await self.edit_draft(ctx, edit)
        if missing or missing_cogs:
            await ctx.send(f"Kept references to {missing} unavailable command(s) and "
                           f"{len(missing_cogs)} unloaded cog(s).")

    @helpmenu.command()
    async def migrate(self, ctx, source: str = "published"):
        """Stage a legacy server menu as the global draft."""
        if source not in {"published", "draft"}:
            await ctx.send("Choose published or draft.")
            return
        data = await self.config.guild(ctx.guild).get_raw("settings", default=None)
        menu = data.get(source) if data else None
        if not menu:
            await ctx.send("This server has no saved legacy menu for that option.")
            return

        def edit(draft):
            draft.clear()
            draft.update(menu)

        await self.edit_draft(ctx, edit)

    @helpmenu.command()
    async def publish(self, ctx):
        """Make the current draft live."""
        async with self.writable_settings() as state:
            changed = bool(state["draft"])
            if changed:
                state.update(previous=state["published"], published=state["draft"], draft={})
        await ctx.send("Help menu published to all servers." if changed else "There is no draft to publish.")

    @helpmenu.command()
    async def rollback(self, ctx):
        """Restore the previous published menu."""
        async with self.writable_settings() as state:
            changed = bool(state["previous"])
            if changed:
                state["published"], state["previous"] = state["previous"], state["published"]
        await ctx.send("Previous help menu restored." if changed else "No previous menu is saved.")

