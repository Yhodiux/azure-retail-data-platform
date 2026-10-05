"""Pure identity/path/metadata contracts for the existing Audit consumer."""
import hashlib
import json
import re
from pathlib import Path

from tooling.bronze_verification import json_bytes, read_json, sha256, validate_ids
from tooling.landing_snapshot import validate_manifest

ACCOUNT = "stretaildevc569ffc1"
FACTORY = ("/subscriptions/c569ffc1-cb82-4e95-a30b-0b25b1628ea3"
           "/resourceGroups/rg-retail-data-dev/providers/Microsoft.DataFactory"
           "/factories/adf-retail-data-dev-c569ffc1")
TABLE_FILES = {name: "olist_" + name + "_dataset.csv" for name in
               ("customers", "orders", "order_items", "order_payments", "products", "sellers")}
RUNTIME = "15.4.x-scala2.12"
CSV_OPTIONS = {"header": "true", "mode": "FAILFAST", "enforceSchema": "false",
               "timestampFormat": "yyyy-MM-dd HH:mm:ss", "encoding": "UTF-8"}


def digest(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("Expected lowercase SHA256")
    return value


def attempt_id(value):
    if not isinstance(value, str) or not re.fullmatch("[1-9][0-9]*", value):
        raise ValueError("attempt_id must be a positive Databricks job run ID")
    return value


def volume_root(catalog, schema, area):
    if area not in {"audit", "bronze", "silver"}:
        raise ValueError("Unsupported volume")
    if any(not re.fullmatch("[a-z][a-z0-9_]*", name) for name in (catalog, schema)):
        raise ValueError("Invalid catalog/schema")
    return Path("/Volumes") / catalog / schema / area


def dfs(container, relative):
    return f"https://{ACCOUNT}.dfs.core.windows.net/{container}/olist/{relative}"


def parse_complete(raw, snapshot, approved_hash):
    if sha256(raw) != digest(approved_hash):
        raise ValueError("Audit COMPLETE approval hash mismatch")
    c = read_json(raw, "Audit COMPLETE")
    validate_ids(snapshot, c.get("adf_run_id"))
    expected_keys = {"schema_version", "status", "snapshot_id", "adf_run_id", "account",
                     "factory_id", "bronze_path", "manifest_sha256", "file_count", "total_bytes", "evidence"}
    if set(c) != expected_keys or type(c["schema_version"]) is not int or c["schema_version"] != 1:
        raise ValueError("Unsupported Audit COMPLETE contract")
    if (c["status"] != "COMPLETE" or c["snapshot_id"] != snapshot or c["account"] != ACCOUNT
            or c["factory_id"] != FACTORY or type(c["file_count"]) is not int or c["file_count"] != 9
            or type(c["total_bytes"]) is not int or c["total_bytes"] < 0):
        raise ValueError("Audit COMPLETE identity/status/count mismatch")
    candidate = f"{snapshot}/attempts/{c['adf_run_id']}"
    if c["bronze_path"] != dfs("bronze", candidate):
        raise ValueError("Unapproved Bronze path")
    digest(c["manifest_sha256"])
    if not isinstance(c["evidence"], dict) or set(c["evidence"]) != {"run", "verification"}:
        raise ValueError("Invalid Audit evidence references")
    for name, ref in c["evidence"].items():
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                or ref["path"] != dfs("audit", f"{snapshot}/runs/{c['adf_run_id']}/{name}.json")):
            raise ValueError("Unapproved evidence path")
        digest(ref["sha256"])
    return c


def resolve_source(c, audit, bronze):
    """Check the real manifest and both hash-bound Audit evidence documents."""
    sid, rid = c["snapshot_id"], c["adf_run_id"]
    candidate = bronze / sid / "attempts" / rid
    raw = (candidate / "manifest.json").read_bytes()
    manifest = validate_manifest(read_json(raw, "Bronze manifest"))
    if (sha256(raw) != c["manifest_sha256"] or manifest["snapshot_id"] != sid
            or sum(f["size_bytes"] for f in manifest["files"]) != c["total_bytes"]):
        raise ValueError("Bronze manifest binding mismatch")
    identity = {k: c[k] for k in ["snapshot_id", "adf_run_id", "account", "factory_id", "bronze_path"]}
    evidence = {}
    for name in ["run", "verification"]:
        raw = (audit / sid / "runs" / rid / (name + ".json")).read_bytes()
        if sha256(raw) != c["evidence"][name]["sha256"]:
            raise ValueError("Audit evidence hash mismatch")
        value = read_json(raw, name)
        if value.get("schema_version") != 1 or any(value.get(k) != v for k, v in identity.items()):
            raise ValueError("Audit evidence identity mismatch")
        evidence[name] = value
    run, verified = evidence["run"], evidence["verification"]
    if (run.get("status") != "Succeeded" or run.get("pipeline_name") != "pl_landing_to_bronze_candidate"
            or run.get("parameters") != {"snapshot_id": sid}):
        raise ValueError("Audit run evidence mismatch")
    if (verified.get("status") != "VERIFIED" or verified.get("exact_inventory") is not True
            or any(verified.get(k) != c[k] for k in ["manifest_sha256", "file_count", "total_bytes"])):
        raise ValueError("Audit verification mismatch")
    files = sorted(manifest["files"], key=lambda f: f["file_name"])
    wanted = [{**f, "landing": {k: f[k] for k in ["size_bytes", "sha256"]},
               "bronze": {k: f[k] for k in ["size_bytes", "sha256"]}} for f in files]
    if verified.get("files") != wanted:
        raise ValueError("Audit verified file inventory mismatch")
    actual = {str(p.relative_to(candidate)).replace('\\', '/') for p in candidate.rglob('*') if p.is_file()}
    if actual != {"manifest.json"} | {"data/" + f["file_name"] for f in files}:
        raise ValueError("Bronze inventory mismatch")
    for f in files:
        path = candidate / "data" / f["file_name"]
        h = hashlib.sha256(); size = 0
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(chunk); size += len(chunk)
        if (size, h.hexdigest()) != (f["size_bytes"], f["sha256"]):
            raise ValueError("Bronze bytes changed: " + f["file_name"])
    return candidate


def build_spec(c, complete_hash, code_hash):
    return {"schema_version": 1, "snapshot_id": c["snapshot_id"], "adf_run_id": c["adf_run_id"],
            "audit_complete_sha256": digest(complete_hash), "manifest_sha256": c["manifest_sha256"],
            "code_sha256": digest(code_hash), "runtime": RUNTIME, "timezone": "UTC",
            "tables": sorted(TABLE_FILES), "csv_options": CSV_OPTIONS}


def build_id(spec):
    return "silver-sha256-" + sha256(json_bytes(spec))


def build_root(silver, spec):
    return silver / spec["snapshot_id"] / "builds" / build_id(spec)


def validate_run(value, spec, selected_attempt):
    expected = {"schema_version": 1, "status": "WRITTEN", "build_id": build_id(spec),
                "attempt_id": attempt_id(selected_attempt), "spec": spec, "tables": sorted(TABLE_FILES)}
    if value != expected:
        raise ValueError("Incompatible run metadata")
    return value


def publish_marker(path, value, create):
    """Conditional publication; pre-existing incompatible metadata always fails."""
    data = json_bytes(value)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Incompatible existing COMPLETE/evidence")
        return "no-op"
    create(path, data)  # Must implement conditional create, never overwrite.
    if path.read_bytes() != data:
        raise ValueError("Publication read-back mismatch")
    return "published"
