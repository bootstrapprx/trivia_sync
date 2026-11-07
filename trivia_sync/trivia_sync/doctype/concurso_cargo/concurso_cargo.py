from frappe.model.document import Document
import frappe

from trivia_sync.integrations.identity import ensure_unique_source_key, source_identity


class ConcursoCargo(Document):
	def validate(self):
		if not self.source_type:
			self.source_type = "Manual"
		if not self.source_id:
			self.source_id = frappe.generate_hash(length=20)
		self.source_id, self.source_key = source_identity(self.source_type, self.source_id)
		ensure_unique_source_key("Concurso Cargo", self.source_key, self.name)
		if self.lms_course and not frappe.db.exists("LMS Course", self.lms_course):
			frappe.throw("O curso LMS associado precisa existir antes de vincular o cargo.")
