import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import discord
from redbot.core import Config, bank, commands

from .catalog import CATALOG

log = logging.getLogger(__name__)
ROSE = 0xB54E72
GOLD = 0xD4A853
NO_PINGS = discord.AllowedMentions.none()
PROPOSAL_SECONDS = 86400
MAX_SPOUSES = 10


def now():
    return int(datetime.now(timezone.utc).timestamp())


def pair(first, second):
    return "-".join(map(str, sorted((first, second))))


def marriages_for(state, user_id):
    return [record for record in state["marriages"].values() if user_id in record["members"]]


def eligibility(state, first, second, open_marriage):
    if pair(first, second) in state["marriages"]:
        return "You are already married to each other."
    for user_id in (first, second):
        existing = marriages_for(state, user_id)
        if len(existing) >= MAX_SPOUSES:
            return f"One of you has reached the limit of {MAX_SPOUSES} marriages."
        if existing and (not open_marriage or any(not row["open"] for row in existing)):
            return "Both this proposal and every existing marriage must allow additional spouses."
    return None


class Marriage(commands.Cog):
    """Propose, manage your marriages, and send gifts."""

    def __init__(self, bot):
        self.bot = bot
        self.purchase_lock = asyncio.Lock()
        self.config = Config.get_conf(self, identifier=638254712906341907, force_registration=True)
        self.config.register_guild(
            state={"marriages": {}, "proposals": {}, "gifts": {}, "preferences": {}},
            wedding_channel=None,
        )

    async def reply(self, ctx, content=None, *, embed=None, private=True):
        kwargs = {"allowed_mentions": NO_PINGS}
        if embed is not None:
            kwargs["embed"] = embed
        if ctx.interaction:
            kwargs["ephemeral"] = private
        await ctx.send(content, **kwargs)

    async def dm(self, member, content=None, *, embed=None):
        try:
            kwargs = {"allowed_mentions": NO_PINGS}
            if embed is not None:
                kwargs["embed"] = embed
            await member.send(content, **kwargs)
            return True
        except discord.HTTPException:
            return False

    def card(self, guild, record, *, certificate=False):
        first, second = record["members"]
        a, b = guild.get_member(first), guild.get_member(second)
        names = " & ".join(
            discord.utils.escape_markdown(member.display_name) if member else f"<@{user_id}>"
            for member, user_id in ((a, first), (b, second))
        )
        embed = discord.Embed(
            title="✦ Wedding Certificate" if certificate else "♡ Relationship Profile",
            description=f"**{names}**",
            color=GOLD if certificate else ROSE,
        )
        embed.add_field(name="Married on", value=f"<t:{record['since']}:D> · <t:{record['since']}:R>")
        embed.add_field(
            name="Marriage style",
            value="Open to additional marriages" if record["open"] else "Exclusive",
        )
        if record["ring"]:
            embed.add_field(name="Wedding ring", value=CATALOG[record["ring"]].label)
        if record.get("name"):
            embed.add_field(name="Couple name", value=record["name"], inline=False)
        if record.get("keepsake"):
            embed.add_field(name="Featured keepsake", value=CATALOG[record["keepsake"]].label)
        if record.get("bio"):
            embed.add_field(name="About us", value=record["bio"], inline=False)
        if a:
            embed.set_thumbnail(url=a.display_avatar.url)
        if b:
            embed.set_author(name=guild.name, icon_url=b.display_avatar.url)
        return embed

    @commands.hybrid_group(name="marry", fallback="help")
    @commands.guild_only()
    async def marry(self, ctx):
        """View marriage commands."""
        await self.reply(ctx, embed=discord.Embed(
            title="♡ Marriage",
            description="**propose** · **proposals** · **accept** · **decline** · **cancel**\n"
                        "**profile** · **style** · **edit** · **keepsake** · **visibility** · **divorce**\n"
                        "Use the **gift** group to browse the shop and send gifts.",
            color=ROSE,
        ))

    @marry.command()
    async def propose(
        self, ctx, member: discord.Member, open_marriage: bool = False, public: bool = False,
        ring: Optional[str] = None, *, note: str = "",
    ):
        """Propose to a member. Ring is an optional item code from the shop."""
        if member.bot or member.id == ctx.author.id:
            return await self.reply(ctx, "Choose another member who isn't a bot.")
        ring = ring.lower() if ring else None
        if ring and (ring not in CATALOG or not CATALOG[ring].ring):
            return await self.reply(ctx, "Choose a ring code from the gift shop, such as `band`.")
        if note and not ctx.interaction:
            return await self.reply(ctx, "Use `/marry propose` when including a private note.")
        if len(note) > 400:
            return await self.reply(ctx, "Keep your note to 400 characters.")
        guild = self.config.guild(ctx.guild)
        key = pair(ctx.author.id, member.id)
        async with guild.state() as state:
            error = eligibility(state, ctx.author.id, member.id, open_marriage)
            if error:
                return await self.reply(ctx, error)
            proposals = state["proposals"]
            for expired in [key for key, value in proposals.items() if value["expires"] <= now()]:
                del proposals[expired]
            if key in proposals:
                return await self.reply(ctx, "There is already a pending proposal between you.")
            if sum(ctx.author.id == row["from"] for row in proposals.values()) >= 5:
                return await self.reply(ctx, "You already have five pending proposals.")
            if ring and self.find_ring(state, ctx.author.id, ring) is None:
                return await self.reply(ctx, "Buy that ring before including it in a proposal.")
            proposal = {
                "from": ctx.author.id, "to": member.id, "open": open_marriage,
                "public": public, "ring": ring, "note": note, "expires": now() + PROPOSAL_SECONDS,
            }
            proposals[key] = proposal
        embed = self.proposal_card(proposal, ctx.guild.name)
        delivered = await self.dm(member, embed=embed)
        await self.reply(ctx, "Proposal sent." if delivered else
                         "Proposal saved. Ask the recipient to open `marry proposals` in this server.")

    def proposal_card(self, proposal, guild_name):
        embed = discord.Embed(
            title="💍 Marriage Proposal", color=ROSE,
            description=f"From <@{proposal['from']}> in **{discord.utils.escape_markdown(guild_name)}**",
        )
        embed.add_field(name="Marriage style", value=(
            "Open to additional marriages" if proposal["open"] else "Exclusive"
        ))
        embed.add_field(name="Wedding visibility", value="Public" if proposal["public"] else "Private")
        if proposal["ring"]:
            embed.add_field(name="Ring", value=CATALOG[proposal["ring"]].label)
        if proposal["note"]:
            embed.add_field(name="Note", value=proposal["note"], inline=False)
        embed.add_field(name="Expires", value=f"<t:{proposal['expires']}:R>")
        embed.set_footer(text="Use marry accept or marry decline with the sender in this server.")
        return embed

    @marry.command()
    async def proposals(self, ctx, member: Optional[discord.Member] = None):
        """List incoming proposals or read a specific proposal."""
        if not ctx.interaction:
            return await self.reply(ctx, "Use the slash command `/marry proposals` to read proposals privately.")
        state = await self.config.guild(ctx.guild).state()
        incoming = [
            row for row in state["proposals"].values()
            if row["to"] == ctx.author.id and row["expires"] > now()
        ]
        if member:
            proposal = next((row for row in incoming if row["from"] == member.id), None)
            if proposal:
                return await self.reply(ctx, embed=self.proposal_card(proposal, ctx.guild.name))
        elif incoming:
            senders = [f"<@{row['from']}>" for row in incoming[:20]]
            return await self.reply(ctx, "Pending proposals from " + ", ".join(senders) +
                                    ". Select a sender to see their proposal.")
        await self.reply(ctx, "You have no matching proposals.")

    @staticmethod
    def find_ring(state, owner_id, ring):
        return next((key for key, row in state["gifts"].items()
                     if row["owner"] == owner_id and row["item"] == ring and row["sender"] is None), None)

    @marry.command()
    async def accept(self, ctx, member: discord.Member):
        """Accept a proposal from this member."""
        guild = self.config.guild(ctx.guild)
        key = pair(ctx.author.id, member.id)
        async with guild.state() as state:
            proposal = state["proposals"].get(key)
            if not proposal or proposal["to"] != ctx.author.id or proposal["expires"] <= now():
                return await self.reply(ctx, "There is no pending proposal from that member.")
            error = eligibility(state, ctx.author.id, member.id, proposal["open"])
            if error:
                return await self.reply(ctx, error)
            ring = proposal["ring"]
            if ring:
                gift_id = self.find_ring(state, member.id, ring)
                if gift_id is None:
                    return await self.reply(ctx, "Ask the proposer to restock the ring or send a new proposal.")
                state["gifts"][gift_id].update(owner=ctx.author.id, sender=member.id, note="")
            record = {
                "members": [member.id, ctx.author.id], "open": proposal["open"],
                "public": proposal["public"], "since": now(), "ring": ring,
                "name": "", "bio": "", "style_request": None,
            }
            state["marriages"][key] = record
            del state["proposals"][key]
        certificate = self.card(ctx.guild, record, certificate=True)
        if record["public"]:
            destination = ctx.guild.get_channel(await guild.wedding_channel()) or ctx.channel
            try:
                await destination.send(embed=certificate, allowed_mentions=NO_PINGS)
            except discord.HTTPException:
                await self.reply(ctx, "Marriage saved. The wedding announcement could not be posted.")
            else:
                await self.reply(ctx, "Marriage accepted.")
        else:
            await self.dm(member, embed=certificate)
            if ctx.interaction:
                await self.reply(ctx, embed=certificate)
            else:
                await self.reply(ctx, "Marriage saved. Open `/marry profile` to view it privately.")

    async def remove_proposal(self, ctx, member, *, incoming):
        async with self.config.guild(ctx.guild).state() as state:
            key = pair(ctx.author.id, member.id)
            proposal = state["proposals"].get(key)
            role = "to" if incoming else "from"
            if not proposal or proposal[role] != ctx.author.id or proposal["expires"] <= now():
                return await self.reply(ctx, "There is no matching pending proposal.")
            del state["proposals"][key]
        await self.reply(ctx, "Proposal declined." if incoming else "Proposal withdrawn.")

    @marry.command()
    async def decline(self, ctx, member: discord.Member):
        """Decline an incoming proposal privately."""
        if not ctx.interaction:
            return await self.reply(ctx, "Use `/marry decline` for a private reply.")
        await self.remove_proposal(ctx, member, incoming=True)

    @marry.command()
    async def cancel(self, ctx, member: discord.Member):
        """Withdraw a proposal you sent."""
        await self.remove_proposal(ctx, member, incoming=False)

    @marry.command()
    async def profile(self, ctx, member: Optional[discord.Member] = None,
                      spouse: Optional[discord.Member] = None):
        """View your marriages or another member's public marriages."""
        member = member or ctx.author
        state = await self.config.guild(ctx.guild).state()
        records = [
            row for row in marriages_for(state, member.id)
            if (row["public"] or (ctx.interaction and ctx.author.id in row["members"]))
            and (spouse is None or (spouse.id != member.id and spouse.id in row["members"]))
        ]
        if len(records) == 1:
            return await self.reply(ctx, embed=self.card(ctx.guild, records[0]))
        if records:
            names = [f"<@{next(uid for uid in row['members'] if uid != member.id)}>" for row in records]
            return await self.reply(ctx, "Choose a spouse to view their card.\n" + "\n".join(names))
        await self.reply(ctx, "No visible marriage matches. Use the slash command to see your private marriages.")

    @marry.command()
    async def style(self, ctx, spouse: discord.Member, open_marriage: bool):
        """Request a style change. Your spouse confirms by requesting the same style."""
        async with self.config.guild(ctx.guild).state() as state:
            record = state["marriages"].get(pair(ctx.author.id, spouse.id))
            if not record:
                return await self.reply(ctx, "You do not have a marriage with that member.")
            if record["open"] == open_marriage:
                record["style_request"] = None
                message = "That is your current style. Any pending change was cleared."
            elif not open_marriage and any(
                len(marriages_for(state, uid)) > 1 for uid in record["members"]
            ):
                return await self.reply(ctx, "Both spouses must have only this marriage to make it exclusive.")
            elif record["style_request"] == spouse.id:
                record.update(open=open_marriage, style_request=None)
                message = "Marriage style updated."
            else:
                record["style_request"] = ctx.author.id
                message = "Request saved. Your spouse can run the same command to confirm."
        await self.reply(ctx, message)

    @marry.command()
    async def edit(self, ctx, spouse: discord.Member, name: str, *, bio: str = ""):
        """Set a shared couple name and bio."""
        if len(name) > 60 or len(bio) > 350:
            return await self.reply(ctx, "Use up to 60 characters for the name and 350 for the bio.")
        async with self.config.guild(ctx.guild).state() as state:
            record = state["marriages"].get(pair(ctx.author.id, spouse.id))
            if not record:
                return await self.reply(ctx, "You do not have a marriage with that member.")
            record.update(name=name, bio=bio)
        await self.reply(ctx, "Relationship profile updated.")

    @marry.command()
    async def keepsake(self, ctx, spouse: discord.Member, item: Optional[str] = None):
        """Feature a gift you received from your spouse. Omit the item to clear it."""
        code = item.lower() if item else None
        async with self.config.guild(ctx.guild).state() as state:
            record = state["marriages"].get(pair(ctx.author.id, spouse.id))
            if not record:
                return await self.reply(ctx, "You do not have a marriage with that member.")
            if code and not any(
                row["item"] == code and row["owner"] == ctx.author.id and row["sender"] == spouse.id
                for row in state["gifts"].values()
            ):
                return await self.reply(ctx, "Choose an item code for a gift you received from that spouse.")
            record["keepsake"] = code
        await self.reply(ctx, "Featured keepsake updated.")

    @marry.command()
    async def visibility(self, ctx, spouse: discord.Member, public: bool):
        """Make a profile private or ask your spouse to make it public."""
        async with self.config.guild(ctx.guild).state() as state:
            record = state["marriages"].get(pair(ctx.author.id, spouse.id))
            if not record:
                return await self.reply(ctx, "You do not have a marriage with that member.")
            if not public or record.get("public_request") == spouse.id:
                record.update(public=public, public_request=None)
                message = "Profile visibility updated."
            elif record["public"]:
                message = "Your profile is already public."
            else:
                record["public_request"] = ctx.author.id
                message = "Request saved. Your spouse can run the same command to confirm."
        await self.reply(ctx, message)

    @marry.command()
    async def divorce(self, ctx, spouse: discord.Member, confirm: bool = False):
        """End a marriage privately. Set confirm to true to complete it."""
        if not ctx.interaction:
            return await self.reply(ctx, "Use `/marry divorce` for a private reply.")
        if not confirm:
            return await self.reply(ctx, "Run this again with **confirm** set to **True** to end this marriage.")
        async with self.config.guild(ctx.guild).state() as state:
            if state["marriages"].pop(pair(ctx.author.id, spouse.id), None) is None:
                return await self.reply(ctx, "You do not have a marriage with that member.")
        await self.dm(spouse, f"Your marriage with {ctx.author.display_name} in {ctx.guild.name} has ended.")
        await self.reply(ctx, "Marriage ended. Your gifts remain in your inventories.")

    @commands.hybrid_group(name="gift", fallback="help")
    @commands.guild_only()
    async def gift(self, ctx):
        """View gift shop and inventory commands."""
        await self.reply(ctx, embed=discord.Embed(
            title="🎁 Gifts", color=GOLD,
            description="**shop** · **buy** · **send** · **inventory** · **settings**",
        ))

    @gift.command()
    async def shop(self, ctx):
        """Browse gifts and see your current bank balance."""
        currency = await bank.get_currency_name(ctx.guild)
        balance = await bank.get_balance(ctx.author)
        embed = discord.Embed(title="✦ Gift Shop", color=GOLD)
        embed.description = f"Your balance is **{balance:,} {currency}**."
        for code, item in CATALOG.items():
            embed.add_field(
                name=f"{item.label} · {item.price:,} {currency}",
                value=f"{item.description}\nItem code `{code}`",
                inline=False,
            )
        await self.reply(ctx, embed=embed)

    @gift.command()
    async def buy(self, ctx, item: str, member: Optional[discord.Member] = None, *, note: str = ""):
        """Buy for later or buy and send immediately by selecting a recipient."""
        async with self.purchase_lock:
            await self.transfer(ctx, item, member, note, purchase=True)

    @gift.command()
    async def send(self, ctx, item: str, member: discord.Member, *, note: str = ""):
        """Send a gift from your inventory to another member."""
        await self.transfer(ctx, item, member, note, purchase=False)

    async def transfer(self, ctx, code, member, note, *, purchase):
        code = code.lower()
        item = CATALOG.get(code)
        if item is None:
            return await self.reply(ctx, "Choose an item code from `gift shop`.")
        if member and (member.bot or member.id == ctx.author.id):
            return await self.reply(ctx, "Choose another member who isn't a bot.")
        if len(note) > 400 or (note and not member):
            return await self.reply(ctx, "Gift notes need a recipient and can be up to 400 characters.")
        if note and not ctx.interaction:
            return await self.reply(ctx, "Use the slash command when including a gift note.")
        charged = False
        guild = self.config.guild(ctx.guild)
        try:
            async with guild.state() as state:
                preferences = state["preferences"].get(str(member.id), {}) if member else {}
                if not preferences.get("accept_gifts", True):
                    return await self.reply(ctx, "That member has turned off incoming gifts.")
                gifts = state["gifts"]
                if purchase:
                    try:
                        await bank.withdraw_credits(ctx.author, item.price)
                    except ValueError:
                        return await self.reply(ctx, "You do not have enough currency for that gift.")
                    charged = True
                    gift_id = uuid4().hex
                else:
                    gift_id = next((key for key, row in gifts.items()
                                    if row["owner"] == ctx.author.id and row["item"] == code
                                    and row["sender"] is None), None)
                    if gift_id is None:
                        return await self.reply(ctx, "You do not own an unsent copy of that gift.")
                gifts[gift_id] = {
                    "item": code, "owner": member.id if member else ctx.author.id,
                    "sender": ctx.author.id if member else None, "note": note, "date": now(),
                }
        except Exception:
            if charged:
                try:
                    await bank.deposit_credits(ctx.author, item.price)
                except Exception:
                    log.exception("Gift purchase refund failed for member %s", ctx.author.id)
            raise
        if member:
            if preferences.get("gift_alerts", True):
                embed = discord.Embed(
                    title=f"🎁 {item.name}", color=GOLD,
                    description=f"From <@{ctx.author.id}> in **{discord.utils.escape_markdown(ctx.guild.name)}**",
                )
                if note:
                    embed.add_field(name="Note", value=note, inline=False)
                await self.dm(member, embed=embed)
            await self.reply(ctx, f"Sent **{item.label}** to {member.mention}.")
        else:
            await self.reply(ctx, f"Added **{item.label}** to your inventory.")

    @gift.command()
    async def inventory(self, ctx, page: int = 1):
        """View your stock and received gifts privately."""
        if not ctx.interaction:
            return await self.reply(ctx, "Use `/gift inventory` to view your gifts privately.")
        state = await self.config.guild(ctx.guild).state()
        stock = {}
        received = []
        for gift in state["gifts"].values():
            if gift["owner"] != ctx.author.id:
                continue
            item = CATALOG[gift["item"]]
            if gift["sender"] is None:
                stock[item.label] = stock.get(item.label, 0) + 1
            else:
                received.append(gift)
        received.sort(key=lambda row: row["date"], reverse=True)
        pages = max(1, (len(received) + 7) // 8)
        if not 1 <= page <= pages:
            return await self.reply(ctx, f"Choose a page from 1 to {pages}.")
        embed = discord.Embed(title="🎁 Your Gift Inventory", color=GOLD)
        embed.add_field(name="Ready to send", inline=False, value=(
            "\n".join(f"{name} × {count}" for name, count in stock.items()) or "No unsent gifts yet."
        ))
        for gift in received[(page - 1) * 8:page * 8]:
            sender = "Former sender" if gift["sender"] == 0 else f"<@{gift['sender']}>"
            embed.add_field(
                name=CATALOG[gift["item"]].label,
                value=f"From {sender} · <t:{gift['date']}:D>" +
                      (f"\n{gift['note']}" if gift["note"] else ""),
                inline=False,
            )
        embed.set_footer(text=f"Received gifts · Page {page}/{pages}")
        await self.reply(ctx, embed=embed)

    @gift.command()
    async def settings(self, ctx, accept_gifts: bool, gift_alerts: bool = True):
        """Choose whether to accept gifts and get gift DMs."""
        async with self.config.guild(ctx.guild).state() as state:
            state["preferences"][str(ctx.author.id)] = {
                "accept_gifts": accept_gifts, "gift_alerts": gift_alerts,
            }
        await self.reply(ctx, "Your gift preferences were updated.")

    @commands.group(name="marriageset")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def marriageset(self, ctx):
        """Configure marriage announcements."""

    @marriageset.command()
    async def channel(self, ctx, channel: Optional[discord.TextChannel] = None):
        """Set the public wedding channel. Omit to use the command channel."""
        await self.config.guild(ctx.guild).wedding_channel.set(channel.id if channel else None)
        await self.reply(ctx, f"Public weddings will appear in {channel.mention}." if channel else
                         "Public weddings will appear in the channel where the proposal is accepted.")

    async def red_delete_data_for_user(self, *, requester, user_id):
        for guild_id in await self.config.all_guilds():
            async with self.config.guild_from_id(guild_id).state() as state:
                state["preferences"].pop(str(user_id), None)
                for key in [
                    key for key, row in state["marriages"].items() if user_id in row["members"]
                ]:
                    del state["marriages"][key]
                for key in [
                    key for key, row in state["proposals"].items()
                    if user_id in (row["from"], row["to"])
                ]:
                    del state["proposals"][key]
                for key, gift in list(state["gifts"].items()):
                    if gift["owner"] == user_id:
                        del state["gifts"][key]
                    elif gift["sender"] == user_id:
                        gift.update(sender=0, note="")
