import tempfile
import unittest
from pathlib import Path

from pyspark.sql import SparkSession
from integration_tests.fixtures import approved_source
from integration.databricks.pipeline import build, validate_and_publish, local_create
from integration.databricks.contracts import read_json


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark=(SparkSession.builder.master('local[2]').appName('silver-adapter-local-tests')
                   .config('spark.ui.enabled','false').config('spark.ui.showConsoleProgress','false')
                   .config('spark.sql.shuffle.partitions','2').getOrCreate())
        cls.spark.sparkContext.setLogLevel('ERROR')

    @classmethod
    def tearDownClass(cls): cls.spark.stop()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.sid,self.digest,_,self.roots=approved_source(Path(self.temp.name))

    def build(self,run='123'):
        return build(self.spark,snapshot=self.sid,complete_hash=self.digest,job_run_id=run,create=local_create,**self.roots)

    def publish(self,result):
        return validate_and_publish(self.spark,snapshot=self.sid,complete_hash=self.digest,
                                    selected_build=result['build_id'],selected_attempt=result['attempt_id'],
                                    create=local_create,**self.roots)

    def test_real_csv_core_dq_parquet_publication_and_repeat(self):
        result=self.build(); root=self.roots['silver']/self.sid/'builds'/result['build_id']
        self.assertFalse((root/'complete.json').exists())
        customer=self.spark.read.parquet(str(root/'attempts/123/tables/customers')).first()
        self.assertEqual(customer.customer_city,'CITY'); self.assertEqual(customer.customer_zip_code_prefix,'01001')
        self.assertEqual(self.build(),result)
        self.assertEqual(self.publish(result),'published'); self.assertEqual(self.publish(result),'no-op')
        self.assertEqual(self.build('124'),result)
        c=read_json((root/'complete.json').read_bytes(),'COMPLETE'); self.assertEqual(c['attempt_id'],'123')
        part=root/'attempts/123/tables/customers/_SUCCESS'
        with part.open('ab') as stream: stream.write(b'tampered')
        with self.assertRaisesRegex(ValueError,'Persisted manifest mismatch'): self.publish(result)

    def test_partial_attempt_is_not_overwritten(self):
        from integration.databricks.pipeline import context
        _,_,root=context(self.sid,self.digest,**self.roots)
        partial=root/'attempts/123'; partial.mkdir(parents=True); (partial/'intent.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Partial attempt'): self.build()
        self.assertEqual((partial/'intent.json').read_text(),'{}')

    def test_real_core_dq_failure_precedes_silver_writes(self):
        from retail_data_core.data_quality import DataQualityError
        with tempfile.TemporaryDirectory() as temp:
            sid,digest,_,roots=approved_source(Path(temp),customer_state='XX')
            with self.assertRaisesRegex(DataQualityError,'allowed_values:customer_state'):
                build(self.spark,snapshot=sid,complete_hash=digest,job_run_id='123',create=local_create,**roots)
            self.assertFalse(roots['silver'].exists())
