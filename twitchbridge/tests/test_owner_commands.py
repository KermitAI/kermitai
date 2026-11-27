import asyncio
import copy
import types
import unittest
from unittest.mock import AsyncMock

from test_bridge import module, policy
import test_aliases as state
import test_global_commands as fixtures
import test_permissions as permissions


class OwnerCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.GlobalCommandTests.setUp(self)
        self.cog.settings_lock = asyncio.Lock()
        self.global_data["owner"] = {"user_id": "9001", "login": "lee"}
        self.cog.config.owner_twitch = state.ConfigValue(self.global_data, "owner")
        self.ctx.author = types.SimpleNamespace(id=99, display_name="Lee")
        self.cog.bot.is_owner = AsyncMock(return_value=True)
        self.cfg["custom_commands"]["hello"].update(permission="owner", cooldown=0, response="Owner response")

    async def test_owner_account_can_run_as_regular_viewer_and_after_rename(self):
        for level in (0, 1, 2):
            self.assertEqual(await self.cog._prepare_command(1, "hello", "", "twitch", level, "Lee",
                twitch_id="9001", twitch_login="new_username"), "Owner response")

    async def test_moderator_or_broadcaster_role_never_grants_owner_access(self):
        self.cfg["custom_commands"]["hello"]["response"] = "{counter:secret}"
        for level in (0, 1, 2):
            self.assertIsNone(await self.cog._prepare_command(1, "hello", "", "twitch", level, "Lee",
                twitch_id="another_id", twitch_login="lee"))
        self.assertEqual(self.cfg["response_counters"], {})
        self.assertEqual(self.cog.cooldowns, {})

    async def test_missing_or_cleared_owner_account_blocks_all_twitch_roles(self):
        await self.cog.clear_owner_account(self.ctx)
        for level in (0, 1, 2):
            self.assertIsNone(await self.cog._prepare_command(1, "hello", "", "twitch", level, "Lee", twitch_id="9001"))
        self.assertIsNone(await self.cog._prepare_command(1, "hello", "", "twitch", 2, "Lee"))

    async def test_setting_account_uses_lookup_id_and_replacement_takes_effect_immediately(self):
        self.cog._lookup_twitch = AsyncMock(return_value={"id": "12345", "login": "newowner"})
        await self.cog.owner_account(self.ctx, "@newowner")
        self.assertEqual(self.global_data["owner"], {"user_id": "12345", "login": "newowner"})
        self.assertIsNone(await self.cog._prepare_command(1, "hello", "", "twitch", 2, "Lee", twitch_id="9001"))
        self.assertEqual(await self.cog._prepare_command(1, "hello", "", "twitch", 0, "New", twitch_id="12345"), "Owner response")
        await self.cog.owner_account(self.ctx)
        self.assertIn("12345", self.ctx.send.call_args.args[0])

    async def test_failed_account_lookup_keeps_previous_account(self):
        before = copy.deepcopy(self.global_data["owner"])
        self.cog._lookup_twitch = AsyncMock(side_effect=module.BridgeError("No account"))
        await self.cog.owner_account(self.ctx, "missing")
        self.assertEqual(self.global_data["owner"], before)

    async def test_global_owner_command_and_alias_work_across_streams(self):
        await self.cog.global_add(self.ctx, "secret", response="Global owner")
        await self.cog.global_permission(self.ctx, "secret", "owner")
        await self.cog.global_cooldown(self.ctx, "secret", 0)
        await self.cog.global_alias_add(self.ctx, "secret", "privatealias")
        for guild in (1, 2):
            self.assertEqual(await self.cog._prepare_command(guild, "privatealias", "", "twitch", 0, "Lee", twitch_id="9001"), "Global owner")
            self.assertIsNone(await self.cog._prepare_command(guild, "secret", "", "twitch", 2, "Broadcaster", twitch_id="9999"))

    async def test_discord_owner_permission_uses_bot_ownership_not_linked_twitch_id_or_guild_role(self):
        self.assertIsNone(await self.cog._prepare_command(1, "hello", "", "discord", 2, "GuildOwner", twitch_id="9001"))
        self.assertEqual(await self.cog._prepare_command(1, "hello", "", "discord", 2, "BotOwner", discord_owner=True), "Owner response")

    async def test_other_staff_cannot_change_delete_preview_or_alias_owner_commands(self):
        self.cfg["custom_commands"]["hello"]["aliases"] = ["secretalias"]
        before = copy.deepcopy(self.cfg["custom_commands"])
        self.cog.bot.is_owner.return_value = False
        for action in (
            lambda: self.cog.command_permission(self.ctx, "hello", "everyone"),
            lambda: self.cog.command_edit(self.ctx, "hello", response="Changed"),
            lambda: self.cog.command_cooldown(self.ctx, "hello", 0),
            lambda: self.cog.command_remove(self.ctx, "hello"),
            lambda: self.cog.command_remove(self.ctx, "secretalias"),
            lambda: self.cog.alias_add(self.ctx, "hello", "newalias"),
            lambda: self.cog.alias_remove(self.ctx, "secretalias"),
            lambda: self.cog.command_preview(self.ctx, "hello")):
            await action()
            self.assertIn("Only the bot owner", self.ctx.send.call_args.args[0])
            self.assertEqual(self.cfg["custom_commands"], before)

    async def test_only_bot_owner_can_assign_or_remove_owner_flag(self):
        self.cfg["custom_commands"]["hello"]["permission"] = "everyone"
        self.cog.bot.is_owner.return_value = False
        await self.cog.command_permission(self.ctx, "hello", "owner")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["permission"], "everyone")
        self.cog.bot.is_owner.return_value = True
        await self.cog.command_permission(self.ctx, "hello", "owner")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["permission"], "owner")
        await self.cog.command_permission(self.ctx, "hello", "everyone")
        self.assertEqual(self.cfg["custom_commands"]["hello"]["permission"], "everyone")

    async def test_account_commands_remain_bot_owner_only(self):
        for name in ("owner_account", "clear_owner_account"):
            checks = getattr(getattr(module.TwitchBridge, name), "__bridge_checks__", [])
            for role in ("bot_owner", "guild_owner", "administrator", "moderator", "member"):
                self.assertEqual(all([await check(permissions.context(role)) for check in checks]), role == "bot_owner")

    def test_policy_owner_flag_is_identity_based_and_platform_scoped(self):
        record = {"platform": "twitch", "permission": "owner"}
        self.assertFalse(policy.command_allowed(record, "twitch", 2))
        self.assertTrue(policy.command_allowed(record, "twitch", 0, is_owner=True))
        self.assertFalse(policy.command_allowed(record, "discord", 2, is_owner=True))
        self.assertNotIn("!hello", " ".join(policy.public_command_pages(self.cfg)))
