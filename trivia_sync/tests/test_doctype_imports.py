import ast
import json
from pathlib import Path
import unittest

from scripts.check_schema_compatibility import DECLARED_RENAMES, DECLARED_RETIRED


APP_ROOT = Path(__file__).resolve().parents[2]


class TestDocTypeControllerImports(unittest.TestCase):
	def test_lms_question_fixture_and_hooks_cover_native_integration(self):
		fixture_path = APP_ROOT / "trivia_sync" / "fixtures" / "custom_field.json"
		fixture_rows = json.loads(fixture_path.read_text())
		fixture_names = {row["name"] for row in fixture_rows}
		required_custom_fields = {
			"LMS Question-trivia_status",
			"LMS Question-trivia_source_type",
			"LMS Question-trivia_qcode",
			"LMS Question-trivia_texto_apoio",
			"LMS Question-trivia_subject_link",
			"LMS Question-trivia_topic_link",
			"LMS Question-trivia_syllabus_topics",
			"LMS Question-trivia_knowledge_pages",
			"LMS Question-trivia_teacher_comment_section",
			"LMS Question-trivia_general_explanation",
			"LMS Question-trivia_ai_comment",
			"LMS Question-trivia_ai_difficulty_stars",
		}
		self.assertTrue(required_custom_fields <= fixture_names)
		self.assertNotIn("LMS Question-trivia_question", fixture_names)

		by_name = {row["name"]: row for row in fixture_rows}
		self.assertEqual(by_name["LMS Question-trivia_teacher_comment_section"]["fieldtype"], "Section Break")
		self.assertEqual(by_name["LMS Question-trivia_teacher_comment_section"]["label"], "Comentário do Professor")
		self.assertEqual(by_name["LMS Question-trivia_teacher_comment_section"]["collapsible"], 0)
		self.assertEqual(by_name["LMS Question-trivia_general_explanation"]["label"], "Comentário do Professor")
		self.assertEqual(by_name["LMS Question-trivia_general_explanation"]["insert_after"], "trivia_teacher_comment_section")
		self.assertEqual(by_name["LMS Question-trivia_ai_comment"]["label"], "Comentário da Athena")
		self.assertEqual(by_name["LMS Question-trivia_ai_comment"]["read_only"], 1)

		import trivia_sync.hooks as hooks

		configured = set(hooks.fixtures[1]["filters"][0][2])
		self.assertEqual(fixture_names, configured)
		self.assertIn("LMS Question-trivia_title", fixture_names)

		ps_path = APP_ROOT / "trivia_sync" / "fixtures" / "property_setter.json"
		ps_rows = json.loads(ps_path.read_text())
		ps_by_name = {row["name"]: row for row in ps_rows}
		self.assertEqual(ps_by_name["LMS Question-main-title_field"]["value"], "trivia_title")
		self.assertEqual(set(ps_by_name), set(hooks.fixtures[2]["filters"][0][2]))
		self.assertIn("LMS Question", hooks.doctype_js)
		self.assertIn("LMS Quiz", hooks.doctype_js)
		self.assertIn("Course Lesson", hooks.doctype_js)
		self.assertIn("LMS Question", hooks.doctype_list_js)

	def test_retired_shadow_doctypes_are_absent(self):
		current_names = {
			json.loads(path.read_text())["name"]
			for path in (APP_ROOT / "trivia_sync" / "trivia_sync" / "doctype").glob("*/*.json")
		}
		for retired in DECLARED_RETIRED:
			self.assertNotIn(retired, current_names)

	def test_qapi_contest_title_accepts_full_source_text(self):
		path = APP_ROOT / "trivia_sync" / "trivia_sync" / "doctype" / "trivia_contest" / "trivia_contest.json"
		fields = json.loads(path.read_text())["fields"]
		title = next(field for field in fields if field["fieldname"] == "titulo")
		self.assertEqual(title["fieldtype"], "Small Text")

	def test_all_internal_doctype_imports_resolve_to_a_python_module(self):
		missing = []
		for controller in (APP_ROOT / "trivia_sync" / "trivia_sync" / "doctype").glob("*/*.py"):
			tree = ast.parse(controller.read_text(encoding="utf-8"))
			for node in ast.walk(tree):
				modules = []
				if isinstance(node, ast.ImportFrom) and node.module:
					modules.append(node.module)
				elif isinstance(node, ast.Import):
					modules.extend(alias.name for alias in node.names)
				for module in modules:
					if not module.startswith("trivia_sync."):
						continue
					module_path = APP_ROOT / Path(*module.split("."))
					if not (module_path.with_suffix(".py").exists() or (module_path / "__init__.py").exists()):
						missing.append(f"{controller}: {module}")
		self.assertEqual(missing, [], "Unresolvable internal imports:\n" + "\n".join(missing))

	def test_declared_schema_renames_have_targets_in_current_schema(self):
		current_names = {
			json.loads(path.read_text())["name"]
			for path in (APP_ROOT / "trivia_sync" / "trivia_sync" / "doctype").glob("*/*.json")
		}
		missing_targets = [target for target in DECLARED_RENAMES.values() if target not in current_names]
		self.assertEqual(missing_targets, [])


if __name__ == "__main__":
	unittest.main()
