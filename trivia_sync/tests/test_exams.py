import importlib
import sys
import types
import unittest
from unittest.mock import patch


class TestLMSQuizBuilder(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe = sys.modules.setdefault("frappe", types.SimpleNamespace())
		frappe.ValidationError = type("ValidationError", (Exception,), {})
		frappe.throw = lambda msg, exc=None: (_ for _ in ()).throw((exc or frappe.ValidationError)(msg))
		frappe.only_for = lambda roles: None
		frappe.db = types.SimpleNamespace(exists=lambda *a, **k: True)
		frappe.get_all = lambda *a, **k: []
		frappe.get_doc = None
		cls.module = importlib.import_module("trivia_sync.integrations.exams")

	def test_insufficient_pool_fails_without_modifying_quiz(self):
		frappe = self.module.frappe
		saved = []
		quiz = types.SimpleNamespace(
			name="QUIZ-1",
			questions=[],
			check_permission=lambda p: None,
			get=lambda f, d=None: [],
			set=lambda f, v: None,
			append=lambda f, v: None,
			save=lambda **kw: saved.append(True),
		)
		with patch.object(frappe, "get_doc", return_value=quiz), patch.object(
			frappe, "get_all", return_value=[{"name": "QTS-1", "marks": 1}]
		), self.assertRaises(Exception):
			self.module.build_lms_quiz_from_bank("QUIZ-1", count=3, only_ready=True)
		self.assertEqual(saved, [])

	def test_populates_lms_quiz_and_supports_appending_without_duplicates(self):
		frappe = self.module.frappe

		class FakeQuiz:
			name = "QUIZ-1"

			def __init__(self):
				self.questions = [types.SimpleNamespace(question="QTS-1", marks=1, type="Choices")]

			def check_permission(self, p):
				return None

			def get(self, field, default=None):
				return getattr(self, field, default)

			def set(self, field, value):
				setattr(self, field, value)

			def append(self, field, row):
				self.questions.append(types.SimpleNamespace(**row))

			def save(self, **kwargs):
				return None

		quiz = FakeQuiz()
		pool = [
			{"name": "QTS-1", "marks": 1},
			{"name": "QTS-2", "marks": 2},
			{"name": "QTS-3", "marks": 1},
		]
		with patch.object(frappe, "get_doc", return_value=quiz), patch.object(
			frappe, "get_all", return_value=pool
		):
			res = self.module.build_lms_quiz_from_bank("QUIZ-1", count=2, append_existing=True)
		self.assertEqual(res["added"], 2)
		self.assertEqual(res["total_questions"], 3)
		self.assertEqual([q.question for q in quiz.questions], ["QTS-1", "QTS-2", "QTS-3"])


if __name__ == "__main__":
	unittest.main()
