import frappe

from trivia_sync.integrations.lms_questions import OPTION_LETTERS, sync_lms_question_deep_dive_embeds


def execute():
	if not hasattr(frappe, "db") or not frappe.db.exists("DocType", "LMS Question"):
		return
	names = frappe.get_all(
		"LMS Question",
		filters={"trivia_general_explanation": ["is", "set"]},
		pluck="name",
	)
	for name in names or []:
		try:
			doc = frappe.get_doc("LMS Question", name)
			sync_lms_question_deep_dive_embeds(doc)
			updates = {f"explanation_{idx}": getattr(doc, f"explanation_{idx}", "") or "" for idx in range(1, len(OPTION_LETTERS) + 1)}
			frappe.db.set_value("LMS Question", name, updates, update_modified=False)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Trivia Sync: backfill deep dive embed failed for {name}")
	if hasattr(frappe.db, "commit"):
		frappe.db.commit()
