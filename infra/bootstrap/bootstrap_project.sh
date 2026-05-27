#!/usr/bin/env bash
# Bootstrap one GCP project so Terraform (driven from GitHub Actions) can manage it.
#
# Idempotent: re-running is safe. Every gcloud call either checks existence first
# or uses an "add"/"update" command that converges to the desired state.
#
# Creates in the target project:
#   1. Required Google APIs enabled
#   2. GCS bucket "<project>-tfstate" (UBL, PAP enforced, versioned)
#   3. Service account "terraform-deployer" with roles/owner on the project
#   4. Workload Identity Pool "github-pool"
#   5. OIDC provider "github-provider" restricted to ${GITHUB_REPO}
#   6. IAM binding allowing principals from that repo to impersonate the SA

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "${SCRIPT_DIR}/config.sh"

PROJECT_ID="${1:-}"
ENV_NAME="${2:-}"

if [[ -z "${PROJECT_ID}" || -z "${ENV_NAME}" ]]; then
  echo "Usage: $0 <project-id> <env-name>" >&2
  echo "Example: $0 dbt-dev-jaffleshop dev" >&2
  exit 2
fi

TF_STATE_BUCKET="${PROJECT_ID}-tfstate"
TF_SA_EMAIL="${TF_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

log() { printf '\n==> %s\n' "$*"; }
sub() { printf '    - %s\n' "$*"; }

log "Bootstrapping ${PROJECT_ID} (env=${ENV_NAME})"
sub "github repo  : ${GITHUB_REPO}"
sub "state bucket : gs://${TF_STATE_BUCKET} (${TF_STATE_LOCATION})"
sub "deployer SA  : ${TF_SA_EMAIL}"

# 0. Precheck: billing must be linked, otherwise bucket creation (step 2)
#    fails partway through with a confusing HTTPError 403 from GCS.
log "Checking project billing"
# Compare against both casings — gcloud's value() printer emits Python-style
# `True`/`False` but the underlying API/yaml emits lowercase. Avoids bash 4
# `${var,,}` which macOS /usr/bin/bash (3.2) does not support.
billing_status="$(gcloud billing projects describe "${PROJECT_ID}" \
  --format='value(billingEnabled)' 2>/dev/null || true)"
if [[ "${billing_status}" != "True" && "${billing_status}" != "true" ]]; then
  cat >&2 <<EOF

ERROR: project '${PROJECT_ID}' has no active billing account.

GCS bucket creation (and most other resource provisioning) will fail until a
billing account is linked. Triage:

  # 1. List billing accounts you can use:
  gcloud billing accounts list

  # 2. Check how many projects are already on the target billing account
  #    (self-serve accounts cap at ~5 — exceeding it surfaces as
  #     "FAILED_PRECONDITION: Cloud billing quota exceeded"):
  gcloud billing projects list --billing-account=ACCOUNT_ID

  # 3. Link this project (replace ACCOUNT_ID from step 1):
  gcloud billing projects link ${PROJECT_ID} --billing-account=ACCOUNT_ID

  # 4. Confirm billing is enabled:
  gcloud billing projects describe ${PROJECT_ID}

  # 5. Re-run this bootstrap (idempotent — picks up where it left off):
  ${0##*/} ${PROJECT_ID} ${ENV_NAME}

If step 3 fails with quota exceeded, either unlink an unused project with
'gcloud billing projects unlink <project>' or request a quota raise:
https://support.google.com/code/contact/billing_quota_increase

EOF
  exit 1
fi
sub "billing enabled"

# 1. Enable required APIs --------------------------------------------------
log "Enabling APIs"
gcloud services enable \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  storage.googleapis.com \
  serviceusage.googleapis.com \
  sts.googleapis.com \
  --project="${PROJECT_ID}"

# 2. GCS bucket for Terraform state ---------------------------------------
log "GCS tfstate bucket"
if gcloud storage buckets describe "gs://${TF_STATE_BUCKET}" \
    --project="${PROJECT_ID}" --format=none >/dev/null 2>&1; then
  sub "bucket exists"
else
  gcloud storage buckets create "gs://${TF_STATE_BUCKET}" \
    --project="${PROJECT_ID}" \
    --location="${TF_STATE_LOCATION}" \
    --uniform-bucket-level-access \
    --public-access-prevention
  sub "bucket created"
fi
gcloud storage buckets update "gs://${TF_STATE_BUCKET}" \
  --project="${PROJECT_ID}" --versioning >/dev/null
sub "versioning enabled"

# 3. Terraform deployer service account ------------------------------------
log "Service account"
if gcloud iam service-accounts describe "${TF_SA_EMAIL}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
  sub "service account exists"
else
  gcloud iam service-accounts create "${TF_SA_NAME}" \
    --project="${PROJECT_ID}" \
    --display-name="Terraform Deployer (${ENV_NAME})" \
    --description="GitHub Actions impersonates this SA to apply Terraform in ${PROJECT_ID}"
  sub "service account created"
fi

# 4. Grant roles/owner on the project --------------------------------------
log "Granting roles/owner to deployer SA"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${TF_SA_EMAIL}" \
  --role="roles/owner" \
  --condition=None \
  --quiet >/dev/null
sub "binding ensured"

# 5. Workload Identity Pool ------------------------------------------------
log "Workload Identity Pool"
if gcloud iam workload-identity-pools describe "${WIF_POOL_ID}" \
    --project="${PROJECT_ID}" --location=global >/dev/null 2>&1; then
  sub "pool exists"
else
  gcloud iam workload-identity-pools create "${WIF_POOL_ID}" \
    --project="${PROJECT_ID}" \
    --location=global \
    --display-name="GitHub Actions"
  sub "pool created"
fi

# 6. GitHub OIDC provider on the pool --------------------------------------
log "OIDC provider"
if gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER_ID}" \
    --project="${PROJECT_ID}" --location=global \
    --workload-identity-pool="${WIF_POOL_ID}" >/dev/null 2>&1; then
  sub "provider exists"
else
  gcloud iam workload-identity-pools providers create-oidc "${WIF_PROVIDER_ID}" \
    --project="${PROJECT_ID}" \
    --location=global \
    --workload-identity-pool="${WIF_POOL_ID}" \
    --display-name="GitHub OIDC" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.ref=assertion.ref,attribute.event_name=assertion.event_name" \
    --attribute-condition="assertion.repository == '${GITHUB_REPO}'"
  sub "provider created (restricted to repo ${GITHUB_REPO})"
fi

# 7. Allow the repo's workflows to impersonate the SA ----------------------
log "Workload Identity binding"
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
WIF_PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL_ID}/attribute.repository/${GITHUB_REPO}"

gcloud iam service-accounts add-iam-policy-binding "${TF_SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="${WIF_PRINCIPAL}" \
  --quiet >/dev/null
sub "workloadIdentityUser binding ensured for ${GITHUB_REPO}"

# 8. Print the values to wire into GitHub Environments ---------------------
WIF_PROVIDER_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL_ID}/providers/${WIF_PROVIDER_ID}"

cat <<EOF

==> ${ENV_NAME} (${PROJECT_ID}) bootstrap complete.

Configure GitHub Environment "${ENV_NAME}" with these two variables (the rest
are derived in Terraform / infra/backends/${ENV_NAME}.config):

  WIF_PROVIDER  = ${WIF_PROVIDER_RESOURCE}
  TF_SA         = ${TF_SA_EMAIL}

For reference / debugging:
  project_id   = ${PROJECT_ID}      (from local.project_id in infra/main.tf)
  state bucket = ${TF_STATE_BUCKET} (from infra/backends/${ENV_NAME}.config)

EOF
