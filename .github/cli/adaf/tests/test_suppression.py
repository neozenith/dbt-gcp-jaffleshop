"""Unit tests for .adaf.yml suppression loading + resolution — pure, no dbt/warehouse."""

# Standard Library
from pathlib import Path

# Third Party
import pytest

# First Party
from adaf.suppression import DEFAULT_ADAF_CONFIG, Suppressions, load_suppressions


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / ".adaf.yml"
    p.write_text(body, encoding="utf-8")
    return p


def test_default_config_location() -> None:
    assert DEFAULT_ADAF_CONFIG == Path(".adaf.yml")


def test_missing_file_is_empty(tmp_path: Path) -> None:
    sup = load_suppressions(tmp_path / "nope.yml")
    assert sup == Suppressions()
    assert sup.is_suppressed("MD-02", "models/legacy/x.sql") is False


def test_exact_rule_match(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        "suppress:\n"
        "  - rule: MD-02\n"
        '    paths: ["models/legacy/**", "models/x/foo.sql"]\n'
        '    reason: "grandfathered; ticket DTB-1234"\n',
    )
    sup = load_suppressions(p)
    # exact file path match
    assert sup.is_suppressed("MD-02", "models/x/foo.sql") is True
    # different rule => not suppressed
    assert sup.is_suppressed("MD-11", "models/x/foo.sql") is False
    assert sup.entries[0].reason == "grandfathered; ticket DTB-1234"


def test_star_wildcard_rule(tmp_path: Path) -> None:
    p = _write(tmp_path, "suppress:\n  - rule: '*'\n    paths: ['models/scratch/**']\n")
    sup = load_suppressions(p)
    assert sup.is_suppressed("MD-02", "models/scratch/wip/a.sql") is True
    assert sup.is_suppressed("ANY-RULE-ID", "models/scratch/b.sql") is True


def test_double_star_spans_directories(tmp_path: Path) -> None:
    p = _write(tmp_path, "suppress:\n  - rule: MD-02\n    paths: ['models/legacy/**']\n")
    sup = load_suppressions(p)
    assert sup.is_suppressed("MD-02", "models/legacy/a.sql") is True
    assert sup.is_suppressed("MD-02", "models/legacy/deep/nested/b.sql") is True
    # leading '**' matches any depth
    p2 = _write(tmp_path, "suppress:\n  - rule: R\n    paths: ['**/foo.sql']\n")
    sup2 = load_suppressions(p2)
    assert sup2.is_suppressed("R", "models/a/b/foo.sql") is True
    assert sup2.is_suppressed("R", "models/a/b/bar.sql") is False


def test_non_match(tmp_path: Path) -> None:
    p = _write(tmp_path, "suppress:\n  - rule: MD-02\n    paths: ['models/legacy/**']\n")
    sup = load_suppressions(p)
    assert sup.is_suppressed("MD-02", "models/active/x.sql") is False
    # single '*' does not cross a directory boundary
    p2 = _write(tmp_path, "suppress:\n  - rule: R\n    paths: ['models/*.sql']\n")
    sup2 = load_suppressions(p2)
    assert sup2.is_suppressed("R", "models/top.sql") is True
    assert sup2.is_suppressed("R", "models/sub/deep.sql") is False


def test_empty_suppress_list(tmp_path: Path) -> None:
    p = _write(tmp_path, "suppress: []\n")
    assert load_suppressions(p).is_suppressed("R", "models/a.sql") is False


@pytest.mark.parametrize(
    "body",
    [
        "suppress: not-a-list\n",
        "suppress:\n  - paths: ['models/**']\n",  # missing rule
        "suppress:\n  - rule: R\n    paths: 'models/**'\n",  # paths not a list
        "suppress:\n  - just-a-string\n",  # entry not a mapping
    ],
)
def test_malformed_raises(tmp_path: Path, body: str) -> None:
    p = _write(tmp_path, body)
    with pytest.raises(ValueError):
        load_suppressions(p)
