import asyncio
import copy
import time
import types
import unittest
from unittest.mock import AsyncMock, patch

from test_bridge import module
import test_community as community_tests

POLICY = module.StreamToolsMixin._render_shared.__globals__
RUNTIME = module.StreamToolsMixin._tick_tools.__globals__


class StreamPolicyTests(unittest.TestCase):
    def test_repeated_counter_fields_increment_once_and_values_are_not_reparsed(self):
        text, counters = POLICY["apply_response"]("{counter} {counter} {user} {args}", {"user": "Viewer", "args": "{counter}"}, {}, "deaths")
        self.assertEqual(text, "1 1 Viewer {counter}")
        self.assertEqual(counters, {"deaths": 1})

    def test_named_counters_share_a_value_across_sources(self):
        text, counters = POLICY["apply_response"]("{counter:deaths}", {}, {"deaths": 41}, "trigger")
        self.assertEqual((text, counters), ("42", {"deaths": 42}))

    def test_word_triggers_match_whole_words_and_phrases_case_insensitively(self):
        match = POLICY["word_matches"]
        self.assertTrue(match("hello", "Well, HELLO!"))
        self.assertFalse(match("hi", "this"))
        self.assertTrue(match("good game", "a good game!"))

    def test_streak_repeated_attendance_misses_and_nonbreaking_policy(self):
        attendance = POLICY["attendance"]
        data = {}
        self.assertEqual(attendance(data, 1, True), 1)
        self.assertEqual(attendance(data, 1, True), 1)
        self.assertEqual(attendance(data, 2, True), 2)
        self.assertEqual(attendance(data, 4, True), 1)
        self.assertEqual(attendance(data, 7, False), 2)


class StreamToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        community_tests.CommunityTests.setUp(self)
        self.cog._init_stream_tools()
        self.cfg.update(automation_revision=0, timers={}, chat_triggers={}, response_counters={},
            todo_items=[], todo_permission="moderator", ad_settings=copy.deepcopy(RUNTIME["AD_DEFAULTS"]),
            ad_notices={}, ad_warning_pause_until=0, first_message=copy.deepcopy(RUNTIME["FIRST_DEFAULTS"]),
            streak_settings=copy.deepcopy(RUNTIME["STREAK_DEFAULTS"]), stream_session={}, viewer_data={})
        self.live = {"broadcaster_id": "stream", "fetched": time.monotonic(), "stream": {
            "id": "s1", "user_id": "stream", "started_at": "2026-11-22T12:00:00Z", "title": "Title", "game_name": "Game", "viewer_count": 42}}
        self.cog._stream_info = AsyncMock(return_value=self.live)
        self.cog.stream_cache[1] = self.live
        self.event = {"chatter_user_id": "viewer", "chatter_user_name": "Viewer", "chatter_user_login": "viewer", "message": {"text": "hello"}}
        self.cog._send_twitch = AsyncMock()

    async def test_concurrent_counter_calls_are_atomic_and_persist(self):
        replies = await asyncio.gather(*[self.cog._render_shared(1, "{counter:deaths}", source="death") for _ in range(10)])
        self.assertEqual(sorted(map(int, replies)), list(range(1, 11)))
        self.assertEqual(self.cfg["response_counters"], {"deaths": 10})
        ctx = types.SimpleNamespace(guild=self.guild, send=AsyncMock())
        await self.cog.counter_reset(ctx, "deaths")
        self.assertEqual(self.cfg["response_counters"]["deaths"], 0)
        await self.cog.counter_set(ctx, "deaths", 50)
        self.assertEqual(await self.cog._render_shared(1, "{counter:deaths}"), "51")

    async def test_game_counters_resume_each_game_and_preserve_global_total(self):
        self.cfg.update(game_counters=["deaths"], response_counters={"deaths": 99})
        self.live["stream"].update(game_id="a", game_name="Game A")
        self.assertEqual(await self.cog._render_shared(1, "{counter:deaths} {counter:deaths}"), "1 1")
        self.live["stream"].update(game_id="b", game_name="Game B")
        self.assertEqual(await self.cog._render_shared(1, "{counter}", source="deaths"), "1")
        self.live["stream"].update(game_id="a", game_name="Game A")
        self.assertEqual(await self.cog._render_shared(1, "{counter:deaths} {game}"), "2 Game A")
        self.assertEqual(self.cfg["response_counters"]["deaths"], 99)
        self.cog._stream_info.assert_awaited_with(1, force=True)
        ctx = types.SimpleNamespace(guild=self.guild, send=AsyncMock())
        await self.cog.counter_set(ctx, "deaths", 50)
        await self.cog.counter_view(ctx, "deaths")
        self.assertIn("Game A: 50", ctx.send.call_args.args[0])
        await self.cog.counter_reset(ctx, "deaths")
        self.assertEqual(self.cfg["response_counters"]["game:stream:a:deaths"], 0)
        self.assertEqual(self.cfg["response_counters"]["game:stream:b:deaths"], 1)
        await self.cog.counter_pergame(ctx, "deaths", False)
        self.assertEqual(await self.cog._render_shared(1, "{counter:deaths}"), "100")

    async def test_game_counter_requires_live_category_and_is_broadcaster_specific(self):
        self.cfg["game_counters"] = ["deaths"]
        self.live["stream"]["game_id"] = "a"
        await asyncio.gather(*[self.cog._render_shared(1, "{counter:deaths}") for _ in range(5)])
        self.assertEqual(self.cfg["response_counters"]["game:stream:a:deaths"], 5)
        self.cfg["broadcaster_id"] = "other"
        self.live["broadcaster_id"] = "other"
        self.assertEqual(await self.cog._render_shared(1, "{counter:deaths}"), "1")
        before = copy.deepcopy(self.cfg["response_counters"])
        self.live["stream"] = None
        with self.assertRaises(module.BridgeError):
            await self.cog._render_shared(1, "{counter:deaths}")
        self.assertEqual(before, self.cfg["response_counters"])

    async def test_target_game_and_url_use_target_account_and_keep_broadcaster_game(self):
        self.cog._lookup_twitch = AsyncMock(return_value={"id": "target-id"})
        self.cog._token = AsyncMock(return_value=("client", {"access_token": "token"}))
        self.cog._request = AsyncMock(return_value=(200, {"data": [{"game_name": "Stardew Valley"}]}))
        self.cog._stream_values = AsyncMock(return_value={"game": "Minecraft"})
        for args in ("friend", "@friend"):
            text = await self.cog._render_shared(1, "{target}|{targeturl}|{targetgame}|{game}", args=args)
            self.assertEqual(text, "@friend|https://twitch.tv/friend|Stardew Valley|Minecraft")
            self.assertEqual(self.cog._request.call_args.kwargs["params"], {"broadcaster_id": "target-id"})

    async def test_target_lookup_is_optional_and_failed_game_has_fallback(self):
        self.cog._lookup_twitch = AsyncMock(side_effect=module.BridgeError("Unavailable"))
        self.assertEqual(await self.cog._render_shared(1, "{targeturl}", args="friend"), "https://twitch.tv/friend")
        self.cog._lookup_twitch.assert_not_awaited()
        self.assertEqual(await self.cog._render_shared(1, "{targetgame}", args="friend"), "Unknown game")
        self.cog._lookup_twitch.reset_mock()
        self.assertEqual(await self.cog._render_shared(1, "Game: {targetgame}; URL: {targeturl}", args=""), "Game: Unknown game; URL:")
        self.cog._lookup_twitch.assert_not_awaited()

    async def test_target_formats_bare_and_tagged_first_argument_and_preserves_args(self):
        for args, expected in [("Some_User", "@Some_User"), ("@Some_User", "@Some_User"),
                               ("Some_User extra text", "@Some_User"), ("", ""),
                               ("@@user", ""), ("https://twitch.tv/user", ""), ("<@123>", "")]:
            with self.subTest(args=args):
                text = await self.cog._render_shared(1, "Target: {target} | Args: {args}", args=args)
                self.assertEqual(text, " ".join(f"Target: {expected} | Args: {args}".split()))

    async def test_failed_render_does_not_increment_counter(self):
        with self.assertRaises(ValueError):
            await self.cog._render_shared(1, "{counter}" + "x" * 501, source="deaths")
        self.assertEqual(self.cfg["response_counters"], {})

    async def test_stream_fields_and_actor_url_work_in_the_shared_renderer(self):
        self.cog._stream_values = AsyncMock(return_value={"uptime": "1h 2m 3s", "title": "Title", "game": "Game", "viewers": 42})
        text = await self.cog._render_shared(1, "{user}|{uptime}|{title}|{game}|{viewers}|{url}", user="Viewer", login="viewer")
        self.assertEqual(text, "Viewer|1h 2m 3s|Title|Game|42|https://twitch.tv/viewer")

    async def test_todo_shared_storage_numbering_and_permissions(self):
        with self.assertRaises(module.BridgeError):
            await self.cog._todo_action(1, "add", "No", 0)
        await self.cog._todo_action(1, "add", "First", 1)
        await self.cog._todo_action(1, "add", "Second", 2)
        self.assertEqual(await self.cog._todo_action(1, "view", "", 1), ["1. First", "2. Second"])
        await self.cog._todo_action(1, "del", "1", 1)
        self.assertEqual(await self.cog._todo_action(1, "view", "", 1), ["1. Second"])
        with self.assertRaises(ValueError):
            await self.cog._todo_action(1, "del", "0", 1)

    async def test_todo_and_ads_mutations_cannot_cross_broadcasters(self):
        self.assertTrue(await self.cog._tool_twitch_command(1, "foreign", self.event, "todo", "add bad"))
        self.assertEqual(self.cfg["todo_items"], [])
        with self.assertRaises(module.BridgeError):
            await self.cog._ad_api(1, "POST", "channels/commercial", "channel:edit:commercial", body={"length": 60}, expected="foreign")
        self.cog._request.assert_not_awaited()

    async def test_streak_and_ever_greeting_only_count_once_per_stream(self):
        self.cfg["streak_settings"]["enabled"] = True
        self.cfg["first_message"]["enabled"] = True
        await self.cog._record_presence(1, "stream", self.event)
        await self.cog._record_presence(1, "stream", self.event)
        self.assertEqual(self.cfg["viewer_data"]["stream"]["viewer"]["streak"], 1)
        self.assertEqual(self.cog.tool_queue.qsize(), 1)
        self.live["stream"] = dict(self.live["stream"], id="s2", started_at="2026-11-23T12:00:00Z")
        await self.cog._record_presence(1, "stream", self.event)
        self.assertEqual(self.cfg["viewer_data"]["stream"]["viewer"]["streak"], 2)
        self.assertEqual(self.cog.tool_queue.qsize(), 1)

    async def test_per_stream_and_specific_user_greetings(self):
        self.cfg["first_message"].update(enabled=True, mode="stream", everyone=False, users={"viewer": "Follow {user} at {url}"})
        await self.cog._record_presence(1, "stream", self.event)
        self.live["stream"] = dict(self.live["stream"], id="s2", started_at="2026-11-23T12:00:00Z")
        await self.cog._record_presence(1, "stream", self.event)
        self.assertEqual(self.cog.tool_queue.qsize(), 2)
        await self.cog._record_presence(1, "stream", dict(self.event, chatter_user_id="other"))
        self.assertEqual(self.cog.tool_queue.qsize(), 2)

    async def test_offline_messages_do_not_create_greetings_or_streaks(self):
        self.cfg["streak_settings"]["enabled"] = True
        self.cfg["first_message"]["enabled"] = True
        self.live["stream"] = None
        await self.cog._record_presence(1, "stream", self.event)
        self.assertEqual(self.cfg["viewer_data"], {})
        self.assertTrue(self.cog.tool_queue.empty())

    async def test_attendance_is_namespaced_by_broadcaster(self):
        self.cfg["streak_settings"]["enabled"] = True
        await self.cog._record_presence(1, "stream", self.event)
        self.cfg["broadcaster_id"] = "other"
        self.live.update(broadcaster_id="other", stream=dict(self.live["stream"], id="other1", user_id="other"))
        await self.cog._record_presence(1, "other", self.event)
        self.assertEqual(self.cfg["viewer_data"]["other"]["viewer"]["streak"], 1)
        self.assertEqual(self.cfg["viewer_data"]["stream"]["viewer"]["streak"], 1)

    async def test_forget_removes_all_tracking_and_per_user_templates(self):
        self.cfg["viewer_data"] = {"stream": {"viewer": {"streak": 10}}}
        self.cfg["first_message"]["users"]["viewer"] = "Hello"
        await self.cog._forget_tool_viewer(1, "viewer")
        self.assertEqual(self.cfg["viewer_data"]["stream"], {})
        self.assertEqual(self.cfg["first_message"]["users"], {})

    async def test_timer_edits_preserve_flags_and_unedited_fields(self):
        self.cfg["timers"]["socials"] = {"seconds": 600, "message": "Old message", "enabled": False, "live_only": False}
        ctx = types.SimpleNamespace(guild=self.guild, send=AsyncMock())
        await self.cog.timer_interval(ctx, "SOCIALS", 900)
        self.assertEqual(self.cfg["timers"]["socials"], {"seconds": 900, "message": "Old message", "enabled": False, "live_only": False})
        await self.cog.timer_message(ctx, "socials", message="Playing {game}")
        self.assertEqual(self.cfg["timers"]["socials"]["seconds"], 900)
        self.assertEqual(self.cfg["timers"]["socials"]["message"], "Playing {game}")
        await self.cog.timer_edit(ctx, "socials", 1200, message="New message")
        self.assertEqual(self.cfg["timers"]["socials"], {"seconds": 1200, "message": "New message", "enabled": False, "live_only": False})
        await self.cog.timer_edit(ctx, "socials", 1500)
        self.assertEqual(self.cfg["timers"]["socials"]["message"], "New message")
        self.assertEqual(self.cfg["automation_revision"], 4)
        self.assertTrue(self.cog.tools_wakeup.is_set())

    async def test_invalid_or_missing_timer_edits_do_not_change_settings(self):
        self.cfg["timers"]["socials"] = {"seconds": 600, "message": "Old", "enabled": True, "live_only": True}
        before = copy.deepcopy(self.cfg["timers"])
        ctx = types.SimpleNamespace(guild=self.guild, send=AsyncMock())
        await self.cog.timer_edit(ctx, "socials", 9, message="Changed")
        await self.cog.timer_message(ctx, "socials", message="")
        await self.cog.timer_edit(ctx, "missing", 600, message="Changed")
        self.assertEqual(self.cfg["timers"], before)
        self.assertEqual(self.cfg["automation_revision"], 0)

    async def test_timer_view_displays_full_template_with_safe_pagination(self):
        self.cfg["timers"]["socials"] = {"seconds": 600, "message": "x" * 4000, "enabled": True, "live_only": True}
        ctx = types.SimpleNamespace(guild=self.guild, send=AsyncMock())
        await self.cog.timer_view(ctx, "socials")
        self.assertEqual(ctx.send.await_count, 3)
        self.assertTrue(all(len(call.args[0]) <= 1800 for call in ctx.send.call_args_list))
        self.assertIn("x" * 4000, "".join(call.args[0] for call in ctx.send.call_args_list))
        self.assertTrue(all(call.kwargs["suppress_embeds"] for call in ctx.send.call_args_list))

    async def test_timers_wait_an_interval_and_skip_offline_streams(self):
        self.cfg["timers"]["socials"] = {"seconds": 10, "enabled": True, "live_only": True, "message": "Follow us"}
        self.cog.tool_configs = {1: self.cfg}
        await self.cog._tick_tools()
        self.assertTrue(self.cog.tool_queue.empty())
        for key in self.cog.timer_due:
            self.cog.timer_due[key] = 0
        await self.cog._tick_tools()
        self.assertEqual(self.cog.tool_queue.qsize(), 1)
        self.live["stream"] = None
        for key in self.cog.timer_due:
            self.cog.timer_due[key] = 0
        await self.cog._tick_tools()
        self.assertEqual(self.cog.tool_queue.qsize(), 1)

    async def test_warning_leads_send_only_one_late_threshold_and_deduplicate(self):
        self.cfg["ad_settings"].update(enabled=True, leads=[300, 60, 10, 1])
        self.cog.tool_configs = {1: self.cfg}
        self.cog.ad_cache[1] = {"broadcaster_id": "stream", "next_ad_at": time.time() + 50, "fetched": time.monotonic()}
        await self.cog._tick_tools()
        self.assertEqual(self.cog.tool_queue.qsize(), 1)
        item = self.cog.tool_queue.get_nowait()[2]
        self.assertEqual(item["lead"], 60)
        self.cog.tool_queue.task_done()
        await self.cog._tick_tools()
        self.assertTrue(self.cog.tool_queue.empty())

    async def test_ad_warning_receipts_persist_and_new_schedules_rearm(self):
        self.assertTrue(await self.cog._reserve_ad_notice(1, 100, 60))
        self.assertFalse(await self.cog._reserve_ad_notice(1, 100, 60))
        self.assertTrue(await self.cog._reserve_ad_notice(1, 400, 60))

    async def test_snooze_updates_schedule_and_pauses_warnings_for_five_minutes(self):
        at = time.time() + 350
        self.cog._ad_api = AsyncMock(side_effect=[("stream", {"next_ad_at": at, "snooze_count": 1}),
                                                ("stream", {"next_ad_at": at, "duration": 60, "snooze_count": 1})])
        text = await self.cog._ad_action(1, "snooze")
        self.assertIn("five minutes", text)
        self.assertAlmostEqual(self.cfg["ad_warning_pause_until"] - time.time(), 300, delta=2)
        self.assertEqual(self.cog.ad_cache[1]["next_ad_at"], at)
        self.assertFalse(self.cog.ad_pending)

    async def test_ad_failure_is_not_retried_and_does_not_claim_success(self):
        self.cog._ad_api = AsyncMock(side_effect=module.BridgeError("No snoozes left"))
        with self.assertRaises(module.BridgeError):
            await self.cog._ad_action(1, "snooze")
        self.cog._ad_api.assert_awaited_once()
        self.assertFalse(self.cog.ad_pending)

    async def test_manual_ads_follow_twitch_cooldown_and_refetch_actual_schedule(self):
        at = time.time() + 900
        self.cog._ad_api = AsyncMock(side_effect=[("stream", {"length": 60, "retry_after": 480}),
                                                ("stream", {"next_ad_at": at, "duration": 60})])
        self.assertIn("started a 60-second", await self.cog._ad_action(1, "run", 60))
        self.assertEqual(self.cog.ad_cache[1]["next_ad_at"], at)
        self.assertEqual(self.cog._ad_api.call_args_list[0].kwargs["body"], {"length": 60})
        with self.assertRaises(module.BridgeError):
            await self.cog._ad_action(1, "run", 60)
        self.assertEqual(self.cog._ad_api.await_count, 2)

    async def test_cannot_run_commercials_offline(self):
        self.live["stream"] = None
        self.cog._ad_api = AsyncMock()
        with self.assertRaises(module.BridgeError):
            await self.cog._ad_action(1, "run", 60)
        self.cog._ad_api.assert_not_awaited()

    async def test_twitch_viewers_cannot_force_or_snooze_ads(self):
        self.cog._ad_action = AsyncMock()
        with self.assertRaises(module.BridgeError):
            await self.cog._tool_twitch_command(1, "stream", self.event, "ads", "run 60")
        self.cog._ad_action.assert_not_awaited()

    async def test_trigger_cooldowns_and_command_exclusion(self):
        self.cfg["chat_triggers"]["hello"] = {"word": "hello", "message": "Hi {user}", "enabled": True, "cooldown": 30}
        for text in ("HELLO", "hello again", "!hello"):
            await self.cog.tool_chat_queue.put((1, "stream", dict(self.event, message={"text": text})))
        task = asyncio.create_task(self.cog._tool_chat_loop())
        await asyncio.wait_for(self.cog.tool_chat_queue.join(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.cog.tool_queue.qsize(), 1)

    async def test_changed_automation_settings_drop_queued_messages(self):
        self.cfg["chat_triggers"]["hello"] = {"enabled": True}
        self.cog._enqueue_tool(1, "stream", "trigger", "hello", "Hi", revision=0)
        self.cfg["automation_revision"] = 1
        task = asyncio.create_task(self.cog._tool_send_loop())
        await asyncio.wait_for(self.cog.tool_queue.join(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.cog._send_twitch.assert_not_awaited()

    async def test_migrated_streak_includes_the_current_live_stream(self):
        self.cog._lookup_twitch = AsyncMock(return_value={"id": "viewer", "login": "viewer"})
        self.cfg["streak_settings"]["enabled"] = True
        ctx = types.SimpleNamespace(guild=self.guild, send=AsyncMock())
        await self.cog.streak_set(ctx, "viewer", 20)
        await self.cog._record_presence(1, "stream", self.event)
        self.assertEqual(self.cfg["viewer_data"]["stream"]["viewer"]["streak"], 20)
        await self.cog.streak_add(ctx, "viewer", 5)
        self.assertEqual(self.cfg["viewer_data"]["stream"]["viewer"]["streak"], 25)

    async def test_snooze_quiet_period_prevents_warning_claims_until_it_ends(self):
        self.cfg["ad_settings"]["enabled"] = True
        self.cog.tool_configs = {1: self.cfg}
        self.cog.ad_cache[1] = {"broadcaster_id": "stream", "next_ad_at": time.time() + 200, "fetched": time.monotonic()}
        self.cog.ad_pause_until[1] = time.time() + 100
        await self.cog._tick_tools()
        self.assertTrue(self.cog.tool_queue.empty())
        self.assertFalse(self.cog.ad_claimed)
        self.cog.ad_pause_until[1] = 0
        await self.cog._tick_tools()
        self.assertEqual(self.cog.tool_queue.qsize(), 1)

    async def test_warning_refetches_schedule_before_sending(self):
        self.cfg["ad_settings"]["enabled"] = True
        at = time.time() + 60
        self.cog.ad_cache[1] = {"broadcaster_id": "stream", "next_ad_at": at, "fetched": time.monotonic()}
        self.cog._refresh_ads = AsyncMock(return_value={"next_ad_at": at + 300})
        self.cog._enqueue_tool(1, "stream", "ad", "ads", "Soon", ad_at=at, lead=60, revision=0)
        task = asyncio.create_task(self.cog._tool_send_loop())
        await asyncio.wait_for(self.cog.tool_queue.join(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.cog._send_twitch.assert_not_awaited()
        self.assertEqual(self.cfg["ad_notices"], {})

    async def test_red_user_deletion_erases_linked_twitch_tracking(self):
        self.cfg["member_links"]["99"] = {"twitch_id": "viewer", "login": "viewer"}
        self.cfg["viewer_data"] = {"stream": {"viewer": {"streak": 10, "greeted": True}}}
        await self.cog.red_delete_data_for_user(requester="user", user_id=99)
        self.assertEqual(self.cfg["viewer_data"]["stream"], {})
        self.assertEqual(self.cfg["member_links"], {})
