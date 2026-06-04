"""`tfs create <stack>` — scaffold stacks/<stack>/ (under the infra root) plus its
per-stack CI caller (under repo_root/.github/workflows/).

Templates are PACKAGE DATA: they ship inside the installed wheel and are read via
importlib.resources, never via a path relative to this file. That's what lets a
globally-installed `tfs` scaffold correctly. The OUTPUT, by contrast, is written
to the two discovered roots — which may sit at any relative depth from each other."""

import logging
import sys
from argparse import Namespace
from importlib.resources import files
from importlib.resources.abc import Traversable

import jinja2

from tfs.config import load_config
from tfs.roots import find_infra_root, find_repo_root

log = logging.getLogger(__name__)


def _templates() -> Traversable:
    """The packaged templates/ directory (works installed or from source)."""
    return files("tfs") / "templates"


def _render(template_text: str, **ctx: str) -> str:
    return jinja2.Template(template_text, undefined=jinja2.StrictUndefined).render(**ctx)


def cmd_create(args: Namespace) -> None:
    stack_name = args.stack
    infra_root = find_infra_root(override=args.infra_root)
    repo_root = find_repo_root(infra_root)
    templates = _templates()

    target_stack_path = infra_root / "stacks" / stack_name
    target_backends_path = target_stack_path / "backends"
    workflows_dir = repo_root / ".github" / "workflows"
    target_workflow = workflows_dir / f"terraform-cicd-stack-{stack_name}.yml"
    base_config = load_config(infra_root)

    if target_stack_path.exists():
        log.info("Stack %s already exists", stack_name)
        sys.exit(0)

    log.info("Creating stack: %s", stack_name)
    log.info("Creating folder structure in: stacks/%s", stack_name)
    target_backends_path.mkdir(parents=True)

    # Copy the static *.tf templates verbatim
    for tf_file in sorted((t for t in templates.iterdir() if t.name.endswith(".tf")), key=lambda t: t.name):
        target = target_stack_path / tf_file.name
        log.info("    Copying template %s --> stacks/%s/%s", tf_file.name, stack_name, tf_file.name)
        target.write_text(tf_file.read_text())

    # Template the per-env backend configs from config.yml
    log.info("Creating backend configs for: %s", stack_name)
    backend_template = (templates / "backends" / "base.config.j2").read_text()
    for environment, env_config in base_config["environments"].items():
        ctx = dict(env_config)
        ctx["environment"] = environment
        ctx["stack_name"] = stack_name
        rendered = _render(backend_template, **ctx)
        out = target_backends_path / f"{environment}.config"
        log.info("    Writing stacks/%s/backends/%s.config", stack_name, environment)
        out.write_text(rendered)

    # Template the stack README
    log.info("Creating README.md for: %s", stack_name)
    readme = _render((templates / "README.md.j2").read_text(), stack_name=stack_name)
    (target_stack_path / "README.md").write_text(readme)

    # Template the per-stack GHA workflow at repo_root/.github/workflows/ — the
    # template lives at templates/workflows/ (no dot-dir) and maps to .github/ here.
    log.info("Creating GHA workflow for: %s", stack_name)
    workflow_template = (templates / "workflows" / "terraform-cicd-stack-STACKNAME.yml.j2").read_text()
    workflow = _render(workflow_template, stack_name=stack_name)
    workflows_dir.mkdir(parents=True, exist_ok=True)
    target_workflow.write_text(workflow)
    log.info("    Writing %s", target_workflow.relative_to(repo_root))

    log.info("Stack %s created successfully ✅", stack_name)
