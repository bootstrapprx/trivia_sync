import frappe

from trivia_sync.integrations.knowledge import (
	get_published_knowledge_page,
	list_published_knowledge_pages,
)


def get_context(context):
	context.no_cache = 1
	slug = (frappe.form_dict.get("slug") or "").strip()
	subject = (frappe.form_dict.get("subject") or "").strip() or None
	if slug:
		page = get_published_knowledge_page(slug)
		context.page_doc = page
		context.pages = []
		context.title = page.get("title") or "Conhecimento"
	else:
		context.page_doc = None
		context.pages = list_published_knowledge_pages(subject=subject)
		context.title = "Base de Conhecimento"
	return context
