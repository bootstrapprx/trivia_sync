import frappe


def _require_role(role):
	roles = frappe.get_roles(frappe.session.user)
	if role not in roles and "System Manager" not in roles:
		frappe.throw("Você não tem permissão para esta decisão editorial.", frappe.PermissionError)


def review_question(question_name, decision, reason=""):
	_require_role("Trivia Reviewer")
	if decision not in ("approved", "rejected"):
		frappe.throw("A decisão deve ser approved ou rejected.")
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
		frappe.throw("A decisão deve ser approved ou rejected.")
	doc = frappe.get_doc("Trivia Question", question_name)
	if decision == "approved" and not (doc.source_license or doc.redistribution_reference):
		frappe.throw("Registre a licença da fonte ou a referência dos termos antes de autorizar redistribuição.")
	doc.redistribution_status = "Approved" if decision == "approved" else "Rejected"
	doc.redistribution_reference = (reason or doc.redistribution_reference or "").strip()
	doc.redistribution_decided_by = frappe.session.user
	doc.redistribution_decided_at = frappe.utils.now_datetime()
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "redistribution_status": doc.redistribution_status}


def validate_projection_eligibility(source):
	if not source.source_key:
		frappe.throw("A questão precisa ter uma identidade estável de fonte.")
	if source.review_status != "Approved":
		frappe.throw("A questão precisa estar aprovada editorialmente.")
	if source.redistribution_status != "Approved":
		frappe.throw("A redistribuição precisa estar autorizada.")
	if not (source.source_license or source.redistribution_reference):
		frappe.throw("A licença ou referência de redistribuição precisa estar registrada.")
	if not source.enunciado or not source.correct_option:
		frappe.throw("Enunciado e gabarito são obrigatórios para projetar a questão.")
	try:
		options = frappe.parse_json(source.options or "{}")
	except (TypeError, ValueError):
		frappe.throw("As alternativas da questão estão inválidas.")
	if not isinstance(options, dict) or len([value for value in options.values() if value]) < 2:
		frappe.throw("A questão precisa ter pelo menos duas alternativas.")
	if source.correct_option not in options or not options[source.correct_option]:
		frappe.throw("O gabarito precisa corresponder a uma alternativa existente.")
	if source.texto_apoio and not frappe.db.exists("Texto de Apoio", source.texto_apoio):
		frappe.throw("O texto de apoio vinculado não existe.")
	return options
