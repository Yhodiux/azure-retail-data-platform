output "resource_group_name" {
  value = azurerm_resource_group.foundation.name
}

output "storage_account_name" {
  value = azurerm_storage_account.lake.name
}

output "filesystem_names" {
  value = sort(keys(azurerm_storage_container.lake_area))
}

output "dfs_endpoint" {
  value = azurerm_storage_account.lake.primary_dfs_endpoint
}

output "databricks_workspace_id" {
  value = azurerm_databricks_workspace.silver.id
}

output "databricks_workspace_name" {
  value = azurerm_databricks_workspace.silver.name
}

output "databricks_workspace_host" {
  value = "https://${azurerm_databricks_workspace.silver.workspace_url}"
}

output "databricks_managed_resource_group_name" {
  value = azurerm_databricks_workspace.silver.managed_resource_group_name
}

output "databricks_access_connector_id" {
  value = azurerm_databricks_access_connector.silver.id
}

output "databricks_access_connector_principal_id" {
  value = azurerm_databricks_access_connector.silver.identity[0].principal_id
}
