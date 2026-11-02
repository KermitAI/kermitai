import io

import discord
from redbot.core import commands

from .audit import build_report


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
