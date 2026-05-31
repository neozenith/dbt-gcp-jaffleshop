"""``check all`` — run every gate over one selection, aggregate, exit non-zero if any fail.

Resolves the model selection ONCE and the manifest ONCE, then fans the shared file list
out to all five checks (deprecations, lint, format, docs, tests) in check mode. The
combined ``--json`` payload is each check's ``to_dict()`` keyed by its name.
"""

# Standard Library
import json
import logging
import sys

# Local
from cicd_cli import config, selection
from cicd_cli.commands import coverage, deprecations, sqlfluff

log = logging.getLogger(__name__)


def cmd_all(args) -> int:
    cwd = config.PROJECT_ROOT
    sel = selection.from_args(args)
    scope = selection.describe(sel)
    files = selection.resolve_model_files(sel, cwd=cwd)

    dep_report = deprecations.run(files, scope=scope, fix=False, cwd=cwd)
    lint_report = sqlfluff.run("lint", files, fix=False, scope=scope, cwd=cwd)
    format_report = sqlfluff.run("format", files, fix=False, scope=scope, cwd=cwd)
    manifest = coverage.load_manifest(args.manifest, parse=args.parse, cwd=cwd)
    docs_report = coverage.evaluate_docs(manifest, files, scope=scope, require_columns=args.require_columns)
    tests_report = coverage.evaluate_tests(manifest, files, scope=scope)

    reports = [dep_report, lint_report, format_report, docs_report, tests_report]
    ok = all(r.ok for r in reports)

    if args.as_json:
        payload = {"ok": ok, "scope": scope, "checks": {r.name: r.to_dict() for r in reports}}
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        for report in reports:
            for level, line in report.human_lines():
                log.log(level, line)
        log.log(logging.INFO if ok else logging.ERROR,
                "✓ all checks passed" if ok else "✗ one or more checks failed")
    return 0 if ok else 1
