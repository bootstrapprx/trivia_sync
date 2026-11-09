app_name = "trivia_sync"
app_title = "Trivia Sync"
app_publisher = "trivia360"
app_description = "Full QAPI sync for Frappe LMS."
app_email = "dev@trivia360.app"
app_license = "MIT"
required_apps = ["lms"]

fixtures = [
	{"dt": "Role", "filters": [["role_name", "in", ["Trivia Editor", "Trivia Reviewer", "Trivia Integrator"]]]},
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"LMS Question-trivia_section",
					"LMS Question-trivia_qcode",
					"LMS Question-trivia_source_key",
					"LMS Question-trivia_question",
					"LMS Question-trivia_projection_key",
					"LMS Question-trivia_banca",
					"LMS Question-trivia_orgao",
					"LMS Question-trivia_cargo",
					"LMS Question-trivia_ano",
					"LMS Question-trivia_materia",
					"LMS Question-trivia_assunto",
					"LMS Question-trivia_source_url",
					"LMS Question-trivia_sync_hash",
					"LMS Question-trivia_texto_apoio",
				],
			]
		],
	}
]

scheduler_events = {"hourly_long": ["trivia_sync.scheduler.run_qapi_sync_if_enabled"]}
doctypes_js = {"Trivia Sync Settings": "public/js/trivia_sync_settings.js"}
doctypes_js.update({"Trivia Question": "public/js/trivia_question.js"})
page_js = {"trivia-sync-onboarding": "public/js/trivia_sync_onboarding.js"}
app_include_js = ["/assets/trivia_sync/js/math_renderer.js"]
web_include_js = ["/assets/trivia_sync/js/math_renderer.js"]
web_include_css = ["/assets/trivia_sync/css/trivia_question.css"]
app_include_css = [
	"/assets/trivia_sync/css/trivia_sync_onboarding.css",
	"/assets/trivia_sync/css/trivia_sync_dashboard.css",
	"/assets/trivia_sync/css/trivia_question.css",
]
