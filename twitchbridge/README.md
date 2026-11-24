# TwitchBridge

Custom Red 3.5+ cog for owner-only Twitch broadcaster/server mapping, private device
approval, bot-token refresh and validation, EventSub chat reception, and Discord
chat logs, standalone shared custom commands, and announcements. No dependency on
Tags or Crates. Includes verified member linking, per-broadcaster role syncing and
shoutout follow messages. Crate redemptions and inventory merging remain deferred.

## 1. Register the Twitch application

Use https://dev.twitch.tv/console/apps and register an application with 2FA enabled.
Choose the **Public** client type: this version deliberately uses device-code
approval and does not accept or need a client secret. Select an appropriate chat
bot category. If the form requires a redirect URL, use `http://localhost:3000`;
it is not used by this device flow. Copy the Client ID.

Use a dedicated Twitch account for Paimon's bot authorization. The broadcaster
account is authorized separately to verify ownership of the channel being linked.
Authorization requests a fixed permission bundle up front, so role mapping and
planned features do not each require another approval. Twitch still binds each
token to the account approving it; a bot account cannot grant broadcaster access.

- Bot bundle: `user:read:chat`, `user:write:chat`,
  `moderator:manage:announcements`, `moderator:manage:shoutouts`, `user:bot`.
- Broadcaster bundle: `user:read:chat`, `moderation:read`,
  `channel:read:subscriptions`, `channel:read:vips`, `channel:bot`,
  `channel:read:redemptions`, `channel:manage:redemptions`, `bits:read`,
  `moderator:read:followers`, `channel:read:ads`, `channel:manage:ads`,
  `channel:edit:commercial`, `channel:manage:broadcast`.

These cover current and already-planned Paimon capabilities. Native shoutout-card
and redemption permissions are reserved; these integrations remain deferred.
This is not a wildcard for every Twitch API permission. A new scope or revoked
access can still require approval. Bot and broadcaster tokens are stored in Red
Config on the VPS. One broadcaster approval also supplies role-sync authorization.

After upgrading an existing installation, approve each account once:

```
[p]twitchset authbot
[p]twitchset authorize
```

Approve the first as Paimon's Twitch bot account and the second as the selected
broadcaster. `twitchroles authorize` uses the same complete broadcaster bundle.
Role mappings no longer change the requested scopes. Existing read-only tokens
continue to work until a feature needs the additional permissions.

## Updating through your connected GitHub repository

Commit and push the updated `twitchbridge` folder to your existing repository.
In Discord, replace `[p]` with your normal prefix (for example `.`):

```
[p]cog update twitchbridge
[p]reload twitchbridge
[p]twitchset authbot
```

Approve the private link as Paimon's Twitch bot account to grant chat-writing
and announcement permission. Make Paimon a moderator in your Twitch channel
using `/mod PAIMON_TWITCH_USERNAME` as the broadcaster. Existing broadcaster and log-channel settings are preserved; no need
to re-link your broadcaster. Existing read-only approval continues to support
logging, but cannot send replies. If installing for the first time, use
`[p]cog install <repo-name> twitchbridge` and `[p]load twitchbridge` instead.

## 2. Manual installation alternative

Using WinSCP, create `/home/ubuntu/paimon-custom` and upload this entire
`twitchbridge` folder inside it. The layout must include:

```
/home/ubuntu/paimon-custom/twitchbridge/__init__.py
/home/ubuntu/paimon-custom/twitchbridge/twitchbridge.py
/home/ubuntu/paimon-custom/twitchbridge/policy.py
/home/ubuntu/paimon-custom/twitchbridge/info.json
```

This leaves the existing RepoManager repositories alone. Red normally already
includes aiohttp. If loading reports that aiohttp is missing, install it using the
same environment that runs Paimon:

```
/home/ubuntu/redenv/bin/python -m pip install 'aiohttp>=3.9.0,<4'
```

In Discord, replace `[p]` with Paimon's normal prefix:

```
[p]addpath /home/ubuntu/paimon-custom
[p]load twitchbridge
```

## 3. Configure the application and approve accounts

As the bot owner, set the public application ID using Red's API-token command:

```
[p]set api twitchbridge client_id,YOUR_CLIENT_ID
```

Then run the following in the server you want to link:

```
[p]twitchset authbot
```

Check your DMs. Open the approval link and ensure you are signed into **Paimon's
Twitch bot account**, not your broadcaster account. Approve access and wait for the
private completion message. Never share the approval URL or code.

```
[p]twitchset link YOUR_BROADCASTER_USERNAME
[p]twitchset authorize
```

The second private approval must be completed while signed into the exact
broadcaster account selected above. An account mismatch is rejected. One
broadcaster can be linked to only one Discord server in this version.
Authorization links are sent only to the initiating bot owner's DMs. To authorize
a broadcaster owned by someone else, that owner must securely complete approval;
there is not yet a public onboarding portal.

```
[p]twitchset chatlog #twitch-chat-log
[p]twitchset enabled true
[p]twitchset status
```

Paimon needs View Channel and Send Messages in the target Discord text channel.
All `twitchset` commands require bot-owner access. The broadcaster username is a
selection, never proof of ownership; successful Twitch approval supplies its
permanent ID. A replacement `link` command pauses logging and requires approval
again. Changing application IDs requires authorizing both accounts again.

## 4. Live verification

1. Wait until status says Connected. Send a message in the linked Twitch chat.
2. Confirm it appears once in the configured Discord channel with a UTC timestamp.
3. Confirm a message in an unrelated Twitch channel is not forwarded.
4. Send text containing mentions and links; check that no Discord mention fires
   and that no link preview appears.
5. Pause with `[p]twitchset enabled false`; verify forwarding stops.
6. Re-enable, reload the cog, and check that it reconnects using saved authorization.

No Twitch credentials or VPS access were used during local development. Local tests
use simulated Twitch/Discord responses; they do not substitute for this live check.

## Operations and limitations

- `[p]twitchset status` shows connection state, last delivery outcome, queue depth,
  and a dropped-message counter. Global connection/delivery health covers all
  configured servers; broadcaster/channel settings are specific to the current server.
- `[p]twitchset disconnect` removes the current server mapping and pending approval, pauses role sync,
  forgets role-sync tokens and attempts to clean integration-granted roles. Member
  identity links and custom commands remain; role mappings must be authorized for
  the next broadcaster before syncing again.
- `[p]twitchset forgetbot` clears the saved bot authorization for **all servers**.
  Revoke app permissions in Twitch Connections as well to revoke access at Twitch.
- Reloading/unloading cancels pending approvals and closes sockets and HTTP sessions.
- One bot-authorized WebSocket serves configured channels. Twitch reconnect handoffs
  transfer subscriptions; ordinary disconnects reconnect and recreate them.
- Tokens are validated at startup and at least hourly while connected; refresh
  tokens rotate under a lock. Protect Red's data directory and backups: Config
  storage is not encrypted. Tokens and Twitch error bodies are never posted to chats.
- Logs are best-effort copies of received chat messages, not a guaranteed complete
  moderation archive. Twitch does not replay chat missed during disconnections.
  This version does not synchronize message deletions, bans, or AutoMod-held text.
- Queue capacity is 2,000 messages. Overflow and failed Discord sends increment the
  dropped counter. Queued messages and the bounded deduplication cache are in memory;
  restarting loses them. A global sender queues Discord log delivery using discord.py's
  rate handling. Channel settings are rechecked before each send.
- Chat text is escaped, mentions disabled, embeds suppressed, and long output
  capped at 1,900 characters. No local persistent message archive is created.
- Existing Discord log messages are not erased by disconnecting or deleting bot
  configuration; manage retention and channel access in Discord.
- Twitch limits connection/subscription counts. This initial version targets a small
  set of channels under one dedicated bot account; large deployments need sharding.

## References

- Device authorization: https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/
- Token validation: https://dev.twitch.tv/docs/authentication/validate-tokens/
- Chat authorization: https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/#channelchatmessage
- WebSocket lifecycle: https://dev.twitch.tv/docs/eventsub/handling-websocket-events/
- Local Red cog loading: https://docs.discord.red/en/stable/cog_guides/core.html

## Shared custom commands

All management commands require bot-owner access and are run in the linked Discord
server. Custom commands are standalone responses, independent of the Tags cog.

```
[p]twitchcommand add hello Hello {user}! Welcome to {channel}.
[p]twitchcommand platform hello both
[p]twitchcommand permission hello everyone
[p]twitchcommand cooldown hello 5
[p]twitchcommand edit hello Hello {user}! You said: {args}
[p]twitchcommand list
[p]twitchcommand remove hello
```

- New commands default to Twitch only, everyone access, and a five-second cooldown.
- In Twitch use `!hello some arguments`. In Discord use your normal Paimon prefix,
  for example `.hello some arguments`, after enabling `discord` or `both`.
- Platforms: `twitch`, `discord`, `both`. Up to 250 commands per server.
- Permissions: `everyone`, `moderator`, `broadcaster`. Twitch moderator badges
  grant moderator access; the actual broadcaster's ID grants broadcaster access.
  In Discord, Red moderators or Manage Server grant moderator access; the server
  owner and bot owners grant broadcaster access. No Twitch/Discord member linking
  is needed for these independent platform checks.
- Templates support only `{user}`, `{args}`, `{channel}`. They are single-pass
  substitutions, never executable code. `{channel}` is the linked Twitch username
  on both platforms. Unknown placeholders remain literal. Discord mentions are disabled.
- Responses, including expanded variables, must fit 500 characters. Whitespace is
  normalized to one line; overlong expansions are rejected and shown in status.
- Cooldowns are shared by everyone on both platforms for each command, from
  0 to 86,400 seconds. They reserve a slot before delivery and do not refund failed
  sends. Cooldowns reset on cog reload; definitions persist in Red Config.
- `[p]twitchset prefix !` changes the Twitch prefix. Discord keeps its own prefix.
- `[p]twitchset enabled false` pauses chat logging and custom commands on both
  platforms. Twitch announcements are also blocked while paused. Discord-only
  owner announcements remain available.
- Registered Discord commands take precedence. Avoid existing Tag or Alias names
  for shared commands, since those independent cogs can also respond.
- Paimon's own Twitch messages are logged but never executed as commands. Messages
  from other channels in a Shared Chat session cannot trigger custom commands.
- A separate 100-item command queue keeps reply delivery out of the EventSub
  receive loop. Twitch sends are serialized at least 2.1 seconds apart globally.
  Twitch API failures and dropped messages are reported through status; sends are
  never automatically retried to avoid duplicate output.
- `[p]twitchset disconnect` removes the broadcaster/log mapping and pauses the
  integration; custom command definitions and announcement-channel settings remain.

## Announcements

Select a Discord destination, then send a message as the bot:

```
[p]twitchset announcements #announcements
[p]twitchannounce twitch We are starting soon!
[p]twitchannounce discord We are starting soon!
[p]twitchannounce both We are starting soon!
```

Twitch destinations use Twitch's native announcement banner. Discord receives an
ordinary text message. They require bot-owner access. Paimon's Twitch account must
be a channel moderator (or the broadcaster) and must approve the announcement scope
using `[p]twitchset authbot` after this update. Missing permission fails explicitly;
there is no fallback to a normal Twitch message.

Choose the Twitch banner color with `[p]twitchset announcementcolor purple`.
Supported colors: `primary` (default, channel accent), `blue`, `green`, `orange`,
`purple`. Twitch accepts one announcement every two seconds; the shared send lock
spaces outbound messages by 2.1 seconds. The maximum is 500 characters for all
three destinations. `both` reports each platform separately: success on one does
not imply success on the other. Discord sends disable mentions and link previews.
Twitch messages use the dedicated bot account. Twitch's shared-chat behavior may
also show bot messages to other channels participating in that shared session.

## Test this update live

1. Re-authorize the bot account and check `twitchset status` for chat-writing approval.
2. Add `hello`, set its platform to `both`, and run it in Twitch and Discord.
3. Check `{user}` and `{args}` with two different people.
4. Set a 10-second cooldown; trigger in Twitch and immediately in Discord. Only
   the first should answer. Wait and check that the next invocation works.
5. Restrict it to moderator, verify a regular viewer/member cannot trigger it,
   and confirm a moderator can. Return permissions to everyone afterward if desired.
6. Send announcements to each destination. Verify messages come from Paimon.
7. Edit/remove a command and verify the change takes effect without a reload.
8. Reload the cog and verify definitions, mapping and chat logging still work.

## Local tests

```
python -B -m unittest discover -s twitchbridge/tests -v
```


## Verified member linking (no crate changes)

Members run these commands in the Discord server linked to the broadcaster:

```
[p]twitchlink THEIR_TWITCH_USERNAME
[p]twitchlink status
[p]twitchlink unlink
```

The bot resolves the permanent Twitch account ID, then DMs a one-time code. The
member signs into that Twitch account and posts `!link CODE` in the linked
broadcaster's Twitch chat (or the configured Twitch prefix). The code expires in
10 minutes and works only for the requesting Discord member, selected Twitch ID,
and server/broadcaster. A copied code sent by another Twitch user cannot claim it.
Discord membership is checked again on completion. Twitch usernames can change;
identity is anchored to the permanent ID. Repeat setup after a rename if necessary
for the displayed username. One-to-one links are enforced separately per server.

Successful linking is confirmed by DM. Codes are hidden in the mirrored Discord
log, although verification messages remain visible in Twitch chat. Twitch may
block repeated messages or filter chat; ensure the verification message actually
appears. Requests have a 15-second per-member delay and a 1,000-pending-request
limit. Codes are memory-only; reload cancels unfinished verification.

Unlink cancels pending requests, removes the identity association and attempts to
remove only roles granted by this integration. Failed removals remain tracked and
are retried by periodic cleanup. No crate method is called: existing Twitch and
Discord inventories are neither read nor merged in this update.

## Per-broadcaster role synchronization

Configure each linked Discord server independently, as bot owner:

```
[p]twitchroles map moderator @Twitch-Moderator
[p]twitchroles map subscriber @Twitch-Subscriber
[p]twitchroles map vip @Twitch-VIP
[p]twitchroles map broadcaster @Broadcaster
[p]twitchroles authorize
[p]twitchroles enabled true
[p]twitchroles sync
[p]twitchroles status
```

Choose only the mappings you need. The authorization DM must be approved by that
server's verified Twitch broadcaster. It uses the complete broadcaster bundle
listed above. Broadcaster mapping uses the verified broadcaster ID. Adding or
removing these mappings no longer changes the approval requirements.
Subscriber queries require a channel with Twitch subscriptions available; otherwise
leave the subscriber mapping out. This is independent of Discord's native Twitch
integration: choose separate roles to avoid two systems managing the same role.

Only verified linked members qualify. The bot polls every 15 minutes; `sync` checks
immediately. Enable Discord's Server Members intent for reliable member caching;
the cog fetches individual members on cache misses. Paimon requires Manage Roles
and a highest role above mapped roles. Administrator, managed and everyone roles
are rejected. This copies status from Twitch into Discord only.

Twitch tokens are validated and refreshed, and all configured status lookups must
succeed before status-based role changes occur. Missing scopes, API outages or
invalid broadcaster approval leave existing qualifying-status grants unchanged.
The integration tracks roles it actually adds. Pre-existing manually assigned
roles are not claimed and will not be removed by synchronization. If two statuses
map to the same role, either status is sufficient to retain the role. Avoid manually
reassigning integration-owned roles if you want independent ownership.

```
[p]twitchroles unmap subscriber
[p]twitchroles enabled false
[p]twitchroles cleanup
```

Removing a mapping removes tracked grants on the next enabled successful sync;
removing all mappings triggers cleanup on that check. Pausing sync preserves linked
members' roles. `cleanup` pauses sync and attempts to remove all integration-owned
roles. Hierarchy/permission failures remain tracked; fix permissions and repeat.
Changing/disconnecting a broadcaster also attempts cleanup and pauses role sync.
Verified member identities remain, while new broadcaster status access requires
fresh authorization. Settings and grants are persisted; immediate changes can take
up to the next polling cycle unless you run `sync` yourself.

Red user-data deletion removes member links, pending challenges and tracking IDs,
and attempts role removal. If role cleanup fails during a deletion request, the
tracking ID is still erased for privacy; an administrator must remove that role
manually. Existing mirrored Discord log messages have their own retention.

## Shoutout follow messages

In Twitch, moderators and the broadcaster can run:

```
!so luna
!shoutout https://twitch.tv/luna
```

In Discord, Red moderators, members with Manage Server, and bot/server owners can
run `[p]twitchshoutout luna`. It sends the follow message to the linked Twitch chat
and confirms delivery in Discord. Linking the target's Discord account is not
required. Twitch account lookup confirms the canonical username and constructs the
URL; external domains, extra paths and URL query strings are rejected.

Configure the per-server message and cooldown as bot owner:

```
[p]twitchset shoutoutmessage Go follow {user} at {url}!
[p]twitchset shoutoutcooldown 60
```

The message must contain `{url}`; `{user}` is Twitch's display name and `{channel}`
is the linked broadcaster. The same server-wide cooldown applies to Twitch and
Discord triggers (0-86400 seconds, default 60). Messages must fit the shared
500-character limit. This is a configurable follow message, not Twitch's native
shoutout card or an announcement banner. `link`, `so`, and `shoutout` are reserved
Twitch triggers; remove older custom commands with those names if needed.

## Live checks for linking, roles, and shoutouts

1. Push/update/reload `twitchbridge`. Existing command/log settings remain.
2. Have a member link; post the code as a different Twitch account first and check
   that it fails, then complete it as the requested account. Check `twitchlink status`.
3. Confirm neither crate inventory changed. Try linking the same Twitch account
   to another Discord member in that server; it must be rejected.
4. Map a dedicated test role, approve broadcaster access, enable role sync and run
   `sync`. Confirm matching linked members receive it and nonmatching ones do not.
5. Remove the Twitch status and sync again. Only the integration-granted role
   should be removed. An equivalent pre-existing manual role must remain.
6. Test unlink and cleanup, reload persistence, and check `twitchroles status`.
7. Test Twitch `!so username` as a moderator and as a regular viewer; only the
   moderator should send a shoutout. Test the Discord command and shared cooldown.
8. Change the shoutout template, check the canonical follow URL, and verify that
   ordinary chat logging and native announcements still work.

Additional Twitch API references:
https://dev.twitch.tv/docs/api/reference/#get-moderators
https://dev.twitch.tv/docs/api/reference/#get-broadcaster-subscriptions
https://dev.twitch.tv/docs/api/reference/#get-vips


## Member linking panel (no commands or DMs required)

As bot owner, configure the text and button label, then post the panel:

```
[p]twitchroles paneltext Connect your Twitch account here to receive your server roles.
[p]twitchroles panellabel Connect Twitch
[p]twitchroles panel #account-linking
```

Each server has one active panel. Members click the button, enter their Twitch
username in a modal, and receive a private Twitch approval link. After signing in
as that account and approving, Paimon verifies the permanent Twitch ID and links
it to the Discord member who opened the modal. A Twitch approval for another
account fails. Members do not type commands in Discord or Twitch and do not need
DMs enabled. The legacy `.twitchlink username` chat-code flow remains available.

Panel approval requests **no Twitch action scopes**. Member access tokens are
used once to verify identity, then revoked; neither member access tokens nor
refresh tokens are saved. Only the verified identity link and timestamp remain.
Crate inventories are not touched. Linked members are checked for role eligibility
promptly when role sync is enabled; normal 15-minute checks continue afterward.

Panel text supports 1-2000 characters; the button label supports 1-80. Changing text
or label updates the existing panel. Posting a new panel deactivates the previous
one and cancels unfinished approvals. `[p]twitchroles panelremove` deactivates it.
A saved panel resumes after cog reload or bot restart; unfinished approvals must
be started again. Deleted Discord panel messages can be replaced by posting a new
panel. The bot must be able to view the channel and send/edit its own messages.

Approvals expire locally after ten minutes. Changing the broadcaster, removing
the panel, unlinking or deleting member data invalidates the pending request.
Approvals are bound to the current Discord user, server, panel and Twitch ID.
Link conflicts remain rejected. Pending tasks are bounded, and unlinking cancels
both in-progress approval and older chat-code requests.

Discord does not expose arbitrary members' profile connections through the bot
API. Reading Twitch connections requires each member to authorize Discord's
`connections` OAuth scope, which would add another login/callback service. This
panel uses direct Twitch approval instead; it does not scrape Discord profiles.

Username-only shoutouts already work: `!so luna` and `[p]twitchshoutout luna`
resolve the Twitch username and generate `https://twitch.tv/luna`. A URL is optional.

### Live checks for this update

1. Update/reload the whole cog and approve the bot and broadcaster bundles once.
2. Post the linking panel, click it as a regular member, enter the Twitch username,
   and approve it. Check a successful private confirmation with no public code.
3. Try approving the wrong Twitch account; it must not create a link.
4. Disable DMs and repeat with another member; button linking should still work.
5. Change the panel text/label, reload the cog, and check that its button still works.
6. Remove/replace a panel during approval; the old request must not create a link.
7. Verify role sync and username-only shoutouts. Confirm crate inventories remain
   unchanged.

References:
https://docs.discord.com/developers/topics/oauth2#shared-resources-oauth2-scopes
https://discordpy.readthedocs.io/en/stable/interactions/api.html#discord.ui.View
https://discuss.dev.twitch.com/t/public-client-device-code-flow-support-for-empty-oauth-scopes/65202


## Channel event messages

Event messages are independent of member linking, roles and crates. Each linked
broadcaster has a separate event listener, permission check and configuration.
Nothing is announced until the owner opts in for that broadcaster's server.

After updating/reloading the cog, authorize the broadcaster once for follows and
cheers (the bundle now includes `moderator:read:followers` and `bits:read`):

```
[p]twitchevents authorize
[p]twitchevents preview follow
[p]twitchevents enabled true
[p]twitchevents status
```

Approve the DM as **the broadcaster**, not Paimon's account. Existing subscription
permission is `channel:read:subscriptions`. No additional bot approval is needed
if chat replies and announcements already work. Existing broadcaster approvals
remain usable for event types they already cover. Missing scopes are shown per
event type; they do not stop chat logging or the other available events.

### Supported events and placeholders

| Event name | Behavior | Available placeholders |
| --- | --- | --- |
| `follow` | Thank a new follower | `{user}`, `{channel}`, `{url}` |
| `subscribe` | Thank a new non-gift subscriber | `{user}`, `{channel}`, `{url}`, `{tier}` |
| `resub` | Thank someone who shares a resubscription message | `{user}`, `{channel}`, `{url}`, `{tier}`, `{months}`, `{message}` |
| `gift` | Thank the gifter once for the gift summary | `{user}`, `{channel}`, `{url}`, `{tier}`, `{count}` |
| `cheer` | Thank a Bits cheer | `{user}`, `{channel}`, `{url}`, `{bits}`, `{message}` |
| `raid` | Welcome an incoming raid | `{user}`, `{channel}`, `{url}`, `{viewers}` |

`{user}` is the event's actor; for raids it is the incoming broadcaster. `{url}` is
that actor's Twitch URL. Anonymous gifts and cheers use `Anonymous` and an empty
URL, regardless of any identity fields in the payload. Tier is 1, 2 or 3; months
is cumulative subscription months. Gift recipients are skipped by `subscribe`
to avoid duplicating the gift summary. Disabling `gift` therefore suppresses gift
acknowledgements altogether. Silent subscription renewals do not generate shared
resub messages. Refollows or suspected follow spam may be suppressed by Twitch.

### Configure messages in the broadcaster's Discord server

All commands below require bot-owner access:

```
[p]twitchevents message follow Welcome {user}! Thanks for following {channel}!
[p]twitchevents message subscribe Thank you for subscribing, {user}!
[p]twitchevents message resub Thanks for {months} months, {user}!
[p]twitchevents message gift Thank you {user} for gifting {count} subs!
[p]twitchevents message cheer Thank you {user} for {bits} Bits!
[p]twitchevents message raid Welcome {user} and your {viewers} raiders! Follow them at {url}!
[p]twitchevents preview raid
[p]twitchevents event follow true
[p]twitchevents event cheer false
[p]twitchevents cooldown follow 5
[p]twitchevents mode chat
[p]twitchevents mode announcement
[p]twitchevents enabled false
```

- All six types have default messages and start selected, but the overall event
  feature is off by default. `enabled true` opts in to all currently selected types.
- `event <type> true/false` selects individual event types.
- `message <type> <text>` saves a template; unknown placeholders, formatting
  expressions, and templates over 4000 characters are rejected. Expanded messages
  are normalized to a single line and truncated to 500 characters when necessary.
- `preview <type>` sends an example to the invoking Discord channel only. It never
  fabricates a live Twitch event or sends a message to Twitch.
- `cooldown <type> <seconds>` sets a per-broadcaster, per-event delivery cooldown
  from 0-86400 seconds (default 0). Events arriving during cooldown are dropped,
  not combined or replayed later.
- `mode chat` is the default. `mode announcement` sends native Twitch banners
  using the existing announcement color and requires the bot's announcement scope
  and moderator status. This choice is separate for each broadcaster.
- `status` shows the event connection, active/failed subscription types, last
  delivery result and queued/sent/dropped counters since cog load.
- `twitchset enabled false` pauses all event responses too. Changing broadcasters,
  changing event settings or disabling an event invalidates its old queued events.

### Delivery and connection behavior

These are separate broadcaster-authorized EventSub WebSockets, so a follow/sub
permission issue cannot disconnect the bot-authorized command/chat logger. Each
broadcaster's scope and subscription failures are reported separately. One failed
subscription (for example, subscriptions unavailable on that channel) does not
remove successful follow/raid subscriptions. Reconnection recreates subscriptions
on a lost socket, while Twitch-requested handoffs transfer them without duplicates.

Outgoing replies share the existing 2.1-second send limiter with commands and
announcements. Event delivery has a separate 200-item global queue. Duplicate
EventSub IDs are suppressed by a bounded in-memory cache; gift recipient events
are suppressed in favor of the gift summary. Events older than two minutes, queue
overflow, cooldown drops and rejected sends increment the dropped counter.
Network-ambiguous sends are not automatically retried. Queues, counters and event
payloads are memory-only and reset on reload; no persistent event archive is made.

No historical follows or subscriber lists are announced at startup. Only new
EventSub notifications received while connected are processed. Twitch does not
replay every event missed during disconnects; do not treat chat thank-you messages
as an accounting record. Existing Twitch Shared Chat behavior applies: user-token
chat messages/announcements may also appear in the shared session's other channels.

### Live verification

1. Approve the broadcaster bundle and enable events in a single test server.
2. Check `twitchevents status` for active types; preview each template in Discord.
3. Test a genuine new follow and an incoming raid. Confirm one appropriate reply
   appears in the correct Twitch channel.
4. Test subscriptions, resubs, gifts and cheers as those events occur naturally;
   do not spend money solely to test. Local tests cover their simulated payloads.
5. Disable a type and confirm it stays silent. Switch chat/announcement modes and
   check the next real event. Reload and verify enabled settings are preserved.
6. Set up a second broadcaster with different messages; verify routing stays
   separate and pausing one does not stop the other's listener or chat commands.

Twitch reference: https://dev.twitch.tv/docs/eventsub/reference/channel


## Stream tools update: timers, to-dos, counters, ads, triggers and attendance

Push the complete `twitchbridge` folder, then run `[p]cog update twitchbridge`
and `[p]reload twitchbridge`. For ad controls, approve the broadcaster again with
`[p]twitchset authorize`: `channel:read:ads`, `channel:manage:ads` and
`channel:edit:commercial` are newly included in the broadcaster bundle. Bot
permissions are unchanged. Other new tools use existing permissions.

All features are configured in the broadcaster's linked Discord server. Setup
requires bot-owner access unless described otherwise. Timers/triggers opt in when
added; ad warnings, streak tracking and first-message greetings start disabled.
Queues/status reset on reload; saved lists, counters, attendance and settings persist.
Existing crate data is not used or modified.

### Shared response variables

Custom command responses, timer text, chat-trigger text and first-message greetings
all support:

| Variable | Value |
| --- | --- |
| `{user}` | Invoking viewer/member display name; empty for timer messages |
| `{args}` | Command arguments, or the original triggering/greeting chat text |
| `{channel}` | Linked broadcaster username |
| `{url}` | Actor's Twitch URL when a Twitch login is available; empty otherwise |
| `{counter}` | Increment the counter named after this command/timer/trigger |
| `{counter:deaths}` | Increment a named counter shared by any response using that name |
| `{uptime}` | Live uptime as hours/minutes/seconds, or Offline |
| `{title}` | Stream title, or last configured channel title offline |
| `{game}` | Game/category, or last configured category offline |
| `{viewers}` | Twitch's live viewer count; 0 offline |
| `{live}` | Live or Offline |
| `{streak}` | Actor's recorded streak; 0 if unavailable/tracking disabled |

Discord custom responses can use verified account links for `{url}` and `{streak}`;
linking remains optional for normal Discord commands. Stream data is cached for up
to 30 seconds. Twitch API failures are reported in `[p]twitchset status`, rather
than replacing live data with invented values.

Counters persist per server, increase once for each distinct referenced counter
per accepted response, and update under a lock. Repeating `{counter}` twice in one
response increments it once. Response text is never evaluated as code or recursively
interpreted. Failed delivery can still consume an increment: counters count accepted
invocations, not confirmed messages. Cooldown/permission denials do not increment.
Unknown placeholders remain literal. Custom commands must fit 500 characters after
expansion; automatic messages normalize whitespace and truncate to 500 characters.

```
[p]twitchcommand add deaths Death count: {counter:deaths}
[p]twitchcommand platform deaths both
[p]twitchcounter view deaths
[p]twitchcounter reset deaths
[p]twitchcounter set deaths 25
[p]twitchcommand add streaminfo {title} | {game} | Live for {uptime} | Viewers: {viewers}
```

Counter names use 1-32 letters/numbers/underscores. There are at most 1000 counters
per server. `set` accepts 0-1000000000. Setup commands do not themselves increment.

### Timed Twitch messages

```
[p]twitchtimer add socials 600 Follow our socials! Current game: {game}
[p]twitchtimer enabled socials false
[p]twitchtimer liveonly socials false
[p]twitchtimer list
[p]twitchtimer remove socials
```

`add <name> <seconds> <message>` also replaces an existing timer. Intervals are
10-86400 seconds; up to 50 timers are allowed. Adding a timer enables it, with
live-only posting by default. `liveonly false` allows offline chat posting.
The first message waits a full interval. Reload, new live sessions or automation
configuration changes restart interval timing. Missed intervals are not replayed.
Live/offline transitions are polled and can take about 30 seconds to be observed.

### Shared Twitch/Discord to-do list

In Twitch:

```
!todo add Finish the next quest
!todo view
!todo del 1
```

In Discord, use the same normal prefix with `.todo ...` when there is no registered
Discord command called todo, or use these unambiguous commands:

```
[p]twitchtodo add Finish the next quest
[p]twitchtodo view
[p]twitchtodo del 1
[p]twitchtodo permission everyone
```

One list is shared by the server and its linked Twitch channel. Viewing is open;
editing defaults to Twitch moderators/broadcaster and Discord Red moderators,
Manage Server, server owner or bot owner. The bot owner can change editing access
to `everyone`, `moderator`, or `broadcaster` with the permission command. In Discord,
`broadcaster` maps to server owner/bot owner, not an unverified Twitch username.
Lists hold 100 items of up to 250 characters each. Deletion uses the current
one-based number and renumbers remaining items. Run view again before deleting
if someone else has edited the list. Long Twitch lists require multiple replies
and obey Twitch's message rate limit; Discord output is grouped into messages.
Avoid conflicting Tags/Alias commands named todo. Canonical `twitchtodo` is always
available regardless of an existing unrelated todo command.

### Ad warnings, snooze and manual commercial breaks

```
[p]twitchads leads 300 60 10 1
[p]twitchads message Ads start in {ad_seconds} seconds for about {ad_duration} seconds.
[p]twitchads mode chat
[p]twitchads enabled true
[p]twitchads status
[p]twitchads snooze
[p]twitchads run 60
```

Lead times are configurable from 300 seconds down to 1 second. You may select one
or several times. Default lead time is 300 seconds. Mode may be `chat` or
`announcement`; banner mode uses the existing announcement color/permissions.
`{ad_seconds}` is remaining time; `{ad_duration}` is Twitch's scheduled break
length. The shared response variables above also work in ad warning templates.

Twitch `!ads status` shows the next ad and available snoozes. Only the actual
broadcaster can run `!ads snooze` or `!ads run 60` from Twitch chat; moderators cannot
force these actions. Discord mutations require bot-owner access. Commercial
lengths supported by the command are 30, 60, 90, 120, 150 and 180 seconds.

Snooze calls Twitch's real five-minute snooze endpoint, consumes an available
snooze, suppresses further warnings for five minutes and then re-arms against the
new Twitch schedule. If Twitch has no snoozes left, the operation fails explicitly.
The pause time persists through reload. Manual commercials require an eligible
live partner/affiliate channel and respect Twitch's returned cooldown. Starting
an ad refreshes Twitch's actual next-ad timestamp; this API does not let Paimon
arbitrarily reset Twitch's Ads Manager schedule to a chosen interval. Only Twitch
controls that schedule, and the command reports the resulting next ad.

Schedules are refreshed approximately every 15 seconds and again before a warning
is sent. A lightweight local scheduler checks deadlines four times per second.
Warnings are prioritized ahead of queued automatic messages, but still share
Twitch's global send limiter. A one-second lead is **best effort**, not a precise
delivery guarantee: network delays, queue contention or Twitch limits may make it
late, in which case it is dropped instead of announcing an ad that already started.
When starting late, one timely threshold is sent instead of replaying all missed
warnings. Sent/attempted warning thresholds are persisted to avoid repeats after
reload. Ad mutations are never automatically retried after an ambiguous failure.
No live ads were run during development; all ad tests use simulated API responses.

Twitch's API contract: https://dev.twitch.tv/docs/api/reference/ads

### Word/phrase chat triggers

```
[p]twitchtrigger add hello hello Hello {user}! Welcome to {channel}.
[p]twitchtrigger add gg "good game" GG {user}! Current game: {game}
[p]twitchtrigger cooldown hello 30
[p]twitchtrigger enabled hello false
[p]twitchtrigger list
[p]twitchtrigger remove hello
```

Matching is case-insensitive with word boundaries, so `hi` will not match inside
`this`. Quote multi-word phrases. Up to 50 triggers are allowed. New triggers
start enabled with a server-wide 30-second cooldown. Command-prefixed chat is
excluded from word triggers. Paimon's own messages and Shared Chat messages from
other channels do not trigger them. `{args}` contains the matched chat message.

### Stream streaks

```
[p]twitchstreak enabled true
[p]twitchstreak breakonmiss true
[p]twitchstreak set luna 20
[p]twitchstreak add luna 5
[p]twitchstreak view luna
[p]twitchstreak forget luna
```

Viewers can use `!streak` in Twitch to see their own value. Tracking counts the
first message from a viewer in each observed live stream, identified by Twitch's
permanent stream ID. Extra messages in the same stream never increment it.
With `breakonmiss true` (default), missing an observed stream resets the count to
1 when they next speak; false retains the count and adds one per attended stream.
Migration set/add numbers include the currently observed live stream, preventing
an immediate extra increment from that stream's next chat message.

Attendance is stored by permanent Twitch user ID and broadcaster, independently
of Discord linking or username changes. Paimon cannot detect silent attendance,
reconstruct chat during downtime, or know every stream it missed while stopped.
Only streams observed while tracking/greetings are active can affect a missed
stream calculation. Very short streams may fall between polling intervals.
Owner-only forget removes streak and greeting history plus per-user greeting text
for that Twitch account. Verified linked user data is also removed by Red's data
deletion hook. Unlinked viewers can ask the bot owner to forget their Twitch ID.

### First-message greetings and automatic follow messages

```
[p]twitchfirst message Welcome {user}! We are playing {game}.
[p]twitchfirst mode ever
[p]twitchfirst mode stream
[p]twitchfirst enabled true
[p]twitchfirst everyone false
[p]twitchfirst user luna Go follow {user} at {url}!
[p]twitchfirst removeuser luna
```

`ever` (default) greets a viewer once after this feature begins observing them.
`stream` greets on their first message each live stream. It does not fire merely
because someone appears in the viewer list. Default greetings apply to everyone
unless `everyone false` is set; per-user templates still apply when false. This
supports automatic shoutout-style follow messages for selected viewers. It posts
the configured text, not Twitch's native shoutout card.

Greeting eligibility is saved before queueing to prevent duplicate greetings on
reconnect. A rejected/overflowed send is not retried on every subsequent message.
All automatic traffic uses bounded queues and the existing send limiter. Messages
older than 60 seconds, stopped streams, changed configurations and changed target
broadcasters are discarded. Use `[p]twitchset status` for the last automation result
and queued/dropped counts.

### Suggested live checks

1. Verify existing logging, commands, linking panels and roles still work.
2. Add a live-only timer; confirm it waits its interval and stops posting offline.
3. Add/view/delete to-dos across Twitch and Discord, checking edit permissions.
4. Run a counter command, reset/set it, and verify the value survives reload.
5. Compare stream variables with Twitch while live and offline.
6. Test whole-word triggers and cooldowns, then greeting ever/stream modes with
   separate accounts and a per-user follow message.
7. Check streaks across two observed streams, a missed stream, and migrated totals.
8. Approve ad permissions, read the schedule, and observe warning timing. Test a
   snooze or a manual commercial only when the broadcaster intends to run ads.


## Moderator stream metadata controls

Update/reload the cog, then approve the broadcaster once with
`[p]twitchset authorize` to add `channel:manage:broadcast`. Bot authorization is
unchanged. Twitch requires the linked broadcaster's token for channel edits;
Paimon checks the invoking moderator before using that permission.

Twitch moderators and the broadcaster can change:

```
!title A new adventure begins!
!game Minecraft
!category Just Chatting
!tags English Cozy Community
!tags clear
!language en
```

With no arguments, `!title`, `!game`, `!category`, `!tags`, and `!language` show the
current value; regular viewers may use these read-only forms. Game and category
are aliases for the same Twitch field. Mutations require the real Twitch
moderator badge or broadcaster ID. Ordinary viewers cannot change any field.

In Discord, Red moderators, members with Manage Server, server owners and bot
owners can use:

```
[p]tstream title A new adventure begins!
[p]tstream game Minecraft
[p]tstream category Just Chatting
[p]tstream tags English Cozy Community
[p]tstream tags clear
[p]tstream language en
```

Omit a value to read it. Discord uses its own moderator permissions; members do
not need to link their Twitch account just to use these Discord commands.
The command always targets that Discord server's configured broadcaster. No
command accepts an arbitrary broadcaster as an update target.

Titles must contain 1-140 characters. Category lookup accepts a name or numeric
Twitch category ID, prefers an exact name match and rejects ambiguous searches
with suggestions. If several match, repeat using the full name or listed ID.
Numeric IDs are validated before updating because Twitch can ignore unknown IDs.
Tags replace the entire tag list: at most 10 unique alphanumeric tags, each up to
25 characters; comma/space separation is supported and `clear` removes all tags.
Language accepts a two-letter code such as en, or other; Twitch validates whether
that language is supported. Only the requested field is patched, preserving all
other channel settings, content labels and stream properties.

Successful updates invalidate the stream-information cache so `{title}` and
`{game}` can refresh promptly. Failed updates do not claim success and are not
automatically retried. Metadata can also be configured while offline, provided
the integration is enabled. Twitch mutation trigger names `title`, `game`,
`category`, `tags`, and `language` are now reserved built-ins; remove older custom
commands with those names if necessary.

Live checks: try reads as a viewer; verify writes fail for a viewer and succeed
for a moderator; test a full category name and an ambiguous one; confirm another
linked broadcaster is unaffected; then check stream variables after updating.
No live channel settings were changed during development.

Twitch references:
https://dev.twitch.tv/docs/api/reference/channels#modify-channel-information
https://dev.twitch.tv/docs/api/reference/search#search-categories


## Custom command aliases

Bot owners can give any TwitchBridge custom command up to ten alternate names:

```
[p]twitchcommand alias add socials links
[p]twitchcommand alias add socials social
[p]twitchcommand alias list socials
[p]twitchcommand alias list
[p]twitchcommand alias remove links
```

Create the original command with `twitchcommand add` first. An enabled Twitch
command `!socials` can then also be invoked as `!links` or `!social`, with the same
arguments and response. On Discord, the normal prefix works for each name when
the original command's platform is discord or both.

Aliases share the canonical command's permission checks, platform setting,
cooldown and implicit `{counter}`. They cannot bypass a cooldown or create an
independent death counter. Editing any alias edits the original response, so all
names stay in sync. Aliases point directly to the original, including when the
alias-add target is itself an alias. Names are case-insensitive and follow normal
custom-command naming rules.

Names already used by another custom command, alias, TwitchBridge built-in or
currently registered Discord command are rejected when the custom command is enabled in Discord. Twitch-only commands and aliases may share Discord command names. Future Discord command-name
collisions still give precedence to the registered Discord command; choose unique
names. No extra Twitch permission or authorization is needed.

`alias remove <alias>` removes only that alternate name. `twitchcommand remove`
with an alias name also removes just that alias. Removing the original command
removes all its aliases. `twitchcommand list` now shows aliases and paginates output.
Existing saved commands need no migration; absent aliases mean an empty list.

This feature manages TwitchBridge custom responses. It does not rename or create
aliases for unrelated Red cogs or the built-in stream-management command groups.

### Per-game death counters

Enable separate game totals for your counter (use its existing name):
```
.twitchcounter pergame deaths true
.twitchcommand add death {game} deaths: {counter:deaths}
.twitchcounter view deaths
.twitchcounter set deaths 25
.twitchcounter reset deaths
```
If `death` already exists, use `twitchcommand edit` instead of `add`.
Twitch `!death` increments the current game's total. Twitch's selected category is
checked fresh on each use; returning to a game resumes that game's saved total.
Storage is separate per broadcaster and Twitch category ID, shared between Discord
and Twitch. A live stream with a selected category is required. This detects the
category, not deaths inside the game: each accepted counter command adds one.
View, set and reset apply only to the current game. Previous global totals remain
untouched; set the current game's value manually to migrate an old total.
`.twitchcounter pergame deaths false` returns to the preserved global counter.
For an existing response using plain `{counter}`, enable per-game tracking for the
original command's name instead (aliases use the original name). Other counters
remain global unless explicitly enabled.

### Game variable across message features

`{game}` is supported in custom commands, word triggers, timers, first-message
messages (including per-user overrides), ad warnings, shoutouts, and all six
channel-event message types and their Discord previews. It always means the
linked broadcaster's current Twitch category, including in raid and shoutout
messages; it does not describe the visitor's game. Offline it uses the last
configured category. Stream metadata is cached for up to 30 seconds. Events and
shoutouts use `Unknown game` when category lookup fails or no category is set,
so an unavailable category does not suppress the alert. Existing templates
without `{game}` do not require an additional category lookup.

```
.twitchevents message follow Thanks for following, {user}! Enjoy {game}!
.twitchevents preview follow
.twitchset shoutoutmessage Follow {user} at {url}! We're playing {game} here.
.twitchtrigger add gamecheck "what game" We're playing {game}!
```

### Event user's game

All `twitchevents` message types also accept `{usergame}`. It resolves the event
actor's channel category: the follower, subscriber, resubscriber, gift sender,
cheerer, or incoming raider. `{game}` still means the linked broadcaster's category.
The lookup happens only when `{usergame}` is used and needs no additional user
authorization. Offline it reads their currently configured category, generally
the last streamed category; it is not a historical record and can change offline.
Anonymous events, missing categories and lookup failures use `Unknown game`.
Discord previews use `Example game` for this placeholder.

```
.twitchevents message raid Welcome {user} and your {viewers} raiders! They last played {usergame}! Follow them: {url}
.twitchevents preview raid
```

### Extended response variables

These work in custom commands (Discord and Twitch), word triggers, timers,
first-message greetings and overrides, ad warning templates, shoutout templates,
and every channel-event type and its preview. Simple one-shot announcements
remain literal text. Templates may contain up to 4000 characters; final chat
messages still have the existing 500-character limit. There is no separate limit
on the number of choices in a list within the template size. Keep each possible
rendered reply within 500 characters. Use straight double quotes around responses.
Apart from the `{roll}` marker inside `randomreply`, expressions cannot be nested: selected replies and fetched content are literal
text, never executed or interpreted as additional variables. Put common fields
outside the expression, e.g. `{user}: {choose "Yes!" "No!"}`. Repeating the exact
same expression in a message reuses its first result (one roll/lookup).

| Variable | Example | Result |
| --- | --- | --- |
| Countdown | `{countdown 2026-12-25 00:00:00 America/Toronto}` | Full months, weeks, days, hours remaining |
| Alternative date format | `{countdown dec 25 2026 12:00:00 AM EST}` | Same duration format; EST is fixed UTC-5 |
| Random integer | `{random 1 100}` | Inclusive random integer from 1 through 100 |
| Weighted random response | `{randomreply 10 "Response A" 80 "Response B" 100 "Response C"}` | A for rolls 1-10, B for 11-80, C for 81-100 |
| Equal random response | `{choose "Response A" "Response B" "Response C"}` | Each choice is equally likely |
| Fetch a text response | `{urlfetch https://example.com/facts}` | Plain-text or JSON response, normalized to one line |
| Follow duration | `{followage}` | Chat user's months, weeks, days and hours following the linked broadcaster |
| Local time | `{time Europe/Helsinki}` | Current date and 24-hour time with timezone abbreviation |
| Weather | `{weather Helsinki/Finland}` | Current model conditions and temperature in Celsius, attributed to Open-Meteo |

Weighted thresholds are positive, strictly increasing cumulative upper bounds.
The last threshold sets the roll maximum; 10/80/100 gives 10%, 70%, 20% odds.
Add more threshold/response pairs or more quoted choices as needed. Repeated uses
may choose the same answer; this does not rotate through or exhaust the list.

Countdowns use full calendar months (month-end dates are clamped), then weeks,
days and whole hours. Past dates return zero for every unit. The example date in
2025 is already past. Use IANA location zones for automatic daylight-saving rules;
EST/EDT and other supported US abbreviations have fixed offsets. Nonexistent local
times during spring DST changes are rejected; ambiguous autumn times use the
first occurrence. The `tzdata` dependency supplies location zones on Windows.

`{followage}` uses the authenticated Twitch chatter identity. For Discord custom
commands, link the member's Twitch account first. For events it uses the event
actor (the incoming raider for raids); anonymous events cannot be looked up.
For shoutouts it uses the target account. It requires the broadcaster's existing
`moderator:read:followers` permission; no extra scope was added. It reports
not-following separately from unavailable authorization/API data. Twitch's current
follow record is used, so unfollowing/re-following resets the reported duration.
It does not reconstruct historic follows or permanently store follow dates.

URL fetch permits public HTTPS URLs on port 443, including query strings. It
never forwards Twitch credentials, follows redirects, accesses private/local
addresses, or evaluates the returned content. DNS addresses are validated at
connection time. Reads time out after five seconds and stop at 64 KiB; up to
500 characters of fetched text are used. At most eight distinct extended
expressions may be used per template. Failures return readable fallback text
without echoing query tokens or internal errors. A preview performs the same
external lookups/random rolls as a real message but posts only in Discord.

Weather uses Open-Meteo geocoding and current conditions (a model estimate, not
a multi-day forecast); successful results cache for five minutes. City/country
queries such as `Helsinki/Finland` and quoted `New York/United States` are accepted.
The first geocoding match is used. No key is required for Open-Meteo's free
non-commercial service. For commercial use, configure a subscribed API key using
Red's shared tokens (`.set api openmeteo api_key YOUR_KEY`); requests then use the
customer endpoints. Review Open-Meteo's current service terms for your use case.

Example commands:
```
.twitchcommand add christmas Christmas in {countdown 2026-12-25 00:00:00 America/Toronto}!
.twitchcommand add dice {user} rolled {random 1 100}!
.twitchcommand add luck {randomreply 10 "Very lucky!" 80 "An ordinary day." 100 "Try again tomorrow!"}
.twitchcommand add answer {choose "Yes!" "No!" "Maybe!"}
.twitchcommand add facts {urlfetch https://example.com/facts}
.twitchcommand add followage {user} — {followage}
.twitchcommand add helsinki It is {time Europe/Helsinki} in Helsinki.
.twitchcommand add weather {weather Helsinki/Finland}
```
If a command already exists, use `twitchcommand edit` instead of `add`.

References: [Twitch follow information](https://dev.twitch.tv/docs/api/reference/channels),
[Open-Meteo weather](https://open-meteo.com/en/docs), and
[Open-Meteo location search](https://open-meteo.com/en/docs/geocoding-api).

### Mentioning a command target

`{args}` preserves the command argument text exactly. Use `{target}` to format the
first argument as a Twitch-style `@username`, whether the viewer typed `username`
or `@username`. It adds exactly one `@` and ignores any later arguments. Empty or
invalid first arguments produce an empty target. This formats a username; it does
not verify the account exists or create a Discord account mention.

```
.twitchcommand edit cheer Let's hear it for {target}!
```
Both `!cheer username` and `!cheer @username` respond with
`Let's hear it for @username!`. Do not put another `@` before `{target}`.

### Annually repeating countdowns

Omit the year to count down to the next occurrence in the specified timezone:
```
{countdown dec 25 12:00:00 AM America/Toronto}
{countdown December 25 00:00:00 America/Toronto}
{countdown 12-25 00:00:00 America/Toronto}
```
Once the target time is reached, the countdown automatically targets the next
year. February 29 advances to the next leap year. An explicitly supplied year
still makes a fixed countdown that stays at zero once past. Annual countdowns
use the same full months, weeks, days and hours output. Timezones follow their
usual DST rules; nonexistent local times are rejected.

```
.twitchcommand edit christmas Christmas is in {countdown dec 25 12:00:00 AM America/Toronto}!
```

### Showing the weighted response roll

Inside a quoted `randomreply` response, `{roll}` displays the same number that
selected the response. It does not make a second independent roll. For example:
```
{randomreply 10 "{roll}% — You're a kitten 🐱" 60 "{roll}% — Not so dangerous." 90 "{roll}% — Oh, we got a badass over here!" 100 "{roll}% — You are Meruem"}
```
This rolls 1-100: kitten is always 1%-10%, not dangerous 11%-60%, badass 61%-90%,
and Meruem 91%-100%. The bounds are inclusive. This is a 1-100 percentage scale,
rather than the original JavaScript's 0-99 scale. `{roll}` is only interpreted
inside a selected `randomreply` response; other nested variables are unsupported.

### Platform-specific name conflicts

New custom commands are Twitch-only, so their names may match commands from
other Discord cogs. For example, `.twitchcommand add rps ...` works even when
Discord already has an `rps` command. Twitch's reserved built-in names and names
already used by another custom command/alias are still protected.

Enabling `.twitchcommand platform rps discord` or `both` checks the original
command name and every alias against registered Discord commands (including
registered aliases). If any conflict, the entire platform change is declined
and the previous setting stays unchanged. The reply lists the conflicting names.
Aliases on Twitch-only commands follow the same rule: they may share Discord
names, but then prevent enabling that command in Discord. For commands already
enabled in Discord, adding a conflicting alias is declined. Registered Discord
commands retain precedence if another cog is loaded later.

### Public Twitch command list and permissions

Viewers can use `!twitchcommands`, `!tcommands`, or `!tcmds` to list the original
names of custom commands available to everyone on Twitch. Discord-only commands,
moderator/broadcaster commands and alternate names are omitted. It reads the
current settings each time, so adding/removing a command or changing permission
or platform updates the list automatically. All three names share a 30-second
per-channel cooldown. Long lists are split into messages of at most 500 characters.
The configured Twitch prefix applies to these built-ins and the displayed names.

The bot owner assigns custom command permissions in Discord:
```
.twitchcommand permission rps everyone
.twitchcommand permission rant moderator
```
`everyone` allows all viewers; `moderator` allows Twitch moderators and the
broadcaster. The existing `broadcaster` setting remains available. New commands
default to `everyone`. Aliases share their original command's permission. On
Discord-enabled commands, the existing Discord moderator/owner checks also apply.
Permission configuration stays owner-only; this does not grant viewers command
management access. The three command-list names are reserved Twitch built-ins.

### Target account game and channel URL

Custom command responses can use `{targetgame}` and `{targeturl}` alongside
`{target}`. They use the first argument, accepting `username` or `@username`.
`{targetgame}` looks up that account's currently configured Twitch category,
including when offline; it is not guaranteed stream-history data. Failed or
missing account/category lookups return `Unknown game`. `{targeturl}` constructs
an HTTPS Twitch channel link without the `@`; missing/invalid arguments produce
an empty URL. The game lookup only runs when requested. `{game}` continues to
mean the linked broadcaster's category.

```
.twitchcommand add follow Be sure to follow {target}! They were recently playing {targetgame} at {targeturl}
```

### Shared variables in built-in shoutouts

`shoutoutmessage` now uses the same renderer as custom commands. `{user}` is the
shouted-out display name, `{url}` is their channel URL, and `{args}` is their
canonical login. `{target}` mentions that account; `{targeturl}` is its channel
URL and `{targetgame}` its currently configured category. `{usergame}` is also
accepted here as an alias for `{targetgame}`. `{game}`, `{title}`, `{uptime}` and
`{viewers}` continue to describe the linked broadcaster's stream.

Shared random/choice, countdown, local-time, weather, URL-fetch, streak,
follow-duration and counter variables work too. Follow duration and streak use
the shouted-out Twitch account. Plain `{counter}` uses the `shoutout` counter;
named counters retain their normal behavior. A template must contain `{url}` or
`{targeturl}`. Normal moderator permissions, cooldowns and routing checks apply.

```
.twitchset shoutoutmessage Be sure to follow {target}! They were recently playing {targetgame} at {targeturl}
```
Use `!so username`, `!shoutout username`, or `.twitchshoutout username` as before.

### Hide location names in weather replies

Add `hidecity` after the location to omit its name from the response:
```
.twitchcommand edit weather For me it is currently {weather Tallinn/Estonia hidecity}
```
Example output: `For me it is currently clear skies, 7.5°C (Open-Meteo)`.
Without `hidecity`, the existing city label remains. Both modes use the same
five-minute cache. The configured location still exists in the saved template
and is sent to the weather provider; this option hides it in rendered chat replies.

### Global Twitch command library

The bot owner can configure a command once for every enabled linked Twitch stream:
```
.twitchglobal add octopus {choose "They have three hearts" "Their blood is blue."}
.twitchglobal edit octopus {choose "They have three hearts" "They taste with their arms."}
.twitchglobal permission octopus everyone
.twitchglobal cooldown octopus 10
.twitchglobal alias add octopus octofact
.twitchglobal alias list
.twitchglobal alias remove octofact
.twitchglobal list
.twitchglobal remove octopus
```
The global library is Twitch-only and does not register Discord chat commands, so
it may use names already registered by Discord cogs. Reserved Twitch built-ins
remain protected. Defaults are everyone permission and a five-second cooldown.
It supports the existing response variables, 4000-character templates, up to
250 command definitions and ten aliases per command. Permissions can be everyone,
moderator or broadcaster. Adding/editing/removing is restricted to the bot owner
from Discord; viewers invoke the commands using that stream's configured prefix.

Each invocation uses its own broadcaster's stream data and target/chatter context.
Cooldowns and counters are per linked stream; aliases share their original
command's cooldown and counter. Named counters use the stream's existing counter
storage, so matching counter names can intentionally share a total within that
stream. Command definitions persist globally in Red Config and apply immediately
to current streams and streams linked later, with no cog reload or per-stream setup.

Local custom command names and aliases take precedence over a matching global
name. A restricted or Discord-only local definition also blocks the matching
Twitch global name; it never falls back to a global command to bypass permission
or platform restrictions. The public `!twitchcommands` / `!tcommands` / `!tcmds`
list includes effective global and local public Twitch commands without duplicates.
Use `.twitchglobal list` to inspect all global definitions; `.twitchcommand list`
continues to show the current server's local definitions.

To copy an existing local command (including response, aliases, permission and
cooldown) into the global library:
```
.twitchglobal import octopus
```
This leaves the local definition untouched and forces the global copy to
Twitch-only. The local copy still wins in its original stream. After reviewing
the global copy, remove the local definition there if you want that stream to
use the global version:
```
.twitchcommand remove octopus
```
Import rejects any conflicting global name/alias without partially importing.

### Preview custom and global commands

The bot owner can preview messages in the current Discord channel:
```
.twitchcommand preview rps username
.twitchglobal preview octopus
```
Syntax is `preview <command-or-alias> [arguments...]`. Local previews inspect the
current server's local definition; global previews inspect the global definition
using this server's linked broadcaster. A global preview warns when the requested
name is overridden locally. The preview uses the invoking Discord display name
for `{user}` and their linked Twitch identity for URL/follow-duration/streak fields.
Arguments populate `{args}` and target variables just as in Twitch chat.

Nothing is sent to Twitch. Command permissions/platform flags and active cooldowns
do not prevent owner previews. Counter fields show the next value without saving
it, and cooldowns remain unchanged. Random choices are rerolled and weather/URL/
Twitch variables perform their normal reads, so live output may differ later.
Per-game counters still require a live stream/category. Discord mentions and link
embeds are disabled for preview messages.

### Current Discord and Twitch access policy

The following policy supersedes older owner-only and public-read descriptions
above. Discord Moderator/Administrator access includes Red-configured mod/admin
roles; Discord's Administrator permission also qualifies. Manage Server alone
no longer grants these staff commands.

| Discord command/group | Allowed users |
| --- | --- |
| `twitchset`, `twitchglobal` | Bot owner only |
| `twitchroles` | Bot owner, guild owner, administrators |
| `twitchlink` | Everyone in the server |
| `twitchcommand`, `twitchannounce`, `twitchshoutout`, `twitchtimer`, `twitchtrigger`, `twitchcounter`, `twitchevents`, `twitchads`, `twitchfirst`, `twitchstreak`, `twitchtodo`, `tstream` | Bot owner, guild owner, administrators, moderators |

These checks also apply to grouped subcommands. `twitchcommand` alias management
and preview are available to staff. `twitchglobal` management and preview remain
bot-owner-only. Broadcaster linking, bot authentication and connection settings
remain bot-owner-only even though staff can configure stream features.

`.todo` is a registered alias for `.twitchtodo`; either bare group shows the list.
`.todo add <text>`, `.todo view`, and `.todo del <number>` use the same per-server
list as Twitch's `!todo` commands. If another cog already owns the Discord `todo`
name, that command is preserved and TwitchBridge still loads with `.twitchtodo`.
The existing fallback path also checks staff access. Legacy to-do `everyone`
settings cannot bypass the moderator access floor; an explicitly selected
broadcaster-only editing policy can still make edits stricter.

Twitch moderator/broadcaster access is required for the full commands `!so`,
`!shoutout`, `!todo`, `!ads`, `!title`, `!game`, `!category`, `!tags`, and `!language`.
This includes read-only views, `!ads status`, `!todo view`, and metadata queries
with no arguments. Moderators can run and snooze ads through the already approved
broadcaster token; Twitch eligibility and ad/snooze limits still apply.
Other public built-ins (`!twitchcommands`, aliases, account linking and streak
viewing) remain available to everyone. Existing custom/global command-specific
permission settings are preserved.

### Twitch quotes posted to Discord

Discord bot owners, guild owners, administrators and moderators can configure
quote submissions for the linked Twitch broadcaster:
```
.twitchquote channel #quotes
.twitchquote permission everyone
.twitchquote mode embed
.twitchquote color purple
.twitchquote cooldown 10
.twitchquote enabled true
.twitchquote status
```
Twitch viewers then submit using `!quote <text>` (or the configured prefix).
Permission options are `everyone`, `moderator` (mods and broadcaster), or
`broadcaster`. Defaults are disabled, moderator permission, embed mode, blurple
color, and a 10-second shared per-channel cooldown. Settings are per linked server.

Use `.twitchquote mode message` for plain chat; `chat` also works as an alias for
message mode. Both formats include `Submitted by @twitch_username | YYYY-MM-DD
HH:MM:SS UTC`: an embed footer in embed mode, or a separate footer line for plain
messages. Colors affect embeds only. Named colors: blue, green, red, purple,
orange, yellow, gold, pink, white, black and blurple. Six-digit hex values are
accepted, e.g. `.twitchquote color #5865F2`.

Quote text is literal, up to 500 characters; it does not expand command variables.
Discord mentions are disabled, and plain-message link previews are suppressed.
Paimon needs View Channel and Send Messages in the destination, plus Embed Links
for embed mode. Only text channels in the linked Discord server are accepted.
Posting is blocked when the bridge/cog is disabled, the broadcaster changes, or
the destination becomes unavailable. A successful submission receives a Twitch
confirmation; denied/failed submissions receive an explanation. The cooldown is
only consumed after Discord accepts the post. Use `.twitchquote enabled false`
to pause submissions. `quote` and `twitchquote` are now reserved built-in names.

Quote channel/settings are stored in Red Config. Submitted quote content,
submitter username and UTC date/time persist in the configured Discord channel;
this feature does not maintain a separate local quote database or delete those
Discord posts on account unlinking.

### Editing existing timers

Discord moderators and above can edit an existing timer without replacing its
enabled/live-only settings:
```
.twitchtimer interval socials 900
.twitchtimer time socials 900
.twitchtimer message socials Follow our socials! We're playing {game}.
.twitchtimer edit socials 900 Follow our socials! We're playing {game}.
.twitchtimer edit socials 900
.twitchtimer view socials
```
`interval` (`time` alias) changes only the interval; `message` changes only the
message. `edit <name> <seconds> [message]` updates both or leaves the message alone
if omitted. Intervals remain 10-86400 seconds. Missing names and invalid values
are rejected without creating/replacing a timer. Edits use the existing scheduler
refresh: pending stale automation messages are invalidated and timer intervals
restart. `view` shows the full saved message and settings without executing any
variables. Existing enabled/liveonly/list/remove commands are unchanged.
