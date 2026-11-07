from .twitchbridge import TwitchBridge

__red_end_user_data_statement__ = (
    "Stores broadcaster IDs, usernames, bot and broadcaster role-sync OAuth tokens, "
    "Discord destination and role IDs, verified per-server Discord/Twitch member links, "
    "link timestamps, linking panel message/channel IDs, and a ledger of integration-granted roles. Pending verification "
    "codes, transient member approval tokens and cooldowns are held in memory. Chat is copied to configured Discord "
    "channels; no local chat archive is kept. Supports member unlinking and Red user "
    "data deletion; existing Discord chat logs are managed separately in Discord."
)


async def setup(bot):
    await bot.add_cog(TwitchBridge(bot))
