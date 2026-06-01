"""The non-prod table TTL: models/seeds get a 24h BigQuery expiry in dev/test, none in prod.

Verified by parsing the project per target and reading the resolved `hours_to_expiration` off the
manifest — offline (fake project IDs via `cleaned_environment`), no warehouse needed.
"""

# Standard Library
import json
import os
import shlex
import subprocess

# Third Party
import pytest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # dbt-jaffleshop


@pytest.mark.parametrize(
    "target,expected",
    [("dev", 24), ("test", 24), ("prod", None)],
    ids=["dev", "test", "prod"],
)
def test_hours_to_expiration_is_24h_in_nonprod_and_none_in_prod(target, expected, cleaned_environment, tmp_path):
    env = cleaned_environment
    env["DBT_GIT_BRANCH"] = "ttl-test"  # a slice is mandatory in non-prod (generate_schema_name)
    env["DBT_PROFILES_DIR"] = PROJECT_DIR  # force it — an inherited stray value (repo root) breaks profile lookup

    result = subprocess.run(
        shlex.split(f"uv run dbt parse --target {target} --target-path {tmp_path}"),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    config = manifest["nodes"]["model.jaffle_shop.orders"]["config"]
    assert config["hours_to_expiration"] == expected
