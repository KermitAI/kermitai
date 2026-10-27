import importlib.util
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("birthday_policy", Path(__file__).parents[1] / "policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class BirthdayPolicyTests(unittest.TestCase):
    def test_valid_dates(self):
        for text, expected in [("07/24", (7, 24)), (" 2/29 ", (2, 29)), ("12/31", (12, 31))]:
            self.assertEqual(policy.parse_birthday(text), expected)

    def test_invalid_dates(self):
        for text in ["02/30", "13/01", "00/10", "1/0", "July 24", "07/24/2000", "", "24/07"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                policy.parse_birthday(text)

    def test_due_and_already_announced(self):
        birthday = {"month": 7, "day": 24, "last_year": 2025}
        self.assertTrue(policy.is_due(birthday, date(2026, 7, 24)))
        self.assertFalse(policy.is_due(birthday, date(2026, 7, 25)))
        birthday["last_year"] = 2026
        self.assertFalse(policy.is_due(birthday, date(2026, 7, 24)))

    def test_leap_day_policy(self):
        birthday = {"month": 2, "day": 29}
        self.assertTrue(policy.is_due(birthday, date(2026, 2, 28)))
        self.assertFalse(policy.is_due(birthday, date(2028, 2, 28)))
        self.assertTrue(policy.is_due(birthday, date(2028, 2, 29)))

    def test_message_token_and_literal_braces(self):
        member = SimpleNamespace(mention="<@123>")
        self.assertEqual(policy.render_message("Happy birthday {member}! {cake}", member),
                         "Happy birthday <@123>! {cake}")

    def test_missing_token_still_pings_member(self):
        self.assertEqual(policy.render_message("Happy birthday!", SimpleNamespace(mention="<@123>")),
                         "<@123> Happy birthday!")


if __name__ == "__main__":
    unittest.main()
