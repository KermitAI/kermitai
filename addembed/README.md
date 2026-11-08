# AddEmbed

Load with `[p]load addembed` after installing this cog from the repository.

```
.addembed #channel "Title" "Starting description" label: Add input style: success emoji: 📝
.addembed #channel "Title" "Starting description" label: Add input style: primary emoji: 📝 roles: @Members @Helpers
```

Replace the dot with your bot prefix. Quote the title and description. Option values can contain spaces. Use role mentions or IDs for the whitelist; holding any listed role permits contributions. Trailing role mentions after the emoji are also accepted.

Creation uses Red's standard moderator permission check: configured moderator and admin roles, Discord administrators, the server owner and bot owners qualify. Red's permissions cog can grant or deny access, and its canrun check sees this requirement. Configure moderator roles with `[p]set roles addmodrole @Moderators`. Role names and Discord role position do not determine Red's moderator status. The creator must be able to view and send in the target channel.

Styles: primary/blurple, secondary/grey/gray, success/green, danger/red. Emoji: Unicode, a Discord custom emoji, or `none`. Labels are limited to 80 characters.

Each click opens a private text-entry modal. Submitting appends two newlines followed by `<@member_id> - text`. With no whitelist, all members who can access the message may contribute. Restrictions are checked again on submission. Members can submit multiple times.

Buttons are restored after bot restarts/reloads, following the [discord.py persistent view API](https://discordpy.readthedocs.io/en/stable/interactions/api.html#discord.ui.View.is_persistent). Concurrent submissions are serialized per message. Contributions are stored in the Discord message itself. Discord's 4,096-character description limit is enforced; entries that do not fit are rejected with a private explanation.

The bot needs View Channel, Send Messages, Embed Links and Read Message History in the destination. Staff can remove an embed by deleting its Discord message. Contributions contain member mentions, but arbitrary input does not generate mention notifications.
