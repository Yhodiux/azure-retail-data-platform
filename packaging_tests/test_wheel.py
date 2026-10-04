"""Validate the built deployment artifact without importing Spark or cloud SDKs."""
import ast
from email.parser import Parser
from pathlib import Path
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class WheelContractTests(unittest.TestCase):
    def setUp(self):
        wheels = list((ROOT / "dist").glob("retail_data_core-*.whl"))
        self.assertEqual(len(wheels), 1, "Build exactly one wheel in dist before testing")
        self.wheel = zipfile.ZipFile(wheels[0])
        self.addCleanup(self.wheel.close)
        metadata = next(n for n in self.wheel.namelist() if n.endswith(".dist-info/METADATA"))
        self.metadata = Parser().parsestr(self.wheel.read(metadata).decode())

    def test_no_runtime_dependencies(self):
        requirements = self.metadata.get_all("Requires-Dist", [])
        self.assertTrue(all('extra == "local-test"' in r for r in requirements), requirements)
        self.assertEqual(requirements, ['pyspark==3.5.4; extra == "local-test"'])

    def test_python_and_pure_wheel(self):
        self.assertEqual(set(self.metadata["Requires-Python"].split(',')), {">=3.8", "<3.12"})
        wheel = next(n for n in self.wheel.namelist() if n.endswith(".dist-info/WHEEL"))
        self.assertIn("Tag: py3-none-any", self.wheel.read(wheel).decode())

    def test_core_only_and_no_cloud_imports(self):
        sources = [n for n in self.wheel.namelist() if n.endswith(".py")]
        self.assertEqual(set(sources), {str(p.relative_to(ROOT / "src")).replace('\\', '/')
                                     for p in (ROOT / "src/retail_data_core").glob("*.py")})
        for name in sources:
            self.assertEqual(self.wheel.read(name), (ROOT / "src" / name).read_bytes())
            tree = ast.parse(self.wheel.read(name))
            for node in ast.walk(tree):
                imports = ([a.name for a in node.names] if isinstance(node, ast.Import)
                           else [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
                for module in imports:
                    self.assertNotIn(module.split('.')[0], {"azure", "databricks", "dbutils", "tooling"})


if __name__ == "__main__":
    unittest.main()
