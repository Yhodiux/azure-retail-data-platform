locals {
  data_factory_name = "adf-${var.project_name}-${var.environment}-${substr(var.subscription_id, 0, 8)}"
  adf_datasets = {
    landing_manifest = { name = "ds_landing_manifest", type = "Json", filesystem = "landing" }
    landing_binary   = { name = "ds_landing_binary", type = "Binary", filesystem = "landing" }
    bronze_binary    = { name = "ds_bronze_binary", type = "Binary", filesystem = "bronze" }
  }
}

resource "azurerm_data_factory" "ingestion" {
  name                = local.data_factory_name
  location            = azurerm_resource_group.foundation.location
  resource_group_name = azurerm_resource_group.foundation.name
  tags                = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_role_assignment" "adf_landing_reader" {
  scope                            = azurerm_storage_container.lake_area["landing"].id
  role_definition_name             = "Storage Blob Data Reader"
  principal_id                     = azurerm_data_factory.ingestion.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "adf_bronze_contributor" {
  scope                            = azurerm_storage_container.lake_area["bronze"].id
  role_definition_name             = "Storage Blob Data Contributor"
  principal_id                     = azurerm_data_factory.ingestion.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_data_factory_linked_service_data_lake_storage_gen2" "lake" {
  name                 = "ls_adls_managed_identity"
  data_factory_id      = azurerm_data_factory.ingestion.id
  url                  = azurerm_storage_account.lake.primary_dfs_endpoint
  use_managed_identity = true
}

# The typed Json/Binary dataset resources in AzureRM 4.81.0 only expose
# AzureBlobStorageLocation. The supported generic dataset represents Gen2
# AzureBlobFSLocation directly, without another provider or resource service.
resource "azurerm_data_factory_custom_dataset" "ingestion" {
  for_each        = local.adf_datasets
  name            = each.value.name
  data_factory_id = azurerm_data_factory.ingestion.id
  type            = each.value.type
  parameters = {
    folder_path = ""
    file_name   = ""
  }

  linked_service {
    name = azurerm_data_factory_linked_service_data_lake_storage_gen2.lake.name
  }

  type_properties_json = jsonencode({
    location = {
      type       = "AzureBlobFSLocation"
      fileSystem = each.value.filesystem
      folderPath = { value = "@dataset().folder_path", type = "Expression" }
      fileName   = { value = "@dataset().file_name", type = "Expression" }
    }
  })
}

resource "azurerm_data_factory_pipeline" "landing_to_bronze_candidate" {
  name            = "pl_landing_to_bronze_candidate"
  data_factory_id = azurerm_data_factory.ingestion.id
  description     = "Binary candidate ingestion only. Succeeded is not COMPLETE; Block 3C verifies SHA-256 and publishes complete.json."
  parameters      = { snapshot_id = "" }
  activities_json = file("${path.module}/adf/landing_to_bronze_candidate.activities.json")
  depends_on = [
    azurerm_data_factory_custom_dataset.ingestion,
    azurerm_role_assignment.adf_landing_reader,
    azurerm_role_assignment.adf_bronze_contributor,
  ]
}
