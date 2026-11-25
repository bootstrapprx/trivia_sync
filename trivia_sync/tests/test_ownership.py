import importlib
import sys
import types
import unittest
from unittest.mock import patch


class TestSourceOwnership(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe = sys.modules.setdefault("frappe", types.SimpleNamespace())
		if not hasattr(frappe, "db"):
			frappe.db = types.SimpleNamespace(
				get_value=lambda *a, **k: None,
				exists=lambda *a, **k: False,
			)
		if not hasattr(frappe, "get_meta"):
			frappe.get_meta = lambda *a, **k: types.SimpleNamespace(has_field=lambda f: False)
		if not hasattr(frappe, "get_all"):
			frappe.get_all = lambda *a, **k: []
		if not hasattr(frappe, "get_doc"):
			frappe.get_doc = None
		cls.module = importlib.import_module("trivia_sync.integrations.ownership")
		cls.lms_module = importlib.import_module("trivia_sync.integrations.lms_questions")

	def test_resource_update_ignores_fields_outside_source_allowlist(self):
		doc = types.SimpleNamespace(nome="Original", editorial_notes="Local")
		self.module.update_source_owned_fields(
			doc,
			{"nome": "From source", "editorial_notes": "Overwritten"},
			"Trivia Exam Board",
		)
		self.assertEqual((doc.nome, doc.editorial_notes), ("From source", "Local"))

	def test_source_fields_changed_detects_catalog_diff_only_on_source_fields(self):
		doc = types.SimpleNamespace(nome="CESPE", sigla="CEBRASPE", custom_note="Keep")
		self.assertFalse(
			self.module.source_fields_changed(
				doc, {"nome": "CESPE", "custom_note": "Changed"}, "Trivia Exam Board"
			)
		)
		self.assertTrue(
			self.module.source_fields_changed(
				doc, {"nome": "FGV"}, "Trivia Exam Board"
			)
		)

	def test_treated_lms_question_preserves_explanations_and_options_on_resync(self):
		frappe = self.lms_module.frappe

		class FakeLMSQuestion:
			def __init__(self):
				self.name = "LMS-Q-1"
				self.question = "<p>Enunciado revisado pelo professor</p>"
				self.option_1 = "Alternativa A revisada"
				self.is_correct_1 = 1
				self.explanation_1 = "Correta conforme regra gramatical."
				self.option_2 = "Alternativa B revisada"
				self.is_correct_2 = 0
				self.explanation_2 = "Incorreta pois não é parassíntese."
				for idx in range(3, 11):
					setattr(self, f"option_{idx}", "")
					setattr(self, f"is_correct_{idx}", 0)
					setattr(self, f"explanation_{idx}", "")
				self.trivia_status = "Ready"
				self.trivia_qcode = "Q-1"
				self.trivia_source_key = "qapi:Q-1"
				self.trivia_banca = ""
				self.trivia_sync_hash = "old-hash"
				self.saved = False

			def is_new(self):
				return False

			def save(self, **kwargs):
				self.saved = True

		treated_doc = FakeLMSQuestion()
		self.assertTrue(self.lms_module.is_lms_question_treated(treated_doc))

		payload = {
			"qcode": "Q-1",
			"source_key": "qapi:Q-1",
			"source_type": "QAPI",
			"enunciado": "Enunciado bruto da QAPI",
			"options": '{"A": "Bruta A", "B": "Bruta B"}',
			"correct_options": '["A"]',
			"banca": "VUNESP",
			"raw_payload": "{}",
		}
		with patch.object(frappe.db, "get_value", return_value="LMS-Q-1"), patch.object(
			frappe, "get_doc", return_value=treated_doc
		):
			result = self.lms_module.upsert_qapi_lms_question(payload)

		self.assertEqual(result, "updated")
		self.assertEqual(treated_doc.question, "<p>Enunciado revisado pelo professor</p>")
		self.assertEqual(treated_doc.option_1, "Alternativa A revisada")
		self.assertEqual(treated_doc.explanation_2, "Incorreta pois não é parassíntese.")
		self.assertEqual(treated_doc.trivia_banca, "VUNESP")


if __name__ == "__main__":
	unittest.main()
