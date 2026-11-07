from frappe.model.document import Document
import frappe
import re
from trivia_sync.integrations.identity import ensure_unique_source_key, source_identity


class TriviaConcurso(Document):
	def validate(self):
		self.source_id, self.source_key = source_identity(self.source_type or "QAPI", self.source_id, self.qapi_id)
		ensure_unique_source_key("Concurso", self.source_key, self.name)
		if self.public_slug and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.public_slug):
			frappe.throw("Use apenas letras minúsculas, números e hífens no identificador público.")
		if self.publication_status == "Published":
			previous = self.get_doc_before_save() if not self.is_new() else None
			if not previous or previous.publication_status != "Published":
				if not self.public_slug or not self.public_summary:
					frappe.throw("Informe um identificador e um resumo antes de publicar o concurso.")
				links = frappe.get_all("Concurso Cargo", filters={"concurso": self.name}, fields=["lms_course"])
				course_names = [row.lms_course for row in links if row.lms_course]
				if not course_names or not frappe.get_all("LMS Course", filters={"name": ["in", course_names], "published": 1}, pluck="name"):
					frappe.throw("Associe ao menos um curso LMS publicado antes de publicar o concurso.")
				self.published_at = frappe.utils.now_datetime()
