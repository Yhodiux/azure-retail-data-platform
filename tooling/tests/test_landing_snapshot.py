import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tooling.landing_snapshot import (
    AzureCliStore, EXPECTED_FILES, bootstrap, canonical_inventory, discover, fingerprint,
    inventory, make_manifest, snapshot_id, validate_manifest,
)


class MemoryStore:
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
        if name in self.blobs:
            raise ValueError("Already exists")
        if name == self.fail_name:
            raise ValueError("Injected failure")
        self.blobs[name] = source.read_bytes()
        self.created.append(name)

    def list_names(self, prefix):
        return {name for name in self.blobs if name.startswith(prefix)}


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        for index, name in enumerate(sorted(EXPECTED_FILES)):
            (self.source / name).write_bytes(f"synthetic,{index}\r\n".encode())
        self.manifest = make_manifest(self.source)
        self.root = f"olist/{self.manifest['snapshot_id']}"

    def test_inventory_order_and_snapshot_are_deterministic(self):
        paths = list(self.source.iterdir())
        first, second = inventory(paths), inventory(reversed(paths))
        self.assertEqual(first, second)
        self.assertEqual(snapshot_id(first), snapshot_id(second))
        self.assertEqual(snapshot_id(first), snapshot_id(list(reversed(first))))

    def test_sha256_known_vector(self):
        path = self.source / "vector"
        path.write_bytes(b"abc")
        self.assertEqual(fingerprint(path), (3, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"))

    def test_canonical_inventory_exact_bytes(self):
        entries = [{"file_name": "b", "size_bytes": 1, "sha256": "y"},
                   {"file_name": "a", "size_bytes": 2, "sha256": "x"}]
        self.assertEqual(canonical_inventory(entries),
                         b'{"files":[{"file_name":"a","sha256":"x","size_bytes":2},{"file_name":"b","sha256":"y","size_bytes":1}],"source":"olist"}')

    def test_content_change_changes_id(self):
        (self.source / sorted(EXPECTED_FILES)[0]).write_bytes(b"different")
        self.assertNotEqual(make_manifest(self.source)["snapshot_id"], self.manifest["snapshot_id"])

    def test_name_change_changes_id_and_discovery_rejects_rename(self):
        changed = copy.deepcopy(self.manifest["files"])
        changed[0]["file_name"] = "renamed.csv"
        self.assertNotEqual(snapshot_id(changed), self.manifest["snapshot_id"])
        (self.source / sorted(EXPECTED_FILES)[0]).rename(self.source / "renamed.csv")
        with self.assertRaisesRegex(ValueError, "Unexpected inventory"):
            discover(self.source)

    def test_valid_manifest_and_timestamp_not_in_snapshot_identity(self):
        self.assertEqual(validate_manifest(self.manifest, self.source), self.manifest)
        changed = copy.deepcopy(self.manifest)
        changed["created_at_utc"] = "2020-01-01T00:00:00Z"
        self.assertEqual(validate_manifest(changed)["snapshot_id"], self.manifest["snapshot_id"])

    def test_missing_file(self):
        (self.source / sorted(EXPECTED_FILES)[0]).unlink()
        with self.assertRaisesRegex(ValueError, "missing="):
            discover(self.source)

    def test_additional_file(self):
        (self.source / "extra.csv").write_bytes(b"synthetic")
        with self.assertRaisesRegex(ValueError, "additional="):
            discover(self.source)

    def test_duplicate_and_traversal_names(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            inventory(list(self.source.iterdir()) + [next(self.source.iterdir())])
        for filename in ["../bad.csv", "/bad.csv", "..\\bad.csv", self.manifest["files"][1]["file_name"]]:
            with self.subTest(filename=filename):
                invalid = copy.deepcopy(self.manifest)
                invalid["files"][0]["file_name"] = filename
                with self.assertRaises(ValueError):
                    validate_manifest(invalid)

    def test_size_and_hash_validation(self):
        for key, value in [("size_bytes", -1), ("size_bytes", True), ("sha256", "invalid")]:
            invalid = copy.deepcopy(self.manifest)
            invalid["files"][0][key] = value
            with self.assertRaises(ValueError):
                validate_manifest(invalid)
        for key, value in [("size_bytes", 999), ("sha256", "0" * 64)]:
            invalid = copy.deepcopy(self.manifest)
            invalid["files"][0][key] = value
            invalid["snapshot_id"] = snapshot_id(invalid["files"])
            with self.assertRaisesRegex(ValueError, "Local size/hash"):
                validate_manifest(invalid, self.source)

    def test_bootstrap_publication_last_and_idempotence(self):
        store = MemoryStore()
        self.assertEqual(bootstrap(self.source, self.manifest, store)["uploaded"], 9)
        self.assertEqual(store.created[-1], self.root + "/manifest.json")
        later_manifest = make_manifest(self.source)
        self.assertEqual(bootstrap(self.source, later_manifest, store)["existing"], 9)
        self.assertEqual(len(store.created), 10)
        for file in self.manifest["files"]:
            self.assertEqual(store.blobs[self.root + "/data/" + file["file_name"]],
                             (self.source / file["file_name"]).read_bytes())

    def test_conflict_fails_without_manifest_or_overwrite(self):
        store = MemoryStore()
        name = self.root + "/data/" + self.manifest["files"][0]["file_name"]
        store.blobs[name] = b"conflicting"
        with self.assertRaisesRegex(ValueError, "Remote size/hash"):
            bootstrap(self.source, self.manifest, store)
        self.assertNotIn(self.root + "/manifest.json", store.blobs)
        self.assertEqual(store.blobs[name], b"conflicting")

    def test_partial_failure_can_resume(self):
        store = MemoryStore()
        store.fail_name = self.root + "/data/" + self.manifest["files"][3]["file_name"]
        with self.assertRaisesRegex(ValueError, "Injected"):
            bootstrap(self.source, self.manifest, store)
        self.assertEqual(len(store.blobs), 3)
        self.assertNotIn(self.root + "/manifest.json", store.blobs)
        store.fail_name = None
        result = bootstrap(self.source, self.manifest, store)
        self.assertEqual((result["existing"], result["uploaded"]), (3, 6))

    def test_published_snapshot_missing_file_is_not_repaired(self):
        store = MemoryStore()
        bootstrap(self.source, self.manifest, store)
        del store.blobs[self.root + "/data/" + self.manifest["files"][0]["file_name"]]
        with self.assertRaisesRegex(ValueError, "Published snapshot is missing"):
            bootstrap(self.source, self.manifest, store)

    def test_extra_remote_file_rejected(self):
        store = MemoryStore()
        store.blobs[self.root + "/data/extra.csv"] = b"extra"
        with self.assertRaisesRegex(ValueError, "Additional remote"):
            bootstrap(self.source, self.manifest, store)

    def test_upload_adapter_enforces_login_and_conditional_create(self):
        with patch("tooling.landing_snapshot.subprocess.run",
                   return_value=SimpleNamespace(stdout="{}")) as run:
            AzureCliStore("stretaildevc569ffc1", cli="az").create("olist/id/data/file.csv", Path("file.csv"))
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--auth-mode") + 1], "login")
            self.assertEqual(command[command.index("--container-name") + 1], "landing")
            self.assertEqual(command[command.index("--overwrite") + 1], "false")
            self.assertEqual(command[command.index("--if-none-match") + 1], "*")
            self.assertNotIn("--account-key", command)
            self.assertNotIn("--sas-token", command)

    def test_invalid_local_manifest_never_calls_store(self):
        store = MemoryStore()
        invalid = copy.deepcopy(self.manifest)
        invalid["snapshot_id"] = "invalid"
        with self.assertRaisesRegex(ValueError, "snapshot_id"):
            bootstrap(self.source, invalid, store)
        self.assertEqual(store.blobs, {})


if __name__ == "__main__":
    unittest.main()
