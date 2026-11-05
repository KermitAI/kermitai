"""Run with python -m unittest discover -s schedular/tests -v."""
import ast
import asyncio
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import types
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scheduling", ROOT / "scheduling.py")
scheduling = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheduling)


def stamp(value):
    return datetime.fromisoformat(value).timestamp()


class SchedulingTests(unittest.TestCase):
    def test_intervals(self):
        for value, expected in (("15 minutes", 900), ("2 hours", 7200), ("1 day", 86400), ("2 weeks", 1209600)):
            self.assertEqual(scheduling.interval(value), expected)
        for value in ("14 minutes", "900 seconds", "0 hours", "-1 days", "1.5 hours", "366 days"):
            with self.assertRaises(ValueError):
                scheduling.interval(value)

    def test_daily_spacing(self):
        self.assertEqual(scheduling.daily_times("17:30, 09:00"), ["09:00", "17:30"])
        self.assertEqual(scheduling.daily_times("00:00,23:45"), ["00:00", "23:45"])
        for value in ("23:50,00:00", "09:00,09:14", "09:00,09:00", "24:00", "9:00", ""):
            with self.assertRaises(ValueError):
                scheduling.daily_times(value)

    def test_timezone_validation(self):
        with self.assertRaises(ValueError):
            scheduling.zone("Not/AZone")

    def test_daily_next_and_rollover(self):
        schedule = dict(mode="daily", times=["09:00", "17:00"], timezone="UTC")
        self.assertEqual(scheduling.next_run(schedule, stamp("2026-11-05T09:00:00+00:00")), stamp("2026-11-05T17:00:00+00:00"))
        self.assertEqual(scheduling.next_run(schedule, stamp("2026-11-05T18:00:00+00:00")), stamp("2026-11-06T09:00:00+00:00"))

    def test_dst_skips_nonexistent_time(self):
        schedule = dict(mode="daily", times=["02:30"], timezone="America/Toronto")
        self.assertEqual(scheduling.next_run(schedule, stamp("2026-03-08T00:00:00-05:00")), stamp("2026-03-09T02:30:00-04:00"))

    def test_dst_no_duplicate_fall_back(self):
        schedule = dict(mode="daily", times=["01:30"], timezone="America/Toronto")
        self.assertEqual(scheduling.next_run(schedule, stamp("2026-11-01T01:30:00-04:00")), stamp("2026-11-02T01:30:00-05:00"))

    def test_interval_does_not_catch_up(self):
        self.assertEqual(scheduling.next_run(dict(mode="interval", interval=900), 100000), 100900)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_reserves_before_send_and_skips_paused_and_future(self):
        events = []
        class Channel:
            async def send(self, *args, **kwargs):
                events.append("send")
                raise RuntimeError("permission denied")
        channel = Channel()
        due = dict(mode="interval", interval=900, next=1, paused=False, channel=1, message="Hello")
        records = {"due": due, "paused": dict(due, paused=True), "future": dict(due, next=20000)}
        class Group:
            async def __call__(self):
                return records
            async def set_raw(self, aid, value):
                events.append((aid, value["next"]))
        group = Group()
        config = types.SimpleNamespace(all_guilds=AsyncMock(return_value={1: {}}), guild_from_id=lambda gid: types.SimpleNamespace(announcements=group))
        guild = types.SimpleNamespace(get_channel=lambda cid: channel)
        cog = types.SimpleNamespace(config=config, bot=types.SimpleNamespace(get_guild=lambda gid: guild,
            cog_disabled_in_guild=AsyncMock(return_value=False)), lock=lambda gid: asyncio.Lock())
        tree = ast.parse((ROOT / "schedular.py").read_text(encoding="utf-8-sig"))
        method = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "Schedular" for n in c.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "tick")
        namespace = dict(time=types.SimpleNamespace(time=lambda: 10000), next_run=scheduling.next_run,
            discord=types.SimpleNamespace(TextChannel=Channel, HTTPException=RuntimeError, AllowedMentions=types.SimpleNamespace(none=lambda: None)))
        exec(compile(ast.Module(body=[method], type_ignores=[]), "worker", "exec"), namespace)
        await namespace["tick"](cog)
        self.assertEqual(events, [("due", 10900), "send", ("due", 10900)])
        self.assertTrue(due["error"])
        events.clear()
        await namespace["tick"](cog)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
