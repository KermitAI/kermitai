import copy
import types
import unittest
from unittest.mock import AsyncMock

import test_global_commands as globals_tests


class PreviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        globals_tests.GlobalCommandTests.setUp(self)
        self.ctx.author = types.SimpleNamespace(id=99, display_name="Lee")
        self.cfg["member_links"] = {"99": {"twitch_id": "viewer", "login": "lee"}}
        self.cog._send_twitch = AsyncMock()

    async def test_local_preview_uses_arguments_alias_and_linked_author_without_side_effects(self):
        self.cfg["custom_commands"]["hello"].update(response="{user} {target} {url} {counter} {counter:named}",
            permission="moderator", aliases=["hi"])
        self.cfg["response_counters"] = {"hello": 4, "named": 9}
        self.cog.cooldowns[(1, "hello")] = 9999999999
        before, cooldowns = copy.deepcopy(self.cfg), dict(self.cog.cooldowns)
        await self.cog.command_preview(self.ctx, "hi", args="@friend")
        self.assertIn("Lee @friend https://twitch.tv/lee 5 10", self.ctx.send.call_args.args[0])
        self.assertEqual(self.cfg, before)
        self.assertEqual(self.cog.cooldowns, cooldowns)
        self.cog._send_twitch.assert_not_awaited()
        self.assertIn("allowed_mentions", self.ctx.send.call_args.kwargs)
        self.assertTrue(self.ctx.send.call_args.kwargs["suppress_embeds"])

    async def test_global_preview_uses_global_response_and_warns_about_local_override(self):
        await self.cog.global_add(self.ctx, "hello", response="Global {channel}: {counter}")
        before = copy.deepcopy(self.cfg)
        await self.cog.global_preview(self.ctx, "hello")
        self.assertIn("Global streamer: 1", self.ctx.send.call_args.args[0])
        self.assertIn("overridden here", self.ctx.send.call_args.args[0])
        self.assertEqual(self.cfg, before)
        self.assertEqual(self.cog.cooldowns, {})
        self.cog._send_twitch.assert_not_awaited()

    async def test_global_alias_preview_and_local_scope_do_not_fall_back(self):
        await self.cog.global_add(self.ctx, "rps", response="{target} {choose \"Rock\"}")
        await self.cog.global_alias_add(self.ctx, "rps", "play")
        await self.cog.command_preview(self.ctx, "play")
        self.assertIn("not found", self.ctx.send.call_args.args[0])
        await self.cog.global_preview(self.ctx, "play", args="friend")
        self.assertIn("@friend Rock", self.ctx.send.call_args.args[0])

    async def test_failed_preview_does_not_save_counters(self):
        self.cfg["custom_commands"]["hello"]["response"] = "{counter}" + "x" * 500
        await self.cog.command_preview(self.ctx, "hello")
        self.assertIn("Preview failed", self.ctx.send.call_args.args[0])
        self.assertEqual(self.cfg["response_counters"], {})
        self.cog._send_twitch.assert_not_awaited()

    async def test_preview_followage_uses_linked_twitch_account(self):
        self.cfg["custom_commands"]["hello"]["response"] = "{followage}"
        self.cog._followage = AsyncMock(return_value="2 months")
        await self.cog.command_preview(self.ctx, "hello")
        self.cog._followage.assert_awaited_once_with(1, "viewer")
        self.assertIn("2 months", self.ctx.send.call_args.args[0])
