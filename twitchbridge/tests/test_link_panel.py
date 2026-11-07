import asyncio
import copy
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_bridge import module
import test_community as community_tests


class PanelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        community_tests.CommunityTests.setUp(self)
        self.panel = {"message_id": 456, "channel_id": 789}
        self.cfg.update(link_panel=dict(self.panel), link_panel_label="Connect Twitch",
                        link_panel_text="Link here")
        self.cog.closing = False
        self.cog.link_views = {}
        self.cog.link_modals = set()
        self.cog.pending_device_links = {}
        self.cog.member_auth_tasks = {}
        self.cog.link_generation = {}
        self.cog._lookup_twitch = AsyncMock(return_value={"id": "viewer", "login": "viewer"})
        self.cog.bot.cog_disabled_in_guild = AsyncMock(return_value=False)
        self.cog.bot.allowed_by_whitelist_blacklist = AsyncMock(return_value=True)
        self.cog.bot.add_view = Mock()
        self.member.bot = False
        self.interaction = types.SimpleNamespace(guild=self.guild, guild_id=1, channel_id=789,
            user=self.member, message=types.SimpleNamespace(id=456),
            response=types.SimpleNamespace(send_modal=AsyncMock(), send_message=AsyncMock(), defer=AsyncMock()),
            followup=types.SimpleNamespace(send=AsyncMock()))

    def device_responses(self, user_id="viewer"):
        self.cog._request.side_effect = [
            (200, {"verification_uri": "https://www.twitch.tv/activate", "user_code": "CODE",
                   "device_code": "private", "interval": 1, "expires_in": 600}),
            (200, {"access_token": "transient", "refresh_token": "discard"}),
            (200, {"client_id": "client", "user_id": user_id, "login": "viewer", "scopes": []}),
            (200, {})]

    async def test_button_opens_private_username_modal(self):
        # Classes are retained on the imported mixin module globals despite test stubs.
        view_class = module.CommunityMixin.link_panel.__globals__["LinkPanelView"]
        view = view_class(self.cog, "Connect Twitch")
        await view.open_link(self.interaction)
        self.interaction.response.send_modal.assert_awaited_once()
        modal = self.interaction.response.send_modal.call_args.args[0]
        self.assertEqual(modal.user_id, 99)
        self.assertEqual(modal.guild_id, 1)
        self.assertEqual(view.timeout, None)
        self.assertEqual(view.children[0].label, "Connect Twitch")

    async def test_deleted_or_replaced_panel_is_inactive(self):
        self.interaction.message.id = 999
        with self.assertRaises(module.BridgeError):
            await self.cog._check_link_panel(self.interaction)

    async def test_identity_only_approval_links_and_never_saves_member_token(self):
        self.device_responses()
        with patch.object(module.asyncio, "sleep", new=AsyncMock()):
            await self.cog._begin_device_link(self.interaction, "viewer", self.panel)
            await self.cog.member_auth_tasks[(1, 99)]
        self.assertEqual(self.cfg["member_links"]["99"]["twitch_id"], "viewer")
        self.assertNotIn("transient", repr(self.cfg))
        self.assertNotIn("discard", repr(self.cfg))
        self.assertEqual(self.cog._request.call_args_list[0].kwargs["data"]["scope"], "")
        self.assertTrue(all(call.kwargs.get("ephemeral") for call in self.interaction.followup.send.call_args_list))
        self.assertTrue(self.cog._request.call_args.args[1].endswith("revoke"))
        self.assertFalse(self.cog.pending_device_links)
        self.assertFalse(self.cog.member_auth_tasks)

    async def test_wrong_approved_twitch_account_cannot_link(self):
        self.device_responses(user_id="attacker")
        with patch.object(module.asyncio, "sleep", new=AsyncMock()):
            await self.cog._begin_device_link(self.interaction, "viewer", self.panel)
            await self.cog.member_auth_tasks[(1, 99)]
        self.assertEqual(self.cfg["member_links"], {})
        self.assertIn("did not match", self.interaction.followup.send.call_args.args[0])

    async def test_panel_removal_during_approval_prevents_link(self):
        self.device_responses()
        with patch.object(module.asyncio, "sleep", new=AsyncMock()):
            await self.cog._begin_device_link(self.interaction, "viewer", self.panel)
            self.cfg["link_panel"] = {}
            await self.cog.member_auth_tasks[(1, 99)]
        self.assertEqual(self.cfg["member_links"], {})

    async def test_unlink_cancels_pending_button_approval_and_clears_state(self):
        self.device_responses()
        await self.cog._begin_device_link(self.interaction, "viewer", self.panel)
        await self.cog._unlink_member(1, 99)
        self.assertFalse(self.cog.pending_device_links)
        self.assertFalse(self.cog.member_auth_tasks)
        self.assertFalse(self.cfg["member_links"])

    async def test_buttons_restore_after_reload_using_saved_message_id(self):
        await self.cog._restore_link_panels()
        view = self.cog.link_views[1]
        self.cog.bot.add_view.assert_called_once_with(view, message_id=456)
        self.assertEqual(view.children[0].label, "Connect Twitch")

    async def test_existing_link_does_not_open_a_new_prompt(self):
        self.cfg["member_links"]["99"] = {"twitch_id": "viewer"}
        view_class = module.CommunityMixin.link_panel.__globals__["LinkPanelView"]
        await view_class(self.cog).open_link(self.interaction)
        self.interaction.response.send_modal.assert_not_awaited()
        self.assertTrue(self.interaction.response.send_message.call_args.kwargs["ephemeral"])

    async def test_username_only_shoutout_resolves_the_canonical_follow_url(self):
        self.cog._lookup_twitch.return_value = {"id": "target", "login": "luna", "display_name": "Luna"}
        self.cog._send_twitch = AsyncMock()
        text = await self.cog._shoutout(1, "luna")
        self.assertEqual(text, "Go follow Luna at https://twitch.tv/luna!")
        self.cog._lookup_twitch.assert_awaited_once_with("luna")

    def test_permission_bundles_cover_features_without_mixing_account_ownership(self):
        self.assertIn("moderator:manage:announcements", module.BOT_SCOPES)
        self.assertIn("moderator:manage:shoutouts", module.BOT_SCOPES)
        self.assertIn("channel:read:subscriptions", module.BROADCASTER_SCOPES)
        self.assertIn("channel:manage:redemptions", module.BROADCASTER_SCOPES)
        self.assertNotIn("channel:manage:redemptions", module.BOT_SCOPES)

    async def test_panel_text_updates_reuse_the_registered_view(self):
        view_class = module.CommunityMixin.link_panel.__globals__["LinkPanelView"]
        view = view_class(self.cog, "Old label")
        self.cog.link_views[1] = view
        message = types.SimpleNamespace(edit=AsyncMock())
        channel = module.discord.TextChannel()
        channel.fetch_message = AsyncMock(return_value=message)
        self.guild.get_channel = lambda cid: channel
        await self.cog._update_link_panel(self.guild)
        self.assertIs(self.cog.link_views[1], view)
        self.assertFalse(view.stopped)
        self.assertEqual(view.children[0].label, "Connect Twitch")
        message.edit.assert_awaited_once()

    async def test_broadcaster_base_approval_also_covers_roles_without_mapping_changes(self):
        self.cfg["broadcaster_auth"] = {}
        self.cog._request.side_effect = [
            (200, {"verification_uri": "https://www.twitch.tv/activate", "user_code": "CODE",
                   "device_code": "device", "interval": 1, "expires_in": 600}),
            (200, {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}),
            (200, {"client_id": "client", "user_id": "stream", "login": "streamer",
                   "scopes": sorted(module.BROADCASTER_SCOPES)})]
        with patch.object(module.asyncio, "sleep", new=AsyncMock()):
            await self.cog._authorize(self.member, 1, "streamer")
        self.assertEqual(set(self.cfg["role_auth"]["scopes"]), module.BROADCASTER_SCOPES)
        self.assertEqual(self.cfg["broadcaster_auth"]["client_id"], "client")
