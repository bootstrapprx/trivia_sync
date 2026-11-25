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


if __name__ == "__main__":
	unittest.main()
