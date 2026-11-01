"""Check embed content and animation delivery without a live Discord connection."""
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_accounts as accounts

module = accounts.module


class Embed:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.fields = []

    def add_field(self, **kwargs):
        self.fields.append(kwargs)

    def set_footer(self, **kwargs):
        self.footer = kwargs

    def set_image(self, **kwargs):
        self.image = kwargs

    def set_thumbnail(self, **kwargs):
        self.thumbnail = kwargs


class HTTPError(Exception):
    pass


class Mentions:
    def __init__(self, **kwargs):
        self.options = kwargs

    @classmethod
    def none(cls):
        return cls(users=False, roles=False, everyone=False)


class PresentationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        accounts.AccountTests.setUp(self)
        self.cog.openings = set()
        self.member = types.SimpleNamespace(id=99, mention="<@99>", display_name="Collector")
        self.discord = types.SimpleNamespace(
            Embed=Embed, HTTPException=HTTPError, AllowedMentions=Mentions,
            utils=types.SimpleNamespace(escape_markdown=lambda text: text),
        )
        self.patch = patch.object(module, "discord", self.discord)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.result = {"tier": "rare", "name": "Gem", "value": 10,
                       "emoji": "X", "image": "https://example.org/gem.png", "empty": False}

    def test_success_and_empty_embeds(self):
        embed = self.cog.result_embed(self.result, self.member)
        self.assertEqual(embed.title, "Congratulations!")
        self.assertIn("<@99>", embed.description)
        self.assertEqual(embed.image["url"], self.result["image"])
        empty = self.cog.result_embed(dict(self.result, name=None, value=0, empty=True), self.member)
        self.assertEqual(empty.title, "Better luck next time!")
        self.assertFalse(hasattr(empty, "image"))

    async def test_animation_slows_lands_then_reveals(self):
        msg = types.SimpleNamespace(edit=AsyncMock())
        ctx = types.SimpleNamespace(author=self.member, send=AsyncMock(return_value=msg))
        with patch.object(module.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            await self.cog.animate_pull(ctx, self.result, {"rare": {"emoji": "X", "items": {"Gem": {}}}})
        delays = [call.args[0] for call in sleep.call_args_list]
        self.assertEqual(delays[:6], sorted(delays[:6]))
        self.assertEqual(msg.edit.await_count, 7)
        self.assertIn("【X】", msg.edit.call_args_list[-2].kwargs["embed"].description)
        self.assertEqual(msg.edit.call_args.kwargs["embed"].title, "Congratulations!")
        self.assertEqual(ctx.send.call_args.kwargs["content"], "<@99>")

    async def test_edit_failure_sends_final_result(self):
        msg = types.SimpleNamespace(edit=AsyncMock(side_effect=HTTPError))
        ctx = types.SimpleNamespace(author=self.member, send=AsyncMock(return_value=msg))
        with patch.object(module.asyncio, "sleep", new_callable=AsyncMock):
            await self.cog.animate_pull(ctx, self.result, {})
        self.assertEqual(ctx.send.await_count, 2)
        self.assertEqual(ctx.send.call_args.kwargs["embed"].title, "Congratulations!")

    async def test_result_persisted_before_animation_and_guard_cleared_on_error(self):
        ctx = types.SimpleNamespace(author=self.member, guild=types.SimpleNamespace(id=1))
        async def animate(*args):
            self.assertEqual((await self.cog.get_discord_collection(1, 99))["pulls"], 1)
            raise HTTPError()
        original_group = self.cog.config.guild
        with patch.object(self.cog.config, "guild_from_id", return_value=original_group), \
             patch.object(self.cog, "embed_access", new_callable=AsyncMock, return_value=True), \
             patch.object(self.cog.config, "guild", return_value=types.SimpleNamespace(tiers=AsyncMock(return_value={})), create=True), \
             patch.object(self.cog, "animate_pull", side_effect=animate):
            with self.assertRaises(HTTPError):
                await self.cog.pull(ctx)
        self.assertEqual(self.cog.openings, set())

    async def test_empty_reward_consumes_cooldown_without_inventory_entry(self):
        self.cog.config.guild.data["tiers"]["a"]["items"]["Gem"]["empty"] = True
        self.cog.config.guild.data["cooldown"] = 100
        result = await self.cog._pull_reward(1, discord_id=99)
        self.assertTrue(result["empty"])
        self.assertIsNone(result["name"])
        data = await self.cog.get_discord_collection(1, 99)
        self.assertEqual(data["inventory"], {})
        self.assertEqual(data["pulls"], 1)
        self.assertEqual(data["value"], 0)
        with self.assertRaises(ValueError):
            await self.cog._pull_reward(1, discord_id=99)

    async def test_twitch_duplicate_keeps_presentation_snapshot(self):
        tier = self.cog.config.guild.data["tiers"]["a"]
        tier["emoji"] = "X"
        tier["items"]["Gem"]["image"] = "https://example.org/gem.png"
        first = await self.cog.pull_twitch(1, "123", "viewer", "r1")
        tier["emoji"] = "Y"
        tier["items"]["Gem"]["image"] = None
        duplicate = await self.cog.pull_twitch(1, "123", "viewer", "r1")
        self.assertEqual(first["emoji"], duplicate["emoji"])
        self.assertEqual(first["image"], duplicate["image"])
        self.assertTrue(duplicate["duplicate"])

    async def test_embed_pages_respect_discord_description_limit(self):
        # Real pagification is not installed in this test environment; verify the
        # configured page bound and the summary/footer on each emitted embed.
        ctx = types.SimpleNamespace(send=AsyncMock(), embed_colour=AsyncMock(return_value=0x123456))
        with patch.object(module, "pagify", return_value=["page one", "page two"]) as pages:
            await self.cog.send_collection(ctx, "Inventory", ["item"], "10 pulls")
        self.assertEqual(pages.call_args.kwargs["page_length"], 3000)
        self.assertEqual(ctx.send.await_count, 2)
        self.assertTrue(all(call.kwargs["embed"].colour == 0x123456 for call in ctx.send.call_args_list))
        self.assertEqual(ctx.send.call_args.kwargs["embed"].footer["text"], "Page 2/2 | Crates")

    async def test_inventory_and_leaderboard_use_embeds(self):
        self.member.display_avatar = types.SimpleNamespace(url="https://example.org/avatar.png")
        guild = types.SimpleNamespace(id=1, members=[self.member])
        ctx = types.SimpleNamespace(author=self.member, guild=guild, send=AsyncMock(),
                                    embed_colour=AsyncMock(return_value=0x123456))
        await self.cog._pull_reward(1, discord_id=99)
        original_group = self.cog.config.guild
        tiers = original_group.data["tiers"]
        with patch.object(self.cog, "embed_access", new_callable=AsyncMock, return_value=True), \
             patch.object(self.cog.config, "guild_from_id", return_value=original_group), \
             patch.object(self.cog.config, "guild", return_value=types.SimpleNamespace(
                 tiers=AsyncMock(return_value=tiers), collections=original_group.collections)):
            await self.cog.inventory(ctx)
            inventory = ctx.send.call_args.kwargs["embed"]
            self.assertEqual(inventory.colour, 0x123456)
            self.assertIn("Gem", inventory.description)
            self.assertIn("x1", inventory.description)
            self.assertIn("10", inventory.fields[0]["value"])
            with patch.object(self.cog.config, "all_members", new_callable=AsyncMock, return_value={}):
                await self.cog.leaderboard(ctx)
            leaderboard = ctx.send.call_args.kwargs["embed"]
            self.assertEqual(leaderboard.colour, 0x123456)
            self.assertIn("Collector", leaderboard.description)
            self.assertIn("10 value", leaderboard.description)
            self.assertIn("1 pulls", leaderboard.description)
