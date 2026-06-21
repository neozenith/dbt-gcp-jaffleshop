"""Unit tests for selectors.yml parsing (adaf.dbt.selectors) — pure, no dbt/warehouse."""

# Third Party
import pytest

# First Party
from adaf.dbt.selectors import _uses_state, load_selectors, selector_names


@pytest.mark.parametrize(
    "definition,expected",
    [
        ("tag:demand", False),
        ("state:modified", True),
        ("state:modified+", True),
        ({"method": "state", "value": "modified"}, True),
        ({"method": "tag", "value": "demand"}, False),
        ({"union": [{"method": "tag", "value": "a"}, {"method": "state", "value": "modified"}]}, True),
        ({"union": [{"method": "tag", "value": "a"}, {"method": "tag", "value": "b"}]}, False),
        ({"intersection": ["tag:x", "state:modified"]}, True),
        (None, False),
        ([], False),
    ],
)
def test_uses_state(definition: object, expected: bool) -> None:
    assert _uses_state(definition) is expected


def test_load_selectors_reads_name_desc_and_state(tmp_path) -> None:
    p = tmp_path / "selectors.yml"
    p.write_text(
        "selectors:\n"
        "  - name: demand\n"
        "    description: Demand models\n"
        "    definition: tag:demand\n"
        "  - name: changed\n"
        "    definition:\n"
        "      method: state\n"
        "      value: modified\n",
        encoding="utf-8",
    )
    out = load_selectors(p)
    assert out == [
        ("demand", "Demand models", False, "tag:demand"),
        ("changed", "", True, "method: state\nvalue: modified"),
    ]
    assert selector_names(p) == ["demand", "changed"]


def test_load_selectors_missing_file_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_selectors(tmp_path / "nope.yml")


def test_load_selectors_missing_name_raises(tmp_path) -> None:
    p = tmp_path / "selectors.yml"
    p.write_text("selectors:\n  - definition: tag:x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_selectors(p)
