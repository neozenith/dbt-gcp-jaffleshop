"""``check all`` — run every gate over one selection, aggregate, exit non-zero if any fail.

Resolves the model selection ONCE and the manifest ONCE, then fans the shared file list out to the
file-scoped checks (deprecations, lint, format, docs, doc-columns, tests) in check mode. The combined
``--json`` payload is each check's ``to_dict()`` keyed by its name.

``system-boundaries`` is also included, but it does NOT consume the model-file selection — it gates by
DATA PRODUCT (``selectors.yml``), so it always runs over every product regardless of
``--changed-only``/``--all``. Like ``doc-columns``, a failure to resolve it (bad selectors / dbt-ls
error) is caught and surfaced as a visible failing row rather than crashing the whole aggregate.
"""

# Standard Library
import json
import logging
import sys

# Local
from adaf import config, selection, style
from adaf.commands import coverage, dataproducts, deprecations, sqlfluff, taxonomy
from adaf.formatting import emit_tool_logs, markdown_summary
from adaf.graph import Graph
from adaf.suppression import Suppressions
from adaf.taxonomy import load_node_facts

log = logging.getLogger(__name__)


def cmd_all(args) -> int:
    cwd = config.PROJECT_ROOT
    sel = selection.from_args(args)
    scope = selection.describe(sel)
    files = selection.resolve_model_files(sel, cwd=cwd)

    # --fix propagates to the fixable checks (deprecations, lint, format); docs/tests have no
    # auto-fix, so it is a no-op for them.
    fix = getattr(args, "fix", False)
    dep_report = deprecations.run(files, scope=scope, fix=fix, cwd=cwd)
    lint_report = sqlfluff.run("lint", files, fix=fix, scope=scope, cwd=cwd)
    format_report = sqlfluff.run("format", files, fix=fix, scope=scope, cwd=cwd)
    if args.docs_generate:
        coverage.dbt_docs_generate(cwd)
        manifest = coverage.load_manifest(args.manifest, parse=False, cwd=cwd)
    else:
        manifest = coverage.load_manifest(args.manifest, parse=args.parse, cwd=cwd)
    docs_report = coverage.evaluate_docs(manifest, files, scope=scope)
    try:
        catalog = coverage.load_catalog(args.catalog)
        columns_report = coverage.evaluate_columns(manifest, catalog, files, scope=scope)
    except FileNotFoundError as exc:
        # Keep the other gates running; surface the missing catalog as a visible columns failure.
        columns_report = coverage.ColumnsReport(scope, [], error=str(exc))
    tests_report = coverage.evaluate_tests(manifest, files, scope=scope)

    # Deterministic taxonomy detectors (grain/freshness/contracts/keys) over the same selection,
    # reading the manifest already on disk. A load failure is surfaced as a visible row, not a crash.
    try:
        _cat = args.catalog if args.catalog and args.catalog.exists() else None
        taxonomy_report = taxonomy.evaluate(
            load_node_facts(args.manifest, _cat), {str(f) for f in files}, strict=False, scope=scope,
            suppressions=Suppressions.load(config.PROJECT_ROOT),
        )
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        taxonomy_report = taxonomy.TaxonomyReport(scope, [], error=str(exc))

    # system-boundaries gates by DATA PRODUCT (selectors.yml), independent of the model-file selection,
    # so it runs over every product. Reuse the manifest already on disk (no re-parse). Catch resolution
    # failures so the aggregate still completes and the failure is rendered, not crashed (cf. doc-columns).
    try:
        graph = Graph.load(args.manifest)
        named_selectors = dataproducts.load_selector_names(args.selectors)
        facts = {n.unique_id: n for n in load_node_facts(args.manifest)}
        exposures = dataproducts.load_exposure_targets(args.manifest)
        sysbound_report = dataproducts.evaluate_system_boundaries(
            graph, named_selectors, node_facts=facts, exposure_targets=exposures
        )
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        sysbound_report = dataproducts.SystemBoundaryReport(scope="all data products", rows=[], error=str(exc))

    reports = [dep_report, lint_report, format_report, docs_report, columns_report,
               tests_report, taxonomy_report, sysbound_report]
    ok = all(r.ok for r in reports)

    # Optional Markdown summary file (a PR-comment body). The full per-check detail stays in the
    # human output / tool logs; this is just the at-a-glance table.
    md_path = getattr(args, "md_path", None)
    if md_path is not None:
        md_path.write_text(markdown_summary(reports, scope), encoding="utf-8")

    if args.as_json:
        payload = {"ok": ok, "scope": scope, "checks": {r.name: r.to_dict() for r in reports}}
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        log.info(style.dim(f"▸ {scope}"))
        for i, report in enumerate(reports):
            if i:
                log.info("")  # blank line separates each check section
            for level, line in report.human_lines(show_passes=args.show_passes):
                log.log(level, line)
            emit_tool_logs(report, show_logs=args.show_logs)
        log.info("")
        log.log(
            logging.INFO if ok else logging.ERROR,
            style.passed("all checks passed") if ok else style.failed("one or more checks failed"),
        )
    return 0 if ok else 1
