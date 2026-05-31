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
from cicd_cli import config, selection
from cicd_cli.formatting import render
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


# --------------------------------------------------------------------------- docs
@dataclass
class DocsRow:
    path: str
    name: str | None
    in_manifest: bool
    has_description: bool
    undocumented_columns: list[str]

    @property
    def ok(self) -> bool:
        return self.in_manifest and self.has_description and not self.undocumented_columns


@dataclass
class DocsReport:
    name: ClassVar[str] = "docs"
    scope: str
    rows: list[DocsRow]

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.rows)

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "scope": self.scope,
            "results": [vars(r) | {"ok": r.ok} for r in self.rows],
        }

    def human_lines(self) -> list[tuple[int, str]]:
        if not self.rows:
            return [(INFO, f"docs: no models to check ({self.scope}) — nothing to do.")]
        lines: list[tuple[int, str]] = [(INFO, f"docs coverage — {self.scope}:")]
        for r in self.rows:
            if r.ok:
                lines.append((INFO, f"  ✓ {r.path}"))
            elif not r.in_manifest:
                lines.append((ERROR, f"  ✗ {r.path} — not in manifest (run `dbt parse`?)"))
            elif not r.has_description:
                lines.append((ERROR, f"  ✗ {r.path} — model '{r.name}' has no description"))
            else:
                lines.append((ERROR, f"  ✗ {r.path} — undocumented columns: {', '.join(r.undocumented_columns)}"))
        lines.append((INFO if self.ok else ERROR,
                      "✓ all selected models documented" if self.ok else "✗ documentation gaps found"))
        return lines


def evaluate_docs(manifest: Manifest, files: list[Path], *, scope: str, require_columns: bool = True) -> DocsReport:
    by_path = manifest.by_path()
    rows: list[DocsRow] = []
    for f in files:
        key = str(f)
        model = by_path.get(key)
        if model is None:
            rows.append(DocsRow(key, None, in_manifest=False, has_description=False, undocumented_columns=[]))
            continue
        undocumented = (
            [name for name, desc in model.columns.items() if not desc.strip()] if require_columns else []
        )
        rows.append(
            DocsRow(
                path=key,
                name=model.name,
                in_manifest=True,
                has_description=bool(model.description.strip()),
                undocumented_columns=undocumented,
            )
        )
    return DocsReport(scope, rows)


def cmd_docs(args) -> int:
    sel = selection.from_args(args)
    files = selection.resolve_model_files(sel)
    manifest = load_manifest(args.manifest, parse=args.parse)
    report = evaluate_docs(manifest, files, scope=selection.describe(sel), require_columns=args.require_columns)
    return render(report, as_json=args.as_json)


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

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "scope": self.scope,
            "results": [vars(r) | {"ok": r.ok} for r in self.rows],
        }

    def human_lines(self) -> list[tuple[int, str]]:
        if not self.rows:
            return [(INFO, f"tests: no models to check ({self.scope}) — nothing to do.")]
        lines: list[tuple[int, str]] = [(INFO, f"test coverage — {self.scope}:")]
        for r in self.rows:
            if r.ok:
                lines.append((INFO, f"  ✓ {r.path} ({r.test_count} test(s))"))
            elif not r.in_manifest:
                lines.append((ERROR, f"  ✗ {r.path} — not in manifest (run `dbt parse`?)"))
            else:
                lines.append((ERROR, f"  ✗ {r.path} — model '{r.name}' has no tests"))
        lines.append((INFO if self.ok else ERROR,
                      "✓ all selected models tested" if self.ok else "✗ test gaps found"))
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
    return render(report, as_json=args.as_json)
