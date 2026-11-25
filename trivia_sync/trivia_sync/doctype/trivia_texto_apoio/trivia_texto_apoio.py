import frappe
from frappe.model.document import Document

from trivia_sync.integrations.identity import ensure_unique_source_key, source_identity


class TriviaTextoApoio(Document):
	def autoname(self):
		codigo = str(getattr(self, "codigo", None) or "").strip()
		if codigo:
			self.codigo = codigo
			self.name = codigo
			if not getattr(self, "source_type", None):
				self.source_type = "QAPI"
			return
		if not getattr(self, "source_type", None):
			self.source_type = "Manual"
		self.name = frappe.generate_hash(length=16)
		if not getattr(self, "source_id", None):
			self.source_id = self.name

	def validate(self):
		codigo = str(getattr(self, "codigo", None) or "").strip()
		source_type = str(getattr(self, "source_type", None) or "").strip()
		if not source_type:
			source_type = "QAPI" if codigo else "Manual"
		self.source_type = source_type
		if codigo:
			self.codigo = codigo
		elif source_type == "QAPI" and not getattr(self, "source_id", None):
			frappe.throw("Provide a QAPI code when Source type is QAPI.")
		source_id = getattr(self, "source_id", None) or codigo or getattr(self, "name", None) or frappe.generate_hash(length=16)
		self.source_id, self.source_key = source_identity(source_type, source_id, codigo or None)
		if hasattr(frappe, "db"):
			ensure_unique_source_key("Trivia Supporting Text", self.source_key, getattr(self, "name", None))
