import importlib
import sys
import types
import unittest
from unittest.mock import patch


class TestReconciliation(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe = sys.modules.setdefault("frappe", types.SimpleNamespace())
		if not hasattr(frappe, "db"):
			frappe.db = types.SimpleNamespace(
				get_value=lambda *args, **kwargs: None,
				set_value=lambda *args, **kwargs: None,
				get_all=lambda *args, **kwargs: [],
			)
		if not hasattr(frappe, "logger"):
			frappe.logger = lambda *args, **kwargs: types.SimpleNamespace(info=lambda *a, **k: None)
		for attr in ("get_meta", "get_all", "get_doc", "new_doc"):
			if not hasattr(frappe, attr):
				setattr(frappe, attr, None)
		cls.module = importlib.import_module("trivia_sync.integrations.reconciliation")

	def test_name_normalization_ignores_accents_case_and_spacing(self):
		self.assertEqual(self.module.normalize_name("  Língua   Portuguesa "), "lingua portuguesa")

	def test_exact_external_id_wins_and_ambiguous_name_is_not_guessed(self):
		frappe = self.module.frappe
		with patch.object(frappe.db, "get_value", return_value="M-1"):
			self.assertEqual(self.module.resolve_catalog("Trivia Subject", "ID-1", "Matemática")["name"], "M-1")
		with patch.object(frappe, "get_meta", return_value=types.SimpleNamespace(has_field=lambda field: field == "nome")), patch.object(
			frappe, "get_all", return_value=[{"name": "M-1", "nome": "Matemática"}, {"name": "M-2", "nome": "Matemática"}]
		):
			result = self.module.resolve_catalog("Trivia Subject", "missing", "Matemática")
		self.assertEqual(result["status"], "ambiguous")
		self.assertIsNone(result["name"])

	def test_ascii_doctype_catalog_uses_query_builder(self):
		frappe = self.module.frappe
		with patch.object(frappe.db, "get_value", return_value="ORG-1") as get_value:
			result = self.module.resolve_catalog("Trivia Organization", "EXT-1", "Órgão Central")
		self.assertEqual(result["name"], "ORG-1")
		get_value.assert_called_once_with("Trivia Organization", {"source_id": "EXT-1"}, "name")

	def test_ascii_doctype_name_match_uses_query_builder(self):
		frappe = self.module.frappe
		with patch.object(frappe, "get_meta", return_value=types.SimpleNamespace(has_field=lambda field: field == "nome")), patch.object(
			frappe, "get_all", return_value=[{"name": "ORG-1", "nome": "Órgão Central"}]
		) as get_all:
			result = self.module.resolve_catalog("Trivia Organization", name="Órgão Central")
		self.assertEqual((result["status"], result["name"], result["method"]), ("resolved", "ORG-1", "unique_name"))
		get_all.assert_called_once_with("Trivia Organization", filters={}, fields=["name", "nome"])

	def test_syllabus_sync_marks_disappeared_nodes_obsolete_without_deleting(self):
		frappe = self.module.frappe
		existing = {"cargo-1/topic-old": "node-old"}
		new_node = types.SimpleNamespace(name="node-new", insert=lambda **kwargs: None)
		with patch.object(frappe.db, "get_value", side_effect=[None, None]), patch.object(
			frappe, "get_all", side_effect=[[], [{"name": "node-old", "source_path": "cargo-1/topic-old"}]]
		), patch.object(frappe.db, "set_value") as set_value, patch.object(
			frappe, "get_doc", return_value=types.SimpleNamespace(save=lambda **kwargs: None)
		), patch.object(frappe, "new_doc", return_value=new_node):
			result = self.module.sync_syllabus_tree("cargo-1", [{"id": "new", "titulo": "Novo"}], "v2")
		self.assertEqual(result["obsolete"], 1)
		self.assertEqual(result["deleted"], 0)
		set_value.assert_called_once_with("Trivia Syllabus Topic", "node-old", "is_obsolete", 1)

	def test_classification_backfill_is_idempotent_when_catalog_is_unresolved(self):
		frappe = self.module.frappe
		patch_module = importlib.import_module("trivia_sync.patches.v0_2.backfill_contest_relations")
		question = types.SimpleNamespace(raw_payload="{}", save=lambda **kwargs: self.fail("unchanged question was saved"))
		with patch.object(frappe, "get_all", return_value=["q1"]), patch.object(frappe, "get_doc", return_value=question), patch.object(
			frappe.db, "get_all", return_value=[]
		):
			first = patch_module.execute()
			second = patch_module.execute()
		self.assertEqual(first, second)
		self.assertEqual(first["updated"], 0)

	def test_apply_ai_topics_links_or_creates_catalogs_matches_syllabus_and_adds_tags(self):
		frappe = self.module.frappe
		created_docs = []

		class FakeNewDoc:
			def __init__(self, doctype):
				self.doctype = doctype
				self.name = f"NEW-{doctype.replace(' ', '-').upper()}"

			def insert(self, **kwargs):
				created_docs.append(self)

		linked_syllabus = []
		question = types.SimpleNamespace(
			name="Q-ZX43SGA",
			materia="",
			trivia_materia=None,
			assunto="",
			trivia_assunto=None,
			concurso_cargo="CC-1",
			ai_topics='["Morfologia", "Gênero dos Substantivos"]',
			conteudos_programaticos=linked_syllabus,
			append=lambda field, row: linked_syllabus.append(types.SimpleNamespace(**row)),
		)
		added_tags = []
		syllabus_rows = [{"name": "SYL-GEN", "titulo": "Gênero dos substantivos", "source_path": "pt/morf/gen", "concurso_cargo": "CC-1"}]
		with patch.object(frappe, "get_meta", return_value=types.SimpleNamespace(has_field=lambda f: f == "nome")), patch.object(
			frappe, "get_all", side_effect=lambda doctype, **kwargs: syllabus_rows if doctype == "Trivia Syllabus Topic" else []
		), patch.object(frappe.db, "get_value", return_value=None), patch.object(
			frappe, "new_doc", side_effect=FakeNewDoc
		), patch.object(
			self.module, "_add_frappe_tag", side_effect=lambda dt, name, tag: (added_tags.append(tag), tag)[1]
		):
			result = self.module.apply_ai_topics_to_question(
				question,
				suggested_materia="Língua Portuguesa",
				suggested_assunto="Morfologia",
			)
		self.assertEqual(question.materia, "Língua Portuguesa")
		self.assertEqual(question.trivia_materia, "NEW-TRIVIA-SUBJECT")
		self.assertEqual(question.assunto, "Morfologia")
		self.assertEqual(question.trivia_assunto, "NEW-TRIVIA-TOPIC")
		self.assertEqual(result["syllabus_topics_added"], ["SYL-GEN"])
		self.assertEqual([row.conteudo_programatico for row in linked_syllabus], ["SYL-GEN"])
		self.assertEqual(added_tags, ["Morfologia", "Gênero dos Substantivos"])
		self.assertEqual(len(created_docs), 2)


if __name__ == "__main__":
	unittest.main()
