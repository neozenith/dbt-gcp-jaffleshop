#!/usr/bin/env bash
# Run bootstrap_project.sh for every project listed in config.sh.
#
# Assumes you are already authenticated (e.g. CLOUDSDK_* environment variables
# are set, or `gcloud auth login` has been completed). Authentication is NOT
# performed by this script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "${SCRIPT_DIR}/config.sh"

for pair in "${PROJECT_PAIRS[@]}"; do
  IFS=':' read -r project env <<<"${pair}"
  "${SCRIPT_DIR}/bootstrap_project.sh" "${project}" "${env}"
done

cat <<'EOF'

==> All projects bootstrapped.

Next step: configure GitHub Environments with the variables printed above.
Either set them by hand in the GitHub UI, or run:

    ./infra/bootstrap/bootstrap_github.sh

EOF
