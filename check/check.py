import io

import discord
from redbot.core import commands

from .audit import build_report
from .repos import build_repo_report, downloader_inventory


class Check(commands.Cog):
    """Report declared access requirements without running other commands."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="checkcommands", aliases=["commandaudit"])
    @commands.is_owner()
    async def checkcommands(self, ctx):
        """List all loaded text/hybrid commands by declared access level.

        Includes hidden commands and subcommands. Custom checks are flagged
        for review. Standalone application commands are listed separately.
        """
        report, counts, review = build_report(self.bot.walk_commands())
        tree = getattr(self.bot, "tree", None)
        if tree is not None:
            app_commands = list(tree.walk_commands())
            if ctx.guild is not None:
                app_commands += list(tree.walk_commands(guild=ctx.guild))
            if app_commands:
                report += ("\nAPPLICATION COMMANDS (review separately)\n"
                           "Discord application-command permissions and callback checks are not classified.\n")
                for command in sorted(app_commands, key=lambda cmd: cmd.qualified_name):
                    report += f"- {command.qualified_name}\n"
        summary = "\n".join(f"{category}: {count}" for category, count in counts.items())
        await ctx.send(
            f"**Command access audit**\n{summary}\nNeeds review: {review}\n"
            "Full report attached. Categories describe declared requirements; see report notes.",
            file=discord.File(io.BytesIO(report.encode("utf-8")), filename="command-access-audit.txt"),
            allowed_mentions=discord.AllowedMentions.none(),
        )


    @commands.command(name="checkrepos", aliases=["repoaudit"])
    @commands.is_owner()
    async def checkrepos(self, ctx):
        """Report installed repos, unloaded cogs, and registered commands.

        This does not test commands, load cogs, update repos, or remove anything.
        """
        try:
            repos, installed, libraries = await downloader_inventory(self.bot)
        except RuntimeError as error:
            await ctx.send(str(error), allowed_mentions=discord.AllowedMentions.none())
            return
        tree = getattr(self.bot, "tree", None)
        apps = list(tree.walk_commands()) if tree is not None else []
        if tree is not None and ctx.guild is not None:
            apps.extend(tree.walk_commands(guild=ctx.guild))
        report, counts = build_repo_report(
            repos, installed, libraries, self.bot.extensions, self.bot.cogs,
            self.bot.walk_commands(), apps,
        )
        await ctx.send(
            f"**Repository audit**\nAdded repos: {counts['repos']}\n"
            f"Installed cogs: {counts['installed']}\n"
            f"Unloaded cogs to review: {counts['unloaded']}\n"
            f"Repos with no tracked cogs/libraries: {counts['candidates']}\n"
            "Full inventory attached. Unloaded cogs are not necessarily broken.",
            file=discord.File(io.BytesIO(report.encode("utf-8")), filename="repository-audit.txt"),
            allowed_mentions=discord.AllowedMentions.none(),
        )
