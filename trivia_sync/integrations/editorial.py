import frappe


def _require_role(role):
	roles = frappe.get_roles(frappe.session.user)
	if role not in roles and "System Manager" not in roles:
		frappe.throw("You do not have permission to make this editorial decision.", frappe.PermissionError)


def review_question(question_name, decision, reason=""):
	_require_role("Trivia Reviewer")
	if decision not in ("approved", "rejected"):
		frappe.throw("Decision must be approved or rejected.")
	doc = frappe.get_doc("Trivia Question", question_name)
	doc.review_status = "Approved" if decision == "approved" else "Rejected"
	doc.reviewed_by = frappe.session.user
	doc.reviewed_at = frappe.utils.now_datetime()
	doc.review_reason = (reason or "").strip()
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "review_status": doc.review_status, "reviewed_at": doc.reviewed_at}


def decide_redistribution(question_name, decision, reason=""):
	_require_role("Trivia Integrator")
	if decision not in ("approved", "rejected"):
		frappe.throw("Decision must be approved or rejected.")
	doc = frappe.get_doc("Trivia Question", question_name)
	if decision == "approved" and not (doc.source_license or doc.redistribution_reference):
		frappe.throw("Record the source license or terms reference before authorizing redistribution.")
	doc.redistribution_status = "Approved" if decision == "approved" else "Rejected"
	doc.redistribution_reference = (reason or doc.redistribution_reference or "").strip()
	doc.redistribution_decided_by = frappe.session.user
	doc.redistribution_decided_at = frappe.utils.now_datetime()
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "redistribution_status": doc.redistribution_status}


def validate_projection_eligibility(source):
	if not source.source_key:
		frappe.throw("The question must have a stable source identity.")
	if source.review_status != "Approved":
		frappe.throw("The question must be editorially approved.")
	if source.redistribution_status != "Approved":
		frappe.throw("Redistribution must be authorized.")
	if not (source.source_license or source.redistribution_reference):
		frappe.throw("A license or redistribution reference must be recorded.")
	if not source.enunciado or not source.correct_option:
		frappe.throw("Question text and answer key are required to project the question.")
	try:
		options = frappe.parse_json(source.options or "{}")
	except (TypeError, ValueError):
		frappe.throw("The question options are invalid.")
	if not isinstance(options, dict) or len([value for value in options.values() if value]) < 2:
		frappe.throw("The question must have at least two options.")
	if source.correct_option not in options or not options[source.correct_option]:
		frappe.throw("The answer key must match an existing option.")
	if source.texto_apoio and not frappe.db.exists("Trivia Supporting Text", source.texto_apoio):
		frappe.throw("The linked supporting text does not exist.")
	return options
