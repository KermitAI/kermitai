# VerifyKick — Red cog

Automatically kicks human members who lack a configured role after 1–365 days.
Settings are separate for each server and survive restarts. Enforcement starts disabled.

## Install

Requires Red 3.5+ with the Server Members Intent enabled in the Discord Developer
Portal and in the bot. Give the bot Kick Members and position its highest role
above the members it needs to kick. Optional notifications require View Channel
and Send Messages in the selected channel.

## Configure

Server administrators can use:

```text
[p]verifykickset role @Member
[p]verifykickset days 7
[p]verifykickset channel #mod-log
[p]verifykickset settings
[p]verifykickset enable
[p]verifykickset preview
```

- `verifykickset channel` without a channel turns notifications off.
- `verifykickset disable` stops enforcement.
- Changing the role or days disables enforcement. Enable again to start a fresh grace period.
- Repeating `enable` while already enabled does not reset deadlines.

## Behavior

Checks run every 15 minutes, so kicks can occur up to approximately 15 minutes
after the deadline (longer during outages or Discord rate limits). The countdown
starts at the later of the server join date and the most recent enable time.
Existing members therefore get a full grace period. Deadlines survive bot restarts;
overdue members can be kicked when the bot comes back online.

Bots, the server owner, administrators, and members at or above the bot's highest
role are skipped. Missing join dates are skipped. A deleted required role suspends
kicks until configured again. Roles are refreshed before each kick. Like all
Discord moderation actions, a role update racing the kick cannot be made atomic.

The member must currently have the required role: losing it after the deadline
makes them eligible at the next check. Other roles do not satisfy the requirement.
Kicks include an audit-log reason. Optional channel notices name the member and
ID, required role, and waiting period without pinging anyone. Notices are sent
only after successful kicks; failed kicks or notices are logged to Red's logs.
Failed notices are not retried. Members are not sent DMs.

`preview` counts currently eligible members without kicking them; it does not pause
the automatic checker. No member-specific data is stored.
