import asyncio
import copy
import re
import random
from urllib.parse import urlsplit
import time
from typing import Optional

import discord
from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import pagify

from .policy import award, choose_reward, positive_weight, ranking, empty_collection, merge_collections, platform_pull_times, parse_duration, inventory_by_rarity


CRATE_EMOJI = "\U0001f4e6"


class Crates(commands.Cog):
    """Configure crate tiers and collect their random rewards."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=981376420015, force_registration=True)
        self.config.register_guild(tiers={}, cooldown=0, enabled=True, shared_cooldown=True, twitch_mode="points", twitch_command="!crate pull", collections={"discord": {}, "twitch": {}})
        self.config.register_member(inventory={}, pulls=0, value=0, last_pull=0)
        self.locks = {}
        self.openings = set()

    def lock(self, guild_id):
        return self.locks.setdefault(guild_id, asyncio.Lock())

    async def red_delete_data_for_user(self, *, requester, user_id):
        guild_ids = set(await self.config.all_guilds()) | set(await self.config.all_members())
        for guild_id in guild_ids:
            async with self.lock(guild_id):
                state = await self.config.guild_from_id(guild_id).collections()
                state["discord"].pop(str(user_id), None)
                # Remove linked Twitch records too, including their redemption history.
                state["twitch"] = {
                    tid: record for tid, record in state["twitch"].items()
                    if record.get("discord_id") != user_id
                }
                await self.config.guild_from_id(guild_id).collections.set(state)
                await self.config.member_from_ids(guild_id, user_id).clear()

    async def _discord_collection(self, state, guild_id, discord_id):
        key = str(discord_id)
        if key not in state["discord"]:
            # Existing Discord inventories are imported only once. The new record,
            # even when empty, always takes precedence over legacy member storage.
            state["discord"][key] = await self.config.member_from_ids(guild_id, discord_id).all()
        return state["discord"][key]

    async def get_discord_collection(self, guild_id, discord_id):
        """Return a snapshot; Discord membership never requires Twitch linking."""
        async with self.lock(guild_id):
            state = await self.config.guild_from_id(guild_id).collections()
            return copy.deepcopy(await self._discord_collection(state, guild_id, discord_id))

    @staticmethod
    def _twitch_record(state, twitch_id, username):
        if not isinstance(twitch_id, str) or not twitch_id.isascii() or not twitch_id.isdecimal():
            raise ValueError("A permanent numeric Twitch user ID is required.")
        if not isinstance(username, str) or not username.strip():
            raise ValueError("A Twitch username is required.")
        record = state["twitch"].setdefault(twitch_id, {
            "username": username, "discord_id": None,
            "collection": empty_collection(), "redemptions": {},
        })
        record["username"] = username
        return record

    async def link_verified_twitch(self, guild_id, twitch_id, username, discord_id):
        """Trusted integration API: caller MUST verify ownership of BOTH accounts.

        No public command accepts an arbitrary username as proof of ownership.
        A Twitch account cannot be reassigned once linked by this API.
        """
        if not isinstance(discord_id, int) or isinstance(discord_id, bool) or discord_id <= 0:
            raise ValueError("A Discord user ID is required.")
        async with self.lock(guild_id):
            group = self.config.guild_from_id(guild_id)
            state = await group.collections()
            record = self._twitch_record(state, twitch_id, username)
            if record["discord_id"] not in (None, discord_id):
                raise ValueError("This Twitch account is already linked to another Discord account.")
            if any(tid != twitch_id and r.get("discord_id") == discord_id
                   for tid, r in state["twitch"].items()):
                raise ValueError("This Discord account already has a linked Twitch account.")
            data = await self._discord_collection(state, guild_id, discord_id)
            if record["discord_id"] is None:
                merge_collections(data, record["collection"])
                record["collection"] = empty_collection()
                record["discord_id"] = discord_id
            # Merge, cleared source, and link are one persistent write.
            await group.collections.set(state)
            return copy.deepcopy(data)

    async def delete_twitch_data(self, guild_id, twitch_id):
        """Trusted API after verifying a Twitch user's deletion request.

        Already merged Discord inventory remains owned by the Discord account.
        """
        async with self.lock(guild_id):
            group = self.config.guild_from_id(guild_id)
            state = await group.collections()
            state["twitch"].pop(str(twitch_id), None)
            await group.collections.set(state)

    async def get_twitch_collection(self, guild_id, twitch_id):
        """Return a collection snapshot, or None for an unknown Twitch account."""
        async with self.lock(guild_id):
            state = await self.config.guild_from_id(guild_id).collections()
            record = state["twitch"].get(str(twitch_id))
            if record is None:
                return None
            if record["discord_id"] is not None:
                data = await self._discord_collection(state, guild_id, record["discord_id"])
            else:
                data = record["collection"]
            return copy.deepcopy(data)

    async def pull_twitch(self, guild_id, twitch_id, username, redemption_id):
        """Trusted API for an authenticated Twitch redemption, not a Discord command.

        Return tier/name/value/duplicate. Repeated redemption IDs never award twice.
        Raises ValueError for disabled, unconfigured, or cooling-down pulls.
        """
        if not isinstance(redemption_id, str) or not redemption_id.strip():
            raise ValueError("A unique Twitch redemption ID is required.")
        return await self._pull_reward(guild_id, twitch_id=twitch_id,
                                       username=username, redemption_id=redemption_id, twitch_source="points")

    async def pull_twitch_command(self, guild_id, twitch_id, username, message_id, message):
        """Trusted API for an authenticated Twitch chat command.

        Caller verifies broadcaster routing and supplies Twitch's message ID and
        original message text. Repeated message IDs never award twice.
        """
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValueError("A unique Twitch message ID is required.")
        if not isinstance(message, str):
            raise ValueError("The original Twitch chat message is required.")
        return await self._pull_reward(
            guild_id, twitch_id=twitch_id, username=username,
            redemption_id=message_id, twitch_source="command", message=message,
        )

    async def _pull_reward(self, guild_id, *, discord_id=None, twitch_id=None,
                           username=None, redemption_id=None, twitch_source="points", message=None):
        async with self.lock(guild_id):
            group = self.config.guild_from_id(guild_id)
            settings = await group.all()
            state = settings["collections"]
            record = None
            if twitch_id is not None:
                record = self._twitch_record(state, twitch_id, username)
                receipts = (record["redemptions"] if twitch_source == "points"
                            else record.setdefault("commands", {}))
                if redemption_id in receipts:
                    return dict(receipts[redemption_id], duplicate=True)
                mode = settings.get("twitch_mode", "points")
                if mode not in (twitch_source, "both"):
                    raise ValueError(f"Twitch {twitch_source} pulls are disabled in this server.")
                if twitch_source == "command" and message.strip().casefold() != settings.get(
                        "twitch_command", "!crate pull").casefold():
                    raise ValueError("This message does not match the configured crate pull command.")
                discord_id = record["discord_id"]
            data = (await self._discord_collection(state, guild_id, discord_id)
                    if discord_id is not None else record["collection"])
            if not settings["enabled"]:
                raise ValueError("Crate pulls are disabled in this server.")
            now = time.time()
            platform = "twitch" if twitch_id is not None else "discord"
            pull_times = platform_pull_times(data)
            last_pull = (data["last_pull"] if settings.get("shared_cooldown", True)
                         else pull_times[platform])
            remaining = last_pull + settings["cooldown"] - now
            if remaining > 0:
                raise ValueError(f"Your next pull is available in {int(remaining) + 1} seconds.")
            tier, name, value = choose_reward(settings["tiers"])
            award(data, name, value, now)
            pull_times[platform] = now
            data["last_pulls"] = pull_times
            tier_config = settings["tiers"][tier]
            item = tier_config["items"].get(name, {}) if name is not None else {}
            result = {"tier": tier, "name": name, "value": value,
                      "emoji": tier_config.get("emoji", "\U0001f4e6"),
                      "image": item.get("image"), "empty": name is None}
            if record is not None:
                receipts[redemption_id] = result
            # Award and redemption receipt commit together, before any announcement.
            await group.collections.set(state)
            return dict(result, duplicate=False)

    async def send_pages(self, ctx, text):
        for page in pagify(text, page_length=1800):
            await ctx.send(page, allowed_mentions=discord.AllowedMentions.none())

    @commands.guild_only()
    @commands.group(name="crate", invoke_without_command=True)
    async def crate(self, ctx):
        """Pull crates, view collections, and see the server leaderboard."""
        await ctx.send_help()

    async def embed_access(self, ctx):
        if not ctx.channel.permissions_for(ctx.guild.me).embed_links:
            await ctx.send("I need the Embed Links permission to display crates.")
            return False
        return True

    def collection_embed(self, title, description):
        return discord.Embed(title=title, description=description, colour=0x5865F2)

    async def send_collection(self, ctx, title, lines, summary, thumbnail=None):
        pages = list(pagify("\n".join(lines), page_length=3000)) or ["Nothing here yet."]
        colour = await ctx.embed_colour()
        for number, page in enumerate(pages, 1):
            embed = discord.Embed(title=title, description=page, colour=colour)
            embed.add_field(name="Collection stats", value=summary, inline=False)
            embed.set_footer(text=f"Page {number}/{len(pages)} | Crates")
            if thumbnail:
                embed.set_thumbnail(url=thumbnail)
            await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    def result_embed(self, result, member):
        empty = result.get("empty", result["name"] is None)
        embed = discord.Embed(
            title="Better luck next time!" if empty else "Congratulations!",
            description=(f"{member.mention}, your crate was empty this time." if empty else
                         f"{member.mention}, you pulled **{discord.utils.escape_markdown(result['name'])}**!"),
            colour=0x747F8D if empty else 0xF1C40F,
        )
        embed.add_field(name="Crate tier", value=f"{result.get('emoji', CRATE_EMOJI)} {result['tier']}")
        embed.add_field(name="Collected value", value=f"{result['value']:,}")
        embed.set_footer(text="Try again after your cooldown." if empty else "Added to your inventory.")
        if result.get("image") and not empty:
            embed.set_image(url=result["image"])
        return embed

    async def animate_pull(self, ctx, result, tiers):
        emojis = [tier.get("emoji", "\U0001f4e6") for tier in tiers.values() if tier["items"]]
        emojis = emojis or ["\U0001f4e6"]
        strip = [random.choice(emojis) for _ in range(7)]
        def frame():
            return self.collection_embed(
                "Opening your crate...",
                f"{ctx.author.mention}\n\n**▼** Selected crate **▼**\n"
                + "  ·  ".join(f"**【{emoji}】**" if i == 3 else emoji for i, emoji in enumerate(strip)),
            )
        message = await ctx.send(content=ctx.author.mention, embed=frame(),
                                 allowed_mentions=discord.AllowedMentions(users=[ctx.author], roles=False, everyone=False))
        # Limit edits and progressively increase delays; Discord may rate-limit frames.
        try:
            for index, delay in enumerate((0.5, 0.5, 0.65, 0.85, 1.1, 1.4)):
                await asyncio.sleep(delay)
                strip = strip[1:] + [random.choice(emojis)]
                if index == 5:
                    strip[3] = result.get("emoji", "\U0001f4e6")
                await message.edit(embed=frame(), allowed_mentions=discord.AllowedMentions.none())
            await asyncio.sleep(1)
            await message.edit(embed=self.result_embed(result, ctx.author), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            # A deleted message or failed animation must still leave a visible result.
            await ctx.send(embed=self.result_embed(result, ctx.author), allowed_mentions=discord.AllowedMentions.none())

    @crate.command(name="pull")
    async def pull(self, ctx):
        """Open a crate with an animated reveal."""
        if not await self.embed_access(ctx):
            return
        key = (ctx.guild.id, ctx.author.id)
        if key in self.openings:
            await ctx.send("Your crate is still opening!")
            return
        self.openings.add(key)
        try:
            try:
                result = await self._pull_reward(ctx.guild.id, discord_id=ctx.author.id)
            except ValueError as exc:
                await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
                return
            tiers = await self.config.guild(ctx.guild).tiers()
            await self.animate_pull(ctx, result, tiers)
        finally:
            self.openings.discard(key)

    async def grant_item(self, guild_id, discord_id, tier, name, quantity):
        """Grant configured collectibles without changing pulls or cooldowns."""
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 1_000_000:
            raise ValueError("Choose a quantity from 1 to 1,000,000.")
        async with self.lock(guild_id):
            group = self.config.guild_from_id(guild_id)
            settings = await group.all()
            item = settings["tiers"].get(tier.lower(), {}).get("items", {}).get(name)
            if item is None:
                raise ValueError("Item not found in that tier. Use its exact configured name.")
            if item.get("empty", False):
                raise ValueError("Empty-pull rewards cannot be given as collectibles.")
            state = settings["collections"]
            data = await self._discord_collection(state, guild_id, discord_id)
            data["inventory"][name] = data["inventory"].get(name, 0) + quantity
            data["value"] += item["value"] * quantity
            await group.collections.set(state)

    @crate.command(name="give")
    @commands.mod_or_permissions(manage_messages=True)
    async def give(self, ctx, member: discord.Member, tier: str, quantity: int, *, name: str):
        """Moderators: give <member> <tier> <quantity> <item name>.

        Adds items and their configured value, without counting as pulls or
        affecting cooldowns. Gift-only members remain off the pull leaderboard.
        """
        name = name.strip()
        try:
            await self.grant_item(ctx.guild.id, member.id, tier, name, quantity)
        except ValueError as exc:
            await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
            return
        await ctx.send(
            f"Gave **{quantity:,} x {discord.utils.escape_markdown(name)}** to {member.mention}.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def remove_inventory_item(self, guild_id, discord_id, name, quantity):
        """Remove owned items without changing pull counts or cooldown timestamps."""
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 1_000_000:
            raise ValueError("Choose a quantity from 1 to 1,000,000.")
        async with self.lock(guild_id):
            group = self.config.guild_from_id(guild_id)
            settings = await group.all()
            state = settings["collections"]
            data = await self._discord_collection(state, guild_id, discord_id)
            owned = data["inventory"].get(name, 0)
            if owned < quantity:
                raise ValueError(f"That member owns {owned:,} of that item; cannot remove {quantity:,}. Use the exact inventory item name.")
            # Match the unit value displayed in inventory, including duplicate names.
            unit_value = 0
            for tier in sorted(settings["tiers"].values(), key=lambda t: t["weight"]):
                if name in tier["items"]:
                    unit_value = tier["items"][name]["value"]
                    break
            remaining = owned - quantity
            if remaining:
                data["inventory"][name] = remaining
            else:
                del data["inventory"][name]
            data["value"] = max(0, data["value"] - unit_value * quantity)
            await group.collections.set(state)

    @crate.command(name="remove")
    @commands.mod_or_permissions(manage_messages=True)
    async def remove(self, ctx, member: discord.Member, quantity: int, *, name: str):
        """Moderators: remove <member> <quantity> <item name>.

        Deducts items and their current catalog value (minimum total value: zero).
        Items removed from the catalog can still be removed, with no value deduction.
        Pull counts and cooldowns stay unchanged.
        """
        name = name.strip()
        try:
            await self.remove_inventory_item(ctx.guild.id, member.id, name, quantity)
        except ValueError as exc:
            await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
            return
        await ctx.send(
            f"Removed **{quantity:,} x {discord.utils.escape_markdown(name)}** from {member.mention}'s inventory.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @crate.command(name="inventory", aliases=["inv"])
    async def inventory(self, ctx, member: Optional[discord.Member] = None):
        """Display collected items, rarest tiers first."""
        if not await self.embed_access(ctx):
            return
        member = member or ctx.author
        data = await self.get_discord_collection(ctx.guild.id, member.id)
        tiers = await self.config.guild(ctx.guild).tiers()
        icons, values = {}, {}
        for tier in sorted(tiers.values(), key=lambda t: t["weight"]):
            for name, item in tier["items"].items():
                icons.setdefault(name, tier.get("emoji", "\U0001f4e6"))
                values.setdefault(name, item["value"])
        lines = []
        for name, qty in inventory_by_rarity(data["inventory"], tiers):
            valuation = (f"1x Value: {values[name]:,} | x{qty:,} Value: {values[name] * qty:,}"
                         if name in values else "Value: unavailable (item removed)")
            lines.append(f"{icons.get(name, CRATE_EMOJI)} **{discord.utils.escape_markdown(name)}**  "
                         f"`x{qty:,}` · {valuation}")
        summary = (f"**{sum(data['inventory'].values()):,}** items | **{len(data['inventory']):,}** unique\n"
                   f"**{data['pulls']:,}** pulls | **{data['value']:,}** collected value")
        await self.send_collection(ctx, f"{member.display_name}'s inventory", lines or ["No items collected yet."],
                                   summary, str(member.display_avatar.url))

    @crate.command(name="leaderboard", aliases=["lb"])
    async def leaderboard(self, ctx):
        """Display the server's collectors, ranked by value then pulls."""
        if not await self.embed_access(ctx):
            return
        async with self.lock(ctx.guild.id):
            members = await self.config.all_members(ctx.guild)
            state = await self.config.guild(ctx.guild).collections()
            members.update({int(uid): data for uid, data in state["discord"].items()})
        current = {member.id: member for member in ctx.guild.members}
        rows = ranking(members, set(current))
        medals = ("\U0001f947", "\U0001f948", "\U0001f949")
        lines = []
        for position, (uid, data) in enumerate(rows, 1):
            badge = medals[position - 1] if position <= 3 else f"**#{position}**"
            name = discord.utils.escape_markdown(current[uid].display_name)
            lines.append(f"{badge} **{name}**\n{data['value']:,} value · {data['pulls']:,} pulls")
        summary = f"**{len(rows):,}** collectors | Ranked by collected value, then pulls"
        await self.send_collection(ctx, "\U0001f3c6 Crates leaderboard", lines or ["No crates pulled yet. Be the first!"], summary)

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
        lines.append(f"Discord/Twitch cooldown shared: {settings.get('shared_cooldown', True)}")
        lines.append(f"Twitch pull mode: {settings.get('twitch_mode', 'points')} | "
                     f"Chat command: {settings.get('twitch_command', '!crate pull')}")
        for key, tier in sorted(tiers.items()):
            chance = tier["weight"] / total * 100 if total and tier["items"] else 0
            lines.append(f"{tier.get('emoji', CRATE_EMOJI)} **{key}** - weight {tier['weight']:g}, chance {chance:.2f}%")
            item_total = sum(i["weight"] for i in tier["items"].values())
            for name, item in sorted(tier["items"].items()):
                lines.append(f"  {discord.utils.escape_markdown(name)} - value {item['value']:,}, "
                             f"weight {item['weight']:g}, {item['weight'] / item_total * 100:.2f}% within tier"
                             + (" [empty pull]" if item.get("empty") else "")
                             + (" [image]" if item.get("image") else ""))
            if not tier["items"]:
                lines.append("  No items; excluded from pulls.")
        if not tiers:
            lines.append("No tiers configured. Add a tier, then add its items.")
        await self.send_pages(ctx, "\n".join(lines))

    @crateset.command(name="tier")
    async def set_tier(self, ctx, tier: str, weight: float, emoji: Optional[str] = None):
        """Add/update a tier: crateset tier <tier> <weight> [emoji].

        Tier names use 1-32 letters, digits, or hyphens. Weights are relative:
        weights 3 and 1 give 75% and 25% chances among populated tiers.
        """
        tier = tier.lower()
        if emoji is not None and not self.valid_emoji(emoji):
            await ctx.send("Use a Unicode emoji or a Discord custom emoji.")
            return
        if not re.fullmatch(r"[a-z0-9-]{1,32}", tier) or not positive_weight(weight):
            await ctx.send("Use a tier name of 1-32 letters/digits/hyphens and a finite weight greater than 0, up to 1,000,000.")
            return
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).tiers() as tiers:
                if tier not in tiers and len(tiers) >= 50:
                    await ctx.send("A server can have up to 50 tiers.")
                    return
                entry = tiers.setdefault(tier, {"items": {}, "emoji": "\U0001f4e6"})
                entry["weight"] = weight
                if emoji is not None:
                    entry["emoji"] = emoji
        await ctx.send(f"Tier `{tier}` saved with weight {weight:g}.")

    @crateset.command(name="item")
    async def set_item(self, ctx, tier: str, weight: float, value: int, *, name: str):
        """Add/update an item: crateset item <tier> <weight> <value> <item name>.

        One item is awarded per pull. Item weights are relative within their tier.
        Value is used for leaderboard points; it does not award bank currency.
        """
        tier, name = tier.lower(), name.strip()
        if not positive_weight(weight) or not 0 <= value <= 1_000_000_000:
            await ctx.send("Weight must be finite and greater than 0, up to 1,000,000. Value must be 0-1,000,000,000.")
            return
        if not 1 <= len(name) <= 100 or any(ord(c) < 32 for c in name):
            await ctx.send("Item names must be 1-100 characters on one line.")
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
                items[name] = dict(items.get(name, {}), weight=weight, value=value)
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
    async def cooldown(self, ctx, *, duration: str):
        """Set time between pulls: 1m, 3h, 1d, 2w, 1h 30m, or plain seconds.

        Use 0 for unlimited pulls (default). Maximum: 365 days.
        """
        try:
            seconds = parse_duration(duration)
        except ValueError as exc:
            await ctx.send(str(exc))
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

    @crateset.command(name="twitchmode")
    async def twitchmode(self, ctx, mode: str):
        """Choose Twitch pulls: points, command, both, or off. Default: points."""
        mode = mode.lower()
        if mode not in {"points", "command", "both", "off"}:
            await ctx.send("Choose points, command, both, or off.")
            return
        async with self.lock(ctx.guild.id):
            await self.config.guild(ctx.guild).twitch_mode.set(mode)
        await ctx.send(f"Twitch pull mode set to {mode}.")

    @crateset.command(name="twitchcommand")
    async def twitchcommand(self, ctx, *, command: str):
        """Set the exact Twitch chat command. Default: !crate pull."""
        command = command.strip()
        if not 1 <= len(command) <= 100 or any(ord(c) < 32 for c in command):
            await ctx.send("Use a single-line command of 1–100 characters.")
            return
        async with self.lock(ctx.guild.id):
            await self.config.guild(ctx.guild).twitch_command.set(command)
        await ctx.send("Twitch pull command saved.")

    @crateset.command(name="sharedcooldown")
    async def sharedcooldown(self, ctx, shared: bool):
        """Share the cooldown between linked Discord/Twitch accounts (default: true).

        False gives each platform its own timer. Twitch points and chat commands
        always share the Twitch timer. Both use the configured cooldown duration.
        """
        async with self.lock(ctx.guild.id):
            await self.config.guild(ctx.guild).shared_cooldown.set(shared)
        await ctx.send("Discord and Twitch now share a cooldown." if shared else
                       "Discord and Twitch now have separate cooldowns.")

    @staticmethod
    def valid_emoji(value):
        return bool(re.fullmatch(r"<a?:[A-Za-z0-9_]{2,32}:[0-9]+>", value) or
                    (0 < len(value) <= 32 and not any(c.isspace() for c in value)
                     and any(ord(c) >= 0x2000 for c in value)
                     and not any(c in value for c in "<>@")))

    @crateset.command(name="tieremoji")
    async def tieremoji(self, ctx, tier: str, emoji: str):
        """Set an existing tier's emoji: crateset tieremoji bronze :emoji:."""
        if not self.valid_emoji(emoji):
            await ctx.send("Use a Unicode emoji or a Discord custom emoji.")
            return
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).tiers() as tiers:
                if tier.lower() not in tiers:
                    await ctx.send("Tier not found.")
                    return
                tiers[tier.lower()]["emoji"] = emoji
        await ctx.send("Tier emoji saved.")

    @crateset.command(name="itemimage")
    async def itemimage(self, ctx, tier: str, url: str, *, name: str):
        """Set an item's image URL, or use 'none' to clear: tier URL item name."""
        url = url.strip("<>")
        try:
            parsed = urlsplit(url)
        except ValueError:
            await ctx.send("Use a valid public HTTP(S) image URL, or none to remove it.")
            return
        if url.lower() != "none" and (parsed.scheme not in {"http", "https"} or not parsed.netloc or len(url) > 2000):
            await ctx.send("Use a public HTTP(S) image URL, or none to remove it.")
            return
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).tiers() as tiers:
                item = tiers.get(tier.lower(), {}).get("items", {}).get(name.strip())
                if item is None:
                    await ctx.send("Item not found.")
                    return
                item["image"] = None if url.lower() == "none" else url
        await ctx.send("Item image saved.")

    @crateset.command(name="itemempty")
    async def itemempty(self, ctx, tier: str, empty: bool, *, name: str):
        """Mark a reward as an empty pull: tier true|false item name.

        Empty rewards keep their weight but award no item or value. They count as
        pulls and consume the cooldown. False restores the item's configured value.
        """
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).tiers() as tiers:
                item = tiers.get(tier.lower(), {}).get("items", {}).get(name.strip())
                if item is None:
                    await ctx.send("Item not found.")
                    return
                item["empty"] = empty
        await ctx.send("Empty-pull setting saved.")
