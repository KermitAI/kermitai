import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

spec = importlib.util.spec_from_file_location("audit", Path(__file__).parents[1] / "audit.py")
audit = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)


def command(level="NONE", perms=(), **kwargs):
    requires = NS(privilege_level=NS(name=level) if level else None,
                  user_perms=perms, checks=[], bot_perms=[],
                  _global_rules={}, _guild_rules={})
    return NS(qualified_name="example", requires=requires, parents=[], cog=None,
              checks=[], enabled=True, hidden=False, aliases=[], **kwargs)


class AuditTests(unittest.TestCase):
    def test_five_levels(self):
        for name, index in audit.LEVELS.items():
            with self.subTest(name=name):
                perms = () if name == "NONE" else None
                self.assertEqual(audit.classify(command(name, perms)).category,
                                 audit.CATEGORIES[index])

    def test_parent_and_cog_requirements(self):
        cmd = command()
        cmd.parents = [command("ADMIN", None)]
        self.assertEqual(audit.classify(cmd).category, audit.CATEGORIES[2])
        cmd.cog = command("BOT_OWNER", None)
        self.assertEqual(audit.classify(cmd).category, audit.CATEGORIES[0])

    def test_permission_alternative_is_documented(self):
        result = audit.classify(command("ADMIN", [("manage_guild", True)]))
        self.assertEqual(result.category, audit.CATEGORIES[2])
        self.assertIn("alternatively", result.notes[0])

    def test_permission_only_is_not_assumed_moderator(self):
        self.assertIsNone(audit.classify(command(None, [("manage_messages", True)])).category)
        self.assertEqual(audit.classify(command(None, [("administrator", True)])).category,
                         audit.CATEGORIES[2])

    def test_unknown_checks_never_become_everyone(self):
        cmd = command()
        def must_not_run(*args):
            raise AssertionError("Audit executed a check")
        cmd.checks = [must_not_run]
        self.assertIsNone(audit.classify(cmd).category)
        cmd.checks = []
        cmd.requires.checks = [must_not_run]
        self.assertIsNone(audit.classify(cmd).category)
        cmd.requires.checks = []
        cmd.cog = command()
        cmd.cog.cog_check = must_not_run
        self.assertIsNone(audit.classify(cmd).category)

    def test_overrides_and_disabled_are_visible(self):
        cmd = command("MOD", None)
        cmd.requires._global_rules = {123: object()}
        cmd.enabled = False
        text, counts, review = audit.build_report([cmd, cmd])
        self.assertIn("overrides configured", text)
        self.assertIn("disabled", text)
        self.assertEqual(sum(counts.values()), 1)
        self.assertEqual(review, 0)

    def test_empty_report(self):
        text, counts, review = audit.build_report([])
        self.assertEqual(len(counts), 5)
        self.assertEqual(sum(counts.values()), 0)
        self.assertEqual(review, 0)


if __name__ == "__main__":
    unittest.main()
