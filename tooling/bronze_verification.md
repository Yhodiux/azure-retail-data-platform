# Block 3C.1: local Bronze verification and COMPLETE publisher

Implemented and tested locally only. No ADF run or real Audit publication has
been performed in this block. The command below is the interface for a later,
explicitly authorized real execution; it is not a dry-run command.

```powershell
python -B -m tooling.bronze_verification verify-publish `
  --subscription-id c569ffc1-cb82-4e95-a30b-0b25b1628ea3 `
  --snapshot-id olist-sha256-68f181a92070c57c77c00f5b989122a7818787bc0ac3e3b089f19cb01c741d6a `
  --adf-run-id <actual-adf-run-uuid>
```

Defaults: account `stretaildevc569ffc1`, resource group `rg-retail-data-dev`,
factory `adf-retail-data-dev-c569ffc1`. They can be supplied explicitly with
`--account`, `--resource-group`, `--factory`. Azure CLI must be on PATH and
already authenticated. `--help` does not contact Azure.

## Verification

Snapshot IDs and run UUIDs are validated before cloud calls. GET Pipeline Runs
uses the explicitly selected factory and API version 2018-06-01. The response
must identify the exact run, status `Succeeded`, pipeline
`pl_landing_to_bronze_candidate` and matching `snapshot_id` parameter.

The canonical Landing manifest is validated using the existing 3A contract:
version 1, source Olist, exactly the nine expected names, valid sizes/hashes,
and snapshot ID recomputed from the manifest inventory. Its ID must match the
requested snapshot. The Bronze manifest must be valid and byte-for-byte equal
to Landing, including the original timestamp and serialization.

Bronze must contain exactly `manifest.json` and the nine declared CSVs under
`data/` in `olist/<snapshot_id>/attempts/<adf_run_id>/`. The Blob API listing
requests all pages (`--num-results '*'`) and metadata. Only entries explicitly
marked `hdi_isfolder=true` are ignored; zero-byte ordinary files are not ignored.
Extra files outside `data/` also fail the inventory check.

Every Landing and Bronze CSV is downloaded to a temporary local file and hashed
in chunks. Both observed byte sizes and SHA-256 values must match the manifest.
The inventory and both manifests are checked again before publication. No CSV
is parsed, typed or transformed, and no ADF metrics substitute for byte integrity.
Temporary downloads are removed on success or failure. The source archive is
not needed for verification.

## Audit contracts (schema_version 1)

All three documents bind `snapshot_id`, `adf_run_id`, storage `account`,
`factory_id`, and the full approved `bronze_path` DFS URI. Files are UTF-8 JSON
with sorted keys, compact separators and a final newline. Deterministic evidence
uses ADF run timestamps rather than a changing local timestamp, so a repeat can
prove compatibility without rewriting its original evidence.

| Document | Location in Audit | Content |
|---|---|---|
| `run.json` | `olist/<snapshot_id>/runs/<adf_run_id>/run.json` | Identity fields, pipeline name, `status=Succeeded`, ADF `run_start` and `run_end`, snapshot parameter |
| `verification.json` | `olist/<snapshot_id>/runs/<adf_run_id>/verification.json` | Identity fields, `status=VERIFIED`, SHA-256 of manifest bytes, count 9, total CSV bytes, `exact_inventory=true`, sorted file evidence |
| `complete.json` | `olist/<snapshot_id>/complete.json` | Identity fields, `status=COMPLETE`, manifest hash, count, total bytes, paths and SHA-256 of both evidence documents |

Each file evidence entry contains `file_name`, manifest `size_bytes` and
`sha256`, plus `landing` and `bronze` objects holding each observed `size_bytes`
and `sha256`. The manifest digest hashes raw original bytes, not normalized JSON.
The total is derived from the verified manifest, not hardcoded to one dataset
release; the current approved snapshot totals 126,186,995 bytes.

## Publication and failure behavior

Only after all integrity checks pass are Audit evidence documents persisted.
Each creation is conditional (`--overwrite false --if-none-match '*'`) and read
back. COMPLETE is created last and read back. Reads always use
`--auth-mode login`; ADF GET uses the authenticated Azure CLI session. No key,
SAS, secret, connection string, role assignment, ADF execution, source write,
Bronze write, deletion or repair operation is implemented.

An existing COMPLETE must match the entire expected document and both referenced
evidence documents must match their canonical bytes. The candidate is still
fully reverified. A compatible repeat returns `result=no-op` without any writes.
A different approved run/candidate or incompatible evidence fails explicitly.
An existing marker with missing evidence is not repaired.

If evidence publication previously stopped before COMPLETE, a retry revalidates
everything, retains compatible evidence, and conditionally creates only missing
objects. Existing incompatible evidence fails before any further publication.
Concurrent conditional-create conflicts stop safely; there is no automatic retry.

Integrity failures occur before Audit writes and cannot create COMPLETE. They
exit with an error and preserve Bronze. Failed verification is reported locally,
not written as a failure record to Audit. An Audit write/read-back failure may
leave partial evidence. A transport failure after marker creation can leave a
valid marker with an uncertain client outcome; retry and reverify, never delete
or overwrite it automatically.

This protocol is not a WORM policy or a distributed lock. Verification proves
bytes observed during the pass; arbitrary concurrent/post-publication writers
can still change storage. Keep approved source/candidate/evidence content
unchanged. The repeated checks reduce detectable races but do not provide an
atomic multi-object storage transaction.

## Human permissions required for a later real execution

Principal: `04993b35-88c4-41c1-b1fa-5438088c4cca` (previously authenticated user).
No new RBAC query, assignment or real data call is performed in Block 3C.1.

| Container | Minimum appropriate built-in role | Known session state |
|---|---|---|
| Landing | Storage Blob Data Reader | Existing human Data Contributor already covers this; retain it |
| Bronze | Storage Blob Data Reader | Requires later permission diagnosis/authorization |
| Audit | Storage Blob Data Contributor | Requires later permission diagnosis/authorization; read is also needed for evidence/idempotence |

Use the container scopes formed by appending `landing`, `bronze` or `audit` to:

```text
/subscriptions/c569ffc1-cb82-4e95-a30b-0b25b1628ea3/resourceGroups/rg-retail-data-dev/providers/Microsoft.Storage/storageAccounts/stretaildevc569ffc1/blobServices/default/containers/
```

The relevant Blob data actions are `Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read`
on Landing/Bronze and read plus `.../blobs/write` on Audit. The recommended Audit
built-in Contributor also includes deletion, though this tooling never deletes.
No Silver/Gold permission is needed.

GET ADF run also requires management-plane
`Microsoft.DataFactory/factories/pipelineruns/read`. Existing subscription Owner
reported earlier covers it. Otherwise, built-in Reader scoped to the factory is
sufficient; do not add it without authorization. Factory scope:

```text
/subscriptions/c569ffc1-cb82-4e95-a30b-0b25b1628ea3/resourceGroups/rg-retail-data-dev/providers/Microsoft.DataFactory/factories/adf-retail-data-dev-c569ffc1
```

References:
- https://learn.microsoft.com/en-us/rest/api/datafactory/pipeline-runs/get?view=rest-datafactory-2018-06-01
- https://learn.microsoft.com/en-us/cli/azure/storage/blob?view=azure-cli-latest#az-storage-blob-list
- https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/storage

No deviation from Architecture v1: ADF produces candidates; this independent
verifier alone decides integrity and publishes the Audit consumer contract.
No infrastructure or Portable Data Core changes are part of this iteration.
