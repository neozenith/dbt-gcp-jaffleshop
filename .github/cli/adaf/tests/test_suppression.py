"""Tests for the layered suppression engine — real files under tmp_path, no mocks.

Covers config-glob matching, inline-comment parsing, the config-then-inline precedence, and the
taxonomy integration (a suppressed gap is dropped from findings and recorded as suppressed).
"""

from adaf.commands import taxonomy as tax_cmd
from adaf.suppression import CONFIG_NAME, SuppressionRule, Suppressions, disable_help
from adaf.taxonomy import NodeFacts


def _node(name="products", path="models/marts/products.sql") -> NodeFacts:
    return NodeFacts(f"model.p.{name}", name, "model", path, "marts", ["product_id"], False, False)


def test_config_rule_matches_code_and_glob() -> None:
    rule = SuppressionRule(frozenset({"MD-02"}), ("models/marts/**",), "legacy")
    assert rule.matches("MD-02", "models/marts/x.sql") is True
    assert rule.matches("MD-01", "models/marts/x.sql") is False  # wrong code
    assert rule.matches("MD-02", "models/staging/x.sql") is False  # wrong path


def test_load_reads_adaf_yml(tmp_path) -> None:
    (tmp_path / CONFIG_NAME).write_text(
        "disable:\n  - rules: [MD-01, MD-02]\n    paths: ['models/marts/spine.sql']\n    reason: generated\n",
        encoding="utf-8",
    )
    s = Suppressions.load(tmp_path)
    assert s.reason_for("MD-01", "models/marts/spine.sql") == "generated"
    assert s.reason_for("MD-02", "models/marts/spine.sql") == "generated"
    assert s.reason_for("MD-01", "models/marts/other.sql") is None


def test_missing_config_means_no_suppressions(tmp_path) -> None:
    s = Suppressions.load(tmp_path)
    assert s.reason_for("MD-01", "models/marts/x.sql") is None


def test_inline_comment_suppression(tmp_path) -> None:
    sql = tmp_path / "models" / "marts" / "spine.sql"
    sql.parent.mkdir(parents=True)
    sql.write_text("-- adaf-disable: MD-01 (synthetic spine has no grain)\nselect 1\n", encoding="utf-8")
    s = Suppressions.load(tmp_path)
    assert s.reason_for("MD-01", "models/marts/spine.sql") == "synthetic spine has no grain"
    assert s.reason_for("MD-02", "models/marts/spine.sql") is None


def test_inline_multiple_codes_and_file_synonym(tmp_path) -> None:
    sql = tmp_path / "m.sql"
    sql.write_text("-- adaf-disable-file: MD-01, MD-02\nselect 1\n", encoding="utf-8")
    s = Suppressions.load(tmp_path)
    assert s.is_suppressed("MD-01", "m.sql") and s.is_suppressed("MD-02", "m.sql")


def test_evaluate_drops_suppressed_gap(tmp_path) -> None:
    # A products node missing its grain test (MD-01) is suppressed by config → not a finding, recorded.
    (tmp_path / CONFIG_NAME).write_text(
        "disable:\n  - rules: [MD-01]\n    paths: ['models/marts/products.sql']\n    reason: demo\n",
        encoding="utf-8",
    )
    s = Suppressions.load(tmp_path)
    report = tax_cmd.evaluate([_node()], {"models/marts/products.sql"}, strict=False, scope="x", suppressions=s)
    assert not any(f.rule_code == "MD-01" for f in report.findings)
    assert any(sf.rule_code == "MD-01" and sf.reason == "demo" for sf in report.suppressed)


def test_disable_help_mentions_both_layers() -> None:
    lines = "\n".join(disable_help("EN-03"))
    assert "-- adaf-disable: EN-03" in lines and CONFIG_NAME in lines and "rules: [EN-03]" in lines
