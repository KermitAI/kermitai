"""Exercise Store embeds and purchase controls with lightweight Discord doubles."""
import importlib.util
import sys
import types
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch


def decorator(*args, **kwargs):
    def wrap(fn):
        fn.command = decorator
        return fn
    return wrap


class View:
    def __init__(self, **kwargs):
        self.children = []
        self.stopped = False

    def add_item(self, child):
        child.view = self
        self.children.append(child)

    def stop(self):
        self.stopped = True


class Component:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.disabled = False
        self.values = []


class Embed:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.fields = []

    def add_field(self, **kwargs):
        self.fields.append(kwargs)

    def set_author(self, **kwargs):
        self.author = kwargs

    def set_footer(self, **kwargs):
        self.footer = kwargs

    def set_image(self, **kwargs):
        self.image = kwargs


bank = types.SimpleNamespace(get_balance=AsyncMock(return_value=1000),
                             get_currency_name=AsyncMock(return_value="Coins"))
root = Path(__file__).parents[1]
pkg = types.ModuleType("store_ui_test")
pkg.__path__ = [str(root)]
modules = {
    "store_ui_test": pkg,
    "discord": types.SimpleNamespace(
        ui=types.SimpleNamespace(View=View, Select=Component, Button=Component),
        ButtonStyle=types.SimpleNamespace(secondary=1, success=2),
        SelectOption=Component, Embed=Embed, TextChannel=object, HTTPException=type("HTTPError", (Exception,), {}),
        AllowedMentions=types.SimpleNamespace(none=lambda: None),
        utils=types.SimpleNamespace(escape_markdown=lambda text: text)),
    "redbot": types.ModuleType("redbot"),
    "redbot.core": types.SimpleNamespace(Config=object, bank=bank, commands=types.SimpleNamespace(
        Cog=object, guild_only=decorator, admin_or_permissions=decorator, group=decorator, is_owner=decorator)),
    "redbot.core.errors": types.SimpleNamespace(BalanceTooHigh=type("BalanceTooHigh", (Exception,), {})),
    "redbot.core.utils": types.ModuleType("redbot.core.utils"),
    "redbot.core.utils.chat_formatting": types.SimpleNamespace(pagify=lambda text, **kwargs: [text]),
}
with patch.dict(sys.modules, modules):
    spec = importlib.util.spec_from_file_location("store_ui_test.store", root / "store.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


class UITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bank.get_balance.return_value = 1000
        self.member = types.SimpleNamespace(id=99, display_name="Buyer", display_avatar=types.SimpleNamespace(url="https://example.org/avatar.png"))
        self.state = {"enabled": True, "channel": None, "listings": {
            "knife": {"kind": "item", "title": "Bronze Knife", "description": "A collectible",
                      "quantity": 2, "item": "Bronze Knife", "price": 100, "stock": 1, "revision": "r1"},
            "opening": {"kind": "crate", "title": "Bonus opening", "description": "Try your luck",
                        "price": 200, "stock": -1, "revision": "r2"}}, "orders": {}}
        self.ctx = types.SimpleNamespace(author=self.member, guild=types.SimpleNamespace(
            id=1, get_member=lambda uid: self.member), channel=types.SimpleNamespace(id=5),
            embed_colour=AsyncMock(return_value=0x123456))
        self.cog = types.SimpleNamespace(config=types.SimpleNamespace(guild=lambda guild: types.SimpleNamespace(
            state=AsyncMock(return_value=self.state))), views=set(), preview=AsyncMock(return_value={
                "emoji": "X", "image": "https://example.org/knife.png"}), access=AsyncMock(),
            reveal=AsyncMock(), engine=types.SimpleNamespace(purchase=AsyncMock(return_value={"id": "order", "duplicate": False})))
        self.cog.bot = types.SimpleNamespace(get_cog=lambda name: self.cog)

    def interaction(self, uid=99):
        return types.SimpleNamespace(user=types.SimpleNamespace(id=uid),
                                     response=types.SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(), edit_message=AsyncMock()),
                                     edit_original_response=AsyncMock(), followup=types.SimpleNamespace(send=AsyncMock()))

    async def test_embed_uses_bank_currency_balance_and_bot_colour(self):
        view = module.StoreView(self.cog, self.ctx)
        embed = await view.render()
        self.assertEqual(embed.colour, 0x123456)
        self.assertIn("Bronze Knife", embed.description)
        self.assertEqual(embed.fields[0]["value"], "1,000 Coins")
        self.assertEqual(embed.fields[1]["value"], "100 Coins")
        self.assertFalse(view.buy.disabled)
        self.assertEqual(embed.image["url"], "https://example.org/knife.png")

    async def test_sold_out_and_unaffordable_buy_buttons_are_disabled(self):
        view = module.StoreView(self.cog, self.ctx)
        self.state["listings"]["knife"]["stock"] = 0
        await view.render()
        self.assertTrue(view.buy.disabled)
        self.state["listings"]["knife"]["stock"] = 1
        bank.get_balance.return_value = 50
        await view.render()
        self.assertTrue(view.buy.disabled)

    async def test_category_filter_and_empty_catalog(self):
        view = module.StoreView(self.cog, self.ctx)
        view.category = "crate"
        embed = await view.render()
        self.assertIn("Bonus opening", embed.description)
        self.assertEqual(view.selected[0], "opening")
        self.state["listings"] = {}
        embed = await view.render()
        self.assertIn("No listings", embed.description)
        self.assertTrue(view.buy.disabled)

    async def test_other_user_cannot_operate_someone_elses_store(self):
        view = module.StoreView(self.cog, self.ctx)
        interaction = self.interaction(uid=22)
        self.assertFalse(await view.interaction_check(interaction))
        interaction.response.send_message.assert_awaited_once()

    async def test_confirmation_can_only_be_spent_once(self):
        view = module.ConfirmPurchase(self.cog, self.ctx, "knife", self.state["listings"]["knife"])
        interaction = self.interaction()
        await view.confirm(interaction)
        await view.confirm(interaction)
        self.cog.engine.purchase.assert_awaited_once()
        self.cog.reveal.assert_awaited_once()

    async def test_cancel_never_charges(self):
        view = module.ConfirmPurchase(self.cog, self.ctx, "knife", self.state["listings"]["knife"])
        await view.cancel(self.interaction())
        self.cog.engine.purchase.assert_not_awaited()
        self.assertTrue(view.stopped)
