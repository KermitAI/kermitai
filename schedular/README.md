# Schedular

Install/load the `schedular` cog in Red, then use your bot prefix with:

- `schedular create` — open an embed preview and button builder.
- `schedular delete` — list announcements with matching letter buttons; press a letter to delete that schedule immediately. Lists over 20 announcements have Previous/Next buttons. Deleted letters stay disabled to prevent mix-ups. Previously posted messages remain.
- `schedular list` — show saved schedules and their IDs.
- `schedular edit <ID>` — change settings, pause/resume, or delete.

Requires Manage Server or bot administrator permission. Only the person who opens a panel can operate it. Changes take effect when **Save** is pressed; **Exit** discards changes. **Delete** removes the saved schedule immediately, leaving previously posted messages in place.

Use **Message** and **Channel** to set the destination and content. **Interval** accepts whole minutes, hours, days or weeks, including shorthand such as `15m`, `2h`, `3d` and `1w` (minimum 15 minutes, maximum 365 days). The first post happens one interval after saving. **Daily times** switches to a daily schedule and accepts comma-separated 24-hour times, such as `09:00, 17:30`. Daily times must be at least 15 minutes apart, including across midnight. **Timezone** accepts IANA names such as `America/Toronto`; the default is UTC. Interval and daily modes are alternatives for each announcement. Create separate announcements if you need both.

The preview shows the next post in each Discord viewer's local time. Daily schedules follow their configured timezone: nonexistent spring-forward times are skipped, and repeated fall-back times post only once. Delivery runs approximately every 30 seconds. Restarting the bot sends at most one overdue post per announcement and schedules the next occurrence from the current time; missed occurrences are not replayed. Pausing stops delivery; saving a resumed schedule starts a fresh interval or selects the next daily time.

Messages are plain Discord text (up to 2,000 characters); configuration uses embeds and buttons. Mentions are displayed without pinging. The bot needs View Channel and Send Messages at the destination, and Embed Links for setup panels. Failed deliveries appear in the schedule panel and are attempted again at the next occurrence. The next occurrence is saved before sending to avoid duplicate retries; a shutdown during delivery can therefore skip that occurrence. The 15-minute minimum applies to each announcement, so multiple independent schedules can post closer together.

Schedules persist in Red Config across restarts. Panels expire after 15 minutes; reopen with `schedular edit`. No member IDs are stored. Custom message text can contain information supplied by administrators.

Tests: `python -m unittest discover -s schedular/tests -v` (no running bot required).
