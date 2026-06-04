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
