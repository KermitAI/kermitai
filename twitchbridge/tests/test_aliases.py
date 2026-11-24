import asyncio
import copy
import types
import unittest
from unittest.mock import AsyncMock, Mock

from test_bridge import module, policy, Field
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
        self.cog.config = types.SimpleNamespace(guild=lambda guild: self.group, guild_from_id=lambda gid: self.group, global_commands=Field({}))
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

    async def test_twitch_only_command_can_share_registered_discord_name(self):
        self.cog.bot.get_command.return_value = object()
        await self.cog.command_add(self.ctx, "rps", response="Twitch game")
        record = self.cfg["custom_commands"]["rps"]
        self.assertEqual(record["platform"], "twitch")
        self.assertEqual(await self.cog._prepare_command(1, "rps", "", "twitch", 0, "Viewer"), "Twitch game")
        self.assertIsNone(await self.cog._prepare_command(1, "rps", "", "discord", 0, "Viewer"))

    async def test_discord_platform_conflicts_reject_without_mutation(self):
        self.cfg["custom_commands"]["hello"]["platform"] = "twitch"
        self.cog.bot.get_command.side_effect = lambda name: object() if name == "hello" else None
        for platform in ("discord", "both"):
            await self.cog.command_platform(self.ctx, "hello", platform)
            self.assertEqual(self.cfg["custom_commands"]["hello"]["platform"], "twitch")
            self.assertIn("`hello`", self.ctx.send.call_args.args[0])

    async def test_twitch_alias_can_share_discord_name_but_blocks_discord_enable(self):
        record = self.cfg["custom_commands"]["hello"]
        record["platform"] = "twitch"
        self.cog.bot.get_command.side_effect = lambda name: object() if name == "rps" else None
        await self.add("rps")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["aliases"], ["rps"])
        await self.cog.command_platform(self.ctx, "rps", "both")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["platform"], "twitch")
        self.assertIn("`rps`", self.ctx.send.call_args.args[0])
        await self.cog.alias_remove(self.ctx, "rps")
        await self.cog.command_platform(self.ctx, "hello", "both")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["platform"], "both")

    async def test_unconflicted_command_can_enable_discord_or_both(self):
        for platform in ("discord", "both", "twitch"):
            await self.cog.command_platform(self.ctx, "hello", platform)
            self.assertEqual(self.cfg["custom_commands"]["hello"]["platform"], platform)

    async def test_shared_alias_rejects_registered_discord_command(self):
        self.cog.bot.get_command.side_effect = lambda name: object() if name == "rps" else None
        for platform in ("discord", "both"):
            self.cfg["custom_commands"]["hello"]["platform"] = platform
            await self.add("rps")
            self.assertNotIn("rps", self.cfg["custom_commands"]["hello"].get("aliases", []))

    async def test_switching_back_to_twitch_is_allowed_despite_discord_conflict(self):
        self.cog.bot.get_command.return_value = object()
        await self.cog.command_platform(self.ctx, "hello", "twitch")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["platform"], "twitch")

    async def test_permission_controls_save_everyone_and_moderator_and_enforce_access(self):
        self.cfg["custom_commands"]["hello"]["cooldown"] = 0
        await self.cog.command_permission(self.ctx, "hello", "moderator")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["permission"], "moderator")
        self.assertIsNone(await self.cog._prepare_command(1, "hello", "", "twitch", 0, "Viewer"))
        for level in (1, 2):
            self.assertIsNotNone(await self.cog._prepare_command(1, "hello", "", "twitch", level, "Mod"))
        await self.cog.command_permission(self.ctx, "hello", "everyone")
        self.assertIsNotNone(await self.cog._prepare_command(1, "hello", "", "twitch", 0, "Viewer"))
        await self.cog.command_permission(self.ctx, "hello", "invalid")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["permission"], "everyone")

    async def test_public_list_is_live_and_respects_permission_and_platform(self):
        self.cog._send_twitch = AsyncMock()
        await self.cog._public_command_list(1, "123")
        self.assertEqual(self.cog._send_twitch.call_args.args[1], "Commands: !hello")
        await self.cog.command_permission(self.ctx, "hello", "moderator")
        await self.cog.command_add(self.ctx, "rps", response="Rock")
        self.cog.cooldowns.clear()
        await self.cog._public_command_list(1, "123")
        self.assertEqual(self.cog._send_twitch.call_args.args[1], "Commands: !rps")
        await self.cog.command_platform(self.ctx, "rps", "discord")
        self.cog.cooldowns.clear()
        await self.cog._public_command_list(1, "123")
        self.assertIn("No public", self.cog._send_twitch.call_args.args[1])

    async def test_public_list_checks_route_and_shared_cooldown(self):
        self.cog._send_twitch = AsyncMock()
        await self.cog._public_command_list(1, "other")
        self.cog._send_twitch.assert_not_awaited()
        await self.cog._public_command_list(1, "123")
        await self.cog._public_command_list(1, "123")
        self.cog._send_twitch.assert_awaited_once()
        self.cog.cooldowns.clear()
        self.cfg["enabled"] = False
        await self.cog._public_command_list(1, "123")
        self.assertEqual(self.cog._send_twitch.await_count, 1)

    async def test_public_list_aliases_dispatch_to_same_handler(self):
        self.cog.command_queue = asyncio.Queue()
        self.cog._public_command_list = AsyncMock()
        for name in ("twitchcommands", "tcommands", "tcmds"):
            self.cog.command_queue.put_nowait((1, "123", {"message": {"text": "!" + name}}))
        task = asyncio.create_task(self.cog._command_loop())
        await asyncio.wait_for(self.cog.command_queue.join(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.cog._public_command_list.await_count, 3)
        for call in self.cog._public_command_list.call_args_list:
            self.assertEqual(call.args, (1, "123"))

    async def test_public_list_names_are_reserved_for_commands_and_aliases(self):
        for name in ("twitchcommands", "tcommands", "tcmds"):
            await self.cog.command_add(self.ctx, name, response="Hidden")
            await self.add(name)
            self.assertNotIn(name, self.cfg["custom_commands"])
            self.assertNotIn(name, self.cfg["custom_commands"]["hello"].get("aliases", []))

    def test_public_list_pages_fit_chat_limits_and_use_configured_prefix(self):
        self.cfg["command_prefix"] = "?"
        self.cfg["custom_commands"] = {"command" + str(i).zfill(3) + "x" * 20:
            {"platform": "twitch", "permission": "everyone"} for i in range(250)}
        pages = policy.public_command_pages(self.cfg)
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page) <= 500 for page in pages))
        text = " ".join(pages)
        self.assertEqual(text.count("?command"), 250)

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
