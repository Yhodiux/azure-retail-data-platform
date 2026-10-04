terraform {
  required_version = ">= 1.6.0, < 2.0.0"
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.118"
    }
  }
}

# Separate local state: this root never owns Azure resources or Jobs.
provider "databricks" {
  host                        = var.workspace_host
  azure_workspace_resource_id = var.workspace_resource_id
  auth_type                   = "azure-cli"
}

data "databricks_current_metastore" "existing" {}
data "databricks_catalog" "existing" {
  name = var.catalog_name
}

locals {
  prefix = "retail_data_dev"
  areas = {
    audit  = { read_only = true, privileges = ["READ_VOLUME"] }
    bronze = { read_only = true, privileges = ["READ_VOLUME"] }
    silver = { read_only = false, privileges = ["READ_VOLUME", "WRITE_VOLUME"] }
  }
}

resource "databricks_schema" "retail" {
  catalog_name  = data.databricks_catalog.existing.name
  name          = local.prefix
  comment       = "Azure Retail file integration; portable transformations remain outside Terraform."
  force_destroy = false
  lifecycle {
    precondition {
      condition     = data.databricks_current_metastore.existing.id == var.expected_metastore_id
      error_message = "Workspace must use the existing eastus metastore."
    }
  }
}

resource "databricks_storage_credential" "retail" {
  name = "sc_${local.prefix}"
  azure_managed_identity {
    access_connector_id = var.access_connector_id
  }
  comment = "Project-owned Access Connector; existing container RBAC only."
}

resource "databricks_external_location" "area" {
  for_each           = local.areas
  name               = "el_${local.prefix}_${each.key}"
  url                = "abfss://${each.key}@${var.storage_account_name}.dfs.core.windows.net/"
  credential_name    = databricks_storage_credential.retail.name
  read_only          = each.value.read_only
  enable_file_events = false
  force_destroy      = false
}

resource "databricks_volume" "area" {
  for_each         = local.areas
  name             = each.key
  catalog_name     = data.databricks_catalog.existing.name
  schema_name      = databricks_schema.retail.name
  volume_type      = "EXTERNAL"
  storage_location = "${databricks_external_location.area[each.key].url}olist"
  comment          = "OLIST domain only; container root remains available for other non-overlapping domains."
}

# Singular-principal grants preserve grants belonging to other principals.
# For an existing catalog, review any direct grants for this principal first:
# this resource is authoritative for that one principal's direct privileges.
resource "databricks_grant" "catalog_use" {
  catalog    = data.databricks_catalog.existing.name
  principal  = var.execution_principal
  privileges = ["USE_CATALOG"]
}

resource "databricks_grant" "schema_use" {
  schema     = databricks_schema.retail.id
  principal  = var.execution_principal
  privileges = ["USE_SCHEMA"]
}

resource "databricks_grant" "volume_access" {
  for_each   = local.areas
  volume     = databricks_volume.area[each.key].id
  principal  = var.execution_principal
  privileges = each.value.privileges
}

output "volume_paths" {
  value = { for area, volume in databricks_volume.area : area => volume.volume_path }
}
