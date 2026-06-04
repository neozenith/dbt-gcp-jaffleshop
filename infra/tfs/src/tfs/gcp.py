"""GCP guardrail — proves the active gcloud credentials can see the target
project before any state-touching terraform call."""

import logging
import subprocess

from tfs.errors import TFStackGCPConfigurationError

log = logging.getLogger(__name__)


def check_project(environment: str) -> None:
    """The GCP analogue of the AWS account-id check — proves you're authenticated
    against dbt-<env>-jaffleshop. Hard failure (no silent skip): if gcloud can't
    describe the project, stop."""
    project_id = f"dbt-{environment}-jaffleshop"
    try:
        result = subprocess.run(
            ["gcloud", "projects", "describe", project_id, "--format=value(projectId)"],
            text=True,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as e:
        raise TFStackGCPConfigurationError("gcloud CLI not found on PATH — install the Google Cloud SDK") from e
    except subprocess.CalledProcessError as e:
        raise TFStackGCPConfigurationError(
            f"Cannot access project '{project_id}' with the active gcloud credentials.\n"
            f"  Authenticate first (e.g. `gcloud auth login` / ADC impersonation), then retry.\n"
            f"  gcloud said: {e.stderr.strip()}"
        ) from e
    log.debug("gcloud sees project: %s", result.stdout.strip())
