import json

import frappe
from frappe.utils import cint
from trivia_sync.integrations.frappe_lms import sync_existing_lms_to_trivia
from trivia_sync.integrations.qapi import sync_qapi_questions, test_qapi_connection
from trivia_sync.integrations.sync import ingest_source
from trivia_sync.integrations.ai_enricher import enrich_pending_questions
from trivia_sync.integrations.reconciliation import question_coverage
from trivia_sync.integrations.editorial import review_question as apply_question_review, decide_redistribution
from trivia_sync.integrations.lms_questions import sync_lms_question
from trivia_sync.integrations.exams import build_simulado as assemble_simulado, publish_prova as publish_exam
from trivia_sync.integrations.learning_content import (
	approve_lesson_material,
	approve_apostila_material,
	export_apostila as export_approved_pdf,
	generate_apostila_material,
	generate_lesson_material as generate_lesson_draft,
	publish_lesson_material as publish_approved_lesson_material,
)


def _admin():
	frappe.only_for("System Manager")


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
		"sync_options": {field: bool(getattr(doc, field, 0)) for field in (
			"sync_questions", "sync_support_texts", "sync_bancas", "sync_orgaos", "sync_cargos",
			"sync_materias", "sync_assuntos", "sync_concursos", "sync_exams", "sync_disciplinas",
			"sync_conteudos", "sync_flashcards", "push_flashcards",
		)},
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
		"sync_questions", "sync_support_texts", "sync_bancas", "sync_orgaos", "sync_cargos",
		"sync_materias", "sync_assuntos", "sync_concursos", "sync_exams", "sync_disciplinas",
		"sync_conteudos", "sync_flashcards", "push_flashcards",
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
	frappe.enqueue(
		"trivia_sync.integrations.sync.ingest_source",
		source_name="QAPI",
		filters=parsed_filters,
		dry_run=bool(cint(dry_run)),
		include_catalogs=bool(cint(full)),
		budget=None if budget in (None, "") else cint(budget),
		max_pages=cint(max_pages),
		queue="long",
		job_name="trivia_sync_qapi_full" if cint(full) else "trivia_sync_qapi_questions",
		enqueue_after_commit=True,
	)
	return {"queued": True, "job": "trivia_sync_qapi_full" if cint(full) else "trivia_sync_qapi_questions"}


@frappe.whitelist()
def enqueue_qapi_full_upgrade(budget=None, max_pages=0, filters=None):
	_admin()
	doc = frappe.get_single("Trivia Sync Settings")
	doc.sync_catalogs = 1
	for field in (
		"sync_questions", "sync_support_texts", "sync_bancas", "sync_orgaos", "sync_cargos", "sync_materias",
		"sync_assuntos", "sync_concursos", "sync_exams", "sync_disciplinas", "sync_conteudos", "sync_flashcards",
	):
		setattr(doc, field, 1)
	# Full upgrade is read-only by default; creating remote flashcards remains explicit.
	doc.push_flashcards = 0
	doc.save(ignore_permissions=True)
	return enqueue_qapi_sync(full=1, budget=budget, max_pages=max_pages, filters=filters)


@frappe.whitelist()
def enqueue_lms_sync():
	_admin()
	frappe.enqueue(
		"trivia_sync.integrations.frappe_lms.sync_existing_lms_to_trivia",
		queue="long",
		job_name="trivia_sync_lms_to_trivia",
		enqueue_after_commit=True,
	)
	return {"queued": True, "job": "trivia_sync_lms_to_trivia"}


@frappe.whitelist()
def qapi_status():
	_admin()
	return test_qapi_connection()


@frappe.whitelist()
def run_qapi_sync_now(dry_run=0, budget=None, max_pages=0, filters=None, full_upgrade=0):
	_admin()
	parsed_filters = json.loads(filters) if isinstance(filters, str) and filters else filters or {}
	return ingest_source(
		"QAPI",
		filters=parsed_filters,
		dry_run=bool(cint(dry_run)),
		include_catalogs=True,
		budget=None if budget in (None, "") else cint(budget),
		max_pages=cint(max_pages),
		force_full_upgrade=bool(cint(full_upgrade)),
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
def review_question(question_name, decision, reason=""):
	return apply_question_review(question_name, decision, reason)


@frappe.whitelist()
def decide_question_redistribution(question_name, decision, reason=""):
	return decide_redistribution(question_name, decision, reason)


@frappe.whitelist()
def project_question(question_name):
	frappe.only_for(("Trivia Integrator", "System Manager"))
	source = frappe.get_doc("Trivia Question", question_name)
	try:
		name = sync_lms_question(source)
		return {"name": name, "status": "Projected"}
	except Exception as exc:
		source.projection_status = "Failed"
		source.projection_error = f"{type(exc).__name__}: {str(exc)[:300]}"
		source.save(ignore_permissions=True)
		return {"name": question_name, "status": "Failed", "error": source.projection_error}


@frappe.whitelist()
def build_simulado(prova_name):
	frappe.only_for(("Trivia Integrator", "System Manager"))
	return assemble_simulado(prova_name)


@frappe.whitelist()
def publish_prova(prova_name, lesson_name=None):
	frappe.only_for(("Trivia Integrator", "System Manager"))
	return publish_exam(prova_name, lesson_name)


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
def generate_lesson_material(recipe_name, level):
	frappe.only_for(("Trivia Integrator", "System Manager"))
	return generate_lesson_draft(recipe_name, level)


@frappe.whitelist()
def generate_apostila_recipe_material(recipe_name, level):
	frappe.only_for(("Trivia Integrator", "System Manager"))
	return generate_apostila_material(recipe_name, level)


@frappe.whitelist()
def approve_lesson_recipe_material(recipe_name, level, version, reason=""):
	return approve_lesson_material(recipe_name, level, version, reason)


@frappe.whitelist()
def approve_apostila_recipe_material(recipe_name, level, version, reason=""):
	return approve_apostila_material(recipe_name, level, version, reason)


@frappe.whitelist()
def publish_lesson_material(recipe_name, level):
	frappe.only_for(("Trivia Integrator", "System Manager"))
	return publish_approved_lesson_material(recipe_name, level)


@frappe.whitelist()
def export_apostila(recipe_name, levels):
	frappe.only_for(("Trivia Integrator", "System Manager"))
	return export_approved_pdf(recipe_name, levels)


@frappe.whitelist()
def run_lms_sync_now():
	_admin()
	return sync_existing_lms_to_trivia()


@frappe.whitelist()
def enqueue_ai_enrichment():
	_admin()
	frappe.enqueue(
		"trivia_sync.integrations.ai_enricher.enrich_pending_questions",
		queue="long",
		job_name="trivia_sync_ai_enrichment",
		enqueue_after_commit=True,
	)
	return {"queued": True, "job": "trivia_sync_ai_enrichment"}


@frappe.whitelist()
def run_ai_enrichment_now():
	_admin()
	return enrich_pending_questions()
