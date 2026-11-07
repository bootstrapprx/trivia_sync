from frappe.model.document import Document
import frappe
from trivia_sync.integrations.identity import ensure_unique_source_key, source_identity


class TriviaConteudo(Document):
	def validate(self):
		self.source_id, self.source_key = source_identity(self.source_type or "QAPI", self.source_id, self.qapi_id)
		ensure_unique_source_key("Conteúdo Programático", self.source_key, self.name)
		if self.concurso_cargo and self.source_path:
			match = frappe.db.exists(
				"Conteúdo Programático",
				{"concurso_cargo": self.concurso_cargo, "source_path": self.source_path},
			)
			if match and match != self.name:
				frappe.throw("Este caminho da ementa já está vinculado ao cargo do concurso.")
