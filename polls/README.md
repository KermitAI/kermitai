# Polls

Load with `[p]load polls`, then run `[p]pollcreate` (administrator or Manage Server permission).

- **Question** sets the main prompt; **Answer** appends a letter-labelled voting option. Remove last answer corrects an unwanted option. Supports 2–25 options (Discord allows 25 buttons per message).
- Configure description, image URL, duration (seconds/minutes/hours/days/weeks, up to 365 days), poll channel, results channel, votes per member, and allowed team roles. Empty roles allows everyone. Defaults: 1 day, 1 vote, current channel for both destinations.
- Only the creator can operate the builder. Create publishes; Exit cancels. Builders expire after 15 minutes and are not restored after restart.
- Votes toggle on/off, show live totals, and allow at most one vote per option per member. The vote limit applies across options. Role eligibility is checked on each click.
- Active polls and votes survive restarts. Polls close within roughly five seconds of their deadline while the bot is online; overdue polls close after restart. Closing removes voting buttons, displays the winner/margin (or tie/no votes) and each option's total, and posts a results copy.
- Both channels require View Channel, Send Messages and Embed Links for the bot. The creator must be able to view and send in both channels.
- Failed message edits or results delivery retry every five seconds. Restore missing permissions/channels to allow delivery. A crash between sending results and saving delivery completion can produce a duplicate results copy.
- Member IDs and votes are removed after successful results delivery. Data deletion requests remove that member's active votes. Discord messages containing published aggregate results remain.

Checks: `python -m unittest discover -s polls/tests -v`. These exercise duration parsing, totals/results, voting toggles, roles, deadlines and concurrent vote limits without a running bot. Live Discord testing is still required for UI and permissions.

## Close or delete a poll

- `[p]pollclose <message ID or message link>` ends voting immediately, removes voting buttons, and posts the final results in the configured channel.
- `[p]polldelete <message ID or message link>` removes the poll message, saved votes, and any tracked results copy. It does not post new results.

Both require administrator or Manage Server permission and work only on polls from the current server. Failed updates/deletions retry automatically; voting stays stopped. Completed polls finalized after this update retain only their message locations so they can be deleted too. Polls already completed before this update are no longer tracked and must be deleted manually in Discord.
