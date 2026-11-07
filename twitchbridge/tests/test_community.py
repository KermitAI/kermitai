import asyncio
import copy
import time
import types
import unittest
from unittest.mock import AsyncMock, patch

from test_bridge import module, policy


class Field:
    def __init__(self, data, key):
        self.data, self.key = data, key

    async def __call__(self):
        return copy.deepcopy(self.data[self.key])

    async def set(self, value):
        self.data[self.key] = copy.deepcopy(value)

    async def __aenter__(self):
        self.working = copy.deepcopy(self.data[self.key])
        return self.working

    async def __aexit__(self, *exc):
        if exc[0] is None:
            self.data[self.key] = self.working


class Group:
    def __init__(self, data):
        self.data = data

    async def all(self):
        return copy.deepcopy(self.data)

    def __getattr__(self, key):
        return Field(self.data, key)


class Role:
    def __init__(self, rid):
        self.id = rid
        self.managed = False
        self.permissions = types.SimpleNamespace(administrator=False)

    def is_default(self):
        return False

    def __lt__(self, other):
        return self.id < other.id


class CommunityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = module.TwitchBridge.__new__(module.TwitchBridge)
        self.cfg = {"broadcaster_id": "stream", "broadcaster": "streamer", "enabled": True,
                    "member_links": {}, "role_mappings": {"moderator": 10}, "managed_roles": {},
                    "roles_enabled": True, "role_auth": {}, "command_prefix": "!"}
        self.group = Group(self.cfg)
        self.cog.config = types.SimpleNamespace(guild_from_id=lambda gid: self.group, guild=lambda guild: self.group,
                                                 all_guilds=AsyncMock(return_value={1: self.cfg}))
        self.cog.settings_lock = asyncio.Lock()
        self.cog.command_locks = {}
        self.cog.pending_links = {}
        self.cog.link_attempts = {}
        self.cog.shoutout_cooldowns = {}
        self.cog.member_auth_tasks = {}
        self.cog.pending_device_links = {}
        self.cog.link_generation = {}
        self.cog._request = AsyncMock()
        self.cog._restart = AsyncMock()
        self.cog._client_id = AsyncMock(return_value="client")
        self.cog._role_token = AsyncMock(return_value=("client", {"access_token": "secret"}))
        self.cog._fetch_role_users = AsyncMock(return_value={"viewer"})
        self.role = Role(10)
        self.member = types.SimpleNamespace(id=99, roles=[], send=AsyncMock(), add_roles=AsyncMock(), remove_roles=AsyncMock())
        self.guild = types.SimpleNamespace(id=1, name="Server", get_member=lambda uid: self.member if uid == 99 else None,
            fetch_member=AsyncMock(return_value=self.member), get_role=lambda rid: self.role if rid == 10 else None,
            me=types.SimpleNamespace(top_role=Role(100), guild_permissions=types.SimpleNamespace(manage_roles=True)))
        self.cog.bot = types.SimpleNamespace(get_guild=lambda gid: self.guild)
        self.event = {"chatter_user_id": "viewer", "chatter_user_login": "viewer"}
        self.cog.pending_links[(1, 99)] = {"code": "private", "expires": time.monotonic() + 600,
            "twitch_id": "viewer", "login": "viewer", "broadcaster_id": "stream"}

    async def test_only_requested_twitch_identity_can_complete_link_once(self):
        self.assertFalse(await self.cog._complete_member_link(1, "stream", {"chatter_user_id": "attacker"}, "private"))
        self.assertTrue(await self.cog._complete_member_link(1, "stream", self.event, "private"))
        self.assertEqual(self.cfg["member_links"]["99"]["twitch_id"], "viewer")
        self.assertFalse(await self.cog._complete_member_link(1, "stream", self.event, "private"))
        self.member.send.assert_awaited_once()

    async def test_expired_wrong_server_and_changed_broadcaster_codes_fail(self):
        self.assertFalse(await self.cog._complete_member_link(2, "stream", self.event, "private"))
        self.assertFalse(await self.cog._complete_member_link(1, "other", self.event, "private"))
        self.cog.pending_links[(1, 99)]["expires"] = 0
        self.assertFalse(await self.cog._complete_member_link(1, "stream", self.event, "private"))
        self.assertEqual(self.cfg["member_links"], {})

    async def test_duplicate_identity_and_account_reassignment_are_rejected(self):
        self.cfg["member_links"]["100"] = {"twitch_id": "viewer", "login": "viewer"}
        self.assertFalse(await self.cog._complete_member_link(1, "stream", self.event, "private"))
        self.cfg["member_links"] = {"99": {"twitch_id": "other", "login": "other"}}
        self.assertFalse(await self.cog._complete_member_link(1, "stream", self.event, "private"))

    async def test_role_sync_adds_and_tracks_only_new_grants(self):
        self.cfg["member_links"]["99"] = {"twitch_id": "viewer"}
        await self.cog._sync_roles(self.guild)
        self.member.add_roles.assert_awaited_once()
        self.assertEqual(self.cfg["managed_roles"], {"99": [10]})
        self.cfg["managed_roles"] = {}
        self.member.roles = [self.role]
        self.member.add_roles.reset_mock()
        await self.cog._sync_roles(self.guild)
        self.assertEqual(self.cfg["managed_roles"], {})
        self.member.add_roles.assert_not_awaited()

    async def test_status_loss_removes_tracked_grants_only(self):
        self.cfg["member_links"]["99"] = {"twitch_id": "viewer"}
        self.member.roles = [self.role]
        self.cog._fetch_role_users.return_value = set()
        await self.cog._sync_roles(self.guild)
        self.member.remove_roles.assert_not_awaited()
        self.cfg["managed_roles"] = {"99": [10]}
        await self.cog._sync_roles(self.guild)
        self.member.remove_roles.assert_awaited_once()
        self.assertEqual(self.cfg["managed_roles"], {})

    async def test_twitch_lookup_failure_preserves_roles(self):
        self.cfg["member_links"]["99"] = {"twitch_id": "viewer"}
        self.cfg["managed_roles"] = {"99": [10]}
        self.member.roles = [self.role]
        self.cog._fetch_role_users.side_effect = module.BridgeError("Unavailable")
        with self.assertRaises(module.BridgeError):
            await self.cog._sync_roles(self.guild)
        self.member.remove_roles.assert_not_awaited()
        self.member.add_roles.assert_not_awaited()
        self.assertEqual(self.cfg["managed_roles"], {"99": [10]})

    async def test_multiple_statuses_share_one_role_without_premature_removal(self):
        self.cfg["member_links"]["99"] = {"twitch_id": "viewer"}
        self.cfg["managed_roles"] = {"99": [10]}
        self.cfg["role_mappings"]["vip"] = 10
        self.member.roles = [self.role]
        self.cog._fetch_role_users.side_effect = [set(), {"viewer"}]
        await self.cog._sync_roles(self.guild)
        self.member.remove_roles.assert_not_awaited()

    async def test_higher_managed_and_administrator_roles_are_not_granted(self):
        self.cfg["member_links"]["99"] = {"twitch_id": "viewer"}
        for kind in ("higher", "managed", "admin"):
            self.role.id = 101 if kind == "higher" else 10
            self.role.managed = kind == "managed"
            self.role.permissions.administrator = kind == "admin"
            await self.cog._sync_roles(self.guild)
        self.member.add_roles.assert_not_awaited()

    async def test_unlink_removes_tracking_and_no_crate_api_is_called(self):
        self.cfg["member_links"]["99"] = {"twitch_id": "viewer"}
        self.cfg["managed_roles"] = {"99": [10]}
        self.member.roles = [self.role]
        await self.cog._unlink_member(1, 99)
        self.assertEqual(self.cfg["member_links"], {})
        self.assertEqual(self.cfg["managed_roles"], {})
        self.assertEqual(self.cog.pending_links, {})
        self.member.remove_roles.assert_awaited_once()

    async def test_no_mappings_cleans_up_previously_owned_grants(self):
        self.cfg["member_links"]["99"] = {"twitch_id": "viewer"}
        self.cfg["role_mappings"] = {}
        self.cfg["managed_roles"] = {"99": [10]}
        self.member.roles = [self.role]
        await self.cog._sync_roles(self.guild)
        self.member.remove_roles.assert_awaited_once()

    async def test_failed_unlink_cleanup_retains_retry_ledger_but_deletion_erases_it(self):
        self.cfg["member_links"]["99"] = {"twitch_id": "viewer"}
        self.cfg["managed_roles"] = {"99": [10]}
        self.member.roles = [self.role]
        self.member.remove_roles.side_effect = module.discord.HTTPException()
        await self.cog._unlink_member(1, 99)
        self.assertEqual(self.cfg["managed_roles"], {"99": [10]})
        await self.cog.red_delete_data_for_user(requester="user", user_id=99)
        self.assertEqual(self.cfg["managed_roles"], {})

    async def test_shoutout_uses_canonical_url_and_shared_cooldown(self):
        self.cog._lookup_twitch = AsyncMock(return_value={"id": "target", "login": "luna", "display_name": "Luna"})
        self.cog._send_twitch = AsyncMock()
        text = await self.cog._shoutout(1, "https://twitch.tv/luna")
        self.assertEqual(text, "Go follow Luna at https://twitch.tv/luna!")
        with self.assertRaises(module.BridgeError):
            await self.cog._shoutout(1, "luna")
        self.cog._send_twitch.assert_awaited_once()

    async def test_queued_shoutout_cannot_follow_broadcaster_change(self):
        self.cog._lookup_twitch = AsyncMock(return_value={"id": "target", "login": "luna", "display_name": "Luna"})
        self.cog._send_twitch = AsyncMock()
        with self.assertRaises(module.BridgeError):
            await self.cog._shoutout(1, "luna", expected_broadcaster="old")
        self.cog._send_twitch.assert_not_awaited()

    async def test_role_queries_paginate_before_returning(self):
        # Restore the real fetch method for this transport test.
        self.cog._request.side_effect = [(200, {"data": [{"user_id": "1"}], "pagination": {"cursor": "next"}}),
                                        (200, {"data": [{"user_id": "2"}], "pagination": {}})]
        fetch = type(self.cog)._fetch_role_users
        result = await fetch(self.cog, "subscriptions", {}, "stream", ["1", "2"])
        self.assertEqual(result, {"1", "2"})
        self.assertIn(("after", "next"), self.cog._request.call_args.kwargs["params"])


    async def test_broadcaster_role_approval_retains_correct_scoped_token(self):
        self.cog._request.side_effect = [
            (200, {"verification_uri": "https://www.twitch.tv/activate", "user_code": "code",
                   "device_code": "device", "interval": 1, "expires_in": 60}),
            (200, {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}),
            (200, {"client_id": "client", "user_id": "stream", "login": "streamer",
                   "scopes": sorted(module.BROADCASTER_SCOPES)})]
        user = types.SimpleNamespace(send=AsyncMock())
        with patch.object(module.asyncio, "sleep", new=AsyncMock()):
            await self.cog._authorize(user, 1, "streamer", purpose="roles")
        self.assertEqual(self.cfg["role_auth"]["user_id"], "stream")
        self.assertEqual(self.cfg["role_auth"]["refresh_token"], "refresh")
        self.assertIn("moderation:read", self.cog._request.call_args_list[0].kwargs["data"]["scopes"])
        self.cog._restart.assert_awaited_once()

    async def test_broadcaster_refresh_rotates_and_validates_identity(self):
        self.cfg["role_auth"] = {"client_id": "client", "user_id": "stream", "access_token": "old",
                                  "refresh_token": "old-refresh", "expires_at": 0}
        self.cog._request.side_effect = [
            (200, {"access_token": "new", "refresh_token": "new-refresh", "expires_in": 3600}),
            (200, {"client_id": "client", "user_id": "stream", "scopes": ["moderation:read"]})]
        _, auth = await type(self.cog)._role_token(self.cog, 1, {"moderation:read"})
        self.assertEqual(auth["refresh_token"], "new-refresh")
        self.assertEqual(self.cfg["role_auth"]["access_token"], "new")

    async def test_role_token_cannot_belong_to_another_broadcaster(self):
        self.cfg["role_auth"] = {"client_id": "client", "user_id": "other"}
        with self.assertRaises(module.BridgeError):
            await type(self.cog)._role_token(self.cog, 1, set())
        self.cog._request.assert_not_awaited()

    async def test_status_checks_with_missing_scope_fail_before_any_role_change(self):
        self.cfg["member_links"]["99"] = {"twitch_id": "viewer"}
        self.cfg["managed_roles"] = {"99": [10]}
        self.member.roles = [self.role]
        self.cog._role_token.side_effect = module.BridgeError("Additional permissions needed")
        with self.assertRaises(module.BridgeError):
            await self.cog._sync_roles(self.guild)
        self.member.remove_roles.assert_not_awaited()
        self.member.add_roles.assert_not_awaited()


class TargetTests(unittest.TestCase):
    def test_twitch_url_parser_rejects_foreign_and_nested_paths(self):
        for value in ("Luna", "@Luna", "https://www.twitch.tv/luna/", "twitch.tv/luna"):
            self.assertEqual(policy.twitch_target(value), "luna")
        for value in ("https://evil.test/luna", "https://twitch.tv.evil/luna", "https://twitch.tv/a/b", "https://u@twitch.tv/luna", "https://twitch.tv/luna?x=1"):
            with self.assertRaises(ValueError):
                policy.twitch_target(value)
