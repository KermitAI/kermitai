# Marriage

Marriage and gifting are available by default in every server the bot joins once the cog and its global slash commands are enabled. Server admins do not need to configure anything. The cog responds to member commands and sends public wedding announcements only when a couple opts in.

After installing the cog, the bot owner runs these commands once:

```text
[p]load marriage
[p]slash enablecog Marriage
[p]slash sync
```

Use `slash sync` without a server argument to register the commands globally. Private profiles, proposal details, declines, divorces, and inventories use slash commands. The prefix gift shop command displays the catalogue and your balance in the channel. Use `/gift shop` for private browsing.

| Command | What it does |
| --- | --- |
| `/marry propose` | Send a proposal with an optional ring and note. Choose whether to allow additional marriages and whether to make the wedding public. |
| `/marry proposals`, `accept`, `decline`, `cancel` | Review and respond to proposals or withdraw your own. Proposals expire after 24 hours. |
| `/marry profile`, `edit`, `keepsake` | View a marriage card, add a couple name and bio, and feature a gift. |
| `/marry style`, `visibility`, `divorce` | Manage the marriage agreement, profile visibility, or end the marriage. |
| `/gift shop`, `buy`, `send` | Browse the catalogue, buy into inventory or directly for another member, and send gifts from your stock. |
| `/gift inventory`, `settings` | View your gifts and manage gift acceptance and DM alerts. |
| `[p]marriageset channel` | Set the channel for public wedding announcements. Omit the channel to use the acceptance channel. |

Marriages, gifts, and preferences are stored per Discord server. Purchases use Red's configured bank and currency. A ring is optional and moves to the recipient's inventory on acceptance. Wedding announcements are opt-in. Changing to a public profile or changing a marriage's style requires agreement from both spouses. The cog allows up to ten marriages per member when all existing marriages and the new proposal allow additional spouses.
