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

    def test_optional_qapi_identity_supports_manual_and_qapi_records(self):
        frappe = self.module.frappe
        old_db = getattr(frappe, "db", None)
        old_hash = getattr(frappe, "generate_hash", None)
        frappe.db = types.SimpleNamespace(get_value=lambda *args: None)
        frappe.generate_hash = lambda length=16: "manualhash123456"[:length]
        try:
            manual = types.SimpleNamespace(qapi_id="", source_type="Manual", source_id="", source_key="", name="")
            self.module.autoname_optional_qapi(manual)
            self.module.apply_optional_qapi_identity(manual, "Trivia Contest")
            self.assertEqual(manual.name, "manualhash123456")
            self.assertEqual(manual.source_type, "Manual")
            self.assertEqual(manual.source_key, "manual:manualhash123456")

            qapi_doc = types.SimpleNamespace(qapi_id="QAPI-99", source_type="QAPI", source_id="", source_key="", name="")
            self.module.autoname_optional_qapi(qapi_doc)
            self.module.apply_optional_qapi_identity(qapi_doc, "Trivia Contest")
            self.assertEqual(qapi_doc.name, "QAPI-99")
            self.assertEqual(qapi_doc.source_key, "qapi:QAPI-99")

            missing_qapi = types.SimpleNamespace(qapi_id="", source_type="QAPI", source_id="", source_key="", name="X")
            with patch.object(frappe, "throw", side_effect=ValueError, create=True), self.assertRaises(ValueError):
                self.module.apply_optional_qapi_identity(missing_qapi, "Trivia Contest")
        finally:
            if old_db is None:
                del frappe.db
            else:
                frappe.db = old_db
            if old_hash is None:
                del frappe.generate_hash
            else:
                frappe.generate_hash = old_hash

    def test_no_doctype_requires_qapi_id_unconditionally(self):
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "trivia_sync" / "doctype"
        for path in sorted(root.glob("*/*.json")):
            data = json.loads(path.read_text())
            self.assertNotEqual(data.get("autoname"), "field:qapi_id", f"{data.get('name')} still autonames by qapi_id")
            for field in data.get("fields", []):
                if field.get("fieldname") == "qapi_id":
                    self.assertEqual(field.get("reqd", 0), 0, f"{data.get('name')}.qapi_id is still reqd=1")
