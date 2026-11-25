from trivia_sync.patches.v0_6.migrate_to_lms_native import backfill_lms_question_titles
import frappe


def execute():
	backfill_lms_question_titles()
	if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
		frappe.db.commit()
