import json

import frappe

OPTION_LETTERS = "ABCDEFGHIJ"
EDITORIAL_TRANSITIONS = {
	"Imported": {"Pending Review"},
	"Pending Review": {"In Review"},
	"In Review": {"Pending Review", "Pending Approval"},
	"Pending Approval": {"Pending Review", "Approved", "Rejected"},
	"Approved": {"Pending Review", "Published", "Archived"},
	"Published": {"Pending Review", "Archived"},
	"Rejected": {"Pending Review", "Archived"},
	"Archived": {"Pending Review"},
}
EDITORIAL_ROLES = {
	"Pending Review": "Trivia Editor",
	"In Review": "Trivia Editor",
	"Pending Approval": "Trivia Editor",
	"Approved": "Trivia Reviewer",
	"Rejected": "Trivia Reviewer",
	"Published": "Trivia Integrator",
	"Archived": "Trivia Integrator",
}


def validate_editorial_transition(previous_status, status, roles, is_new=False):
	if is_new:
		if status != "Imported":
			frappe.throw("New questions must start in Imported status.")
		return
	previous_status = previous_status or "Imported"
	if status == previous_status:
		return
	if status not in EDITORIAL_TRANSITIONS.get(previous_status, set()):
		frappe.throw(f"Cannot move a question from {previous_status} to {status}.")
	required_role = EDITORIAL_ROLES.get(status)
	if required_role and required_role not in roles and "System Manager" not in roles:
		frappe.throw("You do not have permission to make this editorial transition.", frappe.PermissionError)


def question_options(source):
	try:
		options = json.loads(source.options or "{}")
		raw_correct = json.loads(getattr(source, "correct_options", None) or "[]")
	except (TypeError, ValueError):
		frappe.throw("The question options or answer keys are invalid.")
	if not isinstance(options, dict):
		frappe.throw("The question options are invalid.")
	if any(str(letter).upper() not in OPTION_LETTERS for letter in options):
		frappe.throw("Question options must use letters A through J.")
	options = {str(letter).upper(): value for letter, value in options.items() if value not in (None, "")}
	if not 2 <= len(options) <= 10:
		frappe.throw("Choice questions must have between two and ten non-empty options.")
	if not isinstance(raw_correct, list):
		frappe.throw("Correct answers must be a list of option letters.")
	correct = list(dict.fromkeys(str(letter).upper() for letter in raw_correct if letter))
	if not correct:
		legacy = getattr(source, "correct_option", None)
		correct = [legacy] if legacy else []
	if not correct or any(letter not in options for letter in correct):
		frappe.throw("Every correct answer must match an existing option.")
	if len(options) != 5:
		if not getattr(source, "allow_variable_options", 0):
			frappe.throw("Standard choice questions must have exactly five options.")
		if not (getattr(source, "exception_reason", None) or "").strip():
			frappe.throw("Provide a reason for the variable option count.")
	if getattr(source, "editorial_difficulty", None) not in (None, "") and not 1 <= float(source.editorial_difficulty) <= 5:
		frappe.throw("Editorial difficulty must be between one and five stars.")
	return options, correct


def transition_question(question_name, status, reason=""):
	if status not in ("Pending Review", "In Review", "Pending Approval", "Archived"):
		frappe.throw("Editorial status transition must use a review workflow action.")
	doc = frappe.get_doc("Trivia Question", question_name)
	validate_editorial_transition(doc.editorial_status, status, frappe.get_roles(frappe.session.user))
	doc.editorial_status = status
	if status == "Pending Review":
		doc.review_status = "Pending"
		doc.reviewed_by = None
		doc.reviewed_at = None
		doc.review_reason = reason or None
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "editorial_status": doc.editorial_status}


def _require_role(role):
	roles = frappe.get_roles(frappe.session.user)
	if role not in roles and "System Manager" not in roles:
		frappe.throw("You do not have permission to make this editorial decision.", frappe.PermissionError)


def review_question(question_name, decision, reason=""):
	_require_role("Trivia Reviewer")
	if decision not in ("approved", "rejected"):
		frappe.throw("Decision must be approved or rejected.")
	doc = frappe.get_doc("Trivia Question", question_name)
	if doc.editorial_status != "Pending Approval":
		frappe.throw("The question must be pending editorial approval.")
	validate_editorial_transition(doc.editorial_status, "Approved" if decision == "approved" else "Rejected", frappe.get_roles(frappe.session.user))
	if decision == "approved":
		question_options(doc)
	doc.review_status = "Approved" if decision == "approved" else "Rejected"
	doc.editorial_status = "Approved" if decision == "approved" else "Rejected"
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
	if source.review_status != "Approved" or getattr(source, "editorial_status", "Approved") not in ("Approved", "Published"):
		frappe.throw("The question must be editorially approved.")
	if source.redistribution_status != "Approved":
		frappe.throw("Redistribution must be authorized.")
	if not (source.source_license or source.redistribution_reference):
		frappe.throw("A license or redistribution reference must be recorded.")
	if not source.enunciado or not source.correct_option:
		frappe.throw("Question text and answer key are required to project the question.")
	options, _ = question_options(source)
	if source.texto_apoio and not frappe.db.exists("Trivia Supporting Text", source.texto_apoio):
		frappe.throw("The linked supporting text does not exist.")
	return options
