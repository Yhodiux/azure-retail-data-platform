import tempfile
import unittest
from pathlib import Path

from integration.databricks.read_only_smoke import inspect_source
from integration_tests.fixtures import approved_source, RID


class ReadOnlySmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sid, self.digest, _, self.roots = approved_source(self.root)

    def inventory(self):
        return {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_nine_reads_leave_all_source_files_unchanged_and_no_silver(self):
        before = self.inventory()
        result = inspect_source(self.sid, self.digest, self.roots['audit'], self.roots['bronze'])
        self.assertEqual(result['csv_count'], 9)
        self.assertEqual(result['adf_run_id'], RID)
        self.assertEqual(result['complete_sha256'], self.digest)
        self.assertTrue(all(f['header_bytes'] > 0 for f in result['csv_reads']))
        self.assertEqual(self.inventory(), before)
        self.assertFalse(self.roots['silver'].exists())

    def test_wrong_approval_fails_without_writes(self):
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, 'approval hash'):
            inspect_source(self.sid, '0' * 64, self.roots['audit'], self.roots['bronze'])
        self.assertEqual(self.inventory(), before)

    def test_snapshot_traversal_rejected_before_access(self):
        with self.assertRaisesRegex(ValueError, 'Invalid snapshot'):
            inspect_source('../other', self.digest, self.roots['audit'], self.roots['bronze'])


if __name__ == '__main__':
    unittest.main()
