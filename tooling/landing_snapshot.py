"""Prepare and bootstrap an immutable Olist snapshot using Azure CLI login."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_FILES = frozenset([
    "olist_customers_dataset.csv", "olist_geolocation_dataset.csv",
    "olist_orders_dataset.csv", "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv", "olist_order_reviews_dataset.csv",
    "olist_products_dataset.csv", "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
])


def fingerprint(path):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def canonical_inventory(files):
    """Contract: UTF-8, sorted JSON keys, compact separators, sorted filenames."""
    return json.dumps({"source": "olist", "files": sorted(files, key=lambda f: f["file_name"])},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def snapshot_id(files):
    return "olist-sha256-" + hashlib.sha256(canonical_inventory(files)).hexdigest()


def inventory(paths):
    paths = list(paths)
    names = [p.name for p in paths]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate filenames")
    if set(names) != EXPECTED_FILES:
        raise ValueError(f"Unexpected inventory: missing={sorted(EXPECTED_FILES-set(names))}; "
                         f"additional={sorted(set(names)-EXPECTED_FILES)}")
    result = []
    for path in sorted(paths, key=lambda p: p.name):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Expected regular file: {path.name}")
        size, digest = fingerprint(path)
        result.append({"file_name": path.name, "size_bytes": size, "sha256": digest})
    return result


def discover(source_dir):
    source = Path(source_dir)
    if not source.is_dir():
        raise ValueError("Source directory does not exist")
    return inventory(list(source.iterdir()))


def make_manifest(source_dir):
    files = discover(source_dir)
    return {"manifest_version": 1, "source": "olist", "snapshot_id": snapshot_id(files),
            "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "files": files}


def validate_manifest(manifest, source_dir=None):
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be an object")
    if type(manifest.get("manifest_version")) is not int or manifest["manifest_version"] != 1:
        raise ValueError("Unsupported manifest_version")
    if manifest.get("source") != "olist":
        raise ValueError("Unexpected source")
    try:
        timestamp = datetime.fromisoformat(manifest["created_at_utc"].replace("Z", "+00:00"))
        if timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
            raise ValueError()
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ValueError("created_at_utc must be a UTC timestamp")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 9:
        raise ValueError("Manifest must contain exactly nine files")
    names = []
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"file_name", "size_bytes", "sha256"}:
            raise ValueError("Invalid file entry")
        name = entry["file_name"]
        if not isinstance(name, str) or name not in EXPECTED_FILES:
            raise ValueError("Invalid filename or path traversal")
        names.append(name)
        if type(entry["size_bytes"]) is not int or entry["size_bytes"] < 0:
            raise ValueError("Invalid size_bytes")
        if not isinstance(entry["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("Invalid sha256")
    if len(set(names)) != 9:
        raise ValueError("Duplicate filenames")
    if manifest.get("snapshot_id") != snapshot_id(files):
        raise ValueError("snapshot_id does not match inventory")
    if source_dir is not None and canonical_inventory(discover(source_dir)) != canonical_inventory(files):
        raise ValueError("Local size/hash inventory differs from manifest")
    return manifest


class AzureCliStore:
    """Only landing operations; every data command explicitly uses Entra login."""
    def __init__(self, account, cli=None):
        self.account = account
        self.cli = cli or shutil.which("az")
        if not self.cli:
            raise ValueError("Azure CLI is not on PATH")

    def run(self, *args):
        result = subprocess.run([self.cli, "storage", "blob", *args,
                                 "--account-name", self.account, "--container-name", "landing",
                                 "--auth-mode", "login", "--only-show-errors", "-o", "json"],
                                check=True, capture_output=True, text=True)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def read(self, name, destination):
        if not self.run("exists", "--name", name)["exists"]:
            return False
        self.run("download", "--name", name, "--file", str(destination), "--overwrite", "true")
        return True

    def create(self, name, source):
        # Conditional create also protects against a race after the existence check.
        self.run("upload", "--name", name, "--file", str(source),
                 "--overwrite", "false", "--if-none-match", "*")

    def list_names(self, prefix):
        return {blob["name"] for blob in self.run("list", "--prefix", prefix)}


def bootstrap(source_dir, manifest, store):
    """Verify content, create absent objects, and publish manifest last."""
    validate_manifest(manifest, source_dir)
    root = f"olist/{manifest['snapshot_id']}"
    manifest_name = root + "/manifest.json"
    expected = {root + "/data/" + f["file_name"] for f in manifest["files"]}
    with tempfile.TemporaryDirectory(prefix="olist-bootstrap-") as temp:
        downloaded = Path(temp) / "download"
        published = store.read(manifest_name, downloaded)
        if published:
            previous = validate_manifest(json.loads(downloaded.read_text(encoding="utf-8")))
            if canonical_inventory(previous["files"]) != canonical_inventory(manifest["files"]):
                raise ValueError("Published manifest differs")
        if store.list_names(root + "/data/") - expected:
            raise ValueError("Additional remote files")
        uploaded, existing = 0, 0
        for entry in manifest["files"]:
            name = root + "/data/" + entry["file_name"]
            wanted = (entry["size_bytes"], entry["sha256"])
            present = store.read(name, downloaded)
            if not present:
                if published:
                    raise ValueError("Published snapshot is missing a file")
                source = Path(source_dir) / entry["file_name"]
                if fingerprint(source) != wanted:
                    raise ValueError("Source changed during bootstrap")
                store.create(name, source)
                uploaded += 1
                if not store.read(name, downloaded):
                    raise ValueError("Uploaded file is missing")
            else:
                existing += 1
            if fingerprint(downloaded) != wanted:
                raise ValueError(f"Remote size/hash mismatch: {entry['file_name']}")
        if store.list_names(root + "/data/") != expected:
            raise ValueError("Remote inventory differs")
        if not published:
            local_manifest = Path(temp) / "manifest.json"
            local_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            store.create(manifest_name, local_manifest)
            if not store.read(manifest_name, downloaded):
                raise ValueError("Manifest publication verification failed")
            if json.loads(downloaded.read_text(encoding="utf-8")) != manifest:
                raise ValueError("Published manifest verification failed")
    return {"uploaded": uploaded, "existing": existing, "manifest_already_present": published}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["dry-run", "validate", "upload"], nargs="?", default="dry-run")
    parser.add_argument("--source-dir", default="archive")
    parser.add_argument("--account", default="stretaildevc569ffc1")
    parser.add_argument("--manifest", help="Existing local manifest to validate/use")
    args = parser.parse_args()
    try:
        manifest = (json.loads(Path(args.manifest).read_text(encoding="utf-8"))
                    if args.manifest else make_manifest(args.source_dir))
        validate_manifest(manifest, args.source_dir)
        summary = {"snapshot_id": manifest["snapshot_id"], "file_count": len(manifest["files"]),
                   "total_bytes": sum(f["size_bytes"] for f in manifest["files"]),
                   "landing_path": f"https://{args.account}.dfs.core.windows.net/landing/olist/{manifest['snapshot_id']}/",
                   "manifest": manifest}
        if args.command == "upload":
            summary["bootstrap"] = bootstrap(args.source_dir, manifest, AzureCliStore(args.account))
        print(json.dumps(summary, indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Bootstrap failed: {error}\n")


if __name__ == "__main__":
    main()
