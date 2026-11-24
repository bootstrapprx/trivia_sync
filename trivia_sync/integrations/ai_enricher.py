import hashlib
import json
import re
from typing import Any

import frappe
import requests

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-6-luna"
DIFFICULTY_LABELS = {
	1: "Muito fácil",
	2: "Fácil",
	3: "Média",
	4: "Difícil",
	5: "Muito difícil",
}


def stars_to_rating(stars: int) -> float:
	"""Convert 1..5 stars to Frappe's Rating field scale (0.2..1.0)."""
	clamped = max(1, min(5, int(stars)))
	return round(clamped / 5.0, 2)


def rating_to_stars(value: Any) -> int:
	"""Convert a Frappe Rating float (0.2..1.0) or legacy 1..5 integer into 1..5 stars."""
	num = float(value or 0)
	if num <= 0:
		return 0
	if num <= 1.0:
		return max(1, min(5, int(round(num * 5))))
	return max(1, min(5, int(round(num))))


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


def _extract_json(raw_content: Any) -> dict[str, Any]:
	if isinstance(raw_content, dict):
		return raw_content
	text = str(raw_content or "").strip()
	if text.startswith("```"):
		text = re.sub(r"^```(?:json)?\s*", "", text)
		text = re.sub(r"\s*```$", "", text).strip()
	try:
		return json.loads(text)
	except ValueError:
		match = re.search(r"\{[\s\S]*\}", text)
		if match:
			return json.loads(match.group(0))
		raise


def _build_enrich_messages(question: dict[str, Any]) -> list[dict[str, str]]:
	return [
		{
			"role": "system",
			"content": (
				"Você é um especialista em avaliação de concursos públicos brasileiros. "
				"Classifique a dificuldade da questão, sem alterar enunciado, alternativas ou gabarito. "
				"Considere complexidade conceitual, quantidade de inferências, pegadinhas, profundidade "
				"e dependência de legislação específica. Responda exclusivamente no JSON Schema solicitado."
			),
		},
		{
			"role": "user",
			"content": json.dumps(
				{
					"qcode": question.get("qcode"),
					"enunciado": question.get("enunciado"),
					"alternativas": question.get("options"),
					"gabarito": question.get("correct_option"),
					"materia": question.get("materia"),
					"assunto": question.get("assunto"),
					"banca": question.get("banca"),
					"ano": question.get("ano"),
				},
				ensure_ascii=False,
			),
		},
	]


def _build_material_messages(prompt: str, level: str, material_kind: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
	schema = {
		"type": "object",
		"additionalProperties": False,
		"properties": {"title": {"type": "string"}, "content": {"type": "string"}, "summary": {"type": "string"}},
		"required": ["title", "content", "summary"],
	}
	messages = [
		{
			"role": "system",
			"content": (
				"Produza material didático em português brasileiro. Preserve fatos e fontes, "
				"não crie gabaritos ou dados legais. Retorne apenas o JSON solicitado."
			),
		},
		{"role": "user", "content": f"Tipo: {material_kind}. Nível: {level}.\n\n{prompt}"},
	]
	return messages, schema


def _build_option_explanations_messages(question: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any], list[str]]:
	options = question.get("options") or {}
	if isinstance(options, str):
		options = json.loads(options or "{}")
	ordered_letters = sorted(str(letter).upper() for letter, value in options.items() if value not in (None, ""))
	if not ordered_letters:
		raise AIEnrichmentError("Question has no alternatives to explain.")
	schema = {
		"type": "object",
		"additionalProperties": False,
		"properties": {
			letter: {"type": "string", "minLength": 10, "maxLength": 1200}
			for letter in ordered_letters
		},
		"required": ordered_letters,
	}
	messages = [
		{
			"role": "system",
			"content": (
				"Você é um professor especialista em concursos públicos brasileiros. "
				"Para cada alternativa, escreva uma explicação didática em português brasileiro. "
				"REGRA CRÍTICA PARA ALTERNATIVAS INCORRETAS: explique especificamente por que aquela "
				"alternativa está errada SEM revelar, citar ou dar dica de qual é a alternativa correta "
				"(o estudante verá essa mensagem ao marcar a alternativa errada). "
				"Para a(s) alternativa(s) correta(s), explique claramente por que ela responde ao enunciado. "
				"Retorne exclusivamente o JSON solicitado com uma chave para cada letra."
			),
		},
		{
			"role": "user",
			"content": json.dumps(
				{
					"enunciado": question.get("enunciado"),
					"alternativas": options,
					"gabarito_correto": question.get("correct_options") or [question.get("correct_option")],
					"comentario_geral": question.get("explanation") or "",
					"materia": question.get("materia"),
					"assunto": question.get("assunto"),
					"banca": question.get("banca"),
				},
				ensure_ascii=False,
			),
		},
	]
	return messages, schema, ordered_letters


def _build_full_enrich_messages(question: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any], list[str]]:
	options = question.get("options") or {}
	if isinstance(options, str):
		options = json.loads(options or "{}")
	ordered_letters = sorted(str(letter).upper() for letter, value in options.items() if value not in (None, ""))
	if not ordered_letters:
		raise AIEnrichmentError("Question has no alternatives to enrich.")
	schema = {
		"type": "object",
		"additionalProperties": False,
		"properties": {
			"difficulty_stars": {"type": "integer", "minimum": 1, "maximum": 5},
			"difficulty_label": {"type": "string", "enum": ["Muito fácil", "Fácil", "Média", "Difícil", "Muito difícil"]},
			"reason": {"type": "string", "minLength": 20, "maxLength": 800},
			"learning_objective": {"type": "string", "minLength": 5, "maxLength": 300},
			"topics": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
			"general_explanation": {"type": "string", "minLength": 15, "maxLength": 1200},
			"suggested_materia": {"type": "string", "maxLength": 140},
			"suggested_assunto": {"type": "string", "maxLength": 140},
			"syllabus_topic_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
			"option_explanations": {
				"type": "object",
				"additionalProperties": False,
				"properties": {
					letter: {"type": "string", "minLength": 10, "maxLength": 1200}
					for letter in ordered_letters
				},
				"required": ordered_letters,
			},
		},
		"required": [
			"difficulty_stars",
			"difficulty_label",
			"reason",
			"learning_objective",
			"topics",
			"general_explanation",
			"suggested_materia",
			"suggested_assunto",
			"syllabus_topic_ids",
			"option_explanations",
		],
	}
	syllabus_candidates = question.get("syllabus_candidates") or []
	messages = [
		{
			"role": "system",
			"content": (
				"Você é um professor especialista em avaliação de concursos públicos brasileiros. "
				"Analise completamente a questão em português brasileiro, sem alterar enunciado, alternativas ou gabarito. "
				"1) Classifique a dificuldade (1 a 5 estrelas), justificativa técnica, objetivo de aprendizagem, tópicos, matéria e assunto. "
				"2) Se houver itens em ementa_candidatos, selecione em syllabus_topic_ids apenas os IDs (campo 'name') que correspondem diretamente à questão (ou lista vazia se nenhum se aplicar). "
				"3) Escreva um comentário geral didático (general_explanation). "
				"4) Em option_explanations, explique cada alternativa individualmente. "
				"REGRA CRÍTICA PARA ALTERNATIVAS INCORRETAS: explique especificamente por que aquela alternativa está errada "
				"SEM revelar, citar ou dar dica de qual é a alternativa correta (o aluno verá essa mensagem ao errar). "
				"Para a(s) alternativa(s) correta(s), explique claramente por que ela responde ao enunciado. "
				"Responda exclusivamente no JSON Schema solicitado."
			),
		},
		{
			"role": "user",
			"content": json.dumps(
				{
					"qcode": question.get("qcode"),
					"enunciado": question.get("enunciado"),
					"alternativas": options,
					"gabarito_correto": question.get("correct_options") or [question.get("correct_option")],
					"comentario_geral": question.get("explanation") or "",
					"materia": question.get("materia"),
					"assunto": question.get("assunto"),
					"banca": question.get("banca"),
					"ano": question.get("ano"),
					"ementa_candidatos": syllabus_candidates,
				},
				ensure_ascii=False,
			),
		},
	]
	return messages, schema, ordered_letters


def _build_knowledge_concepts_messages(question: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
	sub_schema = {
		"type": "object",
		"additionalProperties": False,
		"properties": {
			"title": {"type": "string", "minLength": 2, "maxLength": 140},
			"summary": {"type": "string", "minLength": 10, "maxLength": 400},
			"explanation": {"type": "string", "minLength": 20, "maxLength": 2000},
			"examples": {"type": "string", "maxLength": 1000},
			"exam_traps": {"type": "string", "maxLength": 800},
		},
		"required": ["title", "summary", "explanation", "examples", "exam_traps"],
	}
	concept_schema = {
		"type": "object",
		"additionalProperties": False,
		"properties": {
			"title": {"type": "string", "minLength": 2, "maxLength": 140},
			"summary": {"type": "string", "minLength": 10, "maxLength": 400},
			"explanation": {"type": "string", "minLength": 30, "maxLength": 3000},
			"examples": {"type": "string", "maxLength": 1200},
			"exam_traps": {"type": "string", "maxLength": 1000},
			"sub_concepts": {"type": "array", "items": sub_schema, "maxItems": 4},
		},
		"required": ["title", "summary", "explanation", "examples", "exam_traps", "sub_concepts"],
	}
	schema = {
		"type": "object",
		"additionalProperties": False,
		"properties": {
			"concepts": {"type": "array", "items": concept_schema, "minItems": 1, "maxItems": 3},
		},
		"required": ["concepts"],
	}
	messages = [
		{
			"role": "system",
			"content": (
				"Você é um professor especialista em concursos públicos brasileiros criando páginas de conhecimento (wiki didática). "
				"Identifique os conceitos pré-requisitos indispensáveis para resolver a questão (ex.: 'Derivação parassintética') "
				"e seus sub-conceitos diretos (ex.: 'Prefixo', 'Sufixo', 'Derivação prefixal e sufixal'). "
				"Para cada conceito e sub-conceito, escreva em português brasileiro: resumo claro, explicação conceitual didática, "
				"exemplos práticos (SEM copiar nem entregar o gabarito da questão) e pegadinhas frequentes de banca. "
				"Responda exclusivamente no JSON Schema solicitado."
			),
		},
		{
			"role": "user",
			"content": json.dumps(
				{
					"enunciado": question.get("enunciado"),
					"alternativas": question.get("options"),
					"materia": question.get("materia"),
					"assunto": question.get("assunto"),
					"topicos": question.get("topics") or [],
					"banca": question.get("banca"),
				},
				ensure_ascii=False,
			),
		},
	]
	return messages, schema


class _BaseAIAdapter:
	model: str = ""

	def _chat_json(self, messages: list[dict[str, str]], schema_name: str, schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
		raise NotImplementedError

	def enrich(self, question: dict[str, Any]) -> dict[str, Any]:
		source = json.dumps(question, ensure_ascii=False, sort_keys=True, default=str)
		enrichment_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
		result = self._chat_json(_build_enrich_messages(question), "question_enrichment", SCHEMA, 1200)
		stars = int(result.get("difficulty_stars", 0))
		if stars not in range(1, 6):
			raise AIEnrichmentError("The AI adapter returned a difficulty outside the 1 to 5 star range.")
		result["difficulty_stars"] = stars
		result["difficulty_label"] = DIFFICULTY_LABELS[stars]
		result["enrichment_hash"] = enrichment_hash
		result["model"] = self.model
		return result

	def generate_material(self, prompt: str, level: str, material_kind: str = "lesson") -> dict[str, str]:
		messages, schema = _build_material_messages(prompt, level, material_kind)
		result = self._chat_json(messages, "trivia_learning_material", schema, 6000)
		if not result.get("title") or not result.get("content"):
			raise AIEnrichmentError("The provider returned empty material.")
		return {**result, "model": self.model}

	def draft_option_explanations(self, question: dict[str, Any]) -> dict[str, Any]:
		messages, schema, ordered_letters = _build_option_explanations_messages(question)
		result = self._chat_json(messages, "option_explanations_draft", schema, 2500)
		explanations = {letter: str(result.get(letter) or "").strip() for letter in ordered_letters}
		if any(not text for text in explanations.values()):
			raise AIEnrichmentError("The AI provider returned empty explanations for one or more alternatives.")
		return {"explanations": explanations, "model": self.model}

	def enrich_full(self, question: dict[str, Any]) -> dict[str, Any]:
		source = json.dumps(
			{
				"qcode": question.get("qcode"),
				"enunciado": question.get("enunciado"),
				"options": question.get("options"),
				"correct_option": question.get("correct_option"),
				"materia": question.get("materia"),
				"assunto": question.get("assunto"),
				"banca": question.get("banca"),
				"ano": question.get("ano"),
			},
			ensure_ascii=False,
			sort_keys=True,
			default=str,
		)
		enrichment_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
		messages, schema, ordered_letters = _build_full_enrich_messages(question)
		result = self._chat_json(messages, "question_full_enrichment", schema, 3500)
		stars = int(result.get("difficulty_stars", 0))
		if stars not in range(1, 6):
			raise AIEnrichmentError("The AI adapter returned a difficulty outside the 1 to 5 star range.")
		result["difficulty_stars"] = stars
		result["difficulty_label"] = DIFFICULTY_LABELS[stars]
		raw_explanations = result.get("option_explanations") or {}
		if not isinstance(raw_explanations, dict):
			raise AIEnrichmentError("The AI provider returned invalid option_explanations.")
		explanations = {letter: str(raw_explanations.get(letter) or "").strip() for letter in ordered_letters}
		if any(not text for text in explanations.values()):
			raise AIEnrichmentError("The AI provider returned empty explanations for one or more alternatives.")
		result["option_explanations"] = explanations
		result["enrichment_hash"] = enrichment_hash
		result["model"] = self.model
		return result

	def extract_knowledge_concepts(self, question: dict[str, Any]) -> dict[str, Any]:
		messages, schema = _build_knowledge_concepts_messages(question)
		result = self._chat_json(messages, "question_knowledge_concepts", schema, 3500)
		concepts = result.get("concepts") or []
		if not isinstance(concepts, list) or not concepts:
			raise AIEnrichmentError("The AI provider returned no knowledge concepts.")
		return {"concepts": concepts, "model": self.model}


class OpenAICompatibleAdapter(_BaseAIAdapter):
	"""Adapter for OpenAI-compatible chat endpoints; credentials stay in Frappe Password fields."""

	def __init__(self, settings_doc=None):
		self.settings = settings_doc or frappe.get_single("Trivia Sync Settings")
		self.base_url = (self.settings.ai_base_url or DEFAULT_BASE_URL).rstrip("/")
		self.api_key = self.settings.get_password("ai_api_key") if self.settings.ai_api_key else ""
		self.model = self.settings.ai_model or DEFAULT_MODEL
		self.timeout = max(15, int(self.settings.ai_timeout or 90))
		if not self.api_key:
			raise AIEnrichmentError("Configure an AI provider key before enriching questions.")

	def _chat_json(self, messages: list[dict[str, str]], schema_name: str, schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
		body: dict[str, Any] = {
			"model": self.model,
			"messages": messages,
			"response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
			"max_completion_tokens": max_tokens,
		}
		if schema_name == "question_enrichment":
			body["reasoning"] = {"effort": "low"}
		response = requests.post(
			f"{self.base_url}/chat/completions",
			headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "application/json"},
			json=body,
			timeout=self.timeout,
		)
		try:
			response.raise_for_status()
			payload = response.json()
			content = payload["choices"][0]["message"]["content"]
			return _extract_json(content)
		except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
			raise AIEnrichmentError(f"AI adapter failed: {exc}") from exc


def resolve_flow_model_name(settings_doc=None) -> str:
	settings = settings_doc or frappe.get_single("Trivia Sync Settings")
	configured = (getattr(settings, "ai_flow_model", None) or "").strip()
	if configured:
		return configured
	try:
		flow_settings = frappe.get_single("Flow Settings")
		small_model = (getattr(flow_settings, "small_model", None) or "").strip()
		if small_model and frappe.db.get_value("Flow Model", small_model, "enabled"):
			return small_model
	except Exception:
		pass
	models = frappe.get_all(
		"Flow Model",
		filters={"enabled": 1, "embedding": 0},
		pluck="name",
		order_by="modified desc",
		limit_page_length=1,
	)
	if models:
		return models[0]
	raise AIEnrichmentError(
		"No enabled chat Flow Model found. Configure a Flow Provider and Flow Model in Frappe Flow, or select one in Trivia Sync Settings."
	)


class FlowAdapter(_BaseAIAdapter):
	"""Adapter that reuses Frappe Flow's configured Flow Provider & Flow Model via LiteLLM."""

	def __init__(self, settings_doc=None):
		self.settings = settings_doc or frappe.get_single("Trivia Sync Settings")
		self.timeout = max(15, int(self.settings.ai_timeout or 90))
		self.flow_model_name = resolve_flow_model_name(self.settings)
		try:
			from frappe.flow.lib.model import litellm_route, model_config
		except ImportError as exc:
			raise AIEnrichmentError("Frappe Flow is not available on this site.") from exc
		cfg = model_config(self.flow_model_name, check_permission=False)
		self.model, self.api_base = litellm_route(cfg["model"], cfg.get("api_base"))
		self.api_key = cfg.get("api_key")
		self.model_params = dict(cfg.get("model_params") or {})

	def _completion(self, messages: list[dict[str, str]], max_tokens: int, response_format: dict[str, Any] | None = None):
		try:
			import litellm
		except ImportError as exc:
			raise AIEnrichmentError("LiteLLM is required for Frappe Flow execution.") from exc
		kwargs: dict[str, Any] = {
			**self.model_params,
			"model": self.model,
			"messages": messages,
			"max_tokens": max_tokens,
			"timeout": self.timeout,
		}
		if self.api_key:
			kwargs["api_key"] = self.api_key
		if self.api_base:
			kwargs["api_base"] = self.api_base
		if response_format:
			kwargs["response_format"] = response_format
		return litellm.completion(**kwargs)

	def _chat_json(self, messages: list[dict[str, str]], schema_name: str, schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
		schema_format = {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}
		try:
			response = self._completion(messages, max_tokens=max_tokens, response_format=schema_format)
		except Exception:
			# Some providers/models in LiteLLM (e.g. Anthropic, Ollama) reject strict json_schema;
			# retry with explicit JSON schema instructions in the prompt.
			fallback_messages = [
				*messages,
				{
					"role": "user",
					"content": f"Responda APENAS com um objeto JSON válido seguindo exatamente este schema:\n{json.dumps(schema, ensure_ascii=False)}",
				},
			]
			try:
				response = self._completion(fallback_messages, max_tokens=max_tokens, response_format=None)
			except Exception as exc:
				raise AIEnrichmentError(f"Frappe Flow AI call failed: {exc}") from exc
		try:
			choice = response["choices"][0] if isinstance(response, dict) else response.choices[0]
			message = choice["message"] if isinstance(choice, dict) else choice.message
			content = message["content"] if isinstance(message, dict) else message.content
			return _extract_json(content)
		except (KeyError, IndexError, AttributeError, TypeError, ValueError) as exc:
			raise AIEnrichmentError(f"Frappe Flow returned invalid JSON: {exc}") from exc


def get_ai_adapter(settings_doc=None) -> _BaseAIAdapter:
	settings = settings_doc or frappe.get_single("Trivia Sync Settings")
	backend = (getattr(settings, "ai_backend", None) or "").strip()
	if backend == "Custom OpenAI-compatible":
		return OpenAICompatibleAdapter(settings)
	if backend == "Frappe Flow":
		return FlowAdapter(settings)
	# Legacy settings without ai_backend set: prefer custom key if explicitly configured, else Flow.
	if getattr(settings, "ai_api_key", None):
		return OpenAICompatibleAdapter(settings)
	return FlowAdapter(settings)


def test_ai_connection(settings_doc=None) -> dict[str, Any]:
	settings = settings_doc or frappe.get_single("Trivia Sync Settings")
	try:
		adapter = get_ai_adapter(settings)
		backend = "Frappe Flow" if isinstance(adapter, FlowAdapter) else "Custom OpenAI-compatible"
		result = adapter._chat_json(
			[{"role": "user", "content": 'Respond with JSON: {"ok": true}'}],
			"ai_healthcheck",
			{"type": "object", "additionalProperties": False, "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
			64,
		)
		return {
			"ok": bool(result.get("ok", True)),
			"backend": backend,
			"model": adapter.model,
			"flow_model": getattr(adapter, "flow_model_name", None),
		}
	except Exception as exc:
		return {"ok": False, "error": str(exc)}


def draft_question_option_explanations(question_name: str):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable AI enrichment in settings before generating explanation drafts.")
	doc = frappe.get_doc("Trivia Question", question_name)
	options = json.loads(doc.options or "{}") if isinstance(doc.options, str) else (doc.options or {})
	correct_raw = getattr(doc, "correct_options", None)
	correct_options = json.loads(correct_raw or "[]") if isinstance(correct_raw, str) else (correct_raw or [])
	if not correct_options and getattr(doc, "correct_option", None):
		correct_options = [doc.correct_option]
	adapter = get_ai_adapter(settings)
	draft = adapter.draft_option_explanations(
		{
			"enunciado": doc.enunciado,
			"options": options,
			"correct_option": getattr(doc, "correct_option", None),
			"correct_options": correct_options,
			"explanation": getattr(doc, "explanation", None),
			"materia": getattr(doc, "materia", None),
			"assunto": getattr(doc, "assunto", None),
			"banca": getattr(doc, "banca", None),
		}
	)
	doc.option_explanations = json.dumps(draft["explanations"], ensure_ascii=False, indent=2)
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "option_explanations": draft["explanations"], "model": draft["model"]}


def _apply_difficulty_fields(doc, data):
	doc.ai_difficulty_stars = stars_to_rating(data["difficulty_stars"])
	doc.ai_difficulty_label = data["difficulty_label"]
	doc.ai_difficulty_reason = data["reason"]
	doc.ai_learning_objective = data["learning_objective"]
	doc.ai_topics = json.dumps(data.get("topics") or [], ensure_ascii=False)
	doc.ai_model = data["model"]
	doc.ai_enrichment_hash = data["enrichment_hash"]
	doc.ai_enrichment_status = "Fresh"
	doc.ai_enriched_at = frappe.utils.now_datetime()


def _safe_apply_ai_topics(doc, topics=None, suggested_materia=None, suggested_assunto=None, syllabus_topic_names=None):
	try:
		from trivia_sync.integrations.reconciliation import apply_ai_topics_to_question

		return apply_ai_topics_to_question(
			doc,
			topics=topics,
			suggested_materia=suggested_materia,
			suggested_assunto=suggested_assunto,
			syllabus_topic_names=syllabus_topic_names,
		)
	except Exception:
		return {"trivia_materia": None, "trivia_assunto": None, "syllabus_topics_added": [], "tags_added": []}


def apply_ai_topics(question_name: str):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	doc = frappe.get_doc("Trivia Question", question_name)
	from trivia_sync.integrations.reconciliation import apply_ai_topics_to_question

	applied = apply_ai_topics_to_question(doc)
	doc.save(ignore_permissions=True)
	return {"name": doc.name, **applied}


def enrich_single_question_difficulty(question_name: str):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable AI enrichment in settings before classifying difficulty.")
	doc = frappe.get_doc("Trivia Question", question_name)
	result = enrich_question_doc(doc, settings)
	return {
		"name": doc.name,
		"difficulty_stars": result["difficulty_stars"],
		"difficulty_label": result["difficulty_label"],
		"learning_objective": result["learning_objective"],
		"topics": result["topics"],
		"model": result["model"],
	}


def enrich_question_full(question_name: str):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable AI enrichment in settings before enriching questions.")
	doc = frappe.get_doc("Trivia Question", question_name)
	options = json.loads(doc.options or "{}") if isinstance(doc.options, str) else (doc.options or {})
	correct_raw = getattr(doc, "correct_options", None)
	correct_options = json.loads(correct_raw or "[]") if isinstance(correct_raw, str) else (correct_raw or [])
	if not correct_options and getattr(doc, "correct_option", None):
		correct_options = [doc.correct_option]
	try:
		from trivia_sync.integrations.reconciliation import candidate_syllabus_topics

		syllabus_candidates = [
			{"name": row.get("name"), "titulo": row.get("titulo")}
			for row in candidate_syllabus_topics(concurso_cargo=getattr(doc, "concurso_cargo", None), limit=60)
		]
	except Exception:
		syllabus_candidates = []
	adapter = get_ai_adapter(settings)
	data = adapter.enrich_full(
		{
			"qcode": doc.qcode,
			"enunciado": doc.enunciado,
			"options": options,
			"correct_option": getattr(doc, "correct_option", None),
			"correct_options": correct_options,
			"explanation": getattr(doc, "explanation", None),
			"materia": getattr(doc, "materia", None),
			"assunto": getattr(doc, "assunto", None),
			"banca": getattr(doc, "banca", None),
			"ano": getattr(doc, "ano", None),
			"syllabus_candidates": syllabus_candidates,
		}
	)
	_apply_difficulty_fields(doc, data)
	doc.option_explanations = json.dumps(data["option_explanations"], ensure_ascii=False, indent=2)
	if not (getattr(doc, "explanation", None) or "").strip() and data.get("general_explanation"):
		doc.explanation = data["general_explanation"]
	applied = _safe_apply_ai_topics(
		doc,
		topics=data.get("topics") or [],
		suggested_materia=data.get("suggested_materia"),
		suggested_assunto=data.get("suggested_assunto"),
		syllabus_topic_names=data.get("syllabus_topic_ids") or [],
	)
	knowledge_summary = {"knowledge_pages_linked": [], "knowledge_pages_created": [], "knowledge_pages_reused": []}
	try:
		from trivia_sync.integrations.knowledge import link_knowledge_concepts

		extracted = adapter.extract_knowledge_concepts(
			{
				"enunciado": doc.enunciado,
				"options": options,
				"materia": getattr(doc, "materia", None),
				"assunto": getattr(doc, "assunto", None),
				"topics": data.get("topics") or [],
				"banca": getattr(doc, "banca", None),
			}
		)
		knowledge_summary = link_knowledge_concepts(doc, extracted["concepts"], ai_model=extracted["model"])
	except Exception:
		pass
	doc.save(ignore_permissions=True)
	return {
		"name": doc.name,
		"difficulty_stars": data["difficulty_stars"],
		"difficulty_label": data["difficulty_label"],
		"learning_objective": data["learning_objective"],
		"topics": data["topics"],
		"option_explanations": data["option_explanations"],
		"model": data["model"],
		**applied,
		**knowledge_summary,
	}


def extract_question_knowledge(question_name: str):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable AI enrichment in settings before extracting knowledge concepts.")
	doc = frappe.get_doc("Trivia Question", question_name)
	options = json.loads(doc.options or "{}") if isinstance(doc.options, str) else (doc.options or {})
	try:
		topics = json.loads(getattr(doc, "ai_topics", None) or "[]")
	except (TypeError, ValueError):
		topics = []
	adapter = get_ai_adapter(settings)
	extracted = adapter.extract_knowledge_concepts(
		{
			"enunciado": doc.enunciado,
			"options": options,
			"materia": getattr(doc, "materia", None),
			"assunto": getattr(doc, "assunto", None),
			"topics": topics,
			"banca": getattr(doc, "banca", None),
		}
	)
	from trivia_sync.integrations.knowledge import link_knowledge_concepts

	summary = link_knowledge_concepts(doc, extracted["concepts"], ai_model=extracted["model"])
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "model": extracted["model"], **summary}


def _question_payload(doc):
	return {
		"qcode": doc.qcode,
		"enunciado": doc.enunciado,
		"options": doc.options,
		"correct_option": doc.correct_option,
		"materia": doc.materia,
		"assunto": doc.assunto,
		"banca": doc.banca,
		"ano": doc.ano,
	}


def enrich_question_doc(doc, settings_doc=None):
	settings_doc = settings_doc or frappe.get_single("Trivia Sync Settings")
	adapter = get_ai_adapter(settings_doc)
	payload = _question_payload(doc)
	result = adapter.enrich(payload)
	_apply_difficulty_fields(doc, result)
	_safe_apply_ai_topics(doc, topics=result.get("topics") or [])
	doc.save(ignore_permissions=True)
	return result


def enrich_pending_questions():
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		raise frappe.ValidationError("Enable AI enrichment in settings before running it.")
	adapter = get_ai_adapter(settings)
	run = frappe.new_doc("Trivia Sync Run")
	run.source = "IA"
	run.operation = "AI enrichment"
	run.status = "Running"
	run.started_at = frappe.utils.now_datetime()
	run.insert(ignore_permissions=True)
	limit = max(1, min(int(settings.ai_batch_size or 10), 100))
	result = {"processed": 0, "enriched": 0, "skipped": 0, "errors": 0}
	try:
		start = 0
		while result["processed"] < limit:
			rows = frappe.get_all(
				"Trivia Question",
				fields=["name", "qcode"],
				limit_page_length=min(limit - result["processed"], 100),
				start=start,
			)
			if not rows:
				break
			start += len(rows)
			for row in rows:
				try:
					doc = frappe.get_doc("Trivia Question", row.name)
					source = json.dumps(_question_payload(doc), ensure_ascii=False, sort_keys=True, default=str)
					digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
					if doc.ai_enrichment_hash == digest:
						result["skipped"] += 1
					else:
						data = adapter.enrich(_question_payload(doc))
						_apply_difficulty_fields(doc, data)
						_safe_apply_ai_topics(doc, topics=data.get("topics") or [])
						doc.save(ignore_permissions=True)
						result["enriched"] += 1
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
