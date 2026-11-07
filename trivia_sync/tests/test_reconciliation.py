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
		with patch.object(frappe.db, "get_value", side_effect=["M-1", None]), patch.object(
			frappe.db, "get_all", return_value=[{"name": "M-1"}, {"name": "M-2"}]
		):
			self.assertEqual(self.module.resolve_catalog("Matéria", "ID-1", "Matemática")["name"], "M-1")
		with patch.object(frappe, "get_meta", return_value=types.SimpleNamespace(has_field=lambda field: True)), patch.object(
			frappe.db, "get_value", return_value=None
		), patch.object(
			frappe.db, "get_all", return_value=[{"name": "M-1", "nome": "Matemática"}, {"name": "M-2", "nome": "Matemática"}]
		):
			result = self.module.resolve_catalog("Matéria", "missing", "Matemática")
		self.assertEqual(result["status"], "ambiguous")
		self.assertIsNone(result["name"])

	def test_syllabus_sync_marks_disappeared_nodes_obsolete_without_deleting(self):
		frappe = self.module.frappe
		existing = {"cargo-1/topic-old": "node-old"}
		new_node = types.SimpleNamespace(name="node-new", insert=lambda **kwargs: None)
		with patch.object(frappe.db, "get_value", side_effect=lambda *a, **k: existing.get(a[1].get("source_path"))), patch.object(
			frappe, "get_doc", return_value=types.SimpleNamespace(save=lambda **kwargs: None)
		), patch.object(frappe, "get_all", return_value=[{"name": "node-old", "source_path": "cargo-1/topic-old"}]) as get_all, patch.object(
			frappe, "new_doc", return_value=new_node
		), patch.object(frappe.db, "set_value") as set_value:
			result = self.module.sync_syllabus_tree("cargo-1", [{"id": "new", "titulo": "Novo"}], "v2")
		self.assertEqual(result["obsolete"], 1)
		self.assertEqual(result["deleted"], 0)
		get_all.assert_called_once()
		set_value.assert_called_once_with("Conteúdo Programático", "node-old", "is_obsolete", 1)

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
