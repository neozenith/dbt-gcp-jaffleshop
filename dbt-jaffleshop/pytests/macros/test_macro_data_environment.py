# Standard Library
import shlex
import subprocess

# Third Party
import pytest


@pytest.mark.parametrize(
    "data_env,expectation",
    [
        # Valid cases
        ("DEV", "DEV"),
        ("TEST", "TEST"),
        ("test", "TEST"),
        ("PROD", "PROD"),
        ("prod", "PROD"),
        # Unset falls back to target.name. Default target is `dev` (per profiles.yml DBT_TARGET fallback).
        ("", "DEV"),
        (None, "DEV"),
        # Invalid cases
        ("INVALID", None),
    ],
)
def test_macro_data_environment(data_env, expectation, cleaned_environment):
    # Given
    logging_marker = "data_environment: DBT_ENV_TYPE: "
    error_logging_marker = "Error: Invalid DBT_ENV_TYPE value:"
    env = cleaned_environment
    env["DBT_CLOUD_GIT_BRANCH"] = "fake-git-branch-so-this-test-lets-other-macros-compile"
    # Conditionally set this value based on parametrised testing permutations
    if data_env:
        env["DBT_ENV_TYPE"] = data_env

    args_flags = "--args '{\"debug_logging\": true}'"  # Needed to emit to stdout for testing

    command = f"uv run dbt run-operation data_environment {args_flags}"

    # When
    output = subprocess.run(shlex.split(command), capture_output=True, text=True, env=env)
    assert logging_marker in output.stdout or error_logging_marker in output.stdout
    out_lines = output.stdout.split("\n")
    logging_lines = [line for line in out_lines if logging_marker in line]

    # Then
    if expectation:
        assert len(logging_lines) == 1
        assert logging_lines[0].split(logging_marker)[1] == expectation
    else:
        assert len(logging_lines) == 0
        error_lines = [line for line in out_lines if error_logging_marker in line]
        assert len(error_lines) == 1
