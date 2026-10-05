"""Execute actual task launchers without __file__, from installed wheels only."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCH = """
import sys
from pathlib import Path
import integration, retail_data_core
assert Path(integration.__file__).is_relative_to(Path(sys.prefix))
assert Path(retail_data_core.__file__).is_relative_to(Path(sys.prefix))
script = Path(sys.argv[1])
sys.argv = [str(script), '--help']
namespace = {'__name__': '__main__'}
assert '__file__' not in namespace
exec(compile(script.read_bytes(), str(script), 'exec'), namespace)
"""


class EntryBootstrapTests(unittest.TestCase):
    def check_entry(self, filename):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-I', '-B', '-c', LAUNCH,
                                     str(ROOT / 'integration/databricks' / filename)],
                                    cwd=directory, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('--snapshot-id', result.stdout)
        self.assertIn('--complete-sha256', result.stdout)

    def test_smoke_without_file_and_checkout_on_path(self):
        self.check_entry('read_only_smoke.py')

    def test_build_without_file_and_checkout_on_path(self):
        self.check_entry('build_silver.py')

    def test_publish_without_file_and_checkout_on_path(self):
        self.check_entry('validate_and_publish_silver.py')


if __name__ == '__main__':
    unittest.main()
