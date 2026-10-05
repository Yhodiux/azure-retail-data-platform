locals {
  synapse_workspace_name = "syn-${var.project_name}-${var.environment}-${substr(var.subscription_id, 0, 8)}"
}

data "azurerm_client_config" "synapse" {}

# Synapse requires a default filesystem. Keep its technical storage separate
# from Gold; no data is copied here and no Spark/pipeline pools are configured.
resource "azurerm_storage_container" "synapse" {
  name                  = "synapse"
  storage_account_id    = azurerm_storage_account.lake.id
  container_access_type = "private"
}

resource "azurerm_synapse_workspace" "serving" {
  name                                 = local.synapse_workspace_name
  resource_group_name                  = azurerm_resource_group.foundation.name
  location                             = "centralus"
  storage_data_lake_gen2_filesystem_id = "${azurerm_storage_account.lake.primary_dfs_endpoint}${azurerm_storage_container.synapse.name}"
  managed_resource_group_name          = "rg-${var.project_name}-${var.environment}-synapse-managed"
  sql_administrator_login              = "retailbootstrap"
  sql_administrator_login_password     = var.synapse_bootstrap_password
  managed_virtual_network_enabled      = false
  public_network_access_enabled        = true
  tags                                 = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_synapse_workspace_aad_admin" "serving" {
  synapse_workspace_id = azurerm_synapse_workspace.serving.id
  login                = var.synapse_entra_admin_login
  object_id            = var.synapse_entra_admin_object_id
  tenant_id            = data.azurerm_client_config.synapse.tenant_id
}

resource "azurerm_synapse_firewall_rule" "operator" {
  name                 = "operator-client"
  synapse_workspace_id = azurerm_synapse_workspace.serving.id
  start_ip_address     = var.synapse_client_ipv4
  end_ip_address       = var.synapse_client_ipv4
}

# Only read access to the published analytics. No account-wide data grants,
# no Gold write privilege, and no Landing/Bronze/Silver access for Synapse.
resource "azurerm_role_assignment" "synapse_gold_reader" {
  scope                            = azurerm_storage_container.lake_area["gold"].id
  role_definition_name             = "Storage Blob Data Reader"
  principal_id                     = azurerm_synapse_workspace.serving.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

variable "synapse_bootstrap_password" {
  description = "Provisioning SQL administrator password; supply via TF_VAR, never Git. SQL serving connects with an Entra token. Terraform state/plan must remain private."
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.synapse_bootstrap_password) >= 16
    error_message = "Supply a strong bootstrap password of at least 16 characters."
  }
}

variable "synapse_entra_admin_login" {
  description = "Existing specific Entra administrator user/group display name."
  type        = string
  default     = "aldevweb@hotmail.com"
}

variable "synapse_entra_admin_object_id" {
  description = "Object ID of the existing Entra administrator, not application ID."
  type        = string
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.synapse_entra_admin_object_id))
    error_message = "Supply the administrator's existing Entra object GUID."
  }
}

variable "synapse_client_ipv4" {
  description = "Single current public IPv4 of the SQL deployment client; no allow-all firewall."
  type        = string
  validation {
    condition     = can(cidrhost("${var.synapse_client_ipv4}/32", 0)) && can(regex("^[0-9.]+$", var.synapse_client_ipv4)) && !contains(["0.0.0.0", "255.255.255.255"], var.synapse_client_ipv4)
    error_message = "Supply one valid public IPv4 address."
  }
}

output "synapse_workspace_name" {
  value = azurerm_synapse_workspace.serving.name
}

output "synapse_serverless_endpoint" {
  value = azurerm_synapse_workspace.serving.connectivity_endpoints["sqlOnDemand"]
}

output "synapse_gold_reader_principal_id" {
  value = azurerm_synapse_workspace.serving.identity[0].principal_id
}
