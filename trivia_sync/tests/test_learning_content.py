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
	if not hasattr(frappe, "ValidationError"):
		frappe.ValidationError = type("ValidationError", (Exception,), {})
	if not hasattr(frappe, "throw"):
		frappe.throw = lambda msg, exc=None: (_ for _ in ()).throw((exc or frappe.ValidationError)(msg))
	if not hasattr(frappe, "parse_json"):
		frappe.parse_json = json.loads
	if not hasattr(frappe, "session"):
		frappe.session = types.SimpleNamespace(user="Administrator")
	if not hasattr(frappe, "get_roles"):
		frappe.get_roles = lambda user=None: ["System Manager"]
	if not hasattr(frappe, "get_doc"):
		frappe.get_doc = None
	if not hasattr(frappe, "get_all"):
		frappe.get_all = lambda *args, **kwargs: []
	if not hasattr(frappe, "get_single"):
		frappe.get_single = None
	if not hasattr(frappe, "db"):
		frappe.db = types.SimpleNamespace(get_value=lambda *args, **kwargs: None, exists=lambda *a, **k: False)
	if not hasattr(frappe, "utils"):
		frappe.utils = types.SimpleNamespace(now_datetime=lambda: "2026-11-25 16:00:00")
	if "frappe.utils" not in sys.modules:
		sys.modules["frappe.utils"] = frappe.utils
	if "frappe.utils.html_utils" not in sys.modules:
		sys.modules["frappe.utils.html_utils"] = types.SimpleNamespace(sanitize_html=lambda text, **kwargs: text)
	if "frappe.utils.pdf" not in sys.modules:
		sys.modules["frappe.utils.pdf"] = types.SimpleNamespace(get_pdf=lambda markup: b"%PDF")
	if "requests" not in sys.modules:
		try:
			import requests  # noqa: F401
		except ImportError:
			sys.modules["requests"] = types.SimpleNamespace(RequestException=Exception)
	return frappe


class TestLearningContent(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		_ensure_frappe_stub()
		cls.module = importlib.import_module("trivia_sync.integrations.learning_content")

	def test_direct_course_lesson_draft_preserves_existing_editorjs_blocks(self):
		frappe = self.module.frappe
		lesson = types.SimpleNamespace(
			name="LESSON-1",
			title="Morfologia",
			course="COURSE-1",
			content=json.dumps({"blocks": [{"id": "keep-1", "type": "paragraph", "data": {"text": "Intro"}}]}),
			body="",
			check_permission=lambda p: None,
			save=lambda **kw: None,
		)
		settings = types.SimpleNamespace(ai_enabled=1, ai_backend="Frappe Flow", ai_model="m1")
		fake_adapter = types.SimpleNamespace(
			generate_material=lambda *args: {"title": "Aula", "content": "<p>Conteúdo gerado</p>", "summary": "Resumo", "model": "m1"}
		)
		with patch.object(frappe, "get_roles", return_value=["Trivia Editor"]), patch.object(
			frappe, "get_single", return_value=settings
		), patch.object(frappe, "get_doc", return_value=lesson), patch.object(
			self.module, "_query_lms_sources", return_value=[{"source_key": "qapi:Q1", "content_hash": "h1", "enunciado": "Pergunta", "materia": "PT", "assunto": "Morfologia"}]
		), patch.object(self.module, "get_ai_adapter", return_value=fake_adapter):
			res = self.module.generate_course_lesson_draft("LESSON-1", level="180")
		self.assertEqual(res["source_questions"], 1)
		blocks = json.loads(lesson.content)["blocks"]
		self.assertEqual(len(blocks), 2)
		self.assertEqual(blocks[0]["id"], "keep-1")
		self.assertIn("Conteúdo gerado", blocks[1]["data"]["text"])

	def test_study_guide_manual_submit_reject_approve_and_pdf_export(self):
		frappe = self.module.frappe
		versions = []
		recipe = types.SimpleNamespace(
			name="AP-1",
			title="Apostila Português",
			course="COURSE-1",
			concurso_cargo="CC-1",
			prompt="",
			status="Draft",
			flags=types.SimpleNamespace(),
			material_versions=versions,
			append=lambda field, row: versions.append(types.SimpleNamespace(**row)),
			save=lambda **kwargs: None,
		)
		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(
			self.module, "_check_course", return_value=(types.SimpleNamespace(published=1, paid_course=0), None)
		), patch.object(self.module, "_current_source_hash", return_value=("hash-1", ["qapi:Q1"], [], "")):
			with patch.object(frappe, "get_roles", return_value=["Trivia Editor"]):
				self.module.create_manual_apostila_material("AP-1", "180", "<p>Texto apostila</p>", "Resumo")
				self.module.submit_apostila_material("AP-1", "180", 1)
			with patch.object(frappe, "get_roles", return_value=["Trivia Reviewer"]):
				self.module.reject_apostila_material("AP-1", "180", 1, reason="Faltou exemplo")
			with patch.object(frappe, "get_roles", return_value=["Trivia Editor"]):
				self.module.submit_apostila_material("AP-1", "180", 1)
			with patch.object(frappe, "get_roles", return_value=["Trivia Reviewer"]):
				approved = self.module.approve_apostila_material("AP-1", "180", 1, reason="OK")
		self.assertEqual(approved["status"], "Approved")

		class FakeFile:
			name = "FILE-1"
			file_url = "/files/apostila.pdf"

			def insert(self, **kwargs):
				return None

		with patch.object(frappe, "get_doc", side_effect=[recipe, FakeFile()]), patch.object(
			self.module, "_check_course", return_value=(types.SimpleNamespace(published=1, paid_course=0), None)
		), patch.object(self.module, "_current_source_hash", return_value=("hash-1", ["qapi:Q1"], [], "")), patch.object(
			self.module, "get_pdf", return_value=b"%PDF"
		):
			exported = self.module.export_apostila("AP-1", ["180"])
		self.assertEqual(exported["is_private"], 0)
		self.assertEqual(versions[0].status, "Published")
		self.assertEqual(versions[0].exported_file, "FILE-1")

	def test_current_source_hash_queries_lms_questions_with_topic_filters(self):
		frappe = self.module.frappe
		recipe = types.SimpleNamespace(
			title="Apostila Morfologia",
			concurso_cargo="CC-1",
			trivia_subject="SUB-PT",
			trivia_topic="TOP-MORF",
			syllabus_topic="SYL-1",
			methodology=None,
			prompt="",
		)
		captured = []

		def fake_get_all(doctype, filters=None, **kwargs):
			captured.append((doctype, filters))
			if doctype == "Trivia Question Syllabus Topic":
				return ["QTS-1"]
			return [{"name": "QTS-1", "trivia_source_key": "qapi:Q1", "trivia_sync_hash": "h1", "question": "Pergunta", "trivia_materia": "PT", "trivia_assunto": "Morfologia"}]

		with patch.object(frappe, "get_all", side_effect=fake_get_all):
			digest, keys, rows, _ = self.module._current_source_hash(recipe)
		self.assertTrue(digest)
		self.assertEqual(keys, ["qapi:Q1"])
		self.assertEqual(len(rows), 1)
		self.assertEqual(captured[1][0], "LMS Question")
		self.assertEqual(captured[1][1]["trivia_status"], "Ready")
		self.assertEqual(captured[1][1]["trivia_subject_link"], "SUB-PT")
		self.assertEqual(captured[1][1]["trivia_topic_link"], "TOP-MORF")


if __name__ == "__main__":
	unittest.main()
