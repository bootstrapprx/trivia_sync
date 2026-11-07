import importlib
import sys
import types
import unittest
from unittest.mock import patch


class TestReconciliation(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.modules.setdefault("frappe", types.SimpleNamespace())
		cls.module = importlib.import_module("trivia_sync.integrations.reconciliation")

	def test_name_normalization_ignores_accents_case_and_spacing(self):
		self.assertEqual(self.module.normalize_name("  Língua   Portuguesa "), "lingua portuguesa")

	def test_exact_external_id_wins_and_ambiguous_name_is_not_guessed(self):
		frappe = self.module.frappe
		with patch.object(frappe.db, "sql", return_value=[{"name": "M-1"}]):
			self.assertEqual(self.module.resolve_catalog("Matéria", "ID-1", "Matemática")["name"], "M-1")
		with patch.object(frappe, "get_meta", return_value=types.SimpleNamespace(has_field=lambda field: field == "nome")), patch.object(
			frappe.db, "sql", side_effect=[[], [], [{"name": "M-1", "nome": "Matemática"}, {"name": "M-2", "nome": "Matemática"}]]
		):
			result = self.module.resolve_catalog("Matéria", "missing", "Matemática")
		self.assertEqual(result["status"], "ambiguous")
		self.assertIsNone(result["name"])

	def test_accented_doctype_catalog_uses_parameterized_sql(self):
		frappe = self.module.frappe
		with patch.object(frappe.db, "get_value", side_effect=AssertionError("query builder rejects accented DocTypes")), patch.object(
			frappe.db, "sql", return_value=[{"name": "ORG-1"}]
		) as sql:
			result = self.module.resolve_catalog("Órgão", "EXT-1", "Órgão Central")
		self.assertEqual(result["name"], "ORG-1")
		db_type = frappe.db.db_type
		quote = "`" if db_type == "mariadb" else '"'
		sql.assert_called_once_with(
			f"SELECT {quote}name{quote} FROM {quote}tabÓrgão{quote} WHERE {quote}source_id{quote} = %s LIMIT 1",
			("EXT-1",), as_dict=True,
		)

	def test_accented_doctype_name_match_uses_parameterized_sql(self):
		frappe = self.module.frappe
		with patch.object(frappe, "get_meta", return_value=types.SimpleNamespace(has_field=lambda field: field == "nome")), patch.object(
			frappe.db, "sql", return_value=[{"name": "ORG-1", "nome": "Órgão Central"}]
		) as sql:
			result = self.module.resolve_catalog("Órgão", name="Órgão Central")
		self.assertEqual((result["status"], result["name"], result["method"]), ("resolved", "ORG-1", "unique_name"))
		self.assertEqual(sql.call_args.args[0], 'SELECT "name", "nome" FROM "tabÓrgão"')

	def test_syllabus_sync_marks_disappeared_nodes_obsolete_without_deleting(self):
		frappe = self.module.frappe
		existing = {"cargo-1/topic-old": "node-old"}
		new_node = types.SimpleNamespace(name="node-new", insert=lambda **kwargs: None)
		with patch.object(frappe.db, "sql", side_effect=[[], [{"name": "node-old", "source_path": "cargo-1/topic-old"}], None]) as sql, patch.object(
			frappe, "get_doc", return_value=types.SimpleNamespace(save=lambda **kwargs: None)
		), patch.object(frappe, "new_doc", return_value=new_node):
			result = self.module.sync_syllabus_tree("cargo-1", [{"id": "new", "titulo": "Novo"}], "v2")
		self.assertEqual(result["obsolete"], 1)
		self.assertEqual(result["deleted"], 0)
		self.assertEqual(sql.call_count, 3)

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


if __name__ == "__main__":
	unittest.main()
