# TwitchBridge — first milestone

Custom Red 3.5+ cog for owner-only Twitch broadcaster/server mapping, private device
approval, bot-token refresh and validation, EventSub chat reception, and Discord
chat logs. No dependency on Crates. Shared commands, announcements, crate
redemptions, member linking and role sync are later milestones, not included yet.

## 1. Register the Twitch application

Use https://dev.twitch.tv/console/apps and register an application with 2FA enabled.
Choose the **Public** client type: this version deliberately uses device-code
approval and does not accept or need a client secret. Select an appropriate chat
bot category. If the form requires a redirect URL, use `http://localhost:3000`;
it is not used by this device flow. Copy the Client ID.

Use a dedicated Twitch account for Paimon's bot authorization. The broadcaster
account is authorized separately to verify ownership of the channel being linked.
Only `user:read:chat` is requested in this milestone. Bot tokens are stored in Red
Config on the VPS; broadcaster tokens are discarded after identity verification.
A later milestone will request additional broadcaster permissions when needed.

## 2. Upload the cog

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
  restarting loses them. A global sender queues Discord delivery using discord.py's
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

## Local tests

```
python -B -m unittest discover -s twitchbridge/tests -v
```
