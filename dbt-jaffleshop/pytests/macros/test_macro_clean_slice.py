# Standard Library
import shlex
import subprocess

# Third Party
import pytest


@pytest.mark.parametrize("is_deployment", [True, False], ids=["deploy", "develop"])
@pytest.mark.parametrize(
    "env_var_name",
    ["DBT_CLOUD_GIT_BRANCH", "DBT_GIT_BRANCH", None],
    ids=["env_var_dbt_cloud", "env_var_dbt", "env_var_none"],
)
@pytest.mark.parametrize("vars_value", [True, False], ids=["project_vars", "no_project_vars"])
@pytest.mark.parametrize(
    "pr_env_var,run_env_var",
    [
        ("DBT_CLOUD_PR_ID", "DBT_CLOUD_RUN_ID"),
        ("DBT_PR_ID", "DBT_RUN_ID"),
    ],
    ids=["ci_envs_dbt_cloud", "ci_envs_dbt"],
)
def test_macro_clean_slice(
    # Parameters
    is_deployment,
    env_var_name,
    vars_value,
    pr_env_var,
    run_env_var,
    # Fixtures
    tmp_path,
    cleaned_environment,
):
    ########## Given

    branch_name = "feature/DPP-99-custom-naming-macros"
    clean_branch = "feature_DPP_99_custom_naming_macros"
    is_branch_defined = bool(vars_value or env_var_name)

    pr_id = "123"
    run_id = "789"
    expected_ci_slice = f"PR{pr_id}_RUN{run_id}"
    logging_marker = "Clean slice: "
    error_log_marker = "Error: Data Environment is non-PROD and no slice is defined"

    env = cleaned_environment

    # Conditionally set these values based on parametrised testing permutations
    if is_deployment:
        env[pr_env_var] = pr_id
        env[run_env_var] = run_id

    if env_var_name:
        env[env_var_name] = branch_name

    args_flags = "--args '{\"debug_logging\": true}'"
    vars_flags = f'--vars \'{{"git_branch": "{branch_name}"}}\'' if vars_value else ""

    command = f"uv run dbt run-operation clean_slice {args_flags} {vars_flags} --target-path {tmp_path}"

    ########## When
    output = subprocess.run(shlex.split(command), capture_output=True, text=True, env=env)

    ########## Then

    if not is_branch_defined and not is_deployment:
        # Unhappy path: no slice defined in non-PROD. Error originates from generate_schema_name.sql.
        assert output.returncode == 2
        assert error_log_marker in output.stdout

    else:
        # Happy path: something defines a slice.
        assert logging_marker in output.stdout
        out_lines = output.stdout.split("\n")
        logging_lines = [line for line in out_lines if logging_marker in line]
        assert len(logging_lines) == 1

        if is_branch_defined:
            assert logging_lines[0].split(logging_marker)[1] == clean_branch
        else:
            if is_deployment:
                assert logging_lines[0].split(logging_marker)[1] == expected_ci_slice
