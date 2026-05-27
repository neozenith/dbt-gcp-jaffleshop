# Standard Library
import json
import shlex
import subprocess

# Third Party
import pytest


@pytest.mark.parametrize("is_deployment", [True, False], ids=["deploy", "develop"])
@pytest.mark.parametrize(
    "branch_env_var_name",
    ["DBT_CLOUD_GIT_BRANCH", "DBT_GIT_BRANCH", None],
    ids=["gitbranch_env_var_dbt_cloud", "gitbranch_env_var_dbt", "gitbranch_env_var_none"],
)
@pytest.mark.parametrize(
    "gitbranch_vars_value", [True, False], ids=["gitbranch_project_vars", "gitbranch_no_project_vars"]
)
@pytest.mark.parametrize(
    "pr_env_var,run_env_var",
    [
        ("DBT_CLOUD_PR_ID", "DBT_CLOUD_RUN_ID"),
        ("DBT_PR_ID", "DBT_RUN_ID"),
    ],
    ids=["ci_envs_dbt_cloud", "ci_envs_dbt"],
)
@pytest.mark.parametrize(
    "data_env,expected_data_env",
    [
        ("DEV", "DEV"),
        ("TEST", "TEST"),
        ("test", "TEST"),
        ("PROD", "PROD"),
        ("prod", "PROD"),
        ("", "DEV"),
        (None, "DEV"),
        ("INVALID", None),
    ],
)
def test_macro_generate_schema_name(
    # Parameters
    data_env,
    expected_data_env,
    pr_env_var,
    run_env_var,
    branch_env_var_name,
    gitbranch_vars_value,
    is_deployment,
    # Fixtures
    tmp_path,
    cleaned_environment,
):
    ########## Given
    branch_name = "feature/DPP-99-custom-naming-macros"
    clean_branch = "feature_DPP_99_custom_naming_macros".upper()
    is_branch_defined = bool(gitbranch_vars_value or branch_env_var_name)
    cleaned_slice = f"{clean_branch}__" if expected_data_env and expected_data_env != "PROD" else ""
    pr_id = "123"
    run_id = "789"
    expected_ci_slice = (
        f"PR{pr_id}_RUN{run_id}__" if expected_data_env and expected_data_env != "PROD" else ""
    )

    env = cleaned_environment

    if is_deployment:
        env[pr_env_var] = pr_id
        env[run_env_var] = run_id

    if branch_env_var_name:
        env[branch_env_var_name] = branch_name

    if data_env:
        env["DBT_ENV_TYPE"] = data_env

    vars_flags = f'--vars \'{{"git_branch": "{branch_name}"}}\'' if gitbranch_vars_value else ""

    command = f"uv run dbt parse --no-partial-parse --target-path {tmp_path} {vars_flags}"

    ########## When
    output = subprocess.run(shlex.split(command), capture_output=True, env=env)

    ########## Then

    if expected_data_env is None:
        assert output.returncode == 2, (
            f"Parsing succeeded when it should have thrown an Invalid DBT_ENV_TYPE error. "
            f"dbt output: {output.stdout.decode('utf-8')}"
        )
        assert "Error: Invalid DBT_ENV_TYPE value:" in output.stdout.decode("utf-8")

    elif not is_branch_defined and not is_deployment and expected_data_env != "PROD":
        assert output.returncode == 2, (
            f"Parsing succeeded when it should have thrown an Invalid Slice error: "
            f"{output.stdout.decode('utf-8')}"
        )
        assert "Error: Data Environment is non-PROD and no slice is defined for " in output.stdout.decode("utf-8")

    else:
        # Manifest should get generated; verify a model's resolved schema + database.
        assert output.returncode == 0, f"dbt-parse error: {output.stdout.decode('utf-8')}"
        manifest = json.loads((tmp_path / "manifest.json").read_text())

        models = [
            model_values for model_key, model_values in manifest["nodes"].items() if model_key.startswith("model.")
        ]
        assert models != []
        model_details = models[0]
        model_config = model_details["config"]
        model_config_database = model_config["database"].lower()
        model_config_schema = model_config["schema"].upper()

        # Schema assertion: slice prefix in non-PROD, plain custom in PROD.
        if is_branch_defined:
            assert model_details["schema"] == f"{cleaned_slice}{model_config_schema}"
        elif is_deployment:
            assert model_details["schema"] == f"{expected_ci_slice}{model_config_schema}"

        # Database assertion: {custom}-{env} in non-PROD, plain {custom} in PROD.
        if expected_data_env == "PROD":
            assert model_details["database"] == model_config_database
        else:
            assert model_details["database"] == f"{model_config_database}-{expected_data_env.lower()}"
