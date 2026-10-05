"""Verify an ADF Bronze candidate and conditionally publish Audit COMPLETE."""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from tooling.landing_snapshot import AzureCliStore, fingerprint, validate_manifest


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def validate_ids(snapshot_id, run_id):
    if not re.fullmatch(r"olist-sha256-[0-9a-f]{64}", snapshot_id):
        raise ValueError("Invalid snapshot_id")
    try:
        if str(UUID(run_id)) != run_id:
            raise ValueError()
    except (ValueError, AttributeError, TypeError):
        raise ValueError("adf_run_id must be a canonical UUID")


class ContainerStore(AzureCliStore):
    """Reuse 3A download/conditional-create; only Audit accepts cloud writes."""
    def __init__(self, account, container, cli=None):
        if container not in {"landing", "bronze", "audit"}:
            raise ValueError("Unsupported container")
        super().__init__(account, cli)
        self.container = container

    def run(self, *args):
        if not args or args[0] not in {"exists", "download", "list", "upload"}:
            raise ValueError("Unsupported storage operation")
        if args[0] == "upload" and self.container != "audit":
            raise ValueError("Only Audit may be written")
        result = subprocess.run(
            [self.cli, "storage", "blob", *args, "--account-name", self.account,
             "--container-name", self.container, "--auth-mode", "login",
             "--only-show-errors", "-o", "json"],
            check=True, capture_output=True, text=True)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def list_names(self, prefix):
        # HNS directories appear in the Blob API. Metadata must be requested.
        blobs = self.run("list", "--prefix", prefix, "--include", "m", "--num-results", "*")
        return {b["name"] for b in blobs
                if str((b.get("metadata") or {}).get("hdi_isfolder", "false")).lower() != "true"}


class AzureCliRunReader:
    def __init__(self, subscription, resource_group, factory, cli):
        self.factory_id = (f"/subscriptions/{subscription}/resourceGroups/{resource_group}"
                           f"/providers/Microsoft.DataFactory/factories/{factory}")
        self.cli = cli

    def get_run(self, run_id):
        url = ("https://management.azure.com" + quote(self.factory_id, safe="/")
               + "/pipelineruns/" + quote(run_id, safe="") + "?api-version=2018-06-01")
        result = subprocess.run([self.cli, "rest", "--method", "get", "--url", url,
                                 "--only-show-errors", "-o", "json"],
                                check=True, capture_output=True, text=True)
        return json.loads(result.stdout)


def read_required(store, name, destination):
    if not store.read(name, destination):
        raise ValueError(f"Missing object: {name}")
    return destination.read_bytes()


def read_json(data, name):
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"Invalid JSON: {name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {name}")
    return value


def persist_evidence(store, name, value, destination):
    """Resume compatible partial publication; never replace existing evidence."""
    if store.read(name, destination):
        if read_json(destination.read_bytes(), name) != value:
            raise ValueError(f"Incompatible existing evidence: {name}")
        return
    destination.write_bytes(json_bytes(value))
    store.create(name, destination)
    if read_required(store, name, destination) != json_bytes(value):
        raise ValueError(f"Evidence read-back mismatch: {name}")


def verify_and_publish(snapshot_id, adf_run_id, *, account, factory_id, run_reader,
                       landing, bronze, audit):
    """All verification precedes any write; errors preserve the candidate."""
    validate_ids(snapshot_id, adf_run_id)
    run = run_reader.get_run(adf_run_id)
    if not isinstance(run, dict) or run.get("runId") != adf_run_id:
        raise ValueError("ADF Run ID mismatch or run not found")
    if run.get("status") != "Succeeded":
        raise ValueError(f"ADF run must be Succeeded, got {run.get('status')}")
    if (run.get("pipelineName") != "pl_landing_to_bronze_candidate"
            or run.get("parameters", {}).get("snapshot_id") != snapshot_id):
        raise ValueError("ADF pipeline or snapshot parameter mismatch")
    root = f"olist/{snapshot_id}"
    candidate = f"{root}/attempts/{adf_run_id}"
    audit_run = f"{root}/runs/{adf_run_id}"
    uri = lambda container, path: f"https://{account}.dfs.core.windows.net/{container}/{path}"
    identity = {"snapshot_id": snapshot_id, "adf_run_id": adf_run_id,
                "account": account, "factory_id": factory_id,
                "bronze_path": uri("bronze", candidate)}
    with tempfile.TemporaryDirectory(prefix="bronze-verification-") as temp:
        downloaded = Path(temp) / "download"
        landing_manifest = read_required(landing, root + "/manifest.json", downloaded)
        manifest = validate_manifest(read_json(landing_manifest, "Landing manifest"))
        if manifest["snapshot_id"] != snapshot_id:
            raise ValueError("Landing manifest snapshot mismatch")
        bronze_manifest = read_required(bronze, candidate + "/manifest.json", downloaded)
        validate_manifest(read_json(bronze_manifest, "Bronze manifest"))
        if bronze_manifest != landing_manifest:
            raise ValueError("Bronze manifest differs byte-for-byte from Landing")
        expected = {candidate + "/manifest.json"} | {
            candidate + "/data/" + f["file_name"] for f in manifest["files"]}

        def check_inventory():
            actual = bronze.list_names(candidate + "/")
            if actual != expected:
                raise ValueError(f"Bronze inventory mismatch: missing={sorted(expected-actual)}; "
                                 f"unexpected={sorted(actual-expected)}")

        check_inventory()
        verified = []
        for entry in sorted(manifest["files"], key=lambda f: f["file_name"]):
            name = entry["file_name"]
            wanted = (entry["size_bytes"], entry["sha256"])
            observed = {}
            for label, store, path in [("landing", landing, root), ("bronze", bronze, candidate)]:
                # Read/hash streams via the reusable download/fingerprint pattern.
                if not store.read(path + "/data/" + name, downloaded):
                    raise ValueError(f"Missing {label} CSV: {name}")
                size, digest = fingerprint(downloaded)
                if (size, digest) != wanted:
                    raise ValueError(f"{label} size/SHA-256 mismatch: {name}")
                observed[label] = {"size_bytes": size, "sha256": digest}
            verified.append({**entry, **observed})
        check_inventory()
        # Detect manifest changes during the verification pass.
        for store, path in [(landing, root), (bronze, candidate)]:
            if read_required(store, path + "/manifest.json", downloaded) != landing_manifest:
                raise ValueError("Manifest changed during verification")
        run_evidence = {"schema_version": 1, **identity, "pipeline_name": run["pipelineName"],
                        "status": "Succeeded", "run_start": run.get("runStart"),
                        "run_end": run.get("runEnd"), "parameters": {"snapshot_id": snapshot_id}}
        verification = {"schema_version": 1, **identity, "status": "VERIFIED",
                        "manifest_sha256": sha256(landing_manifest), "file_count": 9,
                        "total_bytes": sum(f["size_bytes"] for f in manifest["files"]),
                        "exact_inventory": True, "files": verified}
        evidence = {"run": (audit_run + "/run.json", run_evidence),
                    "verification": (audit_run + "/verification.json", verification)}
        complete = {"schema_version": 1, "status": "COMPLETE", **identity,
                    "manifest_sha256": verification["manifest_sha256"],
                    "file_count": 9, "total_bytes": verification["total_bytes"],
                    "evidence": {key: {"path": uri("audit", name),
                                       "sha256": sha256(json_bytes(value))}
                                 for key, (name, value) in evidence.items()}}
        marker = root + "/complete.json"
        if audit.read(marker, downloaded):
            if read_json(downloaded.read_bytes(), marker) != complete:
                raise ValueError("COMPLETE conflict: different run/candidate or incompatible content")
            for name, value in evidence.values():
                if read_required(audit, name, downloaded) != json_bytes(value):
                    raise ValueError(f"COMPLETE evidence missing or incompatible: {name}")
            return {"result": "no-op", "complete": complete}
        # Preflight both objects before writing any partial evidence.
        for name, value in evidence.values():
            if audit.read(name, downloaded) and downloaded.read_bytes() != json_bytes(value):
                raise ValueError(f"Incompatible existing evidence: {name}")
        for name, value in evidence.values():
            persist_evidence(audit, name, value, downloaded)
        downloaded.write_bytes(json_bytes(complete))
        audit.create(marker, downloaded)  # --overwrite false --if-none-match '*'
        if read_required(audit, marker, downloaded) != json_bytes(complete):
            raise ValueError("COMPLETE publication read-back mismatch")
        return {"result": "published", "complete": complete}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["verify-publish"])
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--adf-run-id", required=True)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--account", default="stretaildevc569ffc1")
    parser.add_argument("--resource-group", default="rg-retail-data-dev")
    parser.add_argument("--factory", default="adf-retail-data-dev-c569ffc1")
    args = parser.parse_args()
    try:
        validate_ids(args.snapshot_id, args.adf_run_id)
        landing = ContainerStore(args.account, "landing")
        reader = AzureCliRunReader(args.subscription_id, args.resource_group, args.factory, landing.cli)
        result = verify_and_publish(args.snapshot_id, args.adf_run_id, account=args.account,
                                    factory_id=reader.factory_id, run_reader=reader, landing=landing,
                                    bronze=ContainerStore(args.account, "bronze"),
                                    audit=ContainerStore(args.account, "audit"))
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        # Never retry writes automatically; a race/permission failure stops publication.
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        parser.exit(1, f"Verification/publication failed: {detail}\n")


if __name__ == "__main__":
    main()
