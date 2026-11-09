import json

import frappe
from frappe.model.document import Document

from trivia_sync.integrations.editorial import question_options, validate_editorial_transition
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
		try:
			options = json.loads(self.options or "{}")
		except (TypeError, ValueError):
			options = {}
		self.detected_option_count = sum(1 for value in options.values() if value not in (None, "")) if isinstance(options, dict) else 0
		previous = self.get_doc_before_save() if not self.is_new() else None
		if previous:
			content_fields = ("enunciado", "options", "correct_option", "correct_options", "explanation", "texto_apoio", "marks")
			if any(getattr(previous, field, None) != getattr(self, field, None) for field in content_fields):
				self.review_status = "Pending"
				self.reviewed_by = self.reviewed_at = self.review_reason = None
				self.editorial_status = "Pending Review"
			if previous.source_license != self.source_license or previous.source_attribution != self.source_attribution:
				self.redistribution_status = "Pending"
				self.redistribution_decided_by = self.redistribution_decided_at = None
		if self.editorial_status in ("Approved", "Published"):
			question_options(self)
		validate_editorial_transition(
			previous.editorial_status if previous else None,
			self.editorial_status or "Imported",
			frappe.get_roles(frappe.session.user),
			is_new=not previous,
		)
