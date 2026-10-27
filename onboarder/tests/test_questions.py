"""Run without Red or Discord: python -m unittest discover -s onboarder/tests."""
import importlib.util
import itertools
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("onboarder_questions", Path(__file__).parents[1] / "questions.py")
questions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(questions)


class QuestionnaireTests(unittest.TestCase):
    def test_every_yes_no_path_reaches_review(self):
        for choices in itertools.product(("Yes", "No"), repeat=8):
            answers = {"0": {"details": {"Logging channels": "staff-log"}}}
            step, visited = 0, []
            while step < len(questions.QUESTIONS):
                visited.append(step)
                if step:
                    answers[str(step)] = {"choice": choices[step - 1]}
                step = questions.next_step(step, answers)
            self.assertEqual(step, 9)
            self.assertEqual(6 in visited, answers["5"]["choice"] == "Yes")
            self.assertTrue(all(index in visited for index in (0, 1, 2, 3, 4, 5, 7, 8)))

    def test_full_report_retains_long_answers_and_identity(self):
        text = "Detailed logging preferences " * 140
        session = dict(user_name="Applicant", user_id=42, requester_id=7,
                       guild_name="Staff server", guild_id=99, token="reference",
                       answers={"0": {"details": {"Logging channels": text}},
                                "5": {"choice": "No"},
                                "8": {"choice": "Yes", "details": {"Role requirement": "Either Verified or Member is fine", "Time allowed after joining": "2 hours"}}})
        result = questions.report(session)
        self.assertIn(text, result)
        self.assertIn("Applicant (ID: 42)", result)
        self.assertIn("Staff server (ID: 99)", result)
        self.assertIn("7. Stream alert message\nSkipped", result)
        self.assertIn("Role requirement: Either Verified or Member is fine", result)
        self.assertIn("Time allowed after joining: 2 hours", result)
        for index, (title, _) in enumerate(questions.QUESTIONS):
            self.assertIn(f"{index + 1}. {title}", result)

    def test_default_and_ticket_instructions_are_reported(self):
        self.assertEqual(questions.answer_text({"choice": "Yes", "details": {"Welcome message": "Use App default"}}), "Yes\nWelcome message: Use App default")
        self.assertIn("reach out manually", questions.TICKET_NOTICE)


if __name__ == "__main__":
    unittest.main()
