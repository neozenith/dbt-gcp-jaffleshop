# Standard Library
import os
import shlex
import subprocess

# Third Party
import pytest

DEPLOYMENT_ENV_VARS = ["DBT_CLOUD_PR_ID", "DBT_CLOUD_RUN_ID", "DBT_PR_ID", "DBT_RUN_ID"]
DEVELOPMENT_ENV_VARS = ["DBT_CLOUD_GIT_BRANCH", "DBT_GIT_BRANCH", "GIT_BRANCH"]
ENV_TYPE_VARS = ["DBT_ENV_TYPE"]
ALL_ENV_VARS = DEPLOYMENT_ENV_VARS + DEVELOPMENT_ENV_VARS + ENV_TYPE_VARS


@pytest.fixture(scope="session")  # Reuse for the entire test session
def dependencies():
    subprocess.run(shlex.split("uv run dbt deps"), capture_output=True)


@pytest.fixture(scope="function")  # Per-test isolation
def cleaned_environment():
    """Copy of os.environ with all slice/env-type variables removed so each test starts from a known state."""
    env = os.environ.copy()
    for env_var_unset_key in ALL_ENV_VARS:
        if env_var_unset_key in env:
            del env[env_var_unset_key]
    # profiles.yml still needs these to render — give them fake values so dbt parse/compile can resolve.
    env.setdefault("DBT_BQ_PROJECT_DEV", "fake-gcp-project-dev")
    env.setdefault("DBT_BQ_PROJECT_TEST", "fake-gcp-project-test")
    env.setdefault("DBT_BQ_PROJECT_PROD", "fake-gcp-project-prod")
    env.setdefault("DBT_PROFILES_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return env
