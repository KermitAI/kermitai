import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

spec = importlib.util.spec_from_file_location(
    "policy", Path(__file__).resolve().parents[1] / "policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.now = self.start + timedelta(days=7)
        self.guild = NS(owner_id=1, me=NS(
            top_role=10, guild_permissions=NS(kick_members=True)))
        self.member = NS(id=2, bot=False, guild=self.guild,
                         guild_permissions=NS(administrator=False),
                         joined_at=self.start - timedelta(days=90),
                         top_role=2, roles=[NS(id=5)])

    def due(self):
        return policy.is_due(self.member, 99, 7 * 86400, self.start, self.now)

    def test_exact_deadline_and_existing_member_grace(self):
        self.now -= timedelta(microseconds=1)
        self.assertFalse(self.due())
        self.now += timedelta(microseconds=1)
        self.assertTrue(self.due())

    def test_new_join_uses_join_date(self):
        self.member.joined_at = self.start + timedelta(days=1)
        self.assertFalse(self.due())
        self.now += timedelta(days=1)
        self.assertTrue(self.due())

    def test_required_role_and_removal(self):
        self.member.roles.append(NS(id=99))
        self.assertFalse(self.due())
        self.member.roles.pop()
        self.assertTrue(self.due())

    def test_exempt_members(self):
        for attribute, value in (("bot", True), ("id", 1), ("joined_at", None),
                                 ("top_role", 10), ("top_role", 11)):
            with self.subTest(attribute=attribute, value=value):
                previous = getattr(self.member, attribute)
                setattr(self.member, attribute, value)
                self.assertFalse(self.due())
                setattr(self.member, attribute, previous)
        self.member.guild_permissions.administrator = True
        self.assertFalse(self.due())

    def test_bot_permissions_or_missing_member(self):
        self.guild.me.guild_permissions.kick_members = False
        self.assertFalse(self.due())
        self.guild.me = None
        self.assertFalse(self.due())

    def test_minute_and_hour_deadlines(self):
        for value in ("3m", "1h", "5d"):
            with self.subTest(value=value):
                seconds = policy.parse_duration(value)
                deadline = self.start + timedelta(seconds=seconds)
                self.assertFalse(policy.is_due(self.member, 99, seconds, self.start,
                                               deadline - timedelta(microseconds=1)))
                self.assertTrue(policy.is_due(self.member, 99, seconds, self.start, deadline))


class DurationTests(unittest.TestCase):
    def test_units_and_limits(self):
        for value, expected in (("3m", 180), ("1h", 3600), ("5d", 432000),
                                (" 2H ", 7200), ("1m", 60), ("365d", 31536000)):
            self.assertEqual(policy.parse_duration(value), expected)

    def test_invalid_input(self):
        for value in ("0m", "-1h", "1.5h", "3", "1s", "1h30m", "366d", "", "9999999999d"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.parse_duration(value)

    def test_existing_settings_preserved(self):
        self.assertEqual(policy.waiting_seconds({"days": 5}), 432000)
        self.assertEqual(policy.waiting_seconds({"days": 5, "time_seconds": None}), 432000)
        self.assertEqual(policy.waiting_seconds({"days": 5, "time_seconds": 180}), 180)

    def test_display(self):
        self.assertEqual(policy.format_duration(180), "3 minutes")
        self.assertEqual(policy.format_duration(3600), "1 hour")
        self.assertEqual(policy.format_duration(432000), "5 days")


if __name__ == "__main__":
    unittest.main()
