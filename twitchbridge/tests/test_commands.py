import asyncio
import copy
import types
import unittest
from unittest.mock import AsyncMock

from test_bridge import module, policy


class Settings:
    def __init__(self, data):
        self.data = data

    async def all(self):
        return copy.deepcopy(self.data)


class CommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = module.TwitchBridge.__new__(module.TwitchBridge)
        self.cfg = {"enabled": True, "broadcaster_id": "123", "broadcaster": "streamer",
                    "broadcaster_auth": {"client_id": "client"}, "command_prefix": "!",
                    "custom_commands": {"hello": {"response": "Hello {user}! {args} on {channel}",
                       "platform": "both", "permission": "everyone", "cooldown": 5}}}
        self.group = Settings(self.cfg)
        self.cog.config = types.SimpleNamespace(guild_from_id=lambda gid: self.group, guild=lambda guild: self.group)
        self.cog.command_locks = {}
        self.cog.cooldowns = {}
        self.cog.send_lock = asyncio.Lock()
        self.cog.last_send = 0
        self.cog._token = AsyncMock(return_value=("client", {"user_id": "bot", "access_token": "secret",
                                                            "scopes": ["user:write:chat"]}))
        self.cog._request = AsyncMock(return_value=(200, {"data": [{"is_sent": True, "message_id": "sent1"}]}))

    async def test_cooldown_is_shared_between_platforms_and_serialized(self):
        results = await asyncio.gather(*[
            self.cog._prepare_command(1, "hello", "args", platform, 0, "Viewer")
            for platform in ("twitch", "discord", "twitch")])
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertIn("Hello Viewer! args on streamer", results)

    async def test_permission_and_platform_fail_closed(self):
        record = self.cfg["custom_commands"]["hello"]
        record.update(permission="moderator", platform="twitch")
        self.assertIsNone(await self.cog._prepare_command(1, "hello", "", "twitch", 0, "viewer"))
        self.assertIsNone(await self.cog._prepare_command(1, "hello", "", "discord", 2, "owner"))
        self.assertIsNotNone(await self.cog._prepare_command(1, "hello", "", "twitch", 1, "mod"))

    async def test_paused_or_changed_broadcaster_never_replies(self):
        self.cfg["enabled"] = False
        self.assertIsNone(await self.cog._prepare_command(1, "hello", "", "twitch", 0, "viewer"))
        with self.assertRaises(module.BridgeError):
            await self.cog._send_twitch(1, "test")
        self.cfg["enabled"] = True
        with self.assertRaises(module.BridgeError):
            await self.cog._send_twitch(1, "test", expected_broadcaster="other")
        self.cog._request.assert_not_awaited()

    async def test_missing_write_scope_preserves_logging_but_refuses_send(self):
        self.cog._token.return_value = ("client", {"user_id": "bot", "access_token": "secret", "scopes": []})
        with self.assertRaises(module.BridgeError) as raised:
            await self.cog._send_twitch(1, "test")
        self.assertIn("authbot", str(raised.exception))
        self.cog._request.assert_not_awaited()

    async def test_sends_as_bot_to_verified_broadcaster(self):
        self.assertEqual(await self.cog._send_twitch(1, "test"), "sent1")
        request = self.cog._request.call_args.kwargs["json"]
        self.assertEqual(request, {"sender_id": "bot", "broadcaster_id": "123", "message": "test"})

    async def test_dropped_message_is_not_reported_as_sent(self):
        self.cog._request.return_value = (200, {"data": [{"is_sent": False, "drop_reason": {"message": "sensitive"}}]})
        with self.assertRaises(module.BridgeError) as raised:
            await self.cog._send_twitch(1, "test")
        self.assertNotIn("sensitive", str(raised.exception))
        self.cog._request.assert_awaited_once()

    async def test_http_rate_limit_is_not_retried(self):
        self.cog._request.return_value = (429, {})
        with self.assertRaises(module.BridgeError):
            await self.cog._send_twitch(1, "test")
        self.cog._request.assert_awaited_once()

    async def test_unknown_command_and_overlong_expansion_do_not_send(self):
        self.assertIsNone(await self.cog._prepare_command(1, "missing", "", "twitch", 0, "viewer"))
        with self.assertRaises(ValueError):
            await self.cog._prepare_command(1, "hello", "x" * 500, "twitch", 0, "viewer")
        self.assertEqual(self.cog.cooldowns, {})


    async def test_announcement_reports_partial_failure(self):
        channel = module.discord.TextChannel()
        channel.send = AsyncMock()
        self.cfg["announcements"] = 456
        ctx = types.SimpleNamespace(guild=types.SimpleNamespace(id=1, get_channel=lambda cid: channel), send=AsyncMock())
        self.cog._send_twitch = AsyncMock(side_effect=module.BridgeError("Twitch is unavailable"))
        await self.cog.twitchannounce(ctx, "both", message="Starting soon")
        channel.send.assert_awaited_once()
        report = ctx.send.call_args.args[0]
        self.assertIn("Twitch is unavailable", report)
        self.assertIn("Discord: sent", report)

    async def test_discord_listener_uses_saved_response_and_skips_registered_commands(self):
        guild = types.SimpleNamespace(id=1, owner_id=10)
        author = types.SimpleNamespace(id=20, bot=False, display_name="DiscordViewer",
                                       guild_permissions=types.SimpleNamespace(manage_guild=False))
        channel = types.SimpleNamespace(send=AsyncMock())
        message = types.SimpleNamespace(author=author, guild=guild, channel=channel, content=".hello testing")
        self.cog.bot = types.SimpleNamespace(cog_disabled_in_guild=AsyncMock(return_value=False),
            message_eligible_as_command=AsyncMock(return_value=True), get_context=AsyncMock(return_value=types.SimpleNamespace(valid=False)),
            get_valid_prefixes=AsyncMock(return_value=["."]), is_owner=AsyncMock(return_value=False), is_mod=AsyncMock(return_value=False))
        await self.cog.on_message(message)
        self.assertEqual(channel.send.call_args.args[0], "Hello DiscordViewer! testing on streamer")
        channel.send.reset_mock()
        self.cog.bot.get_context.return_value.valid = True
        await self.cog.on_message(message)
        channel.send.assert_not_awaited()

    async def test_queued_command_rechecks_current_broadcaster(self):
        self.cog.command_queue = asyncio.Queue()
        self.cog._send_twitch = AsyncMock()
        await self.cog.command_queue.put((1, "old", {"chatter_user_id": "user", "broadcaster_user_id": "old",
            "chatter_user_name": "viewer", "message": {"text": "!hello"}}))
        task = asyncio.create_task(self.cog._command_loop())
        await asyncio.wait_for(self.cog.command_queue.join(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.cog._send_twitch.assert_not_awaited()


class CommandPolicyTests(unittest.TestCase):
    def test_templates_are_not_recursive_and_preserve_literal_braces(self):
        self.assertEqual(policy.render_response("{user} {args} {channel} {unknown}",
            user="Alice", args="{user}", channel="streamer"), "Alice {user} streamer {unknown}")

    def test_command_names_and_lengths(self):
        self.assertEqual(policy.command_name("!Socials"), "socials")
        for value in ("twitchset", "a b", "a" * 33, ""):
            with self.assertRaises(ValueError):
                policy.command_name(value)
        for value in ("", "x" * 501):
            with self.assertRaises(ValueError):
                policy.chat_text(value)
        self.assertEqual(policy.chat_text("hello\nworld"), "hello world")

    def test_twitch_badges_map_to_permissions(self):
        self.assertEqual(policy.twitch_level({"chatter_user_id": "1", "broadcaster_user_id": "1"}), 2)
        self.assertEqual(policy.twitch_level({"chatter_user_id": "2", "broadcaster_user_id": "1",
                                              "badges": [{"set_id": "moderator"}]}), 1)
        self.assertEqual(policy.twitch_level({"chatter_user_id": "2", "broadcaster_user_id": "1",
                                              "badges": [{"set_id": "vip"}]}), 0)

    def test_prefixes_are_exact_and_args_preserved(self):
        self.assertEqual(policy.parse_command("!HELLO some args", "!"), ("hello", "some args"))
        self.assertIsNone(policy.parse_command("hello", "!"))
        self.assertIsNone(policy.parse_command("!", "!"))
