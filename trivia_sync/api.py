import frappe
from frappe.utils import cint

from trivia_sync.integrations.frappe_lms import sync_existing_lms_to_trivia
from trivia_sync.integrations.qapi import sync_qapi_questions, test_qapi_connection


@frappe.whitelist()
def onboarding_status():
    frappe.only_for("System Manager")
    doc = frappe.get_single("Trivia Sync Settings")
    return {
        "configured": bool(doc.qapi_api_key),
        "enabled": bool(doc.qapi_enabled),
        "frequency": doc.qapi_sync_frequency or "Hourly",
        "base_url": doc.qapi_base_url,
        "last_sync": doc.last_qapi_sync_at,
    }


@frappe.whitelist()
def save_onboarding(qapi_api_key=None, qapi_enabled=0, qapi_sync_frequency="Hourly", qapi_base_url=None):
    frappe.only_for("System Manager")
    if qapi_sync_frequency not in ("Hourly", "Every scheduler tick"):
        frappe.throw("Frequência de sincronização inválida.")
    doc = frappe.get_single("Trivia Sync Settings")
    doc.qapi_enabled = cint(qapi_enabled)
    doc.qapi_sync_frequency = qapi_sync_frequency
    doc.qapi_base_url = (qapi_base_url or "https://qapi.otunac.com/api").strip().rstrip("/")
    doc.save()
    if qapi_api_key:
        doc.set_password("qapi_api_key", qapi_api_key)
    return onboarding_status()


@frappe.whitelist()
def enqueue_qapi_sync():
    frappe.only_for("System Manager")
    frappe.enqueue("trivia_sync.integrations.qapi.sync_qapi_questions", queue="long", job_name="trivia_sync_qapi_questions", enqueue_after_commit=True)
    return {"queued": True, "job": "trivia_sync_qapi_questions"}


@frappe.whitelist()
def enqueue_lms_sync():
    frappe.only_for("System Manager")
    frappe.enqueue("trivia_sync.integrations.frappe_lms.sync_existing_lms_to_trivia", queue="long", job_name="trivia_sync_lms_to_trivia", enqueue_after_commit=True)
    return {"queued": True, "job": "trivia_sync_lms_to_trivia"}


@frappe.whitelist()
def qapi_status():
    frappe.only_for("System Manager")
    return test_qapi_connection()


@frappe.whitelist()
def run_qapi_sync_now():
    frappe.only_for("System Manager")
    return sync_qapi_questions()


@frappe.whitelist()
def run_lms_sync_now():
    frappe.only_for("System Manager")
    return sync_existing_lms_to_trivia()
