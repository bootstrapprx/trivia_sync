from urllib.parse import quote

import frappe

from trivia_sync.integrations.ai_enricher import get_question_deep_dive


def get_context(context):
	context.no_cache = 1
	q = (frappe.form_dict.get("q") or "").strip()

	if frappe.session.user == "Guest":
		target = f"/aprofundar?q={quote(q, safe='')}" if q else "/aprofundar"
		frappe.local.flags.redirect_location = f"/login?redirect-to={quote(target, safe='')}"
		raise frappe.Redirect

	context.question_name = q
	context.deep_dive = None
	context.error_message = None
	context.title = "Aprofunde seu conhecimento"

	if not q:
		context.error_message = "Nenhuma questão informada. Abra este link a partir do feedback de uma questão no Quiz."
		return context

	try:
		data = get_question_deep_dive(q)
		context.deep_dive = data
		context.title = f"Aprofundamento · {data.get('qcode') or q}"
	except Exception as exc:
		context.error_message = str(exc) or "Não foi possível carregar o aprofundamento desta questão."

	return context
