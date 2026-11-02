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


## Repository cleanup report

After updating the cog, run `[p]reload check`, then `[p]checkrepos`
(alias: `[p]repoaudit`). Downloader must be loaded and initialized.
Both audit commands are bot-owner only.

The attached `repository-audit.txt` groups installed cogs by source repo and shows:

- Repos with no Downloader-tracked cogs or shared libraries: cleanup candidates.
- Installed cogs that are unloaded, with their reason explicitly unknown.
- Loaded cogs and their registered text commands and application command entries.
- Commands hidden or globally disabled on themselves or their parent commands.
- Pinned cogs and installed cogs missing from the local repo's available inventory.
- Installed modules whose original repo is no longer added.
- Loaded extensions outside the Downloader inventory, including core/manual cogs.

An unloaded cog is not evidence of failure. The audit does not try loading it or
recover historical load errors. To diagnose one, deliberately load that individual
cog and inspect its error/logs. Loaded cogs with zero commands may provide listeners,
background tasks, buttons, or shared services and should not be removed on that basis.
Guild-specific disabling and effective permission/help filtering need separate review.

No repos are refreshed or deleted, no cogs are loaded/unloaded, and no command
callbacks or check predicates run. Empty repos are suggestions for manual review;
manually installed cogs and dependencies may still rely on their source. The report
does not collect usage history or verify external services. Application entries
cover global commands and guild commands for the server where you run the audit.
Downloader internals differ across Red versions; the adapter supports the older
cog-based API and the extracted core API, with offline tests for both.
