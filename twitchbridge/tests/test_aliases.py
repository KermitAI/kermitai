import asyncio
import copy
import types
import unittest
from unittest.mock import AsyncMock, Mock

from test_bridge import module, policy
import test_commands as fixtures
import test_community as state


class ConfigValue(state.Field):
    # Red Config values support both `await value()` and `async with value()`.
    def __call__(self):
        return self

    def __await__(self):
        async def read():
            return copy.deepcopy(self.data[self.key])
        return read().__await__()


class ConfigGroup(state.Group):
    def __getattr__(self, key):
        return ConfigValue(self.data, key)


class AliasTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.CommandTests.setUp(self)
        self.group = ConfigGroup(self.cfg)
        self.cog.config = types.SimpleNamespace(guild=lambda guild: self.group, guild_from_id=lambda gid: self.group)
        self.cog.bot = types.SimpleNamespace(get_command=Mock(return_value=None))
        self.ctx = types.SimpleNamespace(guild=types.SimpleNamespace(id=1), send=AsyncMock())

    async def add(self, alias="hi", name="hello"):
        await self.cog.alias_add(self.ctx, name, alias)

    async def test_existing_commands_without_alias_fields_continue_working(self):
        self.assertIsNotNone(await self.cog._prepare_command(1, "hello", "args", "twitch", 0, "Viewer"))
        self.assertNotIn("aliases", self.cfg["custom_commands"]["hello"])

    async def test_alias_shares_cooldown_with_original_and_other_platform(self):
        await self.add()
        self.assertIsNotNone(await self.cog._prepare_command(1, "hi", "args", "twitch", 0, "Viewer"))
        self.assertIsNone(await self.cog._prepare_command(1, "hello", "args", "discord", 0, "Viewer"))
        self.assertIn((1, "hello"), self.cog.cooldowns)
        self.assertNotIn((1, "hi"), self.cog.cooldowns)

    async def test_alias_uses_original_permission_and_platform(self):
        await self.add()
        record = self.cfg["custom_commands"]["hello"]
        record.update(permission="moderator", platform="twitch")
        self.assertIsNone(await self.cog._prepare_command(1, "hi", "", "twitch", 0, "Viewer"))
        self.assertIsNone(await self.cog._prepare_command(1, "hi", "", "discord", 2, "Owner"))
        self.assertIsNotNone(await self.cog._prepare_command(1, "hi", "", "twitch", 1, "Mod"))

    async def test_alias_keeps_the_canonical_implicit_counter(self):
        self.cfg["response_counters"] = {}
        record = self.cfg["custom_commands"]["hello"]
        record.update(response="{counter}", cooldown=0)
        await self.add()
        self.assertEqual(await self.cog._prepare_command(1, "hi", "", "twitch", 0, "Viewer"), "1")
        self.assertEqual(await self.cog._prepare_command(1, "hello", "", "discord", 0, "Viewer"), "2")
        self.assertEqual(self.cfg["response_counters"], {"hello": 2})

    async def test_editing_via_an_alias_updates_original_and_all_aliases(self):
        await self.add()
        await self.cog.command_edit(self.ctx, "hi", response="Updated")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["response"], "Updated")
        self.assertNotIn("hi", self.cfg["custom_commands"])

    async def test_alias_of_an_alias_still_points_directly_to_original(self):
        await self.add()
        await self.add("hey", "hi")
        self.assertEqual(policy.resolve_custom_command(self.cfg["custom_commands"], "hey")[0], "hello")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["aliases"], ["hi", "hey"])

    async def test_conflicts_with_commands_aliases_and_builtins_are_rejected(self):
        await self.add()
        await self.add("hello")
        await self.add("hi")
        await self.add("title")
        self.cog.bot.get_command.return_value = object()
        await self.add("help")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["aliases"], ["hi"])

    async def test_adding_a_command_with_an_existing_alias_name_is_rejected(self):
        await self.add()
        await self.cog.command_add(self.ctx, "hi", response="Wrong")
        self.assertNotIn("hi", self.cfg["custom_commands"])

    async def test_alias_limit_and_case_normalization(self):
        await self.add("!HI")
        for i in range(10):
            await self.add("alt" + str(i))
        aliases = self.cfg["custom_commands"]["hello"]["aliases"]
        self.assertEqual(len(aliases), 10)
        self.assertEqual(aliases[0], "hi")

    async def test_alias_removal_preserves_original_and_other_aliases(self):
        await self.add()
        await self.add("hey")
        await self.cog.alias_remove(self.ctx, "hi")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["aliases"], ["hey"])
        await self.cog.command_remove(self.ctx, "hey")
        self.assertIn("hello", self.cfg["custom_commands"])
        self.assertEqual(self.cfg["custom_commands"]["hello"]["aliases"], [])

    async def test_original_removal_deletes_all_aliases(self):
        await self.add()
        await self.cog.command_remove(self.ctx, "hello")
        self.assertEqual(self.cfg["custom_commands"], {})
        self.assertEqual(policy.resolve_custom_command(self.cfg["custom_commands"], "hi"), (None, None))

    async def test_alias_remove_cannot_accidentally_remove_original(self):
        await self.cog.alias_remove(self.ctx, "hello")
        self.assertIn("hello", self.cfg["custom_commands"])

    async def test_saved_aliases_work_in_a_fresh_cog_instance(self):
        await self.add()
        fresh = module.TwitchBridge.__new__(module.TwitchBridge)
        fresh.config = self.cog.config
        fresh.command_locks, fresh.cooldowns = {}, {}
        self.assertIsNotNone(await fresh._prepare_command(1, "hi", "args", "twitch", 0, "Viewer"))

    async def test_alias_lists_are_paginated_within_discord_limits(self):
        for n in range(15):
            self.cfg["custom_commands"]["command" + str(n)] = {"response": "Hi", "platform": "both", "permission": "everyone", "cooldown": 5,
                "aliases": [f"alias{n}_{i}" + "x" * 20 for i in range(10)]}
        await self.cog.command_list(self.ctx)
        self.assertTrue(all(len(call.args[0]) <= 1800 for call in self.ctx.send.call_args_list))
        self.assertGreater(self.ctx.send.await_count, 1)

    async def test_concurrent_alias_claims_do_not_assign_one_name_twice(self):
        self.cfg["custom_commands"]["other"] = copy.deepcopy(self.cfg["custom_commands"]["hello"])
        await asyncio.gather(self.add("shared", "hello"), self.add("shared", "other"))
        owners = [name for name, record in self.cfg["custom_commands"].items() if "shared" in record.get("aliases", [])]
        self.assertEqual(len(owners), 1)
