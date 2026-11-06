import frappe


def _settings():
    if not frappe.db.exists("Trivia Sync Settings", "Trivia Sync Settings"): return None
    return frappe.get_single("Trivia Sync Settings")


def run_qapi_sync_if_enabled():
    settings = _settings()
    if settings and settings.qapi_enabled and settings.qapi_sync_frequency in ("Hourly", "Every scheduler tick"):
        frappe.enqueue("trivia_sync.integrations.sync.sync_qapi_full", queue="long", job_name="trivia_sync_qapi_full")


def run_lms_sync_if_enabled():
    settings = _settings()
    if settings and settings.lms_sync_enabled and settings.lms_sync_frequency in ("Daily", "Every scheduler tick"):
        frappe.enqueue("trivia_sync.integrations.frappe_lms.sync_existing_lms_to_trivia", queue="long", job_name="trivia_sync_lms_to_trivia")
