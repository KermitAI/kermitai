"""Transaction boundaries: charge once, reserve stock, deliver once, refund safely."""
import asyncio
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location("store_transactions", Path(__file__).parents[1] / "transactions.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BalanceTooHigh(Exception):
    pass


class Value:
    def __init__(self, data):
        self.data = data

    async def __call__(self):
        return copy.deepcopy(self.data)

    async def set(self, value):
        self.data = copy.deepcopy(value)


class Config:
    def __init__(self, data):
        self.group = SimpleNamespace(state=Value(data))

    def guild_from_id(self, guild_id):
        return self.group


class Bank:
    def __init__(self):
        self.balance = 1000
        self.cap = 10000
        self.global_bank = False
        self.charges, self.refunds = 0, 0
        self.uncertain = False

    async def is_global(self):
        return self.global_bank

    async def withdraw_credits(self, member, amount):
        await asyncio.sleep(0)
        if self.balance < amount:
            raise ValueError("insufficient")
        self.balance -= amount
        self.charges += 1
        if self.uncertain:
            raise RuntimeError("connection interrupted after debit")

    async def deposit_credits(self, member, amount):
        if self.balance + amount > self.cap:
            raise BalanceTooHigh()
        self.balance += amount
        self.refunds += 1


class Crates:
    def __init__(self):
        self.receipts = {}
        self.grants = 0
        self.reject = False
        self.fail_after = False

    async def deliver_store_purchase(self, gid, uid, order_id, *args):
        if order_id in self.receipts:
            return self.receipts[order_id]
        if self.reject:
            raise ValueError("catalog removed")
        self.grants += 1
        self.receipts[order_id] = {"tier": "bronze", "name": "Knife", "value": 10, "quantity": 1}
        if self.fail_after:
            raise RuntimeError("delivery committed then disconnected")
        return self.receipts[order_id]


class TransactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        listing = {"revision": "r1", "price": 100, "stock": 2, "kind": "item",
                   "tier": "bronze", "item": "Knife", "title": "Bronze Knife", "quantity": 1}
        self.config = Config({"enabled": True, "channel": None, "listings": {"knife": listing}, "orders": {}})
        self.bank, self.crates = Bank(), Crates()
        self.locks = {}
        self.engine = module.PurchaseEngine(self.config, self.bank, BalanceTooHigh, lambda: self.crates,
                                            lambda gid: self.locks.setdefault(gid, asyncio.Lock()))
        self.member = SimpleNamespace(id=99, guild=SimpleNamespace(id=1))

    def state(self):
        return self.config.group.state.data

    async def buy(self, order="one", revision="r1"):
        return await self.engine.purchase(self.member, 5, "knife", revision, order)

    async def test_purchase_and_duplicate_charge_once(self):
        first = await self.buy()
        second = await self.buy()
        self.assertEqual(first["status"], "complete")
        self.assertTrue(second["duplicate"])
        self.assertEqual(self.bank.balance, 900)
        self.assertEqual(self.bank.charges, 1)
        self.assertEqual(self.crates.grants, 1)
        self.assertEqual(self.state()["listings"]["knife"]["stock"], 1)

    async def test_concurrent_confirmations_for_same_order_do_not_duplicate(self):
        results = await asyncio.gather(*[self.buy() for _ in range(8)])
        self.assertEqual(sum(not result["duplicate"] for result in results), 1)
        self.assertEqual(self.bank.charges, 1)

    async def test_last_stock_sold_once(self):
        self.state()["listings"]["knife"]["stock"] = 1
        results = await asyncio.gather(self.buy("one"), self.buy("two"), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(self.bank.charges, 1)
        self.assertEqual(self.state()["listings"]["knife"]["stock"], 0)

    async def test_insufficient_balance_restores_stock(self):
        self.bank.balance = 50
        with self.assertRaises(module.StoreError):
            await self.buy()
        self.assertEqual(self.bank.balance, 50)
        self.assertEqual(self.state()["listings"]["knife"]["stock"], 2)
        self.assertEqual(self.state()["orders"]["one"]["status"], "failed")
        self.assertEqual(self.crates.grants, 0)

    async def test_known_delivery_failure_refunds_and_restores_stock(self):
        self.crates.reject = True
        with self.assertRaises(module.StoreError):
            await self.buy()
        self.assertEqual(self.bank.balance, 1000)
        self.assertEqual(self.bank.refunds, 1)
        self.assertEqual(self.state()["orders"]["one"]["status"], "refunded")
        self.assertEqual(self.state()["listings"]["knife"]["stock"], 2)
        with self.assertRaises(module.StoreError):
            await self.buy()
        self.assertEqual(self.bank.refunds, 1)

    async def test_refund_cap_retains_full_refund_until_claimed(self):
        self.bank.cap, self.crates.reject = 950, True
        with self.assertRaises(module.StoreError):
            await self.buy()
        self.assertEqual(self.state()["orders"]["one"]["status"], "refund_due")
        self.assertEqual(self.bank.balance, 900)
        self.bank.balance = 800
        with self.assertRaises(module.StoreError):
            await self.engine.refund(self.member, "one")
        self.assertEqual(self.bank.balance, 900)
        self.assertEqual(self.bank.refunds, 1)
        self.assertEqual(self.state()["orders"]["one"]["status"], "refunded")

    async def test_uncertain_delivery_recovery_uses_same_receipt(self):
        self.crates.fail_after = True
        with self.assertLogs(module.log, level="ERROR"), self.assertRaises(module.StoreError):
            await self.buy()
        self.assertEqual(self.state()["orders"]["one"]["status"], "delivering")
        self.assertEqual(self.bank.refunds, 0)
        self.crates.fail_after = False
        result = await self.engine.recover(self.member, "one")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.bank.charges, 1)
        self.assertEqual(self.crates.grants, 1)

    async def test_uncertain_charge_stays_for_review_and_blocks_repurchase(self):
        self.bank.uncertain = True
        with self.assertLogs(module.log, level="ERROR"), self.assertRaises(module.StoreError):
            await self.buy()
        self.assertEqual(self.state()["orders"]["one"]["status"], "charging")
        with self.assertRaises(module.StoreError):
            await self.buy("two")
        self.assertEqual(self.bank.charges, 1)

    async def test_stale_price_closed_store_and_wrong_channel_never_charge(self):
        with self.assertRaises(module.StoreError):
            await self.buy(revision="old")
        self.state()["enabled"] = False
        with self.assertRaises(module.StoreError):
            await self.buy()
        self.state().update(enabled=True, channel=10)
        with self.assertRaises(module.StoreError):
            await self.buy()
        self.assertEqual(self.bank.charges, 0)

    async def test_missing_crates_prevents_charge(self):
        self.crates = None
        with self.assertRaises(module.StoreError):
            await self.buy()
        self.assertEqual(self.bank.charges, 0)

    async def test_global_mode_change_blocks_refund(self):
        self.bank.cap, self.crates.reject = 950, True
        with self.assertRaises(module.StoreError):
            await self.buy()
        self.bank.global_bank = True
        with self.assertRaises(module.StoreError):
            await self.engine.refund(self.member, "one")
        self.assertEqual(self.bank.refunds, 0)

    async def test_other_member_cannot_claim_order_or_refund(self):
        await self.buy()
        other = SimpleNamespace(id=22, guild=self.member.guild)
        with self.assertRaises(module.StoreError):
            await self.engine.purchase(other, 5, "knife", "r1", "one")
        with self.assertRaises(module.StoreError):
            await self.engine.refund(other, "one")

    async def test_restart_recovery_uses_persisted_order(self):
        self.crates.fail_after = True
        with self.assertLogs(module.log, level="ERROR"), self.assertRaises(module.StoreError):
            await self.buy()
        restarted = module.PurchaseEngine(self.config, self.bank, BalanceTooHigh, lambda: self.crates,
                                          lambda gid: asyncio.Lock())
        self.crates.fail_after = False
        await restarted.recover(self.member, "one")
        self.assertEqual(self.crates.grants, 1)
        self.assertEqual(self.bank.charges, 1)
