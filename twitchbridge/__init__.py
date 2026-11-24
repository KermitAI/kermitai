from .twitchbridge import TwitchBridge

__red_end_user_data_statement__ = (
    "Stores broadcaster IDs, usernames, bot and broadcaster role-sync OAuth tokens, "
    "Discord destination and role IDs, verified per-server Discord/Twitch member links, "
    "link timestamps, linking panel IDs, automation settings, to-do text, counters, "
    "ad-warning receipts, Twitch attendance/greeting history, and a ledger of integration-granted roles. Pending verification "
    "codes, transient member approval tokens, channel event payloads and cooldowns are held in memory. Quote settings are stored per server; submitted quote text, Twitch usernames and UTC timestamps are posted to the configured Discord channel without a separate local quote database. Chat is copied to configured Discord "
    "channels; no local chat archive is kept. Supports member unlinking and Red user "
    "data deletion; existing Discord chat logs are managed separately in Discord."
)


async def setup(bot):
    cog = TwitchBridge(bot)
    if bot.get_command("todo") is not None:
        cog.twitchtodo.aliases = [name for name in cog.twitchtodo.aliases if name != "todo"]
    await bot.add_cog(cog)
