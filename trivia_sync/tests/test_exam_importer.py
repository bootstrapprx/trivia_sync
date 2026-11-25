import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch


SAMPLE_MANAUSPREV_YAML = """prova:
  titulo: Concurso Público Manausprev - Analista Previdenciário
  especialidade: Contabilidade
  orgao: Prefeitura de Manaus - Manaus Previdência (Manausprev)
  banca: Fundação Carlos Chagas (FCC)
  data: Março de 2015
  caderno: C03 - Tipo 001
  total_questoes: 3
  duracao: 3 horas e 30 minutos
  gabarito: Não informado no PDF enviado.
textos_apoio:
- id: floresta_tropical
  questoes: 1 a 2
  fonte: Adaptado de Antônio Donato Nobre, O Futuro Climático da Amazônia.
  texto: |-
    Numa definição solta, a floresta tropical é um tapete multicolorido, estruturado e vivo.

    A mítica floresta amazônica vai muito além de um museu geográfico.
questoes:
- numero: 1
  disciplina: Língua Portuguesa
  texto_ou_contexto: floresta_tropical
  enunciado: Depreende-se do texto que
  alternativas:
    A: os organismos habitam a floresta tropical.
    B: o desmatamento transformou tudo em museu.
    C: a definição de Einstein forjou iniciativas.
    D: empresas buscam extrair matéria-prima.
    E: os princípios são ineficazes.
- numero: 2
  disciplina: Língua Portuguesa
  texto_ou_contexto: floresta_tropical
  enunciado: 'Traduz-se corretamente um segmento do texto em:'
  alternativas:
    A: primordial vida marinha = preponderante nascente
    B: propelida pela luz solar = arrefecida
    C: recuperar esse valor intrínseco = reaver essa importância inerente
    D: colônia extravagante = linhagem errante
    E: resiliente biologia = perseverante bioma
- numero: 3
  disciplina: Contabilidade Geral
  enunciado: |-
    Sobre as características qualitativas fundamentais:
    I. Relevância faz diferença nas decisões.
    II. Verificabilidade permite consenso.

    Está correto o que se afirma APENAS em
  alternativas:
    A: I e II.
    B: I.
    C: II.
    D: nenhuma.
    E: todas.
"""


class FakeDoc:
	def __init__(self, doctype, store, name=None):
		self.doctype = doctype
		self._store = store
		self.name = name
		self._new = name is None
		self.questions = []
		self.trivia_knowledge_pages = []
		self.trivia_syllabus_topics = []
		for idx in range(1, 11):
			setattr(self, f"option_{idx}", "")
			setattr(self, f"is_correct_{idx}", 0)
			setattr(self, f"explanation_{idx}", "")

	def is_new(self):
		return self._new

	def set(self, field, value):
		setattr(self, field, value)

	def get(self, field, default=None):
		return getattr(self, field, default)

	def append(self, field, row):
		getattr(self, field).append(types.SimpleNamespace(**row))

	def insert(self, **kwargs):
		if not self.name:
			idx = len(self._store.setdefault(self.doctype, {})) + 1
			self.name = f"{self.doctype.replace(' ', '-').upper()}-{idx}"
		self._new = False
		self._store.setdefault(self.doctype, {})[self.name] = self

	def save(self, **kwargs):
		self._new = False
		self._store.setdefault(self.doctype, {})[self.name] = self


class TestExamImporter(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe = sys.modules.setdefault("frappe", types.SimpleNamespace())
		frappe.ValidationError = type("ValidationError", (Exception,), {})
		frappe.PermissionError = type("PermissionError", (Exception,), {})
		frappe.throw = lambda msg, exc=None: (_ for _ in ()).throw((exc or frappe.ValidationError)(msg))
		frappe.only_for = lambda roles: None
		frappe.get_roles = lambda *a, **k: ["System Manager"]
		frappe.get_all = lambda *a, **k: []
		frappe.get_doc = None
		frappe.new_doc = None
		frappe.get_meta = lambda dt: types.SimpleNamespace(has_field=lambda f: f == "nome")
		frappe.db = types.SimpleNamespace(
			exists=lambda *a, **k: False,
			get_value=lambda *a, **k: None,
			commit=lambda: None,
		)
		cls.module = importlib.import_module("trivia_sync.integrations.exam_importer")

	def test_parse_exam_payload_extracts_manausprev_metadata_texts_and_questions(self):
		parsed = self.module.parse_exam_payload(SAMPLE_MANAUSPREV_YAML)
		self.assertEqual(parsed["prova"]["banca"], "Fundação Carlos Chagas (FCC)")
		self.assertEqual(parsed["prova"]["ano"], 2015)
		self.assertEqual(parsed["prova"]["duracao_minutos"], "210")
		self.assertEqual(len(parsed["textos_apoio"]), 1)
		self.assertIn("floresta_tropical", parsed["textos_apoio"])
		self.assertEqual(len(parsed["questions"]), 3)
		self.assertEqual(parsed["pending_count"], 3)
		self.assertEqual(parsed["answered_count"], 0)
		self.assertEqual(parsed["disciplines"], {"Língua Portuguesa": 2, "Contabilidade Geral": 1})

	def test_parse_answer_key_supports_numbered_compact_json_and_annulled(self):
		self.assertEqual(
			self.module.parse_answer_key("1-A 2-C 3-E 4-X"),
			{1: ["A"], 2: ["C"], 3: ["E"]},
		)
		self.assertEqual(
			self.module.parse_answer_key("ACXEB"),
			{1: ["A"], 2: ["C"], 4: ["E"], 5: ["B"]},
		)
		self.assertEqual(
			self.module.parse_answer_key('{"1": "B", "2": ["A", "D"]}'),
			{1: ["B"], 2: ["A", "D"]},
		)
		self.assertEqual(self.module.parse_answer_key("Não informado no PDF enviado."), {})

	def test_import_ready_exam_creates_texts_lms_questions_and_quiz_then_applies_answer_key(self):
		frappe = self.module.frappe
		store: dict[str, dict[str, FakeDoc]] = {}

		def fake_new_doc(doctype):
			return FakeDoc(doctype, store)

		def fake_get_doc(doctype, name):
			return store[doctype][name]

		def fake_exists(doctype, name=None):
			if isinstance(name, dict):
				return any(
					all(getattr(doc, k, None) == v for k, v in name.items())
					for doc in store.get(doctype, {}).values()
				)
			return name in store.get(doctype, {})

		def fake_get_value(doctype, filters, fieldname):
			if isinstance(filters, dict):
				for doc in store.get(doctype, {}).values():
					if all(getattr(doc, k, None) == v for k, v in filters.items()):
						return getattr(doc, fieldname, None)
				return None
			doc = store.get(doctype, {}).get(filters)
			return getattr(doc, fieldname, None) if doc else None

		with patch.object(frappe, "new_doc", side_effect=fake_new_doc), patch.object(
			frappe, "get_doc", side_effect=fake_get_doc
		), patch.object(frappe.db, "exists", side_effect=fake_exists), patch.object(
			frappe.db, "get_value", side_effect=fake_get_value
		):
			# 1. Import without answer key -> all 3 pending, Quiz created with 210 min duration
			res = self.module.import_ready_exam(SAMPLE_MANAUSPREV_YAML)
			self.assertEqual(res["questions_created"], 3)
			self.assertEqual(res["supporting_texts"], 1)
			self.assertEqual(res["pending_count"], 3)
			self.assertTrue(res["quiz_created"])

			quiz = store["LMS Quiz"][res["quiz_name"]]
			self.assertEqual(quiz.duration, "210")
			self.assertEqual(len(quiz.questions), 3)

			q1 = store["LMS Question"][quiz.questions[0].question]
			self.assertEqual(q1.trivia_answer_key_pending, 1)
			self.assertEqual(q1.trivia_status, "In Preparation")
			self.assertEqual(q1.trivia_banca, "Fundação Carlos Chagas (FCC)")
			self.assertEqual(q1.trivia_ano, 2015)
			self.assertTrue(bool(q1.trivia_texto_apoio))
			self.assertIn("Texto de apoio", q1.question)
			self.assertNotIn("Texto de apoio", q1.trivia_title)
			self.assertLessEqual(len(q1.trivia_title), 135)

			# 2. Apply manual/bulk answer key to the created Quiz
			state = self.module.get_quiz_answer_key_state(quiz.name)
			self.assertEqual(state["pending_count"], 3)

			applied = self.module.apply_quiz_answer_key(quiz.name, "1-A 2-C 3-A")
			self.assertEqual(applied["updated"], 3)

			q2 = store["LMS Question"][quiz.questions[1].question]
			self.assertEqual(q2.trivia_answer_key_pending, 0)
			self.assertEqual((q2.is_correct_1, q2.is_correct_2, q2.is_correct_3), (0, 0, 1))

			# 3. Re-importing same exam is idempotent (no duplicate questions or quizzes)
			res2 = self.module.import_ready_exam(SAMPLE_MANAUSPREV_YAML)
			self.assertEqual(len(store["LMS Question"]), 3)
			self.assertEqual(len(store["LMS Quiz"]), 1)
			self.assertFalse(res2["quiz_created"])


if __name__ == "__main__":
	unittest.main()
