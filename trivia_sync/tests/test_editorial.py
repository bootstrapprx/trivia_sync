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

	def test_migration_purges_dangling_custom_fields_disambiguates_duplicates_and_isolates_bad_rows(self):
		frappe = self.module.frappe
		patch_mod = importlib.import_module("trivia_sync.patches.v0_6.migrate_to_lms_native")

		deleted_docs = []
		cleared_doctypes = []
		frappe.delete_doc = lambda dt, name, **kw: deleted_docs.append((dt, name))
		frappe.clear_cache = lambda doctype=None: cleared_doctypes.append(doctype)
		frappe.db.has_column = lambda dt, col: (dt == "LMS Question" and col == "trivia_question")
		frappe.db.savepoint = lambda name: None
		frappe.db.rollback = lambda save_point=None: None

		good_doc = FakeLMSQuestion("QTS-DUP-OK")

		class FailingLMSQuestion(FakeLMSQuestion):
			def insert(self, **kwargs):
				raise RuntimeError("Simulated DB error on single corrupt row")

		bad_doc = FailingLMSQuestion("QTS-CORRUPT")

		rows = [
			{
				"name": "Q-DUP",
				"qcode": "Q-DUP",
				"source_key": "qapi:Q-DUP",
				"enunciado": "Questão com alternativas duplicadas na origem.",
				"options": '{"A":"Mesmo texto","B":"Mesmo texto","C":"Outra"}',
				"correct_options": '["A"]',
				"texto_apoio": "DELETED-TXT",
				"trivia_materia": "DELETED-SUBJ",
			},
			{
				"name": "Q-BAD",
				"qcode": "Q-BAD",
				"source_key": "qapi:Q-BAD",
				"enunciado": "Questão corrompida.",
				"options": '{"A":"Um","B":"Dois"}',
				"correct_options": '["B"]',
			},
		]

		def fake_get_all(dt, filters=None, **kw):
			if dt == "Custom Field" and isinstance(filters, dict) and "options" in filters:
				return ["LMS Question-custom_legacy_trivia_q"]
			return []

		with patch.object(
			frappe.db,
			"exists",
			side_effect=lambda dt, name=None: (dt == "Custom Field" and name == "LMS Question-trivia_question"),
		), patch.object(
			frappe.db, "table_exists", side_effect=lambda t: t == "Trivia Question"
		), patch.object(
			frappe.db, "sql", side_effect=lambda q, *a, **kw: rows if "FROM `tabTrivia Question`" in q else []
		), patch.object(
			frappe.db, "get_value", return_value=None
		), patch.object(
			frappe, "get_all", side_effect=fake_get_all
		), patch.object(
			frappe, "new_doc", side_effect=[good_doc, bad_doc]
		):
			counts = patch_mod.execute()

		self.assertEqual(counts, {"migrated": 1, "updated": 0, "skipped": 0, "failed": 1})
		self.assertIn(("Custom Field", "LMS Question-trivia_question"), deleted_docs)
		self.assertIn(("Custom Field", "LMS Question-custom_legacy_trivia_q"), deleted_docs)
		self.assertIn("LMS Question", cleared_doctypes)
		self.assertNotEqual(good_doc.option_1, good_doc.option_2)
		self.assertEqual(good_doc.option_2, "Mesmo texto (B)")
		self.assertIsNone(good_doc.trivia_texto_apoio)
		self.assertIsNone(good_doc.trivia_subject_link)

	def test_build_question_title_strips_passages_html_and_fits_tag_link_140_char_limit(self):
		long_passage = "<p>" + ("Texto longo de apoio com vários parágrafos. " * 15) + "</p>"
		long_stem = (
			"<p><strong>A palavra “quantidade” tem 10 letras.</strong> "
			"Assinale a alternativa que apresenta corretamente a quantidade exata de fonemas dessa palavra "
			"segundo a gramática normativa da língua portuguesa contemporânea.</p>"
		)
		composed = (
			f'<div class="trivia-supporting-passage"><p><strong>Texto de apoio</strong></p>{long_passage}</div><hr>'
			f'{long_stem}'
			f'<div class="trivia-knowledge-refs"><small><strong>Conceitos relacionados:</strong> <a href="/conhecimento?slug=fonetica">Fonética</a></small></div>'
		)
		title = self.module.build_question_title(composed, fallback="QTS-2026-00155")
		self.assertLessEqual(len(title), 135)
		self.assertNotIn("Texto de apoio", title)
		self.assertNotIn("Texto longo", title)
		self.assertNotIn("<", title)
		self.assertTrue(title.startswith("A palavra “quantidade” tem 10 letras."))
		self.assertTrue(title.endswith("…"))


if __name__ == "__main__":
	unittest.main()
