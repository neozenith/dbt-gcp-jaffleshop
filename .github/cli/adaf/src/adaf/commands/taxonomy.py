"""``check taxonomy`` — run the deterministic catalogue detectors over the selected models.

Bridges the catalogue's ``detection`` field to runtime: for each rule with a registered detector
(``adaf.taxonomy.DETECTORS``), evaluate every in-scope node and report present / missing. Severity
comes from the catalogue — ``deterministic`` rules are **blockers** (a miss fails the gate),
``hybrid`` rules are advisory **warnings** (suppressible; the LLM ``review`` adjudicates the rest).

Scope: the SELECTED models (changed-only by default), PLUS every source (source-freshness, TM-AU-01,
is global hygiene and has no changed-file notion). ``--strict`` promotes warnings to failures.
"""

import logging
from argparse import Namespace
from dataclasses import dataclass, field
from typing import ClassVar

from adaf import config, selection, style
from adaf.formatting import render_from_args
from adaf.rules import get_rule
from adaf.suppression import Suppressions
from adaf.taxonomy import DETECTORS, MISSING, NOT_APPLICABLE, NodeFacts, load_node_facts

log = logging.getLogger(__name__)

INFO = logging.INFO
ERROR = logging.ERROR

# Map the catalogue's detection mode to a finding severity.
_SEVERITY = {"deterministic": "blocker", "hybrid": "warning"}


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
                lines.append((level, style.fail_item(f"{text}  [warning — disable with: -- adaf-disable: {f.rule_code}]")))
        if self.suppressed and show_passes:
            lines.append((INFO, style.dim(f"   {len(self.suppressed)} suppressed:")))
            for s in self.suppressed:
                lines.append((INFO, style.dim(f"     ➖ {s.node} · {s.rule_code} — {s.reason}")))
        return lines


def _sort_key(f: TaxonomyFinding) -> tuple:
    # blockers first, then warnings, then passes; then node, then rule code.
    rank = {"blocker": 0, "warning": 1}.get(f.severity, 2) if f.status == MISSING else 3
    return (rank, f.node, f.rule_code)


def evaluate(
    nodes: list[NodeFacts],
    in_scope_models: set[str],
    *,
    strict: bool,
    scope: str,
    suppressions: Suppressions | None = None,
) -> TaxonomyReport:
    """Run every registered detector over each in-scope node, producing one finding per (node, rule).

    A finding whose (rule, file) is suppressed (``adaf.yml`` glob or inline ``-- adaf-disable``) is
    dropped from ``findings`` and recorded under ``suppressed`` instead — so a silenced rule can
    never fail the gate, but the opt-out stays auditable.
    """
    findings: list[TaxonomyFinding] = []
    suppressed: list[SuppressedFinding] = []
    for n in nodes:
        # Models are gated only when selected; sources are always in scope (freshness is global).
        if n.resource_type == "model" and n.original_file_path not in in_scope_models:
            continue
        for code, detector in DETECTORS.items():
            result = detector(n)
            if result is None:
                continue  # the rule's role doesn't apply to this node
            status, detail = result
            if status == NOT_APPLICABLE:
                continue
            reason = suppressions.reason_for(code, n.original_file_path) if suppressions else None
            if reason is not None:
                if status == MISSING:  # only a would-be gap is worth recording as suppressed
                    suppressed.append(SuppressedFinding(n.name, code, reason))
                continue
            detection = (get_rule(code) or {}).get("detection", "hybrid")
            findings.append(
                TaxonomyFinding(n.name, n.resource_type, code, detection, _SEVERITY.get(detection, "warning"), status, detail)
            )
    return TaxonomyReport(scope, findings, strict=strict, suppressed=suppressed)


def build_report(args: Namespace) -> TaxonomyReport:
    """Resolve selection + manifest, then evaluate. Shared by the subcommand and `check all`."""
    sel = selection.from_args(args)
    files = selection.resolve_model_files(sel)
    in_scope = {str(f) for f in files}
    manifest = config.under_root(args.manifest)
    if manifest is None or not manifest.exists():
        return TaxonomyReport(
            selection.describe(sel),
            [],
            strict=getattr(args, "strict", False),
            error=f"dbt manifest not found at '{manifest}'. Run `dbt parse` or pass --parse.",
        )
    catalog = config.under_root(getattr(args, "catalog", None))
    nodes = load_node_facts(manifest, catalog if catalog and catalog.exists() else None)
    suppressions = Suppressions.load(config.PROJECT_ROOT)
    return evaluate(
        nodes, in_scope, strict=getattr(args, "strict", False), scope=selection.describe(sel), suppressions=suppressions
    )


def cmd(args: Namespace) -> int:
    return render_from_args(build_report(args), args)
