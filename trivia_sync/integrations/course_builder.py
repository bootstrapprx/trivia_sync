import json
import re
import traceback
from typing import Any

import frappe

from trivia_sync.integrations.ai_enricher import AIEnrichmentError, get_ai_adapter
from trivia_sync.integrations.lms_questions import (
	extract_lms_question_options,
	strip_question_embeds,
)


COURSE_ROLES = ("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator")
VALID_LEVELS = {"mais", "180", "360"}
DEFAULT_COVER_IMAGE = "/assets/trivia_sync/images/athena_course_cover.svg"

LEVEL_GUIDANCE = {
	"mais": "Curso enxuto e direto ao ponto (1 capítulo, 2 a 3 aulas objetivas focadas na regra essencial e aplicação rápida).",
	"180": "Curso intermediário completo (1 a 2 capítulos, 3 a 5 aulas cobrindo base conceitual, regra normativa, exemplos resolvidos e pegadinhas).",
	"360": "Curso aprofundado de domínio total (2 a 3 capítulos, 5 a 8 aulas cobrindo fundamentos, doutrina/jurisprudência/norma, casos práticos e armadilhas de banca).",
}


def _require_course_role() -> None:
	frappe.only_for(COURSE_ROLES)


def _sanitize_html(raw_html: str) -> str:
	text = str(raw_html or "").strip()
	if not text:
		return ""
	try:
		from frappe.utils.html_utils import sanitize_html

		return sanitize_html(text, always_sanitize=True)
	except Exception:
		pass
	try:
		if hasattr(frappe, "utils") and hasattr(frappe.utils, "sanitize_html"):
			return frappe.utils.sanitize_html(text)
	except Exception:
		pass
	return text


def _plain_snippet(raw_html: str, max_len: int = 240) -> str:
	plain = re.sub(r"<[^>]+>", " ", str(raw_html or ""))
	plain = re.sub(r"\s+", " ", plain).strip()
	if len(plain) > max_len:
		return plain[: max_len - 1].rstrip() + "…"
	return plain


def _extract_keywords(text: str, max_terms: int = 6) -> list[str]:
	stopwords = {
		"como", "para", "sobre", "qual", "quais", "quando", "onde", "porque", "pela", "pelo",
		"pelos", "pelas", "uma", "uns", "umas", "dos", "das", "nos", "nas", "com", "sem",
		"entre", "este", "esta", "esse", "essa", "isso", "aquilo", "seria", "foram", "seja",
		"crie", "criar", "curso", "aula", "aulas", "sobre", "baseado", "questao", "questão",
	}
	words = re.findall(r"[A-Za-zÀ-ÿ0-9]{4,}", str(text or "").lower())
	seen: list[str] = []
	for w in words:
		if w not in stopwords and w not in seen:
			seen.append(w)
		if len(seen) >= max_terms:
			break
	return seen


def _find_related_bank_questions(
	seed_doc=None,
	prompt: str = "",
	subject: str | None = None,
	topic: str | None = None,
	limit: int = 20,
) -> list[dict[str, Any]]:
	"""Find Ready, non-deprecated LMS Questions relevant to the seed question or open prompt."""
	results: list[dict[str, Any]] = []
	seen_names: set[str] = set()

	def _add_row(row: dict[str, Any]) -> None:
		name = row.get("name")
		if not name or name in seen_names:
			return
		seen_names.add(name)
		title = row.get("trivia_title") or _plain_snippet(strip_question_embeds(row.get("question") or ""), 110) or name
		results.append(
			{
				"name": name,
				"qcode": row.get("trivia_qcode") or name,
				"title": title,
				"enunciado": _plain_snippet(strip_question_embeds(row.get("question") or ""), 280),
				"materia": row.get("trivia_materia") or "",
				"assunto": row.get("trivia_assunto") or "",
				"banca": row.get("trivia_banca") or "",
				"ano": row.get("trivia_ano") or "",
				"deprecated": bool(int(row.get("trivia_deprecated") or 0)),
			}
		)

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
	]

	if seed_doc is not None and not int(getattr(seed_doc, "trivia_answer_key_pending", 0) or 0):
		_add_row(
			{
				"name": seed_doc.name,
				"trivia_qcode": getattr(seed_doc, "trivia_qcode", None),
				"trivia_title": getattr(seed_doc, "trivia_title", None),
				"question": getattr(seed_doc, "question", None),
				"trivia_materia": getattr(seed_doc, "trivia_materia", None),
				"trivia_assunto": getattr(seed_doc, "trivia_assunto", None),
				"trivia_banca": getattr(seed_doc, "trivia_banca", None),
				"trivia_ano": getattr(seed_doc, "trivia_ano", None),
				"trivia_deprecated": getattr(seed_doc, "trivia_deprecated", 0),
			}
		)

	eff_topic = topic or (getattr(seed_doc, "trivia_topic_link", None) if seed_doc else None)
	eff_subject = subject or (getattr(seed_doc, "trivia_subject_link", None) if seed_doc else None)
	base_filters: dict[str, Any] = {
		"type": "Choices",
		"trivia_status": "Ready",
		"trivia_deprecated": ["!=", 1],
		"trivia_answer_key_pending": ["!=", 1],
	}

	filter_attempts: list[dict[str, Any]] = []
	if eff_topic:
		filter_attempts.append({**base_filters, "trivia_topic_link": eff_topic})
	if seed_doc and getattr(seed_doc, "trivia_assunto", None):
		filter_attempts.append({**base_filters, "trivia_assunto": getattr(seed_doc, "trivia_assunto")})
	if eff_subject:
		filter_attempts.append({**base_filters, "trivia_subject_link": eff_subject})
	if seed_doc and getattr(seed_doc, "trivia_materia", None):
		filter_attempts.append({**base_filters, "trivia_materia": getattr(seed_doc, "trivia_materia")})

	keywords = _extract_keywords(prompt)
	for kw in keywords[:4]:
		filter_attempts.append({**base_filters, "trivia_title": ["like", f"%{kw}%"]})
		filter_attempts.append({**base_filters, "trivia_assunto": ["like", f"%{kw}%"]})
		filter_attempts.append({**base_filters, "question": ["like", f"%{kw}%"]})

	for flt in filter_attempts:
		if len(results) >= limit:
			break
		try:
			rows = frappe.get_all(
				"LMS Question",
				filters=flt,
				fields=fields,
				order_by="modified desc",
				limit_page_length=limit,
			) or []
			for r in rows:
				_add_row(r)
				if len(results) >= limit:
					break
		except Exception:
			continue

	return results[:limit]


def _gather_knowledge_context(seed_doc=None, keywords: list[str] | None = None) -> list[dict[str, str]]:
	pages: list[dict[str, str]] = []
	seen: set[str] = set()

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
		linked_names = [
			getattr(r, "knowledge_page", None) if not isinstance(r, dict) else r.get("knowledge_page")
			for r in (getattr(seed_doc, "trivia_knowledge_pages", None) or [])
		]
		linked_names = [n for n in linked_names if n]
		if linked_names:
			try:
				rows = frappe.get_all(
					"Trivia Knowledge Page",
					filters={"name": ["in", linked_names]},
					fields=["name", "title", "summary", "explanation", "exam_traps"],
				) or []
				for r in rows:
					_append_page(r)
			except Exception:
				pass

	for kw in (keywords or [])[:3]:
		if len(pages) >= 6:
			break
		try:
			rows = frappe.get_all(
				"Trivia Knowledge Page",
				filters={"status": "Published", "title": ["like", f"%{kw}%"]},
				fields=["name", "title", "summary", "explanation", "exam_traps"],
				limit_page_length=3,
			) or []
			for r in rows:
				_append_page(r)
		except Exception:
			continue

	return pages[:6]


def _build_course_blueprint_messages(
	context_payload: dict[str, Any],
	level: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
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
				"minItems": 1,
				"maxItems": 4,
				"items": {
					"type": "object",
					"additionalProperties": False,
					"required": ["title", "description", "lessons"],
					"properties": {
						"title": {"type": "string", "minLength": 5, "maxLength": 120},
						"description": {"type": "string", "minLength": 10, "maxLength": 300},
						"lessons": {
							"type": "array",
							"minItems": 1,
							"maxItems": 5,
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
			"recommended_question_names": {
				"type": "array",
				"maxItems": 15,
				"items": {"type": "string"},
			},
		},
	}

	messages = [
		{
			"role": "system",
			"content": (
				"Você é Athena, arquiteta pedagógica especialista em concursos públicos brasileiros no Frappe LMS. "
				"Sua missão é estruturar um curso didático progressivo a partir de uma questão-semente e/ou de uma pergunta norteadora do professor. "
				f"Diretriz de escopo para o nível '{level}': {LEVEL_GUIDANCE.get(level, LEVEL_GUIDANCE['180'])} "
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
) -> tuple[list[dict[str, str]], dict[str, Any]]:
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
	}
	messages = [
		{
			"role": "system",
			"content": (
				"Você é Athena, professora especialista em concursos públicos brasileiros redigindo uma aula completa para o Frappe LMS. "
				"Escreva html_content em HTML limpo e bem estruturado (<h2>, <h3>, <p>, <ul>, <li>, <strong>, <blockquote>, <table> quando útil para quadros comparativos ou lançamentos). "
				"Ensine com clareza profunda todos os key_points da aula, trazendo fundamentação legal/teórica correta, exemplos inéditos resolvidos passo a passo e alertas de pegadinhas de prova. "
				"REGRA CRÍTICA: NUNCA entregue nem cite o gabarito literal das questões do banco (o aluno resolverá essas questões no Quiz final do curso). "
				"Se houver legislação revogada/substituída no contexto, destaque com clareza 'Como era' vs. 'Como é hoje'. "
				"Responda exclusivamente em português brasileiro no JSON Schema solicitado."
			),
		},
		{"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
	]
	return messages, schema


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

	methodology_text = ""
	if methodology and frappe.db.exists("Trivia Methodology", methodology):
		m_doc = frappe.get_doc("Trivia Methodology", methodology)
		if getattr(m_doc, "active", 1):
			methodology_text = str(getattr(m_doc, "instructions", "") or "").strip()

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
			seed_payload["comentario_do_professor"] = _plain_snippet(seed_doc.trivia_general_explanation, 2500)

	keywords = _extract_keywords(
		f"{clean_prompt} {seed_payload.get('title', '')} {seed_payload.get('assunto', '')} {seed_payload.get('materia', '')}"
	)
	bank_candidates = _find_related_bank_questions(
		seed_doc=seed_doc,
		prompt=clean_prompt,
		subject=subject,
		topic=topic,
		limit=20,
	)
	knowledge_pages = _gather_knowledge_context(seed_doc=seed_doc, keywords=keywords) if use_teacher_materials else []

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
	blueprint = adapter._chat_json(messages, "athena_course_blueprint", schema, 3500)

	valid_candidate_names = {q["name"] for q in bank_candidates}
	rec_names = [
		n for n in (blueprint.get("recommended_question_names") or [])
		if n in valid_candidate_names
	]
	if not rec_names and bank_candidates:
		rec_names = [q["name"] for q in bank_candidates[: min(8, len(bank_candidates))]]
	elif seed_doc and seed_doc.name in valid_candidate_names and seed_doc.name not in rec_names:
		rec_names.insert(0, seed_doc.name)

	blueprint["recommended_question_names"] = list(dict.fromkeys(rec_names))
	return {
		"blueprint": blueprint,
		"bank_candidates": bank_candidates,
		"level": clean_level,
		"model": adapter.model,
	}


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
	if not hasattr(frappe, "db") or not frappe.db.exists("LMS Quiz", {"title": clean}):
		return clean
	for idx in range(2, 50):
		candidate = f"{clean[:118]} · {idx}"
		if not frappe.db.exists("LMS Quiz", {"title": candidate}):
			return candidate
	return f"{clean[:110]} · {frappe.generate_hash(length=6)}"


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
) -> dict[str, Any]:
	"""Stage 2: Materialize LMS Course, Course Chapters, AI-authored Course Lessons, and LMS Quiz."""
	if isinstance(blueprint, str):
		blueprint = json.loads(blueprint or "{}")
	if not isinstance(blueprint, dict):
		frappe.throw("Estrutura de curso inválida.")

	chapters_spec = blueprint.get("chapters") or []
	if not chapters_spec:
		frappe.throw("A ementa precisa ter ao menos um capítulo.")

	clean_level = level if level in VALID_LEVELS else "180"
	effective_user = owner_user or getattr(getattr(frappe, "session", None), "user", None) or "Administrator"

	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Ative a Athena em Trivia Sync Settings antes de gerar um curso.")
	adapter = get_ai_adapter(settings)

	methodology_text = ""
	if methodology and frappe.db.exists("Trivia Methodology", methodology):
		m_doc = frappe.get_doc("Trivia Methodology", methodology)
		if getattr(m_doc, "active", 1):
			methodology_text = str(getattr(m_doc, "instructions", "") or "").strip()

	seed_doc = None
	if seed_question and frappe.db.exists("LMS Question", seed_question):
		seed_doc = frappe.get_doc("LMS Question", seed_question)

	pedagogical_context: dict[str, Any] = {
		"orientacao_do_professor": str(prompt or "").strip(),
	}
	if seed_doc is not None:
		pedagogical_context["questao_referencia"] = {
			"enunciado": strip_question_embeds(getattr(seed_doc, "question", "") or ""),
			"materia": getattr(seed_doc, "trivia_materia", None) or "",
			"assunto": getattr(seed_doc, "trivia_assunto", None) or "",
			"depreciada": bool(int(getattr(seed_doc, "trivia_deprecated", 0) or 0)),
			"norma_revogada": getattr(seed_doc, "trivia_deprecated_law", None) or "",
			"substituida_por": getattr(seed_doc, "trivia_replacement_law", None) or "",
		}
		if use_teacher_materials and getattr(seed_doc, "trivia_general_explanation", None):
			pedagogical_context["comentario_do_professor"] = _plain_snippet(seed_doc.trivia_general_explanation, 2500)
	if use_teacher_materials:
		pedagogical_context["paginas_de_conhecimento"] = _gather_knowledge_context(seed_doc=seed_doc)

	run = frappe.new_doc("Trivia Sync Run")
	run.source = "Athena"
	run.operation = "Create LMS Course"
	run.status = "Running"
	run.started_at = frappe.utils.now_datetime()
	run.insert(ignore_permissions=True)

	chapters_created: list[str] = []
	lessons_created: list[str] = []
	quiz_created_name: str | None = None

	try:
		if target_course:
			if not frappe.db.exists("LMS Course", target_course):
				frappe.throw(f"Curso de destino {target_course} não encontrado.")
			course = frappe.get_doc("LMS Course", target_course)
			course_created = False
		else:
			course = frappe.new_doc("LMS Course")
			course.title = str(blueprint.get("course_title") or "Novo Curso · Athena").strip()[:135]
			course.short_introduction = str(
				blueprint.get("short_introduction") or "Curso estruturado pela Athena."
			).strip()[:280]
			course.description = _sanitize_html(
				blueprint.get("course_description") or f"<p>{course.short_introduction}</p>"
			)
			_apply_safe_course_defaults(course, effective_user)
			course.insert(ignore_permissions=True)
			course_created = True

		last_chapter_doc = None
		for ch_spec in chapters_spec:
			ch_title = str(ch_spec.get("title") or "Capítulo").strip()[:135]
			if not ch_title:
				continue
			chapter_doc = frappe.new_doc("Course Chapter")
			chapter_doc.title = ch_title
			chapter_doc.course = course.name
			if hasattr(chapter_doc, "chapter_description") and ch_spec.get("description"):
				chapter_doc.chapter_description = str(ch_spec.get("description") or "").strip()[:300]
			chapter_doc.insert(ignore_permissions=True)
			chapters_created.append(chapter_doc.name)

			course.append("chapters", {"chapter": chapter_doc.name})
			course.save(ignore_permissions=True)

			for les_spec in (ch_spec.get("lessons") or []):
				les_title = str(les_spec.get("title") or "Aula").strip()[:135]
				if not les_title:
					continue
				run.current_operation = f"Gerando aula: {les_title[:60]}"
				run.save(ignore_permissions=True)

				messages, schema = _build_lesson_writer_messages(
					course_title=course.title,
					chapter_title=ch_title,
					lesson_spec={
						"title": les_title,
						"objective": str(les_spec.get("objective") or ""),
						"key_points": les_spec.get("key_points") or [],
					},
					level=clean_level,
					methodology_text=methodology_text,
					pedagogical_context=pedagogical_context,
				)
				generated = adapter._chat_json(messages, "athena_course_lesson", schema, 5500)
				clean_html = _sanitize_html(generated.get("html_content") or "")
				if not clean_html:
					raise AIEnrichmentError(f"Athena retornou conteúdo vazio para a aula '{les_title}'.")

				lesson_doc = frappe.new_doc("Course Lesson")
				lesson_doc.title = les_title
				lesson_doc.chapter = chapter_doc.name
				lesson_doc.course = course.name
				if hasattr(lesson_doc, "include_in_preview"):
					lesson_doc.include_in_preview = 0
				lesson_doc.body = clean_html
				lesson_doc.insert(ignore_permissions=True)
				lessons_created.append(lesson_doc.name)

				chapter_doc.append("lessons", {"lesson": lesson_doc.name})
			chapter_doc.save(ignore_permissions=True)
			last_chapter_doc = chapter_doc

		selected_questions = [
			str(q).strip()
			for q in (blueprint.get("recommended_question_names") or [])
			if str(q).strip() and frappe.db.exists("LMS Question", str(q).strip())
		]
		selected_questions = list(dict.fromkeys(selected_questions))

		if include_quiz and selected_questions and last_chapter_doc is not None:
			quiz_title = _unique_quiz_title(blueprint.get("quiz_title") or f"Fixação · {course.title}")
			quiz_doc = frappe.new_doc("LMS Quiz")
			quiz_doc.title = quiz_title
			quiz_doc.show_answers = 1
			quiz_doc.passing_percentage = 70
			if hasattr(quiz_doc, "course"):
				quiz_doc.course = course.name

			total_marks = 0
			for q_name in selected_questions:
				q_doc = frappe.get_doc("LMS Question", q_name)
				q_marks = 0 if int(getattr(q_doc, "trivia_deprecated", 0) or 0) else max(1, int(getattr(q_doc, "marks", 1) or 1))
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
			quiz_created_name = quiz_doc.name

			practice_lesson = frappe.new_doc("Course Lesson")
			practice_lesson.title = f"Prática e Fixação · {quiz_title}"[:135]
			practice_lesson.chapter = last_chapter_doc.name
			practice_lesson.course = course.name
			if hasattr(practice_lesson, "include_in_preview"):
				practice_lesson.include_in_preview = 0
			if hasattr(practice_lesson, "quiz_id"):
				practice_lesson.quiz_id = quiz_doc.name
			practice_lesson.body = _sanitize_html(
				"<p><strong>Hora de praticar!</strong> Resolva as questões selecionadas abaixo para consolidar os conceitos estudados nas aulas anteriores e confira os comentários detalhados após responder.</p>"
			)
			practice_lesson.insert(ignore_permissions=True)
			lessons_created.append(practice_lesson.name)

			last_chapter_doc.append("lessons", {"lesson": practice_lesson.name})
			last_chapter_doc.save(ignore_permissions=True)

		run.status = "Completed"
		run.current_operation = f"Curso pronto: {course.name}"
		run.records_created = len(lessons_created) + len(chapters_created) + (1 if course_created else 0) + (1 if quiz_created_name else 0)
		return {
			"course_name": course.name,
			"course_title": course.title,
			"course_created": course_created,
			"chapters_created": len(chapters_created),
			"lessons_created": len(lessons_created),
			"quiz_name": quiz_created_name,
			"quiz_questions": len(selected_questions) if quiz_created_name else 0,
			"model": adapter.model,
		}
	except Exception:
		run.status = "Failed"
		run.error_log = traceback.format_exc()
		frappe.log_error(traceback.format_exc(), "Trivia Sync · Athena Course Builder")
		raise
	finally:
		run.finished_at = frappe.utils.now_datetime()
		run.save(ignore_permissions=True)
		if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
			frappe.db.commit()
