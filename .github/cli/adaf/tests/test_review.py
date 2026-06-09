"""Offline tests for the `adaf review` pure logic — no GitHub Models call.

The LLM HTTP path is an I/O shell (proven by a live run, per the action's design); these
cover the parts that must be correct without a network: the no-drift enum injection, the
matrix rendering, finding validation, and that the prompt is catalogue-driven on DAMA.
"""

import pytest

from adaf.commands import review
from adaf.rules import review_response_format, rule_codes


def test_response_format_injects_every_catalogue_code() -> None:
    rf = review_response_format()
    enum = rf["json_schema"]["schema"]["properties"]["models"]["items"]["properties"]["findings"]["items"][
        "properties"
    ]["rule_code"]["enum"]
    # The on-disk schema enum is a stale placeholder; injection must replace it with the live SSoT.
    assert enum == rule_codes()
    assert len(enum) == 33
    assert rf["json_schema"]["strict"] is True


def test_response_format_strips_meta_keys() -> None:
    schema = review_response_format()["json_schema"]["schema"]
    for k in ("$schema", "title", "description"):
        assert k not in schema


def test_prompt_catalogue_uses_dama_dimensions() -> None:
    cat = review.build_catalogue()
    # MD-01 defends DAMA Uniqueness — the operational tag the prompt must surface.
    assert "MD-01" in cat
    assert "Uniqueness" in cat
    sysp = review.system_prompt()
    assert "MD-01" in sysp and "Only use rule codes from this set" in sysp


def test_validate_rejects_unknown_rule_code() -> None:
    bad = {"models": [{"model": "x", "findings": [{"rule_code": "ZZ-99", "status": "applicable_missing"}]}]}
    with pytest.raises(RuntimeError, match="unknown rule_code"):
        review._validate_result(bad)


def test_validate_requires_models_array() -> None:
    with pytest.raises(RuntimeError, match="missing 'models'"):
        review._validate_result({"not_models": []})


def test_matrix_table_marks_present_missing_na() -> None:
    result = {
        "models": [
            {
                "model": "orders",
                "findings": [
                    {"rule_code": "MD-01", "status": "applicable_present"},
                    {"rule_code": "EN-03", "status": "applicable_missing"},
                    {"rule_code": "MS-05", "status": "not_applicable"},
                ],
            },
        ]
    }
    lines = review.matrix_table(result, "test scope")
    body = "\n".join(lines)
    assert "test scope" in body
    # Applicable columns (present/missing) appear; not_applicable-only columns are dropped.
    assert "MD-01" in body and "EN-03" in body and "MS-05" not in body
    assert "✅" in body and "❌" in body


def test_matrix_table_handles_no_models() -> None:
    assert "_No models to review._" in "\n".join(review.matrix_table({"models": []}, "empty"))


def test_apply_suppressions_demotes_suppressed_gaps(tmp_path) -> None:
    from adaf.suppression import CONFIG_NAME, Suppressions

    (tmp_path / CONFIG_NAME).write_text(
        "disable:\n  - rules: [MD-02]\n    paths: ['models/marts/orders.sql']\n    reason: demo\n", encoding="utf-8"
    )
    result = {
        "models": [
            {
                "model": "orders",
                "findings": [
                    {"rule_code": "MD-02", "status": "applicable_missing"},
                    {"rule_code": "EN-03", "status": "applicable_missing"},
                ],
            }
        ]
    }
    demoted = review.apply_suppressions(result, {"orders": "models/marts/orders.sql"}, Suppressions.load(tmp_path))
    statuses = {f["rule_code"]: f["status"] for f in result["models"][0]["findings"]}
    assert demoted == 1
    assert statuses["MD-02"] == "not_applicable"  # suppressed → demoted
    assert statuses["EN-03"] == "applicable_missing"  # untouched
