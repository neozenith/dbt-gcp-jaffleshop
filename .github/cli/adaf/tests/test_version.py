"""Pure tests for the dbt version-banner parser (`adaf.dbt.version`).

The live ``dbt_version()`` / ``supports_selector_method()`` shell out to ``dbt --version`` (exercised
for real by the multiversion harness); the banner PARSER is pure, so it is unit-tested directly across
every engine's banner shape.
"""

# Third Party
import pytest

# First Party
from adaf.dbt.version import _SELECTOR_METHOD_MIN, _parse_version


@pytest.mark.parametrize(
    "banner,expected",
    [
        ("Core:\n  - installed: 1.11.11\n  - latest:    1.11.12", (1, 11, 11)),  # dbt-core GA
        ("  - installed: 1.12.0b3", (1, 12, 0)),  # dbt-core prerelease
        ("dbt-fusion 2.0.0-preview.190", (2, 0, 0)),  # Fusion Rust binary
        ("dbt Cloud CLI - 0.40.15 (bcc3d4fb 2026-03-02T18:03:57Z)", None),  # Cloud CLI ⇒ undetectable
        ("totally unparseable", None),
    ],
)
def test_parse_version(banner: str, expected: tuple[int, int, int] | None) -> None:
    assert _parse_version(banner) == expected


def test_selector_method_threshold() -> None:
    # 1.11 lacks the `selector:` method; 1.12 and Fusion 2.x have it (tuple order does the gating).
    assert (1, 11, 11) < _SELECTOR_METHOD_MIN
    assert (1, 12, 0) >= _SELECTOR_METHOD_MIN
    assert (2, 0, 0) >= _SELECTOR_METHOD_MIN
