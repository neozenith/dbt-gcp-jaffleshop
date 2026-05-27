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

variable "dbt_human_impersonators" {
  description = <<-EOT
    IAM members allowed to impersonate the dbt-dev service account.
    Honored only when environment == "dev"; ignored in test/prod by design.
    Each entry must include the IAM principal prefix, e.g.:
      - "user:josh@example.com"
      - "group:dbt-developers@example.com"
      - "serviceAccount:foo@bar.iam.gserviceaccount.com"
    Populate via *.auto.tfvars or `-var 'dbt_human_impersonators=[...]'`.
  EOT
  type        = list(string)
  default     = []
}
