# Landing snapshot tooling (Block 3A)

Run from the repository root. Only Python's standard library is needed locally.
The tool is separate from `src/retail_data_core` and does not parse CSV content.

```powershell
python -B -m unittest discover -s tooling/tests -v
python -B -m tooling.landing_snapshot dry-run --source-dir archive
python -B -m tooling.landing_snapshot validate --source-dir archive --manifest <local-manifest.json>
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```

Dry-run and validate do not invoke Azure CLI or write a manifest to disk. Dry-run
prints the generated manifest. Exactly the nine expected files must be present;
additional entries and symbolic links are rejected. Original files remain unchanged.

Snapshot identity hashes UTF-8 JSON of `source` and the sorted file inventory with
sorted keys and compact separators. Timestamps are excluded. Names, byte sizes and
SHA-256 values are included. Metadata schema version is 1.

## Upload capability (not authorized for execution in Block 3A)

The explicit `upload` subcommand uses the authenticated Azure CLI on PATH and
`--auth-mode login` for every storage command. The operator needs data access to
Landing; this tool neither authenticates interactively nor assigns permissions.
No account keys, connection strings or SAS are accepted.

Future command, only after upload authorization:

```powershell
python -B -m tooling.landing_snapshot upload --source-dir archive --account stretaildevc569ffc1
```

Files go to `landing/olist/<snapshot_id>/data/<original-name>`. Existing objects
are downloaded and verified by size and SHA-256; mismatches fail. Missing objects
are conditionally created without overwrite, downloaded and verified. Temporary
downloads are removed automatically. Manifest is conditionally created last at
`landing/olist/<snapshot_id>/manifest.json` and read back for verification.

A failed upload leaves only a partial, unpublished snapshot. A retry verifies
existing files and resumes missing files. An equivalent published manifest is
retained, including its original timestamp. A published snapshot with missing or
different files fails without attempting repair. Concurrent conditional-create
conflicts fail safely; retry explicitly. Use a single uploader and do not modify
Landing after publication: this protocol does not implement WORM or lock out other
writers. Neither the tool nor this block writes Bronze/Audit or creates ADF.

## Block 3C.1: Bronze candidate verification

The separate `python -B -m tooling.bronze_verification` interface checks the real
ADF run, exact Bronze inventory, byte-identical manifests, and Landing/Bronze
sizes and SHA-256 before conditionally publishing Audit evidence and COMPLETE.
See [the contracts, command and required RBAC](bronze_verification.md).
Implementation and tests are local only in Block 3C.1; real execution requires
subsequent authorization. No 3A bootstrap operation is repeated by this module.
