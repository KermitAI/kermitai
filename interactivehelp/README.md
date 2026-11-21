# InteractiveHelp for Red

Copy the `interactivehelp` folder into a Red cog path and run `[p]load interactivehelp`.
The cog replaces Red's existing prefix help formatter. Unload other help
formatter cogs before loading this one. Unloading InteractiveHelp restores
Red's formatter if InteractiveHelp still controls it.

## Member experience

- `[p]help` opens a dashboard in the current channel.
- Category buttons and the All Categories dropdown open private pages for
  the member who requested help. Pages include command details and navigation.
- `[p]help gift shop` opens a control for viewing that command's help privately.
- Staff Help silently ignores clicks from members without staff permissions.
  Eligible members see their group buttons in a private panel.

The four groups are cumulative in this order from highest to lowest:
Bot Owner, Guild Owner, Administrator, Moderator. Administrators qualify
through Discord's Administrator permission or a Red admin role. Moderators
qualify through Red's configured mod roles. Red's own command checks also
apply. Most Red commands with built-in privileges are assigned automatically.
Use explicit assignments for commands that enforce staff access through custom checks.

## Owner editing

Run these prefix commands in the server whose menu you want to edit.
Replace `[p]` with your prefix. Only Red's primary owner account can use them.

| Command | Action |
| --- | --- |
| `[p]helpmenu` | Show editor commands |
| `[p]helpmenu title <text>` | Change the title |
| `[p]helpmenu intro [text]` | Change or clear the intro |
| `[p]helpmenu colour <#RRGGBB>` | Set the accent colour |
| `[p]helpmenu category <id> <true/false> <label>` | Add or rename a category and set whether it is pinned |
| `[p]helpmenu assign <category_id> <group> <command>` | Set a command's category and minimum help access |
| `[p]helpmenu preview` | Receive a draft home-screen preview by DM |
| `[p]helpmenu export [published/draft]` | Receive editable JSON by DM |
| `[p]helpmenu import` | Attach an edited JSON file to validate and stage it |
| `[p]helpmenu publish` | Put the draft live |
| `[p]helpmenu rollback` | Restore the previous published menu |

For example, `[p]helpmenu assign economy public gift shop` places the
gift shop in Economy & Gifts. Group values are `public`, `moderator`,
`administrator`, `guild_owner`, and `bot_owner`. Help access is at least
as strict as a command's inherited help group and Red's built-in privilege.

## JSON editing

Start from an export. Category order in the file controls their display order.
Keep each category ID stable when renaming it. Use `cogs` for whole-cog
assignments, `commands` for overrides by command family, and the top-level
`overrides` object to set an individual command's `category`, `group`,
`hidden`, `description`, or `example`. Use `[p]` within examples to insert
the current prefix. The reserved category ID `other` collects unassigned
commands. Protect any imported menu file containing staff command names by
posting it in a channel visible only to trusted staff.

The draft focuses on prefix command discovery and prefix-based owner editing.

