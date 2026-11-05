"""Run with: python -m unittest discover -s polls/tests -v (no bot required)."""
import ast
import asyncio
import copy
from pathlib import Path
import re
import types
import unittest
from unittest.mock import AsyncMock, Mock

SOURCE = Path(__file__).resolve().parents[1] / "polls.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))


class Embed:
    def __init__(self, **kwargs):
        self.fields = []
    def add_field(self, **kwargs):
        self.fields.append(kwargs)
    def set_footer(self, **kwargs):
        pass
    def set_image(self, **kwargs):
        pass


namespace = {"re": re, "time": types.SimpleNamespace(time=lambda: 100),
             "discord": types.SimpleNamespace(Embed=Embed, Colour=types.SimpleNamespace(green=lambda: 0), HTTPException=RuntimeError)}
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "UNITS" for t in n.targets)]
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
vote = next(n for n in next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Polls").body if isinstance(n, ast.AsyncFunctionDef) and n.name == "vote")
exec(compile(ast.Module(body=[vote], type_ignores=[]), str(SOURCE), "exec"), namespace)


class NotFound(RuntimeError):
    pass


namespace["discord"].NotFound = NotFound
namespace["discord"].AllowedMentions = types.SimpleNamespace(none=lambda: None)
for method in next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Polls").body:
    if isinstance(method, ast.AsyncFunctionDef) and method.name in ("finish_poll", "delete_poll", "manage_poll"):
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), "exec"), namespace)


class PollTests(unittest.TestCase):
    def test_message_references(self):
        parse = namespace["poll_reference"]
        self.assertEqual(parse("123", 1), "123")
        self.assertEqual(parse("<https://discord.com/channels/1/2/123>", 1), "123")
        for value in ("https://discord.com/channels/9/2/123", "abc", "0", "https://example.com/channels/1/2/123"):
            with self.assertRaises(ValueError):
                parse(value, 1)

    def test_duration_units_and_bounds(self):
        for value, seconds in [("1 second", 1), ("2 minutes", 120), ("3 hours", 10800), ("4 days", 345600), ("2 weeks", 1209600)]:
            self.assertEqual(namespace["duration"](value), seconds)
        for value in ("0 seconds", "-1 hours", "1.5 days", "forever", "366 days"):
            with self.assertRaises(ValueError):
                namespace["duration"](value)

    def test_totals_and_winners(self):
        poll = dict(question="Test", description="", answers=["A", "B", "C"], limit=2, image="", closed=True,
                    votes={"1": [0, 1], "2": [0], "3": [2]})
        self.assertEqual(namespace["counts"](poll), [2, 1, 1])
        result = namespace["poll_embed"](poll).fields[0]["value"]
        self.assertIn("Winner: 🇦 with 2 votes (ahead by 1)", result)
        poll["votes"] = {"1": [0, 1]}
        self.assertIn("Tie:", namespace["poll_embed"](poll).fields[0]["value"])
        poll["votes"] = {}
        self.assertIn("No votes", namespace["poll_embed"](poll).fields[0]["value"])


class VotingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.poll = dict(answers=["A", "B"], votes={}, roles=[7], limit=1, ends=200)
        self.messages = []
        self.lock = asyncio.Lock()
        async def get_raw(*args, **kwargs):
            return copy.deepcopy(self.poll)
        async def save(gid, pid, poll):
            self.poll = copy.deepcopy(poll)
        async def refresh(*args):
            pass
        async def send(text, **kwargs):
            self.messages.append(text)
        async def defer(**kwargs):
            pass
        self.cog = types.SimpleNamespace(lock=lambda *args: self.lock, save=save, refresh=refresh,
            config=types.SimpleNamespace(guild_from_id=lambda gid: types.SimpleNamespace(polls=types.SimpleNamespace(get_raw=get_raw))))
        self.interaction = types.SimpleNamespace(user=types.SimpleNamespace(id=42, bot=False, roles=[types.SimpleNamespace(id=7)]),
            guild=types.SimpleNamespace(id=1), response=types.SimpleNamespace(defer=defer), followup=types.SimpleNamespace(send=send))

    async def click(self, index):
        await namespace["vote"](self.cog, self.interaction, 1, "123", index)

    async def test_toggle_and_limit(self):
        await self.click(0)
        await self.click(1)
        self.assertEqual(self.poll["votes"], {"42": [0]})
        self.assertIn("at most", self.messages[-1])
        await self.click(0)
        self.assertEqual(self.poll["votes"], {})

    async def test_roles_and_deadline(self):
        self.interaction.user.roles = []
        await self.click(0)
        self.assertFalse(self.poll["votes"])
        self.interaction.user.roles = [types.SimpleNamespace(id=7)]
        self.poll["ends"] = 100
        await self.click(0)
        self.assertFalse(self.poll["votes"])
        self.assertIn("ended", self.messages[-1])

    async def test_simultaneous_votes_respect_limit(self):
        await asyncio.gather(self.click(0), self.click(1))
        self.assertEqual(len(self.poll["votes"]["42"]), 1)


class ManagementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.poll = dict(question="Test", description="", answers=["A", "B"], votes={"42": [0]},
                         limit=1, image="", channel=10, results=20, ends=200)
        self.group = types.SimpleNamespace(
            polls=types.SimpleNamespace(get_raw=AsyncMock(return_value=self.poll), clear_raw=AsyncMock()),
            completed=types.SimpleNamespace(get_raw=AsyncMock(return_value=None), clear_raw=AsyncMock(), set_raw=AsyncMock()))
        self.message = types.SimpleNamespace(delete=AsyncMock())
        self.channel = types.SimpleNamespace(send=AsyncMock(return_value=types.SimpleNamespace(id=999)),
                                            get_partial_message=Mock(return_value=self.message))
        self.view = Mock()
        self.cog = types.SimpleNamespace(config=types.SimpleNamespace(guild_from_id=lambda gid: self.group),
            bot=types.SimpleNamespace(get_partial_messageable=Mock(return_value=self.channel)),
            save=AsyncMock(), refresh=AsyncMock(), views={(1, "123"): self.view}, dirty={(1, "123")},
            lock=lambda *args: asyncio.Lock())
        self.cog.finish_poll = lambda *args: namespace["finish_poll"](self.cog, *args)
        self.cog.delete_poll = lambda *args: namespace["delete_poll"](self.cog, *args)
        self.ctx = types.SimpleNamespace(guild=types.SimpleNamespace(id=1), send=AsyncMock())

    async def test_force_close_and_repeated_close(self):
        await namespace["manage_poll"](self.cog, self.ctx, "123")
        self.assertTrue(self.poll["closed"])
        self.cog.refresh.assert_awaited_once()
        self.channel.send.assert_awaited_once()
        record = self.group.completed.set_raw.call_args.kwargs["value"]
        self.assertEqual(record, dict(channel=10, results=20, result_message=999))
        self.assertNotIn("votes", record)
        self.group.polls.get_raw.return_value = None
        await namespace["manage_poll"](self.cog, self.ctx, "123")
        self.channel.send.assert_awaited_once()

    async def test_delete_active_without_results(self):
        await namespace["manage_poll"](self.cog, self.ctx, "123", delete=True)
        self.assertTrue(self.poll["deleting"])
        self.channel.send.assert_not_awaited()
        self.message.delete.assert_awaited_once()
        self.group.polls.clear_raw.assert_awaited_once_with("123")
        self.view.stop.assert_called_once()

    async def test_delete_completed_with_results_and_missing_original(self):
        self.group.polls.get_raw.return_value = None
        self.group.completed.get_raw.return_value = dict(channel=10, results=20, result_message=999)
        self.message.delete.side_effect = [NotFound(), None]
        await namespace["manage_poll"](self.cog, self.ctx, "123", delete=True)
        self.assertEqual(self.message.delete.await_count, 2)
        self.group.completed.clear_raw.assert_awaited_once_with("123")
        self.channel.send.assert_not_awaited()

    async def test_failed_delete_retains_cancellation_for_retry(self):
        self.message.delete.side_effect = RuntimeError("Forbidden")
        await namespace["manage_poll"](self.cog, self.ctx, "123", delete=True)
        self.assertTrue(self.poll["deleting"])
        self.cog.save.assert_awaited()
        self.group.polls.clear_raw.assert_not_awaited()
        self.channel.send.assert_not_awaited()
        self.assertIn("retry", self.ctx.send.call_args.args[0])

    async def test_close_delivery_retry_does_not_repeat_original_edit(self):
        self.channel.send.side_effect = [RuntimeError("Forbidden"), types.SimpleNamespace(id=999)]
        await namespace["manage_poll"](self.cog, self.ctx, "123")
        self.assertTrue(self.poll["closed"])
        self.assertTrue(self.poll["finalized"])
        self.group.polls.clear_raw.assert_not_awaited()
        await namespace["manage_poll"](self.cog, self.ctx, "123")
        self.cog.refresh.assert_awaited_once()
        self.group.polls.clear_raw.assert_awaited_once()

    async def test_foreign_server_link_cannot_delete(self):
        await namespace["manage_poll"](self.cog, self.ctx, "https://discord.com/channels/2/10/123", delete=True)
        self.group.polls.get_raw.assert_not_awaited()
        self.message.delete.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
