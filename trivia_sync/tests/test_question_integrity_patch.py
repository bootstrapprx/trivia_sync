import importlib
import sys
import types
import unittest
from unittest.mock import patch


class TestQuestionIntegrityPatch(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.modules.setdefault("frappe", types.SimpleNamespace())
		cls.frappe = sys.modules["frappe"]
		cls.frappe.get_all = lambda *args, **kwargs: []
		cls.frappe.db = types.SimpleNamespace(set_value=lambda *args, **kwargs: None)
		cls.module = importlib.import_module("trivia_sync.patches.v0_5.question_integrity_fields")

	def test_patch_backfills_counts_and_legacy_review_states_without_renaming(self):
		rows = [
			types.SimpleNamespace(name="Q-1", options='{"A":"a","B":"b","C":"c","D":"d","E":"e"}', correct_option="C", correct_options=None, detected_option_count=0, review_status="Approved", editorial_status="Imported", lms_question=None, source_license="", source_attribution="", source_authors="", redistribution_reference="", redistribution_status="Pending", editorial_difficulty=None, allow_variable_options=0, exception_reason=""),
			types.SimpleNamespace(name="Q-2", options='{"A":"a","B":"b"}', correct_option="A", correct_options='["A"]', detected_option_count=2, review_status="Pending", editorial_status="Imported", lms_question="LMS-Q2", source_license="CC-BY", source_attribution="Required", source_authors="Author", redistribution_reference="terms", redistribution_status="Approved", editorial_difficulty=4, allow_variable_options=1, exception_reason="Original has two"),
			types.SimpleNamespace(name="Q-3", options='{"A":"a","B":"b","C":"c","D":"d"}', correct_option="A", correct_options=None, detected_option_count=4, review_status="Approved", editorial_status="Imported", lms_question=None, source_license="CC-BY", source_attribution="", source_authors="", redistribution_reference="", redistribution_status="Approved", editorial_difficulty=None, allow_variable_options=0, exception_reason=""),
		]
		with patch.object(self.frappe, "get_all", return_value=rows), patch.object(self.frappe.db, "set_value") as set_value:
			result = self.module.execute()
		self.assertEqual(result, {"checked": 3, "updated": 3})
		self.assertEqual(set_value.call_args_list[0].args[:2], ("Trivia Question", "Q-1"))
		self.assertEqual(set_value.call_args_list[0].args[2]["correct_options"], '["C"]')
		self.assertEqual(set_value.call_args_list[0].args[2]["editorial_status"], "Approved")
		self.assertEqual(set_value.call_args_list[1].args[2]["editorial_status"], "Pending Review")
		self.assertEqual(set_value.call_args_list[2].args[:2], ("LMS Question", "LMS-Q2"))
		self.assertEqual(set_value.call_args_list[2].args[2]["trivia_source_license"], "CC-BY")
		self.assertEqual(set_value.call_args_list[3].args[2]["editorial_status"], "Pending Review")


if __name__ == "__main__":
	unittest.main()
