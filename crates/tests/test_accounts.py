"""Exercise persistence boundaries without requiring a running Discord bot."""
import asyncio
import copy
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def decorator(*args, **kwargs):
    def wrap(fn):
        fn.command = decorator
        return fn
    return wrap


class Value:
    def __init__(self, group):
        self.group = group

    async def __call__(self):
        return copy.deepcopy(self.group.data["collections"])

    async def set(self, value):
        self.group.data["collections"] = copy.deepcopy(value)


class Group:
    def __init__(self, data):
        self.data = data
        self.collections = Value(self)

    async def all(self):
        return copy.deepcopy(self.data)

    async def clear(self):
        self.data.clear()
        self.data.update(policy.empty_collection())


class Config:
    def __init__(self):
        self.guild = Group({"enabled": True, "cooldown": 0,
                            "tiers": {"a": {"weight": 1, "items": {"Gem": {"weight": 1, "value": 10}}}},
                            "collections": {"discord": {}, "twitch": {}}})
        self.members = {}

    def guild_from_id(self, guild_id):
        return self.guild

    def member_from_ids(self, guild_id, user_id):
        return self.members.setdefault(user_id, Group(policy.empty_collection()))

    async def all_guilds(self):
        return {1: self.guild.data}

    async def all_members(self):
        return {1: self.members}


root = Path(__file__).parents[1]
pkg = types.ModuleType("crate_test_package")
pkg.__path__ = [str(root)]
commands = types.SimpleNamespace(Cog=object, guild_only=decorator, group=decorator,
                                 admin_or_permissions=decorator, mod_or_permissions=decorator)
modules = {
    "crate_test_package": pkg,
    "discord": types.SimpleNamespace(Member=object, Role=object, TextChannel=object),
    "redbot": types.ModuleType("redbot"),
    "redbot.core": types.SimpleNamespace(Config=object, commands=commands),
    "redbot.core.utils": types.ModuleType("redbot.core.utils"),
    "redbot.core.utils.chat_formatting": types.SimpleNamespace(pagify=lambda text, **kw: [text]),
}
with patch.dict(sys.modules, modules):
    spec = importlib.util.spec_from_file_location("crate_test_package.crates", root / "crates.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    policy = sys.modules["crate_test_package.policy"]


class AccountTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = module.Crates.__new__(module.Crates)
        self.cog.config = Config()
        self.cog.locks = {}

    async def test_discord_operates_without_twitch(self):
        await self.cog._pull_reward(1, discord_id=99)
        self.assertEqual((await self.cog.get_discord_collection(1, 99))["inventory"], {"Gem": 1})
        self.assertEqual(self.cog.config.guild.data["collections"]["twitch"], {})

    async def test_merge_legacy_inventory_once_and_route_future_pulls(self):
        legacy = self.cog.config.member_from_ids(1, 99).data
        legacy.update(inventory={"Gem": 2, "Old": 1}, pulls=3, value=25, last_pull=9999999999)
        await self.cog.pull_twitch(1, "123", "viewer", "r1")
        merged = await self.cog.link_verified_twitch(1, "123", "renamed", 99)
        self.assertEqual(merged, {"inventory": {"Gem": 3, "Old": 1}, "pulls": 4,
                                  "value": 35, "last_pull": 9999999999,
                                  "last_pulls": {"discord": 9999999999, "twitch": 9999999999}})
        self.assertEqual(await self.cog.link_verified_twitch(1, "123", "renamed", 99), merged)
        self.assertTrue((await self.cog.pull_twitch(1, "123", "renamed", "r1"))["duplicate"])
        # Set a realistic timestamp to allow another pull after checking merge cooldown.
        state = self.cog.config.guild.data["collections"]
        state["discord"]["99"]["last_pull"] = 0
        await self.cog.pull_twitch(1, "123", "renamed", "r2")
        self.assertEqual((await self.cog.get_discord_collection(1, 99))["pulls"], 5)
        self.assertEqual(await self.cog.get_twitch_collection(1, "123"),
                         await self.cog.get_discord_collection(1, 99))

    async def test_duplicate_concurrent_events_award_once(self):
        results = await asyncio.gather(*[self.cog.pull_twitch(1, "123", "viewer", "same") for _ in range(8)])
        self.assertEqual(sum(not r["duplicate"] for r in results), 1)
        self.assertEqual((await self.cog.get_twitch_collection(1, "123"))["pulls"], 1)

    async def test_conflicting_links_are_rejected(self):
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        with self.assertRaises(ValueError):
            await self.cog.link_verified_twitch(1, "123", "viewer", 100)
        with self.assertRaises(ValueError):
            await self.cog.link_verified_twitch(1, "456", "other", 99)

    async def test_linked_accounts_share_cooldown(self):
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        self.cog.config.guild.data["cooldown"] = 86400
        await self.cog._pull_reward(1, discord_id=99)
        with self.assertRaises(ValueError):
            await self.cog.pull_twitch(1, "123", "viewer", "r1")
        self.assertNotIn("r1", self.cog.config.guild.data["collections"]["twitch"]["123"]["redemptions"])

    async def test_disabled_and_empty_catalog_do_not_award(self):
        self.cog.config.guild.data["enabled"] = False
        with self.assertRaises(ValueError):
            await self.cog.pull_twitch(1, "123", "viewer", "r1")
        self.cog.config.guild.data.update(enabled=True, tiers={})
        with self.assertRaises(ValueError):
            await self.cog.pull_twitch(1, "123", "viewer", "r1")
        self.assertIsNone(await self.cog.get_twitch_collection(1, "123"))

    async def test_user_deletion_removes_legacy_merged_and_linked_data(self):
        await self.cog._pull_reward(1, discord_id=99)
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        await self.cog.red_delete_data_for_user(requester="discord_deleted_user", user_id=99)
        self.assertIsNone(await self.cog.get_twitch_collection(1, "123"))
        self.assertEqual((await self.cog.get_discord_collection(1, 99))["pulls"], 0)

    async def test_receipts_and_links_survive_cog_restart(self):
        await self.cog.pull_twitch(1, "123", "viewer", "r1")
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        restarted = module.Crates.__new__(module.Crates)
        restarted.config = self.cog.config
        restarted.locks = {}
        self.assertTrue((await restarted.pull_twitch(1, "123", "viewer", "r1"))["duplicate"])
        self.assertEqual((await restarted.get_discord_collection(1, 99))["pulls"], 1)

    async def test_twitch_deletion_keeps_already_merged_discord_items(self):
        await self.cog.pull_twitch(1, "123", "viewer", "r1")
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        await self.cog.delete_twitch_data(1, "123")
        self.assertIsNone(await self.cog.get_twitch_collection(1, "123"))
        self.assertEqual((await self.cog.get_discord_collection(1, 99))["inventory"], {"Gem": 1})


class TwitchMethodTests(unittest.IsolatedAsyncioTestCase):
    setUp = AccountTests.setUp
    async def test_command_requires_enabled_mode_and_exact_text(self):
        with self.assertRaises(ValueError):
            await self.cog.pull_twitch_command(1, "123", "viewer", "m1", "!crate pull")
        self.cog.config.guild.data["twitch_mode"] = "command"
        with self.assertRaises(ValueError):
            await self.cog.pull_twitch_command(1, "123", "viewer", "m1", "!crate pull extra")
        with self.assertRaises(ValueError):
            await self.cog.pull_twitch(1, "123", "viewer", "r1")
        result = await self.cog.pull_twitch_command(1, "123", "viewer", "m1", " !CRATE pull ")
        self.assertFalse(result["duplicate"])
        self.assertEqual((await self.cog.get_twitch_collection(1, "123"))["pulls"], 1)

    async def test_command_deduplication_and_separate_event_ids(self):
        self.cog.config.guild.data["twitch_mode"] = "both"
        results = await asyncio.gather(*[
            self.cog.pull_twitch_command(1, "123", "viewer", "same", "!crate pull")
            for _ in range(8)])
        self.assertEqual(sum(not r["duplicate"] for r in results), 1)
        await self.cog.pull_twitch(1, "123", "viewer", "same")
        self.assertEqual((await self.cog.get_twitch_collection(1, "123"))["pulls"], 2)
        self.cog.config.guild.data["twitch_mode"] = "off"
        self.assertTrue((await self.cog.pull_twitch_command(
            1, "123", "viewer", "same", "!crate pull"))["duplicate"])
        with self.assertRaises(ValueError):
            await self.cog.pull_twitch_command(1, "123", "viewer", "new", "!crate pull")

    async def test_command_and_points_share_cooldown(self):
        self.cog.config.guild.data.update(twitch_mode="both", cooldown=86400,
                                         twitch_command="!open")
        await self.cog.pull_twitch_command(1, "123", "viewer", "m1", "!open")
        with self.assertRaises(ValueError):
            await self.cog.pull_twitch(1, "123", "viewer", "r1")
        with self.assertRaises(ValueError):
            await self.cog.pull_twitch_command(1, "123", "viewer", "m2", "!open")


class PlatformCooldownTests(unittest.IsolatedAsyncioTestCase):
    setUp = AccountTests.setUp

    async def test_separate_platforms_and_twitch_methods_share_one_timer(self):
        self.cog.config.guild.data.update(shared_cooldown=False, cooldown=100, twitch_mode="both")
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        with patch.object(module.time, "time", return_value=1000):
            await self.cog._pull_reward(1, discord_id=99)
            await self.cog.pull_twitch_command(1, "123", "viewer", "m1", "!crate pull")
            with self.assertRaises(ValueError):
                await self.cog._pull_reward(1, discord_id=99)
            with self.assertRaises(ValueError):
                await self.cog.pull_twitch(1, "123", "viewer", "r1")
        self.assertEqual((await self.cog.get_discord_collection(1, 99))["pulls"], 2)

    async def test_separate_twitch_pull_does_not_block_discord(self):
        self.cog.config.guild.data.update(shared_cooldown=False, cooldown=100)
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        with patch.object(module.time, "time", return_value=1000):
            await self.cog.pull_twitch(1, "123", "viewer", "r1")
            await self.cog._pull_reward(1, discord_id=99)

    async def test_switching_to_shared_uses_latest_pull_and_back_preserves_timers(self):
        self.cog.config.guild.data.update(shared_cooldown=False, cooldown=100)
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        with patch.object(module.time, "time", return_value=1000):
            await self.cog._pull_reward(1, discord_id=99)
        with patch.object(module.time, "time", return_value=1050):
            await self.cog.pull_twitch(1, "123", "viewer", "r1")
        self.cog.config.guild.data["shared_cooldown"] = True
        with patch.object(module.time, "time", return_value=1100):
            with self.assertRaises(ValueError):
                await self.cog._pull_reward(1, discord_id=99)
            self.cog.config.guild.data["shared_cooldown"] = False
            await self.cog._pull_reward(1, discord_id=99)
            with self.assertRaises(ValueError):
                await self.cog.pull_twitch(1, "123", "viewer", "r2")

    async def test_legacy_timestamp_retained_on_both_platforms(self):
        self.cog.config.guild.data.update(shared_cooldown=False, cooldown=100)
        legacy = self.cog.config.member_from_ids(1, 99).data
        legacy["last_pull"] = 1000
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        with patch.object(module.time, "time", return_value=1050):
            with self.assertRaises(ValueError):
                await self.cog._pull_reward(1, discord_id=99)
            with self.assertRaises(ValueError):
                await self.cog.pull_twitch(1, "123", "viewer", "r1")

    async def test_linking_preserves_each_platform_timer(self):
        self.cog.config.guild.data.update(shared_cooldown=False, cooldown=100)
        with patch.object(module.time, "time", return_value=1000):
            await self.cog._pull_reward(1, discord_id=99)
        with patch.object(module.time, "time", return_value=1050):
            await self.cog.pull_twitch(1, "123", "viewer", "r1")
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        with patch.object(module.time, "time", return_value=1100):
            await self.cog._pull_reward(1, discord_id=99)
            with self.assertRaises(ValueError):
                await self.cog.pull_twitch(1, "123", "viewer", "r2")


class GrantTests(unittest.IsolatedAsyncioTestCase):
    setUp = AccountTests.setUp

    async def test_grant_stacks_value_without_pull_or_cooldown(self):
        await self.cog._pull_reward(1, discord_id=99)
        before = await self.cog.get_discord_collection(1, 99)
        await self.cog.grant_item(1, 99, "a", "Gem", 3)
        after = await self.cog.get_discord_collection(1, 99)
        self.assertEqual(after["inventory"], {"Gem": 4})
        self.assertEqual(after["value"], 40)
        self.assertEqual(after["pulls"], before["pulls"])
        self.assertEqual(after["last_pull"], before["last_pull"])
        self.assertEqual(after["last_pulls"], before["last_pulls"])

    async def test_gift_only_member_excluded_and_link_sees_grant(self):
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        await self.cog.grant_item(1, 99, "a", "Gem", 2)
        data = await self.cog.get_twitch_collection(1, "123")
        self.assertEqual(data["inventory"], {"Gem": 2})
        self.assertEqual(policy.ranking({99: data}, {99}), [])

    async def test_invalid_grants_do_not_write(self):
        for tier, name, qty in (("bad", "Gem", 1), ("a", "unknown", 1),
                                ("a", "Gem", 0), ("a", "Gem", -1),
                                ("a", "Gem", 1_000_001)):
            with self.assertRaises(ValueError):
                await self.cog.grant_item(1, 99, tier, name, qty)
        self.cog.config.guild.data["tiers"]["a"]["items"]["Gem"]["empty"] = True
        with self.assertRaises(ValueError):
            await self.cog.grant_item(1, 99, "a", "Gem", 1)
        self.assertEqual(self.cog.config.guild.data["collections"]["discord"], {})


class RemovalTests(unittest.IsolatedAsyncioTestCase):
    setUp = AccountTests.setUp

    async def test_partial_and_full_removal_preserve_pull_history(self):
        await self.cog._pull_reward(1, discord_id=99)
        await self.cog.grant_item(1, 99, "a", "Gem", 3)
        before = await self.cog.get_discord_collection(1, 99)
        await self.cog.remove_inventory_item(1, 99, "Gem", 2)
        after = await self.cog.get_discord_collection(1, 99)
        self.assertEqual(after["inventory"], {"Gem": 2})
        self.assertEqual(after["value"], 20)
        for key in ("pulls", "last_pull", "last_pulls"):
            self.assertEqual(after[key], before[key])
        await self.cog.remove_inventory_item(1, 99, "Gem", 2)
        after = await self.cog.get_discord_collection(1, 99)
        self.assertEqual(after["inventory"], {})
        self.assertEqual(after["value"], 0)
        self.assertEqual(after["pulls"], 1)

    async def test_invalid_removal_does_not_change_data(self):
        await self.cog.grant_item(1, 99, "a", "Gem", 1)
        before = await self.cog.get_discord_collection(1, 99)
        for name, quantity in (("Gem", 0), ("Gem", -1), ("Gem", 2),
                               ("Missing", 1), ("Gem", 1_000_001)):
            with self.assertRaises(ValueError):
                await self.cog.remove_inventory_item(1, 99, name, quantity)
        self.assertEqual(await self.cog.get_discord_collection(1, 99), before)

    async def test_deleted_catalog_item_can_be_removed_from_linked_inventory(self):
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        await self.cog.grant_item(1, 99, "a", "Gem", 2)
        self.cog.config.guild.data["tiers"] = {}
        await self.cog.remove_inventory_item(1, 99, "Gem", 1)
        data = await self.cog.get_twitch_collection(1, "123")
        self.assertEqual(data["inventory"], {"Gem": 1})
        self.assertEqual(data["value"], 20)

    async def test_value_deduction_never_becomes_negative(self):
        await self.cog.grant_item(1, 99, "a", "Gem", 1)
        self.cog.config.guild.data["tiers"]["a"]["items"]["Gem"]["value"] = 100
        await self.cog.remove_inventory_item(1, 99, "Gem", 1)
        self.assertEqual((await self.cog.get_discord_collection(1, 99))["value"], 0)


class LuckAccountTests(unittest.IsolatedAsyncioTestCase):
    setUp = AccountTests.setUp

    def configure_roles(self):
        self.cog.config.guild.data["luck_roles"] = {"1": 25, "2": 50, "3": 100}
        member = types.SimpleNamespace(roles=[types.SimpleNamespace(id=1), types.SimpleNamespace(id=2)])
        guild = types.SimpleNamespace(get_member=lambda uid: member if uid == 99 else None)
        self.cog.bot = types.SimpleNamespace(get_guild=lambda gid: guild)

    async def test_highest_bonus_applies_to_discord_and_linked_twitch(self):
        self.configure_roles()
        with patch.object(module, "choose_reward", return_value=("a", "Gem", 10)) as choose:
            await self.cog._pull_reward(1, discord_id=99)
            self.assertEqual(choose.call_args.args[1], 50)
            await self.cog.link_verified_twitch(1, "123", "viewer", 99)
            await self.cog.pull_twitch(1, "123", "viewer", "r1")
            self.assertEqual(choose.call_args.args[1], 50)
            await self.cog.pull_twitch(1, "456", "unlinked", "r2")
            self.assertEqual(choose.call_args.args[1], 0)

    async def test_missing_member_has_no_bonus_and_duplicate_does_not_roll(self):
        self.configure_roles()
        self.assertEqual(self.cog.member_luck(1, 1234, self.cog.config.guild.data), 0)
        await self.cog.pull_twitch(1, "123", "viewer", "r1")
        with patch.object(module, "choose_reward") as choose:
            result = await self.cog.pull_twitch(1, "123", "viewer", "r1")
            self.assertTrue(result["duplicate"])
            choose.assert_not_called()


class CooldownResetTests(unittest.IsolatedAsyncioTestCase):
    setUp = AccountTests.setUp

    async def test_reset_preserves_rewards_and_allows_immediate_pull_in_both_modes(self):
        self.cog.config.guild.data["cooldown"] = 86400
        await self.cog._pull_reward(1, discord_id=99)
        before = await self.cog.get_discord_collection(1, 99)
        await self.cog.reset_member_cooldown(1, 99)
        after = await self.cog.get_discord_collection(1, 99)
        for key in ("inventory", "pulls", "value"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(after["last_pull"], 0)
        self.assertEqual(after["last_pulls"], {"discord": 0, "twitch": 0})
        await self.cog._pull_reward(1, discord_id=99)
        self.cog.config.guild.data["shared_cooldown"] = False
        await self.cog.reset_member_cooldown(1, 99)
        await self.cog._pull_reward(1, discord_id=99)

    async def test_linked_twitch_reset_preserves_receipts(self):
        await self.cog.link_verified_twitch(1, "123", "viewer", 99)
        self.cog.config.guild.data.update(cooldown=86400, shared_cooldown=False)
        await self.cog.pull_twitch(1, "123", "viewer", "r1")
        await self.cog.reset_member_cooldown(1, 99)
        self.assertTrue((await self.cog.pull_twitch(1, "123", "viewer", "r1"))["duplicate"])
        await self.cog.pull_twitch(1, "123", "viewer", "r2")
        self.assertEqual((await self.cog.get_twitch_collection(1, "123"))["pulls"], 2)

    async def test_legacy_reset_persists_without_restoring_old_timestamp(self):
        self.cog.config.member_from_ids(1, 99).data.update(last_pull=9999999999, pulls=2)
        await self.cog.reset_member_cooldown(1, 99)
        await self.cog.reset_member_cooldown(1, 99)
        data = await self.cog.get_discord_collection(1, 99)
        self.assertEqual(data["last_pull"], 0)
        self.assertEqual(data["pulls"], 2)
