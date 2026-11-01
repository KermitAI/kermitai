# Crates

A Red 3.5+ cog with an empty catalog: no example tiers or rewards are installed.
Load with `[p]load crates` after installing through your normal cog workflow.

## Member commands

- `[p]crate pull` selects a populated tier by weight, then one item within that tier by weight. Awards one item and announces the result.
- `[p]crate inventory [member]` lists item names and quantities, total pulls, and collected value. Items are ordered by current tier weight, lowest (rarest) first, with alphabetical ties. Items no longer in the catalog appear last. Same-name items in multiple tiers use the lowest tier weight; item weights within a tier do not affect inventory order.
- `[p]crate leaderboard` lists all current server members with at least one successful pull, ordered by collected value, then pull count. Zero-value rewards still qualify. Output is split across messages as needed.

## Configuration

Requires Red admin access or Manage Server permission. All settings are per server.

- `[p]crateset show` displays settings, tiers, items, and effective probabilities.
- `[p]crateset tier <tier> <weight>` creates or updates a tier. Names use letters, numbers, or hyphens (up to 32 characters); names are normalized to lowercase.
- `[p]crateset item <tier> <weight> <value> <item name>` creates or updates an item. The remainder of the command is its name, so spaces do not need quotes. Names are case sensitive and up to 100 characters.
- `[p]crateset removetier <tier>` removes a tier and its reward definitions from future pulls.
- `[p]crateset removeitem <tier> <item name>` removes a reward from future pulls.
- `[p]crateset cooldown <duration>` sets the wait between successful pulls. Accepts `s` (seconds), `m` (minutes), `h` (hours), `d` (days), and `w` (weeks), such as `1m`, `3h`, `1d`, `2w`, or `1h 30m`. Plain seconds still work. Default: `0` (unlimited). Maximum: 365 days. Use `1d` for a 24-hour wait. This is a rolling cooldown, not a calendar-day reset.
- `[p]crateset sharedcooldown <true|false>` controls whether linked Discord and Twitch accounts share a pull cooldown. Default: true. False gives Discord and Twitch independent timers using the same configured duration. Twitch channel-point and chat-command pulls always share the Twitch timer. Unlinked accounts already have independent collections and timers.
- `[p]crateset enabled <true|false>` enables or disables pulls. Default: true. Inventories and leaderboards remain available.

Create at least one tier and add at least one item to it before pulling. Empty tiers are excluded from selection. Tier weights 3 and 1 produce 75% and 25% tier probabilities. Item chances are calculated separately within the chosen tier. Weights must be finite, positive, and no more than 1,000,000. Up to 50 tiers and 100 items per tier are supported.

Value is a nonnegative leaderboard score (up to 1,000,000,000), independent of Red's bank. Scores are recorded at pull time: later changes do not alter earlier awards. Items with the exact same name stack in inventory across tiers. Renaming means removing the old definition and adding a new one; existing inventory keeps the original name. Removing tiers/items preserves inventories, scores, and pull history.

Persistent member data includes inventory, pull count, collected value, and last pull time. Supports Red's user data deletion requests. Awards and cooldowns are saved together before the announcement; if Discord cannot deliver the announcement, the reward remains in inventory. Concurrent pulls are serialized per server to prevent duplicate cooldown claims.

The leaderboard uses Discord's cached server member list; enable the bot's Server Members intent for complete membership information.

## Twitch pull methods

- `[p]crateset twitchmode <points|command|both|off>` selects the accepted Twitch
  pull methods. Default: `points`, preserving existing integrations.
- `[p]crateset twitchcommand <command text>` sets the exact chat command.
  Default: `!crate pull`. Matching ignores case and surrounding whitespace;
  extra arguments do not match. Setting a command does not enable command pulls.

Both Twitch methods award to the same collection and share the Twitch cooldown.
Sharing that cooldown with linked Discord accounts is controlled by `sharedcooldown`. Choosing `off` affects only Twitch pulls.
`[p]crateset show` includes the mode and command text.

These settings are enforced by the Crates integration API. The current TwitchBridge
logs chat only; it does not yet dispatch crate commands or channel-point events.

## Twitch integration foundation

Discord commands continue to work without Twitch or account linking. Existing member
inventories are imported on the first award or link; reads and leaderboards also
recognize legacy data. Back up Red's cog data before installing an update. Once
new awards or merges have been saved, rolling back to the old cog would expose
stale legacy inventories; restore a matching backup when rolling back.

This cog does not connect to Twitch, authorize users, or receive channel-point events.
A separate trusted integration must verify the broadcaster-to-server mapping,
Twitch events, and account ownership before calling these methods on
`bot.get_cog("Crates")`:

- `await cog.pull_twitch(guild_id, twitch_id, username, redemption_id)` awards one
  item and returns `tier`, `name`, `value`, and `duplicate`. Use permanent numeric
  Twitch IDs as strings, not usernames, for identity. The latest username is saved
  for display. Redemption IDs must come from Twitch, not user input. Duplicate
  deliveries return the original result without another award. Only announce when
  `duplicate` is false. Receipts persist without expiry to preserve deduplication.
- `await cog.pull_twitch_command(guild_id, twitch_id, username, message_id, message)`
  handles a verified chat command. Supply Twitch's original message text and permanent
  chat message ID, not user-provided IDs. The caller verifies the broadcaster mapping
  and sender identity before dispatch. Results have the same shape as `pull_twitch`.
  Chat message receipts are stored separately from channel-point receipts, so the
  two ID types cannot collide. Replayed successful events return their original
  result even if the mode or cooldown has since changed. Announce only new awards.
- `await cog.link_verified_twitch(guild_id, twitch_id, username, discord_id)` merges
  quantities and earned totals once, preserves the latest timestamp for each platform, and routes
  future pulls to the Discord inventory. The caller MUST prove ownership of both
  accounts. No public linking command is provided. Links are per server, one-to-one;
  reassignment is rejected. Repeat linking to the same account is safe.
- `await cog.get_twitch_collection(guild_id, twitch_id)` returns a collection
  snapshot (the shared Discord inventory when linked), or `None` if unknown.
- `await cog.get_discord_collection(guild_id, discord_id)` returns a snapshot.
- `await cog.delete_twitch_data(guild_id, twitch_id)` handles a verified Twitch
  deletion request. It deletes the username, link, unmerged inventory, and redemption/chat receipts;
  previously merged Discord items remain. The integration must stop/reject replay
  of deleted historical redemptions. Red's Discord deletion hook removes the
  Discord collection and linked Twitch records as well.

All pulls use the server's existing enabled setting, catalog, and cooldown duration.
Linked accounts share a cooldown by default; `sharedcooldown false` separates Discord
and Twitch timers. A channel-point payment does not bypass the Twitch timer.
Both platform timestamps are tracked even while sharing is enabled, so changing the
setting does not clear cooldown history. Switching to shared mode uses the latest
pull from either platform. Older records without platform history apply their last
pull timestamp to both platforms until new pulls establish separate history. A failed
pull raises `ValueError` and does not record a redemption as awarded. The future
Twitch integration must decide whether to retry or refund rejected redemptions.
Unlinked Twitch inventories are not on the Discord leaderboard until merged.
Showcase delivery belongs to the integration and occurs after persistence. No
Twitch subscription, OAuth, role sync, or live showcase delivery is implemented here.

Account updates, awards, and redemption receipts are serialized per server and
saved together in the guild's `collections` configuration. Run only one process
against a given Red instance's data; these locks do not coordinate multiple processes.
