import asyncio
import copy
import types
import unittest
from unittest.mock import AsyncMock

from test_bridge import module, policy
import test_stream_tools as stream_tests
import test_permissions as permission_tests

Q = module.QuotesMixin._post_quote.__globals__


class QuoteChannel(module.discord.TextChannel):
    def __init__(self, guild, ident=123):
        self.guild, self.id = guild, ident
        self.send = AsyncMock()
        self.permissions = types.SimpleNamespace(view_channel=True, send_messages=True, embed_links=True)
    def permissions_for(self, member):
        return self.permissions


class QuoteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        stream_tests.StreamToolsTests.setUp(self)
        self.guild = types.SimpleNamespace(id=1, me=object())
        self.channel = QuoteChannel(self.guild)
        self.guild.get_channel = lambda ident: self.channel if ident == self.channel.id else None
        self.cog.bot = types.SimpleNamespace(get_guild=lambda gid: self.guild if gid == 1 else None,
            cog_disabled_in_guild=AsyncMock(return_value=False))
        self.cfg["quote_settings"] = {**Q["QUOTE_DEFAULTS"], "enabled": True, "channel": 123, "permission": "everyone"}
        self.cog.cooldowns = {}
        self.ctx = types.SimpleNamespace(guild=self.guild, send=AsyncMock())
        self.event = {"chatter_user_id": "viewer", "chatter_user_login": "viewer_name", "broadcaster_user_id": "stream"}
        self.cog._send_twitch = AsyncMock()

    async def post(self, text="An excellent quote!", event=None, bid="stream"):
        return await self.cog._post_quote(1, bid, event or self.event, text)

    async def test_embed_contains_quote_color_username_and_utc_footer(self):
        await self.post()
        call = self.channel.send.call_args
        embed = call.kwargs["embed"]
        self.assertEqual(embed.description, "An excellent quote!")
        self.assertEqual(embed.color, Q["QUOTE_DEFAULTS"]["color"])
        self.assertRegex(embed.footer.text, r"^Submitted by @viewer_name \| \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$")
        self.assertIn("allowed_mentions", call.kwargs)
        self.assertNotIn("suppress_embeds", call.kwargs)

    async def test_plain_message_has_footer_and_suppresses_mentions_and_previews(self):
        self.cfg["quote_settings"]["mode"] = "message"
        await self.post("@everyone https://example.com {counter}")
        call = self.channel.send.call_args
        self.assertIn("@everyone https://example.com {counter}", call.args[0])
        self.assertIn("Submitted by @viewer_name |", call.args[0])
        self.assertTrue(call.kwargs["suppress_embeds"])
        self.assertIn("allowed_mentions", call.kwargs)

    async def test_twitch_permission_matrix(self):
        events = [(self.event, 0), (dict(self.event, badges=[{"set_id": "moderator"}]), 1),
                  (dict(self.event, chatter_user_id="stream"), 2)]
        for permission, required in [("everyone", 0), ("moderator", 1), ("broadcaster", 2)]:
            self.cfg["quote_settings"]["permission"] = permission
            for event, level in events:
                self.cog.cooldowns.clear()
                self.channel.send.reset_mock()
                if level < required:
                    with self.assertRaises(module.BridgeError):
                        await self.post(event=event)
                    self.channel.send.assert_not_awaited()
                else:
                    await self.post(event=event)
                    self.channel.send.assert_awaited_once()

    async def test_paused_disabled_and_changed_routes_cannot_post(self):
        with self.assertRaises(module.BridgeError):
            await self.post(bid="foreign")
        self.cfg["enabled"] = False
        with self.assertRaises(module.BridgeError):
            await self.post()
        self.cfg["enabled"] = True
        self.cfg["quote_settings"]["enabled"] = False
        with self.assertRaises(module.BridgeError):
            await self.post()
        self.channel.send.assert_not_awaited()

    async def test_missing_channel_and_embed_permissions_prevent_post(self):
        self.cfg["quote_settings"]["channel"] = 999
        with self.assertRaises(module.BridgeError):
            await self.post()
        self.cfg["quote_settings"]["channel"] = 123
        self.channel.permissions.embed_links = False
        with self.assertRaises(module.BridgeError):
            await self.post()
        self.cfg["quote_settings"]["mode"] = "message"
        await self.post()
        self.channel.send.assert_awaited_once()

    async def test_cooldown_only_consumed_after_successful_post(self):
        self.channel.send.side_effect = module.discord.HTTPException()
        with self.assertRaises(module.BridgeError):
            await self.post()
        self.assertEqual(self.cog.cooldowns, {})
        self.channel.send.side_effect = None
        await self.post()
        with self.assertRaises(module.BridgeError):
            await self.post()
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_configuration_colors_and_chat_mode_alias(self):
        for color, expected in [("purple", 0x9B59B6), ("#112233", 0x112233), ("0xABCDEF", 0xABCDEF), ("black", 0)]:
            await self.cog.quote_set_color(self.ctx, color)
            self.assertEqual(self.cfg["quote_settings"]["color"], expected)
        await self.cog.quote_mode(self.ctx, "chat")
        self.assertEqual(self.cfg["quote_settings"]["mode"], "message")
        before = copy.deepcopy(self.cfg["quote_settings"])
        await self.cog.quote_set_color(self.ctx, "invalid")
        await self.cog.quote_mode(self.ctx, "invalid")
        await self.cog.quote_permission(self.ctx, "invalid")
        await self.cog.quote_cooldown(self.ctx, -1)
        self.assertEqual(self.cfg["quote_settings"], before)

    async def test_destination_must_be_same_server_and_enable_requires_channel(self):
        foreign = QuoteChannel(types.SimpleNamespace(id=2))
        await self.cog.quote_channel(self.ctx, foreign)
        self.assertEqual(self.cfg["quote_settings"]["channel"], 123)
        self.cfg["quote_settings"].update(enabled=False, channel=None)
        await self.cog.quote_enabled(self.ctx, True)
        self.assertFalse(self.cfg["quote_settings"]["enabled"])

    async def test_missing_username_empty_text_and_disabled_cog_do_not_post(self):
        for event, text in [(dict(self.event, chatter_user_login=""), "Hello"), (self.event, "")]:
            with self.assertRaises((module.BridgeError, ValueError)):
                await self.post(text, event=event)
        self.cog.bot.cog_disabled_in_guild.return_value = True
        with self.assertRaises(module.BridgeError):
            await self.post()
        self.channel.send.assert_not_awaited()

    async def test_dispatch_posts_once_and_confirms_in_twitch(self):
        self.cog.command_queue = asyncio.Queue()
        event = dict(self.event, message={"text": "!quote A Twitch quote"})
        self.cog.command_queue.put_nowait((1, "stream", event))
        task = asyncio.create_task(self.cog._command_loop())
        await asyncio.wait_for(self.cog.command_queue.join(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.channel.send.assert_awaited_once()
        self.cog._send_twitch.assert_awaited_once_with(1, "Quote sent to Discord.", expected_broadcaster="stream")

    async def test_staff_setup_access_and_reserved_names(self):
        for role in ("bot_owner", "guild_owner", "administrator", "red_admin", "moderator", "member"):
            checks = module.TwitchBridge.twitchquote.__bridge_checks__
            self.assertEqual(all([await check(permission_tests.context(role)) for check in checks]), role != "member")
        for name in ("quote", "twitchquote"):
            with self.assertRaises(ValueError):
                policy.command_name(name)

    async def test_defaults_are_disabled_and_require_moderator(self):
        settings = Q["quote_settings"]({})
        self.assertFalse(settings["enabled"])
        self.assertEqual(settings["permission"], "moderator")
