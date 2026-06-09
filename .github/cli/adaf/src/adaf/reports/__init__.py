"""The check **result dataclasses**, grouped together — one module per check domain. Each report is
the data shape + its rendering (``ok``/``summary``/``to_dict``/``human_lines``); the evaluation logic
that builds them lives in ``adaf.commands.*`` (which also re-export these for back-compat). This
package re-exports the full set for a single import surface."""

from adaf.reports.coverage import ColumnsReport, ColumnsRow, DocsReport, DocsRow, TestsReport, TestsRow
from adaf.reports.dataproducts import (
    BoundaryReport,
    BoundaryTestRow,
    MemberRow,
    ProductBoundary,
    SystemBoundaryReport,
)
from adaf.reports.deprecations import DeprecationsReport
from adaf.reports.sqlfluff import SqlfluffReport
from adaf.reports.taxonomy import SuppressedFinding, TaxonomyFinding, TaxonomyReport

__all__ = [
    "ColumnsReport",
    "ColumnsRow",
    "DocsReport",
    "DocsRow",
    "TestsReport",
    "TestsRow",
    "BoundaryReport",
    "BoundaryTestRow",
    "MemberRow",
    "ProductBoundary",
    "SystemBoundaryReport",
    "DeprecationsReport",
    "SqlfluffReport",
    "SuppressedFinding",
    "TaxonomyFinding",
    "TaxonomyReport",
]
