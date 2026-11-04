import asyncio
import copy
from datetime import datetime, time as wall_time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import math
import logging
import re
import random
from urllib.parse import urlsplit
import time
from typing import Optional

import discord
from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import pagify

from .policy import award, choose_reward, positive_weight, empty_collection, merge_collections, platform_pull_times, parse_duration, inventory_by_rarity, lucky_tier_weights, item_weights, resolve_crate


log = logging.getLogger("red.crates")

CRATE_EMOJI = "\U0001f4e6"


def reset_timezone(name):
    if name.upper() == "EST":
        return timezone(timedelta(hours=-5), "EST")
    return ZoneInfo(name)


def daily_window(now, clock, zone_name):
    zone = reset_timezone(zone_name)
    local_date = datetime.fromtimestamp(now, zone).date()
    reset_time = wall_time.fromisoformat(clock)
    start = datetime.combine(local_date, reset_time, zone).timestamp()
    if now < start:
        local_date -= timedelta(days=1)
        start = datetime.combine(local_date, reset_time, zone).timestamp()
    end = datetime.combine(local_date + timedelta(days=1), reset_time, zone).timestamp()
    return start, end


class Crates(commands.Cog):
    """Configure crate tiers and collect their random rewards."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=981376420015, force_registration=True)
        self.config.register_guild(tiers={}, command_channel=None, luck_roles={}, cooldown=0, cooldown_schedule={"mode": "user"}, enabled=True, shared_cooldown=True, twitch_mode="points", twitch_command="!crate pull", collections={"discord": {}, "twitch": {}})
        self.config.register_member(inventory={}, pulls=0, value=0, last_pull=0)
        self.locks = {}
        self.openings = set()

    def lock(self, guild_id):
        return self.locks.setdefault(guild_id, asyncio.Lock())

    async def cog_check(self, ctx):
        # Apply only to the crate group, including aliases and moderator commands.
        # crateset remains usable elsewhere so admins can always change the channel.
        if ctx.guild is None or ctx.command.qualified_name.split()[0] != "crate":
            return True
        settings = await self.config.guild_from_id(ctx.guild.id).all()
        channel_id = settings.get("command_channel")
        if channel_id is None or ctx.channel.id == channel_id:
            return True
        await ctx.send(f"Crate commands can only be used in <#{channel_id}>. "
                       "An admin can change this with crateset channel.",
                       allowed_mentions=discord.AllowedMentions.none())
        return False

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

    async def pull_twitch(self, guild_id, twitch_id, username, redemption_id, crate_name=None):
        """Trusted API for an authenticated Twitch redemption, not a Discord command.

        Return tier/name/value/duplicate. Repeated redemption IDs never award twice.
        Raises ValueError for disabled, unconfigured, or cooling-down pulls.
        """
        if not isinstance(redemption_id, str) or not redemption_id.strip():
            raise ValueError("A unique Twitch redemption ID is required.")
        return await self._pull_reward(guild_id, twitch_id=twitch_id,
                                       username=username, redemption_id=redemption_id, twitch_source="points", selected_crate=crate_name)

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

    def member_luck(self, guild_id, discord_id, settings):
        bonuses = settings.get("luck_roles", {})
        if not bonuses or discord_id is None:
            return 0
        guild = self.bot.get_guild(guild_id)
        member = guild.get_member(discord_id) if guild else None
        if member is None:
            return 0
        return max((bonuses.get(str(role.id), 0) for role in member.roles), default=0)

    async def _pull_reward(self, guild_id, *, discord_id=None, twitch_id=None,
                           username=None, redemption_id=None, twitch_source="points", message=None, action_context=None, selected_crate=None, defer_reward_commands=False):
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
                if twitch_source == "command":
                    configured = settings.get("twitch_command", "!crate pull").casefold()
                    text = message.strip().casefold()
                    if text != configured:
                        if text.startswith(configured + " ") and len(text[len(configured):].split()) == 1:
                            selected_crate = text[len(configured):].strip()
                        else:
                            raise ValueError("This message does not match the configured crate pull command.")
                discord_id = record["discord_id"]
            data = (await self._discord_collection(state, guild_id, discord_id)
                    if discord_id is not None else record["collection"])
            if not settings["enabled"]:
                raise ValueError("Crate pulls are disabled in this server.")
            now = time.time()
            platform = "twitch" if twitch_id is not None else "discord"
            pull_times = platform_pull_times(data)
            shared = settings.get("shared_cooldown", True)
            schedule = settings["cooldown_schedule"]
            mode = schedule["mode"]
            timer_key = "shared" if shared else platform
            last_pull = data["last_pull"] if shared else pull_times[platform]
            remaining = last_pull + settings["cooldown"] - now
            if mode == "global":
                last_global = state.get("global_pull_times", {}).get(timer_key, 0)
                remaining = last_global + settings["cooldown"] - now
            elif mode == "daily":
                start, end = daily_window(now, schedule["time"], schedule["zone"])
                remaining = end - now if last_pull >= start else 0
            if remaining > 0:
                subject = "The server's next pull" if mode == "global" else "Your next pull"
                raise ValueError(f"{subject} is available in {math.ceil(remaining)} seconds.")
            bonus = self.member_luck(guild_id, discord_id, settings)
            selected_crate = resolve_crate(settings["tiers"], selected_crate)
            tier, name, value, reward_key = choose_reward(settings["tiers"], bonus, crate_name=selected_crate, details=True)
            award(data, name, value, now)
            stats = data.setdefault("crate_stats", {}).setdefault(tier, {"pulls": 0, "value": 0})
            stats["pulls"] += 1
            stats["value"] += value
            pull_times[platform] = now
            data["last_pulls"] = pull_times
            if mode == "global":
                global_times = state.setdefault("global_pull_times", {})
                global_times[platform] = global_times["shared"] = now
            tier_config = settings["tiers"][tier]
            item = tier_config["items"][reward_key]
            result = {"tier": tier, "name": name, "value": value,
                      "emoji": tier_config.get("emoji", "\U0001f4e6"),
                      "image": item.get("image"), "empty": name is None,
                      "item_emoji": item.get("emoji", CRATE_EMOJI), "reward_key": reward_key,
                      "item_odds": self.item_odds(tier_config, bonus)}
            if record is not None:
                receipts[redemption_id] = result
            # Award and redemption receipt commit together, before any announcement.
            await group.collections.set(state)
            reward_commands = copy.deepcopy(item.get("reward_commands", [])) if name is not None else []
        # Never run external commands while holding the collection lock. Commands
        # such as crate resetcooldown acquire it again. Persisted Twitch receipts
        # ensure duplicate events return above without repeating these effects.
        if defer_reward_commands:
            result["pending_reward_commands"] = reward_commands
        else:
            outcomes = await self.run_reward_commands(guild_id, discord_id, reward_commands, action_context)
            if outcomes:
                result["command_results"] = outcomes
        return dict(result, duplicate=False)

    @staticmethod
    def render_reward_command(template, member_id, guild_id):
        return (template.replace("{user_id}", str(member_id))
                .replace("{user}", f"<@{member_id}>")
                .replace("{guild_id}", str(guild_id)))

    async def run_reward_commands(self, guild_id, member_id, actions, source_ctx=None):
        if not actions:
            return []
        outcomes = []
        guild = self.bot.get_guild(guild_id)
        recipient = guild.get_member(member_id) if guild and member_id else None
        for action in actions:
            try:
                if recipient is None:
                    outcomes.append("Skipped: recipient is not a linked Discord server member.")
                    continue
                executor = guild.get_member(action["executor_id"])
                if executor is None or not await self.bot.is_owner(executor):
                    outcomes.append("Skipped: configuring bot owner is unavailable or no longer an owner.")
                    continue
                text = self.render_reward_command(action["command"], member_id, guild_id)
                if source_ctx is not None:
                    source = source_ctx.message
                    prefix = source_ctx.prefix
                else:
                    # Twitch has no Discord message. Reuse the saved setup message
                    # only as context; never repost it or process chat listeners.
                    channel = guild.get_channel(action["channel_id"])
                    if channel is None:
                        outcomes.append("Skipped: reward command setup channel is unavailable.")
                        continue
                    source = await channel.fetch_message(action["message_id"])
                    prefix = action["prefix"]
                message = copy.copy(source)
                message.author = executor
                message.content = prefix + text
                command_ctx = await self.bot.get_context(message)
                if not command_ctx.valid:
                    outcomes.append("Failed: reward command was not found.")
                    continue
                # Do not permit reward commands to roll another reward or change
                # their own setup. Only the explicit cooldown reset is allowed
                # from this cog, including when its aliases are used.
                if command_ctx.command.cog is self:
                    parts = text.split()
                    target = self.bot.get_command(" ".join(parts[:2]))
                    if target is None or target.qualified_name != "crate resetcooldown":
                        outcomes.append("Skipped: only crate resetcooldown may be used from Crates itself.")
                        continue
                await self.bot.invoke(command_ctx)
                outcomes.append("Failed: command reported an error." if command_ctx.command_failed else "Command completed.")
            except Exception:
                # The item has already been saved. Never reroll or retry side
                # effects after an unknown partial failure.
                log.exception("Crates reward command failed in guild %s", guild_id)
                outcomes.append("Failed: command could not be completed; check bot logs.")
        return outcomes

    async def send_pages(self, ctx, text):
        for page in pagify(text, page_length=1800):
            await ctx.send(page, allowed_mentions=discord.AllowedMentions.none())

    @commands.guild_only()
    @commands.group(name="crate", invoke_without_command=True)
    async def crate(self, ctx, crate_name: Optional[str] = None, action: Optional[str] = None):
        """Use crate <name> pull, or crate pull for a single configured crate."""
        if crate_name is not None and action is not None and action.lower() == "pull":
            await self.open_crate(ctx, crate_name)
            return
        if crate_name is not None and action is not None and action.lower() in {"leaderboard", "lb"}:
            await self.show_leaderboard(ctx, crate_name)
            return
        if crate_name is not None:
            await ctx.send("Use crate <name> pull, or crate pull <name>.")
            return
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
            description=(f"{member.mention}, your **{result['tier']}** crate was empty this time." if empty else
                         f"{member.mention}, your **{result['tier']}** crate contained **{discord.utils.escape_markdown(result['name'])}**!"),
            colour=0x747F8D if empty else 0xF1C40F,
        )
        embed.add_field(name="Crate", value=f"{result.get('emoji', CRATE_EMOJI)} {result['tier']}")
        embed.add_field(name="Collected value", value=f"{result['value']:,}")
        embed.set_footer(text="Try again after your cooldown." if empty else "Added to your inventory.")
        if result.get("image") and not empty:
            embed.set_image(url=result["image"])
        return embed

    @staticmethod
    def item_odds(crate, bonus=0):
        weights = item_weights(crate, bonus)
        total = sum(weights.values())
        return [{"name": name, "emoji": crate["items"][name].get("emoji", CRATE_EMOJI),
                 "chance": weight / total * 100, "empty": crate["items"][name].get("empty", False)}
                for name, weight in sorted(weights.items(), key=lambda row: row[1])]

    def opening_embed(self, member, result, strip):
        embed = self.collection_embed(
            f"Opening {result['tier']} crate...",
            f"{member.mention} is pulling the **{result['tier']}** crate!\n\n**▼ Selected item ▼**\n"
            + "  ·  ".join(f"**【{emoji}】**" if i == 3 else emoji for i, emoji in enumerate(strip)),
        )
        lines = [f"{item['emoji']} {discord.utils.escape_markdown(item['name'])}"
                 + (" (empty)" if item.get("empty") else "") + f" — {item['chance']:.4f}%"
                 for item in result.get("item_odds", [])]
        # All 100 supported rewards fit across bounded fields; pages continue in
        # companion embeds sent once, rather than repeating every animation frame.
        pages = list(pagify("\n".join(lines), page_length=950))
        if pages:
            embed.add_field(name="Potential items & chances", value=pages[0], inline=False)
        if len(pages) > 1:
            embed.set_footer(text="Full reward chances are listed in the accompanying message.")
        return embed, pages[1:]

    async def animate_pull(self, ctx, result, tiers):
        if "item_odds" not in result:
            result = dict(result, item_odds=self.item_odds(tiers.get(result["tier"], {"items": {}})))
        emojis = [item["emoji"] for item in result["item_odds"]] or [CRATE_EMOJI]
        strip = [random.choice(emojis) for _ in range(7)]
        embed, extra = self.opening_embed(ctx.author, result, strip)
        if extra:
            # Keep each embed far below Discord's field and total text limits.
            for page in extra:
                await ctx.send(embed=self.collection_embed(f"{result['tier']} crate — more reward chances", page),
                               allowed_mentions=discord.AllowedMentions.none())
        message = await ctx.send(content=ctx.author.mention, embed=embed,
                                 allowed_mentions=discord.AllowedMentions(users=[ctx.author], roles=False, everyone=False))
        try:
            for index, delay in enumerate((0.5, 0.5, 0.65, 0.85, 1.1, 1.4)):
                await asyncio.sleep(delay)
                strip = strip[1:] + [random.choice(emojis)]
                if index == 5:
                    strip[3] = result.get("item_emoji", CRATE_EMOJI)
                frame, _ = self.opening_embed(ctx.author, result, strip)
                await message.edit(embed=frame, allowed_mentions=discord.AllowedMentions.none())
            await asyncio.sleep(1)
            await message.edit(embed=self.result_embed(result, ctx.author), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            await ctx.send(embed=self.result_embed(result, ctx.author), allowed_mentions=discord.AllowedMentions.none())

    @crate.command(name="pull")
    async def pull(self, ctx, crate_name: Optional[str] = None):
        """Open a named crate; omit the name when only one crate is configured."""
        await self.open_crate(ctx, crate_name)

    async def open_crate(self, ctx, crate_name=None):
        if not await self.embed_access(ctx):
            return
        key = (ctx.guild.id, ctx.author.id)
        if key in self.openings:
            await ctx.send("Your crate is still opening!")
            return
        self.openings.add(key)
        try:
            try:
                result = await self._pull_reward(ctx.guild.id, discord_id=ctx.author.id, action_context=ctx,
                                                selected_crate=crate_name, defer_reward_commands=True)
            except ValueError as exc:
                await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
                return
            tiers = await self.config.guild(ctx.guild).tiers()
            await self.animate_pull(ctx, result, tiers)
            outcomes = await self.run_reward_commands(
                ctx.guild.id, ctx.author.id, result.pop("pending_reward_commands", []), ctx)
            if outcomes:
                await ctx.send("\n".join(outcomes), allowed_mentions=discord.AllowedMentions.none())
        finally:
            self.openings.discard(key)

    async def deliver_store_purchase(self, guild_id, discord_id, purchase_id, kind,
                                     tier=None, name=None, quantity=1):
        """Trusted Store API: deliver once per purchase ID, without normal pull effects.

        Purchased openings use current tier odds and role luck. Purchases do not
        alter pull counts/cooldowns or run item reward commands.
        """
        if not isinstance(purchase_id, str) or not purchase_id or len(purchase_id) > 100:
            raise ValueError("A valid purchase ID is required.")
        if kind not in {"item", "crate"} or not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 1000:
            raise ValueError("Invalid Store reward.")
        if kind == "crate" and quantity != 1:
            raise ValueError("Purchase one crate opening at a time.")
        async with self.lock(guild_id):
            group = self.config.guild_from_id(guild_id)
            settings = await group.all()
            state = settings["collections"]
            data = await self._discord_collection(state, guild_id, discord_id)
            receipts = data.setdefault("store_receipts", {})
            if purchase_id in receipts:
                return copy.deepcopy(receipts[purchase_id])
            if not settings["enabled"]:
                raise ValueError("Crates is currently disabled in this server.")
            named_opening = kind == "crate" and tier is not None
            if kind == "crate":
                bonus = self.member_luck(guild_id, discord_id, settings)
                tier, name, value, reward_key = choose_reward(
                    settings["tiers"], bonus, crate_name=tier, details=True)
                entry = settings["tiers"][tier]
                item = entry["items"][reward_key]
            else:
                entry = settings["tiers"].get(tier, {})
                item = entry.get("items", {}).get(name)
                if item is None or item.get("empty"):
                    raise ValueError("The listed collectible is no longer available.")
                value = item["value"]
            if name is not None:
                data["inventory"][name] = data["inventory"].get(name, 0) + quantity
                data["value"] += value * quantity
            result = {"tier": tier, "name": name, "value": value * quantity,
                      "quantity": quantity, "empty": name is None,
                      "emoji": entry.get("emoji", CRATE_EMOJI), "image": item.get("image"),
                      "item_emoji": item.get("emoji", CRATE_EMOJI),
                      "item_odds": self.item_odds(entry, bonus if named_opening else 0)}
            receipts[purchase_id] = result
            await group.collections.set(state)
            return copy.deepcopy(result)

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
        affecting cooldowns. Gifts count toward leaderboard inventory value.
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

    async def reset_member_cooldown(self, guild_id, discord_id):
        """Clear both platform timers while preserving collection and receipts."""
        async with self.lock(guild_id):
            group = self.config.guild_from_id(guild_id)
            state = await group.collections()
            data = await self._discord_collection(state, guild_id, discord_id)
            data["last_pull"] = 0
            data["last_pulls"] = {"discord": 0, "twitch": 0}
            await group.collections.set(state)

    @crate.command(name="resetcooldown", aliases=["resetcd"])
    @commands.mod_or_permissions(manage_messages=True)
    async def resetcooldown(self, ctx, member: Optional[discord.Member] = None):
        """Moderators: resetcooldown [member]; defaults to yourself.

        Clears Discord and linked Twitch cooldowns. Inventory, value, pull counts,
        and duplicate-event receipts remain unchanged.
        """
        member = member or ctx.author
        await self.reset_member_cooldown(ctx.guild.id, member.id)
        await ctx.send(f"Crate cooldown reset for {member.mention} (Discord and linked Twitch).",
                       allowed_mentions=discord.AllowedMentions.none())

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
    async def leaderboard(self, ctx, crate_name: Optional[str] = None):
        """Show crate positions, or the detailed leaderboard for a named crate."""
        await self.show_leaderboard(ctx, crate_name)

    async def show_leaderboard(self, ctx, crate_name=None):
        if not await self.embed_access(ctx):
            return
        async with self.lock(ctx.guild.id):
            tiers = await self.config.guild(ctx.guild).tiers()
            members = await self.config.all_members(ctx.guild)
            state = await self.config.guild(ctx.guild).collections()
            members.update({int(uid): data for uid, data in state["discord"].items()})
        current = {member.id: member for member in ctx.guild.members}
        rows = []
        title = "\U0001f3c6 Crates leaderboard"
        if crate_name is not None:
            crate_name = crate_name.lower()
            if crate_name not in tiers:
                await ctx.send("Unknown crate.")
                return
        elif len(tiers) == 1:
            crate_name = next(iter(tiers))

        def crate_ranking(tier):
            catalog = tiers[tier]["items"]
            collectors = []
            for uid, data in members.items():
                if uid not in current:
                    continue
                owned = {name: qty for name, qty in data["inventory"].items()
                         if qty > 0 and name in catalog}
                if not owned:
                    continue
                collectors.append((uid, {
                    "items": sum(owned.values()),
                    "value": sum(catalog[name]["value"] * qty for name, qty in owned.items()),
                    "pulls": data.get("crate_stats", {}).get(tier, {}).get("pulls", 0),
                }))
            return sorted(collectors, key=lambda row: (-row[1]["value"], -row[1]["pulls"], row[0]))

        if crate_name is None and len(tiers) > 1:
            rankings = {tier: crate_ranking(tier) for tier in sorted(tiers)}
            positions = {uid: [] for standings in rankings.values() for uid, _ in standings}
            for tier, standings in rankings.items():
                label = discord.utils.escape_markdown(tier)
                ranks = {uid: rank for rank, (uid, _) in enumerate(standings, 1)}
                for uid in positions:
                    rank = f"#{ranks[uid]}" if uid in ranks else "Unranked"
                    positions[uid].append(f"{label} **{rank}**")
            lines = [f"**{discord.utils.escape_markdown(current[uid].display_name)}**\n"
                     + " · ".join(positions[uid]) for uid in positions]
            await self.send_collection(ctx, title, lines or ["No matching items in member inventories yet."],
                                       "Positions use the current value of owned items in each crate.")
            return
        if crate_name is not None:
            rows = crate_ranking(crate_name)
            title = f"\U0001f3c6 {crate_name} leaderboard"

        medals = ("\U0001f947", "\U0001f948", "\U0001f949")
        lines = []
        for position, (uid, data) in enumerate(rows, 1):
            badge = medals[position - 1] if position <= 3 else f"**#{position}**"
            name = discord.utils.escape_markdown(current[uid].display_name)
            lines.append(
                f"{badge} **{name}**\n"
                f"{data['items']:,} items · {data['value']:,} inventory value"
            )
        summary = f"**{len(rows):,}** collectors | Ranked by inventory value"
        await self.send_collection(ctx, title, lines or ["No matching items in member inventories yet."], summary)


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
        lines = [f"Pulls enabled: {settings['enabled']} | Cooldown: {settings['cooldown']:,} seconds"]
        channel_id = settings.get("command_channel")
        lines.append(f"Crate command channel: <#{channel_id}>" if channel_id else "Crate command channel: any channel")
        schedule = settings["cooldown_schedule"]
        if schedule["mode"] == "daily":
            lines[0] = f"Pulls enabled: {settings['enabled']} | Daily reset: {schedule['time']} {schedule['zone']}"
        else:
            lines[0] += f" ({schedule['mode']})"
        lines.append(f"Discord/Twitch cooldown shared: {settings.get('shared_cooldown', True)}")
        lines.append(f"Twitch pull mode: {settings.get('twitch_mode', 'points')} | "
                     f"Chat command: {settings.get('twitch_command', '!crate pull')}")
        bonuses = settings.get("luck_roles", {})
        lines.append("Role luck bonuses (highest applies): " + (
            ", ".join(f"<@&{role_id}> +{bonus:g}%" for role_id, bonus in bonuses.items()) or "none"))
        for key, tier in sorted(tiers.items()):
            lines.append(f"{tier.get('emoji', CRATE_EMOJI)} **{key}** - selectable crate | legacy random-store weight {tier['weight']:g}")
            item_total = sum(i["weight"] for i in tier["items"].values())
            for name, item in sorted(tier["items"].items()):
                lines.append(f"  {discord.utils.escape_markdown(name)} - value {item['value']:,}, "
                             f"weight {item['weight']:g}, {item['weight'] / item_total * 100:.2f}% within tier"
                             + (" [empty pull]" if item.get("empty") else "")
                             + (" [image]" if item.get("image") else "")
                             + (f" [{len(item.get('reward_commands', []))} reward commands]" if item.get("reward_commands") else ""))
            if not tier["items"]:
                lines.append("  No items; excluded from pulls.")
        if not tiers:
            lines.append("No tiers configured. Add a tier, then add its items.")
        await self.send_pages(ctx, "\n".join(lines))

    @crateset.command(name="tier")
    async def set_tier(self, ctx, tier: str, weight: float, emoji: Optional[str] = None):
        """Add/update a tier: crateset tier <tier> <weight> [emoji].

        Crate names use 1-32 letters, digits, or hyphens. Members choose the crate;
        this weight is retained for legacy random Store openings and inventory order.
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

    @crateset.command(name="cooldownmode")
    async def cooldownmode(self, ctx, mode: str, clock: Optional[str] = None, zone: str = "UTC"):
        """Select user, global, or daily HH:MM [timezone]."""
        mode = mode.lower()
        schedule = {"mode": mode}
        if mode == "daily":
            if clock is None or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", clock):
                await ctx.send("Use cooldownmode daily HH:MM [timezone], with a 24-hour time.")
                return
            try:
                reset_timezone(zone)
            except (ZoneInfoNotFoundError, ValueError):
                await ctx.send("Unknown timezone. Use UTC, EST, or an IANA name like America/Toronto.")
                return
            schedule.update(time=clock, zone=zone)
        elif mode not in {"user", "global"} or clock is not None:
            await ctx.send("Choose user, global, or daily HH:MM [timezone].")
            return
        async with self.lock(ctx.guild.id):
            await self.config.guild(ctx.guild).cooldown_schedule.set(schedule)
        detail = f" at {clock} {zone}" if mode == "daily" else ""
        await ctx.send(f"Crate cooldown mode set to {mode}{detail}.")

    @crateset.command(name="resetglobalcooldown")
    async def resetglobalcooldown(self, ctx):
        """Clear the server-wide crate cooldown for Discord and Twitch."""
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).collections() as state:
                state.pop("global_pull_times", None)
        await ctx.send("Global crate cooldown reset.")

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

    @crateset.command(name="luck")
    async def luck(self, ctx, role: discord.Role, percent: float):
        """Set a role's rare-item weight bonus: crateset luck @role 25.

        Range 0-1000%. Highest matching role applies; bonuses do not stack.
        Zero removes the role bonus. Preview actual chances with luckshow.
        """
        if not math.isfinite(percent) or not 0 <= percent <= 1000:
            await ctx.send("Choose a luck bonus from 0 to 1,000 percent.")
            return
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).luck_roles() as roles:
                if percent == 0:
                    roles.pop(str(role.id), None)
                else:
                    roles[str(role.id)] = percent
        await ctx.send(f"Luck bonus for {role.mention}: {percent:g}%. Highest matching role applies.",
                       allowed_mentions=discord.AllowedMentions.none())

    @crateset.command(name="luckremove")
    async def luckremove(self, ctx, role: discord.Role):
        """Remove a role's rarity bonus."""
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).luck_roles() as roles:
                roles.pop(str(role.id), None)
        await ctx.send("Role luck bonus removed.")

    @crateset.command(name="luckshow")
    async def luckshow(self, ctx, member: Optional[discord.Member] = None, crate_name: Optional[str] = None):
        """Preview item odds: luckshow [member] [crate name]."""
        member = member or ctx.author
        settings = await self.config.guild(ctx.guild).all()
        bonus = self.member_luck(ctx.guild.id, member.id, settings)
        try:
            name = resolve_crate(settings["tiers"], crate_name)
        except ValueError as error:
            await ctx.send(str(error), allowed_mentions=discord.AllowedMentions.none())
            return
        crate = settings["tiers"][name]
        base, boosted = item_weights(crate), item_weights(crate, bonus)
        base_total, boosted_total = sum(base.values()), sum(boosted.values())
        lines = [f"{name} crate odds for {discord.utils.escape_markdown(member.display_name)}: +{bonus:g}% luck"]
        for item in sorted(base, key=base.get):
            lines.append(f"**{discord.utils.escape_markdown(item)}**: {base[item] / base_total * 100:.4f}% base -> "
                         f"{boosted[item] / boosted_total * 100:.4f}% with luck")
        lines.append("Highest matching role bonus applies to rarer items within this crate.")
        await self.send_pages(ctx, "\n".join(lines))

    @crateset.command(name="channel")
    async def command_channel(self, ctx, channel: Optional[discord.TextChannel] = None):
        """Restrict crate commands to a channel; omit the channel to allow anywhere.

        Examples: crateset channel #games | crateset channel
        Applies to all crate subcommands, including moderator give/remove.
        Configuration commands and Twitch integration calls are unaffected.
        """
        if channel is not None and channel.guild.id != ctx.guild.id:
            await ctx.send("Choose a text channel in this server.")
            return
        if channel is not None:
            perms = channel.permissions_for(ctx.guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                await ctx.send("I need View Channel, Send Messages, and Embed Links in that channel.")
                return
        async with self.lock(ctx.guild.id):
            await self.config.guild(ctx.guild).command_channel.set(channel.id if channel else None)
        await ctx.send(f"Crate commands are now restricted to {channel.mention}." if channel else
                       "Crate commands can now be used in any channel.",
                       allowed_mentions=discord.AllowedMentions.none())

    @crateset.command(name="itemcommand")
    @commands.is_owner()
    async def itemcommand(self, ctx, tier: str, name: str, *, command: str):
        """Owner only: itemcommand <tier> "Item Name" <command without prefix>.

        Appends a reward command. Placeholders: {user}, {user_id}, {guild_id}.
        Commands execute as the configuring owner with normal command checks.
        No reward commands are installed by default. Up to five per item.
        """
        command = command.strip()
        if not 1 <= len(command) <= 1000 or any(ord(c) < 32 for c in command):
            await ctx.send("Use a single-line command of 1–1,000 characters, without its prefix.")
            return
        if self.bot.get_command(command.split()[0]) is None:
            await ctx.send("Command not found. Enter an existing bot command without its prefix.")
            return
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).tiers() as tiers:
                item = tiers.get(tier.lower(), {}).get("items", {}).get(name.strip())
                if item is None:
                    await ctx.send("Item not found. Quote item names containing spaces.")
                    return
                if item.get("empty"):
                    await ctx.send("Reward commands require a collectible item, not an empty-pull reward.")
                    return
                actions = item.setdefault("reward_commands", [])
                if len(actions) >= 5:
                    await ctx.send("An item can have up to five reward commands. Remove one first.")
                    return
                actions.append({"command": command, "executor_id": ctx.author.id,
                                "channel_id": ctx.channel.id, "message_id": ctx.message.id,
                                "prefix": ctx.prefix})
        await ctx.send("Reward command added. It will run on future pulls of this item only.")

    @crateset.command(name="itemcommands")
    @commands.is_owner()
    async def itemcommands(self, ctx, tier: str, *, name: str):
        """Owner only: list an item's reward commands and their removal numbers."""
        tiers = await self.config.guild(ctx.guild).tiers()
        item = tiers.get(tier.lower(), {}).get("items", {}).get(name.strip())
        if item is None:
            await ctx.send("Item not found.")
            return
        lines = [f"{index}. {discord.utils.escape_markdown(action['command'])}"
                 for index, action in enumerate(item.get("reward_commands", []), 1)]
        await self.send_pages(ctx, "\n".join(lines) or "No reward commands configured for this item.")

    @crateset.command(name="removeitemcommand")
    @commands.is_owner()
    async def removeitemcommand(self, ctx, tier: str, index: int, *, name: str):
        """Owner only: removeitemcommand <tier> <command number> <item name>."""
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).tiers() as tiers:
                item = tiers.get(tier.lower(), {}).get("items", {}).get(name.strip())
                actions = item.get("reward_commands", []) if item else []
                if not 1 <= index <= len(actions):
                    await ctx.send("Command number not found. Use crateset itemcommands to list them.")
                    return
                actions.pop(index - 1)
        await ctx.send("Reward command removed.")

    @crateset.command(name="clearitemcommands")
    @commands.is_owner()
    async def clearitemcommands(self, ctx, tier: str, *, name: str):
        """Owner only: clear all commands from an item."""
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).tiers() as tiers:
                item = tiers.get(tier.lower(), {}).get("items", {}).get(name.strip())
                if item is None:
                    await ctx.send("Item not found.")
                    return
                item["reward_commands"] = []
        await ctx.send("All reward commands cleared for this item.")

    @crateset.command(name="itememoji")
    async def itememoji(self, ctx, tier: str, emoji: str, *, name: str):
        """Set an item's reel emoji: itememoji <crate> <emoji> <item name>."""
        if not self.valid_emoji(emoji):
            await ctx.send("Use a Unicode emoji or a Discord custom emoji.")
            return
        async with self.lock(ctx.guild.id):
            async with self.config.guild(ctx.guild).tiers() as tiers:
                item = tiers.get(tier.lower(), {}).get("items", {}).get(name.strip())
                if item is None:
                    await ctx.send("Item not found.")
                    return
                item["emoji"] = emoji
        await ctx.send("Item emoji saved.")
