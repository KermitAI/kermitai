from .twitchbridge import TwitchBridge

__red_end_user_data_statement__ = (
    "Stores broadcaster IDs, usernames, Discord destination IDs and Twitch OAuth tokens. "
    "Chat is copied to the configured Discord channel; no local chat archive is kept."
)


async def setup(bot):
    await bot.add_cog(TwitchBridge(bot))
