locals {
  resource_group_name = "rg-${var.project_name}-${var.environment}"
  lake_areas          = toset(["landing", "bronze", "silver", "gold", "audit"])
  tags = merge(var.tags, {
    project     = var.project_name
    environment = var.environment
    managed_by  = "terraform"
  })
}

resource "azurerm_resource_group" "foundation" {
  name     = local.resource_group_name
  location = var.location
  tags     = local.tags
}

resource "azurerm_storage_account" "lake" {
  name                            = var.storage_account_name
  resource_group_name             = azurerm_resource_group.foundation.name
  location                        = azurerm_resource_group.foundation.location
  account_kind                    = "StorageV2"
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  access_tier                     = "Hot"
  is_hns_enabled                  = true
  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  public_network_access_enabled   = true
  tags                            = local.tags
}

# Resource Manager IDs use the control plane, without creating blob-data grants.
resource "azurerm_storage_container" "lake_area" {
  for_each              = local.lake_areas
  name                  = each.value
  storage_account_id    = azurerm_storage_account.lake.id
  container_access_type = "private"
}
