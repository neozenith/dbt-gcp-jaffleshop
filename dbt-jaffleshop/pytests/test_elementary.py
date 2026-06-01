"""The Elementary dbt package is installed and its models resolve into the project graph.

Parses offline (fake project IDs) and inspects the manifest — proving `dbt deps` installed
Elementary and the dbt_project.yml config (+database / +schema) lets its models compile under
this project's custom generate_database_name/schema_name macros.
"""

# Standard Library
import json
import os
import shlex
import subprocess

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # dbt-jaffleshop


def test_elementary_models_resolve_into_the_graph(cleaned_environment, tmp_path):
    env = cleaned_environment
    env["DBT_GIT_BRANCH"] = "elementary-test"  # slice required in non-prod
    env["DBT_PROFILES_DIR"] = PROJECT_DIR  # force — an inherited stray value breaks profile lookup

    result = subprocess.run(
        shlex.split(f"uv run dbt parse --target dev --target-path {tmp_path}"),
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
