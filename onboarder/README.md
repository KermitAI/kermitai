# Onboarder

A Red 3.5+ cog that collects bot setup preferences through Discord DMs.

## Setup

Install `onboarder` from this cog repository using Red's Downloader, then run:

```
[p]load onboarder
[p]onboardset channel #private-onboarding
[p]onboard <user_ID>
```

Replace `[p]` with your bot prefix. Commands are restricted to bot owners and must be run in a server. Choose a private staff text channel and configure its visibility in Discord. The bot needs View Channel, Send Messages, Embed Links and Attach Files in the results channel. The recipient must allow the bot to DM them.

`[p]onboardset show` displays the destination. `[p]onboardset cancel <user_ID>` cancels a questionnaire and removes its saved answers.

## Questionnaire

1. Logging channels: button opens a text form.
2. Streamer role: Yes opens a role name form; No continues.
3. Boost announcements: Yes opens a message form; Use default requests the App default; No disables announcements.
4. Welcome message: Yes opens a message form; Use default requests the App default; No disables the welcome message.
5. XP levelling: Yes/No.
6. Twitch/YouTube alerts: Yes opens a form for the ping role (enter `none` for no ping); No skips question 7.
7. Stream alert message: Yes opens a message form; Use default requests the App default; No leaves the message unspecified.
8. Tickets: Yes shows the notice to reach out manually for setup; No continues.
9. Autokick: Yes opens a form for required roles, time after joining, an optional notification channel, and whether all listed roles or any one role is required (accepts free-text answers). No continues.
10. Review answers and Submit, Start over, Back or Cancel.

Blank optional message fields explicitly request the App's default; the cog does not invent message templates. Role names, channel names, message templates and timeframes are collected as preferences for manual setup, not resolved or applied to another server.

## Saved progress and delivery

Progress and buttons survive cog reloads and bot restarts. Only one active questionnaire per recipient is allowed. Running `onboard` again resumes it; if its original message was deleted, a replacement is sent with saved answers. Back allows editing previous answers. A modal left open while another action changes the questionnaire cannot overwrite newer answers. Text forms expire after ten minutes; reopen the form button to continue.

The destination is saved when a questionnaire starts. Changing `onboardset channel` affects new questionnaires; run `onboard` again for an existing recipient to update theirs. A failed submission keeps the answers for retry. Successful submissions include a compact summary and the complete text attachment. User-entered mentions do not ping anyone.

Active answers are removed on submission, cancellation, or a Red user-data deletion request. Submitted messages and review/DM messages already sent to Discord remain there and must be deleted separately if needed. Questionnaires do not expire automatically. If a network or process failure occurs immediately after Discord accepts a submission but before its saved progress is cleared, retrying may produce a duplicate; the attached questionnaire reference identifies these.

## Checks

```
python -m unittest discover -s onboarder/tests -v
```

These dependency-free checks cover all Yes/No paths and complete report generation. Live Discord delivery and restart checks require a running Red bot.
