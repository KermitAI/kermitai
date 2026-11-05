import ast
from pathlib import Path
import unittest
from decimal import Decimal, InvalidOperation

SOURCE = Path(__file__).resolve().parents[1] / "forms.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
SCOPE = {"Decimal": Decimal, "InvalidOperation": InvalidOperation}
exec(compile(ast.Module(body=[node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name in ("validate", "position", "report")], type_ignores=[]), str(SOURCE), "exec"), SCOPE)
validate = SCOPE["validate"]


class ValidationTests(unittest.TestCase):
    def test_numbers(self):
        for value in ("0", "-12.5", "1e3"):
            self.assertEqual(validate("number", value), value)
        for value in ("NaN", "Infinity", "hello", ""):
            with self.assertRaises(ValueError):
                validate("number", value)

    def test_yes_no(self):
        self.assertEqual(validate("yesno", " YES "), "YES")
        with self.assertRaises(ValueError):
            validate("yesno", "maybe")

    def test_text(self):
        self.assertEqual(validate("paragraph", " a\nb "), "a\nb")
        with self.assertRaises(ValueError):
            validate("short", "   ")

    def test_all_python_parses(self):
        for path in SOURCE.parent.rglob("*.py"):
            ast.parse(path.read_text(encoding="utf-8-sig"))


class QuestionnaireTests(unittest.TestCase):
    def draft(self):
        return dict(form_id="apply", token="token", answers={"0": "Hello"},
                    form=dict(name="Apply", questions=[dict(text="Why?", type="short"), dict(text="When?", type="short")]))

    def test_legacy_position(self):
        draft = self.draft()
        draft["page"] = 1
        self.assertEqual(SCOPE["position"](draft), 1)
        draft["step"] = 2
        self.assertEqual(SCOPE["position"](draft), 2)

    def test_complete_review(self):
        draft = self.draft()
        draft["answers"]["1"] = "Tomorrow"
        text = SCOPE["report"](draft, 123)
        for value in ("Member ID: 123", "apply", "token", "Why?", "Hello", "When?", "Tomorrow"):
            self.assertIn(value, text)
