app_name = "trivia_sync"
app_title = "Trivia Sync"
app_publisher = "trivia360"
app_description = "Sincroniza questões da QAPI e o conteúdo existente do Frappe LMS com a trivia360."
app_email = "dev@trivia360.app"
app_license = "MIT"

scheduler_events = {
    "hourly_long": [
        "trivia_sync.scheduler.run_qapi_sync_if_enabled",
    ],
    "daily_long": [
        "trivia_sync.scheduler.run_lms_sync_if_enabled",
    ],
}

doctypes_js = {
    "Trivia Sync Settings": "public/js/trivia_sync_settings.js",
}
