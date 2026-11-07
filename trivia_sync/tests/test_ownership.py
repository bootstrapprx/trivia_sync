import importlib
import sys
import types
import unittest


class TestSourceOwnership(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("frappe", types.SimpleNamespace())
        cls.module = importlib.import_module("trivia_sync.integrations.ownership")

    def test_source_update_preserves_editorial_ai_and_projection_fields(self):
        doc = types.SimpleNamespace(
            content_hash="old", review_status="Approved", reviewed_by="editor@example.com", reviewed_at="yesterday",
            review_reason="Checked", editorial_notes="Keep this", ai_enrichment_status="Fresh",
            ai_difficulty_stars=4, lms_question="LMS-Q-1", projection_status="Projected",
        )
        changed = self.module.update_source_owned_fields(
            doc,
            {"qcode": "Q-1", "enunciado": "New prompt", "content_hash": "new", "banca": "New board"},
            "Trivia Question",
        )
        self.assertTrue(changed)
        self.assertEqual(doc.enunciado, "New prompt")
        self.assertEqual(doc.review_status, "Pending")
        self.assertEqual(doc.ai_enrichment_status, "Stale")
        self.assertEqual((doc.reviewed_by, doc.reviewed_at, doc.review_reason), (None, None, None))
        self.assertEqual(doc.editorial_notes, "Keep this")
        self.assertEqual((doc.ai_difficulty_stars, doc.lms_question, doc.projection_status), (4, "LMS-Q-1", "Projected"))

    def test_metadata_only_update_does_not_reset_approval(self):
        doc = types.SimpleNamespace(content_hash="same", review_status="Approved", reviewed_by="reviewer")
        changed = self.module.update_source_owned_fields(
            doc, {"banca": "Updated board", "content_hash": "same"}, "Trivia Question"
        )
        self.assertFalse(changed)
        self.assertEqual((doc.review_status, doc.reviewed_by), ("Approved", "reviewer"))

    def test_license_change_resets_only_redistribution_decision(self):
        doc = types.SimpleNamespace(
            content_hash="same", source_license="CC-BY", source_attribution="Source A",
            redistribution_status="Approved", redistribution_decided_by="reviewer", editorial_notes="Local",
        )
        self.module.update_source_owned_fields(
            doc, {"content_hash": "same", "source_license": "CC0", "source_attribution": "Source A"},
            "Trivia Question",
        )
        self.assertEqual((doc.redistribution_status, doc.redistribution_decided_by), ("Pending", None))
        self.assertEqual(doc.editorial_notes, "Local")

    def test_resource_update_ignores_fields_outside_source_allowlist(self):
        doc = types.SimpleNamespace(nome="Original", editorial_notes="Local")
        self.module.update_source_owned_fields(
            doc, {"nome": "From source", "editorial_notes": "Overwritten"}, "Banca"
        )
        self.assertEqual((doc.nome, doc.editorial_notes), ("From source", "Local"))
