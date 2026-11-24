# InteractiveHelp for Red

Copy the `interactivehelp` folder into a Red cog path and run `[p]load interactivehelp`.
The cog replaces Red's existing prefix help formatter. Unload other help
formatter cogs before loading this one. Unloading InteractiveHelp restores
Red's formatter if InteractiveHelp still controls it.

## Member experience

- `[p]help` and `/help` open the same dashboard in the current channel.
- Use `/help command:<name>` for command or tag details. After updating and reloading the cog, enable `/help` with `[p]slash enablecog InteractiveHelp` and run `[p]slash sync`.
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

Run these prefix commands in any server. Publishing updates the help menu for all servers and DMs. Command visibility still follows the permissions where help is opened.

On first load, the cog copies an existing customized server menu if there is only one distinct saved configuration. If saved configurations differ, use `[p]helpmenu migrate` in the server you want to copy from, then publish the global draft.
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
| `[p]helpmenu migrate [published/draft]` | Copy a legacy server menu into the global draft |
| `[p]helpmenu publish` | Put the draft live across all servers |
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

The export includes a `staff` object with `bot_owner`, `guild_owner`,
`administrator`, and `moderator` command lists. The first export populates
these with discovered staff commands. After importing an edited list, the
staff pages use those assignments. Add a new command or tag by its full name,
move a name to another list, or delete the name to omit it from the staff
pages. Use `overrides.<command>.hidden` to hide an entry everywhere.
Red still enforces built-in privileges and command checks. New staff commands
can be added to an imported list by editing the JSON or with `helpmenu assign`.
The owner-only Other Commands page remains the fallback for unassigned entries.


## Embed layout

Add optional `fields` and `footer` at the top level to edit the home embed.
Each field takes `name`, `value`, and optional `inline` (defaults to false).
Use `staff_help` to customize the Staff Help landing embed, and
`staff_help.groups` for individual staff pages. Staff layouts accept
`title`, `intro`, `fields`, and `footer`. Group pages keep their command
list and append the page counter to the footer. The existing `staff`
object still controls command assignments.

Use up to 25 fields per embed. Field names can be up to 256 characters
and values up to 1,024. The combined embed limit still applies.
