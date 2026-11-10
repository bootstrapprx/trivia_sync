import importlib
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

from trivia_sync.integrations.normalization import normalize_question


class FakeSettings:
    qapi_base_url = "https://qapi.example.test/api"
    mcp_base_url = "https://qapi.example.test/mcp"
    qapi_timeout = 15
    qapi_api_key = "configured"
    mcp_enabled = 0
    qapi_max_requests_per_run = 10
    qapi_min_credit_reserve = 0
    qapi_max_pages = 5
    qapi_page_size = 10
    sync_catalogs = 1
    sync_exams = 1
    sync_flashcards = 1
    sync_support_texts = 1

    def get_password(self, fieldname):
        return "secret"


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.text = "response"

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(self.text)

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.get_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return FakeResponse({"questoes": [], "pages": 1})


class TestQAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("frappe", types.SimpleNamespace())
        cls.client_module = importlib.import_module("trivia_sync.integrations.qapi_client")
        cls.sync_module = importlib.import_module("trivia_sync.integrations.sync")

    def test_normalize_question_preserves_text_reference_and_options(self):
        result = normalize_question({
            "qCode": "Q-123", "enunciado": "Qual é a resposta?", "opcaoA": "Uma", "opcaoB": "Duas",
            "gabarito": "B", "textoCodigo": "TXT-9", "materia": "Direito", "ano": 2024,
        })
        self.assertEqual(result["qcode"], "Q-123")
        self.assertEqual(result["correct_option"], "B")
        self.assertEqual(result["texto_codigo"], "TXT-9")
        self.assertIn('"A": "Uma"', result["options"])

    def test_normalize_question_preserves_rich_content_and_array_options(self):
        result = normalize_question({
            "qCode": "Q-RICH",
            "enunciado": {"html": "Calcule \\(x^2 + 1\\)"},
            "alternativas": [
                {"letra": "A", "texto": "\\(x=1\\)"},
                {"letra": "B", "html": "<strong>\\(x=2\\)</strong>"},
            ],
            "gabarito": {"letra": "B"},
        })
        self.assertIn("\\(x^2 + 1\\)", result["enunciado"])
        self.assertIn("x=2", result["options"])
        self.assertEqual(result["correct_option"], "B")

    def test_normalize_question_preserves_options_beyond_e_and_multiple_answers(self):
        result = normalize_question({
            "qCode": "Q-MULTI",
            "enunciado": "Selecione as corretas",
            "alternativas": [
                {"letra": letter, "texto": letter}
                for letter in "ABCDEF"
            ],
            "gabarito": ["B", "F"],
        })
        self.assertEqual(json.loads(result["options"]), {letter: letter for letter in "ABCDEF"})
        self.assertEqual(json.loads(result["correct_options"]), ["B", "F"])
        self.assertEqual(result["correct_option"], "B")
        self.assertEqual(result["detected_option_count"], 6)

    def test_normalize_question_preserves_sparse_option_letters(self):
        result = normalize_question({
            "qCode": "Q-SPARSE",
            "alternativas": [
                {"letra": "A", "texto": "one"},
                {"letra": "C", "texto": "three"},
                {"letra": "F", "texto": "six"},
            ],
            "gabarito": {"letras": ["C", "F"]},
        })
        self.assertEqual(json.loads(result["options"]), {"A": "one", "C": "three", "F": "six"})
        self.assertEqual(json.loads(result["correct_options"]), ["C", "F"])

    def test_normalize_question_does_not_hide_options_above_lms_capacity(self):
        result = normalize_question({
            "qCode": "Q-TOO-MANY",
            "alternativas": [{"texto": f"option {index}"} for index in range(11)],
            "gabarito": ["A"],
        })
        self.assertEqual(result["detected_option_count"], 11)
        self.assertEqual(len(json.loads(result["options"])), 11)

    def test_client_clamps_page_size_to_qapi_limit(self):
        session = FakeSession()
        with patch.object(self.client_module.requests, "Session", return_value=session):
            client = self.client_module.QAPIClient(FakeSettings())
            client.questoes(page=2, size=99)
        self.assertEqual(session.get_calls[0][1]["params"], {"page": 2, "size": 10})
        self.assertEqual(session.headers["Q-Api-Key"], "secret")

    def test_client_refuses_zero_budget_before_network_call(self):
        session = FakeSession()
        with patch.object(self.client_module.requests, "Session", return_value=session):
            client = self.client_module.QAPIClient(FakeSettings(), max_requests=0)
            with self.assertRaises(self.client_module.QAPIBudgetError):
                client.questoes(page=1)
        self.assertEqual(session.get_calls, [])

    def test_client_stops_at_budget_and_tracks_cost_per_request(self):
        session = FakeSession()
        with patch.object(self.client_module.requests, "Session", return_value=session):
            client = self.client_module.QAPIClient(FakeSettings(), max_requests=1)
            client.questoes(page=1)
            with self.assertRaises(self.client_module.QAPIBudgetError):
                client.questoes(page=2)
        self.assertEqual(client.requests_made, 1)

    def test_exam_request_reserves_100_rest_credits_before_network_call(self):
        session = FakeSession()
        with patch.object(self.client_module.requests, "Session", return_value=session):
            client = self.client_module.QAPIClient(FakeSettings(), max_requests=99)
            with self.assertRaises(self.client_module.QAPIBudgetError):
                client.provas(page=1)
        self.assertEqual((client.requests_made, client.credits_used, session.get_calls), (0, 0, []))
        with patch.object(self.client_module.requests, "Session", return_value=session):
            funded_client = self.client_module.QAPIClient(FakeSettings(), max_requests=100)
            funded_client.provas(page=1)
        self.assertEqual((funded_client.requests_made, funded_client.credits_used), (1, 100))

    def test_mcp_exam_request_charges_twice_rest_cost(self):
        settings = FakeSettings()
        settings.mcp_enabled = 1
        client = self.client_module.QAPIClient(settings, max_requests=199)
        with self.assertRaises(self.client_module.QAPIBudgetError):
            client.provas(page=1)
        self.assertEqual((client.requests_made, client.credits_used), (0, 0))

    def test_dry_run_uses_exam_credit_cost(self):
        frappe = self.sync_module.frappe
        settings = FakeSettings()
        settings.qapi_max_pages = 1
        settings.qapi_page_size = 1
        settings.sync_catalogs = 1
        settings.sync_exams = 1
        settings.sync_flashcards = 0
        settings.sync_support_texts = 0
        old_get_single = getattr(frappe, "get_single", None)
        old_new_doc = getattr(frappe, "new_doc", None)
        frappe.get_single = lambda name: settings
        frappe.new_doc = lambda *args: self.fail("dry-run must not create a run record")
        try:
            result = self.sync_module.ingest_source(dry_run=True, max_pages=1)
        finally:
            if old_get_single is None:
                del frappe.get_single
            else:
                frappe.get_single = old_get_single
            if old_new_doc is None:
                del frappe.new_doc
            else:
                frappe.new_doc = old_new_doc
        self.assertGreaterEqual(result["projected_request_cost"], 200)

    def test_worker_helpers_read_common_pagination_shapes(self):
        self.assertEqual(self.sync_module._rows({"data": [{"id": 1}]}), [{"id": 1}])
        self.assertEqual(self.sync_module._pages({"totalPages": 3}), 3)
        tree = list(self.sync_module._tree_rows({"items": [{"id": "root", "children": [{"id": "child"}]}]}))
        self.assertEqual([row["id"] for row in tree], ["root", "child"])
        self.assertEqual(tree[1]["parent_id"], "root")

    def test_worker_helpers_read_nested_qapi_envelopes_and_page_metadata(self):
        self.assertEqual(self.sync_module._rows({"data": {"items": [{"id": "Q-1"}]}}), [{"id": "Q-1"}])
        self.assertEqual(self.sync_module._pages({"meta": {"pagination": {"total_pages": 4}}}), 4)

    def test_worker_rejects_unrecognized_question_page_instead_of_succeeding_empty(self):
        with self.assertRaises(self.sync_module.QAPIBudgetError.__bases__[0]):
            self.sync_module._rows({"status": "ok", "payload": "unexpected"})

    def test_qapi_filters_accept_documented_organization_filter(self):
        self.assertEqual(
            self.sync_module._validate_filters({"orgao": "Manaus Previdência", "ano": 2026}),
            {"orgao": "Manaus Previdência", "ano": 2026},
        )

    def test_paginated_resource_sync_forwards_filters_to_qapi(self):
        received = []

        class Adapter:
            def fetch_resource(self, method, **kwargs):
                received.append((method, kwargs))
                return {"concursos": [], "pages": 1}

        frappe = self.sync_module.frappe
        old_db = getattr(frappe, "db", None)
        frappe.db = types.SimpleNamespace(commit=lambda: None)
        try:
            self.sync_module._sync_paginated(
                Adapter(), "concursos", "Trivia Contest", "concursos",
                types.SimpleNamespace(qapi_page_size=10), 3,
                {"orgao": "Manaus Previdência", "ano": 2026},
            )
        finally:
            if old_db is None:
                del frappe.db
            else:
                frappe.db = old_db
        self.assertEqual(received, [("concursos", {"page": 1, "size": 10, "filters": {"orgao": "Manaus Previdência", "ano": 2026}})])

    def test_dry_run_reports_upper_bound_without_writes_or_network(self):
        frappe = self.sync_module.frappe
        old_get_single = getattr(frappe, "get_single", None)
        old_new_doc = getattr(frappe, "new_doc", None)
        frappe.get_single = lambda name: FakeSettings()
        frappe.new_doc = lambda *args: self.fail("dry-run must not create a run record")
        try:
            result = self.sync_module.ingest_source(dry_run=True, filters={"ano": 2024})
        finally:
            if old_get_single is None:
                del frappe.get_single
            else:
                frappe.get_single = old_get_single
            if old_new_doc is None:
                del frappe.new_doc
            else:
                frappe.new_doc = old_new_doc
        self.assertEqual(result["writes"], 0)
        self.assertTrue(result["projection_is_upper_bound"])
        self.assertEqual(result["filters"], {"ano": 2024})
        self.assertGreater(result["projected_request_cost"], 0)
        self.assertFalse(result["budget_sufficient_for_upper_bound"])

    def test_request_budget_keeps_configured_reserve(self):
        settings = FakeSettings()
        budget, reserve, spend_limit, pages = self.sync_module._limits(settings, None, 0)
        self.assertEqual((budget, reserve, spend_limit, pages), (10, 1, 9, 5))
        settings.qapi_min_credit_reserve = 4
        self.assertEqual(self.sync_module._limits(settings, None, 0), (10, 4, 6, 5))

    def test_full_plan_reserves_detail_status_and_flashcard_creation_costs(self):
        settings = FakeSettings()
        settings.qapi_max_pages = 1
        settings.qapi_page_size = 10
        settings.sync_exams = 1
        settings.push_flashcards = 1
        cost = self.sync_module._estimated_request_cost(settings, 1, True)
        self.assertGreaterEqual(cost, 2000)
        self.assertTrue(self.sync_module.DETAIL_ENDPOINTS["provas"])

    def test_endpoint_metrics_track_received_created_updated_and_failed(self):
        metrics = {}
        self.sync_module._record_metric(metrics, "get_concursos", received=2)
        self.sync_module._record_metric(metrics, "get_concursos", result="created")
        self.sync_module._record_metric(metrics, "get_concursos", result="updated")
        self.sync_module._record_metric(metrics, "get_concursos", failed=1)
        self.assertEqual(metrics["get_concursos"], {"received": 2, "created": 1, "updated": 1, "failed": 1})

    def test_repeating_same_question_payload_is_idempotent(self):
        frappe = self.sync_module.frappe
        old = {name: getattr(frappe, name, None) for name in ("db", "utils", "get_doc")}
        store = {}

        class FakeDB:
            def exists(self, doctype, filters):
                value = filters.get("source_key") or filters.get("qcode")
                return next((name for name, doc in store.items() if doc.source_key == value or doc.qcode == value), None)

            def get_value(self, doctype, filters, fieldname):
                name = self.exists(doctype, filters)
                return name if fieldname == "name" else getattr(store.get(name), fieldname, None)

        class FakeDoc:
            def __init__(self, values):
                self.__dict__.update(values)
                self._new = True

            def is_new(self):
                return self._new

            def insert(self, **kwargs):
                self.name = self.qcode
                self._new = False
                store[self.name] = self

            def save(self, **kwargs):
                store[self.name] = self

        frappe.db = FakeDB()
        frappe.utils = types.SimpleNamespace(now_datetime=lambda: "now")
        frappe.get_doc = lambda *args: FakeDoc(args[0]) if isinstance(args[0], dict) else store[args[1]]
        try:
            settings = types.SimpleNamespace(sync_support_texts=0)
            row = {"qCode": "Q-55", "enunciado": "Question?", "opcaoA": "A", "gabarito": "A"}
            first = self.sync_module._save_question(None, row, settings)
            second = self.sync_module._save_question(None, row, settings)
            store["Q-55"].source_authors = "Legacy normalization output"
            third = self.sync_module._save_question(None, row, settings)
            fourth = self.sync_module._save_question(None, row, settings)
        finally:
            for name, value in old.items():
                if value is None:
                    delattr(frappe, name)
                else:
                    setattr(frappe, name, value)
        self.assertEqual((first, second, third, fourth, len(store)), ("created", "skipped", "updated", "skipped", 1))


if __name__ == "__main__":
    unittest.main()
