# Echo

Owner-only slash command for Red 3.5+. Paimon posts your text as an ordinary bot message. The invocation, confirmation, and errors are private to you.

After installing the cog from this repository:

1. `[p]load echo`
2. `[p]slash enable echo`
3. `[p]slash sync`

Replace `[p]` with your bot prefix. Discord may take time to display the command after syncing.

Select `/echo`, then enter one of these in its **message** field:

- `Hello everyone!` — send in the current channel.
- `#general Hello everyone!` — insert an actual channel mention using Discord's channel picker.
- `123456789012345678 Hello everyone!` — use a channel ID.
- `https://discord.com/channels/123456789012345678/234567890123456789 Hello everyone!` — use a channel link.

A destination must be first, followed by whitespace and the text. Text is limited to 2,000 characters after removing the destination. Server text channels and threads are supported, including other servers Paimon can access. Paimon needs permission to send there. Mentions in the echoed text work normally and can ping users, roles, or everyone.

Access follows Red's configured bot owners (`bot.is_owner`), not server owners or administrators. If Red has multiple configured owners, each has access. To restrict use to yourself alone, configure yourself as the sole Red owner.

Discord may still show the command in other members' command pickers; the owner check always prevents them from sending an echo. To control command visibility, restrict `/echo` to your account under Server Settings > Integrations > Paimon. Discord administrators may still see it, but cannot pass the bot-owner check.

This cog has no prefix command, so it never posts a typed command into chat. It does not save message content; echoed messages remain in Discord as normal messages.
