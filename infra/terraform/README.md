# Azure Retail Data Platform infrastructure

This directory defines the Azure infrastructure in the current Terraform sources.
It describes declared resources, not a verification of their deployment or runtime
state in Azure. All `.tf` files in this directory belong to the same configuration.

## Storage and lake areas

`main.tf` defines a Resource Group and a Standard LRS, Hot-tier ADLS Gen2 storage
account. The configurable region defaults to `eastus`. The five private lake
containers are:

- `landing`: source files and manifests consumed by ingestion.
- `bronze`: original binary files copied into candidate ingestion attempts.
- `silver`: typed, normalized analytical data produced outside this Terraform code.
- `gold`: published analytical releases consumed by serving.
- `audit`: manifests, run metadata and quality evidence.

`synapse.tf` also defines a separate private `synapse` container in the same
storage account as the workspace's required default filesystem. It is technical
storage, separate from the five lake areas and from Gold.

Storage requires HTTPS and TLS 1.2 or later. Shared Key authorization and anonymous
blob access are disabled; Azure AD authentication is preferred. The public storage
endpoint is enabled. No storage private endpoints or WORM policy are declared.
Terraform creates infrastructure; it does not upload lake data or implement data
transformations or completion verification.

## Azure Data Factory

`adf.tf` defines a Data Factory with a system-assigned Managed Identity, one ADLS
Gen2 linked service using that identity, three parameterized datasets (one JSON
manifest and two Binary datasets), and `pl_landing_to_bronze_candidate`.

The pipeline activities are loaded from
`adf/landing_to_bronze_candidate.activities.json`. Given `snapshot_id`, the pipeline
reads and gates the Landing manifest, copies its listed files sequentially to a
Bronze attempt directory identified by the pipeline Run ID, then copies the
original manifest. There is no trigger. A successful run creates a candidate;
it does not verify SHA-256 or publish `complete.json`. See [ADF details](adf/README.md).

## Databricks

`databricks.tf` defines a Premium Azure Databricks workspace, a managed Resource
Group, and an Access Connector with a system-assigned Managed Identity. The
workspace uses `no_public_ip = true`; the source notes that Secure Cluster
Connectivity with the managed VNet provisions a persistent managed NAT gateway.

These Terraform files do not define Databricks clusters, Jobs, notebooks, Unity
Catalog storage credentials or external locations. Workspace infrastructure and
storage RBAC are declared here; workload configuration is outside this module.

## Synapse

`synapse.tf` defines a Synapse workspace in `centralus`, its managed Resource Group,
and the separate default `synapse` filesystem. The workspace has a system-assigned
Managed Identity, public network access enabled, and managed virtual networking
disabled. It configures an Entra administrator and a firewall rule limited to the
single operator IPv4 supplied as an input.

A SQL administrator login and a sensitive bootstrap password input are required
for provisioning. Supply the password through `TF_VAR_synapse_bootstrap_password`,
never through committed files. The configuration exposes the serverless SQL
endpoint but does not declare dedicated SQL pools, Spark pools, SQL objects or
Synapse pipelines.

## Identity and RBAC

The AzureRM provider uses the operator's existing Azure CLI authentication and an
explicit subscription input. Automatic resource-provider registration is disabled
(`resource_provider_registrations = "none"`), and storage operations use Azure AD.
The deployment identity needs permissions to create the declared resources and
role assignments. No subscription-wide role assignment or human blob-data role
assignment is declared in these files.

The following roles are assigned to system-assigned Managed Identities:

| Identity | Scope | Role |
| --- | --- | --- |
| Data Factory | `landing` container | Storage Blob Data Reader |
| Data Factory | `bronze` container | Storage Blob Data Contributor |
| Databricks Access Connector | `audit`, `bronze` containers | Storage Blob Data Reader |
| Databricks Access Connector | `silver`, `gold` containers | Storage Blob Data Contributor |
| Databricks Access Connector | Storage account | Storage Blob Delegator |
| Synapse workspace | `gold` container | Storage Blob Data Reader |

Databricks delegation-key permission is account-scoped; its explicit blob-data
roles remain container-scoped. Contributor roles include deletion permission.
The Synapse configuration declares no explicit data RBAC assignment on its
technical filesystem and no data roles on Landing, Bronze, Silver or Audit.
ADF's linked service uses Managed Identity rather than a key, SAS or client secret.

## Inputs, versions and local state

`versions.tf` requires Terraform `>= 1.6.0, < 2.0.0` and AzureRM `~> 4.0`.
`.terraform.lock.hcl` records AzureRM 4.81.0 and provider checksums for reproducibility.
`terraform.tfvars.example` contains fictitious foundation values; it is not a
complete input file for the current configuration. Synapse additionally requires
its bootstrap password, Entra administrator object ID and operator IPv4. Review
and explicitly supply the Entra administrator login for your deployment; its
current default is operator-specific. Project name, environment, region and tags
are configurable through the variables declared in this directory.

No remote backend is declared, so Terraform uses local state by default. State,
plans, local tfvars and `.terraform/` are ignored; the provider lock file and the
example input file belong in Git. State and saved plans can contain storage keys
and the Synapse bootstrap password, including values marked sensitive. Keep them
private with filesystem permissions and encrypted private backups. Never publish
credentials, state, plans or real local input files as portfolio artifacts.

## Cost considerations

Storage incurs capacity, operations and transfer charges. ADF incurs charges when
its activities run. Databricks declares a Premium workspace and managed networking;
the managed NAT gateway can incur persistent charges, and compute is configured
outside these files. Synapse serverless SQL queries incur usage charges. Resource
definitions alone do not establish whether resources are deployed, workloads have
run or lake containers currently contain data.
