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


def test_llm_index_maps_statuses():
    review = {"result": {"models": [{"model": "orders", "findings": [
        {"rule_code": "MD-01", "status": "applicable_present"},
        {"rule_code": "EN-03", "status": "applicable_missing"},
        {"rule_code": "MS-05", "status": "not_applicable"},
    ]}]}}
    idx = report.llm_index(review)
    assert idx["orders"] == {"MD-01": "present", "EN-03": "gap", "MS-05": "n/a"}


def test_flag_detects_false_positive_and_negative():
    assert "FALSE POSITIVE" in report._flag("pass", "gap")   # LLM flagged a gap that's covered
    assert "FALSE NEGATIVE" in report._flag("gap", "present")  # LLM missed a real gap
    assert report._flag("pass", "present").startswith("✅")
    assert report._flag("gap", "gap").startswith("✅")
    assert report._flag("n/a", "present").startswith("🟠")     # applicability disagreement
    assert report._flag("no-detector", "gap").startswith("⚪")  # unverified


def test_reconciliation_section_renders_when_review_given(tmp_path):
    node = NodeFacts("model.p.products", "products", "model", "models/marts/products.sql", "marts",
                     [], False, False, [], {"product_id": "STRING"})
    review = {"result": {"models": [{"model": "products",
                                     "findings": [{"rule_code": "EN-01", "status": "applicable_present"}]}]}}
    md = report.build_markdown([node], {"models/marts/products.sql"}, Suppressions.load(tmp_path), "x", review)
    # products PK product_id has no tests → EN-01 gap; LLM said present → false negative on the worklist.
    assert "FALSE NEGATIVE" in md and "LLM reconciliation" in md
