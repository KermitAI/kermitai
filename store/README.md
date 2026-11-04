# Store

A separate Red 3.5+ cog that spends the **existing Red bank balance**, with no
second currency or wallet. It works with either Red's server bank or global bank
and displays the bank's configured currency name. The Economy cog provides earning
commands; Red's bank module holds the balances.

## Getting started

Install/update both Store and Crates through your normal cog workflow, then:

```text
[p]reload crates
[p]load store
```

No example listings, rewards, prices, or stock are installed. Configure Crates
first, then add your own Store listings. Illustrative setup syntax:

```text
[p]storeset item <listing-id> <price> <tier> <quantity> <exact item name>
[p]storeset crate <listing-id> <price> <display name>
```

An item listing delivers the specified quantity of a guaranteed collectible.
A crate listing delivers one random opening using all currently populated Crates
tiers, configured chances, and the buyer's role luck. Empty outcomes remain possible
when configured in Crates, and count as delivered purchases, not failed deliveries.
The store advertises this before purchase.

## Member commands and interface

- `[p]store` opens a shop embed in the bot's configured default embed color.
  Browse All listings, Guaranteed items, or Crate openings using the category
  dropdown and Previous/Next. Each listing shows price, stock, reward, your bank
  balance, and the current item's image/emoji when configured in Crates.
- **Buy** opens a private confirmation showing the listing and price. Nothing is
  charged until **Confirm purchase**. Cancel and expired confirmations cost nothing.
  Only the member who opened the shop can use its controls. Browse views expire
  after two minutes; confirmations expire after one. Reopen after a cog reload.
- `[p]store orders` lists unresolved orders and your ten most recent completed,
  cancelled, failed, or refunded orders.
- `[p]store refund <order-id>` claims a known refund that could not be deposited
  because the bank balance cap was reached. Spend enough currency to make room
  first. Recovery commands remain available outside the store channel.

Both listing types add items and their current collectible value to the existing
Crates collection (including linked Twitch inventories). They do **not** increase
normal pull counts, change normal Discord/Twitch cooldowns, or execute item reward
commands. Members with only purchases remain off Crates' pull leaderboard until
they make a normal pull. Random openings use the Crates emoji reel and reveal;
guaranteed items use a purchase receipt embed. The Store channel is independent
of the normal `crate` command channel restriction.

## Store configuration

Requires a configured Red admin or Manage Server permission:

- `[p]storeset show` lists settings, listing IDs, prices, and stock.
- `[p]storeset item <id> <price> <tier> <quantity> <item name>` adds/updates an
  item listing. Item names use the exact Crates catalog spelling, including spaces.
- `[p]storeset cratefor <id> <price> <crate-name> <display name>` creates a listing for a specific named crate. These openings roll its items with role luck and show item emojis and probabilities.
- `[p]storeset crate <id> <price> <display name>` adds/updates an extra-opening
  listing. Openings are sold one at a time and use current Crates odds.
- `[p]storeset price <id> <price>` changes the price.
- `[p]storeset stock <id> <remaining>` sets remaining **purchases**, not individual
  items in a bundle. Use `-1` for unlimited (default), `0` for sold out.
- `[p]storeset description <id> <text>` sets a description; `none` clears it.
- `[p]storeset remove <id>` removes a listing from future purchases.
- `[p]storeset enabled <true|false>` opens/closes the store. Defaults to true
  with an empty catalog. Closing also rejects already-open confirmations.
- `[p]storeset channel [#channel]` restricts browsing and buying to one channel;
  omit the channel to allow any (default). Store recovery/history and storeset
  commands remain usable elsewhere.
- `[p]storeset orders` lists all unresolved purchase records for owner review.

Listing IDs: 1–32 lowercase letters/digits/hyphens. At most 100 listings per server.
Prices: 1–1,000,000,000 bank currency. Guaranteed item bundle quantities: 1–1,000.
Stock: -1 or 0–1,000,000 purchases. Titles: 1–100 characters; descriptions: up to
500. Updating a listing preserves its description and stock. Changes invalidate
old confirmations, requiring the buyer to reopen the listing at its new price.
Crates must be loaded, updated, and enabled for reward delivery.

## Payments, refunds, and recovery

Each confirmed purchase has a unique persistent order ID. Store reserves stock,
saves the intended charge, withdraws currency through Red's bank API, and requests
an idempotent Crates delivery. Repeated confirmations and recovery deliveries use
the same ID, so they do not deduct currency or add items twice. Stock and per-buyer
operations are serialized within the Store instance, including global-bank buyers
shopping in different guilds. Other cogs' bank activity is outside those locks.

Known reward rejections (such as a removed collectible) are refunded, and reserved
stock is returned. A balance-cap rejection records the whole refund as pending;
no currency is discarded or silently clamped. A changed bank mode blocks recovery
or refund to avoid writing to the wrong wallet. Do not toggle bank mode while
orders are being processed.

Bank, Store, and Crates use separate persistent writes. There is no cross-cog
database transaction. An interrupted or unknown charge/refund is deliberately
left unresolved rather than guessing and risking a second charge or refund.
An unresolved order blocks that member's further purchases in that server until
resolved. No background process automatically retries currency movement.

Bot-owner-only recovery tools:

- `[p]storeset recover <order-id>` retries delivery for `charged` or `delivering`
  orders without charging again. The Crates receipt prevents a second delivery.
  If delivery is known to have been rejected, the normal refund path applies.
- `[p]storeset resolve <order-id> <complete|cancelled>` updates tracking **only**
  after the owner has checked and, if needed, manually corrected the member's
  balance/inventory. It moves no money and grants no items. `cancelled` releases
  the reservation if that listing still has the same stock revision.

Order statuses: `charging` means a debit may have been interrupted; `charged` and
`delivering` are recoverable using the delivery receipt; `refunding` means a refund
may have been interrupted; `refund_due` is a known balance-cap failure safe for the
buyer to claim. `complete`, `failed`, `refunded`, and `cancelled` are terminal.
Use the bank/cog logs to reconcile ambiguous currency operations before resolve.
If a refund happens after an admin has replaced/restocked a listing, Store will not
rewrite that newer stock setting. A failed reveal does not refund a delivered
reward; the item remains in inventory.

The bot needs View Channel, Send Messages, and Embed Links for the storefront and
reveals. Custom tier emojis/images retain the same Discord requirements as Crates.
Only run one bot process against a Red instance's data. Back up cog data before
updates; preserve both Store orders and Crates receipts together when restoring.

## Stored data

Store saves server catalog/settings and member-linked order records (ID, price,
status, bank mode, time, listing snapshot, and reward). Crates stores purchase
receipts in the recipient's collection for idempotency. Both support Red user data
deletion. Deletion removes receipts, so historical deleted order IDs must never be
replayed as new purchases by external integrations. No access tokens or separate
economy balances are stored by Store.

Named crate openings are recommended for the new selectable-crate model. Older random-crate listings remain supported; their reveal now cycles items within the selected crate.
