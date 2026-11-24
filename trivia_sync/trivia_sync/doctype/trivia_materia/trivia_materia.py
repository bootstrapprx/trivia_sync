from frappe.model.document import Document
from trivia_sync.integrations.identity import apply_optional_qapi_identity, autoname_optional_qapi


class TriviaMateria(Document):
	def autoname(self):
		autoname_optional_qapi(self)

	def validate(self):
		apply_optional_qapi_identity(self, "Trivia Subject")
