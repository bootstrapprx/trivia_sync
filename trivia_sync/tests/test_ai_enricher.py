import importlib
import json
import sys
import traceback
import types
import unittest
from unittest.mock import patch


class FakeSettings:
	ai_base_url = "https://llm.example.test/v1"
	ai_api_key = "configured"
	ai_model = "test-model"
	ai_timeout = 20
	ai_enabled = 1
	ai_batch_size = 1

	def get_password(self, fieldname):
		return "secret"


class FakeResponse:
	def __init__(self, payload):
		self.payload = payload

	def raise_for_status(self):
		return None

	def json(self):
		return self.payload


class TestAIEnricher(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe_stub = types.SimpleNamespace(
			get_single=lambda name: FakeSettings(),
			ValidationError=ValueError,
			db=types.SimpleNamespace(exists=lambda *a, **k: False, get_value=lambda *a, **k: None, commit=lambda: None),
		)
		sys.modules.setdefault("frappe", frappe_stub)
		if "requests" not in sys.modules:
			try:
				import requests  # noqa: F401
			except ImportError:
				sys.modules["requests"] = types.SimpleNamespace(post=None, RequestException=Exception)
		cls.module = importlib.import_module("trivia_sync.integrations.ai_enricher")

	def question(self):
		return {
			"qcode": "Q-1",
			"enunciado": "Explique o princípio.",
			"options": {"A": "Certo", "B": "Errado", "C": "Talvez", "D": "Nunca"},
			"correct_option": "A",
			"correct_options": ["A"],
			"materia": "Direito",
			"assunto": "Princípios",
			"banca": "Banca X",
			"ano": 2024,
		}

	def test_enrich_uses_strict_schema_and_returns_five_star_metadata(self):
		payload = {"choices": [{"message": {"content": json.dumps({"difficulty_stars": 5, "difficulty_label": "Muito difícil", "reason": "Exige múltiplas inferências e domínio específico.", "learning_objective": "Aplicar o princípio ao caso concreto.", "topics": ["Princípios"]})}}]}
		with patch.object(self.module.requests, "post", return_value=FakeResponse(payload)) as post:
			result = self.module.OpenAICompatibleAdapter(FakeSettings()).enrich(self.question())
		request = post.call_args.kwargs["json"]
		self.assertEqual(result["difficulty_stars"], 5)
		self.assertEqual(result["model"], "test-model")
		self.assertTrue(request["response_format"]["json_schema"]["strict"])

	def test_enrich_rejects_invalid_star_range(self):
		payload = {"choices": [{"message": {"content": json.dumps({"difficulty_stars": 6, "difficulty_label": "Muito difícil", "reason": "Texto suficientemente longo para passar.", "learning_objective": "Objetivo válido.", "topics": []})}}]}
		with patch.object(self.module.requests, "post", return_value=FakeResponse(payload)), self.assertRaises(self.module.AIEnrichmentError):
			self.module.OpenAICompatibleAdapter(FakeSettings()).enrich(self.question())

	def test_flow_adapter_reuses_frappe_flow_model_and_handles_four_options(self):
		flow_model_mod = types.ModuleType("frappe.flow.lib.model")
		flow_model_mod.model_config = lambda name, check_permission=True: {
			"model": "gemini/gemini-3.1-flash-lite",
			"api_key": "flow-secret",
			"api_base": None,
			"model_params": {},
		}
		flow_model_mod.litellm_route = lambda model_id, api_base: (model_id, api_base)

		def fake_completion(**kwargs):
			return {
				"choices": [{
					"message": {
						"content": json.dumps({
							"A": "Correta.",
							"B": "Incorreta B sem gabarito.",
							"C": "Incorreta C sem gabarito.",
							"D": "Incorreta D sem gabarito.",
						})
					}
				}]
			}

		litellm_mod = types.ModuleType("litellm")
		litellm_mod.completion = fake_completion
		settings = types.SimpleNamespace(ai_backend="Frappe Flow", ai_flow_model="Gemini Flash", ai_timeout=30)
		with patch.dict(sys.modules, {
			"frappe.flow": types.ModuleType("frappe.flow"),
			"frappe.flow.lib": types.ModuleType("frappe.flow.lib"),
			"frappe.flow.lib.model": flow_model_mod,
			"litellm": litellm_mod,
		}):
			adapter = self.module.get_ai_adapter(settings)
			draft = adapter.draft_option_explanations(self.question())
		self.assertEqual(len(draft["explanations"]), 4)
		self.assertEqual(draft["explanations"]["D"], "Incorreta D sem gabarito.")

	def test_frappe_rating_scale_conversion_maps_one_to_five_stars_accurately(self):
		self.assertEqual(self.module.stars_to_rating(1), 0.2)
		self.assertEqual(self.module.stars_to_rating(3), 0.6)
		self.assertEqual(self.module.stars_to_rating(5), 1.0)
		self.assertEqual(self.module.rating_to_stars(0.2), 1)
		self.assertEqual(self.module.rating_to_stars(1.0), 5)

	def test_batch_enrichment_populates_lms_question_explanations_and_marks_ready(self):
		class FakeLMSDoc:
			def __init__(self, name):
				self.name = name
				self.trivia_qcode = name
				self.question = "<p>Assinale o antônimo.</p>"
				self.option_1 = "Agradável"
				self.option_2 = "Horrível"
				self.option_3 = "Repulsiva"
				self.option_4 = "Nojenta"
				self.is_correct_1 = 1
				for i in range(2, 11):
					setattr(self, f"is_correct_{i}", 0)
				for i in range(5, 11):
					setattr(self, f"option_{i}", "")
				for i in range(1, 11):
					setattr(self, f"explanation_{i}", "")
				self.trivia_status = "In Preparation"
				self.trivia_ai_enriched_at = None
				self.trivia_knowledge_pages = []
				self.saved = 0

			def set(self, field, value):
				setattr(self, field, value)

			def save(self, **kwargs):
				self.saved += 1

		class FakeRun:
			name = "RUN-BATCH-LMS"
			def insert(self, **kwargs): pass
			def save(self, **kwargs): pass

		docs = {"QTS-1": FakeLMSDoc("QTS-1"), "QTS-2": FakeLMSDoc("QTS-2")}
		frappe = self.module.frappe
		frappe.get_single = lambda name: FakeSettings()
		frappe.new_doc = lambda name: FakeRun()
		frappe.get_doc = lambda dt, name: docs[name]
		frappe.get_all = lambda *a, **k: []
		frappe.utils = types.SimpleNamespace(now_datetime=lambda: "now")
		frappe.db = types.SimpleNamespace(commit=lambda: None, exists=lambda *a, **k: False, get_value=lambda *a, **k: None)
		frappe.log_error = lambda *args: None
		frappe.get_traceback = traceback.format_exc

		fake_adapter = types.SimpleNamespace(
			enrich_full=lambda q: {
				"difficulty_stars": 2,
				"difficulty_label": "Fácil",
				"reason": "Vocabulário direto.",
				"learning_objective": "Identificar antônimos.",
				"topics": ["Semântica"],
				"general_explanation": "Agradável é antônimo de asquerosa.",
				"suggested_materia": "Português",
				"suggested_assunto": "Semântica",
				"option_explanations": {"A": "Antônimo correto.", "B": "Sinônimo.", "C": "Sinônimo.", "D": "Sinônimo."},
				"enrichment_hash": "h123",
				"model": "test-model",
			},
			extract_knowledge_concepts=lambda q: {"concepts": [], "model": "test-model"},
		)
		with patch.object(self.module, "get_ai_adapter", return_value=fake_adapter), patch.object(
			self.module, "_safe_apply_ai_topics", return_value={}
		):
			res = self.module.enrich_questions_batch(
				question_names=["QTS-1", "QTS-2"],
				mode="full",
				include_knowledge=False,
			)
		self.assertEqual(res["processed"], 2)
		self.assertEqual(res["enriched"], 2)
		self.assertEqual(docs["QTS-1"].trivia_status, "Ready")
		self.assertEqual(docs["QTS-1"].explanation_4, "Sinônimo.")
		self.assertEqual(docs["QTS-1"].trivia_ai_difficulty_stars, 0.4)

	def test_pending_answer_key_blocks_option_explanations_and_keeps_question_in_preparation(self):
		class FakePendingDoc:
			def __init__(self):
				self.name = "QTS-2026-00217"
				self.trivia_qcode = "EX-C1FD3A-Q59"
				self.question = "<p>Declarado nulo o contrato, caberá</p>"
				self.option_1 = "indenizar todo o valor"
				self.option_2 = "vedar indenização"
				self.is_correct_1 = 1
				self.is_correct_2 = 0
				for i in range(3, 11):
					setattr(self, f"option_{i}", "")
					setattr(self, f"is_correct_{i}", 0)
				for i in range(1, 11):
					setattr(self, f"explanation_{i}", "")
				self.trivia_status = "In Preparation"
				self.trivia_answer_key_pending = 1
				self.trivia_knowledge_pages = []

			def set(self, field, value):
				setattr(self, field, value)

			def save(self, **kwargs):
				pass

		doc = FakePendingDoc()
		frappe = self.module.frappe
		frappe.only_for = lambda roles: None
		frappe.throw = lambda msg, exc=None: (_ for _ in ()).throw(ValueError(msg))
		frappe.get_single = lambda name: FakeSettings()
		frappe.get_doc = lambda dt, name: doc
		frappe.utils = types.SimpleNamespace(now_datetime=lambda: "now")

		# 1. Direct option explanation draft must be blocked while answer key is pending
		with self.assertRaises(ValueError):
			self.module.draft_question_option_explanations(doc.name)

		# 2. Full enrichment skips option explanations and keeps status In Preparation
		seen_payload = {}
		fake_adapter = types.SimpleNamespace(
			enrich=lambda q: (
				seen_payload.update(q),
				{
					"difficulty_stars": 3,
					"difficulty_label": "Média",
					"reason": "Cobra art. 59 parágrafo único da Lei 8.666/93.",
					"learning_objective": "Identificar efeitos da nulidade contratual.",
					"topics": ["Nulidade de Contratos"],
					"enrichment_hash": "h999",
					"model": "test-model",
				},
			)[1],
			extract_knowledge_concepts=lambda q: {"concepts": [], "model": "test-model"},
		)
		with patch.object(self.module, "get_ai_adapter", return_value=fake_adapter), patch.object(
			self.module, "_safe_apply_ai_topics", return_value={}
		):
			res = self.module.enrich_question_full(doc.name)

		self.assertTrue(res["explanations_skipped_pending_key"])
		self.assertEqual(seen_payload["correct_options"], [])
		self.assertEqual(doc.trivia_status, "In Preparation")
		self.assertEqual(doc.explanation_1, "")

	def test_replica_treplica_review_and_apply_fixes_wrong_answer_key_and_explanations(self):
		class FakeReviewDoc:
			def __init__(self):
				self.name = "QTS-2026-00217"
				self.trivia_qcode = "EX-C1FD3A-Q59"
				self.question = "<p>Declarado nulo o contrato, caberá</p>"
				self.option_1 = "indenizar todo o valor"
				self.option_2 = "indenizar pelos serviços executados"
				self.is_correct_1 = 1
				self.is_correct_2 = 0
				for i in range(3, 11):
					setattr(self, f"option_{i}", "")
					setattr(self, f"is_correct_{i}", 0)
				for i in range(1, 11):
					setattr(self, f"explanation_{i}", "")
				self.trivia_status = "In Preparation"
				self.trivia_answer_key_pending = 1
				self.trivia_general_explanation = "Art. 59, parágrafo único da Lei 8.666/93."

			def set(self, field, value):
				setattr(self, field, value)

			def save(self, **kwargs):
				pass

		doc = FakeReviewDoc()
		frappe = self.module.frappe
		frappe.only_for = lambda roles: None
		frappe.get_single = lambda name: FakeSettings()
		frappe.get_doc = lambda dt, name: doc
		frappe.utils = types.SimpleNamespace(now_datetime=lambda: "now")

		fake_adapter = types.SimpleNamespace(
			review_with_feedback=lambda q, reviewer_feedback, proposed_correct=None, history=None: {
				"agrees_with_reviewer": True,
				"ai_reply": "Você tem razão: pelo art. 59, parágrafo único da Lei 8.666/93, a indenização limita-se ao que foi executado.",
				"recommended_correct_options": ["B"],
				"difficulty_stars": 3,
				"difficulty_label": "Média",
				"reason": "Exige conhecimento direto do art. 59, parágrafo único.",
				"option_explanations": {
					"A": "Incorreta: não se indeniza parcela ainda não executada.",
					"B": "Correta: o contratado de boa-fé recebe pelo que executou até a declaração de nulidade.",
				},
				"model": "test-model",
			}
		)
		with patch.object(self.module, "get_ai_adapter", return_value=fake_adapter):
			review = self.module.review_question_with_feedback(
				doc.name,
				feedback="A correta é a B conforme art. 59 parágrafo único da Lei 8.666/93.",
				proposed_correct="B",
			)
		self.assertTrue(review["agrees_with_reviewer"])
		self.assertEqual(review["recommended_correct_options"], ["B"])
		# Reviewing alone must NOT mutate the document
		self.assertEqual(doc.is_correct_1, 1)
		self.assertEqual(doc.trivia_answer_key_pending, 1)

		applied = self.module.apply_question_ai_review(
			doc.name,
			correct_options=review["recommended_correct_options"],
			option_explanations=review["option_explanations"],
			difficulty_stars=review["difficulty_stars"],
			difficulty_label=review["difficulty_label"],
			reason=review["reason"],
			model=review["model"],
		)
		self.assertEqual(applied["correct_options"], ["B"])
		self.assertEqual((doc.is_correct_1, doc.is_correct_2), (0, 1))
		self.assertEqual(doc.trivia_answer_key_pending, 0)
		self.assertEqual(doc.trivia_status, "Ready")
		self.assertIn("executou", doc.explanation_2)

	def test_teacher_comment_is_isolated_from_initial_ai_and_only_used_in_replica(self):
		class FakeIsolatedDoc:
			def __init__(self):
				self.name = "QTS-2026-00213"
				self.trivia_qcode = "EX-PREV-Q55"
				self.question = "<p>Hortênsia é servidora pública efetiva.</p>"
				self.option_1 = "Integralidade da remuneração"
				self.option_2 = "Teto do RGPS mais 70% do excedente"
				self.is_correct_1 = 0
				self.is_correct_2 = 1
				for i in range(3, 11):
					setattr(self, f"option_{i}", "")
					setattr(self, f"is_correct_{i}", 0)
				for i in range(1, 11):
					setattr(self, f"explanation_{i}", "")
				self.trivia_status = "In Preparation"
				self.trivia_answer_key_pending = 0
				self.trivia_knowledge_pages = []
				self.trivia_general_explanation = "<p>Anotação exclusiva do professor sobre o art. 2º da Lei 10.887/2004.</p>"
				self.trivia_ai_comment = ""

			def set(self, field, value):
				setattr(self, field, value)

			def save(self, **kwargs):
				pass

		doc = FakeIsolatedDoc()
		frappe = self.module.frappe
		frappe.only_for = lambda roles: None
		frappe.get_single = lambda name: FakeSettings()
		frappe.get_doc = lambda dt, name: doc
		frappe.utils = types.SimpleNamespace(now_datetime=lambda: "now")

		# 1. Default payload never leaks Comentário do Professor
		default_payload = self.module._question_payload(doc)
		self.assertEqual(default_payload["explanation"], "")

		# 2. Replica payload includes Comentário do Professor only when requested
		replica_payload = self.module._question_payload(doc, include_teacher_comment=True)
		self.assertIn("Lei 10.887/2004", replica_payload["explanation"])

		# 3. Initial full enrichment writes to trivia_ai_comment and never touches trivia_general_explanation
		seen_initial_payload = {}
		fake_adapter = types.SimpleNamespace(
			enrich_full=lambda q: (
				seen_initial_payload.update(q),
				{
					"difficulty_stars": 3,
					"difficulty_label": "Média",
					"reason": "Cálculo de pensão por morte no RPPS.",
					"learning_objective": "Aplicar a regra do art. 2º da Lei 10.887/2004.",
					"topics": ["Pensão por morte"],
					"general_explanation": "Comentário gerado automaticamente pela IA.",
					"suggested_materia": "Direito Previdenciário",
					"suggested_assunto": "Pensão por morte",
					"option_explanations": {
						"A": "Incorreta: a EC 41/2003 eliminou a integralidade.",
						"B": "Correta: aplica-se o teto do RGPS mais 70% do excedente.",
					},
					"enrichment_hash": "h-iso",
					"model": "test-model",
				},
			)[1],
			extract_knowledge_concepts=lambda q: {"concepts": [], "model": "test-model"},
			review_with_feedback=lambda q, reviewer_feedback, proposed_correct=None, history=None: {
				"agrees_with_reviewer": True,
				"ai_reply": q.get("explanation", ""),
				"recommended_correct_options": ["B"],
				"difficulty_stars": 3,
				"difficulty_label": "Média",
				"reason": "Confirmado.",
				"option_explanations": {"A": "Errada.", "B": "Correta."},
				"model": "test-model",
			},
		)
		with patch.object(self.module, "get_ai_adapter", return_value=fake_adapter), patch.object(
			self.module, "_safe_apply_ai_topics", return_value={}
		):
			self.module.enrich_question_full(doc.name)

		self.assertEqual(seen_initial_payload["explanation"], "")
		self.assertEqual(doc.trivia_ai_comment, "Comentário gerado automaticamente pela IA.")
		self.assertIn("Anotação exclusiva do professor", doc.trivia_general_explanation)

		# 4. Réplica receives teacher comment when opted in, and omits it when opted out
		with patch.object(self.module, "get_ai_adapter", return_value=fake_adapter):
			res_with = self.module.review_question_with_feedback(doc.name, feedback="Revisar", include_general_comment=1)
			res_without = self.module.review_question_with_feedback(doc.name, feedback="Revisar", include_general_comment=0)
		self.assertIn("Anotação exclusiva do professor", res_with["ai_reply"])
		self.assertNotIn("Anotação exclusiva do professor", res_without["ai_reply"])

	def test_deep_dive_embed_only_on_correct_option_and_stripped_for_ai(self):
		from trivia_sync.integrations.lms_questions import (
			extract_lms_question_options,
			sync_lms_question_deep_dive_embeds,
		)

		class FakeDeepDiveDoc:
			def __init__(self):
				self.name = "QTS-2026-00213"
				self.option_1 = "Integralidade"
				self.option_2 = "Teto RGPS + 70% do excedente"
				self.is_correct_1 = 0
				self.is_correct_2 = 1
				self.explanation_1 = "Incorreta: sem integralidade."
				self.explanation_2 = "Correta conforme art. 2º da Lei 10.887/2004."
				for i in range(3, 11):
					setattr(self, f"option_{i}", "")
					setattr(self, f"is_correct_{i}", 0)
					setattr(self, f"explanation_{i}", "")
				self.trivia_answer_key_pending = 0
				self.trivia_general_explanation = "<p>6. Vamos testar seu entendimento? Calcule a pensão.</p>"

			def set(self, field, value):
				setattr(self, field, value)

		doc = FakeDeepDiveDoc()
		sync_lms_question_deep_dive_embeds(doc)
		# Idempotency check
		sync_lms_question_deep_dive_embeds(doc)

		self.assertNotIn("trivia-deep-dive", doc.explanation_1)
		self.assertIn("Aprofunde seu conhecimento", doc.explanation_2)
		self.assertIn("/aprofundar?q=QTS-2026-00213", doc.explanation_2)
		self.assertEqual(doc.explanation_2.count("trivia-deep-dive-body"), 1)

		# AI extraction strips the embedded teacher comment completely
		_, _, extracted_exps = extract_lms_question_options(doc)
		self.assertEqual(extracted_exps["B"], "Correta conforme art. 2º da Lei 10.887/2004.")

		# Pending answer key removes the embed
		doc.trivia_answer_key_pending = 1
		sync_lms_question_deep_dive_embeds(doc)
		self.assertNotIn("trivia-deep-dive", doc.explanation_2)

	def test_submit_student_reflection_requires_login_grades_with_athena_and_persists(self):
		class FakeQuestion:
			name = "QTS-2026-00213"
			trivia_qcode = "EX-PREV-Q55"
			question = "<p>Hortênsia é servidora pública.</p>"
			option_1 = "A"
			option_2 = "B"
			is_correct_1 = 0
			is_correct_2 = 1
			trivia_general_explanation = "<p>6. Vamos testar seu entendimento? R$ 12.000 com teto R$ 6.000.</p>"

		inserted_records = []

		class FakeReflection:
			def __init__(self):
				self.name = "REF-001"

			def insert(self, ignore_permissions=False):
				inserted_records.append(self)

		frappe = self.module.frappe
		frappe.PermissionError = PermissionError
		frappe.DoesNotExistError = KeyError
		frappe.throw = lambda msg, exc=None: (_ for _ in ()).throw((exc or ValueError)(msg))
		frappe.session = types.SimpleNamespace(user="Guest")
		frappe.db = types.SimpleNamespace(exists=lambda dt, name=None: True)
		frappe.get_doc = lambda dt, name: FakeQuestion()
		frappe.new_doc = lambda dt: FakeReflection()
		frappe.utils = types.SimpleNamespace(now_datetime=lambda: "2026-11-26 15:25:00", sanitize_html=lambda s: s)

		# 1. Guest is blocked
		with self.assertRaises(PermissionError):
			self.module.submit_student_reflection("QTS-2026-00213", "R$ 10.200,00")

		# 2. Logged-in student gets Athena grading & saved record
		frappe.session = types.SimpleNamespace(user="aluno@example.com")
		fake_adapter = types.SimpleNamespace(
			grade_student_reflection=lambda q, teacher_comment, student_answer: {
				"verdict": "Correta",
				"feedback": "Excelente! 6.000 + 70% de 6.000 (4.200) = R$ 10.200,00.",
				"key_takeaway": "Na regra histórica da Lei 10.887/2004, soma-se o teto do RGPS a 70% do excedente.",
				"model": "test-model",
			}
		)
		with patch.object(self.module, "get_ai_adapter", return_value=fake_adapter):
			res = self.module.submit_student_reflection(
				"QTS-2026-00213",
				"R$ 6.000 + 70% de R$ 6.000 = R$ 10.200,00",
			)

		self.assertEqual(res["verdict"], "Correta")
		self.assertIn("10.200", res["athena_feedback"])
		self.assertEqual(len(inserted_records), 1)
		self.assertEqual(inserted_records[0].user, "aluno@example.com")
		self.assertEqual(inserted_records[0].question, "QTS-2026-00213")

	def test_extract_json_repairs_trailing_commas_and_preserves_string_commas(self):
		raw = """```json
		{
			"difficulty_stars": 3,
			"topics": ["Direito, Constitucional", "Atos",],
			"option_explanations": {
				"A": "Texto com vírgula antes de fecha chave: }, ok",
				"B": "Linha 1
Linha 2",
			},
		}
		```"""
		parsed = self.module._extract_json(raw)
		self.assertEqual(parsed["difficulty_stars"], 3)
		self.assertEqual(parsed["topics"], ["Direito, Constitucional", "Atos"])
		self.assertEqual(parsed["option_explanations"]["A"], "Texto com vírgula antes de fecha chave: }, ok")
		self.assertEqual(parsed["option_explanations"]["B"], "Linha 1\nLinha 2")

	def test_athena_detects_deprecated_legislation_and_builds_banner(self):
		from trivia_sync.integrations.lms_questions import strip_question_embeds

		class FakeDeprecatedDoc:
			def __init__(self):
				self.name = "QTS-8666"
				self.trivia_qcode = "EX-8666-Q1"
				self.question = "<p>Segundo a Lei nº 8.666/1993, a modalidade convite...</p>"
				self.option_1 = "Exige 3 convidados"
				self.option_2 = "Exige 5 convidados"
				self.is_correct_1 = 1
				self.is_correct_2 = 0
				for i in range(3, 11):
					setattr(self, f"option_{i}", "")
					setattr(self, f"is_correct_{i}", 0)
				for i in range(1, 11):
					setattr(self, f"explanation_{i}", "")
				self.trivia_status = "In Preparation"
				self.trivia_answer_key_pending = 0
				self.trivia_deprecated = 0
				self.trivia_deprecated_law = ""
				self.trivia_replacement_law = ""
				self.trivia_deprecation_note = ""
				self.trivia_knowledge_pages = []

			def set(self, field, value):
				setattr(self, field, value)

			def save(self, **kwargs):
				pass

		doc = FakeDeprecatedDoc()
		frappe = self.module.frappe
		frappe.only_for = lambda roles: None
		frappe.get_single = lambda name: FakeSettings()
		frappe.get_doc = lambda dt, name: doc
		frappe.utils = types.SimpleNamespace(now_datetime=lambda: "now")

		fake_adapter = types.SimpleNamespace(
			enrich_full=lambda q: {
				"difficulty_stars": 2,
				"difficulty_label": "Fácil",
				"reason": "Cobra modalidade extinta da Lei 8.666/93.",
				"learning_objective": "Comparar modalidades da Lei 8.666/93 com a Lei 14.133/2021.",
				"topics": ["Licitações"],
				"general_explanation": "Como era: a Lei 8.666/93 previa o convite. Como é hoje: a Lei 14.133/2021 extinguiu o convite.",
				"suggested_materia": "Direito Administrativo",
				"suggested_assunto": "Licitações",
				"is_deprecated": True,
				"deprecated_law": "Lei nº 8.666/1993",
				"replacement_law": "Lei nº 14.133/2021",
				"deprecation_note": "A modalidade convite foi extinta pela Nova Lei de Licitações.",
				"option_explanations": {
					"A": "Correta à época da Lei 8.666/93; hoje o convite foi extinto pela Lei 14.133/2021.",
					"B": "Incorreta: mesmo na Lei 8.666/93, o mínimo não era 5.",
				},
				"enrichment_hash": "h-dep",
				"model": "test-model",
			},
			extract_knowledge_concepts=lambda q: {"concepts": [], "model": "test-model"},
		)
		with patch.object(self.module, "get_ai_adapter", return_value=fake_adapter), patch.object(
			self.module, "_safe_apply_ai_topics", return_value={}
		):
			self.module.enrich_question_full(doc.name)

		self.assertEqual(doc.trivia_deprecated, 1)
		self.assertEqual(doc.trivia_deprecated_law, "Lei nº 8.666/1993")
		self.assertEqual(doc.trivia_replacement_law, "Lei nº 14.133/2021")
		self.assertIn("trivia-deprecated-banner", doc.question)
		self.assertIn("Lei nº 14.133/2021", doc.question)
		self.assertEqual(
			strip_question_embeds(doc.question),
			"<p>Segundo a Lei nº 8.666/1993, a modalidade convite...</p>",
		)


if __name__ == "__main__":
	unittest.main()
