from frappe.model.document import Document
import frappe
from trivia_sync.integrations.identity import ensure_unique_source_key, source_identity
from trivia_sync.integrations.reconciliation import _catalog_get_value


class TriviaConteudo(Document):
	def validate(self):
		self.source_id, self.source_key = source_identity(self.source_type or "QAPI", self.source_id, self.qapi_id)
		ensure_unique_source_key("Trivia Syllabus Topic", self.source_key, self.name)
		if self.concurso_cargo and self.source_path:
			match = _catalog_get_value(
				"Trivia Syllabus Topic",
				{"concurso_cargo": self.concurso_cargo, "source_path": self.source_path},
				"name",
			)
			if match and match != self.name:
				frappe.throw("This syllabus path is already linked to this contest position.")
