import unittest
from unittest.mock import patch
from answer_engine import match_faq, answer_question

class AnswerEngineTests(unittest.TestCase):
    def test_known_faq(self):
        self.assertIn("Docker", match_faq("What is Docker?"))
    def test_punctuation_and_case(self):
        self.assertIsNotNone(match_faq("WHAT IS PYTHON?!"))
    def test_unknown(self):
        self.assertIsNone(match_faq("How do black holes form?"))
    @patch("answer_engine.generate_answer")
    def test_faq_does_not_call_ai(self, mock_ai):
        self.assertIn("Docker", answer_question("What is Docker?"))
        mock_ai.assert_not_called()
    @patch("answer_engine.generate_answer", return_value="AI answer")
    def test_unknown_uses_ai(self, mock_ai):
        self.assertEqual(answer_question("How do black holes form?", []), "AI answer")
        mock_ai.assert_called_once()

if __name__ == "__main__": unittest.main()
