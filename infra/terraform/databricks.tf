locals {
  databricks_workspace_name              = "dbw-${var.project_name}-${var.environment}-${substr(var.subscription_id, 0, 8)}"
  databricks_managed_resource_group_name = "rg-${var.project_name}-${var.environment}-databricks-managed"
  databricks_access_connector_name       = "ac-${var.project_name}-${var.environment}-databricks"
  databricks_container_roles = {
    audit  = "Storage Blob Data Reader"
    bronze = "Storage Blob Data Reader"
    silver = "Storage Blob Data Contributor"
  }
}

resource "azurerm_databricks_workspace" "silver" {
  name                        = local.databricks_workspace_name
  resource_group_name         = azurerm_resource_group.foundation.name
  location                    = azurerm_resource_group.foundation.location
  sku                         = "premium"
  managed_resource_group_name = local.databricks_managed_resource_group_name
  tags                        = local.tags

  # SCC with the managed VNet provisions a persistent managed NAT gateway.
  custom_parameters {
    no_public_ip = true
  }
}

resource "azurerm_databricks_access_connector" "silver" {
  name                = local.databricks_access_connector_name
  resource_group_name = azurerm_resource_group.foundation.name
  location            = azurerm_resource_group.foundation.location
  tags                = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_role_assignment" "databricks_container" {
  for_each                         = local.databricks_container_roles
  scope                            = azurerm_storage_container.lake_area[each.key].id
  role_definition_name             = each.value
  principal_id                     = azurerm_databricks_access_connector.silver.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

# User delegation keys require account scope; blob-data permissions stay scoped
# to the three containers above.
resource "azurerm_role_assignment" "databricks_blob_delegator" {
  scope                            = azurerm_storage_account.lake.id
  role_definition_name             = "Storage Blob Delegator"
  principal_id                     = azurerm_databricks_access_connector.silver.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}
