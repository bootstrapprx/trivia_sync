import importlib
import hashlib
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

    def test_material_generation_uses_strict_json_and_returns_model_provenance(self):
        payload = {"choices": [{"message": {"content": json.dumps({"title": "Princípios", "content": "<p>Conteúdo</p>", "summary": "Resumo"})}}]}
        with patch.object(self.module.requests, "post", return_value=FakeResponse(payload)) as post:
            result = self.module.OpenAICompatibleAdapter(FakeSettings()).generate_material("Sources", "180", "lesson")
        request = post.call_args.kwargs["json"]
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(result["title"], "Princípios")
        self.assertTrue(request["response_format"]["json_schema"]["strict"])

    def test_missing_key_fails_before_network_call(self):
        settings = FakeSettings()
        settings.ai_api_key = ""
        with self.assertRaises(self.module.AIEnrichmentError):
            self.module.OpenAICompatibleAdapter(settings)

    def test_worker_skips_fresh_enrichment_without_projecting_to_lms(self):
        class FakeQuestion:
            qcode = "Q-1"
            enunciado = "Explique o princípio."
            options = '{"A":"Certo","B":"Errado"}'
            correct_option = "A"
            materia = "Direito"
            assunto = "Princípios"
            banca = "Banca X"
            ano = 2024
            ai_enrichment_hash = hashlib.sha256(json.dumps({
                "qcode": qcode, "enunciado": enunciado, "options": options, "correct_option": correct_option,
                "materia": materia, "assunto": assunto, "banca": banca, "ano": ano,
            }, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()

        class FakeRun:
            def insert(self, **kwargs): pass
            def save(self, **kwargs): pass

        class FakeRow(dict):
            __getattr__ = dict.__getitem__

        frappe = self.module.frappe
        original = {name: getattr(frappe, name, None) for name in (
            "get_single", "new_doc", "get_all", "get_doc", "utils", "db", "log_error", "get_traceback"
        )}
        frappe.get_single = lambda name: FakeSettings()
        frappe.new_doc = lambda name: FakeRun()
        frappe.get_all = lambda *args, **kwargs: [FakeRow(name="Q-1", qcode="Q-1")] if kwargs["start"] == 0 else []
        frappe.get_doc = lambda *args: FakeQuestion()
        frappe.utils = types.SimpleNamespace(now_datetime=lambda: "now")
        frappe.db = types.SimpleNamespace(commit=lambda: None)
        errors = []
        frappe.log_error = lambda *args: errors.append(args)
        frappe.get_traceback = traceback.format_exc
        try:
            with patch.object(self.module, "OpenAICompatibleAdapter") as adapter:
                result = self.module.enrich_pending_questions()
            self.assertEqual(errors, [], repr(errors))
            self.assertEqual(result, {"processed": 1, "enriched": 0, "skipped": 1, "errors": 0})
            adapter.return_value.enrich.assert_not_called()
        finally:
            for name, value in original.items():
                if value is None:
                    delattr(frappe, name)
                else:
                    setattr(frappe, name, value)


if __name__ == "__main__":
    unittest.main()
