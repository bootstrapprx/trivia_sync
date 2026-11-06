import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch


class FakeSettings:
    ai_base_url = "https://llm.example.test/v1"
    ai_api_key = "configured"
    ai_model = "test-model"
    ai_timeout = 20

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
        frappe_stub = types.SimpleNamespace(get_single=lambda name: FakeSettings(), ValidationError=ValueError)
        sys.modules.setdefault("frappe", frappe_stub)
        cls.module = importlib.import_module("trivia_sync.integrations.ai_enricher")

    def question(self):
        return {"qcode": "Q-1", "enunciado": "Explique o princípio.", "options": '{"A":"Certo","B":"Errado"}', "correct_option": "A", "materia": "Direito", "assunto": "Princípios", "banca": "Banca X", "ano": 2024}

    def test_enrich_uses_strict_schema_and_returns_five_star_metadata(self):
        payload = {"choices": [{"message": {"content": json.dumps({"difficulty_stars": 5, "difficulty_label": "Muito difícil", "reason": "Exige múltiplas inferências e domínio específico.", "learning_objective": "Aplicar o princípio ao caso concreto.", "topics": ["Princípios"]})}}]}
        with patch.object(self.module.requests, "post", return_value=FakeResponse(payload)) as post:
            result = self.module.OpenAICompatibleAdapter(FakeSettings()).enrich(self.question())
        request = post.call_args.kwargs["json"]
        self.assertEqual(result["difficulty_stars"], 5)
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(len(result["enrichment_hash"]), 64)
        self.assertEqual(request["response_format"]["type"], "json_schema")
        self.assertTrue(request["response_format"]["json_schema"]["strict"])

    def test_enrich_rejects_invalid_star_range(self):
        payload = {"choices": [{"message": {"content": json.dumps({"difficulty_stars": 6, "difficulty_label": "Muito difícil", "reason": "Texto suficientemente longo para passar.", "learning_objective": "Objetivo válido.", "topics": []})}}]}
        with patch.object(self.module.requests, "post", return_value=FakeResponse(payload)):
            with self.assertRaises(self.module.AIEnrichmentError):
                self.module.OpenAICompatibleAdapter(FakeSettings()).enrich(self.question())

    def test_missing_key_fails_before_network_call(self):
        settings = FakeSettings()
        settings.ai_api_key = ""
        with self.assertRaises(self.module.AIEnrichmentError):
            self.module.OpenAICompatibleAdapter(settings)


if __name__ == "__main__":
    unittest.main()
