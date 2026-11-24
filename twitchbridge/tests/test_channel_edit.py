import types
import unittest
from unittest.mock import AsyncMock

from test_bridge import module
import test_stream_tools as fixtures

VALIDATION = module.ChannelEditMixin._channel_action.__globals__


class ChannelValidationTests(unittest.TestCase):
    def test_titles_are_nonempty_and_limited_to_140_characters(self):
        self.assertEqual(VALIDATION["title_text"](" New\nTitle "), "New Title")
        for title in ("", "x" * 141, "bad\x00title"):
            with self.assertRaises(ValueError):
                VALIDATION["title_text"](title)

    def test_tags_validate_count_length_uniqueness_and_clear(self):
        parse = VALIDATION["channel_tags"]
        self.assertEqual(parse("English, Cozy"), ["English", "Cozy"])
        self.assertEqual(parse("clear"), [])
        for tags in ("", "English english", "bad-tag", "x" * 26, " ".join(str(i) for i in range(11))):
            with self.assertRaises(ValueError):
                parse(tags)


class ChannelEditTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.StreamToolsTests.setUp(self)
        self.cog._token = AsyncMock(return_value=("client", {"access_token": "bot-token", "user_id": "bot"}))
        self.cog._role_token = AsyncMock(return_value=("client", {"access_token": "broadcaster-token", "user_id": "stream"}))
        self.cog._request.return_value = (204, {})

    async def test_regular_viewers_cannot_change_any_field(self):
        for field in ("title", "game", "category", "tags", "language"):
            with self.assertRaises(module.BridgeError):
                await self.cog._channel_action(1, field, "test", 0)
        self.cog._request.assert_not_awaited()

    async def test_title_patch_uses_broadcaster_token_and_invalidates_stream_cache(self):
        reply = await self.cog._channel_action(1, "title", "New Title", 1)
        self.assertIn("updated: New Title", reply)
        call = self.cog._request.call_args
        self.assertEqual(call.args[0], "PATCH")
        self.assertEqual(call.kwargs["params"], {"broadcaster_id": "stream"})
        self.assertEqual(call.kwargs["json"], {"title": "New Title"})
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer broadcaster-token")
        self.cog._role_token.assert_awaited_once_with(1, {"channel:manage:broadcast"})
        self.assertNotIn(1, self.cog.stream_cache)

    async def test_moderator_can_read_current_title_without_write_permission(self):
        self.cog._request.return_value = (200, {"data": [{"title": "Current Title"}]})
        self.assertEqual(await self.cog._channel_action(1, "title", "", 1), "Stream title: Current Title")
        self.cog._role_token.assert_not_awaited()
        self.assertEqual(self.cog._request.call_args.args[0], "GET")

    async def test_game_alias_resolves_exact_category_instead_of_first_match(self):
        self.cog._request.side_effect = [(200, {"data": [{"id": "1", "name": "Other Game"}, {"id": "2", "name": "Just Chatting"}]}), (204, {})]
        reply = await self.cog._channel_action(1, "game", "just chatting", 1)
        self.assertIn("Just Chatting", reply)
        self.assertEqual(self.cog._request.call_args.kwargs["json"], {"game_id": "2"})

    async def test_ambiguous_categories_are_not_silently_selected(self):
        self.cog._request.return_value = (200, {"data": [{"id": "1", "name": "Game One"}, {"id": "2", "name": "Game Two"}]})
        with self.assertRaises(ValueError) as error:
            await self.cog._channel_action(1, "category", "Game", 1)
        self.assertIn("Several categories", str(error.exception))
        self.cog._request.assert_awaited_once()
        self.cog._role_token.assert_not_awaited()

    async def test_numeric_category_ids_are_checked_with_games_endpoint(self):
        self.cog._request.side_effect = [(200, {"data": [{"id": "509658", "name": "Just Chatting"}]}), (204, {})]
        await self.cog._channel_action(1, "category", "509658", 2)
        self.assertTrue(self.cog._request.call_args_list[0].args[1].endswith("games"))
        self.assertEqual(self.cog._request.call_args.kwargs["json"], {"game_id": "509658"})

    async def test_invalid_category_does_not_patch_anything(self):
        self.cog._request.return_value = (200, {"data": []})
        with self.assertRaises(ValueError):
            await self.cog._channel_action(1, "category", "Unknown", 1)
        self.cog._request.assert_awaited_once()

    async def test_tags_and_language_only_change_requested_fields(self):
        await self.cog._channel_action(1, "tags", "English Cozy", 1)
        self.assertEqual(self.cog._request.call_args.kwargs["json"], {"tags": ["English", "Cozy"]})
        await self.cog._channel_action(1, "tags", "clear", 1)
        self.assertEqual(self.cog._request.call_args.kwargs["json"], {"tags": []})
        await self.cog._channel_action(1, "language", "EN", 1)
        self.assertEqual(self.cog._request.call_args.kwargs["json"], {"broadcaster_language": "en"})
        with self.assertRaises(ValueError):
            await self.cog._channel_action(1, "language", "english", 1)

    async def test_changed_channel_during_lookup_cannot_update_new_broadcaster(self):
        async def lookup(*args, **kwargs):
            self.cfg["broadcaster_id"] = "other"
            return (200, {"data": [{"id": "1", "name": "Game"}]})
        self.cog._request.side_effect = lookup
        with self.assertRaises(module.BridgeError):
            await self.cog._channel_action(1, "category", "Game", 1)
        self.cog._request.assert_awaited_once()
        self.cog._role_token.assert_not_awaited()

    async def test_wrong_broadcaster_token_cannot_update_channel(self):
        self.cog._role_token.return_value = ("client", {"user_id": "other", "access_token": "secret"})
        with self.assertRaises(module.BridgeError):
            await self.cog._channel_action(1, "title", "New", 1)
        self.cog._request.assert_not_awaited()

    async def test_rejected_patch_reports_failure_without_retry_or_cache_invalidation(self):
        self.cog._request.return_value = (403, {})
        with self.assertRaises(module.BridgeError):
            await self.cog._channel_action(1, "title", "New", 1)
        self.assertIn(1, self.cog.stream_cache)
        self.cog._request.assert_awaited_once()

    async def test_discord_reply_disables_mentions_and_link_previews(self):
        self.cog._discord_level = AsyncMock(return_value=1)
        ctx = types.SimpleNamespace(guild=self.guild, send=AsyncMock())
        await self.cog._channel_reply(ctx, "title", "Hello @everyone")
        self.assertTrue(ctx.send.call_args.kwargs["suppress_embeds"])
        self.assertIn("allowed_mentions", ctx.send.call_args.kwargs)
