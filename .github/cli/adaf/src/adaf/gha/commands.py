"""`adaf gha create|update` — generate / refresh per-data-product workflow entrypoints.

Each data product gets its OWN thin workflow file (`adaf-<product>.yml`) — a path-filtered trigger that
`uses:` the shared reusable workflow (`adaf-reusable.yml`, the parallel job graph, deployed by `gha
init`). The reference skeleton is the CLI-owned `adaf/gha/assets/workflow-template.yml` (shipped as
package data); we round-trip it with ruamel (preserving comments + structure) and swap only the
product-specific tokens: the workflow ``name``, the ``jobs.adaf.with.selector`` input, and the
``on.pull_request.paths`` trigger. `create` also deploys the reusable workflow if it's absent.

The trigger ``paths`` are **derived from the selector itself**: `dbt ls --selector <product>` yields the
product's model files, which :mod:`adaf.gha.globber` collapses into globs (``--paths`` mode). Both
commands print the collapse working-out and a false-positive audit (files the globs also match beyond
the canonical strict list) so a human can judge the trade-off.

* ``create`` clones the template for a product (or every product with ``--all``).
* ``update`` re-derives ONLY the ``paths`` block of an existing workflow (e.g. after adding a model),
  leaving every other hand-edit intact.
"""

# Standard Library
import argparse
import logging
import sys
from pathlib import Path

# Third Party
from ruamel.yaml import YAML

# Local
from adaf import config, report
from adaf.dbt.ls import ls_model_paths
from adaf.dbt.manifest_view import ManifestView
from adaf.dbt.selectors import selector_names
from adaf.gha import actions, globber

log = logging.getLogger(__name__)


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    return y


def _on_key(data: object) -> object:
    # YAML 1.1 parses a bare `on:` key as boolean True; ruamel's 1.2 default keeps the string "on".
    return "on" if "on" in data else True  # type: ignore[operator]


def _targets(args: argparse.Namespace, names: list[str]) -> list[str]:
    """Resolve which products to act on: every named selector (``--all``) or the one positional."""
    if getattr(args, "all_products", False):
        return names
    if args.product_name:
        if args.product_name not in names:
            raise RuntimeError(
                f"unknown data product '{args.product_name}'. Define it in {args.selectors} first.\n"
                f"Available: {', '.join(sorted(names)) or '(none)'}"
            )
        return [args.product_name]
    raise RuntimeError("name a PRODUCT or pass --all")


def _discover(product: str, *, macros: bool) -> set[str]:
    """The canonical file set for a selector: its model ``.sql`` files (via ``dbt ls``), plus the
    repo macros those models depend on when ``macros`` is set (read from the manifest)."""
    root = config.project_root()
    discovered = ls_model_paths(product, cwd=root)
    if macros:
        manifest = config.under_root(config.DEFAULT_MANIFEST)
        assert manifest is not None
        view = ManifestView.load(manifest)
        models = view.of_type("model")
        ids = {uid for uid, rec in models.items() if str(rec.raw.get("original_file_path") or "") in discovered}
        discovered = discovered | view.dependent_macro_files(ids)
    return discovered


def _derive_paths(product: str, mode: str, *, macros: bool, color: bool = False) -> tuple[list[str], str]:
    """Discover the selector's files, collapse to trigger globs, audit, render.

    Returns ``(paths, working_out)`` where ``paths`` is the glob list (plus ``dbt_project.yml``) ready
    to drop into ``on.pull_request.paths``, and ``working_out`` is the human-readable derivation."""
    discovered = _discover(product, macros=macros)
    globs = globber.discover_to_globs(discovered, mode) + ["dbt_project.yml"]
    universe = globber.universe_sql(config.project_root(), with_macros=macros)
    fps = globber.false_positives(globs, universe, canonical=discovered)
    return globs, globber.render_working_out(product, mode, discovered, globs, fps, color=color)


def cmd_create(args: argparse.Namespace) -> int:
    color = report.should_colorize(args.color, sys.stdout)
    names = selector_names(args.selectors)
    template: Path = args.template
    if not template.exists():
        raise FileNotFoundError(f"workflow template not found at '{template}'")

    # The per-product callers `uses:` the reusable workflow — make sure it's present (deploy if missing;
    # --force re-syncs it). So `gha create <product>` on a fresh repo yields a working caller + reusable.
    actions.deploy_workflows(args.workflows_dir, force=args.force, color=color)

    for product in _targets(args, names):
        out_path: Path = args.workflows_dir / f"adaf-{product}.yml"
        if out_path.exists() and not args.force:
            # `--all` is a bulk template pass: skip ones that already exist (don't clobber hand-edits)
            # and point at `update` for refreshing their paths. A single create still fails loud.
            if args.all_products:
                report.render_headline(
                    f"skipped {out_path} (exists) — use `adaf gha update {product}` to refresh its paths",
                    color=color,
                    severity="warn",
                )
                continue
            raise RuntimeError(f"{out_path} already exists — pass --force to overwrite, or `adaf gha update {product}`")

        yaml = _yaml()
        data = yaml.load(template.read_text(encoding="utf-8"))
        on_key = _on_key(data)

        globs, working = _derive_paths(product, args.paths, macros=args.macros, color=color)
        data["name"] = f"adaf - {product}"
        data[on_key]["pull_request"]["paths"] = globs
        # The template is a thin caller: the selector is the reusable workflow's `with.selector` input
        # (the job graph itself lives in adaf-reusable.yml, deployed by `gha init`). The caller job name
        # `adaf / <product>` prefixes every reusable-workflow job, so the run reads as
        # "adaf / <product> / <job>" (the reusable's jobs carry bare names: setup, sqlfluff, …).
        data["jobs"]["adaf"]["name"] = f"adaf / {product}"
        data["jobs"]["adaf"]["with"]["selector"] = product

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            yaml.dump(data, fh)

        log.info("gha: created %s from %s (selector: %s)", out_path, template, product)
        report.render_headline(f"created {out_path}", color=color, severity="ok")
        print(working, file=sys.stderr)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    color = report.should_colorize(args.color, sys.stdout)
    names = selector_names(args.selectors)
    for product in _targets(args, names):
        out_path: Path = args.workflows_dir / f"adaf-{product}.yml"
        if not out_path.exists():
            raise RuntimeError(f"{out_path} does not exist — run `adaf gha create {product}` first")

        yaml = _yaml()
        data = yaml.load(out_path.read_text(encoding="utf-8"))

        globs, working = _derive_paths(product, args.paths, macros=args.macros, color=color)
        data[_on_key(data)]["pull_request"]["paths"] = globs  # ONLY the trigger paths; rest untouched

        with out_path.open("w", encoding="utf-8") as fh:
            yaml.dump(data, fh)

        log.info("gha: updated paths in %s (selector: %s)", out_path, product)
        report.render_headline(f"updated {out_path}", color=color, severity="ok")
        print(working, file=sys.stderr)
    return 0


def cmd_analyse(args: argparse.Namespace) -> int:
    """Tabulate, per selector and per --paths algorithm, the collapse cost: TRUE members, glob count,
    files matched, false positives, and the false-positive rate. Read-only (writes no workflow)."""
    names = selector_names(args.selectors)
    root = config.project_root()
    universe = globber.universe_sql(root, with_macros=args.macros)
    rows: list[list[str]] = []
    for product in _targets(args, names):
        discovered = _discover(product, macros=args.macros)
        true_n = len(discovered)
        for mode in globber.PATH_MODES:
            globs = globber.discover_to_globs(discovered, mode)
            fps = globber.false_positives(globs, universe, canonical=discovered)
            matched = true_n + len(fps)
            pct = (len(fps) / matched * 100) if matched else 0.0
            rows.append([product, mode, str(true_n), str(len(globs)), str(matched), str(len(fps)), f"{pct:.1f}%"])
    headers = ["selector", "--paths", "true", "globs", "matched", "false+", "fp%"]
    print(report.render_table(headers, rows, aligns=["l", "l", "r", "r", "r", "r", "r"]))
    return 0
