import frappe


def execute():
	counts = {"checked": 0, "linked": 0, "unmatched": 0}
	for row in frappe.get_all(
		"LMS Question", filters={"trivia_qcode": ["!=", ""]}, fields=["name", "trivia_qcode", "trivia_question"]
	):
		counts["checked"] += 1
		if row.trivia_question:
			continue
		name = frappe.db.get_value("Trivia Question", {"qcode": row.trivia_qcode}, "name")
		if not name:
			counts["unmatched"] += 1
			continue
		source_key = frappe.db.get_value("Trivia Question", name, "source_key")
		frappe.db.set_value(
			"LMS Question", row.name,
			{"trivia_question": name, "trivia_source_key": source_key},
			update_modified=False,
		)
		counts["linked"] += 1
	frappe.logger("trivia_sync").info("Legacy LMS question backfill: %s", counts)
	return counts
