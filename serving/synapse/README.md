# Synapse Serverless serving layer — deployed and validated

The SQL scripts expose the existing five Gold Parquet datasets directly through
`retail_analytics`, without copying data:
**Gold ADLS → Synapse Serverless → SQL views**.
Real SQL execution on 2026-10-05 confirmed all five views, counts matching Gold
and five analytical query result sets. Terraform is convergent (`No changes`),
as confirmed by the operator after deployment.

Workspace: `syn-retail-data-dev-c569ffc1`, region `centralus`. Real SQL provisioning
restrictions in `eastus` and `eastus2` led to this final deployment region.
Endpoint: `syn-retail-data-dev-c569ffc1-ondemand.sql.azuresynapse.net`.

| View | Real validated SQL count |
|---|---:|
| dbo.vw_sales_by_state | 27 |
| dbo.vw_sales_by_category | 74 |
| dbo.vw_sales_by_payment_type | 5 |
| dbo.vw_top_sellers | 3,095 |
| dbo.vw_top_customers | 96,135 |

`infra/terraform/synapse.tf` manages a Workspace with its built-in serverless
endpoint, an empty private technical container required as default storage, an
existing Entra administrator, one client-IP firewall rule and Gold-scoped Storage
Blob Data Reader for the workspace's system-assigned Managed Identity. No pools,
new Integration Runtime, data copying or write grants are configured.

SQL clients authenticate using the existing Azure CLI Microsoft Entra session.
The SQL database-scoped credential uses `IDENTITY = 'Managed Identity'`, and
`GoldParquet` references the exact approved snapshot's datasets directory.
The Gold credential has no secret. An initial SQL administrator password is
required for Workspace provisioning by the AzureRM provider; supply a strong
value through `TF_VAR_synapse_bootstrap_password`, not a committed file. This
bootstrap SQL login is not used by the serving script. Keep Terraform state and
plans private; sensitive inputs remain in those files.

Infrastructure inputs remain runtime variables: the existing administrator's
object ID (`TF_VAR_synapse_entra_admin_object_id`), client IPv4
(`TF_VAR_synapse_client_ipv4`) and bootstrap password. Infrastructure remains
owned by Terraform; the SQL runner only manages database serving metadata.

To apply the SQL scripts and repeat serving validation, run from the project root:

```powershell
powershell -NoProfile -File scripts/serve_synapse.ps1 -Server syn-retail-data-dev-c569ffc1-ondemand.sql.azuresynapse.net
```

The runner uses .NET SqlClient, executes scripts in order, checks all five counts,
and runs five small analytical queries. It writes one local ignored result JSON
under `.tools/synapse/`. Before creating the scoped credential, it checks for the
database master key in `retail_analytics` and creates it only if absent, using a
cryptographically generated runtime password passed as a SQL parameter. That
password is not printed, written to files or included in evidence. Existing keys
are retained. It does not install SQL drivers or execute Databricks.
The SQL views preserve Parquet decimal precision
and use UTF-8 varchar columns and datetime2(6) timestamps.

Only SQL metadata is created. OPENROWSET and validation queries read Gold; no
CETAS, COPY, BULK INSERT or storage modification is used. Product-price revenue
and payment-value revenue remain distinct; `top_*` views expose the full existing
Gold rankings and ordering is applied by the analytical queries.

Executed analytics: TOP 5 states and categories by product sales, payment-type
distribution, TOP 5 sellers and customers. All five count queries and analytical
queries passed. Power BI now imports CSV extracts from these five validated views. The final PBIX does not use a direct/live Synapse connection because of authentication restrictions of the available account. See the [dashboard](../../README.md#power-bi-dashboard) and read-only `scripts/export_powerbi.ps1` runner.

References: [Managed Identity and database-scoped credentials](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql/develop-storage-files-storage-access-control),
[AzureRM Workspace resource](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/synapse_workspace).
