import asyncio
import time
import types
import unittest
from unittest.mock import AsyncMock

from test_bridge import module
import test_stream_tools as fixtures

P = module.PersonalToolsMixin._countdown_command.__globals__


class PersonalToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.StreamToolsTests.setUp(self)
        self.cog._init_personal_tools()
        self.cog.cooldowns = {}
        self.cog.config.owner_twitch.value = {"user_id": "viewer", "login": "viewer"}
        self.cog.config.owner_greeting.value = {"enabled": True, "message": "My owner {user} has arrived!"}
        self.cog.bot = types.SimpleNamespace(get_guild=lambda gid: self.guild, cog_disabled_in_guild=AsyncMock(return_value=False))
        self.ctx = types.SimpleNamespace(guild=self.guild, send=AsyncMock())

    async def asyncTearDown(self):
        tasks = [item.get("task") for item in self.cog.pending_countdowns.values()]
        tasks = [task for task in tasks if isinstance(task, asyncio.Task)]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def test_personal_greeting_only_owner_once_per_stream_independent_of_other_features(self):
        await self.cog._record_presence(1, "stream", dict(self.event, chatter_user_id="someone-else"))
        self.assertEqual(self.cog.tool_queue.qsize(), 0)
        await self.cog._record_presence(1, "stream", self.event)
        await self.cog._record_presence(1, "stream", self.event)
        self.assertEqual(self.cog.tool_queue.qsize(), 1)
        item = self.cog.tool_queue.get_nowait()[2]
        self.assertEqual(item["kind"], "owner_greeting")
        self.assertTrue(await self.cog._owner_greeting_allowed(item))
        self.cog.presence_seen.clear()
        await self.cog._record_presence(1, "stream", self.event)
        self.assertEqual(self.cog.tool_queue.qsize(), 0)
        self.live["stream"] = dict(self.live["stream"], id="s2")
        await self.cog._record_presence(1, "stream", self.event)
        self.assertEqual(self.cog.tool_queue.qsize(), 1)
        self.assertFalse(self.cfg["first_message"]["enabled"])
        self.assertFalse(self.cfg["streak_settings"]["enabled"])

    async def test_personal_greeting_offline_or_disabled_does_not_mark_or_queue(self):
        self.live["stream"] = None
        await self.cog._record_presence(1, "stream", self.event)
        self.assertEqual(self.cfg["viewer_data"], {})
        self.cog.config.owner_greeting.value["enabled"] = False
        await self.cog._record_presence(1, "stream", self.event)
        self.assertEqual(self.cog.tool_queue.qsize(), 0)

    async def test_queued_owner_greeting_rejects_changed_owner_or_message(self):
        await self.cog._record_presence(1, "stream", self.event)
        item = self.cog.tool_queue.get_nowait()[2]
        self.cog.config.owner_twitch.value["user_id"] = "other"
        self.assertFalse(await self.cog._owner_greeting_allowed(item))
        self.cog.config.owner_twitch.value["user_id"] = "viewer"
        self.cog.config.owner_greeting.value["message"] = "Changed"
        self.assertFalse(await self.cog._owner_greeting_allowed(item))

    async def test_owner_greeting_configuration_views_and_edits(self):
        await self.cog.owner_greeting_message(self.ctx, message="Welcome {user}!")
        await self.cog.owner_greeting_message(self.ctx)
        self.assertEqual(self.ctx.send.call_args.args[0], "Welcome {user}!")
        await self.cog.owner_greeting_enabled(self.ctx, False)
        self.assertFalse(self.cog.config.owner_greeting.value["enabled"])
        self.cog.config.owner_twitch.value = {}
        await self.cog.owner_greeting_enabled(self.ctx, True)
        self.assertFalse(self.cog.config.owner_greeting.value["enabled"])

    def test_countdown_duration_units_and_limits(self):
        for raw, expected in [("30s", 30), ("5m", 300), ("1h", 3600), ("24H", 86400)]:
            self.assertEqual(P["countdown_seconds"](raw), expected)
        for raw in ("0s", "30", "-5m", "1h30m", "25h", "1.5m"):
            with self.assertRaises(ValueError):
                P["countdown_seconds"](raw)

    async def test_creating_timer_records_literal_text_and_pending_limits(self):
        text = await self.cog._countdown_command(1, "stream", self.event, "5m {counter} Time for a break!")
        self.assertIn("set for 5m", text)
        item = next(iter(self.cog.pending_countdowns.values()))
        self.assertEqual(item["text"], "{counter} Time for a break!")
        self.assertAlmostEqual(item["due"] - time.monotonic(), 300, delta=1)
        for _ in range(2):
            self.cog.cooldowns.clear()
            await self.cog._countdown_command(1, "stream", self.event, "1h Next timer")
        self.cog.cooldowns.clear()
        with self.assertRaises(module.BridgeError):
            await self.cog._countdown_command(1, "stream", self.event, "1h Too many")

    async def test_countdown_completion_posts_literal_message_and_removes_pending(self):
        key = (1, "example")
        item = {"id": "example", "user_id": "viewer", "broadcaster_id": "stream", "due": time.monotonic() - 1, "text": "Time is up!"}
        self.cog.pending_countdowns[key] = item
        await self.cog._run_countdown(key, item)
        self.cog._send_twitch.assert_awaited_once_with(1, "Time is up!", expected_broadcaster="stream", countdown_guard=item)
        self.assertNotIn(key, self.cog.pending_countdowns)

    async def test_changed_route_prevents_delayed_delivery(self):
        key = (1, "example")
        item = {"id": "example", "user_id": "viewer", "broadcaster_id": "old", "due": time.monotonic() - 1, "text": "No leak"}
        self.cog.pending_countdowns[key] = item
        await self.cog._run_countdown(key, item)
        self.cog._send_twitch.assert_not_awaited()
        self.assertNotIn(key, self.cog.pending_countdowns)

    async def test_countdown_permissions_and_cancel_ownership(self):
        await self.cog._countdown_command(1, "stream", self.event, "1h Reminder")
        ident = next(iter(self.cog.pending_countdowns))[1]
        stranger = dict(self.event, chatter_user_id="stranger")
        with self.assertRaises(module.BridgeError):
            await self.cog._countdown_command(1, "stream", stranger, "cancel " + ident)
        await self.cog._countdown_command(1, "stream", self.event, "cancel " + ident)
        self.assertFalse(self.cog.pending_countdowns)
        self.cfg["countdown_settings"] = {"enabled": True, "permission": "moderator"}
        with self.assertRaises(module.BridgeError):
            await self.cog._countdown_command(1, "stream", stranger, "1m Blocked")

    async def test_disabling_countdowns_cancels_pending(self):
        await self.cog._countdown_command(1, "stream", self.event, "1h Reminder")
        item = next(iter(self.cog.pending_countdowns.values()))
        await self.cog.countdown_enabled(self.ctx, False)
        await asyncio.gather(item["task"], return_exceptions=True)
        self.assertFalse(self.cog.pending_countdowns)
        self.cog._send_twitch.assert_not_awaited()
