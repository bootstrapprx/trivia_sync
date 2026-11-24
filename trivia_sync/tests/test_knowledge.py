import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch


def _ensure_frappe_stub():
	frappe = sys.modules.setdefault("frappe", types.SimpleNamespace())
	if not hasattr(frappe, "PermissionError"):
		frappe.PermissionError = type("PermissionError", (Exception,), {})
	if not hasattr(frappe, "DoesNotExistError"):
		frappe.DoesNotExistError = type("DoesNotExistError", (Exception,), {})
	if not hasattr(frappe, "ValidationError"):
		frappe.ValidationError = type("ValidationError", (Exception,), {})
	if not hasattr(frappe, "throw"):
		def _throw(msg, exc=None):
			raise (exc or frappe.ValidationError)(msg)
		frappe.throw = _throw
	if not hasattr(frappe, "only_for"):
		frappe.only_for = lambda roles: None
	if not hasattr(frappe, "get_roles"):
		frappe.get_roles = lambda user=None: ["System Manager"]
	if not hasattr(frappe, "session"):
		frappe.session = types.SimpleNamespace(user="Administrator")
	if not hasattr(frappe, "db"):
		frappe.db = types.SimpleNamespace(get_value=lambda *a, **k: None, exists=lambda *a, **k: False, count=lambda *a, **k: 0)
	if not hasattr(frappe, "get_all"):
		frappe.get_all = lambda *a, **k: []
	if not hasattr(frappe, "get_doc"):
		frappe.get_doc = None
	if not hasattr(frappe, "new_doc"):
		frappe.new_doc = None
	if not hasattr(frappe, "utils"):
		frappe.utils = types.SimpleNamespace(now_datetime=lambda: "2026-11-24 19:50:00")
	return frappe


class TestKnowledgePages(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		_ensure_frappe_stub()
		cls.module = importlib.import_module("trivia_sync.integrations.knowledge")

	def test_slugify_concept_normalizes_portuguese_accents(self):
		self.assertEqual(self.module.slugify_concept("Derivação Parassintética"), "derivacao-parassintetica")
		self.assertEqual(self.module.slugify_concept("  Crase: casos proibidos! "), "crase-casos-proibidos")

	def test_link_knowledge_concepts_creates_hierarchy_and_reuses_existing(self):
		frappe = self.module.frappe
		store = {}

		class FakeDoc:
			def __init__(self, doctype):
				self.doctype = doctype
				self.related_concepts = []

			def append(self, field, row):
				getattr(self, field).append(types.SimpleNamespace(**row))

			def insert(self, **kwargs):
				self.name = self.slug
				store[self.name] = self

			def save(self, **kwargs):
				store[self.name] = self

		question_links = []
		question = types.SimpleNamespace(
			name="Q-ZG284RV",
			trivia_materia="SUB-PT",
			trivia_assunto="TOP-FORM",
			knowledge_pages=question_links,
			append=lambda field, row: question_links.append(types.SimpleNamespace(**row)),
		)
		concepts = [
			{
				"title": "Derivação Parassintética",
				"summary": "Acréscimo simultâneo de prefixo e sufixo.",
				"explanation": "Ocorre quando prefixo e sufixo entram juntos e a retirada de um deles inviabiliza a palavra.",
				"examples": "Emudecer, anoitecer, entardecer.",
				"exam_traps": "Não confundir com derivação prefixal e sufixal (ex.: infelizmente).",
				"sub_concepts": [
					{
						"title": "Derivação Prefixal e Sufixal",
						"summary": "Acréscimo independente de prefixo e sufixo.",
						"explanation": "Retirando-se um dos afixos, a palavra resultante continua existindo.",
						"examples": "Infelizmente (infeliz / felizmente).",
						"exam_traps": "Bancas misturam ambos na mesma alternativa.",
					}
				],
			}
		]

		def fake_get_value(doctype, filters, field):
			if isinstance(filters, dict) and "slug" in filters:
				return filters["slug"] if filters["slug"] in store else None
			return filters if filters in store else None

		with patch.object(frappe.db, "get_value", side_effect=fake_get_value), patch.object(
			frappe, "new_doc", side_effect=FakeDoc
		), patch.object(frappe, "get_doc", side_effect=lambda dt, name: store[name]):
			first = self.module.link_knowledge_concepts(question, concepts, ai_model="gemini/test")
			second = self.module.link_knowledge_concepts(question, concepts, ai_model="gemini/test")

		self.assertEqual(first["knowledge_pages_linked"], ["derivacao-parassintetica"])
		self.assertEqual(sorted(first["knowledge_pages_created"]), ["derivacao-parassintetica", "derivacao-prefixal-e-sufixal"])
		self.assertEqual(store["derivacao-parassintetica"].status, "Draft")
		self.assertEqual(store["derivacao-prefixal-e-sufixal"].parent_concept, "derivacao-parassintetica")
		self.assertEqual(
			[r.knowledge_page for r in store["derivacao-parassintetica"].related_concepts],
			["derivacao-prefixal-e-sufixal"],
		)
		self.assertEqual(second["knowledge_pages_created"], [])
		self.assertEqual(sorted(second["knowledge_pages_reused"]), ["derivacao-parassintetica", "derivacao-prefixal-e-sufixal"])
		self.assertEqual(len(question_links), 1)

	def test_publish_requires_reviewer_or_integrator_role(self):
		frappe = self.module.frappe
		doc = types.SimpleNamespace(name="parassintese", slug="parassintese", status="Draft", save=lambda **kwargs: None)
		with patch.object(frappe, "get_roles", return_value=["Trivia Editor"]), self.assertRaises(frappe.PermissionError):
			self.module.set_knowledge_page_status("parassintese", "Published")
		with patch.object(frappe, "get_roles", return_value=["Trivia Reviewer"]), patch.object(
			frappe, "get_doc", return_value=doc
		):
			res = self.module.set_knowledge_page_status("parassintese", "Published")
		self.assertEqual(res["status"], "Published")
		self.assertEqual(doc.reviewed_by, "Administrator")

	def test_setup_flow_knowledge_and_skill_handles_missing_embedding_gracefully(self):
		frappe = self.module.frappe
		created = []

		class FakeDoc:
			def __init__(self, doctype):
				self.doctype = doctype
				self.name = f"{doctype}-1"

			def insert(self, **kwargs):
				if self.doctype == "Flow Knowledge Base":
					raise RuntimeError("Configure an embedding model first")
				created.append(self)

		with patch.object(frappe, "only_for"), patch.object(
			frappe.db, "exists", return_value=True
		), patch.object(frappe.db, "get_value", return_value=None), patch.object(
			frappe, "new_doc", side_effect=FakeDoc
		):
			result = self.module.setup_flow_knowledge_and_skill()
		self.assertTrue(result["ok"])
		self.assertEqual(result["skill"], "Flow Skill-1")
		self.assertEqual(len(result["warnings"]), 1)
		self.assertIn("embedding model", result["warnings"][0])


if __name__ == "__main__":
	unittest.main()
