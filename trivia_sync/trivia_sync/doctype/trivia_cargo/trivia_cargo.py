from frappe.model.document import Document
from trivia_sync.integrations.identity import ensure_unique_source_key, source_identity


class TriviaCargo(Document):
	def validate(self):
		self.source_id, self.source_key = source_identity(self.source_type or "QAPI", self.source_id, self.qapi_id)
		ensure_unique_source_key("Trivia Position", self.source_key, self.name)
