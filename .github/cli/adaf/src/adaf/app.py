"""adaf CLI wiring — build_parser() + main() only. No business logic lives here;
handlers come from adaf.commands.*.

Follows the project argparse convention (.claude/rules/python/cli.md): a ``_help``
closure as each parser's default func so an incomplete path prints that group's
help instead of erroring; leaf subcommands override it via ``set_defaults(func=...)``;
``main()`` dispatches ``args.func(args)`` unconditionally and exits with its return code.

Command tree::

    adaf
      rules                       inspect/validate the catalogue (the single source of truth)
        list / show / validate
      check                       deterministic gates over the SELECTED models (changed-only by default)
        deprecations [--fix]      dbt-autofix dry-run / apply over folders of selected models
        lint         [--fix]      SQLFluff full ruleset
        format       [--fix]      SQLFluff formatter subset
        docs                      model description coverage (from manifest)
        doc-columns               resolved column description coverage (needs catalog.json)
        tests                     test coverage (from manifest)
        system-boundaries         fail when an inbound/outbound data-product boundary node has no tests
        all                       run every check; non-zero if any fail
      products                    data-product (named-selector) analysis — read-only
        boundaries / generate / serve

The ``check``/``products`` groups need a dbt project; ``rules`` does not — so the
project root is discovered lazily in main() only for the groups that touch it.
"""

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from adaf import config
from adaf.dbt import selection
from adaf.dbt.scope import UNBOUNDED
from adaf.utils import style
from adaf.commands import checks, coverage, dataproducts, deprecations, taxonomy
from adaf.commands import report as report_cmd
from adaf.commands import review as review_cmd
from adaf.commands import rules as rules_cmd
from adaf.commands import sqlfluff as sqlfluff_cmd
from adaf.commands.defer import cmd_defer_diff, cmd_defer_state
from adaf.gha import cmd_analyse as gha_analyse
from adaf.gha import cmd_create as gha_create
from adaf.gha import cmd_update as gha_update
from adaf.gha.globber import DEFAULT_PATH_MODE, PATH_MODES
from adaf.utils.formatting import render_from_args
from adaf.utils.logging_setup import configure_logging

log = logging.getLogger(__name__)

_ROLES = ("entity", "dimension", "measure", "time", "model")
_DETECTIONS = ("deterministic", "hybrid", "llm")
# groups/commands that operate on a dbt project (lazy root discovery + profiles pinning in main())
_NEEDS_PROJECT = ("check", "products", "review", "report", "defer-diff", "defer-state", "list", "ls", "gha")


def _help(p: argparse.ArgumentParser):
    """Return a handler that prints help for parser p (used as the default func)."""

    def _print_help(_: argparse.Namespace) -> int:
        p.print_help()
        return 0

    return _print_help


# ─── shared flag groups (ported from cicd_cli) ───────────────────────────────


def _add_selection(p: argparse.ArgumentParser) -> None:
    """Scope (changed/all) + dbt select/exclude — shared by every file-scoped check."""
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--changed-only", action="store_true", help="Only models changed vs --base-ref (default)")
    scope.add_argument("--all", action="store_true", dest="all_models", help="All models, not only changed ones")
    p.add_argument(
        "--base-ref",
        default=config.DEFAULT_BASE_REF,
        help="Git ref the changed-only scope diffs against (default: %(default)s)",
    )
    p.add_argument(
        "--select",
        action="append",
        metavar="SELECTOR",
        help="dbt selector to narrow the scope (repeatable; union, like dbt)",
    )
    p.add_argument(
        "--exclude",
        action="append",
        metavar="SELECTOR",
        help="dbt exclusion selector (repeatable; matches dbt --exclude)",
    )
    _add_output(p)


def _add_output(p: argparse.ArgumentParser) -> None:
    """--json / --show-logs / --show-passes / --color — the renderer flags."""
    p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON to stdout (human log lines go to stderr)",
    )
    p.add_argument(
        "--show-logs",
        action="store_true",
        dest="show_logs",
        help="Print the raw underlying-tool transcript even on success",
    )
    p.add_argument(
        "--show-passes",
        action="store_true",
        dest="show_passes",
        help="Show passing results too (default: only failures)",
    )
    p.add_argument(
        "--color", choices=["auto", "always", "never"], default="auto", help="Colourise output (default: %(default)s)"
    )


def _add_fix(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--fix", action="store_true", help="Apply fixes instead of only checking (where the tool supports it)"
    )


def _add_manifest(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--manifest",
        type=Path,
        default=config.DEFAULT_MANIFEST,
        help="Path to dbt manifest.json (default: <project>/%(default)s)",
    )
    p.add_argument("--parse", action="store_true", help="Run `dbt parse` first to refresh the manifest before checking")


def _add_catalog(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--catalog",
        type=Path,
        default=config.DEFAULT_CATALOG,
        help="Path to dbt catalog.json — resolved warehouse columns (default: <project>/%(default)s)",
    )
    p.add_argument(
        "--docs-generate",
        action="store_true",
        dest="docs_generate",
        help="Run `dbt docs generate` first to refresh the manifest + catalog (needs a warehouse build)",
    )


def _add_dataproduct_scope(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--selectors",
        type=Path,
        default=config.DEFAULT_SELECTORS,
        help="Path to dbt's selectors.yml defining the data products (default: <project>/%(default)s)",
    )
    p.add_argument(
        "--product",
        action="append",
        metavar="NAME",
        help="Limit to this named data product (repeatable; default: all in selectors.yml)",
    )


def _add_sdag_output(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=config.DEFAULT_SDAG_OUTPUT,
        help="Directory for the generated viewer assets (default: <project>/%(default)s)",
    )


def _add_target(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--target",
        default=None,
        help="dbt --target (e.g. dev/test) for the live `dbt ls` (default: dbt's profile default)",
    )


def _add_defer_target(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--defer-target",
        dest="defer_target",
        default=None,
        help="dbt --target for the defer-target parse, when it differs from --target "
        "(e.g. --target dev --defer-target nonprod). Defaults to --target's value.",
    )


def _add_scope(p: argparse.ArgumentParser) -> None:
    """Product-scope flags shared by the workflow commands (list / defer-diff): changed/all +
    base-ref + a REQUIRED named --selector + optional defer + lineage-hop expansion + targets.

    Distinct from ``_add_selection`` (the catalogue ``check`` gates' changed/all + inline
    --select/--exclude) — here the scope is always bounded to ONE named data product."""
    scope_grp = p.add_mutually_exclusive_group()
    scope_grp.add_argument("--changed-only", action="store_true", help="Only models changed vs --base-ref (default)")
    scope_grp.add_argument("--all", action="store_true", dest="all_models", help="All in-scope models, not only changed")
    p.add_argument(
        "--base-ref",
        default=config.DEFAULT_BASE_REF,
        help="Git ref the changed-only scope diffs against (default: %(default)s)",
    )
    p.add_argument(
        "--selector",
        required=True,
        help="Named dbt selector (from selectors.yml) bounding the scope (REQUIRED — be explicit)",
    )
    p.add_argument(
        "--defer",
        action="store_true",
        help="Defer unchanged refs to a baseline manifest parsed from --defer-ref (built + cached in tmp/)",
    )
    p.add_argument(
        "--defer-ref",
        dest="defer_ref",
        default="main",
        metavar="REF",
        help="Git ref (branch/tag/sha) whose parsed manifest is the defer target (default: %(default)s)",
    )
    # Lineage expansion: nargs="?" so bare --upstream (const=UNBOUNDED ⇒ all hops) and --upstream N
    # (type=int ⇒ that many hops) both parse; absent ⇒ default None (no expansion).
    p.add_argument(
        "--upstream",
        nargs="?",
        type=int,
        const=UNBOUNDED,
        default=None,
        metavar="N",
        help="Grow the scope with N ancestor hops (bare --upstream = all ancestors; default: no expansion)",
    )
    p.add_argument(
        "--downstream",
        nargs="?",
        type=int,
        const=UNBOUNDED,
        default=None,
        metavar="N",
        help="Grow the scope with N descendant hops (bare --downstream = all descendants; default: no expansion)",
    )
    _add_target(p)
    _add_defer_target(p)


# ─── parser construction ─────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    # --debug / --project-dir shared by every (sub)parser so they work before OR after the
    # subcommand. default=SUPPRESS so an unset occurrence on a subparser never clobbers a value
    # parsed at the top level; main() normalises the possibly-absent attributes.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help="Verbose debug logging")
    common.add_argument(
        "--project-dir",
        dest="project_dir",
        default=argparse.SUPPRESS,
        help="Path to the dbt project (a dir with dbt_project.yml). Overrides $ADAF_PROJECT_DIR and walk-up discovery.",
    )

    parser = argparse.ArgumentParser(
        prog="adaf",
        description="Automated Data Assurance Framework — one CLI over the dbt testing-taxonomy catalogue.",
        parents=[common],
    )
    parser.set_defaults(func=_help(parser))
    sub = parser.add_subparsers(dest="command", required=False)

    _add_rules_group(sub, common)
    _add_check_group(sub, common)
    _add_products_group(sub, common)
    _add_review_group(sub, common)
    _add_report_group(sub, common)
    _add_defer_group(sub, common)
    _add_gha_group(sub, common)

    return parser


def _add_gha_common(p: argparse.ArgumentParser) -> None:
    """Args shared by ``gha create`` / ``update`` / ``analyse``: the product (or --all), selectors
    file, the path-collapse mode, macro inclusion, and the output workflows dir."""
    p.add_argument(
        "product_name",
        metavar="PRODUCT",
        nargs="?",
        help="Named selector / data product (must exist in selectors.yml). Omit with --all.",
    )
    p.add_argument(
        "--all",
        dest="all_products",
        action="store_true",
        help="Act on EVERY named selector in selectors.yml (template/refresh them all for review)",
    )
    p.add_argument(
        "--selectors",
        type=Path,
        default=config.DEFAULT_SELECTORS,
        help="selectors.yml defining the data products (default: <project>/%(default)s)",
    )
    p.add_argument(
        "--paths",
        choices=PATH_MODES,
        default=DEFAULT_PATH_MODE,
        help="How to collapse the selector's files into trigger globs: strict (every file) | leaf "
        "(<dir>/*.{sql,yml}) | recursive (wildcard varying path components). Default: %(default)s",
    )
    p.add_argument(
        "--macros",
        action="store_true",
        help="Also include the repo macros the selected models depend on (read from the manifest)",
    )
    p.add_argument(
        "--workflows-dir",
        type=Path,
        default=config.DEFAULT_WORKFLOWS_DIR,
        dest="workflows_dir",
        help="Directory holding the workflows (default: <project>/%(default)s)",
    )


def _add_gha_group(sub, common: argparse.ArgumentParser) -> None:
    """``adaf gha create|update|analyse`` — generate / refresh / analyse per-data-product workflows.

    Each data product (named selector) gets a thin ``adaf-<product>.yml`` whose ``on.pull_request.paths``
    trigger is DERIVED from the selector's membership (collapsed per --paths), so the workflow only fires
    when that product's files change."""
    gha_p = sub.add_parser("gha", parents=[common], help="Generate per-data-product GHA workflow entrypoints")
    gha_p.set_defaults(func=_help(gha_p))
    gha_sub = gha_p.add_subparsers(dest="gha_cmd", required=False)

    create = gha_sub.add_parser(
        "create",
        parents=[common],
        help="Create .github/workflows/adaf-<product>.yml from the template",
        description=(
            "Clone the CLI-owned workflow template into .github/workflows/adaf-<product>.yml, with the "
            "trigger `paths` DERIVED from `dbt ls --selector <product>` (collapsed per --paths). Prints the "
            "collapse working-out + false-positive audit. Refuses to overwrite without --force."
        ),
        epilog="Examples:\n  adaf gha create demand\n  adaf gha create --all --paths leaf",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_gha_common(create)
    create.add_argument(
        "--template",
        type=Path,
        default=config.DEFAULT_WORKFLOW_TEMPLATE,
        help="Workflow template to clone (default: the CLI-owned base template)",
    )
    create.add_argument("--force", action="store_true", help="Overwrite an existing adaf-<product>.yml")
    create.set_defaults(func=gha_create)

    update = gha_sub.add_parser(
        "update",
        parents=[common],
        help="Re-derive ONLY the trigger paths of an existing adaf-<product>.yml",
        description=(
            "Refresh the `on.pull_request.paths` of an existing workflow from the current selector "
            "membership (e.g. after adding a model), leaving every other hand-edit intact."
        ),
        epilog="Examples:\n  adaf gha update demand\n  adaf gha update --all",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_gha_common(update)
    update.set_defaults(func=gha_update)

    analyse = gha_sub.add_parser(
        "analyse",
        parents=[common],
        help="Tabulate selector size vs each --paths algorithm's false-positive rate",
        description=(
            "Read-only: for one selector (or --all), print a TUI table of how many files are TRUE members, "
            "how many each of the 3 path algorithms would match, and the false-positive count + rate per "
            "algorithm — so you can pick a --paths mode with eyes open."
        ),
        epilog="Examples:\n  adaf gha analyse demand\n  adaf gha analyse --all --macros",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_gha_common(analyse)
    analyse.set_defaults(func=gha_analyse)


def _add_defer_group(sub, common: argparse.ArgumentParser) -> None:
    """``adaf defer-diff`` + ``adaf defer-state`` — the dbt --defer / state workflow commands.

    Top-level (not under ``check``) because they are CI plumbing, not catalogue gates: ``defer-state``
    builds + caches a baseline manifest from a git ref and prints its --state dir; ``defer-diff``
    shows which models in a selector's scope would be BUILT vs DEFERRED against that baseline.
    """
    dd = sub.add_parser(
        "defer-diff",
        parents=[common],
        help="Show built vs deferred models under a selector (vs a --defer-ref baseline)",
        description=(
            "Show which models in scope would be BUILT (differ from the --defer-ref baseline) vs DEFERRED "
            "(resolved to it), with deepdiff explaining why each built model changed. --selector bounds the "
            "product, default reports only changed models, --all the whole product, --upstream / --downstream "
            "grow the scope along the lineage. --details adds a git-diff-style field-level diff per built model."
        ),
        epilog="Examples:\n  adaf defer-diff --selector demand --defer-ref main\n"
        "  adaf defer-diff --all --selector demand --upstream 1 --details",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_scope(dd)
    _add_manifest(dd)
    dd.add_argument(
        "--details",
        action="store_true",
        help="Under each BUILT model, show a colourised git-diff-style unified diff of the changed node facets",
    )
    dd.set_defaults(func=cmd_defer_diff)

    ds = sub.add_parser(
        "defer-state",
        parents=[common],
        help="Build (or reuse) the defer-target state for a ref and print its --state dir (for CI)",
        description=(
            "Check out a git worktree to build the defer-target manifest for a git ref and print its --state "
            "directory on stdout — the plumbing behind --defer, for CI to feed `dbt build --state`."
        ),
        epilog="Examples:\n  STATE=$(adaf defer-state --defer-ref main --target dev --defer-target nonprod)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ds.add_argument(
        "--defer-ref",
        dest="defer_ref",
        default="main",
        metavar="REF",
        help="Git ref whose parsed manifest is the defer-target baseline (default: %(default)s)",
    )
    ds.add_argument("--force", action="store_true", help="Rebuild even if a cached state dir exists for this sha")
    _add_target(ds)
    _add_defer_target(ds)
    ds.set_defaults(func=cmd_defer_state)


def _add_report_group(sub, common: argparse.ArgumentParser) -> None:
    """``adaf report`` — generate the per-model taxonomy review markdown (mechanically, no hand-authoring)."""
    rep = sub.add_parser(
        "report", parents=[common], help="Generate a per-model taxonomy-review markdown with full finding lineage"
    )
    _add_selection(rep)
    _add_manifest(rep)
    _add_catalog(rep)  # warehouse-resolved columns → richer deterministic verdicts
    rep.add_argument(
        "--review",
        type=Path,
        default=None,
        metavar="REVIEW_JSON",
        help="`adaf review --json` output to reconcile against (adds an LLM-vs-deterministic FP/FN column per model)",
    )
    rep.add_argument(
        "-o", "--output", type=Path, default=None, help="Write the markdown to this file (default: stdout)"
    )
    rep.set_defaults(func=report_cmd.cmd)


def _add_rules_group(sub, common: argparse.ArgumentParser) -> None:
    rules_p = sub.add_parser("rules", parents=[common], help="Inspect and validate the rule catalogue (the SSoT)")
    rules_p.set_defaults(func=_help(rules_p))
    rules_sub = rules_p.add_subparsers(dest="rules_cmd", required=False)

    p_list = rules_sub.add_parser("list", parents=[common], help="List catalogue rules (filterable)")
    p_list.add_argument("--role", choices=_ROLES, help="Filter to one role")
    p_list.add_argument("--detection", choices=_DETECTIONS, help="Filter to one detection mode")
    p_list.add_argument("--dama", metavar="DIMENSION", help="Filter to rules defending this DAMA-UK6 dimension")
    p_list.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON to stdout")
    p_list.set_defaults(func=rules_cmd.cmd_list)

    p_show = rules_sub.add_parser("show", parents=[common], help="Show one rule in full")
    p_show.add_argument("code", help="Rule code, e.g. MD-01")
    p_show.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON to stdout")
    p_show.set_defaults(func=rules_cmd.cmd_show)

    p_explain = rules_sub.add_parser(
        "explain", parents=[common], help="Show a rule AND the exact syntax to suppress it (false positives)"
    )
    p_explain.add_argument("code", help="Rule code, e.g. MD-02")
    p_explain.add_argument("--json", action="store_true", dest="as_json", help="Emit the rule JSON to stdout")
    p_explain.set_defaults(func=rules_cmd.cmd_explain)

    p_val = rules_sub.add_parser("validate", parents=[common], help="Validate catalog.json against its meta-schema")
    p_val.set_defaults(func=rules_cmd.cmd_validate)


def _add_check_group(sub, common: argparse.ArgumentParser) -> None:
    check = sub.add_parser("check", parents=[common], help="Deterministic gates over the selected models")
    check.set_defaults(func=_help(check))
    check_sub = check.add_subparsers(dest="check_cmd", required=False)

    dep = check_sub.add_parser("deprecations", parents=[common], help="dbt-autofix over folders of selected models")
    _add_selection(dep)
    _add_fix(dep)
    dep.set_defaults(func=deprecations.cmd)

    lint = check_sub.add_parser("lint", parents=[common], help="SQLFluff full ruleset (lint / --fix)")
    _add_selection(lint)
    _add_fix(lint)
    lint.set_defaults(func=lambda a: _run_sqlfluff("lint", a))

    fmt = check_sub.add_parser("format", parents=[common], help="SQLFluff formatter subset (check / --fix)")
    _add_selection(fmt)
    _add_fix(fmt)
    fmt.set_defaults(func=lambda a: _run_sqlfluff("format", a))

    docs = check_sub.add_parser("docs", parents=[common], help="Model description coverage of selected models")
    _add_selection(docs)
    _add_manifest(docs)
    docs.set_defaults(func=coverage.cmd_docs)

    doc_columns = check_sub.add_parser(
        "doc-columns", parents=[common], help="Column description coverage (resolved via catalog.json)"
    )
    _add_selection(doc_columns)
    _add_manifest(doc_columns)
    _add_catalog(doc_columns)
    doc_columns.set_defaults(func=coverage.cmd_columns)

    tests = check_sub.add_parser("tests", parents=[common], help="Test coverage of selected models")
    _add_selection(tests)
    _add_manifest(tests)
    tests.set_defaults(func=coverage.cmd_tests)

    tax = check_sub.add_parser(
        "taxonomy",
        parents=[common],
        help="Deterministic catalogue detectors (grain/freshness/contracts/keys) over selected models",
    )
    _add_selection(tax)
    _add_manifest(tax)
    _add_catalog(tax)  # optional warehouse-resolved columns enrich key-based + TM-* detection
    tax.add_argument("--strict", action="store_true", help="Promote hybrid-rule warnings to failures")
    tax.set_defaults(func=taxonomy.cmd)

    # system-boundaries selects by DATA PRODUCT (selectors.yml), not the changed-file scope.
    sysbound = check_sub.add_parser(
        "system-boundaries",
        parents=[common],
        help="Fail when an inbound/outbound system-boundary node of a data product has zero tests",
    )
    _add_manifest(sysbound)
    _add_dataproduct_scope(sysbound)
    _add_output(sysbound)
    sysbound.set_defaults(func=dataproducts.cmd_check)

    all_ = check_sub.add_parser("all", parents=[common], help="Run every check; non-zero if any fail")
    _add_selection(all_)
    _add_manifest(all_)
    _add_catalog(all_)
    _add_fix(all_)  # propagates to the fixable checks; no-op for the rest
    all_.add_argument(
        "--selectors",
        type=Path,
        default=config.DEFAULT_SELECTORS,
        help="Path to selectors.yml for the system-boundaries gate (default: <project>/%(default)s)",
    )
    all_.add_argument(
        "--md",
        type=Path,
        default=None,
        dest="md_path",
        help="Also write a Markdown summary table to this file (e.g. for a PR comment)",
    )
    all_.set_defaults(func=checks.cmd_all)


def _add_products_group(sub, common: argparse.ArgumentParser) -> None:
    products = sub.add_parser("products", parents=[common], help="Data-product (named-selector) analysis")
    products.set_defaults(func=_help(products))
    products_sub = products.add_subparsers(dest="products_cmd", required=False)

    boundaries = products_sub.add_parser(
        "boundaries", parents=[common], help="Classify each node of a data product as inbound/outbound/both/internal"
    )
    _add_manifest(boundaries)
    _add_dataproduct_scope(boundaries)
    _add_output(boundaries)
    boundaries.set_defaults(func=dataproducts.cmd)

    generate = products_sub.add_parser(
        "generate", parents=[common], help="Build the sdag Cytoscape JSON + HTML viewer assets"
    )
    _add_manifest(generate)
    _add_dataproduct_scope(generate)
    _add_sdag_output(generate)
    generate.set_defaults(func=dataproducts.cmd_generate)

    serve = products_sub.add_parser(
        "serve", parents=[common], help="Generate the sdag assets, then host them over HTTP"
    )
    _add_manifest(serve)
    _add_dataproduct_scope(serve)
    _add_sdag_output(serve)
    serve.add_argument("-p", "--port", type=int, default=8088, help="HTTP port (default: %(default)s)")
    serve.set_defaults(func=dataproducts.cmd_serve)


def _add_review_group(sub, common: argparse.ArgumentParser) -> None:
    """``adaf review`` — LLM taxonomy review via GitHub Models (keyless)."""
    rev = sub.add_parser(
        "review", parents=[common], help="LLM taxonomy review of dbt models (GitHub Models; --post for PR comments)"
    )
    scope = rev.add_mutually_exclusive_group()
    scope.add_argument("--changed-only", action="store_true", help="Review only models changed vs --base-ref (default)")
    scope.add_argument("--all", action="store_true", dest="all_models", help="Review every model")
    rev.add_argument(
        "--base-ref",
        default=config.DEFAULT_BASE_REF,
        help="Git ref the changed-only scope diffs against (default: %(default)s)",
    )
    rev.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the findings result + token usage as JSON to stdout (for the dev skill)",
    )
    rev.add_argument(
        "--post",
        action="store_true",
        help="Upsert the changed + all coverage matrices as sticky PR comments (needs $GITHUB_REPOSITORY + $PR_NUMBER)",
    )
    rev.add_argument(
        "--model",
        default=os.environ.get("MODEL", "openai/gpt-4o"),
        help="GitHub Models model id (default: %(default)s)",
    )
    rev.add_argument(
        "--endpoint",
        default=os.environ.get("MODELS_ENDPOINT", "https://models.github.ai/inference"),
        help="Inference endpoint (default: %(default)s)",
    )
    rev.add_argument("--token", default=None, help="GitHub token (default: $GITHUB_TOKEN)")
    rev.add_argument(
        "--cost-per-1m-input",
        type=float,
        dest="cost_in",
        default=float(os.environ.get("COST_PER_1M_INPUT", "2.5")),
        help="List price $/1M input tokens for the cost estimate (default: %(default)s)",
    )
    rev.add_argument(
        "--cost-per-1m-output",
        type=float,
        dest="cost_out",
        default=float(os.environ.get("COST_PER_1M_OUTPUT", "10")),
        help="List price $/1M output tokens for the cost estimate (default: %(default)s)",
    )
    rev.set_defaults(func=review_cmd.cmd_review)


def _run_sqlfluff(name: str, args: argparse.Namespace) -> int:
    """Thin adapter: resolve the selection, run lint/format, render. Kept here (not in
    sqlfluff.py) so that module stays free of argparse/selection coupling."""
    sel = selection.from_args(args)
    files = selection.resolve_model_files(sel)
    report = sqlfluff_cmd.run(name, files, fix=args.fix, scope=selection.describe(sel))
    return render_from_args(report, args)


# ─── dispatch ────────────────────────────────────────────────────────────────


def _prepare_project(args: argparse.Namespace) -> None:
    """For project-touching commands: discover the dbt root, load its .env, point dbt at its
    committed profiles.yml, and resolve relative path args against the root."""
    config.set_project_root(getattr(args, "project_dir", None))
    load_dotenv(config.PROJECT_ROOT / ".env")  # project IDs for `dbt parse`/`dbt ls`
    # profiles.yml is committed inside the dbt project; force dbt + the sqlfluff dbt templater at
    # it so an inherited DBT_PROFILES_DIR (e.g. the repo root) can't win.
    os.environ["DBT_PROFILES_DIR"] = str(config.PROJECT_ROOT)
    for attr in ("manifest", "catalog", "selectors", "output", "md_path", "review", "template", "workflows_dir"):
        if hasattr(args, attr):
            setattr(args, attr, config.under_root(getattr(args, attr)))


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.debug = getattr(args, "debug", False)
    configure_logging(debug=args.debug)
    style.configure(getattr(args, "color", "auto"))
    if getattr(args, "command", None) in _NEEDS_PROJECT:
        _prepare_project(args)
    try:
        rc = args.func(args)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        log.error("❌ %s", exc)
        raise SystemExit(1) from exc
    raise SystemExit(rc or 0)


if __name__ == "__main__":
    main()
