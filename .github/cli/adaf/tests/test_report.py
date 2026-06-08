"""The report generator emits findings purely from the detectors — deterministic, no hand-authoring."""

from adaf.commands import report
from adaf.suppression import CONFIG_NAME, Suppressions
from adaf.taxonomy import DETECTORS, NodeFacts


def _model(name, layer, columns, contract=False, tests=None):
    from adaf.taxonomy import AttachedTest  # noqa: PLC0415 - test-local construction helper
    return NodeFacts(f"model.p.{name}", name, "model", f"models/{layer}/{name}.sql", layer, columns,
                     contract, False, tests or [AttachedTest("unique_combination_of_columns", "dbt_utils", None)])


def test_report_is_deterministic(tmp_path):
    nodes = [_model("orders", "marts", ["order_id"])]
    s = Suppressions.load(tmp_path)
    a = report.build_markdown(nodes, {"models/marts/orders.sql"}, s, "x")
    b = report.build_markdown(nodes, {"models/marts/orders.sql"}, s, "x")
    assert a == b  # same input → byte-identical output (nothing random / hand-authored)


def test_every_detector_appears_as_a_row(tmp_path):
    md = report.build_markdown([_model("orders", "marts", ["order_id"])], {"models/marts/orders.sql"},
                               Suppressions.load(tmp_path), "x")
    for code in DETECTORS:
        assert f"`{code}`" in md


def test_pass_and_blocker_render_from_facts(tmp_path):
    # A mart with a grain test passes MD-01; lacking a contract it warns MD-02 — both straight from facts.
    md = report.build_markdown([_model("orders", "marts", ["order_id"])], {"models/marts/orders.sql"},
                               Suppressions.load(tmp_path), "x")
    assert "✅ pass" in md and "has a uniqueness/grain test" in md
    assert "mart has no enforced contract" in md


def test_suppressed_finding_is_marked(tmp_path):
    (tmp_path / CONFIG_NAME).write_text(
        "disable:\n  - rules: [MD-01]\n    paths: ['models/marts/spine.sql']\n    reason: synthetic\n", encoding="utf-8")
    node = NodeFacts("model.p.spine", "spine", "model", "models/marts/spine.sql", "marts", [], False, False, [])
    md = report.build_markdown([node], {"models/marts/spine.sql"}, Suppressions.load(tmp_path), "x")
    assert "🟡 suppressed" in md and "synthetic" in md
