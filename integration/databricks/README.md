# Azure Retail Data Platform — Bronze → Silver → Gold

Azure Databricks Premium and Unity Catalog are deployed. Access to the Audit,
Bronze, Silver and Gold external volumes uses an Azure Databricks Access Connector
with Managed Identity. Unity Catalog and AzureRM retain their existing Terraform
ownership; the deployed Jobs are managed by the Databricks Asset Bundle.

`retail_silver` (Job `927792836355468`) completed Bronze → Silver successfully
on 2026-10-04 (run `398855049611878`). It produced six Parquet tables:
customers (99,441 rows), orders (99,441), order_items (112,650),
order_payments (103,886), products (32,951) and sellers (3,095).
DQ and persisted-data validation passed, including all five referential checks.

A second execution with the same approved inputs on 2026-10-05 (run
`1118167324398464`) completed successfully and returned `no-op` after
revalidation. It retained the original build, published attempt and COMPLETE
SHA256 `79900b6c5db09df534697310dfaa3fa1120885420fab7cc5bb396566bff0b51c`,
with one build/attempt and unchanged counts. Both runs' ephemeral compute
terminated successfully.

`retail_gold` (Job `396644872610919`) completed Silver → Gold on 2026-10-05
(run `336824124776750`, SUCCESS). It reuses the five Portable Data Core
transformations and writes Parquet under `gold/olist/<snapshot_id>/datasets/`.
Its ephemeral compute terminated successfully.

| Gold dataset | Rows | Analytical grain |
|---|---:|---|
| sales_by_state | 27 | Customer state |
| sales_by_category | 74 | Product category, including UNKNOWN |
| sales_by_payment_type | 5 | Payment type |
| top_sellers | 3,095 | Seller ID and state |
| top_customers | 96,135 | Customer unique ID and state |

All five persisted datasets passed schema, nonempty count, required-key,
unique-grain and nonnegative-metric validation. Product sales reconcile to
`13,591,643.70` for state/category/seller outputs; payments reconcile to
`16,008,872.12` for payment-type/customer outputs. These are distinct measures:
item price versus payment value. Item and payment-record counts also reconcile.
Distinct order counts are not additive across categories, sellers or payment
types because one order can span multiple groups. The two `top_*` datasets
contain full grouped rankings, not a truncated top-N sample.

Gold consumes the explicitly approved Silver build and COMPLETE hash, reads its
published attempt and writes the five datasets plus `validation.json` in one task.
Existing Gold output is rejected rather than overwritten automatically; this is
a simple snapshot output, without a second Silver-style attempts/build framework.

**Synapse Serverless: next stage. Power BI: next stage.**

## Bundle and compute

Root `databricks.yml` includes the Silver, Gold and read-only smoke Job definitions. Target `dev`
uses the existing Azure workspace, Azure CLI authentication and development
run_as `aldevweb@hotmail.com`. Target mode is `production` solely to preserve
explicit concurrency/retry settings; this is still a development deployment.
The dev user is also admin/UC owner: this does not test least-privilege isolation.
Production must separately approve a service identity, grants, ownership and
run_as migration. No service principal or credential is created here.

Each pipeline uses ephemeral single-node Jobs Compute: DBR `15.4.x-scala2.12`,
`Standard_D4ds_v4`, `CLASSIC_PREVIEW`, `is_single_node=true`, STANDARD engine,
Dedicated access mode assigned to the dev user, ON_DEMAND_AZURE and no policy.
The CLI-normalized definition includes `num_workers=0`; other single-node
configuration is supplied by Databricks. Job concurrency is 1, timeout is 1800
seconds and both tasks have zero automatic retries. No schedule is configured.

`build_silver` -> `validate_and_publish_silver` use Python adapter scripts and
the portable core and separate adapter wheels as task libraries. There is no wheel entry point
invented and no extra `[local-test]` installed. Cloud integration never enters
the portable core wheel. The adapter wheel includes the two existing tooling
contract modules for their pure functions; Azure CLI storage operations are
never invoked by the Databricks tasks.

## Exact input approval and source contract

Both Job parameters must be supplied explicitly; empty defaults fail closed:

- `snapshot_id`: canonical `olist-sha256-<64 lowercase hex>`.
- `audit_complete_sha256`: SHA256 of the approved Audit COMPLETE raw bytes.

The build also receives `{{job.run_id}}`. Audit is read only from
`/Volumes/<catalog>/<schema>/audit/<snapshot_id>/complete.json`. The deployed
volumes already point at container `/olist`; never append another `olist`.

The adapter consumes the real producer in `tooling/bronze_verification.py`:
`schema_version=1`, `status=COMPLETE`, `snapshot_id`, canonical `adf_run_id`,
`account`, `factory_id`, `bronze_path`, `manifest_sha256`, `file_count=9`,
`total_bytes`, and `evidence.run/verification` with exact DFS paths and SHA256s.
The factory/account are the existing project resources. Bronze must resolve
exactly to `https://<account>.dfs.core.windows.net/bronze/olist/<snapshot>/attempts/<adf_run_id>`.
The adapter never lists candidates to select latest or reads Landing.

Before transformation it verifies both Audit evidence hashes/identities/statuses,
the real existing manifest contract, exact inventory and sizes/SHA256 of all nine
original CSVs. Six supported core tables are processed: customers, orders,
order_items, order_payments, products, sellers. Geolocation, reviews and category
translation are integrity-checked but have no Silver transformation in the core.
The Silver task processes these six tables; the Gold task consumes their
published Parquet output through the existing core analytics functions.

CSV parsing uses the core's explicit schemas, header verification, FAILFAST,
UTF-8 and timestamp format `yyyy-MM-dd HH:mm:ss`; Spark timezone is UTC.
The core performs normalization, schema/table/grain DQ and five referential
checks. DQ and source re-verification must pass before any Silver attempt write.

## Silver layout, identity and publication

Cloud layout:
`silver/olist/<snapshot_id>/builds/<build_id>/attempts/<job_run_id>/`.
Volume-relative layout:
`<snapshot_id>/builds/<build_id>/attempts/<job_run_id>/`.

Each attempt contains:

```text
intent.json
tables/<table_name>/*.parquet
manifest.json
dq.json
run.json
validation.json             # produced by the second task
```

Build completion is `<snapshot_id>/builds/<build_id>/complete.json` in the Silver
volume. This is a NEW versioned Silver publication contract, not a modification
of Audit COMPLETE. It binds the complete build spec, selected attempt and hashes
of manifest/validation. Validation additionally binds run/DQ hashes.

`build_id = silver-sha256-<SHA256(canonical build spec)>`. The spec includes
approved Audit marker and manifest hashes, snapshot/run, hash of portable core
and integration source bytes, runtime, UTC timezone, six tables and parser
options. It excludes timestamps, job run ID and nondeterministic wheel ZIP bytes.
`attempt_id` is the positive Databricks Job run ID, not task run ID or timestamp.

Files are created conditionally: Spark `errorifexists` for table directories,
Files API `overwrite=false` for JSON, with read-back. The Files API writer is
restricted to the Silver volume and uses existing native runtime SDK auth.
SDK 0.20.0 documented with DBR 15.4 includes the Files API used here.
No SAS/key/PAT/connection string is used. Local tests use exclusive filesystem
creation instead of contacting Databricks.

- A finished attempt can be reused; the second task fully revalidates it.
- An existing partial attempt fails; a NEW job run makes a distinct attempt.
  It is never cleaned up, repaired or overwritten automatically.
- Compatible build COMPLETE selects its recorded attempt and is revalidated;
  publication returns no-op without overwriting it.
- Incompatible marker/evidence or another attempt already published fails.
- A conditional-create race fails explicitly; it does not trigger overwrite.
- A timeout after publication can leave a valid COMPLETE with an uncertain
  client result; the next run re-verifies it rather than deleting it.

The second task re-reads Parquet and validates all six schemas/grains, row counts,
five relationships, physical file inventories/hashes, and the run/DQ metadata.
It rechecks persisted bytes and approved Bronze/Audit before writing validation
evidence and finally COMPLETE. No DataFrame is passed between tasks: only
`build_id` and `attempt_id` are set as task values by the integration adapter and
referenced using `{{tasks.build_silver.values.<key>}}`.

This is an immutable-attempt publication protocol, not WORM or a distributed
storage transaction. Authorized external writers can still alter bytes after
verification; single Job concurrency and conditional publication reduce races,
and incompatible content fails. Do not register UC tables inside these external
volumes; this block prepares Parquet files governed by volume privileges.

## Tooling, build and validation

Installed only the official Windows amd64 CLI 1.19.0 executable at
`.tools/databricks/1.19.0/databricks.exe`; no PATH/profile/admin changes or PAT.
Source: `https://github.com/databricks/cli/releases/tag/v1.19.0`.
ZIP SHA256, verified against the release asset digest:
`f5fb771698472b7e4410b1ab06f7fc04119400f218b84cb1c672e245a8fe7658`.

```powershell
$env:DATABRICKS_AUTH_TYPE = 'azure-cli'
$env:DATABRICKS_HOST = 'https://adb-7405611943709721.1.azuredatabricks.net'
./.tools/databricks/1.19.0/databricks.exe bundle validate -t dev --strict
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_integration_tests.ps1
```

`bundle validate --strict` passed against the existing authenticated workspace;
it does not build artifacts or prove cluster startup, deployment or file access.
No deploy/run or SDK storage API is invoked by these validation commands.

Python 3.11 was installed locally and used to build the approved core and adapter
wheels. For subsequent builds, activate a supported Python 3.11 environment and
run `python scripts/build_bundle_wheel.py` and `python scripts/build_adapter_wheel.py`.
The builders use `pip wheel --no-deps` with pinned setuptools. The deployed dev
Bundle verifies the approved wheel SHA256s before upload instead of rebuilding;
changed artifacts require new approval and updated hashes.

Local evidence: 18 contract/API-boundary tests and 3 real Spark integration tests;
the latter use the pinned existing Spark 3.5.4 Docker image, network disabled,
synthetic CSVs and temporary local output. Fixtures use the REAL existing Bronze
COMPLETE producer. Existing 47 tooling, 14 core and 3 packaging tests pass.
Gold adds two Spark persistence/validation tests and an installed-launcher test.
The deployed read-only smoke and successful Silver runs additionally verified
runtime imports, volume access, native SDK authentication, compute startup and
conditional publication on DBR 15.4. The second Silver run demonstrated
idempotent reuse and revalidation against the real approved dataset.

References:
- https://learn.microsoft.com/en-us/azure/databricks/dev-tools/cli/install
- https://learn.microsoft.com/en-us/azure/databricks/dev-tools/bundles/resources
- https://docs.databricks.com/api/files/v2/download-file
- https://raw.githubusercontent.com/databricks/databricks-sdk-py/v0.20.0/databricks/sdk/service/files.py

## Installed adapter imports

All task entry scripts use normal imports from installed packages, compatible
with the Workspace Python-task launcher executing source without defining the
entry script's `__file__`.

`integration/pyproject.toml` builds a separate `retail-databricks-adapters` wheel
containing the adapters and the two existing pure tooling contract modules.
It depends only on `retail-data-core==0.1.0`; it does not copy the portable core
or install PySpark/Databricks SDK. Those runtime services remain supplied by DBR.
Both wheels are task libraries for smoke, Silver and Gold. The portable core wheel
is unchanged. Explicit artifact sources and SHA256 guards ensure deployment
uploads exactly the reviewed wheels; nested build/egg-info directories are excluded.

The regression suite executes each actual entry source with `__name__=__main__`,
no `__file__`, isolated Python `-I`, a temporary working directory, and `--help`.
Imports must resolve to installed wheels, not the checkout. Argument-parser help
exits before services or transformations; no Silver pipeline is executed.
Run after installing both wheels locally with `pip install --no-deps`:
`python -B -m unittest discover -s integration_tests/bootstrap -v`.

Remaining uses of `__file__` belong to normally imported modules: core/adapter
source fingerprinting and reporting the imported core module location. Python's
loader defines module `__file__`; these do not bootstrap an entry script or rely
on a local checkout. Local build/verifier scripts also use `__file__` under the
normal Python launcher, never the Databricks task launcher.
