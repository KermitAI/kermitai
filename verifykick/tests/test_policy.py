import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

spec = importlib.util.spec_from_file_location(
    "policy", Path(__file__).resolve().parents[1] / "verifykick" / "policy.py")
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
        return policy.is_due(self.member, 99, 7, self.start, self.now)

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


if __name__ == "__main__":
    unittest.main()
