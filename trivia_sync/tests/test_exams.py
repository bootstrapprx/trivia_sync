import importlib
import sys
import types
import unittest
from unittest.mock import patch


class TestExamAssembly(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.modules.setdefault("frappe", types.SimpleNamespace())
		cls.module = importlib.import_module("trivia_sync.integrations.exams")

	def test_insufficient_pool_fails_before_creating_lms_rows(self):
		frappe = self.module.frappe
		prova = types.SimpleNamespace(
			name="PROVA-1", titulo="Prova teste", status="Draft", lms_course="COURSE-1", lms_lesson="LESSON-1",
			requested_questions=2, exam_blocks=[], exam_questions=[], exam_versions=[], exam_version=0, concurso=None, concurso_cargo="CC-1",
		)
		with patch.object(frappe, "get_doc", side_effect=[prova, types.SimpleNamespace(lms_course="COURSE-1", concurso=None), types.SimpleNamespace(name="LESSON-1", course="COURSE-1", check_permission=lambda permission: None)]), patch.object(
			frappe, "get_all", side_effect=[[{"name": "TQ-1", "lms_question": "LQ-1", "source_key": "qapi:Q1", "review_status": "Approved", "redistribution_status": "Approved", "source_license": "CC-BY"}], []]
		), patch.object(frappe, "new_doc", side_effect=AssertionError("insufficient pool must write nothing")), patch.object(
			frappe, "get_roles", return_value=["System Manager"]
		), self.assertRaises(Exception):
			self.module.build_simulado("PROVA-1")

	def test_build_creates_one_quiz_and_reuses_unchanged_blueprint(self):
		frappe = self.module.frappe
		class FakeProva:
			def __init__(self):
				self.name="PROVA-1"; self.titulo="Trivia Exam"; self.status="Draft"; self.concurso_cargo="CC-1"
				self.lms_course="COURSE-1"; self.lms_lesson="LESSON-1"; self.requested_questions=1
				self.exam_blocks=[]; self.exam_questions=[]; self.exam_versions=[]; self.exam_version=0; self.blueprint_hash=""; self.lms_quiz=None
			def set(self, field, value): setattr(self, field, value)
			def append(self, field, value): getattr(self, field).append(types.SimpleNamespace(**value))
			def save(self, **kwargs): pass
		prova = FakeProva(); prova.concurso = "CONTEST-1"
		lesson = types.SimpleNamespace(name="LESSON-1", course="COURSE-1", check_permission=lambda permission: None)
		cargo = types.SimpleNamespace(lms_course="COURSE-1", concurso="CONTEST-1")
		pool = [{"name": "TQ-1", "lms_question": "LQ-1", "source_key": "qapi:Q1", "content_hash": "hash", "projection_hash": "p-hash", "source_license": "CC-BY"}]
		class FakeQuiz:
			name="LMS-Q1"
			def __init__(self): self.questions=[]
			def append(self, field, value): self.questions.append(value)
			def insert(self, **kwargs): pass
		with patch.object(frappe, "get_doc", side_effect=[prova, cargo, lesson, prova, cargo, lesson]), patch.object(
			frappe, "get_all", side_effect=[pool, [], pool, []]
		), patch.object(frappe, "new_doc", return_value=FakeQuiz()) as new_doc:
			first = self.module.build_simulado("PROVA-1")
			second = self.module.build_simulado("PROVA-1")
		self.assertEqual((first["quiz"], second["quiz"], second["reused"]), ("LMS-Q1", "LMS-Q1", True))
		self.assertEqual(new_doc.call_count, 1)

	def test_selection_rejects_duplicate_questions_and_topic_shortage(self):
		pool = [
			{"name": "TQ-1", "source_key": "a", "topics": {"TOPIC-1"}},
			{"name": "TQ-2", "source_key": "b", "topics": {"TOPIC-2"}},
		]
		with self.assertRaises(ValueError):
			self.module._select_pool(pool, [{"name": "BLOCK-1", "count": 2, "topics": {"TOPIC-1"}}])

	def test_supersession_rewrites_only_this_exam_quiz_in_editorjs_content(self):
		lesson = types.SimpleNamespace(
			content='{"blocks":[{"type":"paragraph","data":{"text":"Keep me"}},{"type":"quiz","data":{"quiz":"OLD"}},{"type":"quiz","data":{"quiz":"OTHER"}}]}',
			body="Legacy body", save=lambda **kwargs: None,
		)
		self.module._rewrite_lesson(lesson, "NEW", ["OLD"])
		blocks = self.module.frappe.parse_json(lesson.content)["blocks"]
		self.assertTrue(any(block.get("data", {}).get("text") == "Keep me" for block in blocks))
		self.assertTrue(any(block.get("data", {}).get("quiz") == "OTHER" for block in blocks))
		self.assertFalse(any(block.get("data", {}).get("quiz") == "OLD" for block in blocks))
		self.assertTrue(any(block.get("data", {}).get("quiz") == "NEW" for block in blocks))

	def test_publish_supersedes_old_quiz_without_touching_unrelated_lesson_blocks(self):
		frappe = self.module.frappe
		old = types.SimpleNamespace(version=1, quiz="OLD", lesson="LESSON-1", status="Published")
		current = types.SimpleNamespace(version=2, quiz="NEW", lesson=None, status="Ready", published_at=None)
		prova = types.SimpleNamespace(
			name="PROVA-1", status="Ready", lms_quiz="NEW", lms_course="COURSE-1", lms_lesson="LESSON-1",
			exam_version=2, exam_versions=[old, current], save=lambda **kwargs: None,
		)
		lesson = types.SimpleNamespace(
			name="LESSON-1", course="COURSE-1",
			content='{"blocks":[{"type":"paragraph","data":{"text":"Keep"}},{"type":"quiz","data":{"quiz":"OLD"}},{"type":"quiz","data":{"quiz":"OTHER"}}]}',
			body="", check_permission=lambda permission: None, save=lambda **kwargs: None,
		)
		with patch.object(frappe, "get_doc", side_effect=[prova, lesson]), patch.object(
			frappe.utils, "now_datetime", return_value="now"
		):
			result = self.module.publish_prova("PROVA-1")
		blocks = frappe.parse_json(lesson.content)["blocks"]
		self.assertEqual(result["status"], "Published")
		self.assertEqual(old.status, "Superseded")
		self.assertEqual((prova.status, current.status, current.lesson), ("Published", "Published", "LESSON-1"))
		self.assertTrue(any(block.get("data", {}).get("quiz") == "OTHER" for block in blocks))
		self.assertTrue(any(block.get("data", {}).get("quiz") == "NEW" for block in blocks))
		self.assertFalse(any(block.get("data", {}).get("quiz") == "OLD" for block in blocks))

	def test_first_publish_marks_current_version_published(self):
		frappe = self.module.frappe
		current = types.SimpleNamespace(version=1, quiz="QUIZ-1", lesson=None, status="Ready", published_at=None)
		prova = types.SimpleNamespace(
			name="PROVA-1", status="Ready", lms_quiz="QUIZ-1", lms_course="COURSE-1", lms_lesson="LESSON-1",
			exam_version=1, exam_versions=[current], save=lambda **kwargs: None,
		)
		lesson = types.SimpleNamespace(
			name="LESSON-1", course="COURSE-1", content="", body="",
			check_permission=lambda permission: None, save=lambda **kwargs: None,
		)
		with patch.object(frappe, "get_doc", side_effect=[prova, lesson]), patch.object(
			frappe.utils, "now_datetime", return_value="now"
		):
			result = self.module.publish_prova("PROVA-1")
		self.assertEqual(result["status"], "Published")
		self.assertEqual((prova.status, current.status, current.lesson, current.published_at), ("Published", "Published", "LESSON-1", "now"))

	def test_prova_controller_rejects_duplicate_question_rows(self):
		frappe = self.module.frappe
		controller = importlib.import_module("trivia_sync.trivia_sync.doctype.trivia_prova.trivia_prova")
		prova = object.__new__(controller.TriviaProva)
		prova.is_new = lambda: True
		prova.source_type = "Manual"; prova.source_id = "manual-1"; prova.qapi_id = ""; prova.name = "P-1"
		prova.exam_questions = [types.SimpleNamespace(question="TQ-1"), types.SimpleNamespace(question="TQ-1")]
		with patch.object(controller, "source_identity", return_value=("manual-1", "Manual:manual-1")), patch.object(
			controller, "ensure_unique_source_key"
		), patch.object(frappe, "get_doc_before_save", return_value=None, create=True), self.assertRaises(Exception):
			prova.validate()


if __name__ == "__main__":
	unittest.main()
