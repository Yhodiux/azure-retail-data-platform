# Unity Catalog storage foundation

Block 4D extends the existing Access Connector credential with the Gold external
location `el_retail_data_dev_gold`, an EXTERNAL `gold` volume under
`dbw_retail_data_dev_c569ffc1.retail_data_dev`, and `READ_VOLUME`/`WRITE_VOLUME`
for the existing execution principal. AzureRM grants the connector's Managed
Identity Storage Blob Data Contributor only on the Gold container. The extension
added one Azure RBAC resource and three UC resources, with no changes or destroys.
Gold uses `/Volumes/dbw_retail_data_dev_c569ffc1/retail_data_dev/gold`, backed by
`abfss://gold@stretaildevc569ffc1.dfs.core.windows.net/olist`.
Landing remains outside the connector's data access. The foundation details
below describe the original three-volume deployment in Block 4C.2.

Block 4C.2c applied the hash-approved saved plan on 2026-10-04:
**13 added, 0 changed, 0 destroyed**. Read-only API verification confirmed
the schema, project Access Connector credential, three external locations,
three OLIST external volumes and five direct/effective grants. All locations
report file events disabled and no effective event queue. Terraform state
manages the 13 resources. Creation completed with storage validation enabled;
actual file access through `/Volumes` remains untested without Databricks compute.
The development principal is also the owner of the newly created objects.

This is a separate Terraform root and separate local state from `../terraform`.
AzureRM continues to own Azure workspace, project Access Connector and RBAC.
This root owns only project UC objects. A future Databricks Asset Bundle owns
Jobs, tasks, compute and wheel execution; neither Terraform root owns a Job.
No existing state is migrated or modified. The Databricks lock file selects
provider 1.135.0; authentication uses the operator's existing Azure CLI session.
No PAT, SAS, account key, secret or storage connection string is configured.

Reuse catalog `dbw_retail_data_dev_c569ffc1` and eastus metastore
`7a76c963-17a7-405a-bda5-850b116a3344`; the latter is checked before schema
creation. Schema: `retail_data_dev`. Storage credential: `sc_retail_data_dev`,
using the system-assigned identity of `ac-retail-data-dev-databricks`.
The managed Unity Catalog connector remains untouched.

| Area / volume | External location | Container | Access |
| --- | --- | --- | --- |
| audit | el_retail_data_dev_audit | audit | READ_VOLUME; location read_only=true |
| bronze | el_retail_data_dev_bronze | bronze | READ_VOLUME; location read_only=true |
| silver | el_retail_data_dev_silver | silver | READ_VOLUME, WRITE_VOLUME |

External location URLs remain `abfss://<container>@stretaildevc569ffc1.dfs.core.windows.net/`.
Each EXTERNAL volume is registered only at the location's `olist` subdirectory:
`abfss://<container>@stretaildevc569ffc1.dfs.core.windows.net/olist`.
This provides
`/Volumes/dbw_retail_data_dev_c569ffc1/retail_data_dev/<area>/...` without
copying files, DBFS mounts or `/mnt`. Volume-relative paths start at OLIST:
Audit `olist/<snapshot_id>/complete.json` becomes `<snapshot_id>/complete.json`
under the audit volume; Bronze `olist/<snapshot_id>/attempts/<adf_run_id>/...`
becomes `<snapshot_id>/attempts/<adf_run_id>/...` under the bronze volume.
Do not repeat `olist` when resolving a cloud path through a volume.
The three volumes are in distinct containers and do not overlap each other.
Sibling domains outside `/olist` remain available; tables or further volumes
must not be registered inside a volume's reserved `/olist` tree.
There are no Landing or Gold locations or volumes.
All three locations explicitly set `enable_file_events=false`: this batch
flow requires no Event Grid, Storage Queues or additional Azure infrastructure.

The consumer receives USE_CATALOG and USE_SCHEMA plus the volume privileges
above. It receives no READ_FILES/WRITE_FILES bypass, storage credential grant,
CREATE_EXTERNAL_VOLUME, CREATE_TABLE or ALL_PRIVILEGES. Ownership and existing
inherited administrator privileges are separate from consumer grants; an
administrator used as consumer does not demonstrate least-privilege isolation.
The approved development principal is `aldevweb@hotmail.com`. The future Job
`run_as` identity will be decided in the Jobs/Asset Bundle block and receive
its own minimum grants. No identity is created here.

`databricks_grant` manages one principal at a time. On the existing catalog it
is authoritative for that principal's direct grants; inspect them before any
apply so unrelated direct privileges are not removed. Other principals' grants
are preserved. For this review plan, the current user `aldevweb@hotmail.com`
is approved for development; the earlier catalog direct-grants GET returned `{}`.
Changing the principal requires regenerating and reviewing the plan.

## Planning

Run from the Azure Retail project directory, not the shared parent repo root:

```powershell
$foundationOutputs = terraform '-chdir=infra/terraform' output -json | ConvertFrom-Json
$env:TF_VAR_workspace_host = $foundationOutputs.databricks_workspace_host.value
$env:TF_VAR_workspace_resource_id = $foundationOutputs.databricks_workspace_id.value
$env:TF_VAR_access_connector_id = $foundationOutputs.databricks_access_connector_id.value
$env:TF_VAR_storage_account_name = $foundationOutputs.storage_account_name.value
$env:TF_VAR_execution_principal = 'aldevweb@hotmail.com' # approved development principal
terraform '-chdir=infra/unity-catalog' init '-input=false'
terraform '-chdir=infra/unity-catalog' fmt -check
terraform '-chdir=infra/unity-catalog' validate
terraform '-chdir=infra/unity-catalog' plan '-input=false' '-out=block4c2b.tfplan' '-no-color'
```

Do not apply in this block. Plan generated 2026-10-04: **13 add, 0 change,
0 destroy**: 1 schema, 1 credential, 3 locations, 3 volumes, 5 grants.
The corrected saved plan is `infra/unity-catalog/block4c2b.tfplan`, intentionally ignored.
Verified SHA256:
`a72b8f096616a30d2187458f5add55faf092650a3b895579410e9b2b3b3a4e01`.
Saved-plan contract review confirms exactly those 13 creates, file events false
on all locations, volumes under `/olist`, no skip-validation override, unchanged
minimum grants and the project-owned Access Connector. No material blocker was
observed in the corrected plan. The subsequent authorized apply succeeded;
this saved plan is historical evidence and must not be reapplied.
The previous `block4c2.tfplan`, SHA256
`169ee8b39080743f5bfd068d1e62103e540ea7462021ca7740b2a6f003360bc5`,
is REJECTED / OBSOLETE, must never be applied, and is removed locally in 4C.2b.
State, plans, `.terraform/` and wheels remain local. Keep the provider lock
file with source when versioning is separately authorized; the shared parent's
current ignore rules also ignore project source, so `git status` alone cannot
inventory new files. This block does not edit parent ignore rules or stage files.

No read privilege blocker prevented the plan, and no creation error occurred
during the authorized apply. Planning reads the existing
catalog/metastore but does not prove CREATE_STORAGE_CREDENTIAL or
CREATE_EXTERNAL_LOCATION on the metastore, CREATE_SCHEMA on the catalog,
or the eventual credential CREATE_EXTERNAL_LOCATION / location
CREATE_EXTERNAL_VOLUME permissions of the provisioning owner. No privilege
escalation is configured. Resolve an actual denial through the existing owner
if later authorized; never attempt to become Account Admin.

`skip_validation` is omitted from the storage credential and all three locations,
so the provider/API defaults enable validation. Actual validation happens during
creation/apply; generating a plan does not validate effective ADLS access.
Audit/Bronze remain read-only; Silver remains read/write. Creation completed
without validation errors; Terraform did not return a per-operation storage
validation report. No business data was written and no compute was executed.
The default owner is the provisioning identity, distinct from consumer grants.

Existing checks passed: AzureRM fmt/validate, UC fmt/validate, 47 tooling tests,
14 portable core tests in local Docker and 3 built-wheel contract tests.
The closure checks make no Azure changes or further apply. No ADF run,
Databricks compute, notebook or Job execution occurred in this foundation block.

Proposed next block: design the Asset Bundle/Jobs foundation, decide the future
`run_as` identity and prepare explicitly authorized access checks using compute.
The Job Compute policy incompatibility and actual `/Volumes` access remain pending.

## References

- [Volumes and external storage paths](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/volume)
- [Singular-principal grants](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/grant)
- [Managed identity storage credential](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/storage_credential)
