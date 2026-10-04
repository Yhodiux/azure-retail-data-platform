variable "workspace_host" {
  type = string
}
variable "workspace_resource_id" {
  type = string
}
variable "access_connector_id" {
  type = string
  validation {
    condition     = endswith(var.access_connector_id, "/accessConnectors/ac-retail-data-dev-databricks")
    error_message = "Use the project's own Access Connector, never the managed Unity Catalog connector."
  }
}
variable "storage_account_name" {
  type = string
}
variable "catalog_name" {
  type    = string
  default = "dbw_retail_data_dev_c569ffc1"
}
variable "expected_metastore_id" {
  type    = string
  default = "7a76c963-17a7-405a-bda5-850b116a3344"
}
variable "execution_principal" {
  description = "Existing account user/group or service principal application ID; no broad workspace groups."
  type        = string
  validation {
    condition     = length(trimspace(var.execution_principal)) > 0 && !contains(["admins", "users", "account users"], lower(var.execution_principal))
    error_message = "Select a specific existing execution principal, not a general users/admins group."
  }
}
