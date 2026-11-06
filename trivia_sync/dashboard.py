import frappe


def _admin():
	frappe.only_for("System Manager")


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


@frappe.whitelist()
def metrics():
	_admin()
	total_questions = _safe_count("Trivia Question")
	enriched_questions = _safe_count("Trivia Question", {"ai_enriched_at": ["is", "set"]})
	pending_questions = max(total_questions - enriched_questions, 0)
	run_rows = frappe.get_all(
		"Trivia Sync Run",
		fields=[
			"name",
			"source",
			"operation",
			"status",
			"started_at",
			"finished_at",
			"page",
			"records_created",
			"records_updated",
			"records_skipped",
			"records_errors",
		],
		order_by="creation desc",
		limit_page_length=12,
	)
	running = sum(1 for row in run_rows if row.status == "Running")
	failed = sum(1 for row in run_rows if row.status in {"Failed", "Partial"})
	return {
		"workers": {"running": running, "failed_recent": failed, "recent_runs": run_rows},
		"questions": {
			"total": total_questions,
			"enriched": enriched_questions,
			"pending": pending_questions,
			"coverage_percent": round((enriched_questions / total_questions) * 100, 1)
			if total_questions
			else 0,
			**_difficulty_metrics(),
		},
		"catalogs": {
			"bancas": _safe_count("Banca"),
			"orgaos": _safe_count("Órgão"),
			"concursos": _safe_count("Concurso"),
			"provas": _safe_count("Prova"),
			"flashcards": _safe_count("Flashcard"),
		},
		"generated_at": frappe.utils.now_datetime(),
	}
