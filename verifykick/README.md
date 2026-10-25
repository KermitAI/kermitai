# VerifyKick — Red cog

Automatically kicks human members who have none of the configured verification roles after a configurable wait from 1 minute to 365 days.
Settings are separate for each server and survive restarts. Enforcement starts disabled.

## Install

Requires Red 3.5+ with the Server Members Intent enabled in the Discord Developer
Portal and in the bot. Give the bot Kick Members and position its highest role
above the members it needs to kick. Optional notifications require View Channel
and Send Messages in the selected channel.

This folder is the `verifykick` cog package. Its layout is:

```text
verifykick/
├── tests/
├── README.md
├── __init__.py
├── info.json
├── policy.py
└── verifykick.py
```

## Configure

Server administrators can use:

```text
[p]verifykickset roles @Member @Verified
[p]verifykickset time 5d
[p]verifykickset channel #mod-log
[p]verifykickset settings
[p]verifykickset enable
[p]verifykickset preview
```

- `verifykickset time 3m`, `time 1h`, and `time 5d` set minutes, hours, and days.
  Use a positive whole number and one unit (`m`, `h`, or `d`, case-insensitive).
  The default is 7 days. The old `verifykickset days 7` command still works.
  Existing day-based settings and deadlines are preserved when updating.
- `verifykickset channel` without a channel turns notifications off.
- `verifykickset disable` stops enforcement.
- Changing the role or waiting period disables enforcement. Enable again to start a fresh grace period.
- Repeating `enable` while already enabled does not reset deadlines.

## Behavior

Checks run every 30 seconds, so kicks can occur up to approximately 30 seconds
after the deadline (longer during outages or Discord rate limits). The countdown
starts at the later of the server join date and the most recent enable time.
Existing members therefore get a full grace period. Deadlines survive bot restarts;
overdue members can be kicked when the bot comes back online.

Bots, the server owner, administrators, and members at or above the bot's highest
role are skipped. Missing join dates are skipped. If any configured role is deleted, kicks pause until the accepted roles are configured again. Roles are refreshed before each kick. Like all
Discord moderation actions, a role update racing the kick cannot be made atomic.

Having ANY accepted role prevents a kick. Members are eligible only if they have
NONE of the accepted roles when their deadline passes. Losing all accepted roles
after the deadline makes them eligible at the next check.

`verifykickset roles @Member @Verified` replaces the entire accepted list.
The old `verifykickset role` command remains an alias and accepts multiple roles.
Existing single-role settings continue working without resetting deadlines.
Changing the list disables enforcement; run `verifykickset enable` afterward.
Kicks include an audit-log reason. Optional channel notices name the member and
ID, required role, and waiting period without pinging anyone. Notices are sent
only after successful kicks; failed kicks or notices are logged to Red's logs.
Failed notices are not retried. Members are not sent DMs.

`preview` counts currently eligible members without kicking them; it does not pause
the automatic checker. No member-specific data is stored.
