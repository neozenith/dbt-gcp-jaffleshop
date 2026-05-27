# tflint configuration. Activates:
#   - the built-in `terraform` ruleset (preset: recommended) for language-wide
#     best practices: unused declarations, naming conventions, deprecated
#     interpolation, required version constraints, etc.
#   - the `google` plugin for GCP provider-specific rules: invalid resource
#     fields, unsupported argument values, region/zone typos, etc.
#
# First-time setup on a fresh clone:
#   tflint --init             # downloads plugin binaries listed below
#   make lint                 # runs tflint --recursive

config {
  call_module_type = "all"
  force            = false
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "google" {
  enabled = true
  version = "0.32.0"
  source  = "github.com/terraform-linters/tflint-ruleset-google"
}
