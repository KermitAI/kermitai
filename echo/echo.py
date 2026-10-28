"""Owner-only private slash invocation with ordinary bot message output."""

import re

import discord
from redbot.core import app_commands, commands


_DESTINATION = re.compile(
    r"\A(?:<#(?P<mention>[0-9]+)>|(?P<id>[0-9]{15,20})|"
    r"<?https?://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild>[0-9]+)/(?P<link>[0-9]+)/?>?)(?=\s|$)"
)


def split_destination(message):
    """Remove an optional leading channel reference, preserving message formatting."""
    match = _DESTINATION.match(message)
    if match is None:
        return None, None, message
    channel_id = int(match.group("mention") or match.group("id") or match.group("link"))
    guild_id = int(match.group("guild")) if match.group("guild") else None
    # Consume one separator only, so intentional indentation/newlines survive.
    content = message[match.end():]
    if content and content[0].isspace():
        content = content[1:]
    return channel_id, guild_id, content


class Echo(commands.Cog):
    """Let the bot owner send a message through Paimon privately."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="echo", description="Have Paimon repeat your message (bot owner only).")
    @app_commands.guild_only()
    @app_commands.describe(message="Text to echo; optionally start with a channel mention, channel link, or ID.")
    async def echo(self, interaction: discord.Interaction, message: str):
        # Slash commands do not run Red's prefix-command owner checks.
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await self.bot.is_owner(interaction.user):
            await interaction.edit_original_response(content="Only my bot owner can use this command.")
            return

        channel_id, guild_id, content = split_destination(message)
        if not content.strip() or len(content) > 2000:
            await interaction.edit_original_response(content="Please provide a message between 1 and 2,000 characters.")
            return

        try:
            channel = interaction.channel
            if channel_id is not None:
                channel = self.bot.get_channel(channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                await interaction.edit_original_response(content="Choose a server text channel or thread.")
                return
            if guild_id is not None and channel.guild.id != guild_id:
                await interaction.edit_original_response(content="That channel link does not match its server.")
                return
            await channel.send(content, allowed_mentions=discord.AllowedMentions.all())
        except discord.Forbidden:
            await interaction.edit_original_response(content="I don't have permission to send messages in that channel.")
            return
        except discord.NotFound:
            await interaction.edit_original_response(content="I couldn't find that channel.")
            return
        except discord.HTTPException:
            await interaction.edit_original_response(content="Discord couldn't send the message. Please try again.")
            return

        await interaction.edit_original_response(content=f"Sent to {channel.mention}.")
