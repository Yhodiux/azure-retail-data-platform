"""Gold end-to-end Parquet validation with synthetic core fixtures."""
import tempfile
import unittest
from pathlib import Path

import test_core
from pyspark.sql import functions as F

from integration.databricks.gold import build_gold, reconcile, silver_publication, transform, validate_dataset
from integration.databricks.contracts import json_bytes, sha256
from integration.databricks.pipeline import local_create


class GoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_core.PortableCoreTests.setUpClass()
        cls.spark = test_core.PortableCoreTests.spark
        cls.tables = test_core.PortableCoreTests.tables
        cls.outputs = {name: df.cache() for name, df in transform(cls.tables).items()}

    @classmethod
    def tearDownClass(cls):
        test_core.PortableCoreTests.tearDownClass()

    def test_persisted_gold_and_approved_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = 'olist-sha256-' + 'a' * 64
            build = 'silver-sha256-' + 'b' * 64
            source = root / 'silver' / snapshot / 'builds' / build
            marker = json_bytes({'status': 'COMPLETE', 'build_id': build, 'attempt_id': '123',
                                 'spec': {'snapshot_id': snapshot}})
            local_create(source / 'complete.json', marker)
            for name, df in self.tables.items():
                df.write.parquet(str(source / 'attempts/123/tables' / name))
            args = dict(silver=root / 'silver', gold=root / 'gold', snapshot=snapshot,
                        build_id=build, complete_hash=sha256(marker), job_run_id='456', create=local_create)
            report = build_gold(self.spark, **args)
            self.assertEqual(report['status'], 'PASSED')
            self.assertEqual(set(report['datasets']), set(self.outputs))
            self.assertTrue(all(x['row_count'] > 0 for x in report['datasets'].values()))
            self.assertTrue((root / 'gold' / snapshot / 'validation.json').is_file())
            with self.assertRaisesRegex(ValueError, 'already exists'):
                build_gold(self.spark, **args)
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                silver_publication(root / 'silver', snapshot, build, '0' * 64)
            with self.assertRaisesRegex(ValueError, 'Invalid snapshot'):
                silver_publication(root / 'silver', '../escape', build, sha256(marker))

    def test_invalid_keys_metrics_schema_and_reconciliation(self):
        state = self.outputs['sales_by_state']
        for df in [state.withColumn('customer_state', F.lit(None).cast('string')),
                   state.withColumn('total_sales', -F.col('total_sales'))]:
            with self.assertRaisesRegex(ValueError, 'Invalid Gold'):
                validate_dataset('sales_by_state', df)
        with self.assertRaisesRegex(ValueError, 'schema mismatch'):
            validate_dataset('sales_by_state', state.drop('total_sales'))
        changed = dict(self.outputs)
        changed['sales_by_state'] = state.withColumn('total_sales', F.col('total_sales') + 1)
        with self.assertRaisesRegex(ValueError, 'reconciliation failed'):
            reconcile(changed, self.tables)
