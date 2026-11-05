import frappe

from trivia_sync.integrations.frappe_lms import sync_existing_lms_to_trivia
from trivia_sync.integrations.qapi import sync_qapi_questions, test_qapi_connection


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
