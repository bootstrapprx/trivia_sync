import re

import frappe
from frappe.utils import cint

BRAND_NAME = "Trivia Concursos"
BRAND_SHORT_NAME = "Trivia"
ADMIN_APP_TITLE = "Gestão de Concursos"
THEME_COLOR = "#08245A"
BRAND_DESCRIPTION = (
	"Plataforma de preparação, questões comentadas, simulados e trilhas dirigidas para concursos públicos."
)

LOGO_FULL_URL = "/assets/trivia_sync/images/whitelabel/trivia-logo-full.png"
SHIELD_512_URL = "/assets/trivia_sync/images/whitelabel/trivia-shield-512.png"
SHIELD_192_URL = "/assets/trivia_sync/images/whitelabel/trivia-shield-192.png"
SHIELD_64_URL = "/assets/trivia_sync/images/whitelabel/trivia-shield-64.png"
FAVICON_ICO_URL = "/assets/trivia_sync/images/whitelabel/favicon.ico"
FAVICON_32_URL = "/assets/trivia_sync/images/whitelabel/favicon-32x32.png"
FAVICON_16_URL = "/assets/trivia_sync/images/whitelabel/favicon-16x16.png"
APPLE_TOUCH_ICON_URL = "/assets/trivia_sync/images/whitelabel/apple-touch-icon.png"
MANIFEST_URL = "/assets/trivia_sync/whitelabel/manifest.webmanifest"
LMS_WHITELABEL_JS_URL = "/assets/trivia_sync/js/lms_whitelabel.js?v=1"
LMS_WHITELABEL_CSS_URL = "/assets/trivia_sync/css/lms_whitelabel.css?v=1"

BRAND_HTML = (
	f'<img src="{SHIELD_64_URL}" alt="{BRAND_NAME}" '
	'style="height:28px;width:auto;margin-right:8px;vertical-align:middle;">'
	f'<span style="font-weight:700;">{BRAND_NAME}</span>'
)

HEAD_BRAND_MARKER = "<!-- trivia-concursos-whitelabel -->"
HEAD_BRAND_TAGS = (
	f"{HEAD_BRAND_MARKER}\n"
	f'<link rel="icon" type="image/x-icon" href="{FAVICON_ICO_URL}">\n'
	f'<link rel="icon" type="image/png" sizes="32x32" href="{FAVICON_32_URL}">\n'
	f'<link rel="icon" type="image/png" sizes="16x16" href="{FAVICON_16_URL}">\n'
	f'<link rel="apple-touch-icon" sizes="180x180" href="{APPLE_TOUCH_ICON_URL}">\n'
	f'<link rel="manifest" href="{MANIFEST_URL}">\n'
	f'<meta name="theme-color" content="{THEME_COLOR}">\n'
	'<meta name="mobile-web-app-capable" content="yes">\n'
	'<meta name="apple-mobile-web-app-capable" content="yes">\n'
	'<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">\n'
	f'<meta name="apple-mobile-web-app-title" content="{BRAND_SHORT_NAME}">\n'
	f'<meta name="application-name" content="{BRAND_NAME}">'
)

DEFAULT_HOME_PAGES = {"", "home", "index", "frappe", "login"}
EXTERNAL_FRAPPE_DOMAINS = ("frappe.io", "frappeframework.com", "erpnext.com", "frappecloud.com")

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_MANIFEST_LINK_RE = re.compile(r'<link\b[^>]*\brel=["\']manifest["\'][^>]*>', re.IGNORECASE)
_ICON_LINK_RE = re.compile(
	r'<link\b[^>]*\brel=["\'](?:shortcut\s+icon|icon|apple-touch-icon)["\'][^>]*>',
	re.IGNORECASE,
)
_THEME_META_RE = re.compile(r'<meta\b[^>]*\bname=["\']theme-color["\'][^>]*>', re.IGNORECASE)
_OG_TITLE_RE = re.compile(
	r'(<meta\b[^>]*\b(?:property|name)=["\'](?:og:title|twitter:title|og:site_name)["\'][^>]*\bcontent=["\'])'
	r'([^"\']*)'
	r'(["\'][^>]*>)',
	re.IGNORECASE,
)
_OG_IMAGE_RE = re.compile(
	r'(<meta\b[^>]*\b(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*\bcontent=["\'])'
	r'([^"\']*)'
	r'(["\'][^>]*>)',
	re.IGNORECASE,
)
_HEAD_CLOSE_RE = re.compile(r"</head>", re.IGNORECASE)


def is_whitelabel_enabled() -> bool:
	try:
		if not hasattr(frappe, "db") or not frappe.db:
			return True
		val = frappe.db.get_single_value("Trivia Sync Settings", "whitelabel_enabled")
		if val is None or val == "":
			return True
		return bool(cint(val))
	except Exception:
		return True


def _doctype_exists(doctype: str) -> bool:
	try:
		return bool(hasattr(frappe, "db") and frappe.db and frappe.db.exists("DocType", doctype))
	except Exception:
		return False


def _has_field(meta, fieldname: str) -> bool:
	if meta is None:
		return True
	checker = getattr(meta, "has_field", None)
	return bool(checker(fieldname)) if callable(checker) else True


def _save_single_if_changed(doctype: str, updates: dict, conditional_updates: dict | None = None) -> bool:
	if not _doctype_exists(doctype):
		return False
	meta = frappe.get_meta(doctype) if hasattr(frappe, "get_meta") else None
	doc = frappe.get_single(doctype)
	changed = False

	for fieldname, target_value in updates.items():
		if not _has_field(meta, fieldname):
			continue
		if getattr(doc, fieldname, None) != target_value:
			setattr(doc, fieldname, target_value)
			changed = True

	for fieldname, predicate_and_value in (conditional_updates or {}).items():
		if not _has_field(meta, fieldname):
			continue
		predicate, target_value = predicate_and_value
		current_value = getattr(doc, fieldname, None)
		if predicate(current_value) and current_value != target_value:
			setattr(doc, fieldname, target_value)
			changed = True

	if doctype == "Navbar Settings" and hasattr(doc, "help_dropdown"):
		for item in getattr(doc, "help_dropdown", None) or []:
			route = str(getattr(item, "route", "") or "").lower()
			if any(domain in route for domain in EXTERNAL_FRAPPE_DOMAINS) and not cint(getattr(item, "hidden", 0)):
				item.hidden = 1
				changed = True

	if changed:
		flags = getattr(doc, "flags", None)
		if flags is not None:
			flags.ignore_permissions = True
			flags.ignore_mandatory = True
		doc.save(ignore_permissions=True)
	return changed


def _is_default_home(val) -> bool:
	cleaned = str(val or "").strip().strip("/").lower()
	return cleaned in DEFAULT_HOME_PAGES


def _is_default_or_frappe_text(val) -> bool:
	cleaned = str(val or "").strip().lower()
	return not cleaned or "frappe" in cleaned or "learning" in cleaned


def apply_whitelabel(force: bool = False) -> dict:
	"""Synchronize Website, Navbar, System, and LMS Settings with Trivia Concursos branding."""
	if not force and not is_whitelabel_enabled():
		return {"applied": False, "reason": "disabled", "updated_doctypes": []}

	updated_doctypes = []

	if _save_single_if_changed(
		"Website Settings",
		{
			"app_name": BRAND_NAME,
			"app_logo": SHIELD_192_URL,
			"banner_image": LOGO_FULL_URL,
			"splash_image": LOGO_FULL_URL,
			"favicon": FAVICON_ICO_URL,
			"brand_html": BRAND_HTML,
			"footer_logo": LOGO_FULL_URL,
			"copyright": BRAND_NAME,
			"footer_powered": " ",
			"hide_footer_signup": 1,
		},
		conditional_updates={
			"home_page": (_is_default_home, "lms"),
			"title_prefix": (_is_default_or_frappe_text, BRAND_NAME),
		},
	):
		updated_doctypes.append("Website Settings")

	if _save_single_if_changed(
		"Navbar Settings",
		{
			"app_logo": SHIELD_64_URL,
		},
	):
		updated_doctypes.append("Navbar Settings")

	if _save_single_if_changed(
		"System Settings",
		{
			"app_name": BRAND_NAME,
			"disable_system_update_notification": 1,
		},
		conditional_updates={
			"email_footer_address": (_is_default_or_frappe_text, BRAND_NAME),
		},
	):
		updated_doctypes.append("System Settings")

	if _save_single_if_changed(
		"LMS Settings",
		{
			"brand_name": BRAND_NAME,
			"app_logo": SHIELD_192_URL,
			"favicon": FAVICON_32_URL,
			"banner_image": LOGO_FULL_URL,
		},
		conditional_updates={
			"meta_description": (_is_default_or_frappe_text, BRAND_DESCRIPTION),
		},
	):
		updated_doctypes.append("LMS Settings")

	clear_cache = getattr(frappe, "clear_cache", None)
	if callable(clear_cache):
		try:
			clear_cache()
		except Exception:
			pass

	clear_website_cache = getattr(frappe, "clear_website_cache", None)
	if callable(clear_website_cache):
		try:
			clear_website_cache()
		except Exception:
			pass

	return {"applied": True, "updated_doctypes": updated_doctypes}


def ensure_whitelabel_on_migrate():
	"""Idempotent hook invoked on after_install and after_migrate."""
	try:
		apply_whitelabel(force=False)
	except Exception:
		if hasattr(frappe, "log_error") and hasattr(frappe, "get_traceback"):
			frappe.log_error(frappe.get_traceback(), "Trivia Concursos · Whitelabel migrate sync")


def transform_app_entry(app: dict) -> dict:
	if not isinstance(app, dict):
		return app
	updated = dict(app)
	name = updated.get("name")
	if name == "lms":
		updated["title"] = BRAND_NAME
		updated["logo"] = SHIELD_192_URL
		updated["route"] = updated.get("route") or "/lms"
	elif name == "trivia_sync":
		updated["title"] = ADMIN_APP_TITLE
		updated["logo"] = SHIELD_192_URL
		updated["route"] = updated.get("route") or "/app/concursos"
	return updated


def boot_session(bootinfo):
	if not is_whitelabel_enabled() or bootinfo is None:
		return
	bootinfo["app_logo_url"] = SHIELD_64_URL
	bootinfo["app_name"] = BRAND_NAME

	sysdefaults = bootinfo.get("sysdefaults")
	if isinstance(sysdefaults, dict):
		sysdefaults["app_name"] = BRAND_NAME

	apps_data = bootinfo.get("apps_data")
	if isinstance(apps_data, list):
		bootinfo["apps_data"] = [transform_app_entry(item) for item in apps_data]
	elif isinstance(apps_data, dict):
		for key, item in list(apps_data.items()):
			if isinstance(item, dict):
				apps_data[key] = transform_app_entry(item)


@frappe.whitelist()
def get_apps():
	from frappe.apps import get_apps as core_get_apps

	apps = core_get_apps() or []
	if not is_whitelabel_enabled():
		return apps
	return [transform_app_entry(app) for app in apps]


@frappe.whitelist(allow_guest=True)
def get_branding():
	if is_whitelabel_enabled():
		return {
			"brand_name": BRAND_NAME,
			"app_logo": SHIELD_192_URL,
			"favicon": FAVICON_32_URL,
		}
	name = frappe.db.get_single_value("LMS Settings", "brand_name") if _doctype_exists("LMS Settings") else None
	logo = frappe.db.get_single_value("LMS Settings", "app_logo") if _doctype_exists("LMS Settings") else None
	return {"brand_name": name or "LMS", "app_logo": logo}


def _current_request_path(request=None) -> str:
	req = request or getattr(getattr(frappe, "local", None), "request", None)
	return str(getattr(req, "path", "") or "")


def update_website_context(context):
	if not is_whitelabel_enabled() or context is None:
		return

	path = _current_request_path().rstrip("/") or "/"
	context["app_name"] = BRAND_NAME
	context["brand_html"] = BRAND_HTML
	context["favicon"] = FAVICON_ICO_URL
	context["splash_image"] = LOGO_FULL_URL
	context["banner_image"] = LOGO_FULL_URL
	context["footer_logo"] = LOGO_FULL_URL
	context["footer_powered"] = " "
	context["copyright"] = BRAND_NAME

	if path in ("/login", "/update-password"):
		context["logo"] = LOGO_FULL_URL
		context["app_logo"] = LOGO_FULL_URL
	else:
		context["app_logo"] = SHIELD_192_URL

	apps = context.get("apps")
	if isinstance(apps, list):
		context["apps"] = [transform_app_entry(app) for app in apps]

	head_include = str(context.get("head_include") or "")
	if HEAD_BRAND_MARKER not in head_include:
		context["head_include"] = f"{head_include}\n{HEAD_BRAND_TAGS}".strip()


def _replace_title(match: re.Match) -> str:
	raw_title = (match.group(1) or "").strip()
	lower = raw_title.lower()
	if not raw_title or lower in ("lms", "frappe learning", "learning", "frappe"):
		return f"<title>{BRAND_NAME}</title>"
	cleaned = re.sub(r"frappe\s+learning", BRAND_NAME, raw_title, flags=re.IGNORECASE)
	cleaned = re.sub(r"\bfrappe\s+lms\b", BRAND_NAME, cleaned, flags=re.IGNORECASE)
	return f"<title>{cleaned}</title>"


def _replace_og_title(match: re.Match) -> str:
	prefix, content, suffix = match.group(1), match.group(2), match.group(3)
	lower = content.strip().lower()
	if not lower or "frappe" in lower or lower in ("lms", "learning"):
		return f"{prefix}{BRAND_NAME}{suffix}"
	return match.group(0)


def _replace_og_image(match: re.Match) -> str:
	prefix, content, suffix = match.group(1), match.group(2), match.group(3)
	lower = content.strip().lower()
	if not lower or "/assets/lms/" in lower or "/assets/frappe/" in lower:
		return f"{prefix}{LOGO_FULL_URL}{suffix}"
	return match.group(0)


def rewrite_lms_html(html_text: str) -> str:
	"""Rewrite Frappe LMS SPA HTML shell metadata, manifest, icons, and whitelabel assets."""
	if not html_text or "</head>" not in html_text.lower():
		return html_text
	if HEAD_BRAND_MARKER in html_text:
		return html_text

	updated = _TITLE_RE.sub(_replace_title, html_text, count=1)
	updated = _MANIFEST_LINK_RE.sub("", updated)
	updated = _ICON_LINK_RE.sub("", updated)
	updated = _THEME_META_RE.sub("", updated)
	updated = _OG_TITLE_RE.sub(_replace_og_title, updated)
	updated = _OG_IMAGE_RE.sub(_replace_og_image, updated)

	injected_block = (
		f"{HEAD_BRAND_TAGS}\n"
		f'<link rel="stylesheet" href="{LMS_WHITELABEL_CSS_URL}">\n'
		f'<script src="{LMS_WHITELABEL_JS_URL}" defer></script>\n'
		"</head>"
	)
	return _HEAD_CLOSE_RE.sub(injected_block, updated, count=1)


def _extract_request_and_response(args, kwargs):
	request = kwargs.get("request")
	response = kwargs.get("response")
	for item in args:
		if hasattr(item, "get_data") and hasattr(item, "set_data"):
			response = item
		elif hasattr(item, "path"):
			request = item
	return request, response


def after_request(*args, **kwargs):
	request, response = _extract_request_and_response(args, kwargs)
	if response is None:
		return response
	try:
		if getattr(response, "direct_passthrough", False):
			return response
		status_code = getattr(response, "status_code", 200)
		content_type = str(getattr(response, "content_type", "") or "").lower()
		if status_code != 200 or "text/html" not in content_type:
			return response

		path = _current_request_path(request)
		if not (path == "/lms" or path.startswith("/lms/")):
			return response

		if not is_whitelabel_enabled():
			return response

		html_text = response.get_data(as_text=True)
		rewritten = rewrite_lms_html(html_text)
		if rewritten != html_text:
			response.set_data(rewritten)
	except Exception:
		pass
	return response
