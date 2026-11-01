# Crates

A Red 3.5+ cog with an empty catalog: no example tiers or rewards are installed.
Load with `[p]load crates` after installing through your normal cog workflow.

## Member commands

- `[p]crate pull` selects a populated tier by weight, then one item within that tier by weight. Awards one item and announces the result.
- `[p]crate inventory [member]` lists item names and quantities, total pulls, and collected value.
- `[p]crate leaderboard` lists all current server members with at least one successful pull, ordered by collected value, then pull count. Zero-value rewards still qualify. Output is split across messages as needed.

## Configuration

Requires Red admin access or Manage Server permission. All settings are per server.

- `[p]crateset show` displays settings, tiers, items, and effective probabilities.
- `[p]crateset tier <tier> <weight>` creates or updates a tier. Names use letters, numbers, or hyphens (up to 32 characters); names are normalized to lowercase.
- `[p]crateset item <tier> <weight> <value> <item name>` creates or updates an item. The remainder of the command is its name, so spaces do not need quotes. Names are case sensitive and up to 100 characters.
- `[p]crateset removetier <tier>` removes a tier and its reward definitions from future pulls.
- `[p]crateset removeitem <tier> <item name>` removes a reward from future pulls.
- `[p]crateset cooldown <seconds>` sets the wait between successful pulls. Default: 0 (unlimited). Use 86400 for a 24-hour wait. This is a rolling cooldown, not a calendar-day reset.
- `[p]crateset enabled <true|false>` enables or disables pulls. Default: true. Inventories and leaderboards remain available.

Create at least one tier and add at least one item to it before pulling. Empty tiers are excluded from selection. Tier weights 3 and 1 produce 75% and 25% tier probabilities. Item chances are calculated separately within the chosen tier. Weights must be finite, positive, and no more than 1,000,000. Up to 50 tiers and 100 items per tier are supported.

Value is a nonnegative leaderboard score (up to 1,000,000,000), independent of Red's bank. Scores are recorded at pull time: later changes do not alter earlier awards. Items with the exact same name stack in inventory across tiers. Renaming means removing the old definition and adding a new one; existing inventory keeps the original name. Removing tiers/items preserves inventories, scores, and pull history.

Persistent member data includes inventory, pull count, collected value, and last pull time. Supports Red's user data deletion requests. Awards and cooldowns are saved together before the announcement; if Discord cannot deliver the announcement, the reward remains in inventory. Concurrent pulls are serialized per server to prevent duplicate cooldown claims.

The leaderboard uses Discord's cached server member list; enable the bot's Server Members intent for complete membership information.
