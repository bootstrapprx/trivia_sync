import frappe

from trivia_sync.integrations.reconciliation import CLASSIFICATION_FIELDS, reconcile_question_classification


def execute():
	counts = {"checked": 0, "updated": 0, "unmatched": 0, "ambiguous": 0}
	for row in frappe.get_all("Trivia Question", pluck="name"):
		question = frappe.get_doc("Trivia Question", row)
		counts["checked"] += 1
		previous = {link_field: getattr(question, link_field, None) for _, link_field in CLASSIFICATION_FIELDS.values()}
		results = reconcile_question_classification(question)
		for result in results.values():
			if result["status"] in ("unmatched", "ambiguous"):
				counts[result["status"]] += 1
		changed = any(previous[link_field] != results[field]["name"] for field, (_, link_field) in CLASSIFICATION_FIELDS.items())
		if changed:
			question.save(ignore_permissions=True)
			counts["updated"] += 1
	frappe.logger("trivia_sync").info("Contest relation backfill: %s", counts)
	return counts
