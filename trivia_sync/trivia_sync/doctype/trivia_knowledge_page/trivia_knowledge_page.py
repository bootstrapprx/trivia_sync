import frappe
from frappe.model.document import Document

from trivia_sync.integrations.knowledge import slugify_concept


class TriviaKnowledgePage(Document):
	def autoname(self):
		if not (getattr(self, "slug", None) or "").strip():
			self.slug = slugify_concept(self.title)
		else:
			self.slug = slugify_concept(self.slug)
		self.name = self.slug

	def validate(self):
		if not (getattr(self, "slug", None) or "").strip():
			self.slug = slugify_concept(self.title)
		else:
			self.slug = slugify_concept(self.slug)
		if getattr(self, "parent_concept", None) and self.parent_concept == self.name:
			frappe.throw("A knowledge page cannot be its own parent concept.")
		if self.status == "Published" and not (getattr(self, "explanation", None) or "").strip():
			frappe.throw("Provide a concept explanation before publishing a knowledge page.")
		if self.status == "Published" and not getattr(self, "published_at", None):
			self.published_at = frappe.utils.now_datetime()
