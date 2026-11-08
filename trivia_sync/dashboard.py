import json

import frappe

from trivia_sync.integrations.reconciliation import question_coverage

whitelist = getattr(frappe, "whitelist", lambda: (lambda function: function))

def _admin():
	frappe.only_for(("System Manager", "Trivia Reviewer", "Trivia Integrator", "Trivia Editor"))


def _safe_count(doctype, filters=None):
	try:
		return frappe.db.count(doctype, filters=filters or {})
	except Exception:
		return 0


def _difficulty_metrics():
	rows = frappe.db.sql(
		"""
        SELECT ai_difficulty_stars AS stars, COUNT(*) AS total
        FROM `tabTrivia Question`
        WHERE ai_difficulty_stars IS NOT NULL AND ai_difficulty_stars > 0
        GROUP BY ai_difficulty_stars
        ORDER BY ai_difficulty_stars
        """,
		as_dict=True,
	)
	distribution = {str(stars): 0 for stars in range(1, 6)}
	for row in rows:
		distribution[str(int(row.stars))] = int(row.total)
	average = (
		frappe.db.sql(
			"SELECT AVG(ai_difficulty_stars) AS average FROM `tabTrivia Question` WHERE ai_difficulty_stars IS NOT NULL",
			as_dict=True,
		)[0].average
		or 0
	)
	return {"distribution": distribution, "average": round(float(average), 2)}


def _endpoint_metrics(run):
	if not run or not getattr(run, "endpoint_metrics", None):
		return {}
	try:
		metrics = json.loads(run.endpoint_metrics)
	except (TypeError, ValueError):
		return {}
	for values in metrics.values():
		received = int(values.get("received", 0) or 0)
		processed = int(values.get("created", 0) or 0) + int(values.get("updated", 0) or 0)
		values["failed"] = int(values.get("failed", 0) or 0)
		values["utilization_percent"] = round((processed / received) * 100, 1) if received else 0
	return metrics


@whitelist()
def metrics():
	_admin()
	total_questions = _safe_count("Trivia Question")
	enriched_questions = _safe_count("Trivia Question", {"ai_enriched_at": ["is", "set"]})
	pending_questions = max(total_questions - enriched_questions, 0)
	run_rows = frappe.get_all(
		"Trivia Sync Run",
		fields=[
			"name", "source", "operation", "status", "started_at", "finished_at", "page",
			"records_created", "records_updated", "records_skipped", "records_errors", "records_received",
			"endpoint_metrics", "requests_made", "credits_used", "request_budget", "credit_reserve",
			"current_operation", "resume_operation", "resume_page",
		],
		order_by="creation desc",
		limit_page_length=12,
	)
	running = sum(1 for row in run_rows if row.status == "Running")
	failed = sum(1 for row in run_rows if row.status in {"Failed", "Partial"})
	oldest_pending = frappe.get_all(
		"Trivia Question", filters={"review_status": "Pending"}, fields=["creation"],
		order_by="creation asc", page_length=1,
	)
	oldest_days = 0
	if oldest_pending and oldest_pending[0].creation:
		oldest_days = max(0, int((frappe.utils.now_datetime() - oldest_pending[0].creation).total_seconds() // 86400))
	settings = frappe.get_single("Trivia Sync Settings")
	latest_qapi_run = frappe.get_all(
		"Trivia Sync Run", filters={"source": "QAPI"},
		fields=[
			"name", "status", "started_at", "finished_at", "requests_made", "credits_used", "request_budget",
			"credit_reserve", "current_operation", "resume_operation", "resume_page", "records_received",
			"endpoint_metrics",
		],
		order_by="creation desc", page_length=1,
	)
	latest_run = latest_qapi_run[0] if latest_qapi_run else None
	cargo_rows = frappe.get_all(
		"Trivia Contest Position", fields=["name", "concurso", "cargo", "lms_course"],
		order_by="modified desc", page_length=25,
	)
	cargo_coverage = []
	for cargo in cargo_rows:
		coverage = question_coverage(cargo.name)
		cargo_coverage.append({
			"concurso_cargo": cargo.name, "concurso": cargo.concurso, "cargo": cargo.cargo,
			"lms_course": cargo.lms_course, "questions": coverage["total"], "eligible": coverage["eligible"],
			"subjects": coverage["subject"], "topics": coverage["topic"], "review": coverage["review"],
			"license": coverage["license"], "source": coverage["source"],
		})
	return {
		"workers": {"running": running, "failed_recent": failed, "recent_runs": run_rows},
		"editorial": {
			"pending_review": _safe_count("Trivia Question", {"review_status": "Pending"}),
			"oldest_pending_days": oldest_days,
			"projection_pending": _safe_count("Trivia Question", {"projection_status": "Pending"}),
			"projection_failed": _safe_count("Trivia Question", {"projection_status": "Failed"}),
		},
		"source_sync": {
			"enabled": bool(settings.qapi_enabled), "last_run": latest_run,
			"last_sync": settings.last_qapi_sync_at,
			"request_budget": int(settings.qapi_max_requests_per_run or 0),
			"credit_reserve": max(1, int(settings.qapi_min_credit_reserve or 1)),
			"paid_sync_available": int(settings.qapi_max_requests_per_run or 0) > max(1, int(settings.qapi_min_credit_reserve or 1)),
			"endpoint_metrics": _endpoint_metrics(latest_run),
			"records_received": int(getattr(latest_run, "records_received", 0) or 0) if latest_run else 0,
		},
		"syllabus_coverage": cargo_coverage,
		"questions": {
			"total": total_questions, "enriched": enriched_questions, "pending": pending_questions,
			"coverage_percent": round((enriched_questions / total_questions) * 100, 1) if total_questions else 0,
			**_difficulty_metrics(),
		},
		"catalogs": {
			"bancas": _safe_count("Trivia Exam Board"), "orgaos": _safe_count("Trivia Organization"),
			"concursos": _safe_count("Trivia Contest"), "provas": _safe_count("Trivia Exam"),
			"flashcards": _safe_count("Flashcard"),
		},
		"generated_at": frappe.utils.now_datetime(),
	}
