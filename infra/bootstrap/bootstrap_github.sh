#!/usr/bin/env bash
# Create the GitHub Environments (dev, test, prod) on ${GITHUB_REPO} and
# populate the four variables consumed by .github/workflows/terraform.yml:
#   TF_PROJECT_ID, TF_STATE_BUCKET, TF_SA, WIF_PROVIDER
#
# Idempotent. Run AFTER bootstrap_all.sh has succeeded — this script reads each
# GCP project number to construct the WIF_PROVIDER resource path.
#
# Authentication (none performed here):
#   - gcloud: existing CLOUDSDK_* environment / `gcloud auth` session
#   - gh:     existing `gh auth login` with admin on ${GITHUB_REPO}

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "${SCRIPT_DIR}/config.sh"

command -v gh >/dev/null || { echo "gh CLI not installed — see https://cli.github.com" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh CLI not authenticated — run 'gh auth login'" >&2; exit 1; }

log() { printf '\n==> %s\n' "$*"; }
sub() { printf '    - %s\n' "$*"; }

# Create the variable if missing, otherwise PATCH it to the desired value.
upsert_env_var() {
  local env_name="$1" var_name="$2" var_value="$3"
  if gh api "/repos/${GITHUB_REPO}/environments/${env_name}/variables/${var_name}" \
        >/dev/null 2>&1; then
    gh api -X PATCH "/repos/${GITHUB_REPO}/environments/${env_name}/variables/${var_name}" \
      -f "name=${var_name}" -f "value=${var_value}" >/dev/null
    sub "${var_name} updated"
  else
    gh api -X POST "/repos/${GITHUB_REPO}/environments/${env_name}/variables" \
      -f "name=${var_name}" -f "value=${var_value}" >/dev/null
    sub "${var_name} created"
  fi
}

for pair in "${PROJECT_PAIRS[@]}"; do
  IFS=':' read -r project env <<<"${pair}"

  log "GitHub Environment: ${env} (${project})"

  if ! project_number="$(gcloud projects describe "${project}" \
        --format='value(projectNumber)' 2>/dev/null)"; then
    echo "ERROR: project '${project}' not found in gcloud. Run bootstrap_all.sh first." >&2
    exit 1
  fi

  # PUT creates the environment if missing, no-ops if it already exists.
  gh api -X PUT "/repos/${GITHUB_REPO}/environments/${env}" >/dev/null
  sub "environment ensured"

  # Only two vars are needed at runtime — bucket name lives in
  # infra/backends/<env>.config, and project_id is derived in TF from
  # var.environment.
  upsert_env_var "${env}" "WIF_PROVIDER" "projects/${project_number}/locations/global/workloadIdentityPools/${WIF_POOL_ID}/providers/${WIF_PROVIDER_ID}"
  upsert_env_var "${env}" "TF_SA"        "${TF_SA_NAME}@${project}.iam.gserviceaccount.com"
done

echo
echo "==> All GitHub Environments configured on ${GITHUB_REPO}."
