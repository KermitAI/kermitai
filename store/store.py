"""A standalone shop using Red's bank and Crates collections."""
import asyncio
import copy
import logging
import re
import uuid

import discord
from redbot.core import Config, bank, commands
from redbot.core.errors import BalanceTooHigh
from redbot.core.utils.chat_formatting import pagify

from .transactions import PurchaseEngine, StoreError, TERMINAL

log = logging.getLogger("red.store")


class PrivateView(discord.ui.View):
    def __init__(self, cog, ctx, timeout=120):
        super().__init__(timeout=timeout)
        self.cog, self.ctx, self.message = cog, ctx, None

    async def interaction_check(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Open your own store to shop.", ephemeral=True)
            return False
        if self.cog.bot.get_cog("Store") is not self.cog:
            await interaction.response.send_message("The store was reloaded. Open it again.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.cog.views.discard(self)

    async def on_error(self, interaction, error, item):
        log.error("Store interface failed", exc_info=(type(error), error, error.__traceback__))
        text = "The store could not finish that request. Check store orders before retrying a purchase."
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)


class CategoryChoice(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="Browse a category", options=[
            discord.SelectOption(label="All listings", value="all"),
            discord.SelectOption(label="Guaranteed items", value="item"),
            discord.SelectOption(label="Crate openings", value="crate"),
        ], row=0)

    async def callback(self, interaction):
        self.view.category, self.view.page = self.values[0], 0
        await interaction.response.defer()
        await self.view.refresh()


class StoreView(PrivateView):
    def __init__(self, cog, ctx):
        super().__init__(cog, ctx)
        self.category, self.page, self.selected = "all", 0, None
        self.add_item(CategoryChoice())
        self.previous = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, row=1)
        self.buy = discord.ui.Button(label="Buy", style=discord.ButtonStyle.success, row=1)
        self.next = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, row=1)
        self.previous.callback, self.buy.callback, self.next.callback = self.back, self.checkout, self.forward
        for button in (self.previous, self.buy, self.next):
            self.add_item(button)

    async def render(self):
        state = await self.cog.config.guild(self.ctx.guild).state()
        rows = sorted(((key, value) for key, value in state["listings"].items()
                       if self.category == "all" or value["kind"] == self.category), key=lambda row: row[0])
        self.page = min(self.page, max(0, len(rows) - 1))
        self.previous.disabled, self.next.disabled = self.page == 0, self.page >= len(rows) - 1
        balance = await bank.get_balance(self.ctx.author)
        currency = await bank.get_currency_name(self.ctx.guild)
        embed = discord.Embed(title="Store", colour=await self.ctx.embed_colour())
        embed.set_author(name=self.ctx.author.display_name, icon_url=str(self.ctx.author.display_avatar.url))
        embed.add_field(name="Your balance", value=f"{balance:,} {discord.utils.escape_markdown(currency)}", inline=False)
        self.selected = None
        if rows:
            listing_id, listing = rows[self.page]
            self.selected = (listing_id, copy.deepcopy(listing))
            embed.description = f"**{discord.utils.escape_markdown(listing['title'])}**\n{discord.utils.escape_markdown(listing['description'])}"
            embed.add_field(name="Price", value=f"{listing['price']:,} {discord.utils.escape_markdown(currency)}")
            embed.add_field(name="Stock", value="Unlimited" if listing["stock"] < 0 else str(listing["stock"]))
            embed.add_field(name="Reward", value=(f"{listing['quantity']:,} x {discord.utils.escape_markdown(listing['item'])}"
                                                    if listing["kind"] == "item" else f"One {listing['tier']} crate opening" if listing.get("tier") else "One random crate opening"), inline=False)
            preview = await self.cog.preview(self.ctx.guild.id, listing)
            if preview.get("image"):
                embed.set_image(url=preview["image"])
            if preview.get("emoji"):
                embed.description = preview["emoji"] + " " + embed.description
            if listing["kind"] == "crate":
                embed.description += "\n\nUses current Crates odds and role luck. May contain an empty reward if configured."
            self.buy.disabled = not state["enabled"] or listing["stock"] == 0 or balance < listing["price"]
            note = "Sold out" if listing["stock"] == 0 else ("Insufficient balance" if balance < listing["price"] else "Confirmation required")
            embed.set_footer(text=f"{self.page + 1}/{len(rows)} | {listing_id} | {note}")
        else:
            embed.description = "No listings in this category yet."
            self.buy.disabled = True
            embed.set_footer(text="Store | Your economy balance is used for purchases")
        if not state["enabled"]:
            embed.description = "**Store closed**\n\n" + embed.description
        return embed

    async def refresh(self):
        if self.message:
            await self.message.edit(embed=await self.render(), view=self)

    async def back(self, interaction):
        self.page = max(0, self.page - 1)
        await interaction.response.defer()
        await self.refresh()

    async def forward(self, interaction):
        self.page += 1
        await interaction.response.defer()
        await self.refresh()

    async def checkout(self, interaction):
        if self.selected is None:
            await interaction.response.send_message("Select a listing first.", ephemeral=True)
            return
        listing_id, listing = self.selected
        currency = await bank.get_currency_name(self.ctx.guild)
        view = ConfirmPurchase(self.cog, self.ctx, listing_id, listing)
        self.cog.views.add(view)
        embed = discord.Embed(title="Confirm purchase", colour=await self.ctx.embed_colour(),
                              description=f"Buy **{discord.utils.escape_markdown(listing['title'])}** for **{listing['price']:,} {discord.utils.escape_markdown(currency)}**?")
        embed.set_footer(text="One purchase. Your normal crate cooldown and pull count stay unchanged.")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


class ConfirmPurchase(PrivateView):
    def __init__(self, cog, ctx, listing_id, listing):
        super().__init__(cog, ctx, timeout=60)
        self.listing_id, self.listing = listing_id, listing
        self.order_id, self.used = uuid.uuid4().hex, False
        confirm = discord.ui.Button(label="Confirm purchase", style=discord.ButtonStyle.success)
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        confirm.callback, cancel.callback = self.confirm, self.cancel
        self.add_item(confirm)
        self.add_item(cancel)

    async def cancel(self, interaction):
        if self.used:
            await interaction.response.send_message("This confirmation has already been used.", ephemeral=True)
            return
        self.used = True
        self.stop()
        self.cog.views.discard(self)
        await interaction.response.edit_message(content="Purchase cancelled. Nothing was charged.", embed=None, view=None)

    async def confirm(self, interaction):
        if self.used:
            await interaction.response.send_message("This confirmation has already been used. Check store orders.", ephemeral=True)
            return
        self.used = True
        self.stop()
        self.cog.views.discard(self)
        await interaction.response.defer()
        try:
            await self.cog.access(self.ctx)
            member = self.ctx.guild.get_member(interaction.user.id)
            if member is None:
                raise StoreError("You must still be a member of this server to buy.")
            order = await self.cog.engine.purchase(member, self.ctx.channel.id, self.listing_id,
                                                    self.listing["revision"], self.order_id)
        except StoreError as error:
            await interaction.edit_original_response(content=str(error), embed=None, view=None)
            return
        await interaction.edit_original_response(content=f"Purchase complete! Order: {order['id']}.", embed=None, view=None)
        if not order.get("duplicate"):
            try:
                await self.cog.reveal(self.ctx, order)
            except Exception:
                log.exception("Store reveal failed for completed order %s", order["id"])
                await interaction.followup.send("Your reward is saved in your Crates inventory, but its reveal could not be posted.", ephemeral=True)


class Store(commands.Cog):
    """Spend Red bank currency on Crates collectibles and extra openings."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=981376420017, force_registration=True)
        self.config.register_guild(state={"enabled": True, "channel": None, "listings": {}, "orders": {}})
        self.locks, self.views = {}, set()
        self.engine = PurchaseEngine(self.config, bank, BalanceTooHigh, lambda: bot.get_cog("Crates"), self.lock)

    def lock(self, guild_id):
        return self.locks.setdefault(guild_id, asyncio.Lock())

    async def cog_unload(self):
        for view in self.views:
            view.stop()
        self.views.clear()

    async def red_delete_data_for_user(self, *, requester, user_id):
        for gid in await self.config.all_guilds():
            async with self.lock(gid):
                state = await self.config.guild_from_id(gid).state()
                state["orders"] = {key: order for key, order in state["orders"].items() if order["buyer_id"] != user_id}
                await self.config.guild_from_id(gid).state.set(state)

    async def access(self, ctx):
        if await self.bot.cog_disabled_in_guild(self, ctx.guild):
            raise StoreError("Store is disabled in this server.")
        perms = ctx.channel.permissions_for(ctx.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            raise StoreError("I need View Channel, Send Messages, and Embed Links to open the store.")
        member = ctx.guild.get_member(ctx.author.id)
        if member is None or not ctx.channel.permissions_for(member).view_channel:
            raise StoreError("You no longer have access to this store channel.")
        state = await self.config.guild(ctx.guild).state()
        if state["channel"] and state["channel"] != ctx.channel.id:
            raise StoreError(f"Use the store in <#{state['channel']}>.")

    async def preview(self, guild_id, listing):
        crates = self.bot.get_cog("Crates")
        if crates is None or listing["kind"] != "item":
            return {}
        tiers = await crates.config.guild_from_id(guild_id).tiers()
        entry = tiers.get(listing["tier"], {})
        item = entry.get("items", {}).get(listing["item"], {})
        return {"emoji": entry.get("emoji"), "image": item.get("image")}

    async def reveal(self, ctx, order):
        crates = self.bot.get_cog("Crates")
        if crates is None:
            await ctx.send("Purchase complete. Your reward is saved in your Crates inventory.")
            return
        if order["listing"]["kind"] == "crate":
            tiers = await crates.config.guild(ctx.guild).tiers()
            await crates.animate_pull(ctx, order["result"], tiers)
        else:
            result = order["result"]
            embed = discord.Embed(title="Purchase complete", colour=await ctx.embed_colour(),
                                  description=f"{ctx.author.mention} received **{result['quantity']:,} x {discord.utils.escape_markdown(result['name'])}**!")
            if result.get("image"):
                embed.set_image(url=result["image"])
            embed.set_footer(text="Added to your Crates inventory. Thank you for shopping!")
            await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def pages(self, ctx, text):
        for page in pagify(text, page_length=1800):
            await ctx.send(page, allowed_mentions=discord.AllowedMentions.none())

    @commands.guild_only()
    @commands.group(name="store", invoke_without_command=True)
    async def store(self, ctx):
        """Browse the shop using your existing economy balance."""
        try:
            await self.access(ctx)
        except StoreError as error:
            await ctx.send(str(error), allowed_mentions=discord.AllowedMentions.none())
            return
        view = StoreView(self, ctx)
        self.views.add(view)
        view.message = await ctx.send(embed=await view.render(), view=view, allowed_mentions=discord.AllowedMentions.none())

    @store.command(name="orders")
    async def orders(self, ctx):
        """Show your recent orders and any purchases needing attention."""
        state = await self.config.guild(ctx.guild).state()
        rows = sorted((order for order in state["orders"].values() if order["buyer_id"] == ctx.author.id),
                      key=lambda order: order["created"], reverse=True)
        pending = [order for order in rows if order["status"] not in TERMINAL]
        recent = [order for order in rows if order["status"] in TERMINAL][:10]
        await self.pages(ctx, "\n".join(f"`{o['id']}` | {o['status']} | {o['price']:,} | {discord.utils.escape_markdown(o['listing']['title'])}"
                                        for o in pending + recent) or "You have no Store orders yet.")

    @store.command(name="refund")
    async def refund(self, ctx, order_id: str):
        """Claim a previously blocked refund after making room in your bank balance."""
        try:
            await self.engine.refund(ctx.author, order_id)
        except StoreError as error:
            await ctx.send(str(error), allowed_mentions=discord.AllowedMentions.none())

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.group(name="storeset", invoke_without_command=True)
    async def storeset(self, ctx):
        """Manage the separate Store catalog, prices, stock, and availability."""
        await ctx.send_help()

    async def add_listing(self, ctx, listing_id, price, kind, title, tier=None, quantity=1, item=None):
        if not re.fullmatch(r"[a-z0-9-]{1,32}", listing_id) or not 1 <= price <= 1_000_000_000:
            raise StoreError("Use a lowercase listing ID of 1–32 letters/digits/hyphens and a price from 1 to 1,000,000,000.")
        if not 1 <= quantity <= 1000 or not 1 <= len(title) <= 100 or any(ord(c) < 32 for c in title):
            raise StoreError("Use a single-line name of 1–100 characters and quantity 1–1,000.")
        crates = self.bot.get_cog("Crates")
        if crates is None or not hasattr(crates, "deliver_store_purchase"):
            raise StoreError("Load the updated Crates cog first.")
        tiers = await crates.config.guild(ctx.guild).tiers()
        if kind == "item":
            reward = tiers.get(tier, {}).get("items", {}).get(item)
            if reward is None or reward.get("empty"):
                raise StoreError("Choose an existing collectible from that Crates tier, using its exact name.")
        elif not any(t["items"] for t in tiers.values()):
            raise StoreError("Configure at least one populated Crates tier first.")
        async with self.lock(ctx.guild.id):
            state = await self.config.guild(ctx.guild).state()
            if listing_id not in state["listings"] and len(state["listings"]) >= 100:
                raise StoreError("A server can have up to 100 Store listings.")
            old = state["listings"].get(listing_id, {})
            state["listings"][listing_id] = {"kind": kind, "title": title, "description": old.get("description", ""),
                                             "price": price, "tier": tier, "item": item, "quantity": quantity,
                                             "stock": old.get("stock", -1), "revision": uuid.uuid4().hex}
            await self.config.guild(ctx.guild).state.set(state)

    @storeset.command(name="item")
    async def item(self, ctx, listing_id: str, price: int, tier: str, quantity: int, *, name: str):
        """List a guaranteed collectible: ID price tier quantity item name."""
        try:
            await self.add_listing(ctx, listing_id, price, "item", name.strip(), tier.lower(), quantity, name.strip())
        except StoreError as error:
            await ctx.send(str(error))
            return
        await ctx.send("Item listing saved.")

    @storeset.command(name="crate")
    async def crate(self, ctx, listing_id: str, price: int, *, title: str):
        """List one extra random opening: ID price display name."""
        try:
            await self.add_listing(ctx, listing_id, price, "crate", title.strip())
        except StoreError as error:
            await ctx.send(str(error))
            return
        await ctx.send("Crate-opening listing saved.")

    @storeset.command(name="cratefor")
    async def cratefor(self, ctx, listing_id: str, price: int, crate_name: str, *, title: str):
        """List a named crate opening: ID price crate-name display name."""
        crates = self.bot.get_cog("Crates")
        if crates is None:
            await ctx.send("Load Crates first.")
            return
        tiers = await crates.config.guild(ctx.guild).tiers()
        entry = tiers.get(crate_name.lower())
        if not entry or not entry["items"]:
            await ctx.send("Choose an existing crate containing items.")
            return
        try:
            await self.add_listing(ctx, listing_id, price, "crate", title.strip(), crate_name.lower())
        except StoreError as error:
            await ctx.send(str(error))
            return
        await ctx.send("Named crate-opening listing saved.")

    async def edit_listing(self, ctx, listing_id, field, value):
        async with self.lock(ctx.guild.id):
            state = await self.config.guild(ctx.guild).state()
            listing = state["listings"].get(listing_id)
            if listing is None:
                await ctx.send("Listing not found.")
                return
            listing[field], listing["revision"] = value, uuid.uuid4().hex
            await self.config.guild(ctx.guild).state.set(state)
        await ctx.send("Listing updated. Existing purchase confirmations must be reopened.")

    @storeset.command(name="price")
    async def price(self, ctx, listing_id: str, price: int):
        """Change a listing's price."""
        if not 1 <= price <= 1_000_000_000:
            await ctx.send("Choose a price from 1 to 1,000,000,000.")
            return
        await self.edit_listing(ctx, listing_id, "price", price)

    @storeset.command(name="stock")
    async def stock(self, ctx, listing_id: str, stock: int):
        """Set remaining purchases; -1 unlimited, 0 sold out."""
        if not -1 <= stock <= 1_000_000:
            await ctx.send("Choose -1 for unlimited, or 0–1,000,000 remaining purchases.")
            return
        await self.edit_listing(ctx, listing_id, "stock", stock)

    @storeset.command(name="description")
    async def description(self, ctx, listing_id: str, *, text: str):
        """Set listing description; 'none' clears it."""
        if len(text) > 500:
            await ctx.send("Descriptions may contain up to 500 characters.")
            return
        await self.edit_listing(ctx, listing_id, "description", "" if text.lower() == "none" else text)

    @storeset.command(name="remove")
    async def remove(self, ctx, listing_id: str):
        """Remove a listing from future purchases."""
        async with self.lock(ctx.guild.id):
            state = await self.config.guild(ctx.guild).state()
            removed = state["listings"].pop(listing_id, None)
            await self.config.guild(ctx.guild).state.set(state)
        await ctx.send("Listing removed." if removed else "Listing not found.")

    @storeset.command(name="enabled")
    async def enabled(self, ctx, enabled: bool):
        """Open or close the shop."""
        async with self.lock(ctx.guild.id):
            state = await self.config.guild(ctx.guild).state()
            state["enabled"] = enabled
            await self.config.guild(ctx.guild).state.set(state)
        await ctx.send("Store opened." if enabled else "Store closed.")

    @storeset.command(name="channel")
    async def channel(self, ctx, channel: discord.TextChannel = None):
        """Set the store browsing/purchase channel, or omit to allow anywhere."""
        if channel and channel.guild.id != ctx.guild.id:
            await ctx.send("Choose a text channel in this server.")
            return
        async with self.lock(ctx.guild.id):
            state = await self.config.guild(ctx.guild).state()
            state["channel"] = channel.id if channel else None
            await self.config.guild(ctx.guild).state.set(state)
        await ctx.send("Store channel saved." if channel else "Store can be opened in any channel.")

    @storeset.command(name="show")
    async def show(self, ctx):
        """Show settings and all listing IDs, prices, and stock."""
        state = await self.config.guild(ctx.guild).state()
        currency = await bank.get_currency_name(ctx.guild)
        lines = [f"Store enabled: {state['enabled']} | Channel: " + (f"<#{state['channel']}>" if state["channel"] else "any")]
        lines += [f"**{key}** | {discord.utils.escape_markdown(row['title'])} | {row['price']:,} {discord.utils.escape_markdown(currency)} | stock {row['stock']}"
                  for key, row in sorted(state["listings"].items())]
        await self.pages(ctx, "\n".join(lines))

    @storeset.command(name="orders")
    async def pending_orders(self, ctx):
        """Show orders needing attention, without altering money or rewards."""
        state = await self.config.guild(ctx.guild).state()
        rows = [f"`{o['id']}` | member {o['buyer_id']} | {o['status']} | {o['price']:,}"
                for o in state["orders"].values() if o["status"] not in TERMINAL]
        await self.pages(ctx, "\n".join(rows) or "No orders need attention.")

    @storeset.command(name="recover")
    @commands.is_owner()
    async def recover(self, ctx, order_id: str):
        """Owner: retry a charged/delivering order's idempotent delivery."""
        state = await self.config.guild(ctx.guild).state()
        order = state["orders"].get(order_id)
        member = ctx.guild.get_member(order["buyer_id"]) if order else None
        if member is None:
            await ctx.send("Order or current server member not found.")
            return
        try:
            await self.engine.recover(member, order_id)
        except StoreError as error:
            await ctx.send(str(error))
            return
        await ctx.send("Purchase delivery recovered. The member's inventory has the reward.")

    @storeset.command(name="resolve")
    @commands.is_owner()
    async def resolve(self, ctx, order_id: str, status: str):
        """Owner: after manual bank/reward reconciliation, mark complete/cancelled.

        This command moves no currency and delivers no items. Cancelled releases
        reserved stock. Use only after checking/correcting the actual balances.
        """
        if status not in {"complete", "cancelled"}:
            await ctx.send("Choose complete or cancelled, after manually reconciling the order.")
            return
        async with self.lock(ctx.guild.id):
            state = await self.config.guild(ctx.guild).state()
            order = state["orders"].get(order_id)
            if not order or order["status"] in TERMINAL:
                await ctx.send("No unresolved order with that ID.")
                return
            if status == "cancelled":
                self.engine.release_stock(state, order)
            order["status"] = status
            await self.config.guild(ctx.guild).state.set(state)
        await ctx.send("Order tracking updated. No currency or inventory was changed.")
