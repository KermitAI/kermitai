import asyncio
import copy
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch


def decorator(*args, **kwargs):
    def wrap(fn):
        fn.command = decorator
        return fn
    return wrap


class HTTPException(Exception):
    pass


class TextChannel:
    async def send(self, *args, **kwargs):
        pass


root = Path(__file__).parents[1]
pkg = types.ModuleType("bridge_test_package")
pkg.__path__ = [str(root)]
commands = types.SimpleNamespace(Cog=type("Cog", (), {"listener": staticmethod(decorator)}), is_owner=decorator, guild_only=decorator, group=decorator, command=decorator)
modules = {
    "bridge_test_package": pkg,
    "discord": types.SimpleNamespace(TextChannel=TextChannel, HTTPException=HTTPException,
                                     AllowedMentions=types.SimpleNamespace(none=lambda: None)),
    "aiohttp": types.SimpleNamespace(ClientError=type("ClientError", (Exception,), {})),
    "redbot": types.ModuleType("redbot"),
    "redbot.core": types.SimpleNamespace(Config=object, commands=commands),
}
with patch.dict(sys.modules, modules):
    spec = importlib.util.spec_from_file_location("bridge_test_package.twitchbridge", root / "twitchbridge.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    policy = sys.modules["bridge_test_package.policy"]


class Field:
    def __init__(self, value):
        self.value = value

    async def __call__(self):
        return copy.deepcopy(self.value)

    async def set(self, value):
        self.value = copy.deepcopy(value)


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = module.TwitchBridge.__new__(module.TwitchBridge)
        self.cog.config = types.SimpleNamespace(bot_auth=Field({}))
        self.cog.token_lock = asyncio.Lock()
        self.cog.settings_lock = asyncio.Lock()
        self.cog._client_id = AsyncMock(return_value="client")
        self.cog._request = AsyncMock()
        self.cog._restart = AsyncMock()
        self.cog.queue = asyncio.Queue(maxsize=2)
        self.cog.seen = policy.RecentMessages()
        self.cog.dropped = 0
        self.cog.command_queue = asyncio.Queue(maxsize=100)
        self.cog.command_dropped = 0
        self.routes = {"1": {"broadcaster_id": "123", "chatlog": 456}}
        self.message = {"metadata": {"message_timestamp": "2026-11-01T12:00:00Z"}, "payload": {
            "subscription": {"type": "channel.chat.message", "condition": {
                "user_id": "bot", "broadcaster_user_id": "123"}},
            "event": {"message_id": "m1", "broadcaster_user_id": "123",
                      "chatter_user_name": "Viewer", "message": {"text": "hello"}}}}

    def test_only_matching_verified_route_receives_message(self):
        self.cog._notification(self.message, self.routes, "wrong-bot")
        self.assertTrue(self.cog.queue.empty())
        self.cog._notification(self.message, self.routes, "bot")
        self.assertEqual(self.cog.queue.get_nowait()[:3], (1, "123", 456))
        self.cog._notification(self.message, self.routes, "bot")
        self.assertTrue(self.cog.queue.empty())

    def test_queue_is_bounded_and_reports_overflow(self):
        for i in range(5):
            self.message["payload"]["event"]["message_id"] = str(i)
            self.cog._notification(self.message, self.routes, "bot")
        self.assertEqual(self.cog.queue.qsize(), 2)
        self.assertEqual(self.cog.dropped, 3)

    async def test_refresh_rotates_and_validates_token(self):
        await self.cog.config.bot_auth.set({"client_id": "client", "user_id": "bot",
            "expires_at": 0, "refresh_token": "old", "access_token": "expired"})
        self.cog._request.side_effect = [(200, {"access_token": "new", "refresh_token": "rotated", "expires_in": 10000}),
            (200, {"client_id": "client", "user_id": "bot", "scopes": ["user:read:chat", "user:write:chat"]})]
        _, auth = await self.cog._token()
        self.assertEqual(auth["refresh_token"], "rotated")
        self.assertEqual((await self.cog.config.bot_auth())["access_token"], "new")
        await self.cog._token()
        self.assertEqual(self.cog._request.await_count, 2)

    async def test_mismatched_client_requires_reauthorization(self):
        await self.cog.config.bot_auth.set({"client_id": "other"})
        with self.assertRaises(module.BridgeError):
            await self.cog._token()
        self.cog._request.assert_not_awaited()

    async def test_refresh_errors_do_not_expose_tokens(self):
        await self.cog.config.bot_auth.set({"client_id": "client", "user_id": "bot", "expires_at": 0,
                                           "refresh_token": "secret", "access_token": "secret"})
        self.cog._request.return_value = (400, {"message": "secret"})
        with self.assertRaises(module.BridgeError) as raised:
            await self.cog._token()
        self.assertNotIn("secret", str(raised.exception))

    async def test_wrong_broadcaster_cannot_be_linked(self):
        self.cog._request.side_effect = [(200, {"verification_uri": "https://www.twitch.tv/activate",
            "user_code": "code", "device_code": "device", "interval": 1, "expires_in": 60}),
            (200, {"access_token": "token", "refresh_token": "refresh", "expires_in": 100}),
            (200, {"client_id": "client", "login": "imposter", "user_id": "999", "scopes": ["user:read:chat", "user:write:chat"]})]
        user = types.SimpleNamespace(send=AsyncMock())
        with patch.object(module.asyncio, "sleep", new=AsyncMock()):
            await self.cog._authorize(user, 1, "expected")
        self.cog._restart.assert_not_awaited()
        self.assertIn("did not match", user.send.call_args.args[0])

    async def test_bot_authorization_stores_verified_identity(self):
        self.cog._request.side_effect = [(200, {"verification_uri": "https://www.twitch.tv/activate",
            "user_code": "code", "device_code": "device", "interval": 1, "expires_in": 60}),
            (400, {"message": "authorization_pending"}),
            (200, {"access_token": "token", "refresh_token": "refresh", "expires_in": 100}),
            (200, {"client_id": "client", "login": "paimon", "user_id": "bot", "scopes": ["user:read:chat", "user:write:chat"]})]
        user = types.SimpleNamespace(send=AsyncMock())
        with patch.object(module.asyncio, "sleep", new=AsyncMock()):
            await self.cog._authorize(user)
        self.assertEqual((await self.cog.config.bot_auth())["user_id"], "bot")
        self.cog._restart.assert_awaited_once()

    async def test_stale_queued_destination_is_discarded(self):
        group = types.SimpleNamespace(all=AsyncMock(return_value={"enabled": True, "chatlog": 999,
                                                                  "broadcaster_id": "123"}))
        self.cog.config.guild_from_id = lambda gid: group
        self.cog.bot = types.SimpleNamespace(get_guild=lambda gid: self.fail("Stale destination must not be resolved"))
        await self.cog.queue.put((1, "123", 456, "old message"))
        task = asyncio.create_task(self.cog._deliver())
        await asyncio.wait_for(self.cog.queue.join(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


    async def test_websocket_handoff_transfers_subscription_without_recreating(self):
        welcome = {"metadata": {"message_type": "session_welcome"},
                   "payload": {"session": {"id": "session1", "keepalive_timeout_seconds": 10}}}
        reconnect = {"metadata": {"message_type": "session_reconnect"},
                     "payload": {"session": {"reconnect_url": "wss://eventsub.wss.twitch.tv/ws?session=next"}}}
        old = types.SimpleNamespace(receive_json=AsyncMock(side_effect=[welcome, reconnect]), close=AsyncMock())
        new = types.SimpleNamespace(receive_json=AsyncMock(side_effect=[welcome, asyncio.CancelledError()]), close=AsyncMock())
        self.cog.http = types.SimpleNamespace(ws_connect=AsyncMock(side_effect=[old, new]))
        self.cog._token = AsyncMock(return_value=("client", {}))
        self.cog._request.return_value = (202, {})
        with self.assertRaises(asyncio.CancelledError):
            await self.cog._listen(self.routes, "client", {"access_token": "token", "user_id": "bot"})
        self.assertEqual(self.cog._request.await_count, 1)
        old.close.assert_awaited()
        new.close.assert_awaited()
        request = self.cog._request.call_args.kwargs["json"]
        self.assertEqual(request["condition"], {"broadcaster_user_id": "123", "user_id": "bot"})
        self.assertEqual(request["transport"]["session_id"], "session1")

    async def test_subscription_failure_closes_socket(self):
        welcome = {"metadata": {"message_type": "session_welcome"},
                   "payload": {"session": {"id": "session1", "keepalive_timeout_seconds": 10}}}
        ws = types.SimpleNamespace(receive_json=AsyncMock(return_value=welcome), close=AsyncMock())
        self.cog.http = types.SimpleNamespace(ws_connect=AsyncMock(return_value=ws))
        self.cog._request.return_value = (403, {"message": "private response"})
        with self.assertRaises(module.BridgeError):
            await self.cog._listen(self.routes, "client", {"access_token": "token", "user_id": "bot"})
        ws.close.assert_awaited_once()


    def test_own_bot_is_logged_without_triggering_commands(self):
        self.message["payload"]["event"].update(chatter_user_id="bot", message={"text": "!hello"})
        self.cog._notification(self.message, self.routes, "bot")
        self.assertEqual(self.cog.queue.qsize(), 1)
        self.assertTrue(self.cog.command_queue.empty())

    def test_shared_chat_cannot_trigger_commands_from_another_channel(self):
        self.message["payload"]["event"].update(chatter_user_id="viewer", message={"text": "!hello"}, source_broadcaster_user_id="foreign")
        self.cog._notification(self.message, self.routes, "bot")
        self.assertTrue(self.cog.command_queue.empty())

    def test_twitch_commands_work_without_a_discord_log_destination(self):
        self.routes["1"]["chatlog"] = None
        self.message["payload"]["event"].update(chatter_user_id="viewer", message={"text": "!hello"})
        self.cog._notification(self.message, self.routes, "bot")
        self.assertEqual(self.cog.command_queue.qsize(), 1)
        self.assertTrue(self.cog.queue.empty())


class PolicyTests(unittest.TestCase):
    def test_login_rejects_urls_and_markdown(self):
        self.assertEqual(policy.login_name(" Viewer_1 "), "viewer_1")
        for value in ("https://twitch.tv/viewer", "@everyone", "", "a b"):
            with self.assertRaises(ValueError):
                policy.login_name(value)

    def test_reconnect_cannot_send_credentials_to_another_host(self):
        self.assertEqual(policy.reconnect_url("wss://eventsub.wss.twitch.tv/ws?session=1"),
                         "wss://eventsub.wss.twitch.tv/ws?session=1")
        for url in ("ws://eventsub.wss.twitch.tv/ws", "wss://evil.test/ws", "wss://eventsub.wss.twitch.tv.evil/ws",
                    "wss://user@eventsub.wss.twitch.tv/ws", "wss://eventsub.wss.twitch.tv:444/ws"):
            with self.assertRaises(ValueError):
                policy.reconnect_url(url)

    def test_formatting_bounds_and_escapes_content(self):
        line = policy.log_line({"chatter_user_name": "**name**", "message": {"text": "<@123>\n" + "x" * 3000}},
                               "2026-11-01T12:00:00Z")
        self.assertLessEqual(len(line), 1900)
        self.assertNotIn("\n", line)
        self.assertIn("UTC", line)
        self.assertNotIn("<@123>", line)

    def test_recent_message_cache_is_bounded(self):
        cache = policy.RecentMessages(2)
        self.assertTrue(cache.accept("1"))
        self.assertFalse(cache.accept("1"))
        cache.accept("2")
        cache.accept("3")
        self.assertEqual(len(cache.items), 2)
