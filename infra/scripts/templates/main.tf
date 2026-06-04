locals {
  # Project ID convention: dbt-<env>-jaffleshop. Must match a project that was
  # bootstrapped by infra/bootstrap/bootstrap_project.sh.
  project_id = "dbt-${var.environment}-jaffleshop"
}

# Smoke test: proves the deployer SA can read its own project. Replace / extend
# with real resources (or module calls) as the stack grows.
data "google_project" "this" {}

output "project_id" {
  value = data.google_project.this.project_id
}

output "project_number" {
  value = data.google_project.this.number
}
