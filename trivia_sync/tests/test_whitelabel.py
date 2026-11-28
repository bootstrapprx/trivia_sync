import importlib
import json
import struct
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

APP_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_ROOT = APP_ROOT / "trivia_sync" / "public"


def _ensure_frappe_stub():
	frappe = sys.modules.setdefault("frappe", types.SimpleNamespace())
	if not hasattr(frappe, "PermissionError"):
		frappe.PermissionError = type("PermissionError", (Exception,), {})
	if not hasattr(frappe, "ValidationError"):
		frappe.ValidationError = type("ValidationError", (Exception,), {})
	if not hasattr(frappe, "whitelist"):
		frappe.whitelist = lambda *a, **kw: (lambda fn: fn)
	if not hasattr(frappe, "only_for"):
		frappe.only_for = lambda role: None
	if not hasattr(frappe, "local"):
		frappe.local = types.SimpleNamespace(request=None)
	if not hasattr(frappe, "db"):
		frappe.db = types.SimpleNamespace(
			get_single_value=lambda *a, **kw: 1,
			exists=lambda *a, **kw: True,
		)
	if not hasattr(frappe, "utils"):
		frappe.utils = types.SimpleNamespace(
			cint=lambda v: int(v or 0),
			now_datetime=lambda: "2026-11-27 20:00:00",
		)
	elif not hasattr(frappe.utils, "cint"):
		frappe.utils.cint = lambda v: int(v or 0)
	sys.modules.setdefault("frappe.utils", frappe.utils)
	return frappe


def _read_png_header(path: Path) -> tuple[int, int, int]:
	data = path.read_bytes()
	assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a valid PNG"
	width, height, _bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
	return width, height, color_type


class _FakeResponse:
	def __init__(self, body: str, status_code: int = 200, content_type: str = "text/html; charset=utf-8"):
		self._body = body
		self.status_code = status_code
		self.content_type = content_type
		self.direct_passthrough = False

	def get_data(self, as_text: bool = False):
		return self._body if as_text else self._body.encode("utf-8")

	def set_data(self, value: str):
		self._body = value


class TestWhitelabel(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		_ensure_frappe_stub()
		cls.wl = importlib.import_module("trivia_sync.whitelabel")

	def test_whitelabel_assets_and_manifest_integrity(self):
		img_dir = PUBLIC_ROOT / "images" / "whitelabel"
		expected_pngs = {
			"favicon-16x16.png": (16, 16, True),
			"favicon-32x32.png": (32, 32, True),
			"trivia-shield-64.png": (64, 64, True),
			"trivia-shield-192.png": (192, 192, True),
			"trivia-shield-512.png": (512, 512, True),
			"apple-touch-icon.png": (180, 180, False),
			"pwa-192x192.png": (192, 192, False),
			"pwa-512x512.png": (512, 512, False),
			"pwa-maskable-512x512.png": (512, 512, False),
		}
		for filename, (exp_w, exp_h, allow_alpha) in expected_pngs.items():
			path = img_dir / filename
			self.assertTrue(path.is_file(), f"Missing {filename}")
			w, h, color_type = _read_png_header(path)
			self.assertEqual((w, h), (exp_w, exp_h), f"Unexpected dimensions for {filename}")
			if not allow_alpha:
				# PNG color_type 4 (grayscale+alpha) and 6 (RGBA) have alpha; mobile home icons must be opaque
				self.assertNotIn(color_type, (4, 6), f"{filename} must be opaque for iOS/Android maskable icons")

		self.assertTrue((img_dir / "trivia-logo-full.png").is_file())
		ico_bytes = (img_dir / "favicon.ico").read_bytes()
		self.assertEqual(ico_bytes[:4], b"\x00\x00\x01\x00")

		manifest_path = PUBLIC_ROOT / "whitelabel" / "manifest.webmanifest"
		manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
		self.assertEqual(manifest["name"], "Trivia Concursos")
		self.assertEqual(manifest["short_name"], "Trivia")
		self.assertEqual(manifest["start_url"], "/lms")
		self.assertEqual(manifest["display"], "standalone")
		self.assertEqual(manifest["theme_color"], "#08245A")
		self.assertEqual(manifest["background_color"], "#08245A")
		self.assertEqual(len(manifest["icons"]), 3)

		cover_svg = (PUBLIC_ROOT / "images" / "athena_course_cover.svg").read_text(encoding="utf-8")
		self.assertIn("ATHENA · TRIVIA CONCURSOS", cover_svg)
		self.assertNotIn("TRIVIA LMS", cover_svg)

	def test_apply_whitelabel_updates_settings_idempotently_and_respects_toggle(self):
		frappe = self.wl.frappe

		def make_doc(**kwargs):
			ns = types.SimpleNamespace(**kwargs)
			ns.flags = types.SimpleNamespace()
			ns.saved = 0

			def save(**_kw):
				ns.saved += 1

			ns.save = save
			return ns

		docs = {
			"Website Settings": make_doc(
				app_name="Frappe",
				app_logo="",
				banner_image="",
				splash_image="",
				favicon="",
				brand_html="",
				footer_logo="",
				copyright="",
				footer_powered="Powered by Frappe",
				hide_footer_signup=0,
				home_page="home",
				title_prefix="Frappe Learning",
			),
			"Navbar Settings": make_doc(
				app_logo="",
				help_dropdown=[
					types.SimpleNamespace(route="https://docs.frappe.io", hidden=0),
					types.SimpleNamespace(route="/conhecimento", hidden=0),
				],
			),
			"System Settings": make_doc(
				app_name="Frappe",
				disable_system_update_notification=0,
				email_footer_address="",
			),
			"LMS Settings": make_doc(
				brand_name="Frappe Learning",
				app_logo="",
				favicon="",
				banner_image="",
				meta_description="Easy to Use, 100% Open Source Learning Management System",
			),
		}

		fake_meta = types.SimpleNamespace(has_field=lambda _f: True)
		fake_db = types.SimpleNamespace(
			get_single_value=lambda _dt, _f: 1,
			exists=lambda _dt, name=None: name in docs,
		)

		with patch.object(frappe, "db", fake_db), patch.object(
			frappe, "get_meta", return_value=fake_meta, create=True
		), patch.object(frappe, "get_single", side_effect=lambda dt: docs[dt], create=True):
			first = self.wl.apply_whitelabel()
			second = self.wl.apply_whitelabel()

		self.assertTrue(first["applied"])
		self.assertEqual(
			set(first["updated_doctypes"]),
			{"Website Settings", "Navbar Settings", "System Settings", "LMS Settings"},
		)
		self.assertEqual(second["updated_doctypes"], [])
		self.assertEqual(docs["Website Settings"].app_name, "Trivia Concursos")
		self.assertEqual(docs["Website Settings"].home_page, "lms")
		self.assertEqual(docs["Website Settings"].footer_powered, " ")
		self.assertEqual(docs["LMS Settings"].brand_name, "Trivia Concursos")
		self.assertEqual(docs["Navbar Settings"].help_dropdown[0].hidden, 1)
		self.assertEqual(docs["Navbar Settings"].help_dropdown[1].hidden, 0)

		disabled_db = types.SimpleNamespace(get_single_value=lambda _dt, _f: 0, exists=lambda *_a: True)
		with patch.object(frappe, "db", disabled_db):
			skipped = self.wl.apply_whitelabel(force=False)
		self.assertFalse(skipped["applied"])

	def test_boot_session_apps_and_website_context(self):
		frappe = self.wl.frappe
		enabled_db = types.SimpleNamespace(get_single_value=lambda _dt, _f: 1, exists=lambda *_a: True)

		bootinfo = {
			"app_logo_url": "/assets/frappe/images/frappe-framework-logo.svg",
			"sysdefaults": {"app_name": "Frappe"},
			"apps_data": [
				{"name": "lms", "title": "Learning", "logo": "/assets/lms/frontend/learning.svg", "route": "/lms"},
				{"name": "trivia_sync", "title": "Trivia Sync", "logo": "/old.svg", "route": "/app/concursos"},
			],
		}
		with patch.object(frappe, "db", enabled_db):
			self.wl.boot_session(bootinfo)
			branding = self.wl.get_branding()

		self.assertEqual(bootinfo["app_name"], "Trivia Concursos")
		self.assertEqual(bootinfo["sysdefaults"]["app_name"], "Trivia Concursos")
		self.assertEqual(bootinfo["apps_data"][0]["title"], "Trivia Concursos")
		self.assertEqual(bootinfo["apps_data"][1]["title"], "Gestão de Concursos")
		self.assertEqual(branding["brand_name"], "Trivia Concursos")

		login_ctx = {"apps": [{"name": "lms", "title": "Learning"}]}
		fake_local = types.SimpleNamespace(request=types.SimpleNamespace(path="/login"))
		with patch.object(frappe, "db", enabled_db), patch.object(frappe, "local", fake_local):
			self.wl.update_website_context(login_ctx)
		self.assertEqual(login_ctx["logo"], self.wl.LOGO_FULL_URL)
		self.assertEqual(login_ctx["apps"][0]["title"], "Trivia Concursos")
		self.assertIn(self.wl.MANIFEST_URL, login_ctx["head_include"])

	def test_rewrite_lms_html_and_after_request_scoping(self):
		frappe = self.wl.frappe
		enabled_db = types.SimpleNamespace(get_single_value=lambda _dt, _f: 1, exists=lambda *_a: True)
		raw_lms_shell = (
			"<!DOCTYPE html><html><head>"
			"<title>Frappe Learning</title>"
			'<link rel="icon" href="/assets/lms/frontend/favicon.png">'
			'<link rel="manifest" href="/assets/lms/frontend/manifest.webmanifest">'
			'<meta name="theme-color" content="#ffffff">'
			'<meta property="og:title" content="Frappe Learning">'
			"</head><body><div id=\"app\"></div></body></html>"
		)

		lms_req = types.SimpleNamespace(path="/lms/courses")
		lms_resp = _FakeResponse(raw_lms_shell)
		api_req = types.SimpleNamespace(path="/api/method/ping")
		api_resp = _FakeResponse('{"message":"pong"}', content_type="application/json")

		with patch.object(frappe, "db", enabled_db):
			self.wl.after_request(lms_req, lms_resp)
			first_html = lms_resp.get_data(as_text=True)
			self.wl.after_request(lms_req, lms_resp)
			second_html = lms_resp.get_data(as_text=True)
			self.wl.after_request(api_req, api_resp)

		self.assertEqual(first_html, second_html)
		self.assertIn("<title>Trivia Concursos</title>", first_html)
		self.assertNotIn("/assets/lms/frontend/manifest.webmanifest", first_html)
		self.assertNotIn("/assets/lms/frontend/favicon.png", first_html)
		self.assertIn(self.wl.MANIFEST_URL, first_html)
		self.assertIn(self.wl.APPLE_TOUCH_ICON_URL, first_html)
		self.assertIn('content="#08245A"', first_html)
		self.assertIn(self.wl.LMS_WHITELABEL_JS_URL, first_html)
		self.assertEqual(api_resp.get_data(as_text=True), '{"message":"pong"}')

	def test_frontend_script_avoids_unsafe_dom_sinks(self):
		js_source = (PUBLIC_ROOT / "js" / "lms_whitelabel.js").read_text(encoding="utf-8")
		for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "alert("):
			self.assertNotIn(forbidden, js_source)


if __name__ == "__main__":
	unittest.main()
