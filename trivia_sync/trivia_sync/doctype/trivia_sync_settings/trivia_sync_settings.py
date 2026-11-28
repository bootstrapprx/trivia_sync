from frappe.model.document import Document
from frappe.utils import cint

from trivia_sync.whitelabel import apply_whitelabel


class TriviaSyncSettings(Document):
	def validate(self):
		for field in self.meta.get("fields", {"fieldtype": "Password"}):
			if not self.get(field.fieldname) and self.get_password(field.fieldname, raise_exception=False):
				self.set(field.fieldname, "********")

	def on_update(self):
		if cint(self.get("whitelabel_enabled")):
			apply_whitelabel(force=True)
