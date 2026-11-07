from frappe.model.document import Document
import frappe
from trivia_sync.integrations.identity import ensure_unique_source_key, source_identity


class TriviaProva(Document):
	def validate(self):
		self.source_id, self.source_key = source_identity(self.source_type or "QAPI", self.source_id, self.qapi_id)
		ensure_unique_source_key("Prova", self.source_key, self.name)
		questions = [row.question for row in self.exam_questions if row.question]
		if len(questions) != len(set(questions)):
			frappe.throw("Uma questão não pode aparecer mais de uma vez na mesma prova.")
		previous = self.get_doc_before_save() if not self.is_new() else None
		if previous and previous.status == "Published" and previous.lms_quiz == self.lms_quiz:
			if self._questions_signature(previous.exam_questions) != self._questions_signature(self.exam_questions):
				frappe.throw("Não altere questões de uma versão publicada; monte e publique uma nova versão.")
		if self.status == "Published" and (
			not self.lms_quiz or not self.lms_lesson or not any(
				row.version == self.exam_version and row.status == "Published" for row in self.exam_versions
			)
		):
			frappe.throw("Uma prova publicada precisa apontar para uma versão de quiz publicada e uma aula LMS.")

	def _questions_signature(self, rows):
		return [(row.question, row.exam_block, row.ordem, row.marks) for row in rows]
