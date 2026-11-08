"""Offline checks: run with python -m unittest discover -s tags/tests."""
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock
from redbot.core import commands
from tags.core import Tags
from tags.objects import Tag


class CompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def test_all_commands_have_slash_definitions(self):
        for command in Tags.__cog_commands__:
            self.assertIsInstance(command, (commands.HybridCommand, commands.HybridGroup))
            self.assertIsNotNone(command.app_command)
            if isinstance(command, commands.HybridGroup):
                self.assertLessEqual(len(command.app_command.commands), 25)
        params = {p.name: p for p in Tags.invoketag.app_command.parameters}
        self.assertTrue(params["tag_name"].required)
        self.assertFalse(params["response"].required)

    async def test_slash_parent_denial_is_enforced(self):
        parent = SimpleNamespace(can_run=AsyncMock(return_value=False))
        ctx = SimpleNamespace(interaction=object(), command=SimpleNamespace(parents=[parent]))
        self.assertFalse(await Tags.cog_check(None, ctx))
        parent.can_run.assert_awaited_once_with(ctx, change_permission_state=True)
        self.assertFalse(ctx._tags_checking_parents)

    async def test_slash_parent_checks_run_root_first(self):
        calls = []
        async def root_check(*args, **kwargs):
            calls.append("root")
            return True
        async def child_check(*args, **kwargs):
            calls.append("child")
            return True
        parents = [SimpleNamespace(can_run=child_check), SimpleNamespace(can_run=root_check)]
        ctx = SimpleNamespace(interaction=object(), command=SimpleNamespace(parents=parents))
        self.assertTrue(await Tags.cog_check(None, ctx))
        self.assertEqual(calls, ["root", "child"])

    def test_existing_tags_and_aliases_load_without_conversion(self):
        cog = SimpleNamespace(config=object(), bot=object(),
                              guild_tag_cache=defaultdict(dict), global_tag_cache={})
        saved = {"tag": "Hello {author}", "author_id": 123, "uses": 42,
                 "aliases": ["hello"], "created_at": 1700000000}
        for guild in (None, 456):
            tag = Tag.from_dict(cog, "welcome", saved, guild_id=guild)
            tag.add_to_cache()
            self.assertEqual(tag.to_dict(), saved)
            self.assertIs(Tags.get_tag(cog, SimpleNamespace(id=456) if guild else None,
                                       "hello"), tag)