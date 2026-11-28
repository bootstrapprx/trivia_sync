import json
import uuid

import frappe
from frappe.utils import cint

from trivia_sync.integrations.ai_enricher import (
	apply_ai_topics as apply_question_topics_from_ai,
	apply_question_ai_review as apply_lms_question_ai_review,
	codex_login_status as fetch_codex_login_status,
	draft_question_option_explanations as generate_option_explanations_draft,
	enrich_questions_batch,
	enrich_question_full as enrich_single_question_all,
	enrich_single_question_difficulty,
	extract_question_knowledge as extract_knowledge_for_question,
	get_question_deep_dive as fetch_question_deep_dive,
	review_question_with_feedback as review_lms_question_with_feedback,
	start_codex_device_auth as initiate_codex_device_auth,
	submit_student_reflection as evaluate_student_reflection,
	test_ai_connection,
)
from trivia_sync.integrations.exam_importer import (
	apply_quiz_answer_key as apply_lms_quiz_answer_key,
	confirm_question_answer_key as confirm_lms_question_answer_key,
	get_quiz_answer_key_state as fetch_quiz_answer_key_state,
	import_ready_exam as import_ready_exam_payload,
	preview_ready_exam as preview_ready_exam_payload,
)
from trivia_sync.integrations.exams import build_lms_quiz_from_bank
from trivia_sync.integrations.background import create_sync_run, dispatch_background_job
from trivia_sync.integrations.course_builder import (
	create_course_from_blueprint as materialize_athena_course,
	get_course_run_status as fetch_athena_course_run_status,
	plan_course_blueprint as build_athena_course_blueprint,
	resume_course_generation as restart_athena_course_generation,
	start_course_generation as launch_athena_course_generation,
)
from trivia_sync.integrations.frappe_lms import sync_existing_lms_to_trivia
from trivia_sync.integrations.knowledge import (
	get_knowledge_page_backlinks,
	get_question_knowledge_pages,
	set_knowledge_page_status,
	setup_flow_knowledge_and_skill as configure_flow_knowledge_and_skill,
)
from trivia_sync.integrations.learning_content import (
	approve_apostila_material,
	archive_apostila_recipe as archive_study_guide_recipe,
	check_material_freshness,
	create_manual_apostila_material as create_manual_study_guide_draft,
	export_apostila as export_approved_pdf,
	generate_apostila_material,
	generate_course_lesson_draft,
	reject_apostila_material,
	submit_apostila_material,
)
from trivia_sync.integrations.lms_questions import compose_lms_question_html, set_lms_question_status
from trivia_sync.integrations.qapi import test_qapi_connection
from trivia_sync.integrations.reconciliation import question_coverage
from trivia_sync.integrations.sync import ingest_source, reformat_qapi_questions
from trivia_sync.whitelabel import apply_whitelabel


def _admin():
	frappe.only_for("System Manager")


def has_app_permission():
	user_roles = set(frappe.get_roles(frappe.session.user))
	return bool(user_roles.intersection({"System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"}))


@frappe.whitelist()
def apply_whitelabel_now():
	_admin()
	return apply_whitelabel(force=True)


@frappe.whitelist()
def onboarding_status():
	_admin()
	doc = frappe.get_single("Trivia Sync Settings")
	return {
		"configured": bool(doc.qapi_api_key),
		"enabled": bool(doc.qapi_enabled),
		"frequency": doc.qapi_sync_frequency or "Hourly",
		"base_url": doc.qapi_base_url,
		"last_sync": doc.last_qapi_sync_at,
		"full_sync": bool(doc.sync_catalogs),
		"sync_options": {
			field: bool(getattr(doc, field, 0))
			for field in (
				"sync_questions",
				"sync_support_texts",
				"sync_bancas",
				"sync_orgaos",
				"sync_cargos",
				"sync_materias",
				"sync_assuntos",
				"sync_concursos",
				"sync_disciplinas",
				"sync_conteudos",
				"sync_flashcards",
				"push_flashcards",
			)
		},
		"request_budget": doc.qapi_max_requests_per_run or 0,
		"credit_reserve": max(1, int(doc.qapi_min_credit_reserve or 1)),
		"page_size": int(doc.qapi_page_size or 10),
		"max_pages": int(doc.qapi_max_pages or 10),
		"paid_sync_available": int(doc.qapi_max_requests_per_run or 0) > max(1, int(doc.qapi_min_credit_reserve or 1)),
	}


@frappe.whitelist()
def save_onboarding(
	qapi_api_key=None,
	qapi_enabled=0,
	qapi_sync_frequency="Hourly",
	qapi_base_url=None,
	qapi_max_requests_per_run=None,
	qapi_min_credit_reserve=None,
	qapi_page_size=None,
	qapi_max_pages=None,
	sync_catalogs=None,
	sync_options=None,
):
	_admin()
	if qapi_sync_frequency not in ("Hourly", "Every scheduler tick"):
		frappe.throw("Invalid sync frequency.")
	doc = frappe.get_single("Trivia Sync Settings")
	doc.qapi_enabled = cint(qapi_enabled)
	doc.qapi_sync_frequency = qapi_sync_frequency
	doc.qapi_base_url = (qapi_base_url or "https://qapi.otunac.com/api").strip().rstrip("/")
	if qapi_max_requests_per_run is not None:
		doc.qapi_max_requests_per_run = max(0, cint(qapi_max_requests_per_run))
	if qapi_min_credit_reserve is not None:
		doc.qapi_min_credit_reserve = max(1, cint(qapi_min_credit_reserve))
	if qapi_page_size is not None:
		doc.qapi_page_size = max(1, min(10, cint(qapi_page_size)))
	if qapi_max_pages is not None:
		doc.qapi_max_pages = max(1, min(100000, cint(qapi_max_pages)))
	if doc.qapi_enabled and int(doc.qapi_max_requests_per_run or 0) <= max(1, int(doc.qapi_min_credit_reserve or 1)):
		frappe.throw("Set a request budget above the reserve before enabling paid sync.")
	if qapi_api_key:
		doc.qapi_api_key = qapi_api_key
	if sync_catalogs is not None:
		doc.sync_catalogs = cint(sync_catalogs)
	if isinstance(sync_options, str):
		sync_options = json.loads(sync_options or "{}")
	allowed_sync_fields = {
		"sync_questions",
		"sync_support_texts",
		"sync_bancas",
		"sync_orgaos",
		"sync_cargos",
		"sync_materias",
		"sync_assuntos",
		"sync_concursos",
		"sync_disciplinas",
		"sync_conteudos",
		"sync_flashcards",
		"push_flashcards",
	}
	for field, value in (sync_options or {}).items():
		if field in allowed_sync_fields:
			setattr(doc, field, cint(value))
	doc.save()
	return onboarding_status()


@frappe.whitelist()
def enqueue_qapi_sync(full=1, dry_run=0, budget=None, max_pages=0, filters=None):
	_admin()
	parsed_filters = json.loads(filters) if isinstance(filters, str) and filters else filters or {}
	op_label = "Full QAPI sync" if cint(full) else "Pull questions"
	run_name = create_sync_run(
		source="QAPI",
		operation="QAPI ingestion",
		status="Queued",
		current_operation=f"Na fila: {op_label}",
		parameters={"filters": parsed_filters, "full": bool(cint(full)), "max_pages": cint(max_pages)},
	)
	job_name = f"trivia_sync_qapi_{'full' if cint(full) else 'questions'}_{uuid.uuid4().hex[:10]}"
	dispatched = dispatch_background_job(
		"trivia_sync.integrations.sync.ingest_source",
		kwargs={
			"source_name": "QAPI",
			"filters": parsed_filters,
			"dry_run": bool(cint(dry_run)),
			"include_catalogs": bool(cint(full)),
			"budget": None if budget in (None, "") else cint(budget),
			"max_pages": cint(max_pages),
			"queued_run": run_name,
		},
		queue="long",
		job_name=job_name,
		run_name=run_name,
	)
	return {
		**dispatched,
		"message": "Sincronização QAPI iniciada em segundo plano.",
	}


@frappe.whitelist()
def enqueue_qapi_full_upgrade(budget=None, max_pages=0, filters=None):
	_admin()
	doc = frappe.get_single("Trivia Sync Settings")
	doc.sync_catalogs = 1
	for field in (
		"sync_questions",
		"sync_support_texts",
		"sync_bancas",
		"sync_orgaos",
		"sync_cargos",
		"sync_materias",
		"sync_assuntos",
		"sync_concursos",
		"sync_disciplinas",
		"sync_conteudos",
		"sync_flashcards",
	):
		setattr(doc, field, 1)
	doc.push_flashcards = 0
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return enqueue_qapi_sync(full=1, budget=budget, max_pages=max_pages, filters=filters)


@frappe.whitelist()
def enqueue_lms_sync():
	_admin()
	run_name = create_sync_run(
		source="Frappe LMS",
		operation="Push LMS content",
		status="Queued",
		current_operation="Na fila: sincronizar cursos LMS → Trivia",
	)
	return dispatch_background_job(
		"trivia_sync.integrations.frappe_lms.sync_existing_lms_to_trivia",
		kwargs={"run_name": run_name},
		queue="long",
		job_name="trivia_sync_lms_to_trivia",
		run_name=run_name,
	)


@frappe.whitelist()
def qapi_status():
	_admin()
	return test_qapi_connection()


@frappe.whitelist()
def run_qapi_sync_now(dry_run=0, budget=None, max_pages=0, filters=None, include_catalogs=1, full_upgrade=0):
	_admin()
	parsed_filters = json.loads(filters) if isinstance(filters, str) and filters else filters or {}
	return ingest_source(
		"QAPI",
		filters=parsed_filters,
		dry_run=bool(cint(dry_run)),
		include_catalogs=bool(cint(include_catalogs)),
		budget=None if budget in (None, "") else cint(budget),
		max_pages=cint(max_pages),
		force_full_upgrade=bool(cint(full_upgrade)),
	)


@frappe.whitelist()
def repair_qapi_question(question_name):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	return reformat_qapi_questions(question_name=question_name, limit=1)


@frappe.whitelist()
def enqueue_qapi_reformat(limit=10000):
	_admin()
	parsed_limit = max(1, min(cint(limit), 100000))
	run_name = create_sync_run(
		source="QAPI",
		operation="QAPI reformat",
		status="Queued",
		current_operation=f"Na fila: reprocessar formatação QAPI (até {parsed_limit})",
	)
	job_name = f"trivia_sync_reformat_{uuid.uuid4().hex[:10]}"
	return dispatch_background_job(
		"trivia_sync.integrations.sync.reformat_qapi_questions",
		kwargs={"limit": parsed_limit, "run_name": run_name},
		queue="long",
		job_name=job_name,
		run_name=run_name,
	)


@frappe.whitelist()
def resume_qapi_sync(run_name, budget=None):
	_admin()
	run = frappe.get_doc("Trivia Sync Run", run_name)
	if run.source != "QAPI" or run.status not in ("Partial", "Failed", "Blocked"):
		frappe.throw("Only partial, blocked, or failed QAPI runs can be resumed.")
	parameters = json.loads(run.parameters_json or "{}")
	return ingest_source(
		"QAPI",
		filters=parameters.get("filters"),
		max_pages=parameters.get("max_pages", 0),
		include_catalogs=parameters.get("include_catalogs", True),
		budget=None if budget in (None, "") else cint(budget),
		resume_run=run_name,
	)


@frappe.whitelist()
def cargo_question_coverage(concurso_cargo):
	_admin()
	if not frappe.db.exists("Trivia Contest Position", concurso_cargo):
		frappe.throw("Contest position not found.")
	return question_coverage(concurso_cargo)


@frappe.whitelist()
def update_lms_question_status(question_name, status):
	return set_lms_question_status(question_name, status)


@frappe.whitelist()
def build_lms_quiz(
	quiz_name,
	count=10,
	subject=None,
	topic=None,
	board=None,
	concurso_cargo=None,
	syllabus_topic=None,
	only_ready=1,
	append_existing=0,
	marks=None,
	include_deprecated=0,
):
	return build_lms_quiz_from_bank(
		quiz_name=quiz_name,
		count=cint(count or 10),
		subject=subject or None,
		topic=topic or None,
		board=board or None,
		concurso_cargo=concurso_cargo or None,
		syllabus_topic=syllabus_topic or None,
		only_ready=bool(cint(only_ready)),
		append_existing=bool(cint(append_existing)),
		marks=marks,
		include_deprecated=bool(cint(include_deprecated)),
	)


@frappe.whitelist()
def generate_course_lesson_material(
	lesson_name,
	level="180",
	trivia_subject=None,
	trivia_topic=None,
	syllabus_topic=None,
	methodology=None,
	prompt="",
):
	return generate_course_lesson_draft(
		lesson_name=lesson_name,
		level=level,
		trivia_subject=trivia_subject or None,
		trivia_topic=trivia_topic or None,
		syllabus_topic=syllabus_topic or None,
		methodology=methodology or None,
		prompt=prompt or "",
	)


@frappe.whitelist()
def set_contest_publication(concurso_name, status):
	_admin()
	if status not in ("Draft", "Published", "Archived"):
		frappe.throw("Invalid publication status.")
	doc = frappe.get_doc("Trivia Contest", concurso_name)
	doc.publication_status = status
	doc.save()
	return {"name": doc.name, "publication_status": doc.publication_status}


@frappe.whitelist()
def generate_apostila_recipe_material(recipe_name, level):
	frappe.only_for(("Trivia Integrator", "System Manager"))
	return generate_apostila_material(recipe_name, level)


@frappe.whitelist()
def create_manual_apostila_material(recipe_name, level, content, summary=""):
	return create_manual_study_guide_draft(recipe_name, level, content, summary)


@frappe.whitelist()
def submit_apostila_recipe_material(recipe_name, level, version):
	return submit_apostila_material(recipe_name, level, version)


@frappe.whitelist()
def approve_apostila_recipe_material(recipe_name, level, version, reason=""):
	return approve_apostila_material(recipe_name, level, version, reason)


@frappe.whitelist()
def reject_apostila_recipe_material(recipe_name, level, version, reason=""):
	return reject_apostila_material(recipe_name, level, version, reason)


@frappe.whitelist()
def export_apostila(recipe_name, levels):
	frappe.only_for(("Trivia Integrator", "System Manager"))
	return export_approved_pdf(recipe_name, levels)


@frappe.whitelist()
def archive_apostila_recipe(recipe_name):
	return archive_study_guide_recipe(recipe_name)


@frappe.whitelist()
def check_apostila_recipe_freshness(recipe_name):
	return check_material_freshness("Trivia Study Guide Recipe", recipe_name)


@frappe.whitelist()
def run_lms_sync_now():
	_admin()
	return sync_existing_lms_to_trivia()


@frappe.whitelist()
def enqueue_ai_enrichment(mode="full", limit=None, include_knowledge=1, force=0):
	_admin()
	return enqueue_ai_batch(mode=mode, limit=limit, include_knowledge=include_knowledge, force=force)


@frappe.whitelist()
def enqueue_ai_batch(question_names=None, mode="full", limit=None, include_knowledge=1, force=0, filters=None):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	if isinstance(question_names, str):
		question_names = json.loads(question_names or "[]")
	if isinstance(filters, str):
		filters = json.loads(filters or "{}")
	if mode not in ("full", "difficulty", "explanations", "knowledge"):
		frappe.throw("Invalid AI batch mode.")
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable AI enrichment in Trivia Sync Settings before queuing a batch.")
	parsed_limit = None if limit in (None, "") else max(1, min(cint(limit), 200))
	effective_limit = parsed_limit or int(settings.ai_batch_size or 10)
	run_name = create_sync_run(
		source="Athena",
		operation=f"AI batch ({mode})",
		status="Queued",
		current_operation=f"Na fila: lote Athena ({mode}, até {effective_limit} questões)",
		parameters={
			"mode": mode,
			"limit": effective_limit,
			"include_knowledge": bool(cint(include_knowledge)),
			"force": bool(cint(force)),
			"selected_count": len(question_names or []),
		},
	)
	job_name = f"trivia_sync_ai_batch_{mode}_{uuid.uuid4().hex[:8]}"
	dispatched = dispatch_background_job(
		"trivia_sync.integrations.ai_enricher.enrich_questions_batch",
		kwargs={
			"question_names": question_names or None,
			"mode": mode,
			"limit": parsed_limit,
			"include_knowledge": bool(cint(include_knowledge)),
			"force": bool(cint(force)),
			"filters": filters or None,
			"run_name": run_name,
		},
		queue="long",
		job_name=job_name,
		run_name=run_name,
	)
	return {
		**dispatched,
		"mode": mode,
		"selected_count": len(question_names or []),
		"limit": effective_limit,
	}


@frappe.whitelist()
def run_ai_batch_now(question_names=None, mode="full", limit=5, include_knowledge=1, force=0, filters=None):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	if isinstance(question_names, str):
		question_names = json.loads(question_names or "[]")
	if isinstance(filters, str):
		filters = json.loads(filters or "{}")
	parsed_limit = max(1, min(cint(limit or 5), 15))
	return enrich_questions_batch(
		question_names=question_names or None,
		mode=mode,
		limit=parsed_limit,
		include_knowledge=bool(cint(include_knowledge)),
		force=bool(cint(force)),
		filters=filters or None,
	)


@frappe.whitelist()
def run_ai_enrichment_now():
	_admin()
	return enrich_questions_batch(mode="full")


@frappe.whitelist()
def draft_question_option_explanations(question_name):
	return generate_option_explanations_draft(question_name)


@frappe.whitelist()
def enrich_question_difficulty(question_name):
	return enrich_single_question_difficulty(question_name)


@frappe.whitelist()
def enrich_question_all(question_name):
	return enrich_single_question_all(question_name)


@frappe.whitelist()
def apply_question_ai_topics(question_name):
	return apply_question_topics_from_ai(question_name)


@frappe.whitelist()
def extract_question_knowledge(question_name):
	return extract_knowledge_for_question(question_name)


@frappe.whitelist()
def ai_status():
	_admin()
	return test_ai_connection()


@frappe.whitelist()
def question_knowledge_pages(question_name):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	return get_question_knowledge_pages(question_name)


@frappe.whitelist()
def knowledge_page_backlinks(page_name):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	return get_knowledge_page_backlinks(page_name)


@frappe.whitelist()
def update_knowledge_page_status(page_name, status):
	return set_knowledge_page_status(page_name, status)


@frappe.whitelist()
def setup_flow_knowledge_and_skill():
	return configure_flow_knowledge_and_skill()


@frappe.whitelist()
def supporting_text_preview(name):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	if not name or not frappe.db.exists("Trivia Supporting Text", name):
		return None
	doc = frappe.get_doc("Trivia Supporting Text", name)
	return {"name": doc.name, "titulo": doc.titulo, "conteudo": doc.conteudo}


@frappe.whitelist()
def create_and_link_supporting_text(question_name, titulo, conteudo):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	if not (titulo or "").strip() or not (conteudo or "").strip():
		frappe.throw("Provide a title and content for the supporting text.")
	text_doc = frappe.new_doc("Trivia Supporting Text")
	text_doc.source_type = "Manual"
	text_doc.titulo = titulo.strip()
	text_doc.conteudo = conteudo
	text_doc.insert(ignore_permissions=True)
	question = frappe.get_doc("LMS Question", question_name)
	question.trivia_texto_apoio = text_doc.name
	question.question = compose_lms_question_html(
		question.question,
		texto_apoio=text_doc.name,
		knowledge_rows=getattr(question, "trivia_knowledge_pages", None),
	)
	question.save(ignore_permissions=True)
	return {"supporting_text": text_doc.name, "titulo": text_doc.titulo, "question": question.name}


@frappe.whitelist()
def preview_ready_exam(payload, answer_key=None):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	return preview_ready_exam_payload(payload, answer_key=answer_key)


@frappe.whitelist()
def import_ready_exam(
	payload,
	answer_key=None,
	quiz_title=None,
	passing_percentage=60,
	contest=None,
	contest_position=None,
	update_existing=1,
):
	return import_ready_exam_payload(
		payload,
		answer_key=answer_key,
		quiz_title=quiz_title,
		passing_percentage=cint(passing_percentage or 60),
		contest=contest or None,
		contest_position=contest_position or None,
		update_existing=bool(cint(update_existing)),
	)


@frappe.whitelist()
def get_quiz_answer_key_state(quiz_name):
	return fetch_quiz_answer_key_state(quiz_name)


@frappe.whitelist()
def apply_quiz_answer_key(quiz_name, answer_key):
	return apply_lms_quiz_answer_key(quiz_name, answer_key)


@frappe.whitelist()
def confirm_question_answer_key(question_name):
	return confirm_lms_question_answer_key(question_name)


@frappe.whitelist()
def review_question_with_feedback(
	question_name,
	feedback,
	proposed_correct=None,
	history=None,
	include_general_comment=1,
):
	return review_lms_question_with_feedback(
		question_name=question_name,
		feedback=feedback,
		proposed_correct=proposed_correct,
		history=history,
		include_general_comment=bool(cint(include_general_comment)),
	)


@frappe.whitelist()
def apply_question_ai_review(
	question_name,
	correct_options,
	option_explanations,
	difficulty_stars=None,
	difficulty_label=None,
	reason=None,
	model=None,
):
	return apply_lms_question_ai_review(
		question_name=question_name,
		correct_options=correct_options,
		option_explanations=option_explanations,
		difficulty_stars=cint(difficulty_stars) if difficulty_stars not in (None, "") else None,
		difficulty_label=difficulty_label,
		reason=reason,
		model=model,
	)


@frappe.whitelist()
def get_question_deep_dive(question_name):
	return fetch_question_deep_dive(question_name)


@frappe.whitelist()
def submit_student_reflection(question_name, student_answer):
	return evaluate_student_reflection(question_name, student_answer)


@frappe.whitelist()
def start_codex_oauth():
	_admin()
	return initiate_codex_device_auth()


@frappe.whitelist()
def get_codex_oauth_status():
	_admin()
	return fetch_codex_login_status()


@frappe.whitelist()
def plan_athena_course(
	seed_question=None,
	prompt="",
	level="180",
	methodology=None,
	use_teacher_materials=1,
	subject=None,
	topic=None,
):
	return build_athena_course_blueprint(
		seed_question=seed_question or None,
		prompt=prompt or "",
		level=level or "180",
		methodology=methodology or None,
		use_teacher_materials=bool(cint(use_teacher_materials)),
		subject=subject or None,
		topic=topic or None,
	)


@frappe.whitelist()
def create_athena_course(
	blueprint,
	target_course=None,
	seed_question=None,
	prompt="",
	level="180",
	methodology=None,
	use_teacher_materials=1,
	include_quiz=1,
):
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	return materialize_athena_course(
		blueprint=blueprint,
		target_course=target_course or None,
		seed_question=seed_question or None,
		prompt=prompt or "",
		level=level or "180",
		methodology=methodology or None,
		use_teacher_materials=bool(cint(use_teacher_materials)),
		include_quiz=bool(cint(include_quiz)),
		owner_user=frappe.session.user,
	)


@frappe.whitelist()
def enqueue_athena_course(
	blueprint,
	target_course=None,
	seed_question=None,
	prompt="",
	level="180",
	methodology=None,
	use_teacher_materials=1,
	include_quiz=1,
	force=0,
):
	return launch_athena_course_generation(
		blueprint=blueprint,
		target_course=target_course or None,
		seed_question=seed_question or None,
		prompt=prompt or "",
		level=level or "180",
		methodology=methodology or None,
		use_teacher_materials=bool(cint(use_teacher_materials)),
		include_quiz=bool(cint(include_quiz)),
		force=bool(cint(force)),
	)


@frappe.whitelist()
def get_athena_course_run_status(run_name):
	return fetch_athena_course_run_status(run_name)


@frappe.whitelist()
def resume_athena_course(run_name):
	return restart_athena_course_generation(run_name)
