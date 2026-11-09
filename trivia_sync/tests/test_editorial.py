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
		cls.editorial.frappe.parse_json = json.loads
		cls.editorial.frappe.get_roles = lambda *args: []
		cls.editorial.frappe.get_all = lambda *args, **kwargs: []
		cls.editorial.frappe.get_doc = lambda *args, **kwargs: None
		cls.editorial.frappe.new_doc = lambda *args, **kwargs: None
		cls.editorial.frappe.only_for = lambda *args, **kwargs: None
		cls.editorial.frappe.whitelist = lambda *args, **kwargs: lambda fn: fn
		cls.editorial.frappe.throw = lambda message, exc=None: (_ for _ in ()).throw((exc or ValueError)(message))
		cls.editorial.frappe.logger = lambda *args, **kwargs: types.SimpleNamespace(info=lambda *a, **k: None)
		cls.editorial.frappe.PermissionError = type("PermissionError", (Exception,), {})
		cls.editorial.frappe.session = types.SimpleNamespace(user="Administrator")
		cls.editorial.frappe.utils = types.SimpleNamespace(now_datetime=lambda: "now")
		cls.editorial.frappe.db = types.SimpleNamespace(exists=lambda *args, **kwargs: True, get_value=lambda *args, **kwargs: None, set_value=lambda *args, **kwargs: None)
		utils_module = types.ModuleType("frappe.utils")
		utils_module.__path__ = []
		utils_module.cint = lambda value=0: int(value or 0)
		sys.modules.setdefault("frappe.utils", utils_module)
		html_utils = types.ModuleType("frappe.utils.html_utils")
		html_utils.sanitize_html = lambda value: value
		sys.modules.setdefault("frappe.utils.html_utils", html_utils)
		pdf_utils = types.ModuleType("frappe.utils.pdf")
		pdf_utils.get_pdf = lambda *args, **kwargs: b""
		sys.modules.setdefault("frappe.utils.pdf", pdf_utils)
		cls.projection = importlib.import_module("trivia_sync.integrations.lms_questions")

	def source(self, **overrides):
		values = dict(
			name="TQ-1", source_key="qapi:Q-1", qcode="Q-1", enunciado="Question?", options=json.dumps(dict(zip("ABCDE", ["Yes", "No", "Maybe", "Later", "Never"]))),
			correct_option="A", correct_options='["A"]', detected_option_count=5, allow_variable_options=0, exception_reason="",
			editorial_difficulty=3, marks=2, editorial_status="Approved", explanation="Because", review_status="Approved", redistribution_status="Approved", source_license="CC-BY",
			source_attribution="Attribution required", source_authors="Author A", redistribution_reference="terms", texto_apoio=None, sync_hash="sync", ai_enrichment_hash="", ai_difficulty_stars=0,
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
			self.editorial.validate_projection_eligibility(self.source(correct_options='["F"]'))

	def test_standard_choices_require_exactly_five_options(self):
		for count in (4, 6):
			with self.subTest(count=count), self.assertRaises(Exception):
				self.editorial.validate_projection_eligibility(self.source(options=json.dumps(dict(zip("ABCDEF", range(count)))), correct_options='["A"]'))

	def test_variable_option_exception_requires_authorization_and_reason(self):
		question = self.source(options='{"A":"one","B":"two","C":"three","D":"four"}', correct_options='["A"]', detected_option_count=4, allow_variable_options=1, exception_reason="Original exam has four options")
		self.assertEqual(len(self.editorial.validate_projection_eligibility(question)), 4)
		with self.assertRaises(Exception):
			self.editorial.validate_projection_eligibility(self.source(options='{"A":"one","B":"two","C":"three","D":"four"}', correct_options='["A"]', allow_variable_options=1))

	def test_all_correct_answers_must_exist_and_are_preserved(self):
		question = self.source(correct_options='["B","D"]', multiple=1)
		self.assertEqual(self.editorial.validate_projection_eligibility(question), json.loads(question.options))
		with self.assertRaises(Exception):
			self.editorial.validate_projection_eligibility(self.source(correct_options='["F"]'))

	def test_answer_count_outside_lms_limit_is_rejected(self):
		options = dict(zip("ABCDEFGHIJ", [str(n) for n in range(10)]))
		options["K"] = "eleven"
		with self.assertRaises(Exception):
			self.editorial.validate_projection_eligibility(self.source(options=json.dumps(options), correct_options='["A"]', allow_variable_options=1, exception_reason="Legacy format"))

	def test_review_requires_reviewer_role_and_records_transition(self):
		frappe = self.editorial.frappe
		doc = self.source(editorial_status="Pending Approval", save=lambda **kwargs: None)
		with patch.object(frappe, "get_roles", return_value=["Trivia Reviewer"]), patch.object(
			frappe, "get_doc", return_value=doc
		), patch.object(frappe, "session", types.SimpleNamespace(user="reviewer@example.com")), patch.object(
			frappe.utils, "now_datetime", return_value="now"
		):
			result = self.editorial.review_question("TQ-1", "approved", "Conferida")
		self.assertEqual(result["review_status"], "Approved")
		self.assertEqual((doc.reviewed_by, doc.reviewed_at, doc.review_reason), ("reviewer@example.com", "now", "Conferida"))
		self.assertEqual(doc.editorial_status, "Approved")

	def test_approval_rejects_invalid_question_even_when_reviewer_role_is_present(self):
		frappe = self.editorial.frappe
		doc = self.source(editorial_status="Pending Approval", options='{"A":"one","B":"two","C":"three","D":"four"}', correct_options='["A"]', save=lambda **kwargs: None)
		with patch.object(frappe, "get_roles", return_value=["Trivia Reviewer"]), patch.object(
			frappe, "get_doc", return_value=doc
		), patch.object(frappe, "session", types.SimpleNamespace(user="reviewer@example.com")), patch.object(
			frappe.utils, "now_datetime", return_value="now"
		), patch.object(frappe, "throw", side_effect=ValueError, create=True), self.assertRaises(ValueError):
			self.editorial.review_question("TQ-1", "approved")
		self.assertEqual(doc.editorial_status, "Pending Approval")

	def test_review_denies_user_without_reviewer_role(self):
		frappe = self.editorial.frappe
		with patch.object(frappe, "get_roles", return_value=["Trivia Editor"]), patch.object(
			frappe, "session", types.SimpleNamespace(user="editor@example.com")
		), self.assertRaises(frappe.PermissionError):
			self.editorial.review_question("TQ-1", "approved")

	def test_editorial_states_advance_only_through_the_review_flow(self):
		frappe = self.editorial.frappe
		doc = self.source(editorial_status="Imported", save=lambda **kwargs: None)
		with patch.object(frappe, "get_roles", return_value=["Trivia Editor"]), patch.object(
			frappe, "get_doc", return_value=doc
		):
			result = self.editorial.transition_question("TQ-1", "Pending Review")
		self.assertEqual(result["editorial_status"], "Pending Review")
		with patch.object(frappe, "get_roles", return_value=["Trivia Editor"]), patch.object(
			frappe, "get_doc", return_value=doc
		), patch.object(frappe, "throw", side_effect=ValueError, create=True), self.assertRaises(ValueError):
			self.editorial.transition_question("TQ-1", "Approved")

	def test_editorial_transition_validator_blocks_role_and_state_bypass(self):
		self.editorial.validate_editorial_transition("In Review", "Pending Approval", ["Trivia Editor"])
		self.editorial.validate_editorial_transition("Published", "Published", [])
		for previous, target, roles in (
			("Imported", "Approved", ["Trivia Reviewer"]),
			("In Review", "Approved", ["Trivia Reviewer"]),
			("Pending Approval", "Approved", ["Trivia Editor"]),
		):
			with self.subTest(previous=previous, target=target), patch.object(
				self.editorial.frappe, "throw", side_effect=ValueError, create=True
			), self.assertRaises(ValueError):
				self.editorial.validate_editorial_transition(previous, target, roles)

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
			source = self.source(correct_options='["B","D"]', save=lambda **kwargs: None)
			first = self.projection.sync_lms_question(source)
			second = self.projection.sync_lms_question(source)
		finally:
			frappe.db = old_db
			for key, value in old.items():
				if value is None: delattr(frappe, key)
				else: setattr(frappe, key, value)
		self.assertEqual((first, second, len(store)), ("LQ-1", "LQ-1", 1))
		self.assertEqual(store["LQ-1"]["trivia_source_key"], "qapi:Q-1")
		self.assertEqual([store["LQ-1"][f"option_{i}"] for i in range(1, 6)], ["Yes", "No", "Maybe", "Later", "Never"])
		self.assertEqual([store["LQ-1"][f"is_correct_{i}"] for i in range(1, 6)], [0, 1, 0, 1, 0])
		self.assertEqual(store["LQ-1"]["multiple"], 1)
		self.assertEqual(store["LQ-1"]["explanation_2"], "Because")
		self.assertEqual(store["LQ-1"]["explanation_4"], "Because")
		self.assertEqual(store["LQ-1"]["marks"], 2)
		self.assertEqual(store["LQ-1"]["trivia_editorial_difficulty"], 3)
		self.assertEqual(store["LQ-1"]["trivia_source_license"], "CC-BY")

	def test_lms_linked_question_cannot_be_edited_outside_its_source(self):
		frappe = self.projection.frappe
		source = self.source()
		fields = self.projection._projection_fields(source)
		class FakeQuestion(dict):
			__getattr__ = dict.get
		question = FakeQuestion({**fields, "trivia_question": source.name})
		with patch.object(frappe, "get_doc", return_value=source), patch.object(
			frappe, "throw", side_effect=ValueError, create=True
		):
			self.projection.validate_lms_question(question)
			question["option_1"] = "Changed directly in LMS"
			with self.assertRaises(ValueError):
				self.projection.validate_lms_question(question)

	def test_native_lms_questions_are_not_limited_by_trivia_rules(self):
		self.projection.validate_lms_question(types.SimpleNamespace(trivia_question=None))

	def test_linked_supporting_text_is_included_in_every_projection(self):
		frappe = self.projection.frappe
		source = self.source(texto_apoio="TXT-1")
		text = types.SimpleNamespace(conteudo="Support passage")
		with patch.object(frappe, "get_doc", return_value=text):
			fields = self.projection._projection_fields(source)
		self.assertIn("Support passage", fields["question"])
		self.assertEqual(fields["question"].count("Support passage"), 1)

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
