from frappe.model.document import Document
import frappe

from trivia_sync.integrations.identity import ensure_unique_source_key, source_identity


class TriviaQuestion(Document):
	def autoname(self):
		if self.qcode:
			self.name = self.qcode
			return
		if not self.source_id:
			self.source_type = "Manual"
			self.source_id = frappe.generate_hash(length=20)
		self.source_id, self.source_key = source_identity(self.source_type, self.source_id)
		self.name = frappe.generate_hash(length=20)

	def validate(self):
		if not self.source_type:
			self.source_type = "QAPI" if self.qcode else "Manual"
		self.source_id, self.source_key = source_identity(self.source_type, self.source_id, self.qcode)
		ensure_unique_source_key("Trivia Question", self.source_key, self.name)
