import json

import frappe

from trivia_sync.integrations.background import has_active_rq_worker
from trivia_sync.integrations.reconciliation import question_coverage

whitelist = getattr(frappe, "whitelist", lambda: (lambda function: function))


def _admin():
	frappe.only_for(("System Manager", "Trivia Reviewer", "Trivia Integrator", "Trivia Editor"))


def _safe_count(doctype, filters=None):
	try:
		return frappe.db.count(doctype, filters=filters or {})
	except Exception:
		return 0


def _normalize_stars(value):
	num = float(value or 0)
	if num <= 0:
		return 0
	if num <= 1.0:
		return max(1, min(5, int(round(num * 5))))
	return max(1, min(5, int(round(num))))


def _difficulty_metrics():
	try:
		rows = frappe.db.sql(
			"""
			SELECT trivia_ai_difficulty_stars AS stars, COUNT(*) AS total
			FROM `tabLMS Question`
			WHERE trivia_ai_difficulty_stars IS NOT NULL AND trivia_ai_difficulty_stars > 0
			GROUP BY trivia_ai_difficulty_stars
			ORDER BY trivia_ai_difficulty_stars
			""",
			as_dict=True,
		)
	except Exception:
		rows = []
	distribution = {str(stars): 0 for stars in range(1, 6)}
	weighted_sum = 0
	total_rated = 0
	for row in rows:
		stars = _normalize_stars(row.stars)
		count = int(row.total or 0)
		if stars in range(1, 6):
			distribution[str(stars)] += count
			weighted_sum += stars * count
			total_rated += count
	if total_rated:
		average = weighted_sum / total_rated
	else:
		try:
			raw_avg = (
				frappe.db.sql(
					"SELECT AVG(trivia_ai_difficulty_stars) AS average FROM `tabLMS Question` WHERE trivia_ai_difficulty_stars IS NOT NULL",
					as_dict=True,
				)[0].average
				or 0
			)
		except Exception:
			raw_avg = 0
		average = float(raw_avg) * 5 if 0 < float(raw_avg) <= 1.0 else float(raw_avg)
	return {"distribution": distribution, "average": round(float(average), 2)}


def _material_metrics():
	counts = {
		"draft": 0,
		"pending_approval": 0,
		"approved": 0,
		"rejected": 0,
		"published": 0,
		"stale": 0,
		"superseded": 0,
		"archived": 0,
	}
	status_map = {
		"Draft": "draft",
		"Pending Approval": "pending_approval",
		"Approved": "approved",
		"Rejected": "rejected",
		"Published": "published",
		"Stale": "stale",
		"Superseded": "superseded",
		"Archived": "archived",
	}
	try:
		rows = frappe.db.sql(
			"""
			SELECT status, COUNT(*) AS total
			FROM `tabTrivia Material Version`
			GROUP BY status
			""",
			as_dict=True,
		)
	except Exception:
		rows = []
	for row in rows or []:
		key = status_map.get(getattr(row, "status", None) if not isinstance(row, dict) else row.get("status"))
		if key:
			total = getattr(row, "total", 0) if not isinstance(row, dict) else row.get("total", 0)
			counts[key] = int(total or 0)
	counts["knowledge_pages"] = _safe_count("Trivia Knowledge Page")
	counts["study_guides"] = _safe_count("Trivia Study Guide Recipe")
	return counts


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
	total_questions = _safe_count("LMS Question")
	enriched_questions = _safe_count("LMS Question", {"trivia_ai_enriched_at": ["is", "set"]})
	pending_questions = max(total_questions - enriched_questions, 0)
	run_rows = frappe.get_all(
		"Trivia Sync Run",
		fields=[
			"name", "source", "operation", "status", "started_at", "finished_at", "page",
			"records_created", "records_updated", "records_skipped", "records_errors", "records_received",
			"endpoint_metrics", "requests_made", "credits_used", "request_budget", "credit_reserve",
			"current_operation", "resume_operation", "resume_page", "error_log",
		],
		order_by="creation desc",
		limit_page_length=12,
	)
	for row in run_rows:
		raw_err = str(getattr(row, "error_log", None) or (row.get("error_log") if isinstance(row, dict) else "") or "").strip()
		snippet = raw_err.splitlines()[-1][:160] if raw_err else ""
		if isinstance(row, dict):
			row["error_snippet"] = snippet
		else:
			row.error_snippet = snippet
	running = sum(1 for row in run_rows if row.status == "Running")
	queued = sum(1 for row in run_rows if row.status == "Queued")
	failed = sum(1 for row in run_rows if row.status in {"Failed", "Partial"})
	oldest_pending = frappe.get_all(
		"LMS Question",
		filters={"trivia_status": "In Preparation"},
		fields=["creation"],
		order_by="creation asc",
		page_length=1,
	)
	oldest_days = 0
	if oldest_pending and oldest_pending[0].creation:
		oldest_days = max(0, int((frappe.utils.now_datetime() - oldest_pending[0].creation).total_seconds() // 86400))
	settings = frappe.get_single("Trivia Sync Settings")
	latest_qapi_run = frappe.get_all(
		"Trivia Sync Run",
		filters={"source": "QAPI"},
		fields=[
			"name", "status", "started_at", "finished_at", "requests_made", "credits_used", "request_budget",
			"credit_reserve", "current_operation", "resume_operation", "resume_page", "records_received",
			"endpoint_metrics",
		],
		order_by="creation desc",
		page_length=1,
	)
	latest_run = latest_qapi_run[0] if latest_qapi_run else None
	cargo_rows = frappe.get_all(
		"Trivia Contest Position",
		fields=["name", "concurso", "cargo", "lms_course"],
		order_by="modified desc",
		page_length=25,
	)
	cargo_coverage = []
	for cargo in cargo_rows:
		coverage = question_coverage(cargo.name)
		cargo_coverage.append(
			{
				"concurso_cargo": cargo.name,
				"concurso": cargo.concurso,
				"cargo": cargo.cargo,
				"lms_course": cargo.lms_course,
				"questions": coverage["total"],
				"eligible": coverage["eligible"],
				"subjects": coverage["subject"],
				"topics": coverage["topic"],
				"review": coverage["review"],
				"license": coverage["license"],
				"source": coverage["source"],
			}
		)
	in_prep_count = _safe_count("LMS Question", {"trivia_status": "In Preparation"})
	ready_count = _safe_count("LMS Question", {"trivia_status": "Ready"})
	return {
		"workers": {
			"running": running,
			"queued": queued,
			"active": running + queued,
			"rq_worker_online": has_active_rq_worker("long"),
			"failed_recent": failed,
			"recent_runs": run_rows,
		},
		"editorial": {
			"pending_review": in_prep_count,
			"ready_questions": ready_count,
			"oldest_pending_days": oldest_days,
		},
		"source_sync": {
			"enabled": bool(settings.qapi_enabled),
			"last_run": latest_run,
			"last_sync": settings.last_qapi_sync_at,
			"request_budget": int(settings.qapi_max_requests_per_run or 0),
			"credit_reserve": max(1, int(settings.qapi_min_credit_reserve or 1)),
			"paid_sync_available": int(settings.qapi_max_requests_per_run or 0) > max(1, int(settings.qapi_min_credit_reserve or 1)),
			"endpoint_metrics": _endpoint_metrics(latest_run),
			"records_received": int(getattr(latest_run, "records_received", 0) or 0) if latest_run else 0,
		},
		"syllabus_coverage": cargo_coverage,
		"questions": {
			"total": total_questions,
			"enriched": enriched_questions,
			"pending": pending_questions,
			"coverage_percent": round((enriched_questions / total_questions) * 100, 1) if total_questions else 0,
			**_difficulty_metrics(),
		},
		"catalogs": {
			"bancas": _safe_count("Trivia Exam Board"),
			"orgaos": _safe_count("Trivia Organization"),
			"concursos": _safe_count("Trivia Contest"),
			"quizzes": _safe_count("LMS Quiz"),
			"flashcards": _safe_count("Flashcard"),
		},
		"materials": _material_metrics(),
		"generated_at": frappe.utils.now_datetime(),
	}
