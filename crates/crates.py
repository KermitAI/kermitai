import asyncio
import re
import time
from typing import Optional

import discord
from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import pagify

from .policy import award, choose_reward, positive_weight, ranking


class Crates(commands.Cog):
    """Configure crate tiers and collect their random rewards."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=981376420015, force_registration=True)
        self.config.register_guild(tiers={}, cooldown=0, enabled=True)
        self.config.register_member(inventory={}, pulls=0, value=0, last_pull=0)
        self.locks = {}

    def lock(self, guild_id):
        return self.locks.setdefault(guild_id, asyncio.Lock())

    async def red_delete_data_for_user(self, *, requester, user_id):
        for guild_id in await self.config.all_members():
            async with self.lock(guild_id):
                await self.config.member_from_ids(guild_id, user_id).clear()

    async def send_pages(self, ctx, text):
        for page in pagify(text, page_length=1800):
            await ctx.send(page, allowed_mentions=discord.AllowedMentions.none())

    @commands.guild_only()
    @commands.group(name="crate", invoke_without_command=True)
    async def crate(self, ctx):
        """Pull crates, view collections, and see the server leaderboard."""
        await ctx.send_help()

    @crate.command(name="pull")
    async def pull(self, ctx):
        """Open a random crate and add its item to your inventory."""
        async with self.lock(ctx.guild.id):
            settings = await self.config.guild(ctx.guild).all()
            if not settings["enabled"]:
                await ctx.send("Crate pulls are disabled in this server.")
                return
            group = self.config.member(ctx.author)
            data = await group.all()
            now = time.time()
            remaining = data["last_pull"] + settings["cooldown"] - now
            if remaining > 0:
                await ctx.send(f"Your next pull is available <t:{int(now + remaining) + 1}:R>.")
                return
            try:
                tier, name, value = choose_reward(settings["tiers"])
            except ValueError:
                await ctx.send(
                    f"No crates are ready yet. An admin must add tiers and items with `{ctx.clean_prefix}crateset`."
                )
                return
            award(data, name, value, now)
            await group.set(data)
        # Persist the award before announcing it; a failed send cannot lose a reward.
        await ctx.send(
            f"📦 **{discord.utils.escape_markdown(ctx.author.display_name)}** opened a "
            f"**{tier}** crate and pulled **{discord.utils.escape_markdown(name)}**! "
            f"(Value: {value:,})",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @crate.command(name="inventory", aliases=["inv"])
    async def inventory(self, ctx, member: Optional[discord.Member] = None):
        """Show your inventory, or another server member's inventory."""
        member = member or ctx.author
        data = await self.config.member(member).all()
        title = discord.utils.escape_markdown(member.display_name)
        if not data["inventory"]:
            await ctx.send(f"{title} has no items yet.", allowed_mentions=discord.AllowedMentions.none())
            return
        lines = [f"**{title}'s inventory**"]
        lines.extend(f"{discord.utils.escape_markdown(name)} × {qty:,}"
                     for name, qty in sorted(data["inventory"].items()))
        lines.append(f"Total pulls: {data['pulls']:,} | Collected value: {data['value']:,}")
        await self.send_pages(ctx, "\n".join(lines))

    @crate.command(name="leaderboard", aliases=["lb"])
    async def leaderboard(self, ctx):
        """Rank current server members by collected value, then total pulls."""
        members = await self.config.all_members(ctx.guild)
        rows = ranking(members, {member.id for member in ctx.guild.members})
        if not rows:
            await ctx.send("Nobody in this server has pulled a crate yet.")
            return
        lines = ["**Crates leaderboard — collected value**"]
        for position, (uid, data) in enumerate(rows, 1):
            name = discord.utils.escape_markdown(ctx.guild.get_member(uid).display_name)
            lines.append(f"{position}. {name} — {data['value']:,} value | {data['pulls']:,} pulls")
        await self.send_pages(ctx, "\n".join(lines))

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.group(name="crateset", invoke_without_command=True)
    async def crateset(self, ctx):
        """Configure this server's crates. Starts with no tiers or items."""
        await ctx.send_help()

    @crateset.command(name="show")
    async def show(self, ctx):
        """Show settings, items, and effective tier/item chances."""
        settings = await self.config.guild(ctx.guild).all()
        tiers = settings["tiers"]
        total = sum(t["weight"] for t in tiers.values() if t["items"])
        lines = [f"Pulls enabled: {settings['enabled']} | Cooldown: {settings['cooldown']:,} seconds"]
        for key, tier in sorted(tiers.items()):
            chance = tier["weight"] / total * 100 if total and tier["items"] else 0
            lines.append(f"**{key}** — weight {tier['weight']:g}, chance {chance:.2f}%")
            item_total = sum(i["weight"] for i in tier["items"].values())
            for name, item in sorted(tier["items"].items()):
                lines.append(f"  {discord.utils.escape_markdown(name)} — value {item['value']:,}, "
                             f"weight {item['weight']:g}, {item['weight'] / item_total * 100:.2f}% within tier")
            if not tier["items"]:
                lines.append("  No items; excluded from pulls.")
        if not tiers:
            lines.append("No tiers configured. Add a tier, then add its items.")
        await self.send_pages(ctx, "\n".join(lines))

    @crateset.command(name="tier")
    async def set_tier(self, ctx, tier: str, weight: float):
        """Add/update a tier: crateset tier <tier> <weight>.

        Tier names use 1–32 letters, digits, or hyphens. Weights are relative:
        weights 3 and 1 give 75% and 25% chances among populated tiers.
        """
        tier = tier.lower()
        if not re.fullmatch(r"[a-z0-9-]{1,32}", tier) or not positive_weight(weight):
            await ctx.send("Use a tier name of 1–32 letters/digits/hyphens and a finite weight greater than 0, up to 1,000,000.")
            return
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).tiers() as tiers:
                if tier not in tiers and len(tiers) >= 50:
                    await ctx.send("A server can have up to 50 tiers.")
                    return
                tiers.setdefault(tier, {"items": {}})["weight"] = weight
        await ctx.send(f"Tier `{tier}` saved with weight {weight:g}.")

    @crateset.command(name="item")
    async def set_item(self, ctx, tier: str, weight: float, value: int, *, name: str):
        """Add/update an item: crateset item <tier> <weight> <value> <item name>.

        One item is awarded per pull. Item weights are relative within their tier.
        Value is used for leaderboard points; it does not award bank currency.
        """
        tier, name = tier.lower(), name.strip()
        if not positive_weight(weight) or not 0 <= value <= 1_000_000_000:
            await ctx.send("Weight must be finite and greater than 0, up to 1,000,000. Value must be 0–1,000,000,000.")
            return
        if not 1 <= len(name) <= 100 or any(ord(c) < 32 for c in name):
            await ctx.send("Item names must be 1–100 characters on one line.")
            return
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).tiers() as tiers:
                if tier not in tiers:
                    await ctx.send("Create that tier first with crateset tier.")
                    return
                items = tiers[tier]["items"]
                if name not in items and len(items) >= 100:
                    await ctx.send("Each tier can contain up to 100 items.")
                    return
                items[name] = {"weight": weight, "value": value}
        await ctx.send("Item saved.")

    @crateset.command(name="removetier")
    async def remove_tier(self, ctx, tier: str):
        """Remove a tier from future pulls. Collected items remain."""
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).tiers() as tiers:
                removed = tiers.pop(tier.lower(), None)
        await ctx.send("Tier removed. Existing inventories are preserved." if removed is not None else "Tier not found.")

    @crateset.command(name="removeitem")
    async def remove_item(self, ctx, tier: str, *, name: str):
        """Remove an item from a tier's future pulls. Collected items remain."""
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).tiers() as tiers:
                removed = tiers.get(tier.lower(), {}).get("items", {}).pop(name.strip(), None)
        await ctx.send("Item removed. Existing inventories are preserved." if removed is not None else "Item not found.")

    @crateset.command(name="cooldown")
    async def cooldown(self, ctx, seconds: int):
        """Set time between pulls in seconds; 0 allows unlimited pulls (default)."""
        if not 0 <= seconds <= 31_536_000:
            await ctx.send("Choose a cooldown from 0 to 31,536,000 seconds.")
            return
        async with self.lock(ctx.guild.id):
            await self.config.guild(ctx.guild).cooldown.set(seconds)
        await ctx.send(f"Pull cooldown set to {seconds:,} seconds.")

    @crateset.command(name="enabled")
    async def enabled(self, ctx, enabled: bool):
        """Enable or disable pulls: crateset enabled <true|false>."""
        async with self.lock(ctx.guild.id):
            await self.config.guild(ctx.guild).enabled.set(enabled)
        await ctx.send("Crate pulls enabled." if enabled else "Crate pulls disabled.")
