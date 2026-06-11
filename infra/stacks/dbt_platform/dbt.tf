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
# Human developer access (dev SA impersonation + direct BQ read) is driven by
# the curated registry in dbt-developers.yml — see local.developer_members and
# the "Human developer access" section below.
#
# WIF (GitHub OIDC) bindings:
#   dbt-dev:  no WIF — impersonated by humans (see dbt-developers.yml)
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

  # ---------------------------------------------------------------------------
  # Human developer registry — curated in dbt-developers.yml, decoded here.
  # `developers` -> "user:<email>", `groups` -> "group:<email>". Missing or
  # null keys tolerate to []. The resulting member list drives both dbt-dev SA
  # impersonation (dev only) and direct BigQuery read (every env).
  # ---------------------------------------------------------------------------
  _dev_registry   = yamldecode(file("${path.module}/dbt-developers.yml"))
  _dev_user_list  = try(local._dev_registry.developers, null) == null ? [] : local._dev_registry.developers
  _dev_group_list = try(local._dev_registry.groups, null) == null ? [] : local._dev_registry.groups

  developer_members = concat(
    [for email in local._dev_user_list : "user:${email}"],
    [for email in local._dev_group_list : "group:${email}"],
  )
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
# Cross-env + developer READ on this env's artefacts bucket.
#
# The cross-env BigQuery grants above let a foreign dbt SA read this env's DATA;
# these grants let it read this env's STATE FILES (manifest.json) — the metadata
# half that `--defer` / `--state` / `dbt clone` consume. Same inbound direction
# and same principal lists, so they stay in lock-step with the BQ grants:
#   prod apply → dbt-dev + dbt-test SAs (cross_env_reader_emails) can fetch prod's
#                latest/manifest.json as their defer baseline.
#   every apply → developer_members can `make state-pull` this env's manifest.
# objectViewer is read-only: only the owning dbt SA (objectAdmin, above) writes.
resource "google_storage_bucket_iam_member" "dbt_artefacts_cross_env_viewer" {
  for_each = toset(local.cross_env_reader_emails)
  bucket   = google_storage_bucket.dbt_artefacts.name
  role     = "roles/storage.objectViewer"
  member   = "serviceAccount:${each.key}"
}

resource "google_storage_bucket_iam_member" "dbt_artefacts_developer_viewer" {
  for_each = toset(local.developer_members)
  bucket   = google_storage_bucket.dbt_artefacts.name
  role     = "roles/storage.objectViewer"
  member   = each.key
}

# -----------------------------------------------------------------------------
# Human developer access — sourced from dbt-developers.yml (local.developer_members).
#
# 1. dbt-dev SA impersonation (DEV apply only). test/prod SAs are GH-OIDC-only
#    by design, so humans never get a token-creator binding on them — only on
#    dbt-dev, which is the humans-only SA. serviceAccountUser is paired with
#    tokenCreator so the local ADC impersonation flow (Makefile `deploy-dev`)
#    works end-to-end.
# 2. Direct BigQuery READ on THIS env's project (every apply). Lets a developer
#    browse/query dev OR test OR prod in the console AS themselves — read-only;
#    all writes still route through a dbt SA.
# -----------------------------------------------------------------------------
resource "google_service_account_iam_member" "dbt_dev_impersonators" {
  for_each           = var.environment == "dev" ? toset(local.developer_members) : toset([])
  service_account_id = google_service_account.dbt.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = each.key
}

resource "google_service_account_iam_member" "dbt_dev_sa_users" {
  for_each           = var.environment == "dev" ? toset(local.developer_members) : toset([])
  service_account_id = google_service_account.dbt.name
  role               = "roles/iam.serviceAccountUser"
  member             = each.key
}

resource "google_project_iam_member" "developer_bq_data_viewer" {
  for_each = toset(local.developer_members)
  project  = local.project_id
  role     = "roles/bigquery.dataViewer"
  member   = each.key
}

resource "google_project_iam_member" "developer_bq_job_user" {
  for_each = toset(local.developer_members)
  project  = local.project_id
  role     = "roles/bigquery.jobUser"
  member   = each.key
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
# WIF bindings: dbt-prod impersonation — workflow_dispatch OR tag pushes only.
# Two bindings because a principalSet matches one attribute value at a time.
#
# Tag-only is enforced by MEMBERSHIP on attribute.ref_type/tag, NOT an IAM condition.
# A WIF workloadIdentityUser binding condition cannot read the IdP's OIDC claims
# (e.g. request.auth.claims.ref) — such expressions evaluate false and fail closed,
# so the binding denies every token. (That broken condition silently blocked the first
# real tag deploy — v1.0.0 — while only workflow_dispatch ever worked.) GitHub OIDC
# emits ref_type ("tag"/"branch"); matching attribute.ref_type/tag admits tag pushes
# and excludes branch pushes — preserving the documented defence-in-depth (the workflow
# `if:` is gate 1, this binding is gate 2).
#
# REQUIRES the provider to map attribute.ref_type = assertion.ref_type — set in
# infra/bootstrap/bootstrap_project.sh. The provider is bootstrap-managed (not TF), so
# that mapping must exist on the live provider BEFORE this binding is applied.
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
  member             = "${local.wif_principal_prefix}/attribute.ref_type/tag"
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

# =============================================================================
# Dedicated Elementary-reporting SA  (dbt-dev-elementary)
#
# The Elementary CLI (`edr report`) is NOT a read-only tool: to assemble the
# observability dashboard it CREATEs and DROPs intermediate tables inside the
# elementary dataset (BigQuery has no session-temp tables in dbt's execution
# model, so each "temp" relation is a real table that is written then dropped).
#
# The humans-only dbt-dev SA holds only READ on prod (dataViewer via
# cross_env_readers), so it cannot run edr. Rather than widen dbt-dev — which
# would erode the "humans read prod, never write" guarantee for ALL of prod — we
# curate a SEPARATE, purpose-built SA whose ONLY power beyond read is create/drop
# WITHIN the prod ELEMENTARY dataset. Business data (RAW / STAGING / MARTS /
# ANALYTICS) stays read-only for it, exactly like dbt-dev.
#
# Lifecycle mirrors dbt-dev (humans-only, no WIF): created once in the DEV
# project, impersonated by the developers in dbt-developers.yml, and granted
# cross-project into prod by the prod apply.
#   DEV apply : create SA + developer tokenCreator/serviceAccountUser bindings.
#   PROD apply: dataViewer + jobUser on prod  +  dataEditor on prod ELEMENTARY only.
# CI does NOT use this SA — the dbt-docs.yml report step runs as dbt-prod (which
# already has write on its own project). This SA is purely the LOCAL
# `make elementary-report` / `make gha-docs` path.
# =============================================================================

locals {
  # Always lives in the DEV project, whichever env is applying — so the PROD apply
  # can grant it by email with no cross-state reference (same pattern as
  # cross_env_reader_emails). Keep in lock-step with the email hardcoded in
  # dbt-jaffleshop/profiles.yml's prod-impersonate outputs.
  dbt_dev_elementary_email = "dbt-dev-elementary@dbt-dev-jaffleshop.iam.gserviceaccount.com"
}

# --- DEV apply: the SA itself + human impersonation --------------------------
resource "google_service_account" "dbt_dev_elementary" {
  count        = var.environment == "dev" ? 1 : 0
  account_id   = "dbt-dev-elementary"
  display_name = "dbt-dev-elementary (local Elementary report: prod read + ELEMENTARY scratch)"
  description  = "Impersonated by developers to run `edr report` locally against prod. Read-only on prod business data; create/drop ONLY within the prod ELEMENTARY dataset."
}

resource "google_service_account_iam_member" "dbt_dev_elementary_impersonators" {
  for_each           = var.environment == "dev" ? toset(local.developer_members) : toset([])
  service_account_id = google_service_account.dbt_dev_elementary[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = each.key
}

resource "google_service_account_iam_member" "dbt_dev_elementary_sa_users" {
  for_each           = var.environment == "dev" ? toset(local.developer_members) : toset([])
  service_account_id = google_service_account.dbt_dev_elementary[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = each.key
}

# --- PROD apply: read prod + write ONLY the ELEMENTARY dataset ---------------
# Project-level read (business data for test-row samples + the ELEMENTARY tables)
# and jobUser (edr runs query/create/drop jobs in the prod project).
resource "google_project_iam_member" "dbt_dev_elementary_prod_bq_data_viewer" {
  count   = var.environment == "prod" ? 1 : 0
  project = local.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${local.dbt_dev_elementary_email}"
}

resource "google_project_iam_member" "dbt_dev_elementary_prod_bq_job_user" {
  count   = var.environment == "prod" ? 1 : 0
  project = local.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${local.dbt_dev_elementary_email}"
}

# Dataset-scoped editor: the ONLY write this SA gets on prod — create/drop edr's
# scratch tables inside ELEMENTARY. NON-authoritative binding (does not clobber
# other members). The ELEMENTARY dataset is created by dbt (the prod deploy
# pre-builds Elementary's models), NOT Terraform; it must exist at apply time,
# which holds once any prod release has run. If a fresh prod project has never
# deployed dbt, apply this after the first prod deploy.
resource "google_bigquery_dataset_iam_member" "dbt_dev_elementary_prod_elementary_editor" {
  count      = var.environment == "prod" ? 1 : 0
  project    = local.project_id
  dataset_id = "ELEMENTARY"
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${local.dbt_dev_elementary_email}"
}

output "dbt_dev_elementary_sa_email" {
  description = "Email of the dedicated local Elementary-report SA (created in the dev project)."
  value       = var.environment == "dev" ? google_service_account.dbt_dev_elementary[0].email : local.dbt_dev_elementary_email
}
