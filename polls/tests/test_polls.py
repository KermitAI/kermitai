"""Run with: python -m unittest discover -s polls/tests -v (no bot required)."""
import ast
import asyncio
import copy
from pathlib import Path
import re
import types
import unittest

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


class PollTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
