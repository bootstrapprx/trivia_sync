import hashlib
import json
import re
import time
import traceback
import unicodedata
from typing import Any

import frappe

from trivia_sync.integrations.ai_enricher import AIEnrichmentError, get_ai_adapter
from trivia_sync.integrations.background import create_sync_run, dispatch_background_job
from trivia_sync.integrations.lms_questions import (
	extract_lms_question_options,
	strip_question_embeds,
)

whitelist = getattr(frappe, "whitelist", lambda: (lambda function: function))


COURSE_ROLES = ("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator")
VALID_LEVELS = {"mais", "180", "360"}
DEFAULT_COVER_IMAGE = "/assets/trivia_sync/images/athena_course_cover.svg"
SAVEPOINT = "athena_course_build"
LOCK_TTL = 2 * 60 * 60
RESUME_TTL = 24 * 60 * 60

LEVEL_GUIDANCE = {
	"mais": "Curso enxuto e direto ao ponto (1 capítulo, 2 a 3 aulas objetivas focadas na regra essencial e aplicação rápida).",
	"180": "Curso intermediário completo (1 a 2 capítulos, 3 a 5 aulas cobrindo base conceitual, regra normativa, exemplos resolvidos e pegadinhas).",
	"360": "Curso aprofundado de domínio total (2 a 3 capítulos, 5 a 8 aulas cobrindo fundamentos, doutrina/jurisprudência/norma, casos práticos e armadilhas de banca).",
}

# (min, max) — alinhado ao LEVEL_GUIDANCE; o schema e o clamp usam estes valores.
LEVEL_LIMITS = {
	"mais": {"chapters": (1, 1), "lessons_per_chapter": (1, 3), "total_lessons": (2, 3)},
	"180": {"chapters": (1, 2), "lessons_per_chapter": (1, 5), "total_lessons": (3, 5)},
	"360": {"chapters": (2, 3), "lessons_per_chapter": (1, 8), "total_lessons": (5, 8)},
}

_STOPWORDS = {
	"como",
	"para",
	"sobre",
	"qual",
	"quais",
	"quando",
	"onde",
	"porque",
	"pela",
	"pelo",
	"pelos",
	"pelas",
	"uma",
	"uns",
	"umas",
	"dos",
	"das",
	"nos",
	"nas",
	"com",
	"sem",
	"entre",
	"este",
	"esta",
	"esse",
	"essa",
	"isso",
	"aquilo",
	"seria",
	"foram",
	"seja",
	"crie",
	"criar",
	"curso",
	"aula",
	"aulas",
	"baseado",
	"questao",
}

# Checagem determinística de vazamento de gabarito (item 12). Heurística: ajuste ao seu corpus.
_LEAK_PATTERNS = [
	re.compile(r"\bgabarito\b", re.I),
	re.compile(
		r"\b(alternativa|letra|item|op[cç][aã]o)\s*\(?[a-e]\)?\s*(é|e|seria)\s+(a\s+)?(correta|certa|verdadeira)",
		re.I,
	),
	re.compile(r"\b(resposta|alternativa)\s+correta\s+(é|e)\b", re.I),
	re.compile(r"\bcorreta\s*[:\-–]\s*\(?[a-e]\)?\b", re.I),
]


class _ContentRejected(Exception):
	"""Resposta do LLM válida no schema, mas reprovada por regra de conteúdo."""


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------


def _require_course_role() -> None:
	frappe.only_for(COURSE_ROLES)


def _normalize(text: str) -> str:
	decomposed = unicodedata.normalize("NFKD", str(text or ""))
	return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _sanitize_html(raw_html: str) -> str:
	"""Falha fechado: se o sanitizador não rodar, o conteúdo é descartado."""
	text = str(raw_html or "").strip()
	if not text:
		return ""
	try:
		from frappe.utils.html_utils import sanitize_html

		return sanitize_html(text, always_sanitize=True)
	except ImportError:
		if hasattr(frappe, "utils") and hasattr(frappe.utils, "sanitize_html"):
			return frappe.utils.sanitize_html(text)
		frappe.log_error(traceback.format_exc(), "Trivia Sync · sanitize_html indisponível")
		raise AIEnrichmentError("Falha ao sanitizar o HTML gerado; conteúdo descartado por segurança.")
	except Exception:
		frappe.log_error(traceback.format_exc(), "Trivia Sync · sanitize_html falhou")
		raise AIEnrichmentError("Falha ao sanitizar o HTML gerado; conteúdo descartado por segurança.")


def _plain_snippet(raw_html: str, max_len: int = 240) -> str:
	plain = re.sub(r"<[^>]+>", " ", str(raw_html or ""))
	plain = re.sub(r"\s+", " ", plain).strip()
	if len(plain) > max_len:
		return plain[: max_len - 1].rstrip() + "…"
	return plain


def _extract_keywords(text: str, max_terms: int = 6) -> list[str]:
	"""Keywords sem acento (a collation utf8mb4_unicode_ci do MariaDB é accent-insensitive no LIKE)."""
	words = re.findall(r"[a-z0-9]{4,}", _normalize(text))
	seen: list[str] = []
	for w in words:
		if w not in _STOPWORDS and w not in seen:
			seen.append(w)
		if len(seen) >= max_terms:
			break
	return seen


def _load_methodology(methodology: str | None) -> str:
	if methodology and frappe.db.exists("Trivia Methodology", methodology):
		m_doc = frappe.get_doc("Trivia Methodology", methodology)
		if getattr(m_doc, "active", 1):
			return str(getattr(m_doc, "instructions", "") or "").strip()
	return ""


def _clamp_blueprint(blueprint: dict[str, Any], level: str) -> dict[str, Any]:
	lim = LEVEL_LIMITS[level]
	chapters = (blueprint.get("chapters") or [])[: lim["chapters"][1]]
	remaining = lim["total_lessons"][1]
	for ch in chapters:
		keep = max(0, min(lim["lessons_per_chapter"][1], remaining))
		ch["lessons"] = (ch.get("lessons") or [])[:keep]
		remaining -= len(ch["lessons"])
	blueprint["chapters"] = [c for c in chapters if c.get("lessons")]
	return blueprint


# ---------------------------------------------------------------------------
# LLM: retry/backoff + validação pós-geração
# ---------------------------------------------------------------------------


def _chat_json_retry(adapter, messages, name, schema, max_tokens, attempts: int = 3, validator=None):
	last_err: Exception | None = None
	current = list(messages)
	for attempt in range(1, attempts + 1):
		backoff = True
		try:
			data = adapter._chat_json(current, name, schema, max_tokens)
			if validator:
				problem = validator(data)
				if problem:
					raise _ContentRejected(problem)
			return data
		except _ContentRejected as exc:
			last_err = exc
			backoff = False
			current = list(messages) + [
				{
					"role": "user",
					"content": f"Sua resposta anterior foi rejeitada: {exc}. Reescreva corrigindo exatamente isso.",
				}
			]
		except Exception as exc:
			last_err = exc
			frappe.log_error(traceback.format_exc(), f"Trivia Sync · {name} tentativa {attempt}")
		if backoff and attempt < attempts:
			time.sleep(min(2**attempt, 20))
	raise AIEnrichmentError(f"{name}: falhou após {attempts} tentativas ({last_err}).")


def _validate_lesson(data: dict[str, Any]) -> str | None:
	html = str((data or {}).get("html_content") or "")
	plain = _plain_snippet(html, 10**6)
	if len(plain) < 400:
		return "o conteúdo da aula ficou curto demais (mínimo de ~400 caracteres de texto)"
	for pattern in _LEAK_PATTERNS:
		m = pattern.search(plain)
		if m:
			return f"a aula não pode mencionar gabarito ou alternativa correta (trecho: '{m.group(0)}')"
	return None


# ---------------------------------------------------------------------------
# Busca de contexto (ranqueada, poucas queries, erros logados)
# ---------------------------------------------------------------------------


def _query_bank(base_filters, or_filters, fields, limit, label) -> list[dict[str, Any]]:
	if not or_filters:
		return []
	try:
		return (
			frappe.get_all(
				"LMS Question",
				filters=base_filters,
				or_filters=or_filters,
				fields=fields,
				order_by="modified desc",
				limit_page_length=limit,
			)
			or []
		)
	except Exception:
		frappe.log_error(traceback.format_exc(), f"Trivia Sync · busca de questões ({label})")
		return []


def _find_related_bank_questions(
	seed_doc=None,
	prompt: str = "",
	subject: str | None = None,
	topic: str | None = None,
	limit: int = 20,
) -> list[dict[str, Any]]:
	"""Ready, não depreciadas, ranqueadas: tópico > assunto > matéria/subject > keywords."""
	fields = [
		"name",
		"trivia_qcode",
		"trivia_title",
		"question",
		"trivia_materia",
		"trivia_assunto",
		"trivia_banca",
		"trivia_ano",
		"trivia_deprecated",
		"trivia_answer_key_pending",
		"trivia_topic_link",
		"trivia_subject_link",
	]
	eff_topic = topic or (getattr(seed_doc, "trivia_topic_link", None) if seed_doc else None)
	eff_subject = subject or (getattr(seed_doc, "trivia_subject_link", None) if seed_doc else None)
	seed_assunto = getattr(seed_doc, "trivia_assunto", None) if seed_doc else None
	seed_materia = getattr(seed_doc, "trivia_materia", None) if seed_doc else None
	keywords = _extract_keywords(prompt)

	base_filters: dict[str, Any] = {
		"type": "Choices",
		"trivia_status": "Ready",
		"trivia_deprecated": ["!=", 1],
		"trivia_answer_key_pending": ["!=", 1],
	}

	structural: list[list[Any]] = []
	if eff_topic:
		structural.append(["trivia_topic_link", "=", eff_topic])
	if seed_assunto:
		structural.append(["trivia_assunto", "=", seed_assunto])
	if eff_subject:
		structural.append(["trivia_subject_link", "=", eff_subject])
	if seed_materia:
		structural.append(["trivia_materia", "=", seed_materia])

	by_keyword: list[list[Any]] = []
	for kw in keywords[:4]:
		for field in ("trivia_title", "trivia_assunto", "question"):
			by_keyword.append([field, "like", f"%{kw}%"])

	pool: dict[str, dict[str, Any]] = {}
	for label, ors in (("estrutural", structural), ("keywords", by_keyword)):
		for row in _query_bank(base_filters, ors, fields, 100, label):
			pool.setdefault(row["name"], row)

	def _score(row: dict[str, Any]) -> int:
		score = 0
		if eff_topic and row.get("trivia_topic_link") == eff_topic:
			score += 100
		if seed_assunto and row.get("trivia_assunto") == seed_assunto:
			score += 60
		if eff_subject and row.get("trivia_subject_link") == eff_subject:
			score += 40
		if seed_materia and row.get("trivia_materia") == seed_materia:
			score += 20
		hay = _normalize(
			" ".join(str(row.get(k) or "") for k in ("trivia_title", "trivia_assunto", "question"))
		)
		return score + 5 * sum(1 for kw in keywords if kw in hay)

	ranked = sorted(pool.values(), key=_score, reverse=True)

	results: list[dict[str, Any]] = []
	seen: set[str] = set()

	def _add(row: dict[str, Any]) -> None:
		name = row.get("name")
		if not name or name in seen:
			return
		seen.add(name)
		clean_q = strip_question_embeds(row.get("question") or "")
		results.append(
			{
				"name": name,
				"qcode": row.get("trivia_qcode") or name,
				"title": row.get("trivia_title") or _plain_snippet(clean_q, 110) or name,
				"enunciado": _plain_snippet(clean_q, 280),
				"materia": row.get("trivia_materia") or "",
				"assunto": row.get("trivia_assunto") or "",
				"banca": row.get("trivia_banca") or "",
				"ano": row.get("trivia_ano") or "",
				"deprecated": bool(int(row.get("trivia_deprecated") or 0)),
			}
		)

	if seed_doc is not None and not int(getattr(seed_doc, "trivia_answer_key_pending", 0) or 0):
		_add(
			{
				"name": seed_doc.name,
				"trivia_qcode": getattr(seed_doc, "trivia_qcode", None),
				"trivia_title": getattr(seed_doc, "trivia_title", None),
				"question": getattr(seed_doc, "question", None),
				"trivia_materia": seed_materia,
				"trivia_assunto": seed_assunto,
				"trivia_banca": getattr(seed_doc, "trivia_banca", None),
				"trivia_ano": getattr(seed_doc, "trivia_ano", None),
				"trivia_deprecated": getattr(seed_doc, "trivia_deprecated", 0),
			}
		)
	for row in ranked:
		if len(results) >= limit:
			break
		_add(row)
	return results[:limit]


def _gather_knowledge_context(seed_doc=None, keywords: list[str] | None = None) -> list[dict[str, str]]:
	pages: list[dict[str, str]] = []
	seen: set[str] = set()
	page_fields = ["name", "title", "summary", "explanation", "exam_traps"]

	def _append_page(p: dict[str, Any]) -> None:
		name = p.get("name")
		if not name or name in seen:
			return
		seen.add(name)
		pages.append(
			{
				"title": str(p.get("title") or ""),
				"summary": str(p.get("summary") or ""),
				"explanation": _plain_snippet(p.get("explanation") or "", 600),
				"exam_traps": _plain_snippet(p.get("exam_traps") or "", 400),
			}
		)

	if seed_doc is not None:
		linked = [
			getattr(r, "knowledge_page", None) if not isinstance(r, dict) else r.get("knowledge_page")
			for r in (getattr(seed_doc, "trivia_knowledge_pages", None) or [])
		]
		linked = [n for n in linked if n]
		if linked:
			try:
				for r in (
					frappe.get_all(
						"Trivia Knowledge Page", filters={"name": ["in", linked]}, fields=page_fields
					)
					or []
				):
					_append_page(r)
			except Exception:
				frappe.log_error(traceback.format_exc(), "Trivia Sync · páginas de conhecimento vinculadas")

	kws = (keywords or [])[:3]
	if kws and len(pages) < 6:
		try:
			for r in (
				frappe.get_all(
					"Trivia Knowledge Page",
					filters={"status": "Published"},
					or_filters=[["title", "like", f"%{kw}%"] for kw in kws],
					fields=page_fields,
					limit_page_length=6,
				)
				or []
			):
				_append_page(r)
		except Exception:
			frappe.log_error(traceback.format_exc(), "Trivia Sync · páginas de conhecimento por keyword")

	return pages[:6]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def _build_course_blueprint_messages(context_payload: dict[str, Any], level: str):
	lim = LEVEL_LIMITS[level]
	schema = {
		"type": "object",
		"additionalProperties": False,
		"required": [
			"course_title",
			"short_introduction",
			"course_description",
			"chapters",
			"quiz_title",
			"recommended_question_names",
		],
		"properties": {
			"course_title": {"type": "string", "minLength": 8, "maxLength": 120},
			"short_introduction": {"type": "string", "minLength": 15, "maxLength": 280},
			"course_description": {"type": "string", "minLength": 30, "maxLength": 1500},
			"chapters": {
				"type": "array",
				"minItems": lim["chapters"][0],
				"maxItems": lim["chapters"][1],
				"items": {
					"type": "object",
					"additionalProperties": False,
					"required": ["title", "description", "lessons"],
					"properties": {
						"title": {"type": "string", "minLength": 5, "maxLength": 120},
						"description": {"type": "string", "minLength": 10, "maxLength": 300},
						"lessons": {
							"type": "array",
							"minItems": lim["lessons_per_chapter"][0],
							"maxItems": lim["lessons_per_chapter"][1],
							"items": {
								"type": "object",
								"additionalProperties": False,
								"required": ["title", "objective", "key_points"],
								"properties": {
									"title": {"type": "string", "minLength": 5, "maxLength": 120},
									"objective": {"type": "string", "minLength": 10, "maxLength": 300},
									"key_points": {
										"type": "array",
										"minItems": 2,
										"maxItems": 6,
										"items": {"type": "string"},
									},
								},
							},
						},
					},
				},
			},
			"quiz_title": {"type": "string", "minLength": 5, "maxLength": 120},
			"recommended_question_names": {"type": "array", "maxItems": 15, "items": {"type": "string"}},
		},
	}
	messages = [
		{
			"role": "system",
			"content": (
				"Você é Athena, arquiteta pedagógica especialista em concursos públicos brasileiros no Frappe LMS. "
				"Sua missão é estruturar um curso didático progressivo a partir de uma questão-semente e/ou de uma pergunta norteadora do professor. "
				f"Diretriz de escopo para o nível '{level}': {LEVEL_GUIDANCE[level]} "
				f"Totalizando entre {lim['total_lessons'][0]} e {lim['total_lessons'][1]} aulas teóricas. "
				"Organize os capítulos e aulas em ordem lógica de aprendizagem: "
				"(1) conceitos pré-requisitos e fundamentos, (2) regra normativa/teórica detalhada, "
				"(3) aplicação prática / cálculos / distinções críticas, e (4) pegadinhas recorrentes da banca. "
				"Se a questão-semente for depreciada (legislação revogada), inclua o paralelo histórico 'como era vs. como é hoje na norma vigente'. "
				"Em recommended_question_names, selecione APENAS valores exatos do campo 'name' presentes em questoes_disponiveis_no_banco que tenham aderência direta ao curso (ou lista vazia se nenhuma se aplicar). "
				"Não inclua a aula de Quiz dentro da lista de lessons teóricas (o sistema adicionará automaticamente a aula prática com o LMS Quiz ao final). "
				"Responda exclusivamente em português brasileiro no JSON Schema solicitado."
			),
		},
		{"role": "user", "content": json.dumps(context_payload, ensure_ascii=False)},
	]
	return messages, schema


def _build_lesson_writer_messages(
	course_title: str,
	chapter_title: str,
	lesson_spec: dict[str, Any],
	level: str,
	methodology_text: str,
	pedagogical_context: dict[str, Any],
	syllabus: list[dict[str, Any]],
	previous_lessons: list[dict[str, str]],
):
	schema = {
		"type": "object",
		"additionalProperties": False,
		"required": ["html_content", "summary"],
		"properties": {
			"html_content": {"type": "string", "minLength": 80},
			"summary": {"type": "string", "minLength": 15, "maxLength": 350},
		},
	}
	payload = {
		"curso": course_title,
		"capitulo": chapter_title,
		"aula": lesson_spec,
		"nivel": level,
		"metodologia": methodology_text,
		"contexto_pedagogico": pedagogical_context,
		"ementa_completa": syllabus,
		"aulas_anteriores": previous_lessons[-6:],
	}
	messages = [
		{
			"role": "system",
			"content": (
				"Você é Athena, professora especialista em concursos públicos brasileiros redigindo uma aula completa para o Frappe LMS. "
				"Escreva html_content em HTML limpo e bem estruturado (<h2>, <h3>, <p>, <ul>, <li>, <strong>, <blockquote>, <table> quando útil para quadros comparativos ou lançamentos). "
				"Ensine com clareza profunda todos os key_points da aula, trazendo fundamentação legal/teórica correta, exemplos inéditos resolvidos passo a passo e alertas de pegadinhas de prova. "
				"Use 'ementa_completa' para saber onde esta aula se encaixa e 'aulas_anteriores' para NÃO repetir o que já foi explicado: "
				"retome em uma frase, faça a transição e avance. Não antecipe conteúdo de aulas posteriores. "
				"REGRA CRÍTICA: NUNCA entregue nem cite o gabarito literal das questões do banco, nem use a palavra 'gabarito' "
				"(o aluno resolverá essas questões no Quiz final do curso). "
				"Se houver legislação revogada/substituída no contexto, destaque com clareza 'Como era' vs. 'Como é hoje'. "
				"Responda exclusivamente em português brasileiro no JSON Schema solicitado."
			),
		},
		{"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
	]
	return messages, schema


# ---------------------------------------------------------------------------
# Estágio 1: ementa (síncrono, uma chamada de LLM)
# ---------------------------------------------------------------------------


def plan_course_blueprint(
	seed_question: str | None = None,
	prompt: str = "",
	level: str = "180",
	methodology: str | None = None,
	use_teacher_materials: bool = True,
	subject: str | None = None,
	topic: str | None = None,
) -> dict[str, Any]:
	"""Stage 1: Build an editable Athena course blueprint + matched Ready bank questions."""
	_require_course_role()
	clean_level = level if level in VALID_LEVELS else "180"
	clean_prompt = str(prompt or "").strip()

	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Ative a Athena em Trivia Sync Settings antes de planejar um curso.")

	seed_doc = None
	if seed_question:
		if not frappe.db.exists("LMS Question", seed_question):
			frappe.throw(f"Questão {seed_question} não encontrada.")
		seed_doc = frappe.get_doc("LMS Question", seed_question)

	if not seed_doc and not clean_prompt:
		frappe.throw("Informe uma questão-base ou escreva uma pergunta/tema norteador para a Athena.")

	methodology_text = _load_methodology(methodology)

	seed_payload: dict[str, Any] = {}
	if seed_doc is not None:
		options, correct, _ = extract_lms_question_options(seed_doc)
		seed_payload = {
			"name": seed_doc.name,
			"qcode": getattr(seed_doc, "trivia_qcode", None) or seed_doc.name,
			"title": getattr(seed_doc, "trivia_title", None) or "",
			"enunciado": strip_question_embeds(getattr(seed_doc, "question", "") or ""),
			"alternativas": options,
			"gabarito": [] if getattr(seed_doc, "trivia_answer_key_pending", 0) else correct,
			"materia": getattr(seed_doc, "trivia_materia", None) or "",
			"assunto": getattr(seed_doc, "trivia_assunto", None) or "",
			"banca": getattr(seed_doc, "trivia_banca", None) or "",
			"ano": getattr(seed_doc, "trivia_ano", None) or "",
			"depreciada": bool(int(getattr(seed_doc, "trivia_deprecated", 0) or 0)),
			"norma_revogada": getattr(seed_doc, "trivia_deprecated_law", None) or "",
			"substituida_por": getattr(seed_doc, "trivia_replacement_law", None) or "",
			"resumo_mudanca": getattr(seed_doc, "trivia_deprecation_note", None) or "",
		}
		if use_teacher_materials and getattr(seed_doc, "trivia_general_explanation", None):
			seed_payload["comentario_do_professor"] = _plain_snippet(
				seed_doc.trivia_general_explanation, 2500
			)

	keywords = _extract_keywords(
		f"{clean_prompt} {seed_payload.get('title', '')} {seed_payload.get('assunto', '')} {seed_payload.get('materia', '')}"
	)
	bank_candidates = _find_related_bank_questions(
		seed_doc=seed_doc, prompt=clean_prompt, subject=subject, topic=topic, limit=20
	)
	knowledge_pages = (
		_gather_knowledge_context(seed_doc=seed_doc, keywords=keywords) if use_teacher_materials else []
	)

	context_payload = {
		"pergunta_ou_instrucao_do_professor": clean_prompt,
		"questao_semente": seed_payload or None,
		"metodologia": methodology_text,
		"paginas_de_conhecimento": knowledge_pages,
		"questoes_disponiveis_no_banco": [
			{
				"name": q["name"],
				"qcode": q["qcode"],
				"title": q["title"],
				"materia": q["materia"],
				"assunto": q["assunto"],
			}
			for q in bank_candidates
		],
	}

	adapter = get_ai_adapter(settings)
	messages, schema = _build_course_blueprint_messages(context_payload, clean_level)
	blueprint = _chat_json_retry(adapter, messages, "athena_course_blueprint", schema, 3500)
	blueprint = _clamp_blueprint(blueprint, clean_level)

	valid_names = {q["name"] for q in bank_candidates}
	rec_names = [n for n in (blueprint.get("recommended_question_names") or []) if n in valid_names]
	if not rec_names and bank_candidates:
		rec_names = [q["name"] for q in bank_candidates[: min(8, len(bank_candidates))]]
	elif seed_doc and seed_doc.name in valid_names and seed_doc.name not in rec_names:
		rec_names.insert(0, seed_doc.name)

	blueprint["recommended_question_names"] = list(dict.fromkeys(rec_names))
	return {
		"blueprint": blueprint,
		"bank_candidates": bank_candidates,
		"level": clean_level,
		"model": adapter.model,
	}


# ---------------------------------------------------------------------------
# Estágio 2: geração (fila `long`) + materialização atômica
# ---------------------------------------------------------------------------


def _apply_safe_course_defaults(course, owner_user: str) -> None:
	"""Populate Frappe LMS v16 mandatory fields safely on a new draft LMS Course."""
	course.published = 0
	if hasattr(course, "upcoming"):
		course.upcoming = 0
	if hasattr(course, "paid_course"):
		course.paid_course = 0

	try:
		meta = frappe.get_meta("LMS Course") if hasattr(frappe, "get_meta") else None
	except Exception:
		meta = None

	if meta:
		if meta.get_field("instructors") and not getattr(course, "instructors", None):
			course.append("instructors", {"instructor": owner_user})
		img_field = meta.get_field("image")
		if img_field and getattr(img_field, "reqd", 0) and not getattr(course, "image", None):
			course.image = DEFAULT_COVER_IMAGE
	else:
		if hasattr(course, "instructors") and not getattr(course, "instructors", None):
			course.append("instructors", {"instructor": owner_user})
	if not getattr(course, "image", None):
		course.image = DEFAULT_COVER_IMAGE


def _unique_quiz_title(base_title: str) -> str:
	clean = re.sub(r"\s+", " ", str(base_title or "Quiz de Fixação")).strip()[:125]
	if not frappe.db.exists("LMS Quiz", {"title": clean}):
		return clean
	for idx in range(2, 50):
		candidate = f"{clean[:118]} · {idx}"
		if not frappe.db.exists("LMS Quiz", {"title": candidate}):
			return candidate
	return f"{clean[:110]} · {frappe.generate_hash(length=6)}"


def _fingerprint(blueprint: dict[str, Any], target_course, seed_question, level: str) -> str:
	raw = json.dumps(
		{
			"target": target_course,
			"seed": seed_question,
			"level": level,
			"title": blueprint.get("course_title"),
			"chapters": [
				[c.get("title"), [l.get("title") for l in (c.get("lessons") or [])]]
				for c in (blueprint.get("chapters") or [])
			],
		},
		sort_keys=True,
		ensure_ascii=False,
	)
	return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _lock_key(fp: str) -> str:
	return f"trivia_sync:course_lock:{fp}"


def _payload_key(run_name: str) -> str:
	return f"trivia_sync:course_payload:{run_name}"


def _lessons_key(run_name: str) -> str:
	return f"trivia_sync:course_lessons:{run_name}"


def _progress(run_name: str, percent: float, text: str) -> None:
	frappe.db.set_value("Trivia Sync Run", run_name, "current_operation", text[:140], update_modified=False)
	frappe.db.commit()
	if hasattr(frappe, "publish_progress"):
		try:
			frappe.publish_progress(
				percent,
				title="Athena · Gerando curso",
				description=text,
				doctype="Trivia Sync Run",
				docname=run_name,
			)
		except Exception:
			pass


def _pedagogical_context(seed_doc, prompt: str, use_teacher_materials: bool) -> dict[str, Any]:
	ctx: dict[str, Any] = {"orientacao_do_professor": str(prompt or "").strip()}
	if seed_doc is not None:
		ctx["questao_referencia"] = {
			"enunciado": strip_question_embeds(getattr(seed_doc, "question", "") or ""),
			"materia": getattr(seed_doc, "trivia_materia", None) or "",
			"assunto": getattr(seed_doc, "trivia_assunto", None) or "",
			"depreciada": bool(int(getattr(seed_doc, "trivia_deprecated", 0) or 0)),
			"norma_revogada": getattr(seed_doc, "trivia_deprecated_law", None) or "",
			"substituida_por": getattr(seed_doc, "trivia_replacement_law", None) or "",
		}
		if use_teacher_materials and getattr(seed_doc, "trivia_general_explanation", None):
			ctx["comentario_do_professor"] = _plain_snippet(seed_doc.trivia_general_explanation, 2500)
	if use_teacher_materials:
		ctx["paginas_de_conhecimento"] = _gather_knowledge_context(seed_doc=seed_doc)
	return ctx


def _materialize_course(p: dict[str, Any], course_title: str, generated: dict[str, Any]) -> dict[str, Any]:
	"""Fase 2: grava tudo numa única transação. Qualquer erro faz rollback total."""
	blueprint = p["blueprint"]
	owner_user = p["owner_user"]
	target_course = p.get("target_course")
	chapters_created: list[str] = []
	lessons_created: list[str] = []
	quiz_name: str | None = None

	frappe.db.savepoint(SAVEPOINT)
	try:
		if target_course:
			course = frappe.get_doc("LMS Course", target_course)
			course_created = False
		else:
			course = frappe.new_doc("LMS Course")
			course.title = course_title
			course.short_introduction = str(
				blueprint.get("short_introduction") or "Curso estruturado pela Athena."
			).strip()[:280]
			course.description = _sanitize_html(
				blueprint.get("course_description") or f"<p>{course.short_introduction}</p>"
			)
			_apply_safe_course_defaults(course, owner_user)
			course.insert(ignore_permissions=True)
			course_created = True

		last_chapter_doc = None
		for ci, ch_spec in enumerate(blueprint["chapters"]):
			ch_title = str(ch_spec.get("title") or "Capítulo").strip()[:135]
			chapter_doc = frappe.new_doc("Course Chapter")
			chapter_doc.title = ch_title
			chapter_doc.course = course.name
			if hasattr(chapter_doc, "chapter_description") and ch_spec.get("description"):
				chapter_doc.chapter_description = str(ch_spec["description"]).strip()[:300]
			chapter_doc.insert(ignore_permissions=True)
			chapters_created.append(chapter_doc.name)

			course.append("chapters", {"chapter": chapter_doc.name})
			course.save(ignore_permissions=True)

			for li, les_spec in enumerate(ch_spec.get("lessons") or []):
				gen = generated[f"{ci}.{li}"]
				lesson_doc = frappe.new_doc("Course Lesson")
				lesson_doc.title = str(les_spec.get("title") or "Aula").strip()[:135]
				lesson_doc.chapter = chapter_doc.name
				lesson_doc.course = course.name
				if hasattr(lesson_doc, "include_in_preview"):
					lesson_doc.include_in_preview = 0
				lesson_doc.body = _sanitize_html(gen["html_content"])
				lesson_doc.insert(ignore_permissions=True)
				lessons_created.append(lesson_doc.name)
				chapter_doc.append("lessons", {"lesson": lesson_doc.name})

			chapter_doc.save(ignore_permissions=True)
			last_chapter_doc = chapter_doc

		selected = list(
			dict.fromkeys(
				str(q).strip()
				for q in (blueprint.get("recommended_question_names") or [])
				if str(q).strip() and frappe.db.exists("LMS Question", str(q).strip())
			)
		)

		if p.get("include_quiz", True) and selected and last_chapter_doc is not None:
			quiz_title = _unique_quiz_title(blueprint.get("quiz_title") or f"Fixação · {course.title}")
			quiz_doc = frappe.new_doc("LMS Quiz")
			quiz_doc.title = quiz_title
			quiz_doc.show_answers = 1
			quiz_doc.passing_percentage = 70
			if hasattr(quiz_doc, "course"):
				quiz_doc.course = course.name

			total_marks = 0
			for q_name in selected:
				q_doc = frappe.get_doc("LMS Question", q_name)
				q_marks = (
					0
					if int(getattr(q_doc, "trivia_deprecated", 0) or 0)
					else max(1, int(getattr(q_doc, "marks", 1) or 1))
				)
				total_marks += q_marks
				quiz_doc.append(
					"questions",
					{
						"question": q_doc.name,
						"question_detail": getattr(q_doc, "question", ""),
						"type": getattr(q_doc, "type", None) or "Choices",
						"marks": q_marks,
					},
				)
			quiz_doc.total_marks = total_marks
			quiz_doc.insert(ignore_permissions=True)
			quiz_name = quiz_doc.name

			practice = frappe.new_doc("Course Lesson")
			practice.title = f"Prática e Fixação · {quiz_title}"[:135]
			practice.chapter = last_chapter_doc.name
			practice.course = course.name
			if hasattr(practice, "include_in_preview"):
				practice.include_in_preview = 0
			if hasattr(practice, "quiz_id"):
				practice.quiz_id = quiz_doc.name
			practice.body = _sanitize_html(
				"<p><strong>Hora de praticar!</strong> Resolva as questões selecionadas abaixo para consolidar os conceitos estudados nas aulas anteriores e confira os comentários detalhados após responder.</p>"
			)
			practice.insert(ignore_permissions=True)
			lessons_created.append(practice.name)
			last_chapter_doc.append("lessons", {"lesson": practice.name})
			last_chapter_doc.save(ignore_permissions=True)

		return {
			"course_name": course.name,
			"course_title": course.title,
			"course_created": course_created,
			"chapters_created": len(chapters_created),
			"lessons_created": len(lessons_created),
			"quiz_name": quiz_name,
			"quiz_questions": len(selected) if quiz_name else 0,
			"records": len(lessons_created)
			+ len(chapters_created)
			+ (1 if course_created else 0)
			+ (1 if quiz_name else 0),
		}
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise


def _execute_course_build(run_name: str, p: dict[str, Any]) -> dict[str, Any]:
	"""Fase 1 (LLM, sem escrita de domínio) + fase 2 (transação única)."""
	cache = frappe.cache()
	blueprint = p["blueprint"]
	level = p["level"]
	chapters = blueprint["chapters"]
	total = sum(len(c.get("lessons") or []) for c in chapters) or 1

	frappe.db.set_value(
		"Trivia Sync Run",
		run_name,
		{
			"status": "Running",
			"started_at": frappe.utils.now_datetime(),
			"current_operation": "Iniciando redação das aulas...",
			"error_log": None,
		},
		update_modified=False,
	)
	frappe.db.commit()

	try:
		settings = frappe.get_single("Trivia Sync Settings")
		if not settings.ai_enabled:
			frappe.throw("Ative a Athena em Trivia Sync Settings antes de gerar um curso.")
		adapter = get_ai_adapter(settings)

		methodology_text = _load_methodology(p.get("methodology"))
		seed_doc = None
		if p.get("seed_question") and frappe.db.exists("LMS Question", p["seed_question"]):
			seed_doc = frappe.get_doc("LMS Question", p["seed_question"])
		context = _pedagogical_context(seed_doc, p.get("prompt", ""), p.get("use_teacher_materials", True))

		if p.get("target_course"):
			course_title = (
				frappe.db.get_value("LMS Course", p["target_course"], "title") or p["target_course"]
			)
		else:
			course_title = str(blueprint.get("course_title") or "Novo Curso · Athena").strip()[:135]

		syllabus = [
			{"capitulo": c.get("title"), "aulas": [l.get("title") for l in (c.get("lessons") or [])]}
			for c in chapters
		]

		generated: dict[str, Any] = cache.get_value(_lessons_key(run_name)) or {}
		summaries: list[dict[str, str]] = []
		done = 0

		for ci, ch_spec in enumerate(chapters):
			ch_title = str(ch_spec.get("title") or "Capítulo").strip()[:135]
			for li, les_spec in enumerate(ch_spec.get("lessons") or []):
				key = f"{ci}.{li}"
				les_title = str(les_spec.get("title") or "Aula").strip()[:135]
				if key not in generated:
					_progress(
						run_name, done * 100 / total, f"Gerando aula {done + 1}/{total}: {les_title[:60]}"
					)
					messages, schema = _build_lesson_writer_messages(
						course_title=course_title,
						chapter_title=ch_title,
						lesson_spec={
							"title": les_title,
							"objective": str(les_spec.get("objective") or ""),
							"key_points": les_spec.get("key_points") or [],
						},
						level=level,
						methodology_text=methodology_text,
						pedagogical_context=context,
						syllabus=syllabus,
						previous_lessons=summaries,
					)
					data = _chat_json_retry(
						adapter, messages, "athena_course_lesson", schema, 5500, validator=_validate_lesson
					)
					generated[key] = {"html_content": data["html_content"], "summary": data["summary"]}
					cache.set_value(_lessons_key(run_name), generated, expires_in_sec=RESUME_TTL)
				summaries.append({"titulo": les_title, "resumo": generated[key]["summary"]})
				done += 1

		_progress(run_name, 95, "Gravando curso, capítulos, aulas e quiz")
		result = _materialize_course(p, course_title, generated)

		frappe.db.set_value(
			"Trivia Sync Run",
			run_name,
			{
				"status": "Completed",
				"current_operation": f"Curso pronto: {result['course_name']}"[:140],
				"records_created": result["records"],
				"finished_at": frappe.utils.now_datetime(),
			},
			update_modified=False,
		)
		frappe.db.commit()
		cache.delete_value(_lessons_key(run_name))
		cache.delete_value(_payload_key(run_name))
		if hasattr(frappe, "publish_progress"):
			try:
				frappe.publish_progress(
					100,
					title="Athena · Gerando curso",
					description="Concluído",
					doctype="Trivia Sync Run",
					docname=run_name,
				)
			except Exception:
				pass
		result.pop("records", None)
		result["model"] = adapter.model
		return result
	except Exception:
		tb = traceback.format_exc()
		frappe.log_error(tb, "Trivia Sync · Athena Course Builder")
		frappe.db.set_value(
			"Trivia Sync Run",
			run_name,
			{"status": "Failed", "error_log": tb, "finished_at": frappe.utils.now_datetime()},
			update_modified=False,
		)
		frappe.db.commit()
		raise
	finally:
		fp = p.get("fingerprint")
		if fp:
			cache.delete_value(_lock_key(fp))


def _run_course_job(run_name: str, params: dict[str, Any]) -> None:
	"""Entrypoint do worker (fila `long`). O erro já é registrado no Trivia Sync Run."""
	try:
		_execute_course_build(run_name, params)
	except Exception:
		pass


def _prepare_params(
	blueprint,
	target_course,
	seed_question,
	prompt,
	level,
	methodology,
	use_teacher_materials,
	include_quiz,
	owner_user,
) -> dict[str, Any]:
	if isinstance(blueprint, str):
		blueprint = json.loads(blueprint or "{}")
	if not isinstance(blueprint, dict):
		frappe.throw("Estrutura de curso inválida.")
	clean_level = level if level in VALID_LEVELS else "180"
	blueprint = _clamp_blueprint(blueprint, clean_level)
	if not blueprint.get("chapters"):
		frappe.throw("A ementa precisa ter ao menos um capítulo com aulas.")
	if target_course and not frappe.db.exists("LMS Course", target_course):
		frappe.throw(f"Curso de destino {target_course} não encontrado.")
	return {
		"blueprint": blueprint,
		"target_course": target_course or None,
		"seed_question": seed_question or None,
		"prompt": str(prompt or "").strip(),
		"level": clean_level,
		"methodology": methodology or None,
		"use_teacher_materials": bool(use_teacher_materials),
		"include_quiz": bool(include_quiz),
		"owner_user": owner_user or frappe.session.user or "Administrator",
		"fingerprint": _fingerprint(blueprint, target_course, seed_question, clean_level),
	}


def _guard_duplicates(p: dict[str, Any], force: bool) -> None:
	if not p["target_course"] and not force:
		title = str(p["blueprint"].get("course_title") or "").strip()[:135]
		existing = frappe.db.exists("LMS Course", {"title": title}) if title else None
		if existing:
			frappe.throw(
				f"Já existe o curso '{existing}' com este título. Use outro título, escolha-o como curso de destino ou confirme a duplicação (force)."
			)
	if frappe.cache().get_value(_lock_key(p["fingerprint"])):
		frappe.throw("Já existe uma geração em andamento para esta mesma ementa. Aguarde ela terminar.")


def _new_run(status: str = "Queued", current_operation: str = "Na fila para gerar curso...") -> str:
	return create_sync_run(
		source="Athena",
		operation="Create LMS Course",
		status=status,
		current_operation=current_operation,
	)


@whitelist()
def start_course_generation(
	blueprint: dict[str, Any] | str,
	target_course: str | None = None,
	seed_question: str | None = None,
	prompt: str = "",
	level: str = "180",
	methodology: str | None = None,
	use_teacher_materials: bool = True,
	include_quiz: bool = True,
	force: bool = False,
) -> dict[str, Any]:
	"""Enfileira a geração e devolve o nome do Trivia Sync Run para acompanhar o progresso."""
	_require_course_role()
	p = _prepare_params(
		blueprint,
		target_course,
		seed_question,
		prompt,
		level,
		methodology,
		frappe.parse_json(use_teacher_materials)
		if isinstance(use_teacher_materials, str)
		else use_teacher_materials,
		frappe.parse_json(include_quiz) if isinstance(include_quiz, str) else include_quiz,
		frappe.session.user,
	)
	_guard_duplicates(p, bool(frappe.parse_json(force)) if isinstance(force, str) else bool(force))

	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Ative a Athena em Trivia Sync Settings antes de gerar um curso.")

	course_label = str(p["blueprint"].get("course_title") or p.get("target_course") or "Curso")[:80]
	run_name = _new_run(status="Queued", current_operation=f"Na fila: {course_label}")
	cache = frappe.cache()
	cache.set_value(_lock_key(p["fingerprint"]), run_name, expires_in_sec=LOCK_TTL)
	cache.set_value(_payload_key(run_name), p, expires_in_sec=RESUME_TTL)
	frappe.db.commit()

	dispatched = dispatch_background_job(
		f"{__name__}._run_course_job",
		kwargs={"run_name": run_name, "params": p},
		queue="long",
		timeout=3600,
		job_name=f"athena_course_{run_name}",
		run_name=run_name,
	)
	return {"run": run_name, "status": "Queued", **dispatched}


@whitelist()
def resume_course_generation(run_name: str) -> dict[str, Any]:
	"""Retoma uma geração que falhou, reaproveitando as aulas já geradas (cache de 24h)."""
	_require_course_role()
	row = frappe.db.get_value("Trivia Sync Run", run_name, ["status", "owner"], as_dict=True)
	if not row:
		frappe.throw(f"Execução {run_name} não encontrada.")
	if row.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw("Apenas o autor da execução ou um System Manager pode retomá-la.")
	if row.status != "Failed":
		frappe.throw("Só é possível retomar execuções com status Failed.")

	cache = frappe.cache()
	params = cache.get_value(_payload_key(run_name))
	if not params:
		frappe.throw("O prazo de retomada expirou. Gere o curso novamente.")
	if cache.get_value(_lock_key(params["fingerprint"])):
		frappe.throw("Já existe uma geração em andamento para esta mesma ementa.")

	cache.set_value(_lock_key(params["fingerprint"]), run_name, expires_in_sec=LOCK_TTL)
	frappe.db.set_value(
		"Trivia Sync Run",
		run_name,
		{"status": "Queued", "current_operation": "Retomando geração..."},
		update_modified=False,
	)
	frappe.db.commit()
	dispatched = dispatch_background_job(
		f"{__name__}._run_course_job",
		kwargs={"run_name": run_name, "params": params},
		queue="long",
		timeout=3600,
		job_name=f"athena_course_resume_{run_name}",
		run_name=run_name,
	)
	return {"run": run_name, "status": "Queued", **dispatched}


@whitelist()
def get_course_run_status(run_name: str) -> dict[str, Any]:
	_require_course_role()
	row = frappe.db.get_value(
		"Trivia Sync Run",
		run_name,
		["name", "status", "current_operation", "records_created", "error_log"],
		as_dict=True,
	)
	if not row:
		frappe.throw(f"Execução {run_name} não encontrada.")
	row["error_log"] = (row.get("error_log") or "")[-2000:]
	return row


def create_course_from_blueprint(
	blueprint: dict[str, Any] | str,
	target_course: str | None = None,
	seed_question: str | None = None,
	prompt: str = "",
	level: str = "180",
	methodology: str | None = None,
	use_teacher_materials: bool = True,
	include_quiz: bool = True,
	owner_user: str | None = None,
	force: bool = False,
) -> dict[str, Any]:
	"""Versão síncrona (testes, bench console, CLI). Para a UI use start_course_generation."""
	_require_course_role()
	p = _prepare_params(
		blueprint,
		target_course,
		seed_question,
		prompt,
		level,
		methodology,
		use_teacher_materials,
		include_quiz,
		owner_user,
	)
	_guard_duplicates(p, force)
	run_name = _new_run()
	frappe.cache().set_value(_lock_key(p["fingerprint"]), run_name, expires_in_sec=LOCK_TTL)
	frappe.db.commit()
	return _execute_course_build(run_name, p)
