import asyncio
import copy
import types
import unittest
from unittest.mock import AsyncMock

import test_aliases as fixtures
from test_bridge import module, policy


class GlobalCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.AliasTests.setUp(self)
        self.global_data = {"commands": {}}
        self.cfg["response_counters"] = {}
        self.other = copy.deepcopy(self.cfg)
        self.other.update(broadcaster="other", broadcaster_id="456")
        self.groups = {1: fixtures.ConfigGroup(self.cfg), 2: fixtures.ConfigGroup(self.other)}
        self.cog.config = types.SimpleNamespace(
            guild=lambda guild: self.groups[guild.id], guild_from_id=lambda gid: self.groups[gid],
            global_commands=fixtures.ConfigValue(self.global_data, "commands"))

    async def add(self, name="rps", response="Global response"):
        await self.cog.global_add(self.ctx, name, response=response)

    async def test_global_command_works_on_multiple_streams_but_not_discord(self):
        await self.add()
        for guild in (1, 2):
            self.assertEqual(await self.cog._prepare_command(guild, "rps", "", "twitch", 0, "Viewer"), "Global response")
            self.assertIsNone(await self.cog._prepare_command(guild, "rps", "", "discord", 0, "Viewer"))
        self.assertEqual(self.global_data["commands"]["rps"]["platform"], "twitch")

    async def test_alias_shares_cooldown_per_stream_without_blocking_another(self):
        await self.add()
        await self.cog.global_alias_add(self.ctx, "rps", "gameplay")
        self.assertIsNotNone(await self.cog._prepare_command(1, "gameplay", "", "twitch", 0, "Viewer"))
        self.assertIsNone(await self.cog._prepare_command(1, "rps", "", "twitch", 0, "Viewer"))
        self.assertIsNotNone(await self.cog._prepare_command(2, "rps", "", "twitch", 0, "Viewer"))

    async def test_local_command_or_alias_shadows_global_without_permission_bypass(self):
        await self.add("hello")
        self.cfg["custom_commands"]["hello"]["permission"] = "moderator"
        self.assertIsNone(await self.cog._prepare_command(1, "hello", "", "twitch", 0, "Viewer"))
        self.cfg["custom_commands"]["hello"]["platform"] = "discord"
        self.assertIsNone(await self.cog._prepare_command(1, "hello", "", "twitch", 2, "Owner"))
        await self.add("hi")
        await self.cog.alias_add(self.ctx, "hello", "hi")
        self.assertIsNone(await self.cog._prepare_command(1, "hi", "", "twitch", 2, "Owner"))

    async def test_global_responses_use_current_stream_variables_and_separate_counters(self):
        await self.add(response="{channel}: {counter}")
        await self.cog.global_cooldown(self.ctx, "rps", 0)
        self.assertEqual(await self.cog._prepare_command(1, "rps", "", "twitch", 0, "Viewer"), "streamer: 1")
        self.assertEqual(await self.cog._prepare_command(2, "rps", "", "twitch", 0, "Viewer"), "other: 1")
        self.assertEqual(await self.cog._prepare_command(1, "rps", "", "twitch", 0, "Viewer"), "streamer: 2")

    async def test_permission_change_and_invalid_settings(self):
        await self.add()
        await self.cog.global_permission(self.ctx, "rps", "moderator")
        self.assertIsNone(await self.cog._prepare_command(1, "rps", "", "twitch", 0, "Viewer"))
        self.assertIsNotNone(await self.cog._prepare_command(1, "rps", "", "twitch", 1, "Mod"))
        await self.cog.global_permission(self.ctx, "rps", "invalid")
        await self.cog.global_cooldown(self.ctx, "rps", -1)
        self.assertEqual(self.global_data["commands"]["rps"]["permission"], "moderator")
        self.assertEqual(self.global_data["commands"]["rps"]["cooldown"], 5)

    async def test_edits_via_alias_and_removal_preserve_other_records(self):
        await self.add()
        await self.cog.global_alias_add(self.ctx, "rps", "play")
        await self.cog.global_edit(self.ctx, "play", response="Updated")
        self.assertEqual(self.global_data["commands"]["rps"]["response"], "Updated")
        await self.cog.global_alias_remove(self.ctx, "rps")
        self.assertIn("rps", self.global_data["commands"])
        await self.cog.global_remove(self.ctx, "play")
        self.assertIn("rps", self.global_data["commands"])
        self.cog.cooldowns[(1, "global:rps")] = 100
        self.cog.cooldowns[(2, "global:rps")] = 100
        await self.cog.global_remove(self.ctx, "rps")
        self.assertEqual(self.global_data["commands"], {})
        self.assertEqual(self.cog.cooldowns, {})
        self.assertIn("hello", self.cfg["custom_commands"])

    async def test_global_import_copies_settings_and_leaves_local_unchanged(self):
        self.cfg["custom_commands"]["hello"].update(aliases=["hi"], permission="moderator")
        before = copy.deepcopy(self.cfg["custom_commands"])
        await self.cog.global_import(self.ctx, "hi")
        record = self.global_data["commands"]["hello"]
        self.assertEqual(record["permission"], "moderator")
        self.assertEqual(record["aliases"], ["hi"])
        self.assertEqual(record["platform"], "twitch")
        self.assertEqual(self.cfg["custom_commands"], before)

    async def test_import_conflict_is_atomic(self):
        await self.add("hi")
        self.cfg["custom_commands"]["hello"]["aliases"] = ["hi"]
        await self.cog.global_import(self.ctx, "hello")
        self.assertNotIn("hello", self.global_data["commands"])

    async def test_public_list_merges_globals_and_filters_local_shadows(self):
        await self.add("hello")
        await self.add("rps")
        await self.add("private")
        await self.cog.global_permission(self.ctx, "private", "moderator")
        self.cfg["custom_commands"]["hello"]["permission"] = "moderator"
        self.cog._send_twitch = AsyncMock()
        await self.cog._public_command_list(1, "123")
        self.assertEqual(self.cog._send_twitch.call_args.args[1], "Commands: !rps")

    async def test_duplicate_reserved_and_global_alias_names_are_rejected(self):
        await self.add()
        await self.add(response="Should not replace")
        await self.add("so")
        await self.cog.global_alias_add(self.ctx, "rps", "play")
        await self.add("play")
        await self.cog.global_alias_add(self.ctx, "rps", "so")
        self.assertEqual(set(self.global_data["commands"]), {"rps"})
        self.assertEqual(self.global_data["commands"]["rps"]["response"], "Global response")
        self.assertEqual(self.global_data["commands"]["rps"]["aliases"], ["play"])

    async def test_concurrent_alias_claims_have_one_owner(self):
        await self.add("first")
        await self.add("second")
        await asyncio.gather(self.cog.global_alias_add(self.ctx, "first", "shared"),
                             self.cog.global_alias_add(self.ctx, "second", "shared"))
        self.assertEqual(sum("shared" in record.get("aliases", []) for record in self.global_data["commands"].values()), 1)

    async def test_global_state_remains_available_to_fresh_cog(self):
        await self.add()
        fresh = module.TwitchBridge.__new__(module.TwitchBridge)
        fresh.config = self.cog.config
        fresh.command_locks, fresh.cooldowns = {}, {}
        self.assertEqual(await fresh._prepare_command(2, "rps", "", "twitch", 0, "Viewer"), "Global response")

    async def test_paused_and_stale_routes_do_not_execute_globals(self):
        await self.add()
        self.assertIsNone(await self.cog._prepare_command(1, "rps", "", "twitch", 0, "Viewer", broadcaster_id="other"))
        self.cfg["enabled"] = False
        self.assertIsNone(await self.cog._prepare_command(1, "rps", "", "twitch", 0, "Viewer"))
