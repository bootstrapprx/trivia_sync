import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch


class FakeLMSQuestion:
	def __init__(self, name="QTS-1", is_new_doc=True):
		self.name = name
		self._new = is_new_doc
		self.trivia_status = "In Preparation"
		self.trivia_knowledge_pages = []
		self.trivia_syllabus_topics = []
		for idx in range(1, 11):
			setattr(self, f"option_{idx}", "")
			setattr(self, f"is_correct_{idx}", 0)
			setattr(self, f"explanation_{idx}", "")

	def is_new(self):
		return self._new

	def set(self, field, value):
		setattr(self, field, value)

	def get(self, field, default=None):
		return getattr(self, field, default)

	def append(self, field, row):
		getattr(self, field).append(types.SimpleNamespace(**row))

	def insert(self, **kwargs):
		self._new = False

	def save(self, **kwargs):
		self._new = False


class TestLMSQuestionsBridge(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe = sys.modules.setdefault("frappe", types.SimpleNamespace())
		frappe.ValidationError = type("ValidationError", (Exception,), {})
		frappe.PermissionError = type("PermissionError", (Exception,), {})
		frappe.throw = lambda msg, exc=None: (_ for _ in ()).throw((exc or frappe.ValidationError)(msg))
		frappe.only_for = lambda roles: None
		frappe.get_roles = lambda *a, **k: ["System Manager"]
		frappe.get_all = lambda *a, **k: []
		frappe.get_doc = lambda *a, **k: None
		frappe.new_doc = lambda *a, **k: None
		frappe.get_meta = lambda dt: types.SimpleNamespace(has_field=lambda f: False)
		frappe.db = types.SimpleNamespace(
			exists=lambda *a, **k: False,
			get_value=lambda *a, **k: None,
			table_exists=lambda *a, **k: False,
			sql=lambda *a, **k: [],
			commit=lambda: None,
		)
		cls.module = importlib.import_module("trivia_sync.integrations.lms_questions")

	def test_accepts_two_four_and_five_options_directly_into_lms_question(self):
		frappe = self.module.frappe
		for count in (2, 4, 5):
			opts = {chr(65 + i): f"Alternative {i + 1}" for i in range(count)}
			created_doc = FakeLMSQuestion(f"QTS-{count}")
			data = {
				"qcode": f"Q-{count}",
				"source_key": f"qapi:Q-{count}",
				"source_type": "QAPI",
				"enunciado": "Qual a correta?",
				"options": json.dumps(opts),
				"correct_options": '["B"]',
				"banca": "VUNESP",
				"materia": "Português",
				"assunto": "Sintaxe",
			}
			with patch.object(frappe.db, "get_value", return_value=None), patch.object(
				frappe, "new_doc", return_value=created_doc
			):
				res = self.module.upsert_qapi_lms_question(data)
			self.assertEqual(res, "created")
			self.assertEqual(created_doc.trivia_detected_option_count, count)
			self.assertEqual(created_doc.is_correct_2, 1)
			self.assertEqual(created_doc.trivia_status, "In Preparation")

	def test_treated_lms_question_is_not_overwritten_by_qapi_resync(self):
		frappe = self.module.frappe
		doc = FakeLMSQuestion("QTS-READY", is_new_doc=False)
		doc.question = "<p>Enunciado revisado pelo professor</p>"
		doc.option_1 = "A editada"
		doc.option_2 = "B editada"
		doc.is_correct_1 = 1
		doc.explanation_1 = "Correta"
		doc.explanation_2 = "Errada sem entregar gabarito"
		doc.trivia_status = "Ready"
		doc.trivia_banca = ""

		incoming = {
			"qcode": "Q-99",
			"source_key": "qapi:Q-99",
			"enunciado": "<p>Texto bruto QAPI</p>",
			"options": '{"A":"Bruto A","B":"Bruto B"}',
			"correct_options": '["A"]',
			"banca": "FGV",
		}
		with patch.object(frappe.db, "get_value", return_value="QTS-READY"), patch.object(
			frappe, "get_doc", return_value=doc
		):
			res = self.module.upsert_qapi_lms_question(incoming)
		self.assertEqual(res, "updated")
		self.assertEqual(doc.question, "<p>Enunciado revisado pelo professor</p>")
		self.assertEqual(doc.option_1, "A editada")
		self.assertEqual(doc.explanation_2, "Errada sem entregar gabarito")
		self.assertEqual(doc.trivia_banca, "FGV")

	def test_apply_explanations_marks_question_ready_when_all_options_explained(self):
		doc = FakeLMSQuestion("QTS-4", is_new_doc=False)
		for idx, text in enumerate(["Um", "Dois", "Três", "Quatro"], start=1):
			doc.set(f"option_{idx}", text)
		doc.is_correct_3 = 1
		filled = self.module.apply_explanations_to_lms_question(
			doc,
			{"A": "Erro A", "B": "Erro B", "C": "Acerto C", "D": "Erro D"},
		)
		self.assertEqual(filled, 4)
		self.assertEqual(doc.trivia_status, "Ready")
		self.assertEqual(doc.explanation_4, "Erro D")

	def test_compose_question_html_embeds_supporting_text_and_published_knowledge_idempotently(self):
		frappe = self.module.frappe
		knowledge_rows = [types.SimpleNamespace(knowledge_page="parassintese")]
		with patch.object(frappe.db, "exists", return_value=True), patch.object(
			frappe.db, "get_value", return_value="<p>Texto base da rã.</p>"
		), patch.object(
			frappe, "get_all", return_value=[{"name": "parassintese", "title": "Parassíntese", "slug": "parassintese"}]
		):
			first = self.module.compose_lms_question_html("<p>Enunciado?</p>", texto_apoio="TXT-1", knowledge_rows=knowledge_rows)
			second = self.module.compose_lms_question_html(first, texto_apoio="TXT-1", knowledge_rows=knowledge_rows)
		self.assertEqual(first, second)
		self.assertEqual(second.count("Texto base da rã."), 1)
		self.assertIn('/conhecimento?slug=parassintese', second)

	def test_migration_patch_moves_legacy_four_option_trivia_question_to_lms(self):
		frappe = self.module.frappe
		patch_mod = importlib.import_module("trivia_sync.patches.v0_6.migrate_to_lms_native")
		created = FakeLMSQuestion("QTS-MIG-1")
		legacy_row = {
			"name": "Q-TWP69J8",
			"qcode": "Q-TWP69J8",
			"source_key": "qapi:Q-TWP69J8",
			"source_type": "QAPI",
			"enunciado": "Analise a palavra ASQUEROSA.",
			"options": '{"A":"Agradável","B":"Horrível","C":"Repulsiva","D":"Nojenta"}',
			"correct_options": '["A"]',
			"option_explanations": '{"A":"Antônimo correto.","B":"Sinônimo.","C":"Sinônimo.","D":"Sinônimo."}',
			"ai_difficulty_stars": 2,
			"banca": "VUNESP",
		}
		with patch.object(frappe.db, "exists", return_value=False), patch.object(
			frappe.db, "table_exists", side_effect=lambda t: t == "Trivia Question"
		), patch.object(frappe.db, "sql", return_value=[legacy_row]), patch.object(
			frappe.db, "get_value", return_value=None
		), patch.object(frappe, "new_doc", return_value=created):
			counts = patch_mod.execute()
		self.assertEqual(counts["migrated"], 1)
		self.assertEqual(created.trivia_detected_option_count, 4)
		self.assertEqual(created.trivia_status, "Ready")
		self.assertEqual(created.trivia_ai_difficulty_stars, 0.4)
		self.assertEqual(created.explanation_2, "Sinônimo.")


if __name__ == "__main__":
	unittest.main()
