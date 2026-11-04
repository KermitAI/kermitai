"""Purchase coordination. Bank and inventory writes use a durable order journal."""
import asyncio
import copy
import logging
import time

log = logging.getLogger("red.store")
TERMINAL = {"complete", "failed", "refunded", "cancelled"}


class StoreError(ValueError):
    pass


class PurchaseEngine:
    def __init__(self, config, bank, balance_error, get_crates, guild_lock):
        self.config = config
        self.bank = bank
        self.balance_error = balance_error
        self.get_crates = get_crates
        self.guild_lock = guild_lock
        self.buyers = {}

    def buyer_lock(self, member):
        # Serialize across guilds too when Red uses a global bank.
        return self.buyers.setdefault(member.id, asyncio.Lock())

    async def save(self, guild_id, state):
        await self.config.guild_from_id(guild_id).state.set(state)

    @staticmethod
    def release_stock(state, order):
        if order.get("reserved"):
            listing = state["listings"].get(order["listing_id"])
            if listing and listing["revision"] == order["listing"]["revision"] and listing["stock"] >= 0:
                listing["stock"] += 1
            order["reserved"] = False

    async def purchase(self, member, channel_id, listing_id, revision, order_id):
        gid = member.guild.id
        async with self.buyer_lock(member), self.guild_lock(gid):
            state = await self.config.guild_from_id(gid).state()
            existing = state["orders"].get(order_id)
            if existing:
                if existing["buyer_id"] != member.id:
                    raise StoreError("This order belongs to another member.")
                if existing["status"] == "complete":
                    return dict(existing, duplicate=True)
                raise StoreError(f"Order {order_id} is {existing['status']}; it will not charge again.")
            if any(o["buyer_id"] == member.id and o["status"] not in TERMINAL for o in state["orders"].values()):
                raise StoreError("You have an unresolved order. Use store orders before buying again.")
            if not state["enabled"]:
                raise StoreError("The store is currently closed.")
            if state["channel"] and state["channel"] != channel_id:
                raise StoreError(f"Use the store in <#{state['channel']}>.")
            listing = state["listings"].get(listing_id)
            if not listing or listing["revision"] != revision:
                raise StoreError("This listing changed. Reopen the store to see its current price.")
            if listing["stock"] == 0:
                raise StoreError("This listing is sold out.")
            crates = self.get_crates()
            if crates is None or not hasattr(crates, "deliver_store_purchase"):
                raise StoreError("Load the updated Crates cog before making purchases.")
            order = {"id": order_id, "buyer_id": member.id, "listing_id": listing_id,
                     "listing": copy.deepcopy(listing), "price": listing["price"],
                     "global_bank": await self.bank.is_global(), "created": time.time(),
                     "status": "charging", "reserved": listing["stock"] > 0}
            state["orders"][order_id] = order
            if order["reserved"]:
                listing["stock"] -= 1
            await self.save(gid, state)
            try:
                await self.bank.withdraw_credits(member, order["price"])
            except ValueError:
                order["status"] = "failed"
                self.release_stock(state, order)
                await self.save(gid, state)
                raise StoreError("You do not have enough currency for this purchase.") from None
            except Exception:
                log.exception("Store charge uncertain for order %s", order_id)
                raise StoreError(f"Order {order_id} needs owner review; it will not charge again.") from None
            order["status"] = "charged"
            await self.save(gid, state)
            return await self.deliver(member, state, order, crates)

    async def deliver(self, member, state, order, crates):
        order["status"] = "delivering"
        await self.save(member.guild.id, state)
        listing = order["listing"]
        try:
            result = await crates.deliver_store_purchase(
                member.guild.id, member.id, order["id"], listing["kind"],
                listing.get("tier"), listing.get("item"), listing.get("quantity", 1))
        except ValueError as error:
            # Crates validates before writing. Known rejection is safe to refund.
            order["error"] = str(error)
            return await self.refund_locked(member, state, order)
        except Exception:
            # Delivery may have committed before an I/O failure. Retry the same
            # idempotent delivery via owner recovery; never refund blindly.
            log.exception("Store delivery uncertain for order %s", order["id"])
            raise StoreError(f"Order {order['id']} needs recovery. Your purchase is recorded; do not pay again.") from None
        order["result"] = result
        order["status"] = "complete"
        await self.save(member.guild.id, state)
        return dict(order, duplicate=False)

    async def refund_locked(self, member, state, order):
        if await self.bank.is_global() != order["global_bank"]:
            raise StoreError("Bank mode changed. The bot owner must review this order before refunding.")
        order["status"] = "refunding"
        await self.save(member.guild.id, state)
        try:
            await self.bank.deposit_credits(member, order["price"])
        except self.balance_error:
            order["status"] = "refund_due"
            await self.save(member.guild.id, state)
            raise StoreError(f"Delivery failed. Your balance cap prevents the refund. Spend some currency, then use store refund {order['id']}.") from None
        except Exception:
            log.exception("Store refund uncertain for order %s", order["id"])
            raise StoreError(f"Refund for {order['id']} needs owner review; no automatic retry will risk a double refund.") from None
        order["status"] = "refunded"
        self.release_stock(state, order)
        await self.save(member.guild.id, state)
        raise StoreError(f"The reward could not be delivered. Your {order['price']:,} currency was refunded. Order: {order['id']}.")

    async def refund(self, member, order_id):
        async with self.buyer_lock(member), self.guild_lock(member.guild.id):
            state = await self.config.guild_from_id(member.guild.id).state()
            order = state["orders"].get(order_id)
            if not order or order["buyer_id"] != member.id or order["status"] != "refund_due":
                raise StoreError("No pending refundable order with that ID belongs to you.")
            return await self.refund_locked(member, state, order)

    async def recover(self, member, order_id):
        async with self.buyer_lock(member), self.guild_lock(member.guild.id):
            state = await self.config.guild_from_id(member.guild.id).state()
            order = state["orders"].get(order_id)
            if not order or order["buyer_id"] != member.id or order["status"] not in {"charged", "delivering"}:
                raise StoreError("Only charged/delivering orders can be recovered automatically.")
            if await self.bank.is_global() != order["global_bank"]:
                raise StoreError("Bank mode changed; review this order manually.")
            crates = self.get_crates()
            if crates is None:
                raise StoreError("Load Crates before recovering delivery.")
            return await self.deliver(member, state, order, crates)
