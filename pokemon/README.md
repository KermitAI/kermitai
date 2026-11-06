# Pokémon

An opt-in Red 3.5+ cog combining GO-style collection resources with main-series Pokémon stats. This is a first playable implementation, **not a complete Pokémon GO clone or cartridge battle simulator**. Raids are intentionally reserved for later. Full special-move effects remain unfinished.

## Setup

1. Install/load `pokemon` through your normal Red cog workflow.
2. Run `[p]pokeset`. Click **Spawn channel** to open the channel dropdown. Other settings use buttons, with modals for typed input.
3. Choose **Enable / disable** to enable this server. Every server starts disabled.
4. Players open `[p]pokemon` (alias `[p]poke`) for an icon-labelled button menu. **Inventory** shows a grouped item bag with icons, quantities, Stardust, and total family Candy; depleted items are hidden. All subsequent input uses embeds, buttons, dropdowns, and modals. Moderator settings remain usable while the game is disabled.

Grant View Channel, Send Messages, and Embed Links in the selected channel. The first encounter occurs after the configured interval, default **30 minutes**. The scheduler checks every 30 seconds. One public encounter exists per server. Each Pokémon stays for **five minutes**, then flees if nobody has caught it; its message changes to a flee notice and the catch button is removed. The encounter timer is separate from the spawn interval. Configure **Interval** in `[p]pokeset` from **5 to 1440 minutes**; five minutes is useful for testing. A new spawn waits for any active encounter to end. Restarting restores the original expiry deadline and does not produce a backlog of spawns. Catch buttons survive restarts. Other menus and pending trade buttons should be reopened after a reload.

First use downloads official [PokéAPI CSV tables](https://github.com/PokeAPI/pokeapi/tree/master/data/v2/csv) into the cog data directory. Network access is needed for this initial cache, not every encounter. The loader was checked against 1,025 species, 1,351 form records, 937 moves, and 25 natures. All nine generations in that dataset are available. Wild encounters currently select default species forms; the cache includes alternate-form data for future form selection. Remove the `dex` cache while the cog is unloaded to refresh upstream data.

## Pokéstop and catching

- `[p]pokestop` grants **3–6 random supplies plus 50–150 Stardust**. Rewards include Poké/Great/Ultra Balls, potions (including stronger potions), revives, and berries. Master Balls and other premium balls are excluded. These are custom bot rewards rather than an exact GO drop table.
- Each player can spin once every **five minutes per server**. The cooldown is saved across reloads. The command and the **Pokéstop** menu action share that cooldown. Pokémon must be enabled; no bank currency is charged.
- `[p]pokecatch` (alias `[p]catch`) in the configured spawn channel opens ball selection for the current encounter. The spawn button and **Catch** menu action use the same capture rules. The first successful player catches it; failed attempts do not extend its five-minute window.
- A caught encounter changes to a capture notice and loses its catch button. Expired menus cannot consume balls or grant a late capture, even if Discord cannot edit the public message.

## Trainer cards and staff PC viewing

Use `[p]trainer` (alias `[p]trainercard`) or **Trainer** in the Pokémon menu to see your game-style trainer card. It includes your current Discord nickname and avatar, live Red bank balance and currency name, unique owned species count, total Pokémon, trainer level, XP, and Stardust. Duplicates, shinies, and alternate forms of the same species count once in the Pokédex; transferring away the last Pokémon of a species reduces the count.

Use **View another trainer** on a card, or **Other trainer** in the Pokémon menu, to enter a member ID, mention, or exact nickname in a modal. Trainer cards are visible to other members. Names shared by multiple members require an ID or mention. Viewing a card does not create or change the target's collection.

Staff use `[p]pokebox` → **View member PC box**, or administrators use `[p]pokeset` → **View PC box**, to enter a member in a modal. The target's box opens privately with their nickname, Pokémon IDs, levels, shininess, and pagination. Only the staff member who opened it may interact; staff permissions are checked again on each page. Inspection is read-only and remains available while the game is disabled. Server administrators, configured Red admins/moderators, or members with Manage Server/Manage Messages may use the inspection interface; the standalone command follows Red's moderator or Manage Server command check.

## Collection rules

- No geographic restrictions. Legendary, Mythical, and all stages of pseudo-legendary families are excluded from wild selection. Administrators can grant these Pokémon; raids will provide their normal acquisition path later.
- Each trainer starts with 20 Poké Balls when their account is first persisted. Each throw consumes one ball; an optional berry is also consumed. Five-second per-trainer throw cooldown. Only one trainer can catch an encounter.
- Successful catches give 100 trainer XP, 100 Stardust, and 3 family Candy before bonuses. Razz Berries multiply catch chance by 1.5; Pinap Berries double Candy. Shininess is rolled once for the successful catcher with baseline odds 1/4096. A failed throw never rerolls a visible shiny.
- Candy is keyed by evolution family, so evolutions share it. Transfer gives 1 family Candy and permanently removes the Pokémon, including its party slot. Transfer and box wipe require confirmation.
- Power up: +1 Pokémon level for current level × 100 Stardust and 2 Candy. Trainer level is `min(50, 1 + floor(sqrt(XP / 1000)))`; the power-up ceiling is `min(100, max(30, trainer level × 2))`. This is a custom progression curve, not GO's exact level table.
- Evolution: 50 Candy for a direct evolution, preserving IVs, EVs, nature, shininess, and relative size; awards 500 trainer XP. Branch target is entered in a modal. This first version uses Candy alone; stones, friendship, location, trade, time, and special evolution requirements are not enforced. Admin force evolution bypasses Candy.
- Pokémon have random levels 1–30 on capture, six IVs 0–31, six EVs, a nature, height, weight, and up to four level-up moves from the newest available version group. Power-ups/evolution refresh the four level-up moves; there is no move tutor yet. Hidden Power uses the cartridge IV bit ordering and its modern fixed move power.

## Roles

Click **Notification role** in `[p]pokeset` and enter its role ID or role mention in the modal. Use a normal role that interested members can opt into through your server's existing role tools. Make the role mentionable, or give the bot Mention Everyone permission in the spawn channel. Only that role is allowed to ping in a new spawn announcement; notification settings do not grant or remove roles from members. Enter `0` in the notification-role modal to disable pings. Deleted roles or roles the bot can no longer mention are skipped without blocking spawning. Notifications are disabled by default.


In `[p]pokeset` → **Role bonuses**, enter a server role ID and `catch,shiny,rare,xp,candy`, for example `1.2,2,2,1.5,1`. The first four values are multipliers 1–100; Candy is an extra integer 0–100. Enter role ID `0` to clear bonuses.

The largest bonus in each category wins; roles do not stack. Catch, shiny, XP, and Candy apply to the catching member. A public encounter has one shared species, so rarity uses the highest rarity multiplier among cached server members who have a saved trainer account. It benefits the shared encounter, rather than generating a different Pokémon for each person. A higher multiplier flattens capture-rate-based species weights, making low-catch-rate species more likely. This does not affect the reserved-species exclusions. Keep the bot's member cache populated for role-based rarity to reflect all trainers; presence intent is not required.

## Shop and economy

The Pokéshop uses `redbot.core.bank`, the same standard bank as this repository's Store cog. It therefore shares Paimon's economy **if Paimon uses that Red bank**. No separate wallet is introduced. A custom Paimon economy outside Red's bank still needs an adapter; Paimon's source is not in this repository.

The catalog includes Poké Balls, Great/Ultra/Master Balls, specialty balls, Legends-style balls, potions, revives, and berries. Prices are in `rules.py`. Great/Ultra and several specialty balls have catch modifiers; location-, friendship-, sleep-, and encounter-mode-specific ball mechanics are not simulated. Those balls use their listed base multiplier. Origin Ball is not an automatic legendary capture. See `BALLS` and `ball_multiplier` for the current rules. Balls outside the first dropdown are in **More ball types**.

Purchases require a price confirmation. Healing is available from the shop: potions restore non-fainted Pokémon; revives restore fainted Pokémon. Battle HP persists when a battle completes or is forfeited. A timeout or reload discards that battle's unsaved changes.

Every purchase has a persisted order ID. The game records intent before moving bank funds and never automatically retries an uncertain bank operation. **Orders** shows player orders; the admin Orders view shows unresolved order IDs. Bot owner `[p]pokeorders` opens reconciliation:

- Verify actual bank balances/debits first, especially `charging` and `crediting` records.
- `deliver` commits the already-paid purchase or trade assets exactly once.
- `cancel` closes the order and unlocks assets. It does not refund or reverse bank money; do any required bank correction separately before cancelling.
- Reconciliation itself never moves bank funds. Restore the original bank mode before reconciling.

The bank and inventory cannot commit in one database transaction, so these review states are deliberate. Locks serialize this cog's bank operations across guilds; other economy cogs can still change a balance concurrently. Completed order journals are retained for review and data deletion.

## Trades

Trade Pokémon, items, currency, or a combination. The modal takes the recipient's Discord member ID, your Pokémon IDs, their Pokémon IDs, optional item terms, and a signed currency amount. Use `none` for empty lists. Example items: `offer:ultra-ball=2;request:potion=1`. Positive currency means the proposer pays; negative means the recipient pays. The embed names the bank currency and shows both sides before acceptance.

Only the recipient may accept. Proposals expire after five minutes. Ownership, item quantities, and bank balances are checked again at acceptance. Pending proposals do not reserve assets; the first accepted valid trade wins. Currency trade failures keep both collections locked until bot-owner reconciliation. Trading fees, distance rules, lucky trades, and trade-induced IV rerolls are not included.

## Battles and remaining work

Pick exactly six Pokémon with **Party**, then challenge a member using **Battle**. Both trainers must accept the stated battle limitations. Choose moves or switches through private dropdowns. Both actions resolve together using priority and speed; speed ties are random. All six party members can be used, with automatic replacement on fainting. Forfeit ends a battle; inactivity cancels it after five minutes; a 200-turn limit prevents endless battles.

Implemented: stat calculations, nature modifiers, IVs, capped EV yields on knockouts, type effectiveness/immunity, STAB, accuracy, PP, priority, speed order, Hidden Power type, switching, fainting, Struggle/recoil, and persistent HP/earned EVs. EVs cap at 252 per stat and 510 total. Collection changes are locked while battling.

**Incomplete:** every move's data is loaded, but the engine currently permits ordinary direct damage and Hidden Power only. Unsupported moves are excluded and Struggle is available when no supported move has PP. Abilities, held items, critical hits, multi-hit moves, statuses, stat stages, weather, terrain, and other special move effects still need implementation. There is no claim of cartridge-accurate battling. Evolution conditions, form selection, move tutoring, GO's exact progression/catch formula, more items, and raids also remain future work.

## Administration and privacy

`[p]pokeset` provides give/take Pokémon, give/take items, force evolution, role bonuses, interval settings, and confirmed PC box wipes. **Settings** shows the saved configuration and action buttons; **Enable / disable** saves and confirms the new state; **Orders** lists unresolved payment records (or explicitly reports none). Settings callbacks check permissions again; private menus reject other users. `[p]pokeorders` is bot-owner only.

Collections and resources are per server. Red user deletion removes a user's stored collection, orders, trade proposals, and encounter attempts, and cancels active battles. Public Discord messages are not deleted by this hook. Unresolved bank exchanges should be reviewed before voluntarily deleting account records, because deletion removes the associated journal.

## Validation

`python -m unittest discover -s pokemon/tests -v`

Tests use lightweight Discord/Red/bank doubles so they run without a bot token. They cover Pokéstop rewards and saved cooldowns, five-minute expiry, notification roles, catch races, single-charge purchases, uncertain payment recovery, trade validation/payment failures, component limits, stat rules, reserved wild species, and data deletion. Syntax checks and a live official-data import were also run. Live Discord and the actual Paimon bank integration still require a test-server check.
