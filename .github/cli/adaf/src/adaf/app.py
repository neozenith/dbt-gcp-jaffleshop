"""Automated Data Assurance Framework CLI wiring — build_parser() + main() only.

No business logic lives here; the command bodies live in adaf.checks (shell-out gates),
adaf.coverage (manifest-backed gates), and adaf.sdag (the lineage viewer).

Follows the project argparse convention (.claude/rules/python/cli.md): a ``_help``
closure as each parser's default func (so an incomplete path prints help instead of
erroring), leaf subcommands override it via ``set_defaults(func=...)``, and ``main()``
dispatches ``args.func(args)`` unconditionally, exiting with its return code.

Command tree::

    adaf
      list (ls) [--defer]     list the resolved target model files for the scope
                              (--defer splits each group into built / deferred subgroups)
      deprecations (dep) [--fix] [--commands]  dbt-autofix over folders of the selected models
      sqlfluff (fluff)  [--fix] [--format FMT] [--commands]  SQLFluff lint (or fix) over the selected models
      docscov                 model-description coverage of the selected models (from manifest)
      testcov                 test coverage of the selected models (from manifest)
      defer-state             build/reuse the defer-target state for a ref; print its --state dir (CI)
      sdag                    the data-product lineage viewer
        generate [--inline]   write the viewer assets (--inline = one standalone HTML)
        serve    [--inline]   regenerate, then host the viewer over HTTP
        check    [--parse]    lint boundary-node system-boundary obligations (fails on violations)

The file-scoped commands also share an optional ``--target`` (dbt target, e.g. dev/test) that
flows to ``dbt ls`` and the defer-target parse so state:modified compares like-for-like.

The file-scoped commands (list / deprecations / sqlfluff / docscov / testcov) share the scope
flags: --changed-only (default) / --all, --base-ref, and a REQUIRED --selector. The scope is
always the models in (changed or all) that are ALSO in ``dbt ls --selector <name>``. ``sdag``
instead operates over the
NAMED selectors (data products) in selectors.yml and defaults to ``--parse`` (use --no-parse).
"""

# Standard Library
import argparse
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Local
from adaf import config, report
from adaf.commands import checks, coverage
from adaf.commands import report as report_cmd
from adaf.commands.defer import built_model_paths, cmd_defer_state
from adaf.commands.sdaglint import cmd_sdag_check
from adaf.dbt import selectorflags
from adaf.dbt.ls import ls_model_paths
from adaf.dbt.manifest_view import ManifestView
from adaf.dbt.selection import (
    UNBOUNDED,
    describe,
    from_args,
    grouped_scope,
    resolve_model_files,
    resolve_model_ids,
)
from adaf.gha import cmd_analyse as gha_analyse
from adaf.gha import cmd_create as gha_create
from adaf.gha import cmd_init as gha_init
from adaf.gha import cmd_update as gha_update
from adaf.gha import globber
from adaf.gha.globber import DEFAULT_PATH_MODE, PATH_MODES
from adaf.git.gitutil import changed_model_files
from adaf.sdag import cmd_generate, cmd_serve
from adaf.sdag.commands import ARCHIVE_DEFAULT


def _help(p: argparse.ArgumentParser) -> Callable[[argparse.Namespace], int]:
    """Return a handler that prints help for parser p (used as the default func)."""

    def _print_help(_: argparse.Namespace) -> int:
        p.print_help()
        return 0

    return _print_help


def _describe(p: argparse.ArgumentParser, purpose: str, *examples: str) -> argparse.ArgumentParser:
    """Make a subcommand self-describing: a full-sentence ``description`` (shown in its ``--help``
    body) plus an ``epilog`` of copy-pasteable example invocations. Returned so callers can chain.

    This is what lets an agent traverse the whole CLI from ``--help`` alone — ``adaf --help`` lists
    every subcommand with its one-line ``help=``, and ``adaf <cmd> --help`` then explains the
    command's purpose and shows how to run it.
    """
    p.description = purpose
    if examples:
        p.epilog = "Examples:\n" + "\n".join(f"  {ex}" for ex in examples)
        p.formatter_class = argparse.RawDescriptionHelpFormatter
    return p


def _add_scope(p: argparse.ArgumentParser) -> None:
    """Scope flags shared by every file-scoped command: changed/all + base-ref + selector."""
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--changed-only", action="store_true", help="Only models changed vs --base-ref (default)")
    scope.add_argument("--all", action="store_true", dest="all_models", help="All in-scope models, not only changed")
    scope.add_argument(
        "--state-modified",
        action="store_true",
        dest="state_modified",
        help="Only models the OFFLINE calculator flags as dbt state:modified vs --defer-ref (faithful; "
        "selector resolves Cloud-CLI-safely, baseline build needs dbt-core)",
    )
    scope.add_argument(
        "--state-modified-plus",
        action="store_true",
        dest="state_modified_plus",
        help="state:modified + descendants (M+) — the canonical deferred-build set",
    )
    scope.add_argument(
        "--state-modified-plus-plus",
        action="store_true",
        dest="state_modified_plus_plus",
        help="(selector ∩ state:modified+) THEN all descendants — crosses the product boundary to "
        "rebuild out-of-product consumers (always resolved to paths; never the native expression)",
    )
    p.add_argument(
        "--state",
        default=None,
        metavar="DIR",
        help="Explicit baseline manifest dir for --state-modified (the dbt --state convention). Skips "
        "building it from --defer-ref via git — supply a prebuilt baseline (e.g. `adaf defer-state`).",
    )
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
    p.add_argument(
        "--json-out",
        dest="json_out",
        type=Path,
        default=None,
        metavar="PATH",
        help="Also write machine-readable findings JSON to PATH (for `adaf report`). Combine with -q "
        "to emit ONLY the JSON (suppress the human findings text).",
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


def _add_fix(p: argparse.ArgumentParser) -> None:
    p.add_argument("--fix", action="store_true", help="Apply fixes in place instead of only reporting (mutates files)")


def _add_commands(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--commands",
        action="store_true",
        help="Print the exact subprocess command(s) adaf would run instead of running them (no magic)",
    )


def _add_manifest(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--manifest",
        type=Path,
        default=config.DEFAULT_MANIFEST,
        help="Path to dbt manifest.json (default: <project>/%(default)s)",
    )
    p.add_argument("--parse", action="store_true", help="Run `dbt parse` first to refresh the manifest")


def _add_sdag_scope(p: argparse.ArgumentParser) -> None:
    """Flags shared by the sdag commands: selectors file, product filter, manifest, output dir."""
    p.add_argument(
        "--selectors",
        type=Path,
        default=config.DEFAULT_SELECTORS,
        help="Path to dbt's selectors.yml defining the data products (default: <project>/%(default)s)",
    )
    p.add_argument(
        "--manifest",
        type=Path,
        default=config.DEFAULT_MANIFEST,
        help="Path to dbt manifest.json (default: <project>/%(default)s)",
    )
    # Default ON (matches dbt's --no-* convention): the viewer reflects the live graph, so it
    # reparses unless you opt out with --no-parse (e.g. when the manifest is known-fresh).
    p.add_argument(
        "--parse",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run `dbt parse` first to refresh the manifest (default: on; use --no-parse to skip)",
    )
    p.add_argument(
        "--inline",
        action="store_true",
        help="Emit a single standalone sdag.html with the JS + graph JSON inlined (no sidecar files)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=config.DEFAULT_SDAG_OUTPUT,
        help="Directory for the generated viewer assets (default: <project>/%(default)s)",
    )
    # Bundle the generated viewer into a portable .zip. Bare --archive ⇒ <output>/sdag.zip;
    # --archive PATH ⇒ that path. Pair with --inline for a single self-contained sdag.html.
    p.add_argument(
        "--archive",
        nargs="?",
        const=ARCHIVE_DEFAULT,
        default=None,
        metavar="PATH",
        help="Bundle the generated viewer into a portable .zip (bare: <output>/sdag.zip; or --archive PATH). "
        "Pair with --inline for a single-file archive.",
    )


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--project-dir",
        dest="project_dir",
        default=argparse.SUPPRESS,
        help="Path to the dbt project (a dir with dbt_project.yml). Overrides $ADAF_PROJECT_DIR + walk-up discovery.",
    )
    common.add_argument(
        "-v",
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Verbose debug logging (DEBUG level) to stderr",
    )
    common.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Quiet: only warnings + errors (drops INFO progress logs)",
    )
    common.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="When to colourise report output (default: %(default)s)",
    )

    parser = argparse.ArgumentParser(
        prog="adaf",
        description=(
            "Automated Data Assurance Framework CLI: SQLFluff + dbt-autofix gates and coverage "
            "checks over the models you changed that are also in a named dbt selector, plus an "
            "sdag data-product lineage viewer."
        ),
        epilog=(""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
    )
    parser.set_defaults(func=_help(parser))
    sub = parser.add_subparsers(dest="command", required=False)

    p_list = sub.add_parser(
        "list", aliases=["ls"], parents=[common], help="List the resolved target model files for the scope"
    )
    _describe(
        p_list,
        "Resolve the scope (changed or --all models that are also in the named selector) and print the "
        "model .sql files that the gates would run on. The dry-run preview of every other command's target set.",
        "adaf list --selector demand",
        "adaf list --all --selector demand --upstream 1",
    )
    _add_scope(p_list)
    p_list.add_argument(
        "--bare",
        action="store_true",
        help="Flat path list with no group headers (pipeable); default groups by selector/upstream/downstream",
    )
    p_list.add_argument(
        "--macros",
        action="store_true",
        help="Also list the repo macro files the selected models depend on (read from the manifest)",
    )
    p_list.add_argument(
        "--paths",
        choices=PATH_MODES,
        default=None,
        help="Preview the gha trigger globs this --paths mode would emit for the selector, and highlight "
        "(dark red) the FALSE-POSITIVE files those globs also match beyond the selector's own members",
    )
    p_list.add_argument(
        "--flags",
        action="store_true",
        help="Instead of listing models, emit the dbt `--select`/`--state`/`--defer` flags to feed "
        "`dbt build`/`compile`. With --defer the seed is state:modified ∩ selector; --upstream/"
        "--downstream attach +/- graph operators so dbt traverses the lineage from the seed.",
    )
    p_list.set_defaults(func=_cmd_list)

    p_dep = sub.add_parser(
        "deprecations", aliases=["dep"], parents=[common], help="dbt-autofix over folders of selected models"
    )
    _describe(
        p_dep,
        "Run dbt-autofix's deprecation scan over the folders of the selected models (dry-run; reports files "
        "that need changes). Add --fix to rewrite them in place, or --commands to print the exact dbt-autofix "
        "command(s) instead of running them.",
        "adaf deprecations --selector demand",
        "adaf dep --all --selector demand --fix",
        "adaf dep --all --selector demand --commands",
    )
    _add_scope(p_dep)
    _add_fix(p_dep)
    _add_commands(p_dep)
    p_dep.set_defaults(func=_cmd_deprecations)

    p_fluff = sub.add_parser(
        "sqlfluff", aliases=["fluff"], parents=[common], help="SQLFluff lint (or --fix) over selected models"
    )
    _describe(
        p_fluff,
        "Lint the selected models with SQLFluff (exit code is the pass/fail signal). Add --fix to apply "
        "auto-fixable rules in place, --format github-annotation-native to emit inline PR annotations in CI, "
        "or --commands to print the exact sqlfluff command instead of running it.",
        "adaf sqlfluff --selector demand",
        "adaf fluff --all --selector demand --fix",
        "adaf fluff --all --selector demand --commands",
    )
    _add_scope(p_fluff)
    _add_fix(p_fluff)
    _add_commands(p_fluff)
    p_fluff.add_argument(
        "--format",
        dest="fmt",
        default=None,
        help="SQLFluff --format for lint output (e.g. github-annotation-native for inline PR annotations)",
    )
    p_fluff.set_defaults(func=_cmd_sqlfluff)

    p_docs = sub.add_parser("docscov", parents=[common], help="Model-description coverage of selected models")
    _describe(
        p_docs,
        "Fail the selected models that have no description, read from the dbt manifest (no warehouse). "
        "Use --parse to refresh the manifest first.",
        "adaf docscov --all --selector demand --parse",
    )
    _add_scope(p_docs)
    _add_manifest(p_docs)
    p_docs.set_defaults(func=_cmd_docscov)

    p_tests = sub.add_parser("testcov", parents=[common], help="Test coverage of selected models")
    _describe(
        p_tests,
        "Fail the selected models that have zero tests, read from the dbt manifest (no warehouse). "
        "Use --parse to refresh the manifest first.",
        "adaf testcov --all --selector demand",
    )
    _add_scope(p_tests)
    _add_manifest(p_tests)
    p_tests.set_defaults(func=_cmd_testcov)

    p_ds = sub.add_parser(
        "defer-state",
        parents=[common],
        help="Build (or reuse) the defer-target state for a ref and print its --state dir (for CI)",
    )
    p_ds.add_argument(
        "--defer-ref",
        dest="defer_ref",
        default="main",
        metavar="REF",
        help="Git ref whose parsed manifest is the defer-target baseline (default: %(default)s)",
    )
    p_ds.add_argument("--force", action="store_true", help="Rebuild even if a cached state dir exists for this sha")
    _add_target(p_ds)
    _add_defer_target(p_ds)
    _describe(
        p_ds,
        "Generate defer state files: Checkout a git worktree to build the defer-target manifest for a git ref "
        "and print its --state directory on stdout — the plumbing behind --defer, for CI to feed `dbt build --state`.",
        "STATE=$(adaf defer-state --defer-ref main --target dev --defer-target nonprod)",
    )
    p_ds.set_defaults(func=cmd_defer_state)

    _add_sdag_group(sub, common)
    _add_gha_group(sub, common)

    report_p = sub.add_parser(
        "report",
        parents=[common],
        help="Summarise check findings + the dbt build into one sticky PR comment",
    )
    report_p.add_argument(
        "--findings-dir",
        dest="findings_dir",
        type=Path,
        default=Path("findings"),
        metavar="DIR",
        help="Directory of per-check findings JSON artifacts (default: %(default)s)",
    )
    report_p.add_argument(
        "--run-results",
        dest="run_results",
        type=Path,
        default=Path("target/run_results.json"),
        metavar="PATH",
        help="dbt run_results.json for the build summary (default: %(default)s)",
    )
    report_p.add_argument(
        "--manifest",
        type=Path,
        default=Path("target/manifest.json"),
        metavar="PATH",
        help="dbt manifest.json for node names/paths (default: %(default)s)",
    )
    report_p.add_argument("--selector", default=None, help="Data product name for the title (default: $DBT_SELECTOR)")
    report_p.add_argument(
        "--repo", default=None, metavar="OWNER/REPO", help="Target repo (default: $GITHUB_REPOSITORY)"
    )
    report_p.add_argument(
        "--pr", type=int, default=None, metavar="N", help="PR number (default: $DBT_PR_NUMBER / $GITHUB_REF)"
    )
    report_p.add_argument("--token", default=None, help="GitHub token (default: $GITHUB_TOKEN)")
    report_p.add_argument(
        "--section",
        choices=["findings", "build", "all"],
        default="all",
        help="Which section of the sticky comment to render/upsert (default: %(default)s — the whole comment)",
    )
    report_p.add_argument(
        "--marker",
        default=report_cmd.DEFAULT_MARKER,
        help="Hidden HTML marker identifying the sticky comment (default: %(default)s)",
    )
    report_p.add_argument(
        "--edr-url", dest="edr_url", default=None, help="EDR report artifact URL (default: $EDR_REPORT_URL)"
    )
    report_p.add_argument(
        "--sdag-url", dest="sdag_url", default=None, help="sdag viewer artifact URL (default: $SDAG_VIEWER_URL)"
    )
    report_p.add_argument(
        "--docs-url", dest="docs_url", default=None, help="dbt docs artifact URL (default: $DBT_DOCS_URL)"
    )
    report_p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Print the markdown instead of posting the comment",
    )
    report_p.set_defaults(func=report_cmd.cmd_report)

    return parser


def _add_gha_common(p: argparse.ArgumentParser) -> None:
    """Args shared by ``gha create`` / ``gha update``: the product (or --all), selectors file, the
    path-collapse mode, and the output workflows dir."""
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


def _add_gha_group(sub: Any, common: argparse.ArgumentParser) -> None:
    """``adaf gha create|update`` — generate / refresh per-data-product workflow entrypoints."""
    gha_p = sub.add_parser("gha", parents=[common], help="Generate per-data-product GHA workflow entrypoints")
    gha_p.set_defaults(func=_help(gha_p))
    gha_sub = gha_p.add_subparsers(dest="gha_cmd", required=False)

    create = gha_sub.add_parser(
        "create", parents=[common], help="Create .github/workflows/adaf-<product>.yml from the template"
    )
    _add_gha_common(create)
    create.add_argument(
        "--template",
        type=Path,
        default=config.DEFAULT_WORKFLOW_TEMPLATE,
        help="Workflow template to clone (default: the CLI-owned base template)",
    )
    create.add_argument("--force", action="store_true", help="Overwrite an existing adaf-<product>.yml")
    _describe(
        create,
        "Clone the CLI-owned workflow template into .github/workflows/adaf-<product>.yml, with the trigger "
        "`paths` DERIVED from `dbt ls --selector <product>` (collapsed per --paths). Prints the collapse "
        "working-out + false-positive audit. Refuses to overwrite without --force.",
        "adaf gha create demand",
        "adaf gha create --all --paths leaf",
        "adaf gha create supply --paths strict --workflows-dir tmp/gha",
    )
    create.set_defaults(func=gha_create)

    update = gha_sub.add_parser(
        "update", parents=[common], help="Re-derive ONLY the trigger paths of an existing adaf-<product>.yml"
    )
    _add_gha_common(update)
    _describe(
        update,
        "Refresh the `on.pull_request.paths` of an existing workflow from the current selector membership "
        "(e.g. after adding a model), leaving every other hand-edit intact. Same --paths modes + audit.",
        "adaf gha update demand",
        "adaf gha update --all",
    )
    update.set_defaults(func=gha_update)

    analyse = gha_sub.add_parser(
        "analyse", parents=[common], help="Tabulate selector size vs each --paths algorithm's false-positive rate"
    )
    _add_gha_common(analyse)
    _describe(
        analyse,
        "Read-only: for one selector (or --all), print a TUI table of how many files are TRUE members, "
        "how many each of the 3 path algorithms (strict/leaf/recursive) would match, and the false-"
        "positive count + rate per algorithm — so you can pick a --paths mode with eyes open.",
        "adaf gha analyse demand",
        "adaf gha analyse --all --macros",
    )
    analyse.set_defaults(func=gha_analyse)

    init = gha_sub.add_parser(
        "init", parents=[common], help="Materialise the CLI-owned adaf-* composite actions into .github/actions"
    )
    init.add_argument(
        "--actions-dir",
        type=Path,
        default=config.DEFAULT_ACTIONS_DIR,
        dest="actions_dir",
        help="Directory to write the adaf-<name>/ composite actions into (default: <project>/%(default)s)",
    )
    init.add_argument(
        "--workflows-dir",
        type=Path,
        default=config.DEFAULT_WORKFLOWS_DIR,
        dest="workflows_dir",
        help="Directory to write the reusable workflow (adaf-reusable.yml) into (default: <project>/%(default)s)",
    )
    init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files (otherwise existing files are skipped and version drift is reported)",
    )
    _describe(
        init,
        "Write the CLI-owned reusable composite actions (adaf-ci, adaf-cleanup) into "
        ".github/actions, stamping each file with a `# adaf:managed version=<X.Y.Z>` banner. Existing files "
        "are skipped unless --force; a skip whose deployed version differs from the CLI version is flagged "
        "as drift so you know to re-sync.",
        "adaf gha init",
        "adaf gha init --force",
        "adaf gha init --actions-dir tmp/actions",
    )
    init.set_defaults(func=gha_init)


def _add_sdag_check_scope(p: argparse.ArgumentParser) -> None:
    """``sdag check`` uses the SAME scope core as the file-scoped gates (required --selector,
    --changed-only default / --all, --base-ref, --defer…) plus --manifest/--parse."""
    _add_scope(p)
    _add_manifest(p)


def _add_sdag_group(sub: Any, common: argparse.ArgumentParser) -> None:
    """``adaf sdag {generate,serve,check}`` — the data-product lineage viewer + boundary lint."""
    sdag_p = sub.add_parser("sdag", parents=[common], help="Data-product lineage viewer (generate / serve / check)")
    sdag_p.set_defaults(func=_help(sdag_p))
    sdag_sub = sdag_p.add_subparsers(dest="sdag_cmd", required=False)

    gen = sdag_sub.add_parser(
        "generate", parents=[common], help="Write the sdag Cytoscape JSON + HTML/JS viewer assets"
    )
    _describe(
        gen,
        "Resolve every static named selector (data product), read the manifest, and write the interactive "
        "Cytoscape lineage viewer assets to --output. Use --inline for one standalone HTML, --no-parse to "
        "reuse the existing manifest, --archive to bundle the viewer into a portable .zip.",
        "adaf sdag generate --no-parse",
        "adaf sdag generate --inline -o tmp/sdag",
        "adaf sdag generate --inline --archive",
    )
    _add_sdag_scope(gen)
    gen.set_defaults(func=cmd_generate)

    serve = sdag_sub.add_parser("serve", parents=[common], help="Generate the sdag assets, then host them over HTTP")
    _describe(
        serve,
        "Regenerate the viewer assets, then host them over HTTP (the multi-file viewer needs a server, not "
        "file://). Open the printed localhost URL.",
        "adaf sdag serve",
        "adaf sdag serve --port 9000",
    )
    _add_sdag_scope(serve)
    serve.add_argument("-p", "--port", type=int, default=8088, help="HTTP port (default: %(default)s)")
    serve.set_defaults(func=cmd_serve)

    check = sdag_sub.add_parser(
        "check", parents=[common], help="Lint each data product's boundary nodes for system-boundary obligations"
    )
    _describe(
        check,
        "Lint a data product's system-boundary nodes against their obligations — outbound models need "
        "a contract (MD-02), exposure (MD-11), semantic model (MD-12); inbound sources need freshness "
        "(TM-AU-01); inbound nodes need a volume-anomaly test (MD-07). Same scope as every check: "
        "--selector bounds the product, default reports only changed boundary nodes, --all reports the "
        "whole product. Exits 1 on any unsuppressed violation; suppress false positives in .adaf.yml.",
        "adaf sdag check --all --selector demand",
        "adaf sdag check --selector demand",
        "adaf sdag check --all --selector demand --defer --defer-ref main",
    )
    _add_sdag_check_scope(check)
    check.set_defaults(func=cmd_sdag_check)


# ─── leaf handlers ────────────────────────────────────────────────────────────


def _git_changed_models(base_ref: str, cwd: Path) -> set[str]:
    """Changed-vs-git model paths for the `list` two-tone highlight — or EMPTY when git context is
    unavailable.

    The highlight inherently needs a git baseline; running against a non-repo (e.g. the multiversion
    Docker fixture) or without the `git` binary means there is no "changed" set to compute. That must
    NOT break `list` (whose core job is to list the scope) — so we degrade the *adornment* (no
    highlight), never the *command*. Only the two git-absence signals are caught; any other error
    still surfaces.
    """
    try:
        return {str(p) for p in changed_model_files(base_ref, cwd=cwd)}
    except (FileNotFoundError, RuntimeError) as exc:
        logging.getLogger(__name__).debug("git unavailable (%s); listing without changed-file highlight", exc)
        return set()


def _cmd_list(args: argparse.Namespace) -> int:
    sel = from_args(args)
    if getattr(args, "flags", False):  # emit dbt build flags instead of listing models
        flags = selectorflags.compose(sel)
        if flags:
            print(flags)
        return 0
    color = report.should_colorize(args.color, sys.stdout)
    root = config.project_root()
    manifest = config.under_root(config.DEFAULT_MANIFEST)
    assert manifest is not None  # DEFAULT_MANIFEST is a fixed relative path
    view = ManifestView.load(manifest)
    # Split the scope into selector models + the upstream/downstream nodes a hop flag added, so each
    # direction can be a titled group (and the hop nodes render as darker-grey context).
    selector, upstream, downstream = grouped_scope(sel, view, cwd=root)
    # Highlight git-changed models (vs --base-ref) in a lighter grey so they pop under --all.
    changed = _git_changed_models(sel.base_ref, root)
    # Under --defer, split each group into BUILT (state:modified+ vs --defer-ref) and DEFERRED
    # (reused from the baseline) subgroups — the same M+ set `adaf ls --flags` would build.
    built = built_model_paths(sel, manifest, root=root) if getattr(sel, "defer", False) else None
    rc = checks.list_targets(
        describe(sel),
        selector,
        color=color,
        bare=getattr(args, "bare", False),
        changed=changed,
        upstream=upstream,
        downstream=downstream,
        built=built,
    )
    if getattr(args, "macros", False):
        macro_files = view.dependent_macro_files(resolve_model_ids(sel, view, cwd=root))
        report.render_headline(
            f"dependent macros — {len(macro_files)} repo macro file(s)", color=color, severity="info"
        )
        for path in sorted(macro_files):
            print(path)
    if getattr(args, "paths", None):
        # Preview the gha trigger globs for this mode against the FULL selector membership (matching
        # `gha create`), and flag in dark red the extra files those globs would also fire on.
        discovered = ls_model_paths(sel.selector, cwd=root)
        if getattr(args, "macros", False):
            models = view.of_type("model")
            ids = {u for u, r in models.items() if str(r.raw.get("original_file_path") or "") in discovered}
            discovered |= view.dependent_macro_files(ids)
        globs = globber.discover_to_globs(discovered, args.paths)
        _log = logging.getLogger(__name__)
        for glob in globs:
            _log.info("ls --paths %s — glob checked: %s", args.paths, glob)
        fps = globber.false_positives(globs, globber.universe_sql(root, with_macros=args.macros), canonical=discovered)
        report.render_headline(
            f"--paths {args.paths}: {len(globs)} glob(s), {len(fps)} false positive(s)",
            color=color,
            severity="warn" if fps else "ok",
        )
        for path in sorted(fps):
            print(report.colorize(path, "darkred", color))
    return rc


def _cmd_deprecations(args: argparse.Namespace) -> int:
    color = report.should_colorize(args.color, sys.stdout)
    return checks.check_deprecations(
        resolve_model_files(from_args(args)),
        fix=args.fix,
        commands=args.commands,
        color=color,
        json_out=args.json_out,
        quiet=getattr(args, "quiet", False),
    )


def _cmd_sqlfluff(args: argparse.Namespace) -> int:
    color = report.should_colorize(args.color, sys.stdout)
    return checks.check_sqlfluff(
        resolve_model_files(from_args(args)),
        fix=args.fix,
        fmt=getattr(args, "fmt", None),
        commands=args.commands,
        color=color,
        json_out=args.json_out,
        quiet=getattr(args, "quiet", False),
    )


def _cmd_docscov(args: argparse.Namespace) -> int:
    sel = from_args(args)
    manifest = coverage.load_manifest(args.manifest, parse=args.parse, target=sel.target)
    color = report.should_colorize(args.color, sys.stdout)
    return coverage.check_docs(
        resolve_model_files(sel),
        manifest,
        scope=describe(sel),
        color=color,
        manifest_path=args.manifest,
        json_out=args.json_out,
        quiet=getattr(args, "quiet", False),
    )


def _cmd_testcov(args: argparse.Namespace) -> int:
    sel = from_args(args)
    manifest = coverage.load_manifest(args.manifest, parse=args.parse, target=sel.target)
    color = report.should_colorize(args.color, sys.stdout)
    return coverage.check_tests(
        resolve_model_files(sel),
        manifest,
        scope=describe(sel),
        color=color,
        manifest_path=args.manifest,
        json_out=args.json_out,
        quiet=getattr(args, "quiet", False),
    )


# ─── dispatch ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "debug", False):
        level = logging.DEBUG
    elif getattr(args, "quiet", False):
        level = logging.WARNING
    else:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    if getattr(args, "command", None):  # every command operates on the dbt project
        config.set_project_root(getattr(args, "project_dir", None))
        # Point dbt + the sqlfluff dbt templater at the committed profiles.yml, and default
        # to oauth so the BigQuery adapter initialises without a service-account keyfile.
        os.environ["DBT_PROFILES_DIR"] = str(config.project_root())
        os.environ.setdefault("DBT_AUTH_METHOD", "oauth")
        # Resolve relative path args against the discovered project root.
        for attr in ("manifest", "selectors", "output", "template", "workflows_dir", "state"):
            if hasattr(args, attr):
                setattr(args, attr, config.under_root(getattr(args, attr)))
    try:
        rc = args.func(args)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", flush=True)
        raise SystemExit(1) from exc
    raise SystemExit(rc or 0)


if __name__ == "__main__":
    main()
