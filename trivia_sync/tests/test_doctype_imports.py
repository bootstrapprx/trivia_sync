import ast
import json
from pathlib import Path
import unittest

from scripts.check_schema_compatibility import DECLARED_RENAMES


APP_ROOT = Path(__file__).resolve().parents[2]


class TestDocTypeControllerImports(unittest.TestCase):
    def test_question_schema_and_lms_fixture_cover_integrity_fields(self):
        question = json.loads((APP_ROOT / "trivia_sync" / "trivia_sync" / "doctype" / "trivia_question" / "trivia_question.json").read_text())
        fieldnames = {field["fieldname"] for field in question["fields"]}
        self.assertTrue({"correct_options", "detected_option_count", "allow_variable_options", "exception_reason", "editorial_difficulty", "editorial_status"} <= fieldnames)
        fixture_path = APP_ROOT / "trivia_sync" / "fixtures" / "custom_field.json"
        fixture_names = {row["name"] for row in json.loads(fixture_path.read_text())}
        self.assertTrue({"LMS Question-trivia_source_license", "LMS Question-trivia_source_attribution", "LMS Question-trivia_redistribution_reference"} <= fixture_names)
        import trivia_sync.hooks as hooks
        configured = set(hooks.fixtures[1]["filters"][0][2])
        self.assertTrue(fixture_names <= configured)
        self.assertIn("LMS Question", hooks.doc_events)

    def test_qapi_contest_and_exam_titles_accept_full_source_text(self):
        for doctype in ("trivia_contest", "trivia_exam"):
            path = APP_ROOT / "trivia_sync" / "trivia_sync" / "doctype" / doctype / f"{doctype}.json"
            fields = json.loads(path.read_text())["fields"]
            title = next(field for field in fields if field["fieldname"] == "titulo")
            self.assertEqual(title["fieldtype"], "Small Text")

    def test_all_internal_doctype_imports_resolve_to_a_python_module(self):
        missing = []
        for controller in (APP_ROOT / "trivia_sync" / "doctype").glob("*/*.py"):
            tree = ast.parse(controller.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    modules.append(node.module)
                elif isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                for module in modules:
                    prefix = "trivia_sync."
                    if not module.startswith(prefix):
                        continue
                    module_path = APP_ROOT / Path(*module.split("."))
                    if not (module_path.with_suffix(".py").exists() or (module_path / "__init__.py").exists()):
                        missing.append(f"{controller}: {module}")
        self.assertEqual(missing, [], "Unresolvable internal imports:\n" + "\n".join(missing))

    def test_declared_schema_renames_have_targets_in_current_schema(self):
        current_names = {
            path.read_text(encoding="utf-8").split('"name": "', 1)[1].split('"', 1)[0]
            for path in (APP_ROOT / "trivia_sync" / "trivia_sync" / "doctype").glob("*/*.json")
            if '"name": "' in path.read_text(encoding="utf-8")
        }
        missing_targets = [target for target in DECLARED_RENAMES.values() if target not in current_names]
        self.assertEqual(missing_targets, [])


if __name__ == "__main__":
    unittest.main()
