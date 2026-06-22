"""Shared Terraform command construction + invocation.

The single place that knows how to build `terraform init`/`plan`/... command lines
and run them with `cwd=infra_root` + `-chdir=stacks/<stack>`. Both the
passthrough CLI (:mod:`tfs.commands.terraform`) and the diagram renderer
(:mod:`tfs.diagrams`) drive Terraform through here, so a flag added to `tfs plan`
cannot silently diverge from the plan the diagram is built on (inventory finding
D1). The only diagram-specific knobs are exposed as keyword args (`lock`, `out`).

Pure string builders are unit-tested; `run` is the thin subprocess seam.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def tfvars_flag(stack_path: Path, environment: str) -> str:
    """`-var-file=<env>.tfvars` when that file exists in the stack, else ""."""
    return f"-var-file={environment}.tfvars" if (stack_path / f"{environment}.tfvars").exists() else ""


def chdir_for(stack_name: str) -> str:
    return f"stacks/{stack_name}"


def init_cmd(stack_name: str, environment: str) -> str:
    chdir = chdir_for(stack_name)
    return f"terraform -chdir={chdir} init -backend-config=./backends/{environment}.config -reconfigure"


def plan_cmd(
    stack_name: str,
    environment: str,
    var_file: str,
    *,
    lock: bool = True,
    out: str = "",
) -> str:
    """`terraform plan` for a stack/env. `lock=False` + `out=` are the diagram
    renderer's only divergence (a throwaway, read-only plan saved for `show -json`)."""
    chdir = chdir_for(stack_name)
    parts = [f"terraform -chdir={chdir} plan -no-color -input=false"]
    if not lock:
        parts.append("-lock=false")
    if out:
        parts.append(f"-out={out}")
    parts.append(f"-var environment={environment}")
    if var_file:
        parts.append(var_file)
    return " ".join(parts)


def apply_cmd(stack_name: str, environment: str, var_file: str) -> str:
    chdir = chdir_for(stack_name)
    parts = [f"terraform -chdir={chdir} apply -no-color -input=false", f"-var environment={environment}"]
    if var_file:
        parts.append(var_file)
    parts.append("-auto-approve")
    return " ".join(parts)


def show_json_cmd(stack_name: str, plan_file: str) -> str:
    return f"terraform -chdir={chdir_for(stack_name)} show -json {plan_file}"


def run(cmd: str, infra_root: Path, *, capture: bool = False) -> subprocess.CompletedProcess[str]:  # pragma: no cover
    """Run a terraform command line with cwd=infra_root (so -chdir paths resolve). The
    subprocess IO seam — exercised by live terraform runs, not unit tests."""
    log.info("Running:\n\n%s\n", cmd)
    return subprocess.run(shlex.split(cmd), text=True, cwd=infra_root, check=True, capture_output=capture)
