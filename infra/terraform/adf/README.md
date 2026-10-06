# Block 3B: Landing to Bronze candidate (plan only)

`../adf.tf` defines one dev Data Factory with a system-assigned identity,
one ADLS Gen2 managed-identity linked service, three parameterized datasets,
one pipeline, and two container-scoped role assignments. Foundation resources
and the existing human Landing assignment are not changed or imported.

The pipeline receives `snapshot_id`; pass the full `olist-sha256-...` value.
Lookup reads `landing/olist/<snapshot_id>/manifest.json` as a single JSON object.
The gate checks manifest version 1, source `olist`, matching snapshot ID and
nonempty `files`. Invalid values fail explicitly; missing fields or incompatible
types fail expression evaluation before any copy activity can run.

ForEach iterates manifest `files` sequentially. Its single reusable Binary Copy
activity uses the exact `file_name`, not wildcard discovery, and copies to
`bronze/olist/<snapshot_id>/attempts/<pipeline().RunId>/data/<file_name>`.
After all file copies succeed, a separate Binary Copy preserves the original
manifest at the attempt root. There is no CSV parsing, mapping, compression,
merge, business transformation, deletion activity or source write.

Succeeded means a candidate was copied, not that it is COMPLETE. Block 3C must
verify byte sizes/SHA-256, validate the complete candidate inventory and publish
`complete.json`. This pipeline does not verify hashes, publish completion or
implement storage WORM. A failed attempt can contain partial data; consumers must
ignore attempts without a validated completion marker. No trigger is defined.

The factory identity receives Storage Blob Data Reader on Landing and Storage
Blob Data Contributor on Bronze. The Contributor built-in includes deletion,
although the pipeline has no delete activity. No permissions are granted on
Audit, Silver or Gold. Native ADF activity/run monitoring is sufficient for this
block; there is no lake-based logging or extra diagnostic infrastructure.

## AzureRM representation

AzureRM 4.81.0 typed JSON and Binary dataset resources only expose
`AzureBlobStorageLocation` (and HTTP for JSON), not `AzureBlobFSLocation`.
The existing provider's supported `azurerm_data_factory_custom_dataset` resource
therefore represents `Json` and `Binary` datasets with Gen2 locations directly.
The dedicated Gen2 linked-service resource uses `use_managed_identity = true`;
no key, SAS, service-principal secret or connection string is configured.
This is a provider representation detail, not an architecture change.

References:
- https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.81.0/website/docs/r/data_factory_custom_dataset.html.markdown
- https://learn.microsoft.com/en-us/azure/data-factory/format-binary
- https://learn.microsoft.com/en-us/azure/data-factory/connector-azure-data-lake-storage

`block3b.tfplan` is a local, ignored saved plan for human review. No apply or
pipeline execution is authorized by this block. Provider auto-registration
remains disabled (`resource_provider_registrations = "none"`).
