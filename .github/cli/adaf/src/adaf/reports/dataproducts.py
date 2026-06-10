"""Result dataclasses for ``products boundaries`` (descriptive) and ``check system-boundaries`` (gate).

``BoundaryReport`` is read-only classification; ``SystemBoundaryReport`` gates each boundary node on
its per-class artifacts (and surfaces inbound test suggestions). The evaluation logic that builds
these lives in ``adaf.commands.dataproducts``.
"""

import logging
from dataclasses import dataclass, field
from typing import ClassVar

from adaf.utils import style

INFO = logging.INFO
ERROR = logging.ERROR

# Display/sort order for the four classifications: boundary roles first (most interesting), interior
# last. Also the canonical key order in the JSON ``counts`` block.
CLASS_ORDER = ["inbound", "outbound", "both", "internal"]


# ─── products boundaries (descriptive) ───────────────────────────────────────


@dataclass
class MemberRow:
    """One classified node within a data product."""

    unique_id: str
    name: str
    resource_type: str
    classification: str  # inbound | outbound | both | internal
    external_parents: list[str]
    external_children: list[str]

    @property
    def is_boundary(self) -> bool:
        return self.classification != "internal"


@dataclass
class ProductBoundary:
    """A data product (named selector) with each of its data nodes classified."""

    product: str
    description: str
    rows: list[MemberRow]

    @property
    def counts(self) -> dict[str, int]:
        counts = {k: 0 for k in CLASS_ORDER}
        for row in self.rows:
            counts[row.classification] += 1
        return counts


@dataclass
class BoundaryReport:
    name: ClassVar[str] = "boundaries"
    products: list[ProductBoundary]
    scope: str

    @property
    def ok(self) -> bool:
        # Descriptive analysis — there is no gate yet, so it always "passes" (exit 0).
        return True

    def summary(self) -> str:
        if not self.products:
            return "no data products defined"
        boundary = sum(c for p in self.products for k, c in p.counts.items() if k != "internal")
        nodes = sum(len(p.rows) for p in self.products)
        return f"{boundary}/{nodes} boundary node(s) across {len(self.products)} data product(s)"

    def to_dict(self) -> dict:
        return {
            "analysis": self.name,
            "ok": self.ok,
            "scope": self.scope,
            "products": [
                {
                    "product": p.product,
                    "description": p.description,
                    "n_members": len(p.rows),
                    "counts": p.counts,
                    "nodes": [
                        {
                            "unique_id": r.unique_id,
                            "name": r.name,
                            "resource_type": r.resource_type,
                            "classification": r.classification,
                            "external_parents": r.external_parents,
                            "external_children": r.external_children,
                        }
                        for r in sorted(p.rows, key=_row_sort_key)
                    ],
                }
                for p in self.products
            ],
        }

    def human_lines(self, *, show_passes: bool = False) -> list[tuple[int, str]]:
        label = style.section("boundaries")
        if not self.products:
            return [(INFO, f"{label}  {style.dim('— no data products defined in selectors.yml')}")]
        lines: list[tuple[int, str]] = [
            (
                INFO,
                f"{label}  {style.bold(f'{len(self.products)} data product(s)')} "
                f"{style.dim('— system-boundary classification')}",
            )
        ]
        for p in self.products:
            counts = p.counts
            breakdown = ", ".join(f"{counts[k]} {k}" for k in CLASS_ORDER if counts[k])
            lines.append(
                (INFO, f"   {style.bold(style.cyan(p.product))} {style.dim(f'({len(p.rows)} node(s): {breakdown})')}")
            )
            shown = p.rows if show_passes else [r for r in p.rows if r.is_boundary]
            for r in sorted(shown, key=_row_sort_key):
                lines.append((INFO, style.boundary_item(r.classification, f"{r.name} ({r.resource_type}){_detail(r)}")))
            hidden = counts["internal"]
            if not show_passes and hidden:
                note = f"· {hidden} internal node(s) hidden — --show-passes to show"
                lines.append((INFO, f"      {style.dim(note)}"))
        return lines


def _row_sort_key(row: MemberRow) -> tuple[int, str]:
    """Boundary roles first (in CLASS_ORDER), then alphabetical by name."""
    return (CLASS_ORDER.index(row.classification), row.name)


def _detail(row: MemberRow) -> str:
    """A concise `← N ext parent(s) → M ext child(ren)` suffix, dimmed; empty for a clean root/leaf."""
    bits: list[str] = []
    if row.external_parents:
        bits.append(f"← {len(row.external_parents)} ext parent(s)")
    if row.external_children:
        bits.append(f"→ {len(row.external_children)} ext child(ren)")
    return f"  {style.dim(' '.join(bits))}" if bits else ""


# ─── check system-boundaries (gate) ──────────────────────────────────────────


@dataclass
class BoundaryTestRow:
    """One boundary node of a data product: its test count, the per-class artifacts it owes, and any
    deterministic test suggestions (advisory — for inbound nodes)."""

    product: str
    unique_id: str
    name: str
    resource_type: str
    classification: str  # inbound | outbound | both (internal nodes are not gated, so never here)
    test_count: int
    required: list[str] = field(default_factory=list)  # artifacts this boundary class owes
    missing: list[str] = field(default_factory=list)  # required artifacts that are absent
    suggestions: list[str] = field(default_factory=list)  # advisory deterministic test recommendations

    @property
    def ok(self) -> bool:
        return self.test_count > 0 and not self.missing

    @property
    def present(self) -> list[str]:
        return [a for a in self.required if a not in self.missing]


@dataclass
class SystemBoundaryReport:
    name: ClassVar[str] = "system-boundaries"
    scope: str
    rows: list[BoundaryTestRow]
    error: str | None = None  # set when membership couldn't be resolved (check-all keeps running)

    @property
    def ok(self) -> bool:
        return self.error is None and all(r.ok for r in self.rows)

    def summary(self) -> str:
        if self.error:
            return "could not resolve data products"
        if not self.rows:
            return "no boundary nodes"
        bad = sum(1 for r in self.rows if not r.ok)
        return (
            f"all {len(self.rows)} boundary node(s) satisfied" if self.ok else f"{bad} boundary node(s) under-protected"
        )

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "scope": self.scope,
            "error": self.error,
            "results": [vars(r) | {"ok": r.ok} for r in sorted(self.rows, key=_test_row_sort_key)],
        }

    def human_lines(self, *, show_passes: bool = False) -> list[tuple[int, str]]:
        label = style.section("system-boundaries")
        if self.error:
            return [(ERROR, f"{label}  {style.failed(self.error)}")]
        if not self.rows:
            return [(INFO, f"{label}  {style.dim('— no boundary nodes to gate')}")]
        if self.ok:
            lines: list[tuple[int, str]] = [
                (INFO, f"{label}  {style.passed(f'all {len(self.rows)} boundary node(s) satisfied')}")
            ]
        else:
            bad = sum(1 for r in self.rows if not r.ok)
            lines = [(ERROR, f"{label}  {style.failed(f'{bad} boundary node(s) under-protected')}")]
        # Group rows by product so each product's at-risk edge is clear. Failing rows always show;
        # passing rows that carry advisory suggestions show too (the suggestions are the point).
        shown = self.rows if show_passes else [r for r in self.rows if not r.ok or r.suggestions]
        for product in dict.fromkeys(r.product for r in self.rows):  # stable, definition order
            product_rows = [r for r in shown if r.product == product]
            if not product_rows:
                continue
            lines.append((INFO, f"   {style.bold(style.cyan(product))}"))
            for r in sorted(product_rows, key=_test_row_sort_key):
                desc = f"{r.name} ({r.resource_type}, {r.classification})"
                req = f" · needs: {', '.join(r.required)}" if r.required else ""
                if r.ok:
                    lines.append((INFO, style.pass_item(f"{desc} — {r.test_count} test(s){req}")))
                else:
                    gaps = []
                    if r.test_count == 0:
                        gaps.append("no tests")
                    if r.missing:
                        gaps.append("missing " + ", ".join(r.missing))
                    lines.append((ERROR, style.fail_item(f"{desc} — {'; '.join(gaps)}{req}")))
                for sug in r.suggestions:  # advisory, deterministic test recommendations
                    lines.append((INFO, f"      {style.dim(f'↳ suggest: {sug}')}"))
        return lines


def _test_row_sort_key(row: BoundaryTestRow) -> tuple[str, int, str]:
    """Group by product, then boundary role (CLASS_ORDER), then name."""
    return (row.product, CLASS_ORDER.index(row.classification), row.name)
