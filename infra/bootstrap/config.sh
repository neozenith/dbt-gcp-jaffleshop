#!/usr/bin/env bash
# Shared configuration for the bootstrap scripts.
# Source this file from other scripts; do not execute it directly.

# GitHub repo allowed to impersonate the deployer service accounts via WIF.
GITHUB_REPO="${GITHUB_REPO:-neozenith/dbt-gcp-jaffleshop}"

# GCS location for the Terraform state buckets in every project.
TF_STATE_LOCATION="${TF_STATE_LOCATION:-australia-southeast1}"

# Resource naming conventions, applied identically per project.
TF_SA_NAME="${TF_SA_NAME:-terraform-deployer}"
WIF_POOL_ID="${WIF_POOL_ID:-github-pool}"
WIF_PROVIDER_ID="${WIF_PROVIDER_ID:-github-provider}"

# Ordered list of <gcp-project-id>:<env-name> pairs to bootstrap.
# Order matters: dev first so failures surface in the cheapest project first.
PROJECT_PAIRS=(
  "dbt-dev-jaffleshop:dev"
  "dbt-test-jaffleshop:test"
  "dbt-prod-jaffleshop:prod"
)
