"""Unit tests for `dbt ls` stdout parsing — pure, no dbt/warehouse.

Focused on ``_strip_log_prefix``: the dbt Cloud CLI prefixes every stdout line with a log
timestamp (``HH:MM:SS`` ± fraction), which must be stripped before the ``.sql``/``{`` tests so
both dbt-core (clean) and dbt Cloud CLI (timestamped) output resolve to the same clean values.
"""

# Third Party
import pytest

# First Party
from adaf.dbt.ls import _strip_log_prefix


@pytest.mark.parametrize(
    "line,expected",
    [
        # Timestamped .sql path (dbt Cloud CLI).
        ("11:34:22 models/marts/dim_customer.sql", "models/marts/dim_customer.sql"),
        # Clean .sql path (dbt-core) — passes through unchanged.
        ("models/marts/dim_customer.sql", "models/marts/dim_customer.sql"),
        # Timestamped JSON line.
        ('11:34:22 {"unique_id": "model.proj.x"}', '{"unique_id": "model.proj.x"}'),
        # Milliseconds variant (dot fraction).
        ("11:34:22.456 models/staging/stg_orders.sql", "models/staging/stg_orders.sql"),
        # Comma-fraction variant.
        ("09:00:01,789 models/a.sql", "models/a.sql"),
        # Non-matching line — no timestamp prefix, untouched.
        ("just a plain line", "just a plain line"),
        # A path whose own name contains digits/colons must not be mangled.
        ("models/12:00:00_weird.sql", "models/12:00:00_weird.sql"),
    ],
)
def test_strip_log_prefix(line: str, expected: str) -> None:
    assert _strip_log_prefix(line) == expected
