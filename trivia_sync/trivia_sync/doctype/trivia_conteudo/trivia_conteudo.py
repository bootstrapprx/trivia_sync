from frappe.model.document import Document
import frappe
from trivia_sync.integrations.identity import apply_optional_qapi_identity, autoname_optional_qapi
from trivia_sync.integrations.reconciliation import _catalog_get_value


class TriviaConteudo(Document):
	def autoname(self):
		autoname_optional_qapi(self)

	def validate(self):
		apply_optional_qapi_identity(self, "Trivia Syllabus Topic")
		if self.concurso_cargo and self.source_path:
			match = _catalog_get_value(
				"Trivia Syllabus Topic",
				{"concurso_cargo": self.concurso_cargo, "source_path": self.source_path},
				"name",
			)
			if match and match != self.name:
				frappe.throw("This syllabus path is already linked to this contest position.")
