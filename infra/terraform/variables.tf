variable "subscription_id" {
  description = "Azure subscription selected explicitly for this deployment."
  type        = string
}

variable "location" {
  description = "Azure region for the development foundation; review before deployment."
  type        = string
  default     = "eastus"
}

variable "project_name" {
  description = "Project prefix for resource naming."
  type        = string
  default     = "retail-data"
}

variable "environment" {
  description = "Environment suffix."
  type        = string
  default     = "dev"
}

variable "storage_account_name" {
  description = "Globally unique storage account name: 3-24 lowercase letters and digits."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "Use 3-24 lowercase letters and digits."
  }
}

variable "tags" {
  description = "Additional non-sensitive resource tags."
  type        = map(string)
  default     = {}
}
