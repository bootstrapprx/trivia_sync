import frappe
import requests
from trivia_sync.integrations.normalization import answer_letter, normalize_question

BASE_DEFAULT = "https://qapi.otunac.com/api"


def settings():
    return frappe.get_single("Trivia Sync Settings")


def _api_key(doc):
    return doc.get_password("qapi_api_key") if doc.qapi_api_key else ""


def _get(doc, path, params=None):
    base = (doc.qapi_base_url or BASE_DEFAULT).rstrip("/")
    response = requests.get(f"{base}/{path.lstrip('/')}", headers={"Accept": "application/json", "Q-Api-Key": _api_key(doc)}, params=params or {}, timeout=30)
    response.raise_for_status()
    return response.json()


def test_qapi_connection():
    doc = settings()
    if not _api_key(doc):
        return {"ok": False, "error": "Configure o Q-Api-Key antes de testar."}
    try:
        payload = _get(doc, "/questoes", {"page": 1, "size": 1})
        return {"ok": True, "total": payload.get("total", 0), "page": payload.get("page", 1)}
    except requests.RequestException as exc:
        frappe.log_error(frappe.get_traceback(), "Trivia Sync · QAPI connection")
        return {"ok": False, "error": str(exc)}


def _save_question(data):
    if not data["qcode"] or not data["enunciado"]:
        return "skipped"
    name = frappe.db.exists("Trivia Question", {"qcode": data["qcode"]})
    if name:
        doc = frappe.get_doc("Trivia Question", name)
        if doc.sync_hash == data["sync_hash"]:
            return "skipped"
        for key, value in data.items():
            setattr(doc, key, value)
        doc.last_synced_at = frappe.utils.now_datetime()
        doc.save(ignore_permissions=True)
        return "updated"
    doc = frappe.get_doc({"doctype": "Trivia Question", **data, "last_synced_at": frappe.utils.now_datetime()})
    doc.insert(ignore_permissions=True)
    return "created"


def sync_qapi_questions():
    doc = settings()
    if not _api_key(doc):
        raise frappe.ValidationError("Configure o Q-Api-Key antes de sincronizar.")
    run = frappe.new_doc("Trivia Sync Run")
    run.source, run.operation, run.status, run.started_at = "QAPI", "Pull questions", "Running", frappe.utils.now_datetime()
    run.insert(ignore_permissions=True)
    created = updated = skipped = errors = 0
    messages = []
    try:
        max_pages = max(1, min(int(doc.qapi_max_pages or 10), 1000))
        size = max(1, min(int(doc.qapi_page_size or 10), 10))
        for page in range(1, max_pages + 1):
            payload = _get(doc, "/questoes", {"page": page, "size": size})
            run.page = page
            for row in payload.get("questoes", []):
                try:
                    result = _save_question(normalize_question(row))
                    if result == "created": created += 1
                    elif result == "updated": updated += 1
                    else: skipped += 1
                except Exception as exc:
                    errors += 1
                    messages.append(f"{row.get('qCode', '?')}: {exc}")
            frappe.db.commit()
            if page >= int(payload.get("pages", page)):
                break
        run.status = "Partial" if errors else "Completed"
        run.records_created, run.records_updated, run.records_skipped, run.records_errors = created, updated, skipped, errors
        if doc.qapi_enabled:
            doc.last_qapi_sync_at = frappe.utils.now_datetime()
            doc.save(ignore_permissions=True)
    except Exception:
        run.status = "Failed"
        messages.append(frappe.get_traceback())
        frappe.log_error(frappe.get_traceback(), "Trivia Sync · QAPI sync")
        raise
    finally:
        run.finished_at, run.error_log = frappe.utils.now_datetime(), "\n".join(messages)
        run.save(ignore_permissions=True)
        frappe.db.commit()
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}
