import frappe

from trivia_sync.public import get_public_contest, list_public_contests


def get_context(context):
	context.no_cache = 1
	context.title = "Public contests"
	slug = frappe.form_dict.get("slug")
	if slug:
		context.contest = get_public_contest(slug)
		context.contests = []
	else:
		context.contest = None
		context.contests = list_public_contests()
	return context
