"""Regression tests using discord.py's actual button registration (no connection)."""
import ast
import asyncio
import copy
import logging
from pathlib import Path
import re
import time
import types
import unittest
from unittest.mock import AsyncMock

try:
    import discord
    from discord.ui.view import ViewStore
except ImportError:
    discord = None


def load_poll_classes():
    source = Path(__file__).resolve().parents[1] / "polls.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    ballot = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Ballot")
    cog = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Polls")
    cog.bases = []
    for method in cog.body:
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method.decorator_list = []
    scope = dict(discord=discord, asyncio=asyncio, copy=copy, time=time, re=re,
                 log=logging.getLogger(__name__))
    exec(compile(ast.Module(body=nodes + [ballot, cog], type_ignores=[]), str(source), "exec"), scope)
    return scope["Polls"], scope["Ballot"]


@unittest.skipIf(discord is None, "Install discord.py to run actual button dispatch regression tests")
class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        Polls, Ballot = load_poll_classes()
        self.poll = dict(question="Test", answers=["A", "B"], description="", image="", votes={},
                         roles=[], limit=1, ends=time.time() + 3600, channel=10, results=20)
        self.store = ViewStore(state=None)
        self.cog = Polls.__new__(Polls)
        self.cog.views, self.cog.locks, self.cog.dirty = {}, {}, set()
        self.fail_edit = False
        async def edit(**kwargs):
            if self.fail_edit:
                raise discord.HTTPException(types.SimpleNamespace(status=503, reason="Unavailable"), "Retry")
            view = kwargs["view"]
            if view is not None:
                # Message.edit registers its view with Discord's connection state.
                self.store.add_view(view, message_id=123)
        self.message = types.SimpleNamespace(edit=edit)
        channel = types.SimpleNamespace(get_partial_message=lambda mid: self.message)
        self.cog.bot = types.SimpleNamespace(get_partial_messageable=lambda cid: channel)
        async def get_raw(*args, **kwargs):
            return copy.deepcopy(self.poll)
        async def set_raw(pid, *, value):
            self.poll = copy.deepcopy(value)
        group = types.SimpleNamespace(polls=types.SimpleNamespace(get_raw=get_raw, set_raw=set_raw))
        self.cog.config = types.SimpleNamespace(guild_from_id=lambda gid: group)
        self.view = Ballot(self.cog, 1, "123", self.poll)
        self.cog.views[1, "123"] = self.view
        self.store.add_view(self.view, message_id=123)

    async def asyncTearDown(self):
        for view in self.cog.views.values():
            view.stop()

    async def click(self, index, uid=42):
        key = (2, f"kermitpoll:1:123:{index}")
        item = self.store._views.get(123, {}).get(key)
        self.assertIsNotNone(item, "Poll buttons were unregistered after a count update")
        interaction = types.SimpleNamespace(user=types.SimpleNamespace(id=uid, bot=False, roles=[]),
            guild=types.SimpleNamespace(id=1), response=types.SimpleNamespace(defer=AsyncMock()),
            followup=types.SimpleNamespace(send=AsyncMock()))
        await item.callback(interaction)
        interaction.response.defer.assert_awaited_once()
        return interaction

    async def test_vote_remove_and_other_member_after_refresh(self):
        await self.click(0)
        self.assertEqual(self.poll["votes"], {"42": [0]})
        self.assertEqual(self.cog.views[1, "123"].children[0].label, "1")
        await self.click(0)
        self.assertEqual(self.poll["votes"], {})
        self.assertEqual(self.cog.views[1, "123"].children[0].label, "0")
        await self.click(1, uid=43)
        self.assertEqual(self.poll["votes"], {"43": [1]})
        self.assertIs(self.cog.views[1, "123"], self.view)
        self.assertFalse(self.view.is_finished())

    async def test_restored_poll_refresh_preserves_callbacks(self):
        await self.cog.refresh(1, "123", self.poll)
        await self.click(1)
        await self.click(1)
        self.assertFalse(self.poll["votes"])

    async def test_edit_failure_preserves_votes_and_retry_buttons(self):
        self.fail_edit = True
        interaction = await self.click(0)
        self.assertEqual(self.poll["votes"], {"42": [0]})
        self.assertIn((1, "123"), self.cog.dirty)
        self.assertIn("refresh shortly", interaction.followup.send.call_args.args[0])
        self.fail_edit = False
        await self.cog.refresh(1, "123", self.poll)
        await self.click(0)
        self.assertFalse(self.poll["votes"])
        self.assertNotIn((1, "123"), self.cog.dirty)

    async def test_closed_poll_removes_callbacks(self):
        self.poll["closed"] = True
        await self.cog.refresh(1, "123", self.poll)
        self.assertTrue(self.view.is_finished())
        self.assertNotIn(123, self.store._views)
        self.assertNotIn((1, "123"), self.cog.views)


if __name__ == "__main__":
    unittest.main()
