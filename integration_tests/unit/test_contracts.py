import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from integration_tests.fixtures import approved_source, RID
from integration.databricks.contracts import (parse_complete, resolve_source, build_spec, build_id,
                                             attempt_id, volume_root, json_bytes, sha256, publish_marker)
from integration.databricks.pipeline import local_create, complete_attempt, context
from integration.databricks.runtime import set_task_values, files_create


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.sid,self.digest,self.complete,self.roots=approved_source(Path(self.temp.name))

    def test_real_producer_contract_and_exact_paths(self):
        c=parse_complete(json_bytes(self.complete),self.sid,self.digest)
        candidate=resolve_source(c,self.roots['audit'],self.roots['bronze'])
        self.assertEqual(candidate,self.roots['bronze']/self.sid/'attempts'/RID)

    def test_unapproved_marker_bytes(self):
        with self.assertRaisesRegex(ValueError,'approval hash'):
            parse_complete(json_bytes(self.complete)+b' ',self.sid,self.digest)

    def test_status_and_unknown_contract_fields(self):
        for patch in [{'status':'Succeeded'},{'schema_version':True},{'latest':True},{'file_count':8}]:
            c={**self.complete,**patch}; raw=json_bytes(c)
            with self.assertRaises(ValueError): parse_complete(raw,self.sid,sha256(raw))

    def test_bronze_and_evidence_path_traversal(self):
        for key in ['bronze_path','evidence']:
            c=copy.deepcopy(self.complete)
            if key=='bronze_path': c[key]+='/../other'
            else: c[key]['run']['path']='https://evil/run.json'
            raw=json_bytes(c)
            with self.assertRaises(ValueError): parse_complete(raw,self.sid,sha256(raw))

    def test_manifest_tampering(self):
        p=self.roots['bronze']/self.sid/'attempts'/RID/'manifest.json'; p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'manifest binding'): resolve_source(self.complete,self.roots['audit'],self.roots['bronze'])

    def test_evidence_tampering(self):
        p=self.roots['audit']/self.sid/'runs'/RID/'verification.json'; p.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'evidence hash'): resolve_source(self.complete,self.roots['audit'],self.roots['bronze'])

    def test_csv_tampering(self):
        p=self.roots['bronze']/self.sid/'attempts'/RID/'data/olist_customers_dataset.csv'; p.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'bytes changed'): resolve_source(self.complete,self.roots['audit'],self.roots['bronze'])

    def test_extra_bronze_file(self):
        (self.roots['bronze']/self.sid/'attempts'/RID/'extra.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'inventory'): resolve_source(self.complete,self.roots['audit'],self.roots['bronze'])

    def test_build_identity_changes_with_source_or_code(self):
        spec=build_spec(self.complete,self.digest,'1'*64)
        self.assertEqual(build_id(spec),build_id(copy.deepcopy(spec)))
        self.assertNotEqual(build_id(spec),build_id({**spec,'code_sha256':'2'*64}))
        self.assertNotEqual(build_id(spec),build_id({**spec,'audit_complete_sha256':'3'*64}))
        self.assertNotIn('attempt_id',spec)

    def test_attempt_identity_rejects_paths_and_zero(self):
        self.assertEqual(attempt_id('123'),'123')
        for value in ['../123','0','01','2026-10-02',None]:
            with self.assertRaises(ValueError): attempt_id(value)

    def test_snapshot_rejected_before_filesystem_read(self):
        with self.assertRaisesRegex(ValueError,'snapshot_id'):
            context('../outside',self.digest,**self.roots)

    def test_volume_mapping_and_no_landing(self):
        self.assertEqual(str(volume_root('catalog','schema','silver')).replace('\\','/'),'/Volumes/catalog/schema/silver')
        with self.assertRaises(ValueError): volume_root('catalog','schema','landing')

    def test_conditional_publication_and_incompatible_complete(self):
        path=Path(self.temp.name)/'silver/complete.json'; value={'status':'COMPLETE'}
        self.assertEqual(publish_marker(path,value,local_create),'published')
        self.assertEqual(publish_marker(path,value,local_create),'no-op')
        with self.assertRaisesRegex(ValueError,'Incompatible'): publish_marker(path,{'status':'OTHER'},local_create)
        self.assertEqual(path.read_bytes(),json_bytes(value))

    def test_conditional_race_is_not_overwritten(self):
        path=Path(self.temp.name)/'race.json'
        def racer(path,data):
            local_create(path,b'other'); local_create(path,data)
        with self.assertRaises(FileExistsError): publish_marker(path,{'ok':True},racer)
        self.assertEqual(path.read_bytes(),b'other')

    def test_incompatible_existing_silver_complete(self):
        root=Path(self.temp.name)/'silver'; root.mkdir(); (root/'complete.json').write_bytes(json_bytes({'status':'COMPLETE'}))
        with self.assertRaisesRegex(ValueError,'Incompatible'): complete_attempt(root,build_spec(self.complete,self.digest,'1'*64))

    def test_task_values_only_two_small_identifiers(self):
        values={}; db=SimpleNamespace(jobs=SimpleNamespace(taskValues=SimpleNamespace(set=lambda key,value:values.update({key:value}))))
        set_task_values(db,{'build_id':'silver-sha256-'+'1'*64,'attempt_id':'123'})
        self.assertEqual(set(values),{'build_id','attempt_id'}); self.assertLess(len(json_bytes(values)),1024)

    def test_files_api_writer_is_conditional_and_silver_only(self):
        calls=[]
        files=SimpleNamespace(create_directory=lambda p:calls.append(('mkdir',p)),
                              upload=lambda p,data,overwrite:calls.append(('upload',p,data.read(),overwrite)))
        silver=volume_root('catalog','schema','silver'); create=files_create(SimpleNamespace(files=files),silver)
        create(silver/'snapshot/builds/build/complete.json',b'{}')
        self.assertEqual(calls[-1][-1],False)
        self.assertEqual(calls[-1][-2],b'{}')
        with self.assertRaises(ValueError): create(volume_root('catalog','schema','audit')/'file',b'bad')
        with self.assertRaises(ValueError): create(silver/'../audit/file',b'bad')
        self.assertEqual(len(calls),2)

    def test_run_metadata_rejects_wrong_attempt_and_missing_tables(self):
        from integration.databricks.contracts import validate_run, TABLE_FILES
        spec=build_spec(self.complete,self.digest,'1'*64)
        run={'schema_version':1,'status':'WRITTEN','build_id':build_id(spec),
             'attempt_id':'123','spec':spec,'tables':sorted(TABLE_FILES)}
        self.assertEqual(validate_run(run,spec,'123'),run)
        with self.assertRaisesRegex(ValueError,'run metadata'): validate_run(run,spec,'124')
        with self.assertRaisesRegex(ValueError,'run metadata'): validate_run({**run,'tables':[]},spec,'123')
