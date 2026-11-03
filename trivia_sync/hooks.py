app_name = "trivia_sync"
app_title = "Trivia Sync"
app_publisher = "bootstrapprx"
app_description = "Sync questions from API sources"
app_email = "anderson.thome@outlook.com"
app_license = "mit"

# Send non-GET requests for this app's endpoints as native `application/json`
# bodies instead of form-encoded, per-key JSON-stringified values.
use_json_request_body = True

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "trivia_sync",
# 		"logo": "/assets/trivia_sync/logo.png",
# 		"title": "Trivia Sync",
# 		"route": "/trivia_sync",
# 		"has_permission": "trivia_sync.api.permission.has_app_permission",
# 	}
# ]

# The dock, the rail down the left of the desk, is a document rather than a hook. Author it in
# Manage Dock on a developer-mode site and press Export to App, and it is written to
# `trivia_sync/dock/trivia_sync/trivia_sync.json` for git to carry. An app that ships none has no
# rail: its sidebar gets a switcher in the header instead.
#
# A companion app, one that extends a host app rather than standing on its own, says so with
# `mount_on` on that same record, and its entries are appended to the host's rail. Mounting keeps
# the companion off the apps screen, so it takes precedence over any add_to_apps_screen above.

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/trivia_sync/css/trivia_sync.css"
# app_include_js = "/assets/trivia_sync/js/trivia_sync.js"

# include js, css files in header of web template
# web_include_css = "/assets/trivia_sync/css/trivia_sync.css"
# web_include_js = "/assets/trivia_sync/js/trivia_sync.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "trivia_sync/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_kanban_js = {"doctype" : "public/js/doctype_kanban.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "trivia_sync/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Setup Wizard
# ------------

# open a fresh site's setup in this app's own UI instead of the desk wizard.
# must be a non-desk route (not under /desk or /app); to customize setup within
# desk, use setup_wizard_stages / setup_wizard_complete instead.
# setup_wizard_url = "/trivia_sync/setup"

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "trivia_sync.utils.jinja_methods",
# 	"filters": "trivia_sync.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "trivia_sync.install.before_install"
# after_install = "trivia_sync.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "trivia_sync.uninstall.before_uninstall"
# after_uninstall = "trivia_sync.uninstall.after_uninstall"

# Disable / Enable
# ----------------
# Called when this app is logically disabled or re-enabled on a site,
# without uninstalling it. Use this to hide/restore fields this app adds
# to other apps' doctypes.

# before_disable = "trivia_sync.uninstall.before_disable"
# after_disable = "trivia_sync.uninstall.after_disable"
# before_enable = "trivia_sync.install.before_enable"
# after_enable = "trivia_sync.install.after_enable"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "trivia_sync.utils.before_app_install"
# after_app_install = "trivia_sync.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "trivia_sync.utils.before_app_uninstall"
# after_app_uninstall = "trivia_sync.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "trivia_sync.build.after_build"

# To hook into the build process of other apps
# The list of apps being built is passed as an argument

# after_app_build = "trivia_sync.build.after_app_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "trivia_sync.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["trivia_sync.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"trivia_sync.tasks.all"
# 	],
# 	"daily": [
# 		"trivia_sync.tasks.daily"
# 	],
# 	"hourly": [
# 		"trivia_sync.tasks.hourly"
# 	],
# 	"weekly": [
# 		"trivia_sync.tasks.weekly"
# 	],
# 	"monthly": [
# 		"trivia_sync.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "trivia_sync.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "trivia_sync.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "trivia_sync.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "trivia_sync.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["trivia_sync.utils.before_request"]
# after_request = ["trivia_sync.utils.after_request"]

# Job Events
# ----------
# before_job = ["trivia_sync.utils.before_job"]
# after_job = ["trivia_sync.utils.after_job"]

# after_file_upload = ["trivia_sync.utils.after_file_upload"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"trivia_sync.auth.validate"
# ]

# on_social_login = "trivia_sync.auth.on_social_login"

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# Require all whitelisted methods to have type annotations
require_type_annotated_api_methods = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

