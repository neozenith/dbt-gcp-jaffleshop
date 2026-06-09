"""Result dataclasses for ``check taxonomy`` — the deterministic detector findings + report."""

import logging
from dataclasses import dataclass, field
from typing import ClassVar

from adaf.taxonomy import MISSING
from adaf.utils import style

INFO = logging.INFO
ERROR = logging.ERROR


@dataclass
class TaxonomyFinding:
    node: str
    resource_type: str
    rule_code: str
    detection: str
    severity: str  # blocker | warning
    status: str  # present | missing
    detail: str

    @property
    def ok(self) -> bool:
        return self.status != MISSING

    @property
    def fails_gate(self) -> bool:
        """A blocker miss always fails; a warning miss fails only under --strict (set by the report)."""
        return self.status == MISSING and self.severity == "blocker"


@dataclass
class SuppressedFinding:
    node: str
    rule_code: str
    reason: str


@dataclass
class TaxonomyReport:
    name: ClassVar[str] = "taxonomy"
    scope: str
    findings: list[TaxonomyFinding]
    strict: bool = False
    error: str | None = None
    suppressed: list[SuppressedFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        if self.error is not None:
            return False
        return not any(self._is_failure(f) for f in self.findings)

    def _is_failure(self, f: TaxonomyFinding) -> bool:
        if f.status != MISSING:
            return False
        return f.severity == "blocker" or self.strict

    def summary(self) -> str:
        if self.error:
            return "could not load manifest"
        suffix = f" ({len(self.suppressed)} suppressed)" if self.suppressed else ""
        if not self.findings:
            return "nothing to check" + suffix
        blockers = sum(1 for f in self.findings if f.status == MISSING and f.severity == "blocker")
        warns = sum(1 for f in self.findings if f.status == MISSING and f.severity == "warning")
        if not blockers and not warns:
            return "all detected rules satisfied" + suffix
        bits = []
        if blockers:
            bits.append(f"{blockers} blocker(s)")
        if warns:
            bits.append(f"{warns} warning(s)")
        return " + ".join(bits) + " across deterministic detectors" + suffix

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "scope": self.scope,
            "strict": self.strict,
            "error": self.error,
            "suppressed": [{"node": s.node, "rule_code": s.rule_code, "reason": s.reason} for s in self.suppressed],
            "results": [
                {
                    "node": f.node,
                    "resource_type": f.resource_type,
                    "rule_code": f.rule_code,
                    "detection": f.detection,
                    "severity": f.severity,
                    "status": f.status,
                    "detail": f.detail,
                    "ok": f.ok,
                }
                for f in sorted(self.findings, key=_sort_key)
            ],
        }

    def human_lines(self, *, show_passes: bool = False) -> list[tuple[int, str]]:
        label = style.section("taxonomy")
        if self.error:
            return [(ERROR, f"{label}  {style.failed(self.error)}")]
        if not self.findings:
            return [(INFO, f"{label}  {style.dim('— nothing to check')}")]
        if self.ok:
            lines: list[tuple[int, str]] = [(INFO, f"{label}  {style.passed(self.summary())}")]
        else:
            lines = [(ERROR, f"{label}  {style.failed(self.summary())}")]
        shown = self.findings if show_passes else [f for f in self.findings if f.status == MISSING]
        for f in sorted(shown, key=_sort_key):
            text = f"{f.node} ({f.resource_type}) · {f.rule_code} — {f.detail}"
            if f.status != MISSING:
                lines.append((INFO, style.pass_item(text)))
            elif f.severity == "blocker":
                lines.append((ERROR, style.fail_item(f"{text}  [blocker]")))
            else:
                level = ERROR if self.strict else INFO
                lines.append(
                    (level, style.fail_item(f"{text}  [warning — disable with: -- adaf-disable: {f.rule_code}]"))
                )
        if self.suppressed and show_passes:
            lines.append((INFO, style.dim(f"   {len(self.suppressed)} suppressed:")))
            for s in self.suppressed:
                lines.append((INFO, style.dim(f"     ➖ {s.node} · {s.rule_code} — {s.reason}")))
        return lines


def _sort_key(f: TaxonomyFinding) -> tuple:
    # blockers first, then warnings, then passes; then node, then rule code.
    rank = {"blocker": 0, "warning": 1}.get(f.severity, 2) if f.status == MISSING else 3
    return (rank, f.node, f.rule_code)
