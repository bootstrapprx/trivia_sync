import ast
from pathlib import Path
import unittest

from scripts.check_schema_compatibility import DECLARED_RENAMES


APP_ROOT = Path(__file__).resolve().parents[2]


class TestDocTypeControllerImports(unittest.TestCase):
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
