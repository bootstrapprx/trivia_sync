import json

import frappe


def execute():
	counts = {"checked": 0, "updated": 0}
	for row in frappe.get_all(
		"Trivia Question",
		fields=[
			"name", "options", "correct_option", "correct_options", "detected_option_count", "review_status",
			"editorial_status", "lms_question", "source_license", "source_attribution", "source_authors",
			"redistribution_reference", "redistribution_status", "editorial_difficulty", "allow_variable_options",
			"exception_reason",
		],
		limit_page_length=0,
	):
		counts["checked"] += 1
		values = {}
		try:
			options = json.loads(row.options or "{}")
		except (TypeError, ValueError):
			options = {}
		count = sum(1 for value in options.values() if value not in (None, "")) if isinstance(options, dict) else 0
		if count != int(row.detected_option_count or 0):
			values["detected_option_count"] = count
		if not row.correct_options and row.correct_option:
			values["correct_options"] = json.dumps([row.correct_option])
		if row.editorial_status == "Imported":
			try:
				correct = json.loads(row.correct_options or "[]") if row.correct_options else [row.correct_option] if row.correct_option else []
			except (TypeError, ValueError):
				correct = []
			approved_shape = count == 5 and correct and all(letter in options and options[letter] for letter in correct)
			values["editorial_status"] = (
				"Approved" if row.review_status == "Approved" and approved_shape
				else "Rejected" if row.review_status == "Rejected"
				else "Pending Review"
			)
		if values:
			frappe.db.set_value("Trivia Question", row.name, values, update_modified=False)
			counts["updated"] += 1
		if row.lms_question:
			frappe.db.set_value(
				"LMS Question",
				row.lms_question,
				{
					"trivia_source_license": row.source_license,
					"trivia_source_attribution": row.source_attribution,
					"trivia_source_authors": row.source_authors,
					"trivia_redistribution_reference": row.redistribution_reference,
					"trivia_redistribution_status": row.redistribution_status,
					"trivia_editorial_difficulty": row.editorial_difficulty,
					"trivia_detected_option_count": count,
					"trivia_allow_variable_options": row.allow_variable_options,
					"trivia_exception_reason": row.exception_reason,
				},
				update_modified=False,
			)
	return counts
