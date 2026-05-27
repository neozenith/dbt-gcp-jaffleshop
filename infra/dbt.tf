# =============================================================================
# dbt service accounts + GCS artefact buckets, scoped per environment.
#
# Cross-env BigQuery read access is granted INTO this project from other envs'
# dbt SAs. The map below is the authority on "who can read into me":
#
#   dev:  []              — no one reads into dev
#   test: [dev]           — dbt-dev SA gets BQ reader on test
#   prod: [dev, test]     — dbt-dev and dbt-test SAs get BQ reader on prod
#
# This direction (inbound) is the correct way to model cross-env IAM with a
# single TF stack applied per env: each env's apply grants foreign principals
# into itself, no foreign-env state references needed.
#
# WIF (GitHub OIDC) bindings:
#   dbt-dev:  no WIF — impersonated by humans (see var.dbt_human_impersonators)
#   dbt-test: WIF principalSet on attribute.event_name/pull_request
#   dbt-prod: WIF principalSet on attribute.event_name/workflow_dispatch
#             AND   principalSet on attribute.event_name/push + IAM condition
#             restricting ref to refs/tags/* (release-tag pushes)
# =============================================================================

locals {
  # Inbound cross-env BigQuery readers per environment.
  cross_env_readers = {
    dev  = []
    test = ["dev"]
    prod = ["dev", "test"]
  }

  cross_env_reader_emails = [
    for env in local.cross_env_readers[var.environment] :
    "dbt-${env}@dbt-${env}-jaffleshop.iam.gserviceaccount.com"
  ]

  # WIF pool principalSet prefix — pool ID is hardcoded in bootstrap/config.sh as `github-pool`.
  wif_principal_prefix = "principalSet://iam.googleapis.com/projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/github-pool"
}

# -----------------------------------------------------------------------------
# Service account that dbt runs as in this environment.
# -----------------------------------------------------------------------------
resource "google_service_account" "dbt" {
  account_id   = "dbt-${var.environment}"
  display_name = "dbt-${var.environment} (BigQuery + GCS artefacts)"
  description  = "Runs dbt against ${local.project_id}. Cross-env read scopes live in dbt.tf."
}

# -----------------------------------------------------------------------------
# Self read/write on this env's BigQuery
# -----------------------------------------------------------------------------
resource "google_project_iam_member" "dbt_self_bq_data_editor" {
  project = local.project_id
  role    = "roles/bigquery.dataEditor"
  member  = google_service_account.dbt.member
}

resource "google_project_iam_member" "dbt_self_bq_job_user" {
  project = local.project_id
  role    = "roles/bigquery.jobUser"
  member  = google_service_account.dbt.member
}

# -----------------------------------------------------------------------------
# Cross-env READ access: grant other envs' dbt SAs reader into this project's BQ
# -----------------------------------------------------------------------------
resource "google_project_iam_member" "dbt_cross_env_bq_data_viewer" {
  for_each = toset(local.cross_env_reader_emails)
  project  = local.project_id
  role     = "roles/bigquery.dataViewer"
  member   = "serviceAccount:${each.key}"
}

resource "google_project_iam_member" "dbt_cross_env_bq_job_user" {
  for_each = toset(local.cross_env_reader_emails)
  project  = local.project_id
  role     = "roles/bigquery.jobUser"
  member   = "serviceAccount:${each.key}"
}

# -----------------------------------------------------------------------------
# GCS bucket for dbt JSON artefacts (manifest.json, run_results.json, catalog.json).
# Versioning + 90-day lifecycle keeps historical runs auditable without unbounded growth.
# -----------------------------------------------------------------------------
resource "google_storage_bucket" "dbt_artefacts" {
  name          = "${local.project_id}-dbt-artefacts"
  location      = var.region
  force_destroy = false

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket_iam_member" "dbt_artefacts_admin" {
  bucket = google_storage_bucket.dbt_artefacts.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.dbt.member
}

# -----------------------------------------------------------------------------
# Human / local-developer impersonation of dbt-dev SA.
# Honored only on dev — test/prod are GH-OIDC-only by design.
# Populate via -var or *.auto.tfvars (see variables.tf for example).
# -----------------------------------------------------------------------------
resource "google_service_account_iam_member" "dbt_human_impersonators" {
  for_each           = var.environment == "dev" ? toset(var.dbt_human_impersonators) : toset([])
  service_account_id = google_service_account.dbt.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = each.key
}

# -----------------------------------------------------------------------------
# WIF binding: dbt-test impersonation, restricted to pull_request events.
# Pool already enforces attribute.repository == 'neozenith/dbt-gcp-jaffleshop' (bootstrap),
# so this principalSet is "any PR from this repo".
# -----------------------------------------------------------------------------
resource "google_service_account_iam_member" "dbt_test_wif_pr" {
  count              = var.environment == "test" ? 1 : 0
  service_account_id = google_service_account.dbt.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.wif_principal_prefix}/attribute.event_name/pull_request"
}

# -----------------------------------------------------------------------------
# WIF bindings: dbt-prod impersonation — workflow_dispatch OR push to tags only.
# Two bindings because principalSet matches one attribute value at a time; an IAM
# condition further restricts the push binding to tag refs (block branch pushes).
# -----------------------------------------------------------------------------
resource "google_service_account_iam_member" "dbt_prod_wif_workflow_dispatch" {
  count              = var.environment == "prod" ? 1 : 0
  service_account_id = google_service_account.dbt.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.wif_principal_prefix}/attribute.event_name/workflow_dispatch"
}

resource "google_service_account_iam_member" "dbt_prod_wif_tag_push" {
  count              = var.environment == "prod" ? 1 : 0
  service_account_id = google_service_account.dbt.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.wif_principal_prefix}/attribute.event_name/push"

  condition {
    title       = "Tag refs only"
    description = "Restrict the push principalSet to tag refs (refs/tags/*) — blocks branch pushes."
    expression  = "request.auth.claims.ref.startsWith('refs/tags/')"
  }
}

# -----------------------------------------------------------------------------
# Outputs — surface SA email + bucket name so workflows / scripts can reference them.
# -----------------------------------------------------------------------------
output "dbt_service_account_email" {
  description = "Email of the dbt SA for this environment."
  value       = google_service_account.dbt.email
}

output "dbt_artefacts_bucket" {
  description = "GCS bucket holding dbt manifest.json / run_results.json / catalog.json."
  value       = google_storage_bucket.dbt_artefacts.name
}
