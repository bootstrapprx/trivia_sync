app_name = "trivia_sync"
app_title = "Trivia Sync"
app_publisher = "trivia360"
app_description = "Contest sync, AI enrichment, and knowledge tools for Frappe LMS."
app_email = "dev@trivia360.app"
app_license = "MIT"
required_apps = ["lms"]

add_to_apps_screen = [
	{
		"name": "trivia_sync",
		"logo": "/assets/frappe/images/frappe-framework-logo.svg",
		"title": "Trivia Sync",
		"route": "/app/concursos",
		"has_permission": "trivia_sync.api.has_app_permission",
	}
]

fixtures = [
	{"dt": "Role", "filters": [["role_name", "in", ["Trivia Editor", "Trivia Reviewer", "Trivia Integrator"]]]},
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"LMS Question-trivia_title",
					"LMS Question-trivia_section",
					"LMS Question-trivia_status",
					"LMS Question-trivia_answer_key_pending",
					"LMS Question-trivia_source_type",
					"LMS Question-trivia_qcode",
					"LMS Question-trivia_source_key",
					"LMS Question-trivia_texto_apoio",
					"LMS Question-trivia_col_break_1",
					"LMS Question-trivia_banca",
					"LMS Question-trivia_orgao",
					"LMS Question-trivia_cargo",
					"LMS Question-trivia_ano",
					"LMS Question-trivia_materia",
					"LMS Question-trivia_assunto",
					"LMS Question-trivia_links_section",
					"LMS Question-trivia_subject_link",
					"LMS Question-trivia_topic_link",
					"LMS Question-trivia_concurso",
					"LMS Question-trivia_concurso_cargo",
					"LMS Question-trivia_links_col_break",
					"LMS Question-trivia_syllabus_topics",
					"LMS Question-trivia_knowledge_pages",
					"LMS Question-trivia_general_explanation",
					"LMS Question-trivia_ai_section",
					"LMS Question-trivia_editorial_difficulty",
					"LMS Question-trivia_ai_difficulty_stars",
					"LMS Question-trivia_ai_difficulty_label",
					"LMS Question-trivia_ai_difficulty_reason",
					"LMS Question-trivia_ai_learning_objective",
					"LMS Question-trivia_ai_topics",
					"LMS Question-trivia_ai_model",
					"LMS Question-trivia_ai_enriched_at",
					"LMS Question-trivia_detected_option_count",
					"LMS Question-trivia_source_url",
					"LMS Question-trivia_source_license",
					"LMS Question-trivia_source_attribution",
					"LMS Question-trivia_source_authors",
					"LMS Question-trivia_sync_hash",
					"LMS Question-trivia_raw_payload",
				],
			]
		],
	},
	{
		"dt": "Property Setter",
		"filters": [
			[
				"name",
				"in",
				[
					"LMS Question-main-title_field",
					"LMS Question-main-show_title_field_in_link",
					"LMS Question-question-in_list_view",
				],
			]
		],
	},
]

after_migrate = [
	"trivia_sync.patches.v0_6.migrate_to_lms_native.ensure_lms_native_clean",
]

scheduler_events = {"hourly_long": ["trivia_sync.scheduler.run_qapi_sync_if_enabled"]}
doc_events = {
	"LMS Question": {
		"before_validate": "trivia_sync.integrations.lms_questions.sync_lms_question_title",
		"on_update": "trivia_sync.integrations.learning_content.invalidate_stale_materials_for_question",
	},
	"Trivia Methodology": {"on_update": "trivia_sync.integrations.learning_content.invalidate_stale_materials_for_methodology"},
}
doctype_js = {
	"Trivia Sync Settings": "public/js/trivia_sync_settings.js",
	"LMS Question": "public/js/lms_question.js",
	"LMS Quiz": "public/js/lms_quiz.js",
	"Course Lesson": "public/js/course_lesson.js",
	"Trivia Study Guide Recipe": "public/js/trivia_study_guide_recipe.js",
	"Trivia Contest": "public/js/trivia_contest.js",
	"Trivia Knowledge Page": "public/js/trivia_knowledge_page.js",
}
doctype_list_js = {
	"LMS Question": "public/js/lms_question_list.js",
	"LMS Quiz": "public/js/lms_quiz_list.js",
}
page_js = {"trivia-sync-onboarding": "public/js/trivia_sync_onboarding.js"}
app_include_js = [
	"/assets/trivia_sync/js/math_renderer.js",
	"/assets/trivia_sync/js/exam_importer.js",
]
web_include_js = ["/assets/trivia_sync/js/math_renderer.js"]
web_include_css = ["/assets/trivia_sync/css/trivia_question.css?v=7"]
app_include_css = [
	"/assets/trivia_sync/css/trivia_sync_onboarding.css",
	"/assets/trivia_sync/css/trivia_sync_dashboard.css",
	"/assets/trivia_sync/css/trivia_question.css?v=7",
]
