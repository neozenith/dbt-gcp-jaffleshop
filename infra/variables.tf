variable "environment" {
  description = "Deployment environment — one of dev / test / prod."
  type        = string
  nullable    = false
  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be one of 'dev', 'test', 'prod'."
  }
}

variable "region" {
  description = "Default region for regional resources."
  type        = string
  default     = "australia-southeast1"
}

# NOTE: human developer access was previously driven by var.dbt_human_impersonators.
# It is now sourced from the curated registry in dbt-developers.yml (decoded into
# local.developer_members in dbt.tf) so onboarding is a reviewed one-line YAML diff.
