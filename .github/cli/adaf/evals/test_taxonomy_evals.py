"""DeepEval harness — evaluate ADAF's deterministic detectors against the intentionally-broken
dbt fixture (`dbt-jaffleshop`).

This is the agent-skill evaluation layer the goal calls for. Rather than an LLM judge (which would be
non-deterministic and need a key), the metrics here are **custom deterministic** DeepEval metrics:
they run the real `adaf check taxonomy` over the fixture and assert the known gaps are caught with the
right severity AND the right DAMA-UK6 attribution, that suppressions silence the right findings, and
that the review output contract injects the full rule enum. The fixture is the ground truth — these
goldens encode "what a correct review of these models looks like".

Run:  uv run --group eval pytest evals/ -p no:cacheprovider
The dbt fixture must stay broken for these to pass (that is the point); they make no changes.
"""

import json
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest
from deepeval import assert_test
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from adaf.rules import get_rule, review_response_format

REPO = Path(__file__).resolve().parents[4]
PROJECT = REPO / "dbt-jaffleshop"


@lru_cache(maxsize=1)
def taxonomy_output() -> str:
    """Run `adaf check taxonomy --all --json` over the fixture once; return raw JSON (the 'actual output')."""
    proc = subprocess.run(
        ["uv", "run", "--directory", str(PROJECT), "adaf", "check", "taxonomy", "--all", "--json"],
        capture_output=True, text=True, cwd=REPO,
    )
    if not proc.stdout.strip():
        raise RuntimeError(f"adaf produced no JSON. stderr:\n{proc.stderr}")
    return proc.stdout


def _case() -> LLMTestCase:
    return LLMTestCase(input="adaf check taxonomy --all", actual_output=taxonomy_output())


# ─── custom deterministic metrics ────────────────────────────────────────────


class GapDetected(BaseMetric):
    """Pass iff a MISSING finding for (rule_code, node) exists with the expected severity."""

    def __init__(self, rule_code: str, node: str, severity: str):
        self.rule_code, self.node, self.severity, self.threshold = rule_code, node, severity, 1.0
        self.evaluation_cost = 0

    def measure(self, test_case: LLMTestCase) -> float:
        data = json.loads(test_case.actual_output)
        hit = any(
            r["rule_code"] == self.rule_code and r["node"] == self.node
            and r["status"] == "missing" and r["severity"] == self.severity
            for r in data["results"]
        )
        self.score = 1.0 if hit else 0.0
        self.success = hit
        self.reason = f"{self.rule_code} on {self.node} ({self.severity}) {'detected' if hit else 'NOT detected'}"
        return self.score

    async def a_measure(self, test_case: LLMTestCase) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.success

    @property
    def __name__(self):
        return f"GapDetected[{self.rule_code}/{self.node}/{self.severity}]"


class Suppressed(BaseMetric):
    """Pass iff (rule_code, node) is recorded as suppressed and NOT present as an active finding."""

    def __init__(self, rule_code: str, node: str):
        self.rule_code, self.node, self.threshold = rule_code, node, 1.0
        self.evaluation_cost = 0

    def measure(self, test_case: LLMTestCase) -> float:
        data = json.loads(test_case.actual_output)
        in_suppressed = any(s["rule_code"] == self.rule_code and s["node"] == self.node for s in data["suppressed"])
        in_findings = any(r["rule_code"] == self.rule_code and r["node"] == self.node for r in data["results"])
        ok = in_suppressed and not in_findings
        self.score, self.success = (1.0 if ok else 0.0), ok
        self.reason = f"{self.rule_code}/{self.node}: suppressed={in_suppressed}, leaked_into_findings={in_findings}"
        return self.score

    async def a_measure(self, test_case: LLMTestCase) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.success

    @property
    def __name__(self):
        return f"Suppressed[{self.rule_code}/{self.node}]"


class CorrectDamaAttribution(BaseMetric):
    """Pass iff the catalogue attributes `rule_code` to the expected DAMA-UK6 dimension."""

    def __init__(self, rule_code: str, expected_dama: str):
        self.rule_code, self.expected_dama, self.threshold = rule_code, expected_dama, 1.0
        self.evaluation_cost = 0

    def measure(self, test_case: LLMTestCase) -> float:
        rule = get_rule(self.rule_code) or {}
        ok = self.expected_dama in rule.get("dama", [])
        self.score, self.success = (1.0 if ok else 0.0), ok
        self.reason = f"{self.rule_code} dama={rule.get('dama')} (expected to include {self.expected_dama})"
        return self.score

    async def a_measure(self, test_case: LLMTestCase) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.success

    @property
    def __name__(self):
        return f"CorrectDamaAttribution[{self.rule_code}={self.expected_dama}]"


# ─── golden cases ─────────────────────────────────────────────────────────────

# Known blocker gaps in the broken fixture (rule, node, severity).
_GAP_GOLDENS = [
    ("MD-01", "products", "blocker"),
    ("MD-01", "supplies", "blocker"),
    ("MD-01", "locations", "blocker"),
    ("TM-AU-01", "raw_customers", "blocker"),
    ("TM-AU-01", "raw_orders", "blocker"),
    ("TM-AU-01", "raw_supplies", "blocker"),
    ("MD-02", "products", "warning"),
]

# Expected DAMA-UK6 attribution per rule (the catalogue is the source of truth).
_DAMA_GOLDENS = [("MD-01", "Uniqueness"), ("TM-AU-01", "Timeliness"), ("MD-02", "Validity"), ("EN-03", "Consistency")]


@pytest.mark.parametrize(("rule", "node", "severity"), _GAP_GOLDENS)
def test_known_gap_is_detected(rule, node, severity):
    assert_test(_case(), [GapDetected(rule, node, severity)])


@pytest.mark.parametrize(("rule", "node"), [("MD-01", "metricflow_time_spine"), ("MD-02", "metricflow_time_spine")])
def test_suppressed_false_positive_is_silenced(rule, node):
    assert_test(_case(), [Suppressed(rule, node)])


@pytest.mark.parametrize(("rule", "dama"), _DAMA_GOLDENS)
def test_finding_has_correct_dama_attribution(rule, dama):
    assert_test(_case(), [CorrectDamaAttribution(rule, dama)])


def test_review_output_schema_injects_full_rule_enum():
    enum = review_response_format()["json_schema"]["schema"]["properties"]["models"]["items"]["properties"][
        "findings"
    ]["items"]["properties"]["rule_code"]["enum"]
    assert len(enum) == 33  # the LLM can only emit catalogue codes — no drift
