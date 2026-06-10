"""The Elementary dbt package is installed and its models resolve into the project graph.

Parses offline (fake project IDs) and inspects the manifest — proving `dbt deps` installed
Elementary and the dbt_project.yml config (+database / +schema) lets its models compile under
this project's custom generate_database_name/schema_name macros.

Parsed against the `prod` target on purpose: Elementary is gated PROD-only in dbt_project.yml
(`+enabled: "{{ env_var('DBT_ENV_TYPE', target.name) | upper == 'PROD' }}"`). Under any non-prod
target dbt parks those nodes in `manifest["disabled"]`, so a `--target dev` parse would resolve
zero elementary models even though the package is correctly installed. `data_environment()`
defaults DBT_ENV_TYPE to target.name, so `--target prod` enables them without extra env wiring
and skips the non-prod slice requirement.
"""

# Standard Library
import json
import os
import shlex
import subprocess

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # dbt-jaffleshop


def test_elementary_models_resolve_into_the_graph(cleaned_environment, tmp_path):
    env = cleaned_environment
    env["DBT_PROFILES_DIR"] = PROJECT_DIR  # force — an inherited stray value breaks profile lookup

    # --target prod so DBT_ENV_TYPE resolves to PROD and Elementary's PROD-only models are enabled
    # (see module docstring). Prod naming needs no slice, so DBT_GIT_BRANCH is intentionally unset.
    result = subprocess.run(
        shlex.split(f"uv run dbt parse --target prod --target-path {tmp_path}"),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    elementary_models = [
        node
        for node in manifest["nodes"].values()
        if node.get("package_name") == "elementary" and node["resource_type"] == "model"
    ]
    assert elementary_models, "no elementary models in the graph — is the package installed/configured?"
    # All land in an `elementary` schema (the +schema config applied).
    assert all("elementary" in node["schema"].lower() for node in elementary_models)
