import frappe
from frappe.model.document import Document

from trivia_sync.integrations.identity import ensure_unique_source_key, source_identity


class TriviaContestPosition(Document):
	"""Contest-specific position linking a contest to an existing catalog position/course."""

	def validate(self):
		self.source_id, self.source_key = source_identity(
			self.source_type or "Manual", self.source_id
		)
		ensure_unique_source_key("Trivia Contest Position", self.source_key, self.name)
		if self.concurso and not frappe.db.exists("Trivia Contest", self.concurso):
			frappe.throw("The selected contest does not exist.")
		if self.cargo and not frappe.db.exists("Trivia Position", self.cargo):
			frappe.throw("The selected catalog position does not exist.")
