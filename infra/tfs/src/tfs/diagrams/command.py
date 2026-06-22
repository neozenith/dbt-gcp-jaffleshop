"""`tfs diagram <stack> <env>` entry point.

Orchestrates: throwaway plan -> plan JSON -> graph -> layout -> draw.io-compatible
SVG (+ PNG). Drives Terraform through the shared :mod:`tfs._terraform` driver, so
the diagram's plan can't diverge from `tfs plan`. With ``--publish`` it pushes the
result to a PR (CI only).
"""

from __future__ import annotations

import json
import logging
from argparse import Namespace
from pathlib import Path

from tfs import _terraform as tf
from tfs.config import list_stacks
from tfs.diagrams import layout as layout_mod
from tfs.diagrams import plan_model, readme as readme_mod, svg_render
from tfs.diagrams.plan_model import Graph
from tfs.errors import TFStackCLIInputError
from tfs.gcp import check_project
from tfs.roots import find_infra_root

log = logging.getLogger(__name__)

_PLAN_FILE = "tmp/diagram.tfplan"

# The canonical environment whose topology represents the stack's architecture in
# its README — prod is the most complete (it includes the IAP-env-only resources).
_README_ENV = "prod"


def _load_plan_json(stack: str, env: str, infra_root: Path) -> dict:  # pragma: no cover - terraform subprocess IO
    """init + (throwaway, unlocked) plan -> the plan JSON document."""
    stack_path = infra_root / "stacks" / stack
    (stack_path / "tmp").mkdir(parents=True, exist_ok=True)
    var_file = tf.tfvars_flag(stack_path, env)

    log.info("Planning %s/%s for diagram …", stack, env)
    tf.run(tf.init_cmd(stack, env), infra_root, capture=True)
    tf.run(tf.plan_cmd(stack, env, var_file, lock=False, out=_PLAN_FILE), infra_root, capture=True)
    out = tf.run(tf.show_json_cmd(stack, _PLAN_FILE), infra_root, capture=True)
    return json.loads(out.stdout)


def _render_svg(stack: str, env: str, mode: str, iam: str, infra_root: Path) -> tuple[Graph, str]:  # pragma: no cover - terraform subprocess IO
    """plan -> graph -> layout -> draw.io-compatible SVG string. The shared render core."""
    doc = _load_plan_json(stack, env, infra_root)
    graph = plan_model.build_graph(doc, mode=mode, iam=iam)
    layout = layout_mod.compute(graph)
    title = f"{stack} | {env} | {mode}"
    return graph, svg_render.render(graph, layout, title=title, mode=mode)


def cmd_diagram(args: Namespace) -> None:  # pragma: no cover - terraform/cairo IO orchestration
    infra_root = find_infra_root(override=args.infra_root)
    if args.stack not in list_stacks(infra_root):
        raise TFStackCLIInputError(f"Stack '{args.stack}' does not exist. One of {list_stacks(infra_root)}")

    if getattr(args, "readme", False):
        _diagram_readme(args, infra_root)
        return

    if args.env is None:
        raise TFStackCLIInputError("env is required (one of dev/test/prod) unless --readme is given")
    check_project(args.env)

    graph, svg = _render_svg(args.stack, args.env, args.mode, args.iam, infra_root)

    out_dir = Path(args.out_dir) if getattr(args, "out_dir", None) else infra_root / "diagrams"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"{args.stack}-{args.env}-{args.mode}"
    svg_path = base.with_suffix(".svg")
    png_path = base.with_suffix(".png")
    svg_path.write_text(svg, encoding="utf-8")

    # Rasterize to PNG. Imported lazily so a missing system cairo only bites the
    # PNG step (and crashes loudly there), never `tfs diagram --help` etc.
    from tfs.diagrams import raster

    raster.svg_to_png(svg_path, png_path)
    log.info("✅ wrote %s (+ .png) — %d resources", svg_path.name, len(graph.nodes))


def _diagram_readme(args: Namespace, infra_root: Path) -> None:  # pragma: no cover - terraform/file IO orchestration
    """Render the canonical (prod, state) architecture SVG into the stack dir and
    upsert the README diagram region. With ``--check``, render+compare instead of
    write, failing loudly when the committed diagram is stale (a fitness function).

    SVG-only: no PNG step, so this needs no system cairo and runs on a dev laptop.
    """
    env = args.env or _README_ENV
    if args.mode != "state":
        raise TFStackCLIInputError("--readme renders the architecture; it requires --mode state (the default).")
    check_project(env)

    _, svg = _render_svg(args.stack, env, "state", args.iam, infra_root)
    fresh = svg.encode("utf-8")
    stack_dir = infra_root / "stacks" / args.stack
    svg_path = stack_dir / readme_mod.SVG_FILENAME
    readme_path = stack_dir / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    block = readme_mod.embed_block(args.stack, env)

    if getattr(args, "check", False):
        committed = svg_path.read_bytes() if svg_path.exists() else None
        reasons = readme_mod.staleness(readme_text, block, committed, fresh)
        if reasons:
            raise TFStackCLIInputError(
                f"{args.stack} README diagram is stale ({'; '.join(reasons)}). "
                f"Run `tfs diagram {args.stack} --readme` and commit the result."
            )
        log.info("✅ %s README architecture diagram is up to date", args.stack)
        return

    svg_path.write_text(svg, encoding="utf-8")
    readme_path.write_text(readme_mod.upsert_region(readme_text, block), encoding="utf-8")
    log.info("✅ embedded architecture diagram (%s) in %s", env, readme_path)


def cmd_diagram_comment(args: Namespace) -> None:  # pragma: no cover - gh subprocess IO
    """Post/update the sticky PR comment linking to the uploaded diagram artifact.

    No terraform/render/cloud access — the image files are produced by `tfs diagram`
    and uploaded by GitHub's actions/upload-artifact; this only links that artifact
    URL into the PR comment. CI-only (reads GH context from the environment)."""
    from tfs.diagrams import publish

    publish.post_comment(args.stack, args.env, args.mode, args.png_artifact_id, args.svg_artifact_id)
