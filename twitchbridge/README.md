# TwitchBridge

Custom Red 3.5+ cog for owner-only Twitch broadcaster/server mapping, private device
approval, bot-token refresh and validation, EventSub chat reception, and Discord
chat logs, standalone shared custom commands, and announcements. No dependency on
Tags or Crates. Crate redemptions, member linking and role sync are later milestones.

## 1. Register the Twitch application

Use https://dev.twitch.tv/console/apps and register an application with 2FA enabled.
Choose the **Public** client type: this version deliberately uses device-code
approval and does not accept or need a client secret. Select an appropriate chat
bot category. If the form requires a redirect URL, use `http://localhost:3000`;
it is not used by this device flow. Copy the Client ID.

Use a dedicated Twitch account for Paimon's bot authorization. The broadcaster
account is authorized separately to verify ownership of the channel being linked.
The bot requests `user:read:chat` and `user:write:chat`; broadcaster identity
approval requests only `user:read:chat`. Bot tokens are stored in Red
Config on the VPS; broadcaster tokens are discarded after identity verification.
A later milestone will request additional broadcaster permissions when needed.

## Updating through your connected GitHub repository

Commit and push the updated `twitchbridge` folder to your existing repository.
In Discord, replace `[p]` with your normal prefix (for example `.`):

```
[p]cog update twitchbridge
[p]reload twitchbridge
[p]twitchset authbot
```

Approve the private link as Paimon's Twitch bot account to grant chat-writing
permission. Existing broadcaster and log-channel settings are preserved; no need
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
- `[p]twitchset disconnect` removes the current server mapping and pending approval.
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
  receive loop. Twitch sends are serialized at least 1.6 seconds apart globally.
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

These are ordinary plain-text chat messages, not Twitch's colored `/announce`
banners. They require bot-owner access. The maximum is 500 characters for all
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
