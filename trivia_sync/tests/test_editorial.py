import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch


class TestEditorialGate(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.modules.setdefault("frappe", types.SimpleNamespace())
		cls.editorial = importlib.import_module("trivia_sync.integrations.editorial")
		cls.projection = importlib.import_module("trivia_sync.integrations.lms_questions")

	def source(self, **overrides):
		values = dict(
			name="TQ-1", source_key="qapi:Q-1", qcode="Q-1", enunciado="Question?", options=json.dumps({"A": "Yes", "B": "No"}),
			correct_option="A", explanation="Because", review_status="Approved", redistribution_status="Approved", source_license="CC-BY",
			redistribution_reference="terms", texto_apoio=None, sync_hash="sync", ai_enrichment_hash="", ai_difficulty_stars=0,
			banca="Board", orgao="Agency", cargo="Role", ano=2024, materia="Math", assunto="Algebra", source_url="https://source.invalid",
			ai_difficulty_label="", ai_difficulty_reason="", ai_learning_objective="", ai_topics="[]", ai_model="", ai_enriched_at=None,
			save=lambda **kwargs: None,
		)
		values.update(overrides)
		return types.SimpleNamespace(**values)

	def test_pending_or_rejected_question_cannot_be_projected(self):
		frappe = self.editorial.frappe
		for source in (self.source(review_status="Pending"), self.source(redistribution_status="Rejected")):
			with self.subTest(source=source), self.assertRaises(Exception), patch.object(
				frappe, "new_doc", side_effect=AssertionError("must reject before LMS writes")
			):
				self.projection.sync_lms_question(source)

	def test_projection_requires_recorded_license_and_valid_answer_shape(self):
		frappe = self.editorial.frappe
		with self.assertRaises(Exception):
			self.editorial.validate_projection_eligibility(self.source(source_license="", redistribution_reference=""))
		with self.assertRaises(Exception):
			self.editorial.validate_projection_eligibility(self.source(correct_option="C"))

	def test_review_requires_reviewer_role_and_records_transition(self):
		frappe = self.editorial.frappe
		doc = self.source(save=lambda **kwargs: None)
		with patch.object(frappe, "get_roles", return_value=["Trivia Reviewer"]), patch.object(
			frappe, "get_doc", return_value=doc
		), patch.object(frappe, "session", types.SimpleNamespace(user="reviewer@example.com")), patch.object(
			frappe.utils, "now_datetime", return_value="now"
		):
			result = self.editorial.review_question("TQ-1", "approved", "Conferida")
		self.assertEqual(result["review_status"], "Approved")
		self.assertEqual((doc.reviewed_by, doc.reviewed_at, doc.review_reason), ("reviewer@example.com", "now", "Conferida"))

	def test_review_denies_user_without_reviewer_role(self):
		frappe = self.editorial.frappe
		with patch.object(frappe, "get_roles", return_value=["Trivia Editor"]), patch.object(
			frappe, "session", types.SimpleNamespace(user="editor@example.com")
		), self.assertRaises(frappe.PermissionError):
			self.editorial.review_question("TQ-1", "approved")

	def test_projection_is_idempotent_by_stable_source_identity(self):
		frappe = self.projection.frappe
		store = {}
		class FakeDB:
			def get_value(self, doctype, filters, field):
				key = filters.get("trivia_projection_key") or filters.get("trivia_source_key") or filters.get("trivia_qcode")
				field = "trivia_projection_key" if filters.get("trivia_projection_key") else ("trivia_source_key" if filters.get("trivia_source_key") else "trivia_qcode")
				return next((name for name, doc in store.items() if doc.get(field) == key), None)
		class FakeDoc:
			def __init__(self, values=None): self.values = values or {}; self.name = "LQ-1"
			def set(self, field, value): self.values[field] = value
			def __getattr__(self, field): return self.values.get(field)
			def is_new(self): return self.name not in store
			def insert(self, **kwargs): store[self.name] = self.values
			def save(self, **kwargs): store[self.name] = self.values
		old_db = frappe.db
		frappe.db = FakeDB()
		old = {key: getattr(frappe, key, None) for key in ("new_doc", "get_doc", "utils")}
		frappe.new_doc = lambda doctype: FakeDoc()
		frappe.get_doc = lambda doctype, name: FakeDoc(store[name])
		frappe.utils = types.SimpleNamespace(now_datetime=lambda: "now")
		try:
			source = self.source(save=lambda **kwargs: None)
			first = self.projection.sync_lms_question(source)
			second = self.projection.sync_lms_question(source)
		finally:
			frappe.db = old_db
			for key, value in old.items():
				if value is None: delattr(frappe, key)
				else: setattr(frappe, key, value)
		self.assertEqual((first, second, len(store)), ("LQ-1", "LQ-1", 1))
		self.assertEqual(store["LQ-1"]["trivia_source_key"], "qapi:Q-1")

	def test_legacy_backfill_links_only_matching_qcodes(self):
		frappe = self.editorial.frappe
		patch_module = importlib.import_module("trivia_sync.patches.v0_3.backfill_legacy_lms_questions")
		rows = [
			types.SimpleNamespace(name="LQ-1", trivia_qcode="Q-1", trivia_question=None),
			types.SimpleNamespace(name="LQ-unrelated", trivia_qcode="other", trivia_question=None),
		]
		with patch.object(frappe, "get_all", return_value=rows), patch.object(
			frappe.db, "get_value", side_effect=["TQ-1", "qapi:Q-1", None]
		), patch.object(frappe.db, "set_value") as set_value:
			counts = patch_module.execute()
		self.assertEqual(counts, {"checked": 2, "linked": 1, "unmatched": 1})
		set_value.assert_called_once_with(
			"LMS Question", "LQ-1", {"trivia_question": "TQ-1", "trivia_source_key": "qapi:Q-1"}, update_modified=False
		)

	def test_projection_failure_is_retryable_and_keeps_editorial_approval(self):
		frappe = self.editorial.frappe
		api = importlib.import_module("trivia_sync.api")
		source = self.source(save=lambda **kwargs: None)
		with patch.object(frappe, "only_for"), patch.object(frappe, "get_doc", return_value=source), patch.object(
			api, "sync_lms_question", side_effect=RuntimeError("temporary LMS error")
		):
			result = api.project_question("TQ-1")
		self.assertEqual(result["status"], "Failed")
		self.assertEqual(source.review_status, "Approved")
		self.assertEqual(source.projection_status, "Failed")

	def test_changed_question_used_by_quiz_creates_a_new_lms_question_version(self):
		frappe = self.projection.frappe
		old_values = {"trivia_source_key": "qapi:Q-1", "trivia_projection_key": "old-version", "trivia_sync_hash": "old"}
		store = {"LQ-old": old_values.copy()}
		class FakeDB:
			def get_value(self, doctype, filters, field):
				for name, values in store.items():
					if all(values.get(key) == value for key, value in filters.items()): return name
				return None
			def exists(self, doctype, filters): return "LMS Quiz Question" if doctype == "LMS Quiz Question" else None
		class FakeDoc:
			def __init__(self, name="LQ-new", values=None): self.name=name; self.values=values or {}
			def set(self, field, value): self.values[field]=value
			def __getattr__(self, field): return self.values.get(field)
			def is_new(self): return self.name not in store
			def insert(self, **kwargs): store[self.name]=self.values
			def save(self, **kwargs): store[self.name]=self.values
		old_db=frappe.db; frappe.db=FakeDB()
		old_get=frappe.get_doc; old_new=frappe.new_doc; old_utils=frappe.utils
		frappe.get_doc=lambda doctype,name: FakeDoc(name,store[name])
		frappe.new_doc=lambda doctype: FakeDoc()
		frappe.utils=types.SimpleNamespace(now_datetime=lambda:"now")
		try:
			source=self.source(sync_hash="new")
			result=self.projection.sync_lms_question(source)
		finally:
			frappe.db=old_db; frappe.get_doc=old_get; frappe.new_doc=old_new; frappe.utils=old_utils
		self.assertEqual(result,"LQ-new")
		self.assertEqual(store["LQ-old"]["trivia_sync_hash"],"old")
		self.assertEqual(source.lms_question,"LQ-new")


if __name__ == "__main__":
	unittest.main()
