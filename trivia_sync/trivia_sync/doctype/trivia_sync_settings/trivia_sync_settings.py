from frappe.model.document import Document


class TriviaSyncSettings(Document):
	def validate(self):
		for field in self.meta.get("fields", {"fieldtype": "Password"}):
			if not self.get(field.fieldname) and self.get_password(field.fieldname, raise_exception=False):
				self.set(field.fieldname, "********")
