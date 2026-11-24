import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch


def _ensure_frappe_stub():
	frappe = sys.modules.setdefault("frappe", types.SimpleNamespace())
	if not hasattr(frappe, "PermissionError"):
		class _PermissionError(Exception):
			pass
		frappe.PermissionError = _PermissionError
	if not hasattr(frappe, "ValidationError"):
		class _ValidationError(Exception):
			pass
		frappe.ValidationError = _ValidationError
	if not hasattr(frappe, "throw"):
		def _throw(msg, exc=None):
			raise (exc or frappe.ValidationError)(msg)
		frappe.throw = _throw
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
	if not hasattr(frappe, "new_doc"):
		frappe.new_doc = None
	if not hasattr(frappe, "db"):
		frappe.db = types.SimpleNamespace(get_value=lambda *args, **kwargs: None)
	if not hasattr(frappe, "utils"):
		frappe.utils = types.SimpleNamespace(now_datetime=lambda: "2026-11-24 15:00:00")
	elif not hasattr(frappe.utils, "now_datetime"):
		frappe.utils.now_datetime = lambda: "2026-11-24 15:00:00"
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

	def test_generated_material_is_draft_and_has_source_provenance(self):
		frappe = self.module.frappe
		version = types.SimpleNamespace()
		recipe = types.SimpleNamespace(
			name="RECIPE-1", title="Lesson", course="COURSE-1", course_lesson="LESSON-1", concurso_cargo="CC-1",
			prompt="Explain", status="Draft", flags=types.SimpleNamespace(), material_versions=[],
			append=lambda field, row: version.__dict__.update(row), save=lambda **kwargs: None,
		)
		settings = types.SimpleNamespace(ai_enabled=1, ai_model="model-1")
		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(
			frappe, "get_single", return_value=settings
		), patch.object(self.module, "_check_course"), patch.object(
			self.module, "_current_source_hash", return_value=("hash", ["qapi:Q1"], [{"source_key": "qapi:Q1", "content_hash": "hash", "enunciado": "Prompt"}], "")
		), patch.object(
			self.module, "OpenAICompatibleAdapter", return_value=types.SimpleNamespace(generate_material=lambda *args: {"title": "Aula", "content": "Draft content", "summary": "Resumo", "model": "model-1"})
		):
			result = self.module.generate_lesson_material("RECIPE-1", "mais")
		self.assertEqual(result["status"], "Draft")
		self.assertEqual(version.status, "Draft")
		self.assertEqual(version.origin, "AI")
		self.assertTrue(version.source_hash)
		self.assertEqual(version.model, "model-1")

	def test_manual_draft_submit_reject_and_approve_lifecycle(self):
		frappe = self.module.frappe
		versions = []
		recipe = types.SimpleNamespace(
			name="RECIPE-2", title="Lesson 2", course="COURSE-1", course_lesson="LESSON-1", concurso_cargo="CC-1",
			prompt="", status="Draft", flags=types.SimpleNamespace(), material_versions=versions,
			append=lambda field, row: versions.append(types.SimpleNamespace(**row)), save=lambda **kwargs: None,
		)
		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(
			self.module, "_check_course", return_value=(types.SimpleNamespace(), types.SimpleNamespace())
		), patch.object(
			self.module, "_current_source_hash", return_value=("hash-1", ["qapi:Q1"], [], "")
		), patch.object(frappe, "get_roles", return_value=["Trivia Editor"]):
			created = self.module.create_manual_lesson_material("RECIPE-2", "180", "<p>Conteudo autoral</p>", "Resumo")
			self.assertEqual(created["origin"], "Manual")
			self.assertEqual(created["status"], "Draft")
			submitted = self.module.submit_lesson_material("RECIPE-2", "180", 1)
			self.assertEqual(submitted["status"], "Pending Approval")
			with self.assertRaises(frappe.PermissionError):
				self.module.approve_lesson_material("RECIPE-2", "180", 1)

		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(
			self.module, "_current_source_hash", return_value=("hash-1", ["qapi:Q1"], [], "")
		), patch.object(frappe, "get_roles", return_value=["Trivia Reviewer"]):
			with self.assertRaises(Exception):
				self.module.reject_lesson_material("RECIPE-2", "180", 1, reason="")
			rejected = self.module.reject_lesson_material("RECIPE-2", "180", 1, reason="Ajustar exemplo")
			self.assertEqual(rejected["status"], "Rejected")
			self.assertEqual(versions[0].review_reason, "Ajustar exemplo")

		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(
			self.module, "_current_source_hash", return_value=("hash-1", ["qapi:Q1"], [], "")
		), patch.object(frappe, "get_roles", return_value=["Trivia Editor"]):
			resubmitted = self.module.submit_lesson_material("RECIPE-2", "180", 1)
			self.assertEqual(resubmitted["status"], "Pending Approval")

		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(
			self.module, "_current_source_hash", return_value=("hash-1", ["qapi:Q1"], [], "")
		), patch.object(frappe, "get_roles", return_value=["Trivia Reviewer"]):
			approved = self.module.approve_lesson_material("RECIPE-2", "180", 1, reason="OK")
			self.assertEqual(approved["status"], "Approved")

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
		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(self.module, "_check_course", return_value=(None, None)), patch.object(
			self.module, "_current_source_hash", return_value=("new", [], [], "")
		), patch.object(frappe, "new_doc", side_effect=AssertionError("must reject before publication")):
			result = self.module.publish_lesson_material("RECIPE-1", "180")
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

	def test_publishing_v2_supersedes_v1_and_unpublish_removes_block(self):
		frappe = self.module.frappe
		v1_marker = self.module._material_marker("RECIPE-1", "mais", 1)
		lesson = types.SimpleNamespace(
			course="COURSE-1",
			content=json.dumps({"blocks": [
				{"id": "manual-block", "type": "paragraph", "data": {"text": "Keep"}},
				{"id": v1_marker, "type": "paragraph", "data": {"text": "Old v1"}},
			]}),
			body="",
			save=lambda **kwargs: None,
		)
		v1 = types.SimpleNamespace(level="mais", version=1, status="Published", source_hash="hash", content="Old v1", model="m1")
		v2 = types.SimpleNamespace(level="mais", version=2, status="Approved", source_hash="hash", content="New v2", model="m1")
		recipe = types.SimpleNamespace(
			name="RECIPE-1", title="Lesson", course="COURSE-1", course_lesson="LESSON-1", concurso_cargo="CC-1",
			status="Published", flags=types.SimpleNamespace(), material_versions=[v1, v2], save=lambda **kwargs: None,
		)
		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(
			self.module, "_check_course", return_value=(types.SimpleNamespace(), lesson)
		), patch.object(self.module, "_current_source_hash", return_value=("hash", [], [], "")):
			pub = self.module.publish_lesson_material("RECIPE-1", "mais")
		self.assertEqual(pub["version"], 2)
		self.assertEqual(pub["superseded_versions"], [1])
		self.assertEqual(v1.status, "Superseded")
		self.assertEqual(v2.status, "Published")
		blocks = frappe.parse_json(lesson.content)["blocks"]
		self.assertEqual(len(blocks), 2)
		self.assertEqual(blocks[0]["id"], "manual-block")
		self.assertEqual(blocks[1]["data"]["text"], "New v2")

		with patch.object(frappe, "get_doc", return_value=recipe), patch.object(
			self.module, "_check_course", return_value=(types.SimpleNamespace(), lesson)
		), patch.object(frappe, "get_roles", return_value=["Trivia Integrator"]):
			unpub = self.module.unpublish_lesson_material("RECIPE-1", "mais")
		self.assertEqual(unpub["status"], "Draft")
		self.assertEqual(v2.status, "Archived")
		remaining = frappe.parse_json(lesson.content)["blocks"]
		self.assertEqual([b["id"] for b in remaining], ["manual-block"])

	def test_apostila_file_visibility_and_publication_tracking(self):
		frappe = self.module.frappe
		v1 = types.SimpleNamespace(level="180", version=1, status="Published", source_hash="old", content="Old")
		v2 = types.SimpleNamespace(level="180", version=2, status="Approved", source_hash="hash", content="Text")
		recipe = types.SimpleNamespace(name="AP-1", title="Apostila", course="COURSE-1", concurso_cargo=None, status="Draft", material_versions=[v1, v2])
		created = []

		class FakeFile:
			name = "FILE-1"
			file_url = "/private/files/book.pdf"

			def insert(self, **kwargs):
				created.append(self)

		for course, expected_private in (
			(types.SimpleNamespace(published=0, paid_course=0), 1),
			(types.SimpleNamespace(published=1, paid_course=0), 0),
		):
			v1.status = "Published"
			v2.status = "Approved"
			file = FakeFile()
			with patch.object(frappe, "get_doc", side_effect=[recipe, file]), patch.object(
				self.module, "_check_course", return_value=(course, None)
			), patch.object(self.module, "_current_source_hash", return_value=("hash", [], [], "")), patch.object(
				self.module, "get_pdf", return_value=b"%PDF"
			):
				result = self.module.export_apostila("AP-1", ["180"])
			self.assertEqual(result["is_private"], expected_private)
			self.assertEqual(v1.status, "Superseded")
			self.assertEqual(v2.status, "Published")
			self.assertEqual(v2.exported_file, "FILE-1")
			self.assertEqual(v2.exported_file_url, "/private/files/book.pdf")
			self.assertEqual(recipe.status, "Published")

	def test_stale_invalidation_marks_affected_recipes(self):
		frappe = self.module.frappe
		v1 = types.SimpleNamespace(level="mais", version=1, status="Published", source_hash="old-hash")
		recipe = types.SimpleNamespace(
			name="RECIPE-3", title="Lesson", course="COURSE-1", course_lesson="LESSON-1", concurso_cargo="CC-1",
			status="Published", flags=types.SimpleNamespace(), material_versions=[v1], save=lambda **kwargs: None,
		)
		question = types.SimpleNamespace(concurso_cargo="CC-1")
		with patch.object(frappe, "get_all", side_effect=[[], ["RECIPE-3"], [], []]), patch.object(
			frappe, "get_doc", return_value=recipe
		), patch.object(self.module, "_current_source_hash", return_value=("new-hash", ["qapi:Q1"], [], "")):
			invalidated = self.module.invalidate_stale_materials_for_question(question)
		self.assertEqual(len(invalidated), 1)
		self.assertEqual(v1.status, "Stale")

	def test_validate_material_recipe_blocks_manual_status_bypass_and_published_edits(self):
		prev_row = types.SimpleNamespace(level="mais", version=1, status="Published", content="Locked")
		previous = types.SimpleNamespace(status="Published", material_versions=[prev_row])

		bypass_row = types.SimpleNamespace(level="mais", version=1, status="Approved", content="Locked")
		recipe_bypass = types.SimpleNamespace(
			status="Published", course="C1", course_lesson=None, flags=types.SimpleNamespace(),
			material_versions=[bypass_row], is_new=lambda: False, get_doc_before_save=lambda: previous,
		)
		with self.assertRaises(Exception):
			self.module.validate_material_recipe(recipe_bypass)

		edited_row = types.SimpleNamespace(level="mais", version=1, status="Published", content="Tampered")
		recipe_edit = types.SimpleNamespace(
			status="Published", course="C1", course_lesson=None, flags=types.SimpleNamespace(),
			material_versions=[edited_row], is_new=lambda: False, get_doc_before_save=lambda: previous,
		)
		with self.assertRaises(Exception):
			self.module.validate_material_recipe(recipe_edit)

	def test_current_source_hash_applies_subject_topic_and_syllabus_filters(self):
		frappe = self.module.frappe
		recipe = types.SimpleNamespace(
			title="Aula Morfologia",
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
				return ["Q-1", "Q-2"]
			return [{"source_key": "qapi:Q-1", "content_hash": "h1", "enunciado": "E1", "materia": "PT", "assunto": "Morfologia"}]

		with patch.object(frappe, "get_all", side_effect=fake_get_all):
			digest, keys, rows, _ = self.module._current_source_hash(recipe)
		self.assertTrue(digest)
		self.assertEqual(keys, ["qapi:Q-1"])
		self.assertEqual(len(rows), 1)
		self.assertEqual(captured[0], ("Trivia Question Syllabus Topic", {"conteudo_programatico": "SYL-1"}))
		self.assertEqual(
			captured[1][1],
			{
				"review_status": "Approved",
				"redistribution_status": "Approved",
				"concurso_cargo": "CC-1",
				"trivia_materia": "SUB-PT",
				"trivia_assunto": "TOP-MORF",
				"name": ["in", ["Q-1", "Q-2"]],
			},
		)


if __name__ == "__main__":
	unittest.main()
