import importlib
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

    def test_client_clamps_page_size_to_qapi_limit(self):
        session = FakeSession()
        with patch.object(self.client_module.requests, "Session", return_value=session):
            client = self.client_module.QAPIClient(FakeSettings())
            client.questoes(page=2, size=99)
        self.assertEqual(session.get_calls[0][1]["params"], {"page": 2, "size": 10})
        self.assertEqual(session.headers["Q-Api-Key"], "secret")

    def test_worker_helpers_read_common_pagination_shapes(self):
        self.assertEqual(self.sync_module._rows({"data": [{"id": 1}]}), [{"id": 1}])
        self.assertEqual(self.sync_module._pages({"totalPages": 3}), 3)
        tree = list(self.sync_module._tree_rows({"items": [{"id": "root", "children": [{"id": "child"}]}]}))
        self.assertEqual([row["id"] for row in tree], ["root", "child"])
        self.assertEqual(tree[1]["parent_id"], "root")


if __name__ == "__main__":
    unittest.main()
