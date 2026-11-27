import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any

import frappe
import requests

from trivia_sync.integrations.lms_questions import (
	MAX_TITLE_CHARS,
	apply_explanations_to_lms_question,
	apply_formatted_options_to_lms_question,
	compose_lms_question_html,
	extract_lms_question_options,
	strip_question_embeds,
)

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


def _repair_json_text(candidate: str) -> str:
	"""Repair common LLM JSON quirks (trailing commas outside strings, raw control chars inside strings)."""
	out: list[str] = []
	in_string = False
	escape = False
	length = len(candidate)
	idx = 0
	while idx < length:
		ch = candidate[idx]
		if in_string:
			if escape:
				out.append(ch)
				escape = False
			elif ch == "\\":
				out.append(ch)
				escape = True
			elif ch == '"':
				out.append(ch)
				in_string = False
			elif ch == "\n":
				out.append("\\n")
			elif ch == "\r":
				out.append("\\r")
			elif ch == "\t":
				out.append("\\t")
			else:
				out.append(ch)
		else:
			if ch == '"':
				out.append(ch)
				in_string = True
			elif ch == ",":
				lookahead = idx + 1
				while lookahead < length and candidate[lookahead] in " \t\r\n":
					lookahead += 1
				if lookahead < length and candidate[lookahead] in "}]":
					idx += 1
					continue
				out.append(ch)
			else:
				out.append(ch)
		idx += 1
	return "".join(out)


def _extract_json(raw_content: Any) -> dict[str, Any]:
	if isinstance(raw_content, dict):
		return raw_content
	text = str(raw_content or "").strip()
	if text.startswith("```"):
		text = re.sub(r"^```(?:json)?\s*", "", text)
		text = re.sub(r"\s*```$", "", text).strip()

	candidates = [text]
	match = re.search(r"\{[\s\S]*\}", text)
	if match and match.group(0) != text:
		candidates.append(match.group(0))

	last_error: Exception | None = None
	for candidate in candidates:
		for attempt in (candidate, _repair_json_text(candidate)):
			try:
				parsed = json.loads(attempt)
				if isinstance(parsed, dict):
					return parsed
			except ValueError as exc:
				last_error = exc
	if last_error:
		raise last_error
	raise ValueError("Empty or non-object JSON payload.")


def _build_enrich_messages(question: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
	options = question.get("options") or {}
	if isinstance(options, str):
		options = json.loads(options or "{}")
	ordered_letters = sorted(str(letter).upper() for letter, value in options.items() if value not in (None, ""))
	properties: dict[str, Any] = {
		**SCHEMA["properties"],
		"friendly_title": {"type": "string", "minLength": 8, "maxLength": 110},
	}
	required = [*SCHEMA["required"], "friendly_title"]
	if ordered_letters:
		properties["formatted_options"] = {
			"type": "object",
			"additionalProperties": False,
			"properties": {letter: {"type": "string", "minLength": 1, "maxLength": 2000} for letter in ordered_letters},
			"required": ordered_letters,
		}
		required.append("formatted_options")
	schema = {"type": "object", "additionalProperties": False, "properties": properties, "required": required}
	messages = [
		{
			"role": "system",
			"content": (
				"Você é Athena, especialista em avaliação de concursos públicos brasileiros. "
				"Use todo o seu conhecimento geral de domínio para classificar a dificuldade da questão, "
				"sem alterar o conteúdo do enunciado, das alternativas ou do gabarito. "
				"Considere complexidade conceitual, quantidade de inferências, pegadinhas, profundidade "
				"e dependência de legislação específica. "
				"1) Em friendly_title, crie um nome reduzido, amigável e altamente buscável (máx. 110 caracteres) que resuma o tema central da questão "
				"(ex.: 'PCASP · Registro contábil de contribuição patronal ao RPPS (FCC 2015)'). Nunca copie mecanicamente o começo do enunciado com reticências. "
				"2) Em formatted_options (quando houver alternativas), melhore APENAS a estética/legibilidade visual de cada alternativa "
				"(quebras de linha <br>, negrito <strong> em rótulos como 'D -', 'C -', 'I.', 'II.', 'III.'), "
				"SEM ALTERAR, ADICIONAR OU REMOVER NENHUMA PALAVRA, NÚMERO OU PONTUAÇÃO do texto original. Se já estiver limpa e curta, devolva-a exatamente igual. "
				"Responda exclusivamente no JSON Schema solicitado."
			),
		},
		{
			"role": "user",
			"content": json.dumps(
				{
					"qcode": question.get("qcode"),
					"texto_apoio": question.get("texto_apoio") or "",
					"enunciado": question.get("enunciado"),
					"alternativas": options,
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
	return messages, schema


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
				"Produza material didático em português brasileiro usando todo o seu conhecimento de domínio e as fontes fornecidas. "
				"Preserve fatos, não mostre gabaritos diretos nem invente dispositivos legais. Retorne apenas o JSON solicitado."
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
		"properties": {letter: {"type": "string", "minLength": 10, "maxLength": 1200} for letter in ordered_letters},
		"required": ordered_letters,
	}
	deprecation_clause = ""
	if question.get("deprecated"):
		deprecation_clause = (
			"ATENÇÃO — QUESTÃO DEPRECIADA / LEGISLAÇÃO SUPERADA: "
			f"Norma revogada: {question.get('deprecated_law') or 'não especificada'}. "
			f"Substituída por: {question.get('replacement_law') or 'legislação vigente aplicável'}. "
			"Nas explicações, contextualize explicitamente COMO ERA à época da prova e COMO É HOJE na legislação vigente, "
			"para que o estudante compreenda a evolução do legislador (mantendo a regra de não entregar o gabarito nas incorretas). "
		)
	messages = [
		{
			"role": "system",
			"content": (
				"Você é Athena, professora especialista em concursos públicos brasileiros. "
				"Use todo o seu conhecimento geral de domínio (e o texto_apoio, se fornecido) para escrever explicações em português brasileiro. "
				f"{deprecation_clause}"
				"REGRA CRÍTICA PARA ALTERNATIVAS INCORRETAS: explique especificamente por que aquela "
				"alternativa está errada SEM revelar, citar, referenciar ou dar dica de qual é a alternativa correta "
				"(nunca escreva frases como 'conforme a alternativa A' — o estudante verá essa mensagem ao errar). "
				"Para a(s) alternativa(s) correta(s), explique claramente por que ela responde ao enunciado. "
				"Retorne exclusivamente o JSON solicitado com uma chave para cada letra."
			),
		},
		{
			"role": "user",
			"content": json.dumps(
				{
					"texto_apoio": question.get("texto_apoio") or "",
					"enunciado": question.get("enunciado"),
					"alternativas": options,
					"gabarito_correto": question.get("correct_options") or [question.get("correct_option")],
					"comentario_geral": question.get("explanation") or "",
					"materia": question.get("materia"),
					"assunto": question.get("assunto"),
					"banca": question.get("banca"),
					"ano": question.get("ano"),
					"depreciada": bool(question.get("deprecated")),
					"norma_revogada": question.get("deprecated_law") or "",
					"substituida_por": question.get("replacement_law") or "",
					"resumo_mudanca": question.get("deprecation_note") or "",
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
	syllabus_candidates = question.get("syllabus_candidates") or []
	properties: dict[str, Any] = {
		"difficulty_stars": {"type": "integer", "minimum": 1, "maximum": 5},
		"difficulty_label": {"type": "string", "enum": ["Muito fácil", "Fácil", "Média", "Difícil", "Muito difícil"]},
		"reason": {"type": "string", "minLength": 20, "maxLength": 800},
		"learning_objective": {"type": "string", "minLength": 5, "maxLength": 300},
		"topics": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
		"general_explanation": {"type": "string", "minLength": 15, "maxLength": 1200},
		"suggested_materia": {"type": "string", "maxLength": 140},
		"suggested_assunto": {"type": "string", "maxLength": 140},
		"friendly_title": {"type": "string", "minLength": 8, "maxLength": 110},
		"formatted_options": {
			"type": "object",
			"additionalProperties": False,
			"properties": {letter: {"type": "string", "minLength": 1, "maxLength": 2000} for letter in ordered_letters},
			"required": ordered_letters,
		},
		"is_deprecated": {"type": "boolean"},
		"deprecated_law": {"type": "string", "maxLength": 160},
		"replacement_law": {"type": "string", "maxLength": 160},
		"deprecation_note": {"type": "string", "maxLength": 500},
		"option_explanations": {
			"type": "object",
			"additionalProperties": False,
			"properties": {letter: {"type": "string", "minLength": 10, "maxLength": 1200} for letter in ordered_letters},
			"required": ordered_letters,
		},
	}
	required_fields = [
		"difficulty_stars",
		"difficulty_label",
		"reason",
		"learning_objective",
		"topics",
		"general_explanation",
		"suggested_materia",
		"suggested_assunto",
		"friendly_title",
		"formatted_options",
		"is_deprecated",
		"deprecated_law",
		"replacement_law",
		"deprecation_note",
		"option_explanations",
	]
	if syllabus_candidates:
		properties["syllabus_topic_ids"] = {"type": "array", "items": {"type": "string"}, "maxItems": 6}
		required_fields.append("syllabus_topic_ids")
	schema = {"type": "object", "additionalProperties": False, "properties": properties, "required": required_fields}
	messages = [
		{
			"role": "system",
			"content": (
				"Você é Athena, professora especialista em avaliação de concursos públicos brasileiros. "
				"Use todo o seu conhecimento geral de domínio (e o texto_apoio, se fornecido) para analisar completamente a questão em português brasileiro, sem alterar enunciado, alternativas ou gabarito. "
				"1) Classifique a dificuldade (1 a 5 estrelas), justificativa técnica, objetivo de aprendizagem, tópicos, matéria e assunto. "
				"2) Em friendly_title, crie um nome reduzido, amigável e altamente buscável (máx. 110 caracteres) que resuma o tema central da questão "
				"(ex.: 'PCASP · Registro contábil de contribuição patronal ao RPPS (FCC 2015)'). Nunca copie mecanicamente o começo do enunciado com reticências. "
				"3) Em formatted_options, melhore APENAS a estética/legibilidade visual de cada alternativa "
				"(quebras de linha <br>, negrito <strong> em rótulos como 'D -', 'C -', 'I.', 'II.', 'III.'), "
				"SEM ALTERAR, ADICIONAR OU REMOVER NENHUMA PALAVRA, NÚMERO OU PONTUAÇÃO do texto original. Se a alternativa já estiver limpa e curta, devolva-a exatamente igual. "
				"4) Se houver itens em ementa_candidatos, selecione em syllabus_topic_ids apenas os IDs (campo 'name') que correspondem diretamente à questão (ou lista vazia se nenhum se aplicar). "
				"5) VERIFICAÇÃO DE LEGISLAÇÃO REVOGADA / QUESTÃO DEPRECIADA: verifique se a questão já vem marcada com depreciada=true OU se cobra legislação/regra integralmente revogada ou superada no ordenamento atual (ex.: Lei nº 8.666/1993 substituída pela Lei nº 14.133/2021, CPC/1973 substituído pelo CPC/2015, etc.). "
				"Se for depreciada, retorne is_deprecated=true, preencha deprecated_law, replacement_law e deprecation_note (resumo objetivo do que mudou), e estruture o general_explanation e as option_explanations contextualizando explicitamente 'Como era (à época da prova)' e 'Como é hoje (legislação vigente)', permitindo ao aluno analisar o padrão e a evolução do legislador. "
				"Caso a questão esteja vigente/atual, retorne is_deprecated=false e strings vazias em deprecated_law, replacement_law e deprecation_note. "
				"6) Escreva um comentário geral didático (general_explanation). "
				"7) Em option_explanations, explique cada alternativa individualmente (2, 3, 4, 5 ou mais alternativas, conforme fornecidas). "
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
					"texto_apoio": question.get("texto_apoio") or "",
					"enunciado": question.get("enunciado"),
					"alternativas": options,
					"gabarito_correto": question.get("correct_options") or [question.get("correct_option")],
					"comentario_geral": question.get("explanation") or "",
					"materia": question.get("materia"),
					"assunto": question.get("assunto"),
					"banca": question.get("banca"),
					"ano": question.get("ano"),
					"depreciada": bool(question.get("deprecated")),
					"norma_revogada": question.get("deprecated_law") or "",
					"substituida_por": question.get("replacement_law") or "",
					"resumo_mudanca": question.get("deprecation_note") or "",
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
		"properties": {"concepts": {"type": "array", "items": concept_schema, "minItems": 1, "maxItems": 3}},
		"required": ["concepts"],
	}
	messages = [
		{
			"role": "system",
			"content": (
				"Você é um professor especialista em concursos públicos brasileiros criando páginas de conhecimento (wiki didática). "
				"Use todo o seu conhecimento geral de domínio para identificar os conceitos pré-requisitos indispensáveis para resolver a questão "
				"(ex.: 'Derivação parassintética') e seus sub-conceitos diretos (ex.: 'Prefixo', 'Sufixo', 'Derivação prefixal e sufixal'). "
				"Para cada conceito e sub-conceito, escreva em português brasileiro: resumo claro, explicação conceitual didática, "
				"exemplos práticos (SEM copiar nem entregar o gabarito da questão) e pegadinhas frequentes de banca. "
				"Responda exclusivamente no JSON Schema solicitado."
			),
		},
		{
			"role": "user",
			"content": json.dumps(
				{
					"texto_apoio": question.get("texto_apoio") or "",
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


def _build_review_debate_messages(
	question: dict[str, Any],
	reviewer_feedback: str,
	proposed_correct: list[str] | None = None,
	history: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any], list[str]]:
	options = question.get("options") or {}
	if isinstance(options, str):
		options = json.loads(options or "{}")
	ordered_letters = sorted(str(letter).upper() for letter, value in options.items() if value not in (None, ""))
	if not ordered_letters:
		raise AIEnrichmentError("Question has no alternatives to review.")

	schema = {
		"type": "object",
		"additionalProperties": False,
		"properties": {
			"agrees_with_reviewer": {"type": "boolean"},
			"ai_reply": {"type": "string", "minLength": 20, "maxLength": 2500},
			"recommended_correct_options": {
				"type": "array",
				"items": {"type": "string", "enum": ordered_letters},
				"minItems": 1,
				"maxItems": len(ordered_letters),
			},
			"difficulty_stars": {"type": "integer", "minimum": 1, "maximum": 5},
			"difficulty_label": {"type": "string", "enum": ["Muito fácil", "Fácil", "Média", "Difícil", "Muito difícil"]},
			"reason": {"type": "string", "minLength": 20, "maxLength": 800},
			"option_explanations": {
				"type": "object",
				"additionalProperties": False,
				"properties": {letter: {"type": "string", "minLength": 10, "maxLength": 1200} for letter in ordered_letters},
				"required": ordered_letters,
			},
		},
		"required": [
			"agrees_with_reviewer",
			"ai_reply",
			"recommended_correct_options",
			"difficulty_stars",
			"difficulty_label",
			"reason",
			"option_explanations",
		],
	}

	messages: list[dict[str, str]] = [
		{
			"role": "system",
			"content": (
				"Você é um professor especialista em concursos públicos brasileiros em diálogo técnico (réplica e tréplica) com um revisor humano. "
				"Avalie a questão e a argumentação do revisor com total rigor técnico, jurídico e imparcialidade. "
				"REGRAS OBRIGATÓRIAS: "
				"1) NUNCA defenda cegamente o gabarito cadastrado nem explicações anteriores — especialmente se `gabarito_pendente` for true (nesse caso o gabarito atual é apenas um marcador provisório sem valor). "
				"2) Se o revisor tiver razão, marque `agrees_with_reviewer: true`, admita claramente o erro em `ai_reply` e corrija `recommended_correct_options` e todas as `option_explanations`. "
				"3) Se você discordar do revisor com base sólida (lei, doutrina, norma gramatical ou cálculo), marque `agrees_with_reviewer: false` e fundamente sua tréplica em `ai_reply` de forma clara e respeitosa. "
				"4) Em `option_explanations`, explique cada alternativa coerente com `recommended_correct_options`. "
				"Para alternativas incorretas, explique o erro específico SEM revelar, citar ou apontar qual é a alternativa correta (nunca cite outra letra). "
				"Responda exclusivamente no JSON Schema solicitado."
			),
		},
		{
			"role": "user",
			"content": json.dumps(
				{
					"qcode": question.get("qcode"),
					"texto_apoio": question.get("texto_apoio") or "",
					"enunciado": question.get("enunciado"),
					"alternativas": options,
					"gabarito_atual": question.get("correct_options") or [],
					"gabarito_pendente": bool(question.get("answer_key_pending")),
					"explicacoes_atuais": question.get("current_explanations") or {},
					"comentario_geral": question.get("explanation") or "",
					"materia": question.get("materia"),
					"assunto": question.get("assunto"),
					"banca": question.get("banca"),
					"ano": question.get("ano"),
				},
				ensure_ascii=False,
			),
		},
	]
	for turn in (history or [])[-6:]:
		role = "assistant" if turn.get("role") == "assistant" else "user"
		content = str(turn.get("content") or "").strip()
		if content:
			messages.append({"role": role, "content": content})

	feedback_payload: dict[str, Any] = {"replica_do_revisor": reviewer_feedback.strip()}
	if proposed_correct:
		feedback_payload["gabarito_proposto_pelo_revisor"] = proposed_correct
	messages.append({"role": "user", "content": json.dumps(feedback_payload, ensure_ascii=False)})
	return messages, schema, ordered_letters


class _BaseAIAdapter:
	model: str = ""

	def _chat_json(self, messages: list[dict[str, str]], schema_name: str, schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
		raise NotImplementedError

	def enrich(self, question: dict[str, Any]) -> dict[str, Any]:
		source = json.dumps(question, ensure_ascii=False, sort_keys=True, default=str)
		enrichment_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
		messages, schema = _build_enrich_messages(question)
		result = self._chat_json(messages, "question_enrichment", schema, 2000)
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

	def review_with_feedback(
		self,
		question: dict[str, Any],
		reviewer_feedback: str,
		proposed_correct: list[str] | None = None,
		history: list[dict[str, str]] | None = None,
	) -> dict[str, Any]:
		messages, schema, ordered_letters = _build_review_debate_messages(
			question,
			reviewer_feedback=reviewer_feedback,
			proposed_correct=proposed_correct,
			history=history,
		)
		result = self._chat_json(messages, "question_review_debate", schema, 3500)
		stars = int(result.get("difficulty_stars", 3))
		if stars not in range(1, 6):
			stars = 3
		raw_exp = result.get("option_explanations") or {}
		explanations = {letter: str(raw_exp.get(letter) or "").strip() for letter in ordered_letters}
		if any(not text for text in explanations.values()):
			raise AIEnrichmentError("The AI provider returned empty explanations during review.")
		rec_correct = [
			str(l).strip().upper()
			for l in (result.get("recommended_correct_options") or [])
			if str(l).strip().upper() in ordered_letters
		]
		if not rec_correct:
			raise AIEnrichmentError("The AI provider did not return a valid recommended answer key.")
		return {
			"agrees_with_reviewer": bool(result.get("agrees_with_reviewer")),
			"ai_reply": str(result.get("ai_reply") or "").strip(),
			"recommended_correct_options": list(dict.fromkeys(rec_correct)),
			"difficulty_stars": stars,
			"difficulty_label": DIFFICULTY_LABELS[stars],
			"reason": str(result.get("reason") or "").strip(),
			"option_explanations": explanations,
			"model": self.model,
		}


	def grade_student_reflection(
		self,
		question: dict[str, Any],
		teacher_comment: str,
		student_answer: str,
	) -> dict[str, Any]:
		messages, schema = _build_student_reflection_messages(
			question,
			teacher_comment=teacher_comment,
			student_answer=student_answer,
		)
		result = self._chat_json(messages, "student_reflection_grading", schema, 2000)
		verdict = str(result.get("verdict") or "Reflexão registrada").strip()
		if verdict not in ("Correta", "Parcialmente correta", "Incorreta", "Reflexão registrada"):
			verdict = "Reflexão registrada"
		feedback = str(result.get("feedback") or "").strip()
		if not feedback:
			raise AIEnrichmentError("Athena não retornou comentário para a resposta.")
		return {
			"verdict": verdict,
			"feedback": feedback,
			"key_takeaway": str(result.get("key_takeaway") or "").strip(),
			"model": self.model,
		}


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


_CODEX_AUTH_LOCK = threading.Lock()
_CODEX_AUTH_PROC: subprocess.Popen | None = None
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
	return _ANSI_RE.sub("", str(text or ""))


def _resolve_codex_binary(settings_doc=None) -> str:
	configured = str(getattr(settings_doc, "ai_codex_binary", None) or "").strip() if settings_doc else ""
	if configured:
		if os.path.isfile(configured) and os.access(configured, os.X_OK):
			return configured
		raise AIEnrichmentError(f"Binário codex configurado não encontrado ou sem permissão de execução: {configured}")

	found = shutil.which("codex")
	if found:
		return found

	home = Path.home()
	candidates: list[Path] = []
	nvm_root = home / ".nvm" / "versions" / "node"
	if nvm_root.is_dir():
		candidates.extend(sorted(nvm_root.glob("*/bin/codex"), reverse=True))
	candidates.extend([
		home / ".local" / "bin" / "codex",
		Path("/usr/local/bin/codex"),
		Path("/usr/bin/codex"),
	])
	for path in candidates:
		if path.is_file() and os.access(str(path), os.X_OK):
			return str(path)

	raise AIEnrichmentError(
		"Codex CLI não encontrado no servidor. Instale `@openai/codex` ou informe o caminho do binário em Trivia Sync Settings."
	)


def _codex_env(binary_path: str) -> dict[str, str]:
	env = dict(os.environ)
	# Force OAuth session instead of accidentally billing an OpenAI API key in the environment
	env.pop("OPENAI_API_KEY", None)
	env.pop("CODEX_API_KEY", None)
	bin_dir = str(Path(binary_path).parent)
	current_path = env.get("PATH") or ""
	if bin_dir and bin_dir not in current_path.split(os.pathsep):
		env["PATH"] = f"{bin_dir}{os.pathsep}{current_path}" if current_path else bin_dir
	return env


def codex_login_status(settings_doc=None) -> dict[str, Any]:
	settings = settings_doc or frappe.get_single("Trivia Sync Settings")
	binary = _resolve_codex_binary(settings)
	proc = subprocess.run(
		[binary, "login", "status"],
		capture_output=True,
		text=True,
		timeout=15,
		env=_codex_env(binary),
	)
	combined = _strip_ansi((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
	lower = combined.lower()
	not_logged = any(marker in lower for marker in ("not logged in", "logged out", "unauthenticated", "no credentials"))
	authenticated = proc.returncode == 0 and not not_logged
	return {
		"ok": authenticated,
		"authenticated": authenticated,
		"backend": "Codex CLI (OAuth)",
		"binary": binary,
		"model": (getattr(settings, "ai_codex_model", None) or "").strip() or "codex-default",
		"status_text": combined or ("Logged in" if authenticated else "Not logged in"),
	}


def start_codex_device_auth(settings_doc=None) -> dict[str, Any]:
	"""Start `codex login --device-auth` in the background and return verification URL + one-time code."""
	global _CODEX_AUTH_PROC
	frappe.only_for("System Manager")
	settings = settings_doc or frappe.get_single("Trivia Sync Settings")
	binary = _resolve_codex_binary(settings)

	status = codex_login_status(settings)
	if status["authenticated"]:
		return {
			"ok": True,
			"already_authenticated": True,
			"status_text": status["status_text"],
			"binary": binary,
		}

	with _CODEX_AUTH_LOCK:
		if _CODEX_AUTH_PROC is not None and _CODEX_AUTH_PROC.poll() is None:
			try:
				_CODEX_AUTH_PROC.terminate()
			except Exception:
				pass
		proc = subprocess.Popen(
			[binary, "login", "--device-auth"],
			stdin=subprocess.DEVNULL,
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
			env=_codex_env(binary),
		)
		_CODEX_AUTH_PROC = proc

	lines: list[str] = []
	verification_url = ""
	user_code = ""
	deadline = time.monotonic() + 10.0

	url_re = re.compile(r"https?://[^\s]+")
	code_re = re.compile(r"\b([A-Z0-9]{4,5}-[A-Z0-9]{4,5})\b")

	while time.monotonic() < deadline and proc.stdout is not None:
		ready, _, _ = select.select([proc.stdout], [], [], 0.25)
		if ready:
			chunk = proc.stdout.readline()
			if not chunk:
				break
			clean = _strip_ansi(chunk).strip()
			if clean:
				lines.append(clean)
				if not verification_url:
					m_url = url_re.search(clean)
					if m_url:
						verification_url = m_url.group(0).rstrip(".,)")
				if not user_code:
					m_code = code_re.search(clean)
					if m_code:
						user_code = m_code.group(1)
				if verification_url and user_code:
					break
		elif proc.poll() is not None:
			break

	def _reap(p: subprocess.Popen):
		try:
			p.wait(timeout=900)
		except Exception:
			try:
				p.kill()
			except Exception:
				pass

	threading.Thread(target=_reap, args=(proc,), daemon=True).start()

	raw_output = "\n".join(lines).strip()
	if not verification_url and proc.poll() not in (None, 0):
		raise AIEnrichmentError(f"Não foi possível iniciar o login OAuth do Codex: {raw_output or 'erro desconhecido'}")

	return {
		"ok": True,
		"already_authenticated": False,
		"verification_url": verification_url or "https://auth.openai.com/codex/device",
		"user_code": user_code,
		"raw_output": raw_output,
		"binary": binary,
	}


class CodexCLIAdapter(_BaseAIAdapter):
	"""Adapter that executes OpenAI Codex CLI non-interactively using the user's OAuth session (no API key)."""

	def __init__(self, settings_doc=None):
		self.settings = settings_doc or frappe.get_single("Trivia Sync Settings")
		self.binary = _resolve_codex_binary(self.settings)
		self.explicit_model = str(getattr(self.settings, "ai_codex_model", None) or "").strip()
		self.model = self.explicit_model or "codex-default"
		self.timeout = max(30, int(getattr(self.settings, "ai_timeout", None) or 120))

	def _chat_json(self, messages: list[dict[str, str]], schema_name: str, schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
		prompt_parts: list[str] = []
		for msg in messages:
			role = str(msg.get("role") or "user").upper()
			content = str(msg.get("content") or "").strip()
			if content:
				prompt_parts.append(f"[{role}]\n{content}")
		prompt_parts.append(
			"[OUTPUT_REQUIREMENT]\nResponda EXCLUSIVAMENTE com um objeto JSON válido seguindo o JSON Schema fornecido. "
			"Não execute comandos de shell, não leia arquivos locais e não adicione texto fora do JSON."
		)
		prompt_text = "\n\n".join(prompt_parts)

		with tempfile.TemporaryDirectory(prefix="trivia_codex_") as tmpdir:
			schema_path = os.path.join(tmpdir, f"{schema_name}.schema.json")
			output_path = os.path.join(tmpdir, f"{schema_name}.out.json")
			with open(schema_path, "w", encoding="utf-8") as sf:
				json.dump(schema, sf, ensure_ascii=False)

			cmd = [
				self.binary,
				"exec",
				"--ephemeral",
				"--skip-git-repo-check",
				"--sandbox",
				"read-only",
				"--color",
				"never",
				"--output-schema",
				schema_path,
				"-o",
				output_path,
			]
			if self.explicit_model:
				cmd.extend(["-m", self.explicit_model])
			cmd.append("-")

			try:
				proc = subprocess.run(
					cmd,
					input=prompt_text,
					capture_output=True,
					text=True,
					timeout=self.timeout,
					env=_codex_env(self.binary),
					cwd=tmpdir,
				)
			except subprocess.TimeoutExpired as exc:
				raise AIEnrichmentError(
					f"Codex CLI excedeu o tempo limite de {self.timeout}s."
				) from exc
			except OSError as exc:
				raise AIEnrichmentError(f"Falha ao executar Codex CLI ({self.binary}): {exc}") from exc

			content = ""
			if os.path.isfile(output_path):
				with open(output_path, "r", encoding="utf-8") as of:
					content = of.read().strip()
			if not content:
				content = (proc.stdout or "").strip()

			if proc.returncode != 0 and not content:
				err_text = _strip_ansi(proc.stderr or proc.stdout or "").strip()
				if any(k in err_text.lower() for k in ("not logged in", "login", "unauthorized", "auth", "sign in")):
					raise AIEnrichmentError(
						"Sessão OAuth do Codex não autenticada ou expirada. "
						"Clique em 'Conectar Codex (OAuth)' em Trivia Sync Settings."
					)
				raise AIEnrichmentError(f"Codex CLI falhou (código {proc.returncode}): {err_text[:400]}")

			try:
				return _extract_json(content)
			except ValueError as exc:
				raise AIEnrichmentError(f"Codex CLI retornou JSON inválido: {exc}") from exc


def get_ai_adapter(settings_doc=None) -> _BaseAIAdapter:
	settings = settings_doc or frappe.get_single("Trivia Sync Settings")
	backend = (getattr(settings, "ai_backend", None) or "").strip()
	if backend == "Codex CLI (OAuth)":
		return CodexCLIAdapter(settings)
	if backend == "Custom OpenAI-compatible":
		return OpenAICompatibleAdapter(settings)
	if backend == "Frappe Flow":
		return FlowAdapter(settings)
	if getattr(settings, "ai_api_key", None):
		return OpenAICompatibleAdapter(settings)
	return FlowAdapter(settings)


def test_ai_connection(settings_doc=None) -> dict[str, Any]:
	settings = settings_doc or frappe.get_single("Trivia Sync Settings")
	try:
		adapter = get_ai_adapter(settings)
		if isinstance(adapter, CodexCLIAdapter):
			return codex_login_status(settings)
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


def _supporting_text_content(doc) -> str:
	name = getattr(doc, "trivia_texto_apoio", None) or getattr(doc, "texto_apoio", None)
	if not name:
		return ""
	try:
		if hasattr(frappe, "db") and hasattr(frappe.db, "get_value"):
			return str(frappe.db.get_value("Trivia Supporting Text", name, "conteudo") or "").strip()
	except Exception:
		return ""
	return ""


def _question_payload(doc, include_teacher_comment: bool = False) -> dict[str, Any]:
	options, correct, explanations = extract_lms_question_options(doc)
	enunciado = strip_question_embeds(getattr(doc, "question", None) or getattr(doc, "enunciado", None) or "")
	if not options and getattr(doc, "options", None):
		options = json.loads(doc.options) if isinstance(doc.options, str) else doc.options
	if not correct and getattr(doc, "correct_option", None):
		correct = [doc.correct_option]
	answer_key_pending = bool(getattr(doc, "trivia_answer_key_pending", 0))
	effective_correct = [] if answer_key_pending else correct
	# Teacher comment (`trivia_general_explanation`) is strictly isolated from initial AI analysis;
	# it is only shared when explicitly requested during a Réplica/Tréplica debate.
	explanation_for_ai = (
		(getattr(doc, "trivia_general_explanation", None) or "")
		if include_teacher_comment
		else (getattr(doc, "trivia_ai_comment", None) or "")
	)
	payload: dict[str, Any] = {
		"qcode": getattr(doc, "trivia_qcode", None) or getattr(doc, "qcode", None),
		"enunciado": enunciado,
		"options": options,
		"correct_option": effective_correct[0] if effective_correct else None,
		"correct_options": effective_correct,
		"answer_key_pending": answer_key_pending,
		"current_explanations": explanations,
		"explanation": explanation_for_ai,
		"materia": getattr(doc, "trivia_materia", None) or getattr(doc, "materia", None),
		"assunto": getattr(doc, "trivia_assunto", None) or getattr(doc, "assunto", None),
		"banca": getattr(doc, "trivia_banca", None) or getattr(doc, "banca", None),
		"ano": getattr(doc, "trivia_ano", None) or getattr(doc, "ano", None),
		"deprecated": bool(int(getattr(doc, "trivia_deprecated", 0) or 0)),
		"deprecated_law": getattr(doc, "trivia_deprecated_law", None) or "",
		"replacement_law": getattr(doc, "trivia_replacement_law", None) or "",
		"deprecation_note": getattr(doc, "trivia_deprecation_note", None) or "",
	}
	supporting = _supporting_text_content(doc)
	if supporting:
		payload["texto_apoio"] = supporting
	return payload


def _apply_difficulty_fields(doc, data):
	doc.trivia_ai_difficulty_stars = stars_to_rating(data["difficulty_stars"])
	doc.trivia_ai_difficulty_label = data["difficulty_label"]
	doc.trivia_ai_difficulty_reason = data["reason"]
	doc.trivia_ai_learning_objective = data["learning_objective"]
	doc.trivia_ai_topics = json.dumps(data.get("topics") or [], ensure_ascii=False)
	doc.trivia_ai_model = data["model"]
	doc.trivia_ai_enriched_at = frappe.utils.now_datetime()


def _apply_deprecation_fields(doc, data):
	if not data.get("is_deprecated"):
		return
	doc.trivia_deprecated = 1
	if data.get("deprecated_law") and not getattr(doc, "trivia_deprecated_law", None):
		doc.trivia_deprecated_law = str(data["deprecated_law"]).strip()[:140]
	if data.get("replacement_law") and not getattr(doc, "trivia_replacement_law", None):
		doc.trivia_replacement_law = str(data["replacement_law"]).strip()[:140]
	if data.get("deprecation_note") and not getattr(doc, "trivia_deprecation_note", None):
		doc.trivia_deprecation_note = str(data["deprecation_note"]).strip()[:500]


def _apply_presentation_fields(doc, data):
	friendly = re.sub(r"\s+", " ", str(data.get("friendly_title") or "")).strip()
	if friendly:
		doc.trivia_title = friendly[:MAX_TITLE_CHARS]
	formatted_options = data.get("formatted_options")
	if isinstance(formatted_options, dict):
		apply_formatted_options_to_lms_question(doc, formatted_options)


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
		return {"trivia_subject_link": None, "trivia_topic_link": None, "syllabus_topics_added": [], "tags_added": []}


def _refresh_question_html(doc):
	if hasattr(doc, "question"):
		doc.question = compose_lms_question_html(
			doc.question,
			texto_apoio=getattr(doc, "trivia_texto_apoio", None),
			knowledge_rows=getattr(doc, "trivia_knowledge_pages", None),
			deprecated=bool(int(getattr(doc, "trivia_deprecated", 0) or 0)),
			deprecated_law=getattr(doc, "trivia_deprecated_law", None),
			replacement_law=getattr(doc, "trivia_replacement_law", None),
			deprecation_note=getattr(doc, "trivia_deprecation_note", None),
		)


def apply_ai_topics(question_name: str):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	doc = frappe.get_doc("LMS Question", question_name)
	from trivia_sync.integrations.reconciliation import apply_ai_topics_to_question

	applied = apply_ai_topics_to_question(doc)
	doc.save(ignore_permissions=True)
	return {"name": doc.name, **applied}


def draft_question_option_explanations(question_name: str):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable AI enrichment in settings before generating explanation drafts.")
	doc = frappe.get_doc("LMS Question", question_name)
	if getattr(doc, "trivia_answer_key_pending", 0):
		frappe.throw(
			"Esta questão está com gabarito pendente (Answer key pending). "
			"Informe ou confirme o gabarito primeiro (ou use 'Contestar / Réplica (IA)') para evitar explicações baseadas no marcador provisório."
		)
	adapter = get_ai_adapter(settings)
	draft = adapter.draft_option_explanations(_question_payload(doc))
	apply_explanations_to_lms_question(doc, draft["explanations"])
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "option_explanations": draft["explanations"], "model": draft["model"], "trivia_status": doc.trivia_status}


def enrich_question_doc(doc, settings_doc=None):
	settings_doc = settings_doc or frappe.get_single("Trivia Sync Settings")
	adapter = get_ai_adapter(settings_doc)
	payload = _question_payload(doc)
	result = adapter.enrich(payload)
	_apply_difficulty_fields(doc, result)
	_apply_presentation_fields(doc, result)
	_safe_apply_ai_topics(doc, topics=result.get("topics") or [])
	doc.save(ignore_permissions=True)
	return result


def enrich_single_question_difficulty(question_name: str):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable AI enrichment in settings before classifying difficulty.")
	doc = frappe.get_doc("LMS Question", question_name)
	result = enrich_question_doc(doc, settings)
	return {
		"name": doc.name,
		"difficulty_stars": result["difficulty_stars"],
		"difficulty_label": result["difficulty_label"],
		"learning_objective": result["learning_objective"],
		"topics": result["topics"],
		"model": result["model"],
	}


def extract_question_knowledge(question_name: str):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable AI enrichment in settings before extracting knowledge concepts.")
	doc = frappe.get_doc("LMS Question", question_name)
	payload = _question_payload(doc)
	try:
		payload["topics"] = json.loads(getattr(doc, "trivia_ai_topics", None) or "[]")
	except (TypeError, ValueError):
		payload["topics"] = []
	adapter = get_ai_adapter(settings)
	extracted = adapter.extract_knowledge_concepts(payload)
	from trivia_sync.integrations.knowledge import link_knowledge_concepts

	summary = link_knowledge_concepts(doc, extracted["concepts"], ai_model=extracted["model"])
	_refresh_question_html(doc)
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "model": extracted["model"], **summary}


def enrich_question_full(question_name: str):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable AI enrichment in settings before enriching questions.")
	doc = frappe.get_doc("LMS Question", question_name)
	payload = _question_payload(doc)
	pending_key = bool(payload.get("answer_key_pending"))
	try:
		from trivia_sync.integrations.reconciliation import candidate_syllabus_topics

		payload["syllabus_candidates"] = [
			{"name": row.get("name"), "titulo": row.get("titulo")}
			for row in candidate_syllabus_topics(concurso_cargo=getattr(doc, "trivia_concurso_cargo", None), limit=60)
		]
	except Exception:
		payload["syllabus_candidates"] = []

	adapter = get_ai_adapter(settings)
	if pending_key:
		# Never generate per-option explanations from the temporary placeholder answer key
		data = adapter.enrich(payload)
		_apply_difficulty_fields(doc, data)
		_apply_presentation_fields(doc, data)
		applied = _safe_apply_ai_topics(doc, topics=data.get("topics") or [])
		explanations_out = {}
	else:
		data = adapter.enrich_full(payload)
		_apply_difficulty_fields(doc, data)
		_apply_deprecation_fields(doc, data)
		_apply_presentation_fields(doc, data)
		apply_explanations_to_lms_question(doc, data["option_explanations"])
		if data.get("general_explanation"):
			doc.trivia_ai_comment = data["general_explanation"]
		applied = _safe_apply_ai_topics(
			doc,
			topics=data.get("topics") or [],
			suggested_materia=data.get("suggested_materia"),
			suggested_assunto=data.get("suggested_assunto"),
			syllabus_topic_names=data.get("syllabus_topic_ids") or [],
		)
		explanations_out = data["option_explanations"]
	knowledge_summary = {"knowledge_pages_linked": [], "knowledge_pages_created": [], "knowledge_pages_reused": []}
	try:
		from trivia_sync.integrations.knowledge import link_knowledge_concepts

		extracted = adapter.extract_knowledge_concepts({**payload, "topics": data.get("topics") or []})
		knowledge_summary = link_knowledge_concepts(doc, extracted["concepts"], ai_model=extracted["model"])
	except Exception:
		pass
	_refresh_question_html(doc)
	doc.save(ignore_permissions=True)
	return {
		"name": doc.name,
		"trivia_status": getattr(doc, "trivia_status", None),
		"explanations_skipped_pending_key": pending_key,
		"difficulty_stars": data["difficulty_stars"],
		"difficulty_label": data["difficulty_label"],
		"learning_objective": data["learning_objective"],
		"topics": data["topics"],
		"option_explanations": explanations_out,
		"model": data["model"],
		**applied,
		**knowledge_summary,
	}


def review_question_with_feedback(
	question_name: str,
	feedback: str,
	proposed_correct: str | list[str] | None = None,
	history: str | list[dict[str, str]] | None = None,
	include_general_comment: bool = True,
) -> dict[str, Any]:
	"""Run an interactive Réplica/Tréplica review with the AI without mutating the question yet."""
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable AI enrichment in settings before starting an AI review.")
	cleaned_feedback = str(feedback or "").strip()
	if not cleaned_feedback:
		frappe.throw("Provide your argument / feedback for the AI review.")
	doc = frappe.get_doc("LMS Question", question_name)
	payload = _question_payload(doc, include_teacher_comment=bool(include_general_comment))

	parsed_proposed: list[str] | None = None
	if proposed_correct:
		if isinstance(proposed_correct, str):
			try:
				maybe = json.loads(proposed_correct)
				parsed_proposed = [str(x).strip().upper() for x in maybe] if isinstance(maybe, list) else [proposed_correct.strip().upper()]
			except ValueError:
				parsed_proposed = [p.strip().upper() for p in re.split(r"[,;/\s]+", proposed_correct) if p.strip()]
		elif isinstance(proposed_correct, list):
			parsed_proposed = [str(x).strip().upper() for x in proposed_correct if str(x).strip()]

	parsed_history: list[dict[str, str]] = []
	if history:
		if isinstance(history, str):
			try:
				parsed_history = json.loads(history) or []
			except ValueError:
				parsed_history = []
		elif isinstance(history, list):
			parsed_history = history

	adapter = get_ai_adapter(settings)
	review = adapter.review_with_feedback(
		payload,
		reviewer_feedback=cleaned_feedback,
		proposed_correct=parsed_proposed,
		history=parsed_history,
	)
	return {
		"name": doc.name,
		"current_correct_options": payload.get("correct_options") or [],
		"answer_key_pending": bool(payload.get("answer_key_pending")),
		**review,
	}


def apply_question_ai_review(
	question_name: str,
	correct_options: str | list[str],
	option_explanations: str | dict[str, str],
	difficulty_stars: int | None = None,
	difficulty_label: str | None = None,
	reason: str | None = None,
	model: str | None = None,
) -> dict[str, Any]:
	"""Apply an approved AI review (answer key, per-option explanations, difficulty) to LMS Question."""
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	doc = frappe.get_doc("LMS Question", question_name)
	if isinstance(correct_options, str):
		try:
			parsed_corr = json.loads(correct_options)
		except ValueError:
			parsed_corr = [p.strip().upper() for p in re.split(r"[,;/\s]+", correct_options) if p.strip()]
	else:
		parsed_corr = list(correct_options or [])
	chosen = {str(x).strip().upper() for x in parsed_corr if str(x).strip()}
	if not chosen:
		frappe.throw("Provide at least one correct option letter to apply.")

	if isinstance(option_explanations, str):
		explanations = json.loads(option_explanations or "{}")
	else:
		explanations = dict(option_explanations or {})

	options, _, _ = extract_lms_question_options(doc)
	if not chosen.issubset(set(options.keys())):
		frappe.throw("Selected correct options do not match the question's alternatives.")

	from trivia_sync.integrations.lms_questions import OPTION_LETTERS

	for idx, letter in enumerate(OPTION_LETTERS, start=1):
		if letter in options:
			doc.set(f"is_correct_{idx}", int(letter in chosen))
		else:
			doc.set(f"is_correct_{idx}", 0)
	doc.multiple = int(len(chosen) > 1)
	doc.trivia_answer_key_pending = 0

	if difficulty_stars:
		doc.trivia_ai_difficulty_stars = stars_to_rating(int(difficulty_stars))
		doc.trivia_ai_difficulty_label = difficulty_label or DIFFICULTY_LABELS[max(1, min(5, int(difficulty_stars)))]
	if reason:
		doc.trivia_ai_difficulty_reason = reason
	if model:
		doc.trivia_ai_model = model
	doc.trivia_ai_enriched_at = frappe.utils.now_datetime()

	apply_explanations_to_lms_question(doc, explanations)
	doc.save(ignore_permissions=True)
	return {
		"name": doc.name,
		"correct_options": sorted(chosen),
		"trivia_answer_key_pending": 0,
		"trivia_status": getattr(doc, "trivia_status", None),
	}


def _has_all_lms_explanations(doc) -> bool:
	options, _, explanations = extract_lms_question_options(doc)
	if len(options) < 2:
		return False
	return all(bool(explanations.get(letter)) for letter in options)


def enrich_questions_batch(
	question_names: list[str] | None = None,
	mode: str = "full",
	limit: int | None = None,
	include_knowledge: bool = True,
	force: bool = False,
	filters: dict[str, Any] | None = None,
):
	if mode not in ("full", "difficulty", "explanations", "knowledge"):
		raise frappe.ValidationError("Invalid AI batch mode.")
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		raise frappe.ValidationError("Enable AI enrichment in settings before running it.")
	adapter = get_ai_adapter(settings)
	default_limit = len(question_names) if question_names else int(settings.ai_batch_size or 10)
	batch_limit = max(1, min(int(limit or default_limit), 200))

	if question_names:
		targets = list(dict.fromkeys(str(name) for name in question_names if name))[:batch_limit]
	else:
		query_filters = {"type": "Choices", **(filters or {})}
		if not force and mode == "difficulty":
			query_filters.setdefault("trivia_ai_enriched_at", ["is", "not set"])
		elif not force and mode in ("full", "explanations"):
			query_filters.setdefault("trivia_status", ["!=", "Ready"])
		targets = frappe.get_all(
			"LMS Question",
			filters=query_filters,
			pluck="name",
			order_by="creation asc",
			limit_page_length=batch_limit,
		) or []

	run = frappe.new_doc("Trivia Sync Run")
	run.source = "IA"
	run.operation = f"AI batch ({mode})"
	run.status = "Running"
	run.started_at = frappe.utils.now_datetime()
	run.records_received = len(targets)
	run.parameters_json = json.dumps(
		{"mode": mode, "limit": batch_limit, "include_knowledge": bool(include_knowledge), "force": bool(force), "count": len(targets)},
		ensure_ascii=False,
	)
	run.insert(ignore_permissions=True)
	frappe.db.commit()

	result = {"processed": 0, "enriched": 0, "skipped": 0, "errors": 0, "run": getattr(run, "name", None)}
	try:
		for name in targets:
			try:
				doc = frappe.get_doc("LMS Question", name)
				payload = _question_payload(doc)
				if not payload.get("options"):
					result["skipped"] += 1
				elif mode == "difficulty":
					if not force and getattr(doc, "trivia_ai_enriched_at", None):
						result["skipped"] += 1
					else:
						data = adapter.enrich(payload)
						_apply_difficulty_fields(doc, data)
						_apply_presentation_fields(doc, data)
						_safe_apply_ai_topics(doc, topics=data.get("topics") or [])
						doc.save(ignore_permissions=True)
						result["enriched"] += 1
				elif mode == "explanations":
					if payload.get("answer_key_pending") or (not force and _has_all_lms_explanations(doc)):
						result["skipped"] += 1
					else:
						draft = adapter.draft_option_explanations(payload)
						apply_explanations_to_lms_question(doc, draft["explanations"])
						doc.save(ignore_permissions=True)
						result["enriched"] += 1
				elif mode == "knowledge":
					if not force and getattr(doc, "trivia_knowledge_pages", None):
						result["skipped"] += 1
					else:
						try:
							payload["topics"] = json.loads(getattr(doc, "trivia_ai_topics", None) or "[]")
						except (TypeError, ValueError):
							payload["topics"] = []
						extracted = adapter.extract_knowledge_concepts(payload)
						from trivia_sync.integrations.knowledge import link_knowledge_concepts

						link_knowledge_concepts(doc, extracted["concepts"], ai_model=extracted["model"])
						_refresh_question_html(doc)
						doc.save(ignore_permissions=True)
						result["enriched"] += 1
				else:  # full
					already_complete = (
						bool(getattr(doc, "trivia_ai_enriched_at", None))
						and _has_all_lms_explanations(doc)
						and (not include_knowledge or bool(getattr(doc, "trivia_knowledge_pages", None)))
					)
					if not force and already_complete:
						result["skipped"] += 1
					else:
						if payload.get("answer_key_pending"):
							data = adapter.enrich(payload)
							_apply_difficulty_fields(doc, data)
							_apply_presentation_fields(doc, data)
							_safe_apply_ai_topics(doc, topics=data.get("topics") or [])
						else:
							try:
								from trivia_sync.integrations.reconciliation import candidate_syllabus_topics

								payload["syllabus_candidates"] = [
									{"name": row.get("name"), "titulo": row.get("titulo")}
									for row in candidate_syllabus_topics(concurso_cargo=getattr(doc, "trivia_concurso_cargo", None), limit=60)
								]
							except Exception:
								payload["syllabus_candidates"] = []
							data = adapter.enrich_full(payload)
							_apply_difficulty_fields(doc, data)
							_apply_deprecation_fields(doc, data)
							_apply_presentation_fields(doc, data)
							apply_explanations_to_lms_question(doc, data["option_explanations"])
							if data.get("general_explanation"):
								doc.trivia_ai_comment = data["general_explanation"]
							_safe_apply_ai_topics(
								doc,
								topics=data.get("topics") or [],
								suggested_materia=data.get("suggested_materia"),
								suggested_assunto=data.get("suggested_assunto"),
								syllabus_topic_names=data.get("syllabus_topic_ids") or [],
							)
						if include_knowledge:
							try:
								from trivia_sync.integrations.knowledge import link_knowledge_concepts

								extracted = adapter.extract_knowledge_concepts({**payload, "topics": data.get("topics") or []})
								link_knowledge_concepts(doc, extracted["concepts"], ai_model=extracted["model"])
							except Exception:
								pass
						_refresh_question_html(doc)
						doc.save(ignore_permissions=True)
						result["enriched"] += 1
			except Exception:
				result["errors"] += 1
				frappe.log_error(frappe.get_traceback(), f"Trivia Sync · AI batch ({mode}) · {name}")
			result["processed"] += 1
			run.records_created = result["enriched"]
			run.records_skipped = result["skipped"]
			run.records_errors = result["errors"]
			run.save(ignore_permissions=True)
			frappe.db.commit()
		run.status = "Partial" if result["errors"] else "Completed"
		return result
	except Exception:
		run.status = "Failed"
		run.error_log = frappe.get_traceback()
		frappe.log_error(frappe.get_traceback(), f"Trivia Sync · AI batch ({mode})")
		raise
	finally:
		run.finished_at = frappe.utils.now_datetime()
		run.save(ignore_permissions=True)
		frappe.db.commit()


def _build_student_reflection_messages(
	question: dict[str, Any],
	teacher_comment: str,
	student_answer: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
	schema = {
		"type": "object",
		"additionalProperties": False,
		"required": ["verdict", "feedback", "key_takeaway"],
		"properties": {
			"verdict": {
				"type": "string",
				"enum": ["Correta", "Parcialmente correta", "Incorreta", "Reflexão registrada"],
			},
			"feedback": {"type": "string", "minLength": 20},
			"key_takeaway": {"type": "string", "minLength": 10},
		},
	}
	payload = {
		"questao": {
			"codigo": question.get("qcode"),
			"materia": question.get("materia"),
			"assunto": question.get("assunto"),
			"banca": question.get("banca"),
			"ano": question.get("ano"),
			"enunciado": question.get("enunciado"),
		},
		"comentario_do_professor": teacher_comment,
		"resposta_do_aluno": student_answer,
	}
	messages = [
		{
			"role": "system",
			"content": (
				"Você é Athena, tutora pedagógica especialista em concursos públicos brasileiros. "
				"O professor deixou um Comentário do Professor que pode conter uma pergunta retórica, exercício de cálculo ou desafio de fixação para o aluno. "
				"Um aluno decidiu responder a esse desafio. Avalie a resposta do aluno com clareza, cordialidade e rigor técnico, "
				"tomando o Comentário do Professor e o ordenamento jurídico/teórico aplicável como referência. "
				"Quando houver cálculo ou comparação entre regras/incisos, mostre o passo a passo de forma didática. "
				"Se o aluno acertou, confirme e reforce o raciocínio; se errou ou acertou parcialmente, aponte exatamente onde está o ajuste sem desanimá-lo. "
				"Se a resposta for uma reflexão aberta sem gabarito único, use o veredito 'Reflexão registrada' e comente construtivamente. "
				"Responda sempre em português brasileiro."
			),
		},
		{"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
	]
	return messages, schema


def get_question_deep_dive(question_name: str) -> dict[str, Any]:
	"""Return teacher commentary, question context, published knowledge links, and the logged-in student's reflection history."""
	user = getattr(getattr(frappe, "session", None), "user", None)
	if not user or user == "Guest":
		frappe.throw("Faça login para acessar o aprofundamento da questão.", frappe.PermissionError)
	if not question_name or not frappe.db.exists("LMS Question", question_name):
		frappe.throw("Questão não encontrada.", frappe.DoesNotExistError)

	doc = frappe.get_doc("LMS Question", question_name)
	teacher_comment = getattr(doc, "trivia_general_explanation", None) or ""
	if hasattr(frappe, "utils") and hasattr(frappe.utils, "sanitize_html"):
		teacher_comment = frappe.utils.sanitize_html(teacher_comment)
		enunciado_html = frappe.utils.sanitize_html(strip_question_embeds(getattr(doc, "question", "") or ""))
	else:
		enunciado_html = strip_question_embeds(getattr(doc, "question", "") or "")

	supporting_html = _supporting_text_content(doc)
	if supporting_html and hasattr(frappe, "utils") and hasattr(frappe.utils, "sanitize_html"):
		supporting_html = frappe.utils.sanitize_html(supporting_html)

	knowledge_pages = []
	try:
		from trivia_sync.integrations.knowledge import get_question_knowledge_pages

		knowledge_pages = [
			p for p in (get_question_knowledge_pages(doc.name) or [])
			if p.get("status") == "Published" and p.get("slug")
		]
	except Exception:
		knowledge_pages = []

	reflections = []
	if frappe.db.exists("DocType", "Trivia Student Reflection"):
		reflections = frappe.get_all(
			"Trivia Student Reflection",
			filters={"question": doc.name, "user": user},
			fields=["name", "student_answer", "verdict", "athena_feedback", "key_takeaway", "athena_model", "submitted_at"],
			order_by="submitted_at desc, creation desc",
			limit=20,
		) or []

	return {
		"question_name": doc.name,
		"qcode": getattr(doc, "trivia_qcode", None) or doc.name,
		"title": getattr(doc, "trivia_title", None) or doc.name,
		"materia": getattr(doc, "trivia_materia", None) or "",
		"assunto": getattr(doc, "trivia_assunto", None) or "",
		"banca": getattr(doc, "trivia_banca", None) or "",
		"ano": getattr(doc, "trivia_ano", None) or "",
		"deprecated": bool(int(getattr(doc, "trivia_deprecated", 0) or 0)),
		"deprecated_law": getattr(doc, "trivia_deprecated_law", None) or "",
		"replacement_law": getattr(doc, "trivia_replacement_law", None) or "",
		"deprecation_note": getattr(doc, "trivia_deprecation_note", None) or "",
		"supporting_html": supporting_html,
		"enunciado_html": enunciado_html,
		"teacher_comment_html": teacher_comment,
		"knowledge_pages": knowledge_pages,
		"reflections": reflections,
	}


def submit_student_reflection(question_name: str, student_answer: str) -> dict[str, Any]:
	"""Grade a logged-in student's answer to the teacher's challenge with Athena and persist the attempt."""
	user = getattr(getattr(frappe, "session", None), "user", None)
	if not user or user == "Guest":
		frappe.throw("Faça login para enviar sua resposta à Athena.", frappe.PermissionError)
	answer = str(student_answer or "").strip()
	if not answer:
		frappe.throw("Escreva sua resposta antes de enviar para a Athena.")
	if len(answer) > 6000:
		frappe.throw("Sua resposta excedeu o limite máximo de 6.000 caracteres.")
	if not question_name or not frappe.db.exists("LMS Question", question_name):
		frappe.throw("Questão não encontrada.", frappe.DoesNotExistError)

	doc = frappe.get_doc("LMS Question", question_name)
	teacher_comment = str(getattr(doc, "trivia_general_explanation", None) or "").strip()
	if not teacher_comment:
		frappe.throw("Esta questão ainda não possui Comentário do Professor para correção.")

	payload = _question_payload(doc, include_teacher_comment=True)
	adapter = get_ai_adapter()
	graded = adapter.grade_student_reflection(
		payload,
		teacher_comment=teacher_comment,
		student_answer=answer,
	)

	feedback_text = graded["feedback"]
	if hasattr(frappe, "utils") and hasattr(frappe.utils, "sanitize_html"):
		feedback_text = frappe.utils.sanitize_html(feedback_text)

	submitted_at = frappe.utils.now_datetime()
	saved_name = None
	if frappe.db.exists("DocType", "Trivia Student Reflection"):
		reflection = frappe.new_doc("Trivia Student Reflection")
		reflection.question = doc.name
		reflection.user = user
		reflection.student_answer = answer
		reflection.verdict = graded["verdict"]
		reflection.athena_feedback = feedback_text
		reflection.key_takeaway = graded.get("key_takeaway") or ""
		reflection.athena_model = graded.get("model") or ""
		reflection.submitted_at = submitted_at
		reflection.insert(ignore_permissions=True)
		saved_name = reflection.name

	return {
		"name": saved_name,
		"question": doc.name,
		"student_answer": answer,
		"verdict": graded["verdict"],
		"athena_feedback": feedback_text,
		"key_takeaway": graded.get("key_takeaway") or "",
		"athena_model": graded.get("model") or "",
		"submitted_at": str(submitted_at),
	}


def enrich_pending_questions():
	return enrich_questions_batch(mode="full")
