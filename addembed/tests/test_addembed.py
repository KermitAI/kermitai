import ast
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
tree = ast.parse((ROOT / "addembed.py").read_text(encoding="utf-8-sig"))
helpers = ast.Module(body=[node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.Assign))], type_ignores=[])
scope = {"re": re}
exec(compile(helpers, "helpers", "exec"), scope)


class ContributionTests(unittest.TestCase):
    def test_format_and_trim(self):
        self.assertEqual(scope["append_entry"]("Intro", 42, "  My entry  "), "Intro\n\n<@42> - My entry")

    def test_description_boundary(self):
        suffix = "\n\n<@42> - x"
        self.assertEqual(len(scope["append_entry"]("a" * (4096 - len(suffix)), 42, "x")), 4096)
        with self.assertRaises(ValueError):
            scope["append_entry"]("a" * (4097 - len(suffix)), 42, "x")

    def test_whitespace_rejected(self):
        with self.assertRaises(ValueError):
            scope["append_entry"]("Intro", 42, " \n ")

    def test_options_with_spaces(self):
        result = scope["parse_options"]("label: Add your information style: green emoji: 📝 roles: <@&123> <@&456>")
        self.assertEqual(result["label"], "Add your information")
        self.assertEqual(result["style"], 3)
        self.assertEqual(result["roles"], "<@&123> <@&456>")

    def test_invalid_options(self):
        for value in ("label: X style: link emoji: none",
                      "label: X label: Y style: green emoji: none",
                      "label: X style: green",
                      "label: " + "a" * 81 + " style: green emoji: none"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                scope["parse_options"](value)

    def test_metadata(self):
        json.loads((ROOT / "info.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
