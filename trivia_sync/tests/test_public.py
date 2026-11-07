import importlib
import sys
import types
import unittest
from unittest.mock import patch


class TestPublicCatalog(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.modules.setdefault("frappe", types.SimpleNamespace())
		cls.module = importlib.import_module("trivia_sync.public")

	def test_public_dto_contains_only_curated_contest_and_published_course_fields(self):
		frappe = self.module.frappe
		contest = {"name": "CON-1", "public_slug": "edital-2026", "titulo": "Edital 2026", "public_summary": "Resumo", "ano": 2026, "estado": "MG", "regiao": "Sudeste"}
		cargo = {"concurso": "CON-1", "cargo": "CARGO-1", "lms_course": "COURSE-1"}
		course = {"name": "COURSE-1", "title": "Curso público"}
		with patch.object(frappe, "get_all", side_effect=[[contest], [cargo], [course]]), patch.object(
			frappe.utils, "now_datetime", return_value="now"
		):
			result = self.module.list_public_contests()
		self.assertEqual(result, [{
			"slug": "edital-2026", "title": "Edital 2026", "summary": "Resumo", "year": 2026,
			"region": "Sudeste", "state": "MG", "courses": [{"title": "Curso público"}],
		}])
		self.assertNotIn("name", result[0])
		self.assertNotIn("source_key", result[0])

	def test_private_course_and_unpublished_contest_are_unreachable(self):
		frappe = self.module.frappe
		with patch.object(frappe, "get_all", side_effect=[[{"name": "CON-1", "public_slug": "hidden", "titulo": "Hidden", "public_summary": ""}], [{"concurso": "CON-1", "lms_course": "PRIVATE"}], []]), patch.object(
			frappe.utils, "now_datetime", return_value="now"
		):
			self.assertEqual(self.module.list_public_contests(), [])
		with patch.object(frappe, "get_all", return_value=[]), patch.object(
			frappe.utils, "now_datetime", return_value="now"
		), self.assertRaises(Exception):
			self.module.get_public_contest("hidden")


if __name__ == "__main__":
	unittest.main()
