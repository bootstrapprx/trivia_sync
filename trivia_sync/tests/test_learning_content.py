import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch


class TestLearningContent(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.modules.setdefault("frappe", types.SimpleNamespace())
		cls.module = importlib.import_module("trivia_sync.integrations.learning_content")

	def test_generated_material_is_draft_and_has_source_provenance(self):
		frappe = self.module.frappe
		version = types.SimpleNamespace()
		recipe = types.SimpleNamespace(name="RECIPE-1", title="Lesson", course="COURSE-1", course_lesson="LESSON-1", concurso_cargo="CC-1", prompt="Explain", material_versions=[], append=lambda field, row: version.__dict__.update(row), save=lambda **kwargs: None)
		settings = types.SimpleNamespace(ai_enabled=1)
		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(
			frappe, "get_single", return_value=settings
		), patch.object(self.module, "_check_course"), patch.object(
			self.module, "_current_source_hash", return_value=("hash", ["qapi:Q1"], [{"source_key":"qapi:Q1","content_hash":"hash","enunciado":"Prompt"}], "")
		), patch.object(
			self.module, "OpenAICompatibleAdapter", return_value=types.SimpleNamespace(generate_material=lambda *args: {"title": "Aula", "content": "Draft content", "summary": "Resumo", "model": "model-1"})
		):
			result = self.module.generate_lesson_material("RECIPE-1", "mais")
		self.assertEqual(result["status"], "Draft")
		self.assertEqual(version.status, "Draft")
		self.assertTrue(version.source_hash)
		self.assertEqual(version.model, "model-1")

	def test_course_permission_is_required_for_material_work(self):
		frappe = self.module.frappe
		recipe = types.SimpleNamespace(course="COURSE-1")
		course = types.SimpleNamespace(check_permission=lambda permission: (_ for _ in ()).throw(frappe.PermissionError()))
		with patch.object(frappe, "get_doc", return_value=course), self.assertRaises(frappe.PermissionError):
			self.module._check_course(recipe)

	def test_unapproved_or_stale_material_cannot_publish(self):
		frappe = self.module.frappe
		version = types.SimpleNamespace(level="180", version=1, status="Approved", source_hash="old")
		recipe = types.SimpleNamespace(name="RECIPE-1", course="COURSE-1", course_lesson="LESSON-1", concurso_cargo="CC-1", source_hash="new", material_versions=[version], save=lambda **kwargs: None)
		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(self.module, "_check_course", return_value=(None,None)), patch.object(
			self.module, "_current_source_hash", return_value=("new", [], [], "")
		), patch.object(frappe, "new_doc", side_effect=AssertionError("must reject before publication")):
			result=self.module.publish_lesson_material("RECIPE-1", "180")
		self.assertEqual(result["status"], "Stale")
		self.assertEqual(version.status, "Stale")

	def test_lesson_publish_preserves_editorjs_blocks_and_is_idempotent(self):
		frappe = self.module.frappe
		content = {"blocks": [{"id": "old", "type": "paragraph", "data": {"text": "Keep"}}]}
		lesson = types.SimpleNamespace(course="COURSE-1", content=json.dumps(content), body="", save=lambda **kwargs: None)
		version = types.SimpleNamespace(level="mais", version=1, status="Approved", source_hash="hash", content="Generated", model="model-1")
		recipe = types.SimpleNamespace(course="COURSE-1", course_lesson="LESSON-1", concurso_cargo="CC-1", source_hash="hash", material_versions=[version], name="RECIPE-1", title="Lesson", save=lambda **kwargs: None)
		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(
			self.module, "_check_course", return_value=(types.SimpleNamespace(), lesson)
		), patch.object(self.module, "_current_source_hash", return_value=("hash", [], [], "")), patch.object(
			frappe.utils, "now_datetime", return_value="now"
		):
			first = self.module.publish_lesson_material("RECIPE-1", "mais")
		self.assertEqual(first["status"], "Published")
		blocks = frappe.parse_json(lesson.content)["blocks"]
		self.assertEqual(len(blocks), 2)
		self.assertEqual(blocks[0]["data"]["text"], "Keep")
		self.assertIn("Generated", blocks[1]["data"]["text"])
		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(
			self.module, "_check_course", return_value=(types.SimpleNamespace(), lesson)
		), patch.object(self.module, "_current_source_hash", return_value=("hash", [], [], "")):
			second = self.module.publish_lesson_material("RECIPE-1", "mais")
		self.assertTrue(second["reused"])

	def test_apostila_file_visibility_follows_published_free_course_policy(self):
		frappe = self.module.frappe
		recipe = types.SimpleNamespace(name="AP-1", title="Apostila", course="COURSE-1", concurso_cargo=None,
			material_versions=[types.SimpleNamespace(level="180", status="Approved", source_hash="hash", content="Text")])
		created=[]
		class FakeFile:
			name="FILE-1"; file_url="/private/files/book.pdf"
			def insert(self, **kwargs): created.append(self)
		for course, expected_private in ((types.SimpleNamespace(published=0,paid_course=0),1),(types.SimpleNamespace(published=1,paid_course=0),0)):
			file=FakeFile()
			with patch.object(frappe,"get_doc",side_effect=[recipe,file]), patch.object(
				self.module,"_check_course",return_value=(course,None)
			), patch.object(self.module,"_current_source_hash",return_value=("hash",[],[],"")), patch.object(
				self.module,"get_pdf",return_value=b"%PDF"
			):
				result=self.module.export_apostila("AP-1",["180"])
			self.assertEqual(result["is_private"],expected_private)


if __name__ == "__main__":
	unittest.main()
