import ast
import unittest
from pathlib import Path


class TestAIWorkerSyntax(unittest.TestCase):
    def test_ai_enricher_module_parses(self):
        source = Path(__file__).parents[1].joinpath("integrations", "ai_enricher.py").read_text()
        ast.parse(source)


if __name__ == "__main__":
    unittest.main()
