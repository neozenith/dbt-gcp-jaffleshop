"""``check docs`` and ``check tests`` — documentation & test coverage of selected models.

Both join the selected model files against dbt's manifest:

* **docs**  — a model passes if it has a non-empty ``description`` and (by default) every
  column declared in its YAML is described. ``--no-columns`` relaxes to model-level only.
* **tests** — a model passes if at least one test node depends on it.

A selected model file that is absent from the manifest fails loudly (it usually means
the manifest is stale — re-run ``dbt parse`` or pass ``--parse``).

These checks have no ``--fix``: descriptions and tests cannot be synthesised automatically.

Note on the column check: the manifest only knows about columns DECLARED in YAML, so
this verifies described-vs-declared, not described-vs-actual-warehouse-columns. The
latter needs ``catalog.json`` and can be layered on later.
"""

# Standard Library
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

# Local
from cicd_cli import config, selection, style
from cicd_cli.catalog import Catalog
from cicd_cli.formatting import render_from_args
from cicd_cli.manifest import Manifest

log = logging.getLogger(__name__)

INFO = logging.INFO
ERROR = logging.ERROR


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


# --------------------------------------------------------- docs (model descriptions)
@dataclass
class DocsRow:
    path: str
    name: str | None
    in_manifest: bool
    has_description: bool

    @property
    def ok(self) -> bool:
        return self.in_manifest and self.has_description


@dataclass
class DocsReport:
    name: ClassVar[str] = "docs"
    scope: str
    rows: list[DocsRow]

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.rows)

    def summary(self) -> str:
        if not self.rows:
            return "nothing to check"
        return "all documented" if self.ok else f"{sum(1 for r in self.rows if not r.ok)} model(s) missing a description"

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "scope": self.scope,
            "results": [vars(r) | {"ok": r.ok} for r in self.rows],
        }

    def human_lines(self, *, show_passes: bool = False) -> list[tuple[int, str]]:
        label = style.section("docs")
        if not self.rows:
            return [(INFO, f"{label}  {style.dim('— nothing to check')}")]
        shown = self.rows if show_passes else [r for r in self.rows if not r.ok]
        if self.ok:
            lines: list[tuple[int, str]] = [(INFO, f"{label}  {style.passed('all selected models have descriptions')}")]
        else:
            lines = [(ERROR, f"{label}  {style.failed('model description gaps found')}")]
        for r in shown:
            if r.ok:
                lines.append((INFO, style.pass_item(r.path)))
            elif not r.in_manifest:
                lines.append((ERROR, style.fail_item(f"{r.path} — not in manifest (run `dbt parse`?)")))
            else:
                lines.append((ERROR, style.fail_item(f"{r.path} — model '{r.name}' has no description")))
        return lines


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


# ----------------------------------------------- columns (RESOLVED column descriptions)
# Denominator is the model's ACTUAL columns (from catalog.json / `dbt docs generate`), not the
# YAML-declared subset — a column that exists in the warehouse but is absent from YAML is
# undocumented. A column counts as documented if it's declared in the manifest with a non-empty
# description (matched case-insensitively against the catalog's column name).
@dataclass
class ColumnsRow:
    path: str
    name: str | None
    in_manifest: bool
    in_catalog: bool
    documented: int
    total: int  # actual (resolved) columns
    undocumented_columns: list[str]

    @property
    def ok(self) -> bool:
        return self.in_manifest and self.in_catalog and not self.undocumented_columns

    @property
    def ratio(self) -> str:
        return f"{self.documented}/{self.total}"


@dataclass
class ColumnsReport:
    name: ClassVar[str] = "doc-columns"
    scope: str
    rows: list[ColumnsRow]
    error: str | None = None  # set when the catalog couldn't be loaded (check-all keeps running)

    @property
    def ok(self) -> bool:
        return self.error is None and all(r.ok for r in self.rows)

    def summary(self) -> str:
        if self.error:
            return "catalog missing"
        if not self.rows:
            return "nothing to check"
        uncatalogued = sum(1 for r in self.rows if r.in_manifest and not r.in_catalog)
        if uncatalogued == len(self.rows):
            return f"{uncatalogued} model(s) not in catalog — build first"
        return f"{sum(r.documented for r in self.rows)}/{sum(r.total for r in self.rows)} columns documented"

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "scope": self.scope,
            "error": self.error,
            "results": [vars(r) | {"ok": r.ok} for r in self.rows],
        }

    def human_lines(self, *, show_passes: bool = False) -> list[tuple[int, str]]:
        label = style.section("doc-columns")
        if self.error:
            return [(ERROR, f"{label}  {style.failed(self.error)}")]
        if not self.rows:
            return [(INFO, f"{label}  {style.dim('— nothing to check')}")]
        shown = self.rows if show_passes else [r for r in self.rows if not r.ok]
        summary = f"{sum(r.documented for r in self.rows)}/{sum(r.total for r in self.rows)} columns documented"
        if self.ok:
            lines: list[tuple[int, str]] = [
                (INFO, f"{label}  {style.passed('all resolved columns documented')} {style.dim(f'({summary})')}")
            ]
        else:
            lines = [(ERROR, f"{label}  {style.failed(f'column documentation gaps — {summary}')}")]
        for r in shown:
            if not r.in_manifest:
                lines.append((ERROR, style.fail_item(f"{r.path} — not in manifest (run `dbt parse`?)")))
            elif not r.in_catalog:
                lines.append((ERROR, style.fail_item(f"{r.path} — not in catalog (run `dbt docs generate`?)")))
            elif r.ok:
                detail = "no columns" if r.total == 0 else f"{r.ratio} columns documented"
                lines.append((INFO, style.pass_item(f"{r.path} ({detail})")))
            else:
                lines.append((ERROR, style.fail_item(
                    f"{r.path} — {r.ratio} columns documented; missing: {', '.join(r.undocumented_columns)}")))
        return lines


def evaluate_columns(manifest: Manifest, catalog: Catalog, files: list[Path], *, scope: str) -> ColumnsReport:
    by_path = manifest.by_path()
    rows: list[ColumnsRow] = []
    for f in files:
        key = str(f)
        model = by_path.get(key)
        if model is None:
            rows.append(ColumnsRow(key, None, in_manifest=False, in_catalog=False, documented=0, total=0, undocumented_columns=[]))
            continue
        actual = catalog.columns_for(model.unique_id)
        if actual is None:
            rows.append(ColumnsRow(key, model.name, in_manifest=True, in_catalog=False, documented=0, total=0, undocumented_columns=[]))
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


# -------------------------------------------------------------------------- tests
@dataclass
class TestsRow:
    path: str
    name: str | None
    in_manifest: bool
    test_count: int

    @property
    def ok(self) -> bool:
        return self.in_manifest and self.test_count > 0


@dataclass
class TestsReport:
    name: ClassVar[str] = "tests"
    scope: str
    rows: list[TestsRow]

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.rows)

    def summary(self) -> str:
        if not self.rows:
            return "nothing to check"
        return "all tested" if self.ok else f"{sum(1 for r in self.rows if not r.ok)} model(s) untested"

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "scope": self.scope,
            "results": [vars(r) | {"ok": r.ok} for r in self.rows],
        }

    def human_lines(self, *, show_passes: bool = False) -> list[tuple[int, str]]:
        label = style.section("tests")
        if not self.rows:
            return [(INFO, f"{label}  {style.dim('— nothing to check')}")]
        shown = self.rows if show_passes else [r for r in self.rows if not r.ok]
        if self.ok:
            lines: list[tuple[int, str]] = [(INFO, f"{label}  {style.passed('all selected models tested')}")]
        else:
            lines = [(ERROR, f"{label}  {style.failed('test gaps found')}")]
        for r in shown:
            if r.ok:
                lines.append((INFO, style.pass_item(f"{r.path} ({r.test_count} test(s))")))
            elif not r.in_manifest:
                lines.append((ERROR, style.fail_item(f"{r.path} — not in manifest (run `dbt parse`?)")))
            else:
                lines.append((ERROR, style.fail_item(f"{r.path} — model '{r.name}' has no tests")))
        return lines


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
