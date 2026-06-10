"""Result dataclasses for ``check docs`` / ``check doc-columns`` / ``check tests``."""

import logging
from dataclasses import dataclass
from typing import ClassVar

from adaf.utils import style

INFO = logging.INFO
ERROR = logging.ERROR


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
        return (
            "all documented" if self.ok else f"{sum(1 for r in self.rows if not r.ok)} model(s) missing a description"
        )

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


# ----------------------------------------------- columns (RESOLVED column descriptions)
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
                lines.append(
                    (
                        ERROR,
                        style.fail_item(
                            f"{r.path} — {r.ratio} columns documented; missing: {', '.join(r.undocumented_columns)}"
                        ),
                    )
                )
        return lines


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
