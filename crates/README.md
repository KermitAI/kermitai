# Crates

A Red 3.5+ cog with an empty catalog: no example tiers or rewards are installed.
Load with `[p]load crates` after installing through your normal cog workflow.

## Quick start

`[p]` stands for your bot prefix. For example, use `.crate pull` if your prefix is `.`.
Angle brackets mark required arguments and square brackets mark optional ones.

```text
[p]crateset tier knives 1
[p]crateset item knives 0.7 10 Bronze Knife
[p]crateset item knives 0.05 100 Diamond Knife
[p]crateset cooldown 1h
[p]crate knives pull
```

The item arguments are **crate, weight, value, name**. If a crate has just one
item, any valid positive weight gives it a 100% chance.

## Member commands

- `[p]crate <crate-name> pull` (for example `crate knives pull`) selects a named crate and rolls one of its items. `[p]crate pull <crate-name>` is an alternative. `[p]crate pull` chooses automatically only when exactly one crate is configured; otherwise it lists the crate names. If a crate name matches a built-in subcommand such as `inventory`, use the `crate pull <name>` form. Displays an animated reel of that crate's item emojis that slows onto the selected reward, then reveals the item in an embed and mentions the player. The opening embed states the crate being opened and lists item probabilities, including the member's role luck. Long reward lists continue in companion embeds. Awards one item unless the selected reward is configured as an empty pull.
- `[p]crate inventory [member]` (alias `inv`) shows an embed with tier icons, item quantities, unit values and stack values (for example, `1x Value: 10 | x19 Value: 190`), collection totals, and collected value. Per-item values use the current catalog; removed items show value unavailable. If an item name exists in multiple tiers, its lowest-weight tier supplies the displayed value. The overall collected value remains the historical score earned at award time, so it may differ after catalog value changes. Items are ordered by current tier weight, lowest (rarest) first, with alphabetical ties. Items no longer in the catalog appear last. Same-name items in multiple tiers use the lowest tier weight; item weights within a tier do not affect inventory order.
- `[p]crate leaderboard [crate-name]` (alias `lb`) shows each collector's position in every configured crate when several crates exist and no name is supplied. With one crate, it opens that crate's detailed leaderboard automatically. Use `[p]crate leaderboard knives` or `[p]crate knives leaderboard` to open the detailed standings for Knives. Detailed standings include current server members who own at least one item whose exact name matches the crate's current catalog. They show item quantity and current inventory value. Rank uses inventory value first and recorded crate pulls second. Gifts and purchases count toward owned quantity and value. Older combined pull totals cannot be assigned to a crate. If two crates contain an item with the same name, its inventory stack counts for both. Members with no matching items in a particular crate show as **Unranked** in the overview.

## Moderator item grants

`[p]crate give <member> <tier> <quantity> <item name>` gives configured items to a
server member. For example: `[p]crate give @member bronze 2 Bronze Knife`.
Requires a configured Red moderator role (including your Moderators role when
configured in Red), Red admin access, or Manage Messages permission.

Grants add quantities and the item's current value to the collection, without
increasing pull count or changing either cooldown. A member with matching gifts can appear on the leaderboard with zero pulls. Linked Twitch accounts
see the same inventory. Empty-pull rewards cannot be granted. Quantity: 1–1,000,000.

`[p]crate remove <member> <quantity> <item name>` removes owned items with the
same moderator permissions. Example: `[p]crate remove @member 2 Bronze Knife`.
Use the exact inventory name; no tier is required. Removing more than the member
owns is rejected, and stacks disappear when their quantity reaches zero. Pull
counts and both cooldowns remain unchanged. Linked Twitch inventory reflects the
removal too. The current catalog value is deducted from collected value, floored
at zero; same-name items use their lowest-weight tier's value, matching inventory.
For items no longer in the catalog, removal changes quantity only because the
original per-item earned value was not stored. Catalog price changes mean the
score deduction may differ from the value originally earned.

`[p]crate resetcooldown [member]` (alias `resetcd`) clears a member's Discord and
linked Twitch cooldowns. Omit the member to reset your own. Uses the same moderator
permissions as give/remove and follows the configured crate channel restriction.
Inventory, collected value, pull counts, and Twitch duplicate-event receipts stay
unchanged. The configured cooldown duration is not changed. An opening animation
already in progress must finish before that member starts another Discord pull.

## Configuration

Requires Red admin access or Manage Server permission. All settings are per server.

- `[p]crateset channel #games` restricts the entire Discord `crate` command group to that specific text channel, including pull, inventory, leaderboard, give, and remove. Aliases follow the same restriction. No moderator bypass is applied. Threads and other channels are not included. The bot must have View Channel, Send Messages, and Embed Links in the selected channel.
- `[p]crateset channel` clears the restriction, allowing crate commands in any channel (default). Configuration commands remain available anywhere; Twitch integration calls are unaffected. If the configured channel is deleted, use this command or select a replacement.
- `[p]crateset show` displays settings, tiers, items, and effective probabilities.
- `[p]crateset tier <tier> <weight> [emoji]` creates or updates a tier. The optional emoji can be Unicode or a Discord custom emoji; existing tiers default to a crate emoji. Omitting it preserves the existing emoji. Names use letters, numbers, or hyphens (up to 32 characters); names are normalized to lowercase.
- `[p]crateset item <tier> <weight> <value> <item name>` creates or updates an item. The remainder of the command is its name, so spaces do not need quotes. Names are case sensitive and up to 100 characters.
- `[p]crateset itememoji <crate> <emoji> <item name>` sets the emoji used for that reward in the reel. Supports Unicode and Discord custom emojis; existing items default to a crate emoji. Images continue to use `itemimage`.
- `[p]crateset tieremoji <tier> <emoji>` changes an existing tier's emoji.
- `[p]crateset itemimage <tier> <URL|none> <item name>` sets an optional public HTTP(S) image URL for the reward reveal, or clears it with `none`. Discord must be able to load the image; URLs are not fetched by the bot.
- `[p]crateset itemempty <tier> <true|false> <item name>` makes that weighted reward an empty pull: no item or value, but it still counts as a pull and consumes the cooldown. Set false to restore its normal reward behavior. Nothing is marked empty by default; a zero-value item is still a collectible.
- `[p]crateset removetier <tier>` removes a tier and its reward definitions from future pulls.
- `[p]crateset removeitem <tier> <item name>` removes a reward from future pulls.
- `[p]crateset enabled <true|false>` enables or disables pulls. Default: true. Inventories and leaderboards remain available.

Existing tier records now act as selectable crates; no inventory or reward definitions are migrated or deleted. Create a crate with `crateset tier`, then add its items with `crateset item`. A selected crate with no items cannot be opened. Crate weights do not affect a named pull; item weights inside that crate determine probabilities. Item weights 3 and 1 give 75% and 25% base chances. Crate weights are retained for inventory ordering and older random Store listings. Weights must be finite, positive, and no more than 1,000,000. Up to 50 tiers and 100 items per tier are supported.

Value is a nonnegative leaderboard score (up to 1,000,000,000), independent of Red's bank. Scores are recorded at pull time: later changes do not alter earlier awards. Items with the exact same name stack in inventory across tiers. Renaming means removing the old definition and adding a new one; existing inventory keeps the original name. Removing tiers/items preserves inventories, scores, and pull history.

Persistent member data includes inventory, pull count, collected value, and last pull time. Supports Red's user data deletion requests. Awards and cooldowns are saved together before the announcement; if Discord cannot deliver the announcement, the reward remains in inventory. Concurrent pulls are serialized per server to prevent duplicate cooldown claims.

The leaderboard uses Discord's cached server member list; enable the bot's Server Members intent for complete membership information.

## Transfer crates between servers

1. Run `[p]crateset export` in the source server and download the attached `crates.json`.
2. In the destination server, attach the file to the message `[p]crateset import`.

Both commands require Red admin access or Manage Server. The file contains all
crate and item definitions, including weights, values, emojis, image URLs, and
empty rewards. Custom emoji references require the bot to have access to those
emojis. Reward commands are configured separately in the destination server.
Inventories, pull history, cooldowns, role luck, and channel settings stay with
their original server. Imports skip existing crate names and validate the entire
file before saving. The destination can hold up to 50 crates.

## Cooldowns

| Command | Effect |
| --- | --- |
| `[p]crateset cooldownmode user` | Default. Each member waits the configured duration after their own pull. |
| `[p]crateset cooldownmode global` | After any pull, everyone sharing that server timer waits the configured duration. |
| `[p]crateset cooldownmode daily <HH:MM> [timezone]` | Each member gets one pull per reset window. Everyone becomes eligible at the scheduled time. Defaults to UTC if the timezone is omitted. |
| `[p]crateset cooldown <duration>` | Sets the wait for User and Global modes. Accepts plain seconds or units such as `1m`, `3h`, `1d`, `2w`, or `1h 30m`. The default is `0` for unlimited pulls, and the maximum is 365 days. |
| `[p]crateset sharedcooldown <true\|false>` | Defaults to true. Shares the timer across linked Discord and Twitch accounts in User and Daily modes, or across both platforms in Global mode. False gives each platform its own timer or daily eligibility. Twitch chat and channel points always share the Twitch timer. |
| `[p]crate resetcooldown [member]` | Clears a member's timers for User or Daily mode, including linked Twitch. Defaults to yourself. |
| `[p]crateset resetglobalcooldown` | Clears the server-wide timers for both platforms in Global mode. |

Use `[p]crateset cooldownmode daily 12:00 EST` for noon at UTC−5 year-round.
Use `[p]crateset cooldownmode daily 12:00 America/Toronto` for noon Toronto
time with daylight saving. Daily uses a 24-hour clock. Pull eligibility applies
across all crate names, and empty outcomes consume eligibility too.

## Optional item reward commands

No reward commands are installed or attached to any item automatically. These
settings let the bot owner configure their own existing prefix commands later:

- `[p]crateset itemcommand <tier> "Item Name" <command without prefix>` appends
  a command to the item. Quote names containing spaces. Up to five commands may
  be attached; they run in configured order on each new pull of that collectible.
- `[p]crateset itemcommands <tier> <item name>` lists the commands with numbers.
- `[p]crateset removeitemcommand <tier> <number> <item name>` removes one command.
- `[p]crateset clearitemcommands <tier> <item name>` clears all of them.

Placeholders: `{user}` is the pulling member's Discord mention, `{user_id}` is
their numeric Discord ID, and `{guild_id}` is the server ID. Include the recipient
placeholder wherever your economy or other command expects its target. The actual
command syntax and amount are determined by the cog providing that command; Crates
does not invent economy commands, award bank currency, or reset cooldowns by itself.
Only built-in placeholders are replaced; this is not Python or shell execution.

Only the bot owner can manage reward commands, because they execute as the owner
who configured them, not as the member pulling. That owner must remain a bot owner
and a current server member. Normal command argument parsing, permissions, checks,
and command cooldowns apply. Commands are invoked directly through the bot command
framework; they are not posted to Discord as executable chat messages. The only
command from Crates itself allowed as a reward action is `crate resetcooldown`
(including its alias), to avoid direct recursive pulls or configuration changes.

Discord actions run in the pull's channel after the reward is revealed.
Commands that send their own responses can post them in that channel. This lets a configured cooldown reset affect the
just-completed pull. Moderator give/remove operations and empty-pull rewards do
not trigger commands. Updating an item preserves its command list.

Linked Twitch pulls can run commands for a current Discord member. They reuse the
saved configuration message as context in its channel, so keep that message and
channel available, and allow the bot to read its message history. Reconfigure an
action if its setup message is deleted or its saved prefix is no longer valid.
Normal channel checks still apply. Unlinked Twitch accounts receive their item,
but Discord command actions are skipped. No actions are deferred until linking.

Discord posts command completion, failure, or skipping after the reveal;
the Twitch API returns `command_results` on the original attempt. Command errors
are logged without undoing the saved item or cooldown. A command that responds
with its own error message without signalling a framework failure may still report
completion. A timeout or partial failure is not retried automatically.

Twitch receipts are saved before any side effect: duplicate event deliveries never
rerun reward commands, even after failure. A process stop between saving the item
and finishing its commands can leave actions incomplete. Arbitrary other cogs'
side effects cannot be made transactional with Crates storage; inspect the other
cog before manually correcting a failed payout. The receipt stores the original
item result, not the later command execution report.

## Role luck bonuses

- `[p]crateset luck <role> <percent>` sets a rarity weight bonus. Allowed bonus:
  0–1,000%; zero removes it. No bonuses are enabled by default.
- `[p]crateset luckremove <role>` removes a bonus.
- `[p]crateset luckshow [member] [crate-name]` previews base and effective item
  probabilities for that member and crate. With multiple crates, specify both
  the member and crate, for example `luckshow @member knives`.

For named pulls, role luck now boosts **rarer items inside the selected crate**.
The highest matching role bonus applies; bonuses do not stack. The commonest item
keeps its weight; the rarest gets the full multiplier; intermediate items receive
proportional increases. Formula:
`adjusted = weight * (1 + percent/100 * (max_weight-weight)/(max_weight-min_weight))`.
A 25% bonus means up to 25% more relative weight, not 25 percentage points added
straight to the final probability. Equal-weight rewards or a single item keep the
same odds. The opening embed and luckshow use the same probabilities as selection.
Empty rewards participate by their configured weight too.

Discord pulls use the member's current cached roles. Verified linked Twitch users
use the linked Discord member's roles; unlinked or unavailable members get no bonus.
Legacy random Store listings retain tier-based luck, while named Store openings
use item-based luck. Cooldowns, manual grants, saved base weights, and already saved
results are unaffected. Enable Server Members intent for reliable role information.

## Discord presentation

The bot needs **Embed Links**, View Channel, and Send Messages permissions. Custom
emojis must be usable by the bot (external emojis may require Use External Emojis).
The Discord pull reveal takes approximately six seconds with a limited number of
message edits. Discord rate limits can make it slower. Each member may have one
opening animation active per server. The reel is decorative; named-pull odds are determined by the selected crate's
item weights and role luck before the animation. The reel stops on the saved
reward's item emoji, not the crate emoji.

Reward data and cooldown are saved before presentation. If an edit fails, the bot
tries to post the final result separately. If Discord delivery fails entirely, the
award remains saved. Empty pulls display “Better luck next time”; collected items
display “Congratulations” and an optional reward image. Inventory and leaderboard
use multiple embeds when necessary, preserving rarity ordering and rankings.
Inventory and leaderboard embeds use the bot's configured default embed color
for the command context.

Example configuration (use your own image URL):

```text
[p]crateset tier bronze 0.7 🟤
[p]crateset tieremoji bronze 🟤
[p]crateset itemimage bronze https://your-domain.example/bronze.png Bronze Knife
```

No example catalog is installed automatically. Updating an item's weight/value
preserves its image and empty-pull setting. Leaderboard eligibility requires a matching item in inventory.

## Twitch pull methods

- `[p]crateset twitchmode <points|command|both|off>` selects the accepted Twitch
  pull methods. Default: `points`, preserving existing integrations.
- `[p]crateset twitchcommand <command text>` sets the exact chat command.
  Default: `!crate pull`. Matching ignores case and surrounding whitespace;
  a crate name may follow the configured command, such as `!crate pull knives`. Other extra arguments do not match. Setting a command does not enable command pulls.

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

- `await cog.pull_twitch(guild_id, twitch_id, username, redemption_id, crate_name=None)` awards one
  reward and returns `tier`, `name`, `value`, `emoji`, `image`, `empty`, and `duplicate`. Empty outcomes return `name=None` and `value=0`. Older saved receipts may lack the new presentation fields, so callers should use defaults. New receipts preserve the image and emoji at pull time. Use permanent numeric
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

Twitch channel-point callers must pass `crate_name` when multiple crates exist.
Twitch chat supports the configured command followed by a crate name. With one
configured crate, omitting the name opens it automatically. Duplicate receipts
return the original result regardless of a later crate argument.

All normal pulls use the server's enabled setting, catalog, and cooldown mode.
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


## Separate Store cog compatibility

The optional `Store` cog uses Red's existing bank balance for guaranteed items and
extra random crate openings. Store has its own `[p]store` / `[p]storeset` commands
and catalog, described in the [Store README](../store/README.md). No listings are installed by default.

Trusted API: `await cog.deliver_store_purchase(guild_id, discord_id, purchase_id,
kind, tier=None, name=None, quantity=1)`. `kind` is `item` or `crate`; crate quantity
must be one, while collectible bundles accept 1–1,000. The caller is responsible
for charging/authorizing the purchase and supplying its permanent unique ID.

Delivery and receipt are saved together in the Discord collection. Retrying the
same ID returns the original result, including when the catalog has since changed
or Crates was disabled. Pass `tier` to purchase a named crate using item odds and role luck. Omitting it
preserves legacy Store random-crate selection. Purchased openings do
not increase normal pull counts, change platform cooldowns, or run reward commands.
Guaranteed purchases reject removed/empty rewards. Empty random outcomes are valid
purchases, with no inventory item. Purchases add collectible value and quantities
to the shared inventory. The normal crate command channel restriction does not
apply to this API; Store enforces its own channel and access settings.

Store receipts contain purchase IDs and reward snapshots and are removed with the
Discord collection under Red user deletion. Preserve both Store orders and Crates
receipts in backups to maintain safe recovery. The API is for trusted cogs only;
it is not a public command for free rewards.
