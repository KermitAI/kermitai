import types
import unittest
from unittest.mock import AsyncMock

from test_bridge import module
import test_stream_tools as stream_tests

ACCESS = module.StreamToolsMixin._discord_level.__globals__["discord_access"]


def context(role):
    guild = types.SimpleNamespace(id=1, owner_id=10)
    author = types.SimpleNamespace(id=10 if role == "guild_owner" else 20,
        guild_permissions=types.SimpleNamespace(administrator=role == "administrator", manage_guild=role == "manage_guild"))
    bot = types.SimpleNamespace(is_owner=AsyncMock(return_value=role == "bot_owner"),
        is_admin=AsyncMock(return_value=role == "red_admin"), is_mod=AsyncMock(return_value=role == "moderator"))
    return types.SimpleNamespace(bot=bot, guild=guild, author=author, send=AsyncMock())


class DiscordPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_staff_command_groups_have_requested_access(self):
        names = ["twitchcommand", "command_alias", "alias_add", "alias_remove", "alias_list",
            "twitchannounce", "twitchshoutout", "twitchtimer", "twitchtrigger", "twitchcounter",
            "twitchevents", "twitchads", "twitchfirst", "twitchstreak", "twitchtodo", "todo_permission", "tstream"]
        for name in names:
            checks = getattr(getattr(module.TwitchBridge, name), "__bridge_checks__", [])
            self.assertTrue(checks, name)
            for role in ("bot_owner", "guild_owner", "administrator", "red_admin", "moderator", "member", "manage_guild"):
                ctx = context(role)
                allowed = all([await check(ctx) for check in checks])
                self.assertEqual(allowed, role not in ("member", "manage_guild"), (name, role))

    async def test_connection_and_globals_remain_bot_owner_only(self):
        for name in ("twitchset", "twitchglobal"):
            checks = getattr(getattr(module.TwitchBridge, name), "__bridge_checks__", [])
            self.assertTrue(checks)
            for role in ("bot_owner", "guild_owner", "administrator", "moderator", "member"):
                self.assertEqual(all([await check(context(role)) for check in checks]), role == "bot_owner", (name, role))

    async def test_roles_allow_owners_and_admins_but_not_moderators(self):
        checks = module.TwitchBridge.twitchroles.__bridge_checks__
        for role in ("bot_owner", "guild_owner", "administrator", "red_admin", "moderator", "member", "manage_guild"):
            self.assertEqual(all([await check(context(role)) for check in checks]),
                role in ("bot_owner", "guild_owner", "administrator", "red_admin"), role)

    async def test_linking_has_no_staff_or_owner_restriction(self):
        self.assertFalse(getattr(module.TwitchBridge.twitchlink, "__bridge_checks__", []))

    async def test_discord_action_levels_follow_same_access_tiers(self):
        cog = module.TwitchBridge.__new__(module.TwitchBridge)
        for role, expected in [("bot_owner", 2), ("guild_owner", 2), ("administrator", 1),
                               ("red_admin", 1), ("moderator", 1), ("member", 0), ("manage_guild", 0)]:
            ctx = context(role)
            cog.bot = ctx.bot
            self.assertEqual(await cog._discord_level(ctx), expected, role)


class TwitchPermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        stream_tests.StreamToolsTests.setUp(self)

    def moderator(self):
        return dict(self.event, badges=[{"set_id": "moderator"}])

    async def test_shoutout_dispatch_requires_twitch_moderator(self):
        import asyncio
        self.cog.command_queue = asyncio.Queue()
        self.cog._shoutout = AsyncMock()
        for name in ("so", "shoutout"):
            for event in (self.event, self.moderator()):
                message = dict(event, message={"text": "!" + name + " friend"})
                self.cog.command_queue.put_nowait((1, "stream", message))
        task = asyncio.create_task(self.cog._command_loop())
        await asyncio.wait_for(self.cog.command_queue.join(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.cog._shoutout.await_count, 2)

    async def test_regular_viewers_cannot_read_todo_or_ad_status(self):
        self.cog._refresh_ads = AsyncMock()
        for name, args in [("todo", ""), ("todo", "view"), ("todo", "add X"), ("ads", "status"),
                           ("ads", "run 60"), ("ads", "snooze")]:
            with self.subTest(name=name, args=args), self.assertRaises(module.BridgeError):
                await self.cog._tool_twitch_command(1, "stream", self.event, name, args)
        self.cog._refresh_ads.assert_not_awaited()
        self.cog._send_twitch.assert_not_awaited()

    async def test_moderators_can_run_and_snooze_ads(self):
        self.cog._ad_action = AsyncMock(return_value="Done")
        for action in ("run 60", "snooze"):
            await self.cog._tool_twitch_command(1, "stream", self.moderator(), "ads", action)
        self.assertEqual(self.cog._ad_action.await_count, 2)
        self.assertEqual(self.cog._send_twitch.await_count, 2)

    async def test_discord_and_twitch_share_todo_and_block_nonstaff_fallback(self):
        ctx = context("moderator")
        self.cog.bot = ctx.bot
        await self.cog.todo_add(ctx, text="Discord item")
        await self.cog._tool_twitch_command(1, "stream", self.moderator(), "todo", "add Twitch item")
        self.assertEqual(self.cfg["todo_items"], ["Discord item", "Twitch item"])
        await self.cog._tool_twitch_command(1, "stream", self.moderator(), "todo", "")
        self.assertIn("1. Discord item", self.cog._send_twitch.call_args_list[-2].args[1])
        await self.cog.todo_view(ctx)
        self.assertIn("2. Twitch item", ctx.send.call_args.args[0])
        member_ctx = context("member")
        self.cog.bot = member_ctx.bot
        await self.cog._todo_reply(member_ctx, "view", "")
        self.assertNotIn("Discord item", member_ctx.send.call_args.args[0])

    async def test_metadata_lookups_and_updates_require_moderators(self):
        for field in ("title", "game", "category", "tags", "language"):
            for value in ("", "New value"):
                with self.subTest(field=field, value=value), self.assertRaises(module.BridgeError):
                    await self.cog._channel_action(1, field, value, 0)
        self.cog._request.assert_not_awaited()

    async def test_legacy_everyone_todo_setting_does_not_bypass_moderator_floor(self):
        self.cfg["todo_permission"] = "everyone"
        for action in ("view", "add"):
            with self.assertRaises(module.BridgeError):
                await self.cog._todo_action(1, action, "Unauthorized", 0)
        self.assertEqual(self.cfg["todo_items"], [])
