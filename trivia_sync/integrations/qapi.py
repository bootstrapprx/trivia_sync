import frappe
from trivia_sync.integrations.qapi_client import QAPIClient, QAPIError
from trivia_sync.integrations.sync import sync_qapi_full


def settings():
    return frappe.get_single("Trivia Sync Settings")


def test_qapi_connection():
    try:
        payload = QAPIClient().questoes(page=1, size=1)
        return {"ok": True, "total": payload.get("total", 0) if isinstance(payload, dict) else 0, "page": payload.get("page", 1) if isinstance(payload, dict) else 1}
    except Exception as exc:
        frappe.log_error(frappe.get_traceback(), "Trivia Sync · QAPI connection")
        return {"ok": False, "error": str(exc)}


def sync_qapi_questions():
    return sync_qapi_full()
