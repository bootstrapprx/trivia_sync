import importlib
import sys
import types
import unittest
from unittest.mock import patch


class FakeSettings:
	ai_enabled = 1
	ai_backend = "Frappe Flow"


class FakeCache:
	def __init__(self):
		self.data = {}

	def get_value(self, key):
		return self.data.get(key)

	def set_value(self, key, val, expires_in_sec=None):
		self.data[key] = val

	def delete_value(self, key):
		self.data.pop(key, None)


class TestAthenaCourseBuilder(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe = sys.modules.setdefault("frappe", types.SimpleNamespace())
		frappe.ValidationError = ValueError
		frappe.throw = lambda msg, exc=None: (_ for _ in ()).throw((exc or ValueError)(msg))
		frappe.only_for = lambda roles: None
		frappe.session = types.SimpleNamespace(user="professor@example.com")
		frappe.local = types.SimpleNamespace(site=None)
		frappe.utils = types.SimpleNamespace(now_datetime=lambda: "2026-11-27 16:45:00", sanitize_html=lambda s: s)
		frappe.log_error = lambda *a, **k: None
		frappe.generate_hash = lambda length=6: "abc123"
		if "requests" not in sys.modules:
			sys.modules["requests"] = types.SimpleNamespace(post=None, RequestException=Exception)
		cls.module = importlib.import_module("trivia_sync.integrations.course_builder")

	def _seed_question(self):
		doc = types.SimpleNamespace(
			name="QTS-2026-00213",
			trivia_qcode="EX-PREV-Q55",
			trivia_title="RPPS · Cálculo da pensão por morte na Lei 10.887/2004",
			question="<p>Hortênsia é servidora pública efetiva.</p>",
			option_1="Integralidade",
			option_2="Teto do RGPS + 70% do excedente",
			is_correct_1=0,
			is_correct_2=1,
			explanation_1="",
			explanation_2="",
			trivia_materia="Direito Previdenciário",
			trivia_assunto="Pensão por morte",
			trivia_banca="FCC",
			trivia_ano=2024,
			trivia_subject_link="SUB-PREV",
			trivia_topic_link="TOP-PENSAO",
			trivia_answer_key_pending=0,
			trivia_deprecated=0,
			trivia_deprecated_law="",
			trivia_replacement_law="",
			trivia_deprecation_note="",
			trivia_general_explanation="<p>Anotação didática do professor sobre o art. 2º.</p>",
			trivia_knowledge_pages=[],
			marks=2,
			type="Choices",
		)
		for i in range(3, 11):
			setattr(doc, f"option_{i}", "")
			setattr(doc, f"is_correct_{i}", 0)
			setattr(doc, f"explanation_{i}", "")
		return doc

	def test_plan_course_blueprint_respects_teacher_materials_toggle_and_filters_question_ids(self):
		seed = self._seed_question()
		frappe = self.module.frappe
		frappe.get_single = lambda name: FakeSettings()
		frappe.db = types.SimpleNamespace(exists=lambda dt, name=None: name == seed.name)
		frappe.get_doc = lambda dt, name: seed
		frappe.get_all = lambda dt, filters=None, **kw: [
			{
				"name": "QTS-2026-00214",
				"trivia_qcode": "EX-PREV-Q56",
				"trivia_title": "RPPS · Aposentadoria voluntária",
				"question": "<p>Outra questão pronta.</p>",
				"trivia_materia": "Direito Previdenciário",
				"trivia_assunto": "Pensão por morte",
				"trivia_banca": "FCC",
				"trivia_ano": 2024,
				"trivia_deprecated": 0,
			}
		] if dt == "LMS Question" else []

		seen_prompts = []

		class FakeAdapter:
			model = "athena-test"

			def _chat_json(self, messages, schema_name, schema, max_tokens):
				seen_prompts.append(messages[-1]["content"])
				return {
					"course_title": "Pensão por Morte no RPPS (Lei 10.887/2004)",
					"short_introduction": "Domine o cálculo da pensão por morte de servidores ativos e inativos.",
					"course_description": "<p>Curso completo sobre o art. 2º da Lei 10.887/2004.</p>",
					"chapters": [
						{
							"title": "Fundamentos e Regra de Cálculo",
							"description": "Base constitucional e legal",
							"lessons": [
								{
									"title": "Servidor ativo vs. aposentado",
									"objective": "Distinguir os incisos I e II do art. 2º",
									"key_points": ["Teto do RGPS", "Parcela de 70%"],
								}
							],
						}
					],
					"quiz_title": "Simulado · Pensão por Morte",
					"recommended_question_names": ["QTS-2026-00213", "HALLUCINATED-ID", "QTS-2026-00214"],
				}

		with patch.object(self.module, "get_ai_adapter", return_value=FakeAdapter()):
			res_with = self.module.plan_course_blueprint(seed_question=seed.name, use_teacher_materials=True)
			res_without = self.module.plan_course_blueprint(seed_question=seed.name, use_teacher_materials=False)

		self.assertIn("Anotação didática do professor", seen_prompts[0])
		self.assertNotIn("Anotação didática do professor", seen_prompts[1])
		self.assertEqual(
			res_with["blueprint"]["recommended_question_names"],
			["QTS-2026-00213", "QTS-2026-00214"],
		)

	def test_create_course_from_blueprint_builds_draft_course_chapters_lessons_and_quiz(self):
		seed = self._seed_question()
		deprecated_q = self._seed_question()
		deprecated_q.name = "QTS-OLD-8666"
		deprecated_q.trivia_deprecated = 1
		deprecated_q.marks = 3

		questions_db = {seed.name: seed, deprecated_q.name: deprecated_q}
		created_docs: dict[str, list] = {}
		seq = {"n": 0}
		cache = FakeCache()

		class FakeDoc:
			def __init__(self, doctype):
				seq["n"] += 1
				self.doctype = doctype
				self.name = f"{doctype.upper().replace(' ', '-')}-{seq['n']}"
				self.flags = types.SimpleNamespace(ignore_validate=False)
				self.chapters = []
				self.lessons = []
				self.questions = []
				self.instructors = []
				self.include_in_preview = 0
				self.quiz_id = None
				self.image = None
				self.total_marks = 0

			def append(self, table, row):
				getattr(self, table).append(types.SimpleNamespace(**row))

			def insert(self, ignore_permissions=False):
				created_docs.setdefault(self.doctype, []).append(self)
				return self

			def save(self, ignore_permissions=False):
				return self

		frappe = self.module.frappe
		frappe.get_single = lambda name: FakeSettings()
		frappe.new_doc = lambda dt: FakeDoc(dt)
		frappe.cache = lambda: cache
		frappe.db = types.SimpleNamespace(
			exists=lambda dt, name=None: (name in questions_db) if dt == "LMS Question" else False,
			commit=lambda: None,
			savepoint=lambda sp: None,
			rollback=lambda **kw: None,
			set_value=lambda *a, **k: None,
			get_value=lambda *a, **k: None,
		)
		frappe.get_doc = lambda dt, name: questions_db[name]
		frappe.get_all = lambda *a, **k: []

		long_lesson_html = (
			"<h2>Regra do Art. 2º da Lei nº 10.887/2004</h2>"
			"<p>"
			+ (
				"No regime próprio de previdência social, o cálculo histórico da pensão por morte "
				"observa o limite máximo dos benefícios do RGPS acrescido de setenta por cento da parcela "
				"que superar esse teto previdenciário, distinguindo servidores aposentados e em atividade. "
			)
			* 3
			+ "</p>"
		)

		class FakeWriterAdapter:
			model = "athena-writer"

			def _chat_json(self, messages, schema_name, schema, max_tokens):
				return {
					"html_content": long_lesson_html,
					"summary": "Resumo didático completo da aula sobre o art. 2º.",
				}

		blueprint = {
			"course_title": "Curso Pensão por Morte RPPS",
			"short_introduction": "Introdução direta ao curso.",
			"course_description": "<p>Descrição completa.</p>",
			"chapters": [
				{
					"title": "Capítulo 1 · Regra Geral",
					"description": "Conceitos e cálculos",
					"lessons": [
						{"title": "Aula 1 · Teto do RGPS", "objective": "Calcular excedente", "key_points": ["Teto", "70%"]},
						{"title": "Aula 2 · Casos Práticos", "objective": "Resolver questões", "key_points": ["Ativo", "Inativo"]},
					],
				}
			],
			"quiz_title": "Quiz · Pensão por Morte",
			"recommended_question_names": [seed.name, deprecated_q.name],
		}

		with patch.object(self.module, "get_ai_adapter", return_value=FakeWriterAdapter()):
			res = self.module.create_course_from_blueprint(
				blueprint=blueprint,
				seed_question=seed.name,
				level="180",
				include_quiz=True,
				owner_user="professor@example.com",
			)

		self.assertTrue(res["course_created"])
		self.assertEqual(res["chapters_created"], 1)
		self.assertEqual(res["lessons_created"], 3)
		self.assertEqual(res["quiz_questions"], 2)

		course = created_docs["LMS Course"][0]
		self.assertEqual(course.published, 0)
		self.assertEqual(course.instructors[0].instructor, "professor@example.com")
		self.assertEqual(course.image, self.module.DEFAULT_COVER_IMAGE)

		quiz = created_docs["LMS Quiz"][0]
		self.assertEqual([(q.question, q.marks) for q in quiz.questions], [(seed.name, 2), (deprecated_q.name, 0)])
		self.assertEqual(quiz.total_marks, 2)

		practice_lesson = created_docs["Course Lesson"][-1]
		self.assertEqual(practice_lesson.quiz_id, quiz.name)


if __name__ == "__main__":
	unittest.main()
