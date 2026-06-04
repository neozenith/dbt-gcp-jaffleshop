# Partial backend configuration for the GCS backend.
# https://developer.hashicorp.com/terraform/language/backend#partial-configuration
#
# Populated at init time, never edited directly:
#   terraform -chdir=stacks/<stack_name> init -backend-config=./backends/<env>.config -reconfigure
terraform {
  required_version = ">= 1.10.0"

  backend "gcs" {
    bucket = ""
    prefix = ""
  }
}
