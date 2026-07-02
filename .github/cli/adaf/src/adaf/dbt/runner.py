"""Centralised dbt subprocess helpers shared by the gates, the `ls` resolver, the viewer, and the
defer builder.

The CLI shells out to `dbt` rather than importing it. ``run_dbt`` is the single place every
invocation goes through — one home for the command shape, env, capture, and fail-loud error
formatting (`dbt ls`, `dbt parse`, `dbt deps` all route here, including the worktree-targeted parse
the defer builder needs via `--project-dir` / `--target-path` / a scrubbed env).
"""

# Standard Library
import os
import subprocess
from pathlib import Path

# Local
from adaf import config


def run_dbt(args: list[str], *, cwd: Path | None = None, extra_env: dict[str, str] | None = None) -> str:
    """Run ``dbt <args>``; fail loud on a non-zero exit (tail of output in the error); return stdout.

    The single dbt entry point for the whole CLI — ``ls.py`` (which needs the stdout) and the
    parse/deps helpers below all delegate here, so the subprocess + error shape lives in one place.
    """
    cwd = cwd or config.project_root()
    env = {**os.environ, **(extra_env or {})}
    proc = subprocess.run(["dbt", *args], cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-30:])
        raise RuntimeError(f"`dbt {' '.join(args)}` failed (exit {proc.returncode}):\n{tail}")
    return proc.stdout


def dbt_parse(
    cwd: Path | None = None,
    *,
    project_dir: Path | None = None,
    profiles_dir: Path | None = None,
    target: str | None = None,
    target_path: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> None:
    """Run ``dbt parse``. Bare call refreshes the current project's ``target/manifest.json``;
    the optional flags target another project tree (the defer worktree) into a chosen path.

    ``target`` selects the dbt target (``--target dev``/``test``); it bakes target-specific schema
    names into the manifest, so a state:modified comparison must use the same target on both sides.
    """
    args = ["parse"]
    if project_dir is not None:
        args += ["--project-dir", str(project_dir)]
    if profiles_dir is not None:
        args += ["--profiles-dir", str(profiles_dir)]
    if target is not None:
        args += ["--target", target]
    if target_path is not None:
        args += ["--target-path", str(target_path)]
    run_dbt(args, cwd=cwd, extra_env=extra_env)


def dbt_deps(*, project_dir: Path | None = None, cwd: Path | None = None) -> None:
    """Run ``dbt deps`` to install a project's packages (its own packages.yml/lock)."""
    args = ["deps"]
    if project_dir is not None:
        args += ["--project-dir", str(project_dir)]
    run_dbt(args, cwd=cwd)
