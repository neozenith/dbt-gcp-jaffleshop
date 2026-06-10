"""``check docs`` / ``check doc-columns`` / ``check tests`` — coverage of selected models.

Both join the selected model files against dbt's manifest:

* **docs**  — a model passes if it has a non-empty ``description`` and every column declared in its
  YAML is described.
* **doc-columns** — denominator is the model's ACTUAL columns (``catalog.json``); a column counts as
  documented if its manifest description is non-empty.
* **tests** — a model passes if at least one test node depends on it.

A selected model file absent from the manifest fails loudly (stale manifest — re-run ``dbt parse``).
The result dataclasses live in ``adaf.reports.coverage`` (re-exported here for back-compat).
"""

# Standard Library
import logging
import subprocess
from pathlib import Path

# Local
from adaf import config
from adaf.dbt import selection
from adaf.dbt.catalog import Catalog
from adaf.dbt.manifest import Manifest
from adaf.reports.coverage import ColumnsReport, ColumnsRow, DocsReport, DocsRow, TestsReport, TestsRow
from adaf.utils.formatting import render_from_args

log = logging.getLogger(__name__)

__all__ = [
    "ColumnsReport",
    "ColumnsRow",
    "DocsReport",
    "DocsRow",
    "TestsReport",
    "TestsRow",
    "load_manifest",
    "dbt_docs_generate",
    "load_catalog",
    "evaluate_docs",
    "evaluate_columns",
    "evaluate_tests",
    "cmd_docs",
    "cmd_columns",
    "cmd_tests",
]


def load_manifest(path: Path, *, parse: bool = False, cwd: Path | None = None) -> Manifest:
    """Load the manifest, optionally refreshing it first via ``dbt parse`` (fail loud)."""
    cwd = cwd or config.PROJECT_ROOT
    if parse:
        proc = subprocess.run(["dbt", "parse"], cwd=cwd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"`dbt parse` failed (exit {proc.returncode}):\n{proc.stderr or proc.stdout}")
    if not Path(path).exists():
        raise FileNotFoundError(f"dbt manifest not found at '{path}'. Run `dbt parse` or pass --parse.")
    return Manifest.load(path)


def dbt_docs_generate(cwd: Path | None = None) -> None:
    """Run ``dbt docs generate`` to (re)build manifest.json + catalog.json (needs a warehouse)."""
    cwd = cwd or config.PROJECT_ROOT
    proc = subprocess.run(["dbt", "docs", "generate"], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"`dbt docs generate` failed (exit {proc.returncode}):\n{proc.stderr or proc.stdout}")


def load_catalog(path: Path) -> Catalog:
    """Load catalog.json (the resolved warehouse columns); fail loud if it isn't there."""
    if not Path(path).exists():
        raise FileNotFoundError(
            f"dbt catalog not found at '{path}'. Run `dbt docs generate` (needs a warehouse build) or pass --docs-generate."
        )
    return Catalog.load(path)


def evaluate_docs(manifest: Manifest, files: list[Path], *, scope: str) -> DocsReport:
    by_path = manifest.by_path()
    rows: list[DocsRow] = []
    for f in files:
        key = str(f)
        model = by_path.get(key)
        if model is None:
            rows.append(DocsRow(key, None, in_manifest=False, has_description=False))
        else:
            rows.append(DocsRow(key, model.name, in_manifest=True, has_description=bool(model.description.strip())))
    return DocsReport(scope, rows)


def cmd_docs(args) -> int:
    sel = selection.from_args(args)
    files = selection.resolve_model_files(sel)
    manifest = load_manifest(args.manifest, parse=args.parse)
    report = evaluate_docs(manifest, files, scope=selection.describe(sel))
    return render_from_args(report, args)


def evaluate_columns(manifest: Manifest, catalog: Catalog, files: list[Path], *, scope: str) -> ColumnsReport:
    by_path = manifest.by_path()
    rows: list[ColumnsRow] = []
    for f in files:
        key = str(f)
        model = by_path.get(key)
        if model is None:
            rows.append(
                ColumnsRow(
                    key, None, in_manifest=False, in_catalog=False, documented=0, total=0, undocumented_columns=[]
                )
            )
            continue
        actual = catalog.columns_for(model.unique_id)
        if actual is None:
            rows.append(
                ColumnsRow(
                    key, model.name, in_manifest=True, in_catalog=False, documented=0, total=0, undocumented_columns=[]
                )
            )
            continue
        described = {name.lower() for name, desc in model.columns.items() if desc.strip()}
        undocumented = [col for col in actual if col.lower() not in described]
        rows.append(
            ColumnsRow(
                key,
                model.name,
                in_manifest=True,
                in_catalog=True,
                documented=len(actual) - len(undocumented),
                total=len(actual),
                undocumented_columns=undocumented,
            )
        )
    return ColumnsReport(scope, rows)


def cmd_columns(args) -> int:
    sel = selection.from_args(args)
    files = selection.resolve_model_files(sel)
    if args.docs_generate:
        dbt_docs_generate(config.PROJECT_ROOT)
    manifest = load_manifest(args.manifest, parse=args.parse)
    catalog = load_catalog(args.catalog)  # fail loud if absent — no silent declared-only fallback
    report = evaluate_columns(manifest, catalog, files, scope=selection.describe(sel))
    return render_from_args(report, args)


def evaluate_tests(manifest: Manifest, files: list[Path], *, scope: str) -> TestsReport:
    by_path = manifest.by_path()
    rows: list[TestsRow] = []
    for f in files:
        key = str(f)
        model = by_path.get(key)
        if model is None:
            rows.append(TestsRow(key, None, in_manifest=False, test_count=0))
        else:
            rows.append(TestsRow(key, model.name, in_manifest=True, test_count=model.test_count))
    return TestsReport(scope, rows)


def cmd_tests(args) -> int:
    sel = selection.from_args(args)
    files = selection.resolve_model_files(sel)
    manifest = load_manifest(args.manifest, parse=args.parse)
    report = evaluate_tests(manifest, files, scope=selection.describe(sel))
    return render_from_args(report, args)
