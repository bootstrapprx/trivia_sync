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
					"LMS Question-trivia_banca",
					"LMS Question-trivia_orgao",
					"LMS Question-trivia_cargo",
					"LMS Question-trivia_ano",
					"LMS Question-trivia_materia",
					"LMS Question-trivia_assunto",
					"LMS Question-trivia_source_url",
					"LMS Question-trivia_sync_hash",
					"LMS Question-trivia_texto_apoio",
					"LMS Question-trivia_ai_difficulty_stars",
					"LMS Question-trivia_ai_difficulty_label",
					"LMS Question-trivia_ai_difficulty_reason",
					"LMS Question-trivia_ai_learning_objective",
					"LMS Question-trivia_ai_topics",
					"LMS Question-trivia_ai_model",
					"LMS Question-trivia_ai_enriched_at",
					"LMS Question-trivia_source_key",
					"LMS Question-trivia_question",
					"LMS Question-trivia_projection_key",
					"LMS Question-trivia_source_license",
					"LMS Question-trivia_source_attribution",
					"LMS Question-trivia_source_authors",
					"LMS Question-trivia_redistribution_reference",
					"LMS Question-trivia_redistribution_status",
					"LMS Question-trivia_editorial_difficulty",
					"LMS Question-trivia_detected_option_count",
					"LMS Question-trivia_allow_variable_options",
					"LMS Question-trivia_exception_reason",
				],
			]
		],
	}
]

scheduler_events = {"hourly_long": ["trivia_sync.scheduler.run_qapi_sync_if_enabled"]}
doc_events = {"LMS Question": {"validate": "trivia_sync.integrations.lms_questions.validate_lms_question"}}
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
