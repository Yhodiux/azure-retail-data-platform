import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tooling.bronze_verification import (
    AzureCliRunReader, ContainerStore, json_bytes, verify_and_publish,
)
from tooling.landing_snapshot import EXPECTED_FILES, make_manifest


class FakeStore:
    def __init__(self):
        self.blobs = {}
        self.created = []
        self.fail_name = None

    def read(self, name, destination):
        if name not in self.blobs:
            return False
        destination.write_bytes(self.blobs[name])
        return True

    def create(self, name, source):
        if name in self.blobs or name == self.fail_name:
            raise ValueError("Conditional create failed")
        self.blobs[name] = source.read_bytes()
        self.created.append(name)

    def list_names(self, prefix):
        return {name for name in self.blobs if name.startswith(prefix)}


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        source = Path(self.temp.name)
        for index, name in enumerate(sorted(EXPECTED_FILES)):
            (source / name).write_bytes(f"synthetic,{index}\r\n".encode())
        self.manifest = make_manifest(source)
        self.sid = self.manifest["snapshot_id"]
        self.rid = "11111111-1111-4111-8111-111111111111"
        self.root = f"olist/{self.sid}"
        self.candidate = f"{self.root}/attempts/{self.rid}"
        self.marker = self.root + "/complete.json"
        self.landing, self.bronze, self.audit = FakeStore(), FakeStore(), FakeStore()
        for store, root in [(self.landing, self.root), (self.bronze, self.candidate)]:
            store.blobs[root + "/manifest.json"] = json_bytes(self.manifest)
            for name in EXPECTED_FILES:
                store.blobs[root + "/data/" + name] = (source / name).read_bytes()
        self.run = {"runId": self.rid, "pipelineName": "pl_landing_to_bronze_candidate",
                    "status": "Succeeded", "parameters": {"snapshot_id": self.sid},
                    "runStart": "2026-10-02T00:00:00Z", "runEnd": "2026-10-02T00:01:00Z"}
        self.before = copy.deepcopy(self.bronze.blobs)

    def verify(self, run_id=None):
        return verify_and_publish(self.sid, run_id or self.rid, account="testaccount",
                                  factory_id="/subscriptions/test/factories/test",
                                  run_reader=SimpleNamespace(get_run=lambda rid: self.run),
                                  landing=self.landing, bronze=self.bronze, audit=self.audit)

    def rejected(self, message):
        with self.assertRaisesRegex(ValueError, message):
            self.verify()
        self.assertNotIn(self.marker, self.audit.blobs)
        self.assertEqual(self.audit.created, [])

    def test_valid_candidate_and_new_complete_published_last(self):
        result = self.verify()
        self.assertEqual(result["result"], "published")
        self.assertEqual(len(self.audit.blobs), 3)
        self.assertEqual(self.audit.created[-1], self.marker)
        self.assertEqual(self.bronze.blobs, self.before)
        self.assertEqual(self.bronze.created, [])
        self.assertEqual(self.landing.created, [])
        marker = json.loads(self.audit.blobs[self.marker])
        self.assertEqual(marker["adf_run_id"], self.rid)
        self.assertTrue(marker["bronze_path"].endswith(self.candidate))

    def test_adf_not_succeeded(self):
        for status in ["Failed", "Cancelled", "Queued", "InProgress", None]:
            with self.subTest(status=status):
                self.run["status"] = status
                self.rejected("must be Succeeded")

    def test_missing_csv(self):
        del self.bronze.blobs[self.candidate + "/data/" + sorted(EXPECTED_FILES)[0]]
        self.rejected("inventory mismatch.*missing=")

    def test_unexpected_csv(self):
        self.bronze.blobs[self.candidate + "/data/extra.csv"] = b"unexpected"
        self.rejected("inventory mismatch.*unexpected=")

    def test_unexpected_file_outside_data(self):
        self.bronze.blobs[self.candidate + "/extra.json"] = b"{}"
        self.rejected("inventory mismatch")

    def test_wrong_size(self):
        self.bronze.blobs[self.candidate + "/data/" + sorted(EXPECTED_FILES)[0]] = b"short"
        self.rejected("bronze size/SHA-256 mismatch")

    def test_wrong_sha256_same_size(self):
        key = self.candidate + "/data/" + sorted(EXPECTED_FILES)[0]
        self.bronze.blobs[key] = b"x" * len(self.bronze.blobs[key])
        self.rejected("bronze size/SHA-256 mismatch")

    def test_landing_hash_must_also_match(self):
        key = self.root + "/data/" + sorted(EXPECTED_FILES)[0]
        self.landing.blobs[key] = b"x" * len(self.landing.blobs[key])
        self.rejected("landing size/SHA-256 mismatch")

    def test_missing_landing_csv(self):
        del self.landing.blobs[self.root + "/data/" + sorted(EXPECTED_FILES)[0]]
        self.rejected("Missing landing CSV")

    def test_bronze_manifest_different(self):
        m = copy.deepcopy(self.manifest)
        m["created_at_utc"] = "2020-01-01T00:00:00Z"
        self.bronze.blobs[self.candidate + "/manifest.json"] = json_bytes(m)
        self.rejected("differs byte-for-byte")

    def test_manifest_same_semantics_different_bytes_rejected(self):
        self.bronze.blobs[self.candidate + "/manifest.json"] = json.dumps(self.manifest, indent=4).encode()
        self.rejected("differs byte-for-byte")

    def test_missing_manifest(self):
        del self.bronze.blobs[self.candidate + "/manifest.json"]
        self.rejected("Missing object")

    def test_wrong_snapshot_manifest(self):
        self.manifest["snapshot_id"] = "olist-sha256-" + "0" * 64
        self.landing.blobs[self.root + "/manifest.json"] = json_bytes(self.manifest)
        self.rejected("snapshot_id does not match")

    def test_wrong_snapshot_adf_parameter(self):
        self.run["parameters"]["snapshot_id"] = "olist-sha256-" + "0" * 64
        self.rejected("snapshot parameter mismatch")

    def test_wrong_pipeline(self):
        self.run["pipelineName"] = "another_pipeline"
        self.rejected("pipeline or snapshot")

    def test_wrong_run_id(self):
        self.run["runId"] = "22222222-2222-4222-8222-222222222222"
        self.rejected("Run ID mismatch")

    def test_nonexistent_run(self):
        self.run = None
        self.rejected("run not found")

    def test_adf_query_error_propagates_without_writes(self):
        reader = SimpleNamespace(get_run=lambda rid: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, "az", stderr="Run not found")))
        with self.assertRaises(subprocess.CalledProcessError):
            verify_and_publish(self.sid, self.rid, account="testaccount", factory_id="factory",
                               run_reader=reader, landing=self.landing, bronze=self.bronze, audit=self.audit)
        self.assertEqual(self.audit.blobs, {})

    def test_invalid_ids_rejected_before_azure(self):
        for sid, rid in [("../wrong", self.rid), (self.sid, "../wrong")]:
            with self.assertRaises(ValueError):
                verify_and_publish(sid, rid, account="testaccount", factory_id="factory",
                                   run_reader=None, landing=None, bronze=None, audit=None)

    def test_repeat_same_complete_is_noop_and_reverifies(self):
        self.verify()
        before = copy.deepcopy(self.audit.blobs)
        self.assertEqual(self.verify()["result"], "no-op")
        self.assertEqual(self.audit.blobs, before)
        self.assertEqual(len(self.audit.created), 3)
        key = self.candidate + "/data/" + sorted(EXPECTED_FILES)[0]
        self.bronze.blobs[key] = b"corrupt"
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self.verify()
        self.assertEqual(self.audit.blobs, before)

    def test_complete_conflict_other_run(self):
        self.verify()
        marker = json.loads(self.audit.blobs[self.marker])
        marker["adf_run_id"] = "22222222-2222-4222-8222-222222222222"
        self.audit.blobs[self.marker] = json_bytes(marker)
        before = copy.deepcopy(self.audit.blobs)
        with self.assertRaisesRegex(ValueError, "COMPLETE conflict"):
            self.verify()
        self.assertEqual(self.audit.blobs, before)

    def test_complete_requires_matching_evidence(self):
        self.verify()
        key = self.root + "/runs/" + self.rid + "/verification.json"
        self.audit.blobs[key] = b"{}"
        with self.assertRaisesRegex(ValueError, "evidence missing or incompatible"):
            self.verify()
        self.assertEqual(len(self.audit.created), 3)

    def test_partial_publication_recovery(self):
        self.audit.fail_name = self.root + "/runs/" + self.rid + "/verification.json"
        with self.assertRaisesRegex(ValueError, "Conditional create failed"):
            self.verify()
        self.assertNotIn(self.marker, self.audit.blobs)
        self.assertEqual(self.bronze.blobs, self.before)
        self.audit.fail_name = None
        self.assertEqual(self.verify()["result"], "published")
        self.assertEqual(len(self.audit.created), 3)

    def test_incompatible_partial_evidence_not_overwritten(self):
        key = self.root + "/runs/" + self.rid + "/verification.json"
        self.audit.blobs[key] = b"{}"
        self.rejected("Incompatible existing evidence")
        self.assertEqual(self.audit.blobs[key], b"{}")

    def test_conditional_marker_conflict_no_overwrite(self):
        self.audit.fail_name = self.marker
        with self.assertRaisesRegex(ValueError, "Conditional create failed"):
            self.verify()
        self.assertNotIn(self.marker, self.audit.blobs)
        self.assertEqual(self.bronze.blobs, self.before)

    def test_manifest_changes_during_verification_rejected(self):
        original = self.landing.read
        count = 0
        def changing_read(name, path):
            nonlocal count
            if name.endswith("manifest.json"):
                count += 1
                if count == 2:
                    self.landing.blobs[name] += b" "
            return original(name, path)
        self.landing.read = changing_read
        self.rejected("Manifest changed")


class AdapterTests(unittest.TestCase):
    def test_hns_directories_ignored_but_zero_byte_files_retained(self):
        store = ContainerStore("account", "bronze", cli="az")
        with patch.object(store, "run", return_value=[
            {"name": "root/data", "metadata": {"hdi_isfolder": "true"}},
            {"name": "root/DIR", "metadata": {"hdi_isfolder": "True"}},
            {"name": "root/empty.csv", "metadata": {}},
            {"name": "root/extra.csv", "metadata": None},
        ]) as run:
            self.assertEqual(store.list_names("root/"), {"root/empty.csv", "root/extra.csv"})
            self.assertEqual(run.call_args.args, ("list", "--prefix", "root/", "--include", "m", "--num-results", "*"))

    def test_audit_create_login_and_conditional(self):
        with patch("tooling.bronze_verification.subprocess.run", return_value=SimpleNamespace(stdout="{}")) as run:
            ContainerStore("account", "audit", cli="az").create("complete.json", Path("local.json"))
            cmd = run.call_args.args[0]
            for flag, value in [("--auth-mode", "login"), ("--container-name", "audit"),
                                ("--overwrite", "false"), ("--if-none-match", "*")]:
                self.assertEqual(cmd[cmd.index(flag)+1], value)
            self.assertNotIn("--account-key", cmd)
            self.assertNotIn("--sas-token", cmd)

    def test_bronze_and_landing_writes_refused(self):
        for container in ["landing", "bronze"]:
            with self.assertRaisesRegex(ValueError, "Only Audit"):
                ContainerStore("account", container, cli="az").create("file", Path("local"))

    def test_adf_reader_only_get(self):
        with patch("tooling.bronze_verification.subprocess.run", return_value=SimpleNamespace(stdout='{"status":"Succeeded"}')) as run:
            reader = AzureCliRunReader("sub", "rg", "factory", "az")
            reader.get_run("11111111-1111-4111-8111-111111111111")
            cmd = run.call_args.args[0]
            self.assertEqual(cmd[cmd.index("--method")+1], "get")
            self.assertIn("/pipelineruns/", cmd[cmd.index("--url")+1])
            self.assertNotIn("createRun", " ".join(cmd))


if __name__ == "__main__":
    unittest.main()
