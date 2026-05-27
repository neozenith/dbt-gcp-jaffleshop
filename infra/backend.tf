# Partial backend configuration.
# https://developer.hashicorp.com/terraform/language/backend#partial-configuration
#
# Populated at init time, never edited directly:
#   terraform -chdir=infra init -backend-config=./backends/<env>.config -reconfigure
terraform {
  required_version = ">= 1.10.0"

  backend "gcs" {
    bucket = ""
    prefix = ""
  }
}
