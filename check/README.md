# Check

Load with `[p]load check`, then run `[p]checkcommands` (alias: `[p]commandaudit`).
Only bot owners can run the report. Replace `[p]` with your bot prefix.

The report includes every loaded text/hybrid command, including hidden commands,
subcommands, aliases, parent requirements and cog requirements. It groups declared
privileges into Bot-Owner, Guild Owner, Administrators, Moderators and everyone.
Administrators and Moderators refer to Red's configured roles.

Red permission alternatives are shown beside each command. Permission-only checks
that cannot be mapped reliably, custom command checks and custom cog checks go into
a Needs review appendix. Standalone application commands are inventoried separately,
including guild commands for the server where the report is requested.

This is a static audit, not a guarantee of effective access. Permission overrides
are flagged, not resolved. Global checks, permission hooks, channel restrictions,
Discord application-command permissions and checks inside callbacks need separate
review. Disabled commands are marked. The cog never invokes audited commands or
predicates and stores no user data. The full report is attached as a UTF-8 text file;
the bot needs permission to send messages and attach files.

Run offline classifier tests with `python -m unittest discover -s check/tests`.
