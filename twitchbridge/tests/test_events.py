import asyncio
import copy
import time
import types
import unittest
from unittest.mock import AsyncMock

from test_bridge import module
import test_community as community_tests
import test_commands as command_tests


events = module.ChannelEventsMixin._event_count.__globals__
DEFAULTS = events["EVENT_DEFAULTS"]
SPECS = events["event_specs"]
RENDER = events["render_event"]
VALIDATE = events["validate_event_template"]
KINDS = tuple(events["EVENTS"])


class EventPolicyTests(unittest.TestCase):
    def test_subscription_versions_and_incoming_raid_conditions(self):
        specs = SPECS("123", KINDS)
        self.assertEqual(specs["follow"]["version"], "2")
        self.assertEqual(specs["follow"]["condition"], {"broadcaster_user_id": "123", "moderator_user_id": "123"})
        self.assertEqual(specs["raid"]["condition"], {"to_broadcaster_user_id": "123"})
        self.assertEqual(specs["cheer"]["type"], "channel.cheer")

    def test_templates_reject_format_code_and_unavailable_fields(self):
        for template in ("{user.__class__}", "{user!r}", "{user:1000}", "{bits}", "broken {", "", "x" * 501):
            with self.assertRaises(ValueError):
                VALIDATE("follow", template)
        self.assertEqual(VALIDATE("cheer", "Thanks {user} for {bits}!"), "Thanks {user} for {bits}!")

    def test_anonymous_gifts_and_cheers_never_reveal_payload_identity(self):
        payload = {"is_anonymous": True, "user_name": "SecretName", "user_login": "secretlogin", "bits": 100, "total": 5, "tier": "2000"}
        self.assertEqual(RENDER("cheer", "{user}|{url}|{bits}", payload, "channel"), "Anonymous||100")
        self.assertEqual(RENDER("gift", "{user} gifted {count} at tier {tier}", payload, "channel"), "Anonymous gifted 5 at tier 2")

    def test_resub_and_raid_values_use_the_correct_actor_and_counts(self):
        self.assertEqual(RENDER("resub", "{user}|{months}|{message}", {"user_name": "Viewer", "cumulative_months": 12,
            "message": {"text": "Great stream!"}}, "channel"), "Viewer|12|Great stream!")
        self.assertEqual(RENDER("raid", "{user}|{viewers}|{url}", {"from_broadcaster_user_name": "Raider",
            "from_broadcaster_user_login": "raider", "viewers": 42}, "channel"), "Raider|42|https://twitch.tv/raider")

    def test_expanded_messages_are_bounded_and_never_reparsed(self):
        payload = {"user_name": "{bits}", "bits": 100, "message": "x" * 1000 + "\ntext"}
        self.assertEqual(RENDER("cheer", "{user}", payload, "channel"), "{bits}")
        rendered = RENDER("cheer", "{message}", payload, "channel")
        self.assertEqual(len(rendered), 500)
        self.assertTrue(rendered.endswith("..."))
        self.assertNotIn("\n", rendered)


class EventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        community_tests.CommunityTests.setUp(self)
        self.cog._init_channel_events()
        self.cog.closing = False
        self.cog.bot.cog_disabled_in_guild = AsyncMock(return_value=False)
        self.cfg["channel_events"] = copy.deepcopy(DEFAULTS)
        self.cfg["channel_events"].update(enabled=True)
        self.cog._send_twitch = AsyncMock()
        self.specs = SPECS("stream", KINDS)
        self.payload = {"broadcaster_user_id": "stream", "user_name": "Viewer", "user_login": "viewer"}
        self.cog._event_token = AsyncMock(return_value=("client", {"user_id": "stream", "access_token": "secret", "scopes": sorted(module.BROADCASTER_SCOPES)}))

    def message(self, kind, payload=None, message_id="id1"):
        return {"metadata": {"message_id": message_id, "message_type": "notification"},
                "payload": {"subscription": copy.deepcopy(self.specs[kind]), "event": payload or self.payload}}

    def notify(self, kind, payload=None, message_id="id1"):
        self.cog._channel_event_notification(1, "stream", 0, self.specs, self.message(kind, payload, message_id))

    async def drain(self):
        task = asyncio.create_task(self.cog._event_sender_loop())
        await asyncio.wait_for(self.cog.event_queue.join(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def test_duplicate_events_queue_once(self):
        self.notify("follow")
        self.notify("follow")
        self.assertEqual(self.cog.event_queue.qsize(), 1)
        self.assertEqual(self.cog.event_counts[1]["queued"], 1)

    def test_other_broadcasters_or_subscription_conditions_are_rejected(self):
        self.notify("follow", dict(self.payload, broadcaster_user_id="foreign"))
        msg = self.message("follow")
        msg["payload"]["subscription"]["condition"]["moderator_user_id"] = "foreign"
        self.cog._channel_event_notification(1, "stream", 0, self.specs, msg)
        self.assertTrue(self.cog.event_queue.empty())

    def test_only_incoming_raids_are_announced(self):
        self.notify("raid", {"to_broadcaster_user_id": "foreign", "from_broadcaster_user_id": "stream"})
        self.assertTrue(self.cog.event_queue.empty())
        self.notify("raid", {"to_broadcaster_user_id": "stream", "from_broadcaster_user_id": "foreign"})
        self.assertEqual(self.cog.event_queue.qsize(), 1)

    def test_gift_recipients_are_not_announced_in_addition_to_gift_summary(self):
        self.notify("subscribe", dict(self.payload, is_gift=True))
        self.assertTrue(self.cog.event_queue.empty())
        self.notify("gift", dict(self.payload, total=5), "gift1")
        self.assertEqual(self.cog.event_queue.qsize(), 1)

    def test_event_queue_is_bounded_and_overflow_is_visible(self):
        self.cog.event_queue = asyncio.Queue(maxsize=1)
        self.notify("follow", message_id="a")
        self.notify("follow", message_id="b")
        self.assertEqual(self.cog.event_counts[1]["dropped"], 1)

    async def test_event_delivery_uses_this_broadcasters_template(self):
        self.cfg["channel_events"]["messages"]["follow"] = "Welcome {user} to {channel}!"
        self.notify("follow")
        await self.drain()
        call = self.cog._send_twitch.call_args
        self.assertEqual(call.args, (1, "Welcome Viewer to streamer!"))
        self.assertEqual(call.kwargs["expected_broadcaster"], "stream")
        self.assertEqual(self.cog.event_counts[1]["sent"], 1)

    async def test_announcement_mode_uses_native_announcements(self):
        self.cfg["channel_events"]["mode"] = "announcement"
        self.notify("follow")
        await self.drain()
        self.assertTrue(self.cog._send_twitch.call_args.kwargs["announcement"])

    async def test_disabled_changed_and_expired_events_do_not_send(self):
        self.notify("follow")
        self.cfg["channel_events"]["revision"] = 1
        await self.drain()
        self.cog._send_twitch.assert_not_awaited()
        self.cfg["channel_events"]["revision"] = 0
        await self.cog.event_queue.put((1, "stream", 0, "follow", time.monotonic() - 121, self.payload))
        await self.drain()
        self.cog._send_twitch.assert_not_awaited()

    async def test_per_type_cooldown_drops_follow_without_blocking_other_events(self):
        self.cfg["channel_events"]["cooldowns"]["follow"] = 60
        self.notify("follow", message_id="a")
        self.notify("follow", message_id="b")
        self.notify("cheer", dict(self.payload, bits=10), "c")
        await self.drain()
        self.assertEqual(self.cog._send_twitch.await_count, 2)
        self.assertEqual(self.cog.event_counts[1]["dropped"], 1)

    async def test_failed_outbound_message_is_not_retried(self):
        self.cog._send_twitch.side_effect = module.BridgeError("Not accepted")
        self.notify("follow")
        await self.drain()
        self.cog._send_twitch.assert_awaited_once()
        self.assertEqual(self.cog.event_counts[1]["dropped"], 1)

    def welcome(self):
        return {"metadata": {"message_type": "session_welcome"}, "payload": {"session": {"id": "s1", "keepalive_timeout_seconds": 10}}}

    async def test_partial_authorization_still_subscribes_available_event_types(self):
        ws = types.SimpleNamespace(receive_json=AsyncMock(side_effect=[self.welcome(), asyncio.CancelledError()]), close=AsyncMock())
        self.cog.http = types.SimpleNamespace(ws_connect=AsyncMock(return_value=ws))
        self.cog._request.return_value = (202, {})
        auth = {"access_token": "secret", "scopes": []}
        with self.assertRaises(asyncio.CancelledError):
            await self.cog._listen_channel_events(1, "stream", ("follow", "raid"), 0, "client", auth)
        self.cog._request.assert_awaited_once()
        self.assertEqual(self.cog._request.call_args.kwargs["json"]["type"], "channel.raid")
        self.assertIn("follow: broadcaster approval needed", self.cog.event_connections[1])
        ws.close.assert_awaited_once()

    async def test_no_accepted_subscriptions_close_the_socket(self):
        ws = types.SimpleNamespace(receive_json=AsyncMock(return_value=self.welcome()), close=AsyncMock())
        self.cog.http = types.SimpleNamespace(ws_connect=AsyncMock(return_value=ws))
        with self.assertRaises(module.BridgeError):
            await self.cog._listen_channel_events(1, "stream", ("follow",), 0, "client", {"access_token": "secret", "scopes": []})
        ws.close.assert_awaited_once()

    async def test_event_reconnect_handoff_does_not_resubscribe(self):
        reconnect = {"metadata": {"message_type": "session_reconnect"},
                     "payload": {"session": {"reconnect_url": "wss://eventsub.wss.twitch.tv/ws?session=new"}}}
        old = types.SimpleNamespace(receive_json=AsyncMock(side_effect=[self.welcome(), reconnect]), close=AsyncMock())
        new = types.SimpleNamespace(receive_json=AsyncMock(side_effect=[self.welcome(), asyncio.CancelledError()]), close=AsyncMock())
        self.cog.http = types.SimpleNamespace(ws_connect=AsyncMock(side_effect=[old, new]))
        self.cog._request.return_value = (202, {})
        with self.assertRaises(asyncio.CancelledError):
            await self.cog._listen_channel_events(1, "stream", ("raid",), 0, "client", {"access_token": "secret", "scopes": []})
        self.cog._request.assert_awaited_once()
        old.close.assert_awaited()
        new.close.assert_awaited_once()

    async def test_failing_one_subscription_does_not_remove_successful_ones(self):
        ws = types.SimpleNamespace(receive_json=AsyncMock(side_effect=[self.welcome(), asyncio.CancelledError()]), close=AsyncMock())
        self.cog.http = types.SimpleNamespace(ws_connect=AsyncMock(return_value=ws))
        self.cog._request.side_effect = [(400, {}), (202, {})]
        with self.assertRaises(asyncio.CancelledError):
            await self.cog._listen_channel_events(1, "stream", ("subscribe", "raid"), 0, "client",
                {"access_token": "secret", "scopes": ["channel:read:subscriptions"]})
        self.assertIn("1/2", self.cog.event_connections[1])
        self.assertIn("subscribe: subscription refused", self.cog.event_connections[1])


    async def test_event_token_uses_broadcaster_auth_and_rejects_route_changes(self):
        self.cog._role_token.reset_mock()
        await type(self.cog)._event_token(self.cog, 1, "stream")
        self.cog._role_token.assert_awaited_once_with(1, set())
        with self.assertRaises(module.BridgeError):
            await type(self.cog)._event_token(self.cog, 1, "other")

    async def test_supervisor_isolates_broadcaster_connections_and_cancels_disabled_one(self):
        other = copy.deepcopy(self.cfg)
        other["broadcaster_id"] = "other"
        self.cog.config.all_guilds.return_value = {1: self.cfg, 2: other}
        self.cog.bot.wait_until_red_ready = AsyncMock()
        started, stopped = [], []
        async def hold(gid, broadcaster, kinds, revision):
            started.append((gid, broadcaster))
            try:
                await asyncio.Future()
            finally:
                stopped.append(gid)
        self.cog._channel_event_loop = hold
        async def until(predicate):
            while not predicate():
                await asyncio.sleep(0)
        supervisor = asyncio.create_task(self.cog._event_supervisor_loop())
        try:
            await asyncio.wait_for(until(lambda: len(started) == 2), 1)
            self.assertEqual(set(started), {(1, "stream"), (2, "other")})
            self.cfg["channel_events"]["enabled"] = False
            self.cog.events_wakeup.set()
            await asyncio.wait_for(until(lambda: 1 in stopped), 1)
            self.assertNotIn(2, stopped)
        finally:
            self.cog.closing = True
            self.cog.events_wakeup.set()
            await asyncio.wait_for(supervisor, 1)
        self.assertFalse(self.cog.event_tasks)
        self.assertIn(2, stopped)


class EventSendGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        command_tests.CommandTests.setUp(self)
        self.cfg["channel_events"] = copy.deepcopy(DEFAULTS)
        self.cfg["channel_events"].update(enabled=True)

    async def test_send_guard_rechecks_configuration_after_waiting_for_rate_limit(self):
        with self.assertRaises(module.BridgeError):
            await self.cog._send_twitch(1, "Old event", expected_broadcaster="123", event_guard=(1, "follow", time.monotonic()))
        self.cog._request.assert_not_awaited()

    async def test_send_guard_rejects_a_disabled_event(self):
        self.cfg["channel_events"]["types"]["follow"] = False
        with self.assertRaises(module.BridgeError):
            await self.cog._send_twitch(1, "Old event", expected_broadcaster="123", event_guard=(0, "follow", time.monotonic()))
        self.cog._request.assert_not_awaited()

    async def test_owner_changes_during_token_refresh_cancel_the_pending_event(self):
        self.cog.bot = types.SimpleNamespace(get_guild=lambda gid: object(), cog_disabled_in_guild=AsyncMock(return_value=False))
        auth = ("client", {"user_id": "bot", "access_token": "secret", "scopes": ["user:write:chat"]})
        async def token_after_change():
            self.cfg["channel_events"]["revision"] = 1
            return auth
        self.cog._token = token_after_change
        with self.assertRaises(module.BridgeError):
            await self.cog._send_twitch(1, "Old event", expected_broadcaster="123", event_guard=(0, "follow", time.monotonic()))
        self.cog._request.assert_not_awaited()
