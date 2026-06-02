"""Argument parsing and dispatch — no business logic (see commands/).

Follows the project CLI conventions (.claude/rules/python/cli.md):
* stdlib ``argparse`` only;
* every group uses ``set_defaults(func=_help(parser))`` + ``add_subparsers(required=False)``
  so an incomplete path prints that group's help instead of erroring;
* leaf commands override ``func`` with their real handler;
* ``main()`` dispatches unconditionally via ``args.func(args)``.

Every leaf shares the selection flags (``--changed-only``/``--all``/``--select``/
``--exclude``/``--base-ref``); the fixable leaves additionally take ``--fix``.

Command tree::

    cicd_cli
      check                       gates over the SELECTED models (changed-only by default)
        deprecations [--fix]      dbt-autofix dry-run / apply over folders of selected models
        lint         [--fix]      SQLFluff full ruleset (lint / fix)
        format       [--fix]      SQLFluff formatter subset (lint --rules / format)
        docs                      model description coverage (no autofix)
        doc-columns               column description coverage, resolved via catalog (no autofix)
        tests                     test coverage (no autofix)
        system-boundaries         fail when an inbound/outbound data-product boundary node has no tests
        all                       run every check; non-zero if any fail
      products                    data-product (named-selector) analysis — read-only
        boundaries                classify each node as inbound/outbound/both/internal system boundary
        generate                  build the sdag Cytoscape JSON + HTML viewer assets
        serve                     generate the sdag assets, then host them over HTTP
"""

# Standard Library
import argparse
import logging
import os
import sys
from pathlib import Path

# Third Party
from dotenv import load_dotenv

# Local
from cicd_cli import config, selection, style
from cicd_cli.commands import checks, coverage, dataproducts, deprecations, sqlfluff
from cicd_cli.formatting import render_from_args
from cicd_cli.logging_setup import configure_logging

log = logging.getLogger(__name__)


def _help(parser: argparse.ArgumentParser):
    """Return a handler that prints ``parser``'s help — the default for incomplete paths."""

    def _print_help(_: argparse.Namespace) -> None:
        parser.print_help()

    return _print_help


def _add_selection(p: argparse.ArgumentParser) -> None:
    """The selection flags shared by every leaf: scope (changed/all) + dbt select/exclude."""
    scope = p.add_mutually_exclusive_group()
    scope.add_argument(
        "--changed-only",
        action="store_true",
        help="Only models changed vs --base-ref (default)",
    )
    scope.add_argument(
        "--all",
        action="store_true",
        dest="all_models",
        help="All models, not only changed ones",
    )
    p.add_argument(
        "--base-ref",
        default=config.DEFAULT_BASE_REF,
        help="Git ref the changed-only scope diffs against (default: %(default)s)",
    )
    p.add_argument(
        "--select",
        action="append",
        metavar="SELECTOR",
        help="dbt selector to narrow the scope (repeatable; multiple union, like dbt)",
    )
    p.add_argument(
        "--exclude",
        action="append",
        metavar="SELECTOR",
        help="dbt exclusion selector (repeatable; matches dbt --exclude)",
    )
    _add_output(p)


def _add_output(p: argparse.ArgumentParser) -> None:
    """The output flags every renderer needs: --json / --show-logs / --show-passes / --color."""
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
        help="Print the raw underlying-tool transcript even on success (always shown on failure)",
    )
    p.add_argument(
        "--show-passes",
        action="store_true",
        dest="show_passes",
        help="Show passing results too (default: only failures are shown)",
    )
    p.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Colourise output: auto (TTY only), always, or never (default: %(default)s)",
    )


def _add_fix(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--fix",
        action="store_true",
        help="Apply fixes instead of only checking (where the tool supports it)",
    )


def _add_manifest(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--manifest",
        type=Path,
        default=config.DEFAULT_MANIFEST,
        help="Path to dbt manifest.json (default: %(default)s)",
    )
    p.add_argument(
        "--parse",
        action="store_true",
        help="Run `dbt parse` first to refresh the manifest before checking",
    )


def _add_catalog(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--catalog",
        type=Path,
        default=config.DEFAULT_CATALOG,
        help="Path to dbt catalog.json — resolved warehouse columns (default: %(default)s)",
    )
    p.add_argument(
        "--docs-generate",
        action="store_true",
        dest="docs_generate",
        help="Run `dbt docs generate` first to refresh the manifest + catalog (needs a warehouse build)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cicd_cli",
        description="Centralised dev/CI automation for the dbt jaffle-shop project.",
    )
    parser.set_defaults(func=_help(parser))
    sub = parser.add_subparsers(dest="command", required=False)

    # --- check group -------------------------------------------------------
    check = sub.add_parser("check", help="Gates over the selected models (changed-only by default)")
    check.set_defaults(func=_help(check))
    check_sub = check.add_subparsers(dest="check_cmd", required=False)

    dep = check_sub.add_parser("deprecations", help="dbt-autofix over folders of selected models")
    _add_selection(dep)
    _add_fix(dep)
    dep.set_defaults(func=deprecations.cmd)

    lint = check_sub.add_parser("lint", help="SQLFluff full ruleset (lint / --fix)")
    _add_selection(lint)
    _add_fix(lint)
    lint.set_defaults(func=lambda a: _run_sqlfluff("lint", a))

    fmt = check_sub.add_parser("format", help="SQLFluff formatter subset (check / --fix)")
    _add_selection(fmt)
    _add_fix(fmt)
    fmt.set_defaults(func=lambda a: _run_sqlfluff("format", a))

    docs = check_sub.add_parser("docs", help="Model description coverage of selected models")
    _add_selection(docs)
    _add_manifest(docs)
    docs.set_defaults(func=coverage.cmd_docs)

    doc_columns = check_sub.add_parser("doc-columns", help="Column description coverage (resolved via catalog.json)")
    _add_selection(doc_columns)
    _add_manifest(doc_columns)
    _add_catalog(doc_columns)
    doc_columns.set_defaults(func=coverage.cmd_columns)

    tests = check_sub.add_parser("tests", help="Test coverage of selected models")
    _add_selection(tests)
    _add_manifest(tests)
    tests.set_defaults(func=coverage.cmd_tests)

    # system-boundaries selects by DATA PRODUCT (selectors.yml), not by the changed-file scope the
    # other checks share — so it takes --selectors/--product, not _add_selection. Fails when a node
    # on a product's system boundary (inbound/outbound/both) has zero tests.
    sysbound = check_sub.add_parser(
        "system-boundaries",
        help="Fail when an inbound/outbound system-boundary node of a data product has zero tests",
    )
    _add_manifest(sysbound)
    sysbound.add_argument(
        "--selectors",
        type=Path,
        default=config.DEFAULT_SELECTORS,
        help="Path to dbt's selectors.yml defining the data products (default: %(default)s)",
    )
    sysbound.add_argument(
        "--product",
        action="append",
        metavar="NAME",
        help="Limit the gate to this named data product (repeatable; default: all in selectors.yml)",
    )
    _add_output(sysbound)
    sysbound.set_defaults(func=dataproducts.cmd_check)

    all_ = check_sub.add_parser("all", help="Run every check; non-zero if any fail")
    _add_selection(all_)
    _add_manifest(all_)
    _add_catalog(all_)
    _add_fix(all_)  # propagates to the fixable checks (deprecations, lint, format); no-op for the rest
    all_.add_argument(
        "--selectors",
        type=Path,
        default=config.DEFAULT_SELECTORS,
        help="Path to selectors.yml for the system-boundaries gate (default: %(default)s)",
    )
    all_.add_argument(
        "--md",
        type=Path,
        default=None,
        dest="md_path",
        help="Also write a Markdown summary table to this file (e.g. for a PR comment)",
    )
    all_.set_defaults(func=checks.cmd_all)

    # --- products group ----------------------------------------------------
    # Data-product (named-selector) analysis. Read-only today; feeds a future contracts/tests gate.
    products = sub.add_parser("products", help="Data-product (named-selector) analysis")
    products.set_defaults(func=_help(products))
    products_sub = products.add_subparsers(dest="products_cmd", required=False)

    boundaries = products_sub.add_parser(
        "boundaries",
        help="Classify each node of a data product as an inbound/outbound/both/internal system boundary",
    )
    _add_manifest(boundaries)  # --manifest + --parse (the lineage graph comes from manifest.json)
    _add_dataproduct_scope(boundaries)  # --selectors + --product
    _add_output(boundaries)  # --json / --show-passes (shows internal nodes too) / --color
    boundaries.set_defaults(func=dataproducts.cmd)

    # products generate / serve — the interactive sdag viewer over the data products.
    generate = products_sub.add_parser("generate", help="Build the sdag Cytoscape JSON + HTML viewer assets")
    _add_manifest(generate)
    _add_dataproduct_scope(generate)
    _add_sdag_output(generate)
    generate.set_defaults(func=dataproducts.cmd_generate)

    serve = products_sub.add_parser("serve", help="Generate the sdag assets, then host them over HTTP")
    _add_manifest(serve)
    _add_dataproduct_scope(serve)
    _add_sdag_output(serve)
    serve.add_argument("-p", "--port", type=int, default=8088, help="HTTP port (default: %(default)s)")
    serve.set_defaults(func=dataproducts.cmd_serve)

    return parser


def _add_dataproduct_scope(p: argparse.ArgumentParser) -> None:
    """The data-product selection flags: --selectors (the selectors.yml) + --product (subset by name)."""
    p.add_argument(
        "--selectors",
        type=Path,
        default=config.DEFAULT_SELECTORS,
        help="Path to dbt's selectors.yml defining the data products (default: %(default)s)",
    )
    p.add_argument(
        "--product",
        action="append",
        metavar="NAME",
        help="Limit to this named data product (repeatable; default: all in selectors.yml)",
    )


def _add_sdag_output(p: argparse.ArgumentParser) -> None:
    """The viewer output directory flag (defaults under the project tmp/)."""
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=config.DEFAULT_SDAG_OUTPUT,
        help="Directory for the generated viewer assets (default: %(default)s)",
    )


def _run_sqlfluff(name: str, args: argparse.Namespace) -> int:
    # Thin adapter: resolve the selection, run lint/format, render. (Kept here rather than
    # in sqlfluff.py so that module stays free of argparse/selection coupling.)
    sel = selection.from_args(args)
    files = selection.resolve_model_files(sel)
    report = sqlfluff.run(name, files, fix=args.fix, scope=selection.describe(sel))
    return render_from_args(report, args)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging()
    style.configure(getattr(args, "color", "auto"))
    load_dotenv()  # load dbt-jaffleshop/.env if present (project IDs for dbt parse/ls)
    # profiles.yml is committed inside the dbt project, so point dbt AND the sqlfluff dbt
    # templater at it unconditionally — mirrors the Makefile's `export DBT_PROFILES_DIR :=
    # $(CURDIR)`. An inherited DBT_PROFILES_DIR (e.g. the repo root) would otherwise win and
    # dbt would fail with "Could not find profile named 'jaffle_shop'".
    os.environ["DBT_PROFILES_DIR"] = str(config.PROJECT_ROOT)
    try:
        rc = args.func(args)
    except (RuntimeError, FileNotFoundError) as exc:
        log.error("%s", exc)
        sys.exit(1)
    sys.exit(rc or 0)
