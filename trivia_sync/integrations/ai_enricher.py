import hashlib
import json
from typing import Any

import frappe
import requests

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-6-luna"


class AIEnrichmentError(RuntimeError):
    pass


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "difficulty_stars": {"type": "integer", "minimum": 1, "maximum": 5},
        "difficulty_label": {"type": "string", "enum": ["Muito fácil", "Fácil", "Média", "Difícil", "Muito difícil"]},
        "reason": {"type": "string", "minLength": 20, "maxLength": 800},
        "learning_objective": {"type": "string", "minLength": 5, "maxLength": 300},
        "topics": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
    "required": ["difficulty_stars", "difficulty_label", "reason", "learning_objective", "topics"],
}


class OpenAICompatibleAdapter:
    """Adapter for OpenAI-compatible chat endpoints; credentials stay in Frappe Password fields."""

    def __init__(self, settings_doc=None):
        self.settings = settings_doc or frappe.get_single("Trivia Sync Settings")
        self.base_url = (self.settings.ai_base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = self.settings.get_password("ai_api_key") if self.settings.ai_api_key else ""
        self.model = self.settings.ai_model or DEFAULT_MODEL
        self.timeout = max(15, int(self.settings.ai_timeout or 90))
        if not self.api_key:
            raise AIEnrichmentError("Configure a chave do adaptador IA antes de enriquecer questões.")

    def enrich(self, question: dict[str, Any]) -> dict[str, Any]:
        source = json.dumps(question, ensure_ascii=False, sort_keys=True, default=str)
        enrichment_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "application/json"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": (
                        "Você é um especialista em avaliação de concursos públicos brasileiros. "
                        "Classifique a dificuldade da questão, sem alterar enunciado, alternativas ou gabarito. "
                        "Considere complexidade conceitual, quantidade de inferências, pegadinhas, profundidade "
                        "e dependência de legislação específica. Responda exclusivamente no JSON Schema solicitado."
                    )},
                    {"role": "user", "content": json.dumps({
                        "qcode": question.get("qcode"), "enunciado": question.get("enunciado"),
                        "alternativas": question.get("options"), "gabarito": question.get("correct_option"),
                        "materia": question.get("materia"), "assunto": question.get("assunto"),
                        "banca": question.get("banca"), "ano": question.get("ano"),
                    }, ensure_ascii=False)},
                ],
                "response_format": {"type": "json_schema", "json_schema": {"name": "question_enrichment", "strict": True, "schema": SCHEMA}},
                "reasoning": {"effort": "low"},
                "max_completion_tokens": 1200,
            },
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIEnrichmentError(f"Falha no adaptador IA: {exc}") from exc
        stars = int(result.get("difficulty_stars", 0))
        if stars not in range(1, 6):
            raise AIEnrichmentError("O adaptador IA retornou uma dificuldade fora do intervalo de 1 a 5 estrelas.")
        result["enrichment_hash"] = enrichment_hash
        result["model"] = self.model
        return result


def _question_payload(doc):
    return {"qcode": doc.qcode, "enunciado": doc.enunciado, "options": doc.options, "correct_option": doc.correct_option,
            "materia": doc.materia, "assunto": doc.assunto, "banca": doc.banca, "ano": doc.ano}


def enrich_question_doc(doc, settings_doc=None):
    settings_doc = settings_doc or frappe.get_single("Trivia Sync Settings")
    adapter = OpenAICompatibleAdapter(settings_doc)
    payload = _question_payload(doc)
    result = adapter.enrich(payload)
    doc.ai_difficulty_stars = result["difficulty_stars"]
    doc.ai_difficulty_label = result["difficulty_label"]
    doc.ai_difficulty_reason = result["reason"]
    doc.ai_learning_objective = result["learning_objective"]
    doc.ai_topics = json.dumps(result["topics"], ensure_ascii=False)
    doc.ai_model = result["model"]
    doc.ai_enrichment_hash = result["enrichment_hash"]
    doc.ai_enriched_at = frappe.utils.now_datetime()
    doc.save(ignore_permissions=True)
    return result


def enrich_pending_questions():
    settings = frappe.get_single("Trivia Sync Settings")
    if not settings.ai_enabled:
        raise frappe.ValidationError("Ative o enriquecimento IA nas configurações antes de executar.")
    adapter = OpenAICompatibleAdapter(settings)
    run = frappe.new_doc("Trivia Sync Run")
    run.source = "IA"
    run.operation = "AI enrichment"
    run.status = "Running"
    run.started_at = frappe.utils.now_datetime()
    run.insert(ignore_permissions=True)
    limit = max(1, min(int(settings.ai_batch_size or 10), 100))
    rows = frappe.get_all("Trivia Question", fields=["name", "qcode", "enunciado", "options", "correct_option", "materia", "assunto", "banca", "ano", "ai_enrichment_hash"], limit_page_length=limit)
    result = {"processed": 0, "enriched": 0, "skipped": 0, "errors": 0}
    try:
        for row in rows:
            try:
                doc = frappe.get_doc("Trivia Question", row.name)
                source = json.dumps(_question_payload(doc), ensure_ascii=False, sort_keys=True, default=str)
                digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
                if doc.ai_enrichment_hash == digest:
                    result["skipped"] += 1
                    continue
                data = adapter.enrich(_question_payload(doc))
                for field, value in {"ai_difficulty_stars":data["difficulty_stars"], "ai_difficulty_label":data["difficulty_label"], "ai_difficulty_reason":data["reason"], "ai_learning_objective":data["learning_objective"], "ai_topics":json.dumps(data["topics"], ensure_ascii=False), "ai_model":data["model"], "ai_enrichment_hash":data["enrichment_hash"], "ai_enriched_at":frappe.utils.now_datetime()}.items(): setattr(doc, field, value)
                doc.save(ignore_permissions=True); result["enriched"] += 1
            except Exception:
                result["errors"] += 1
                frappe.log_error(frappe.get_traceback(), f"Trivia Sync · AI enrichment · {row.get('qcode')}")
            result["processed"] += 1
            frappe.db.commit()
        run.status = "Partial" if result["errors"] else "Completed"
        run.records_created = result["enriched"]
        run.records_skipped = result["skipped"]
        run.records_errors = result["errors"]
        return result
    except Exception:
        run.status = "Failed"
        run.error_log = frappe.get_traceback()
        frappe.log_error(frappe.get_traceback(), "Trivia Sync · AI enrichment")
        raise
    finally:
        run.finished_at = frappe.utils.now_datetime()
        run.save(ignore_permissions=True)
        frappe.db.commit()
