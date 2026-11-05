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
        for value, expected in (("15 minutes", 900), ("2 hours", 7200), ("1 day", 86400), ("2 weeks", 1209600), ("15m", 900), ("2h", 7200), ("3d", 259200), ("1w", 604800), (" 15 M ", 900), ("2H", 7200)):
            self.assertEqual(scheduling.interval(value), expected)
        for value in ("14 minutes", "900 seconds", "0 hours", "-1 days", "1.5 hours", "366 days", "14m", "900s", "0h", "-1d", "1.5h", "53w", "1h30m"):
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


class DeletePickerTests(unittest.IsolatedAsyncioTestCase):
    def make_picker(self, count=21):
        class View:
            def __init__(self, **kwargs):
                self.children = []
            def clear_items(self):
                self.children.clear()
            def add_item(self, item):
                self.children.append(item)
            def is_finished(self):
                return False
        class Button:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        records = {str(i): dict(message=f"Message {i}", channel=1, mode="interval",
            interval=900, interval_label="15 minutes", times=[], timezone="UTC", paused=False, revision=str(i)) for i in range(count)}
        saved = {aid: dict(record) for aid, record in records.items()}
        group = types.SimpleNamespace(get_raw=AsyncMock(side_effect=lambda aid, default=None: saved.get(aid)), clear_raw=AsyncMock())
        cog = types.SimpleNamespace(config=types.SimpleNamespace(guild=lambda guild: types.SimpleNamespace(announcements=group)), lock=lambda gid: asyncio.Lock())
        ctx = types.SimpleNamespace(guild=types.SimpleNamespace(id=1))
        tree = ast.parse((ROOT / "schedular.py").read_text(encoding="utf-8-sig"))
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DeletePicker")
        namespace = dict(asyncio=asyncio, discord=types.SimpleNamespace(ui=types.SimpleNamespace(View=View, Button=Button),
            ButtonStyle=types.SimpleNamespace(danger=1), AllowedMentions=types.SimpleNamespace(none=lambda: None)))
        exec(compile(ast.Module(body=[node], type_ignores=[]), "picker", "exec"), namespace)
        picker = namespace["DeletePicker"](cog, ctx, records)
        picker.embed = lambda: None
        interaction = types.SimpleNamespace(response=types.SimpleNamespace(defer=AsyncMock(), edit_message=AsyncMock()),
            followup=types.SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())
        return picker, group, saved, interaction

    async def test_letter_deletes_only_assigned_id_and_keeps_mapping(self):
        picker, group, saved, interaction = self.make_picker()
        await picker.children[1].callback(interaction)
        group.clear_raw.assert_awaited_once_with("1")
        self.assertTrue(picker.children[1].disabled)
        self.assertEqual(picker.visible()[2][0], "2")
        self.assertEqual(len(picker.children), 23)
        await picker.children[-2].callback(interaction)
        self.assertEqual(picker.visible()[0][0], "20")
        self.assertEqual(len(picker.children), 4)

    async def test_changed_schedule_is_not_deleted(self):
        picker, group, saved, interaction = self.make_picker(1)
        saved["0"]["revision"] = "changed"
        await picker.children[0].callback(interaction)
        group.clear_raw.assert_not_awaited()
        interaction.followup.send.assert_awaited_once()

    async def test_already_deleted_schedule_disables_button(self):
        picker, group, saved, interaction = self.make_picker(1)
        saved.clear()
        await picker.children[0].callback(interaction)
        group.clear_raw.assert_not_awaited()
        self.assertTrue(picker.children[0].disabled)


if __name__ == "__main__":
    unittest.main()
