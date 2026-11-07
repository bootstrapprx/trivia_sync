import importlib
import sys
import types
import unittest
from unittest.mock import patch


class TestSourceIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("frappe", types.SimpleNamespace())
        cls.module = importlib.import_module("trivia_sync.integrations.identity")

    def test_identity_uses_source_type_and_external_id(self):
        self.assertEqual(
            self.module.source_identity("Hugging Face", "dataset/row-7"),
            ("dataset/row-7", "hugging-face:dataset/row-7"),
        )

    def test_identity_uses_legacy_qcode_as_source_id(self):
        self.assertEqual(self.module.source_identity("QAPI", qcode="Q-123"), ("Q-123", "qapi:Q-123"))

    def test_duplicate_identity_is_rejected_but_current_record_is_allowed(self):
        frappe = self.module.frappe
        old_db = getattr(frappe, "db", None)
        frappe.db = types.SimpleNamespace(get_value=lambda *args: "QUESTION-1")
        try:
            with patch.object(frappe, "throw", side_effect=ValueError, create=True):
                with self.assertRaises(ValueError):
                    self.module.ensure_unique_source_key("Trivia Question", "qapi:Q-1", "QUESTION-2")
                self.module.ensure_unique_source_key("Trivia Question", "qapi:Q-1", "QUESTION-1")
        finally:
            if old_db is None:
                del frappe.db
            else:
                frappe.db = old_db
