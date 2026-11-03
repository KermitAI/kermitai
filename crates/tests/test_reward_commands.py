"""Reward command side effects use normal bot invocation after persistence."""
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_accounts as accounts


class RewardCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        accounts.AccountTests.setUp(self)
        self.executor = types.SimpleNamespace(id=1)
        self.recipient = types.SimpleNamespace(id=99)
        self.source = types.SimpleNamespace(author=self.recipient, content=".crate pull")
        self.ctx = types.SimpleNamespace(message=self.source, prefix=".")
        self.channel = types.SimpleNamespace(fetch_message=AsyncMock(return_value=self.source))
        self.guild = types.SimpleNamespace(
            get_member=lambda uid: {1: self.executor, 99: self.recipient}.get(uid),
            get_channel=lambda cid: self.channel if cid == 10 else None,
        )
        async def context(message):
            return types.SimpleNamespace(message=message, valid=True, command_failed=False,
                                         command=types.SimpleNamespace(cog=None))
        self.cog.bot = types.SimpleNamespace(
            get_guild=lambda gid: self.guild, is_owner=AsyncMock(return_value=True),
            get_context=AsyncMock(side_effect=context), invoke=AsyncMock(),
            get_command=lambda name: types.SimpleNamespace(qualified_name="crate resetcooldown"),
        )
        self.action = {"command": "payout {user} 100", "executor_id": 1,
                       "channel_id": 10, "message_id": 20, "prefix": "."}
        self.item = self.cog.config.guild.data["tiers"]["a"]["items"]["Gem"]
        self.item["reward_commands"] = [self.action]

    async def test_command_substitutes_recipient_but_invokes_as_configuring_owner(self):
        await self.cog._pull_reward(1, discord_id=99, action_context=self.ctx)
        message = self.cog.bot.get_context.call_args.args[0]
        self.assertEqual(message.content, ".payout <@99> 100")
        self.assertIs(message.author, self.executor)
        self.assertEqual(self.source.content, ".crate pull")
        self.assertIs(self.source.author, self.recipient)
        self.cog.bot.invoke.assert_awaited_once()
        self.assertEqual(self.cog.render_reward_command("x {user_id} {guild_id}", 99, 123), "x 99 123")

    async def test_award_persisted_before_command_and_reset_does_not_deadlock(self):
        self.action["command"] = "crate resetcooldown {user}"
        self.cog.config.guild.data["cooldown"] = 86400
        async def invoke(ctx):
            self.assertEqual((await self.cog.get_discord_collection(1, 99))["pulls"], 1)
            await self.cog.reset_member_cooldown(1, 99)
        self.cog.bot.invoke.side_effect = invoke
        await self.cog._pull_reward(1, discord_id=99, action_context=self.ctx)
        data = await self.cog.get_discord_collection(1, 99)
        self.assertEqual(data["last_pull"], 0)
        self.assertEqual(data["inventory"], {"Gem": 1})

    async def test_duplicate_twitch_event_does_not_repeat_commands(self):
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        first = await self.cog.pull_twitch(1, "123", "viewer", "r1")
        duplicate = await self.cog.pull_twitch(1, "123", "viewer", "r1")
        self.assertIn("Command completed.", first["command_results"])
        self.assertTrue(duplicate["duplicate"])
        self.cog.bot.invoke.assert_awaited_once()
        self.channel.fetch_message.assert_awaited_once_with(20)

    async def test_unlinked_and_missing_owner_skip_commands(self):
        result = await self.cog.pull_twitch(1, "123", "viewer", "r1")
        self.assertIn("Skipped:", result["command_results"][0])
        self.cog.bot.invoke.assert_not_awaited()
        self.cog.bot.is_owner.return_value = False
        result = await self.cog._pull_reward(1, discord_id=99, action_context=self.ctx)
        self.assertIn("no longer an owner", result["command_results"][0])
        self.cog.bot.invoke.assert_not_awaited()

    async def test_no_commands_for_manual_grants_or_empty_rewards(self):
        await self.cog.grant_item(1, 99, "a", "Gem", 2)
        self.cog.bot.invoke.assert_not_awaited()
        self.item["empty"] = True
        await self.cog._pull_reward(1, discord_id=99, action_context=self.ctx)
        self.cog.bot.invoke.assert_not_awaited()

    async def test_command_failure_keeps_item_and_is_not_retried(self):
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        self.cog.bot.invoke.side_effect = RuntimeError("failure")
        with patch.object(accounts.module.log, "exception"):
            result = await self.cog.pull_twitch(1, "123", "viewer", "r1")
        self.assertIn("Failed:", result["command_results"][0])
        self.assertEqual((await self.cog.get_discord_collection(1, 99))["inventory"], {"Gem": 1})
        await self.cog.pull_twitch(1, "123", "viewer", "r1")
        self.cog.bot.invoke.assert_awaited_once()

    async def test_recursive_crates_command_is_rejected(self):
        async def context(message):
            return types.SimpleNamespace(message=message, valid=True, command_failed=False,
                                         command=types.SimpleNamespace(cog=self.cog))
        self.cog.bot.get_context.side_effect = context
        self.cog.bot.get_command = lambda name: types.SimpleNamespace(qualified_name="crate pull")
        self.action["command"] = "crate pull"
        result = await self.cog._pull_reward(1, discord_id=99, action_context=self.ctx)
        self.assertIn("Skipped:", result["command_results"][0])
        self.cog.bot.invoke.assert_not_awaited()
