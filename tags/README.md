# Tags with slash commands

A copy of Seina-Cogs Tags with the original prefix commands and matching slash
commands. Original source and MIT attribution are in UPSTREAM.md and LICENSE.

Examples:
- `/invoketag tag_name:welcome args:some arguments` (tag and alias autocomplete)
- `/tags`
- `/tag add tag_name:welcome tagscript:Hello {author}!`
- `/tag edit`, `/tag alias`, `/tag list`, `/tag info`, `/tag backup`
- `/tag global ...` and `/tagsettings ...` (bot owner only)

All original command checks and converters remain in use. Prefix aliases are
retained; slash commands use canonical names. Tags are selected through
`/invoketag`; individual stored tags do not become separate slash commands.

## Switch from Seina-Cogs on the same bot

Replace `[p]` with your bot prefix and `<oldrepo>` / `<yourrepo>` with the
Downloader repository names shown by `[p]repo list`.

1. Back up Red's bot data. Optionally save `[p]tag backup` in each server and
   `[p]tag global backup` for global tags.
2. Publish this repository containing the tags folder to your GitHub account.
   Add it to Red if needed: `[p]repo add <yourrepo> <your GitHub repository URL>`.
3. `[p]unload tags`
4. `[p]cog uninstall <oldrepo> tags`
5. `[p]cog install <yourrepo> tags`
6. `[p]load tags`
7. `[p]slash enablecog Tags`
8. `[p]slash sync`
9. Test one existing tag using both its prefix and `/invoketag`.

This copy intentionally keeps class name `Tags`, Config identifier
`567234895692346562369`, and the original data schema. On the same bot instance,
existing server/global tags, aliases, authors, usage counts and settings are
reused automatically. Do not clear the Tags configuration or delete its data
folder. Both implementations cannot be loaded together. Keep the Seina repo if
you use other cogs from it.

For a different bot instance, use the existing backup/restore commands. Upload
the saved JSON file in Discord and pass that message's link to `/tag restore`
or `/tag global restore`. These restore operations can replace existing data;
back up the destination first. Settings/custom blocks need a full bot-data
migration if moving between instances.

## Slash behavior

Slash inputs have no user message. Delete, react-to-user-message and reply-to-
invocation actions are skipped for slash invocations; prefix behavior remains.
Bot-output reactions, TagScript, embeds and command actions retain the shared
processor. A redirected or action-only invocation receives a completion reply.
Discord text options have a 6,000-character limit; use Pastebin or prefix
commands for larger scripts (the cog supports up to 10,000 characters).

Red's enabling/syncing guide:
https://docs.discord.red/en/stable/guide_slash_and_interactions.html