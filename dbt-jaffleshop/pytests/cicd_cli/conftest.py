"""Shared fixtures for the cicd_cli unit tests.

A hand-built mini-manifest covering the cases the coverage checks care about:
a fully documented+tested model, one with an undocumented column, and one with
no description and no tests. A seed node is included to prove non-model/test
resource types are ignored.
"""

# Third Party
import pytest

# Local
from cicd_cli.manifest import Manifest

MANIFEST_DATA = {
    "nodes": {
        "model.jaffle_shop.documented": {
            "resource_type": "model",
            "name": "documented",
            "original_file_path": "models/marts/documented.sql",
            "description": "A fully documented and tested model.",
            "columns": {"id": {"description": "the primary key"}},
        },
        "model.jaffle_shop.partial_cols": {
            "resource_type": "model",
            "name": "partial_cols",
            "original_file_path": "models/staging/partial_cols.sql",
            "description": "Has a model description but one undocumented column.",
            "columns": {"id": {"description": "the id"}, "blank": {"description": ""}},
        },
        "model.jaffle_shop.no_desc": {
            "resource_type": "model",
            "name": "no_desc",
            "original_file_path": "models/marts/no_desc.sql",
            "description": "",
            "columns": {},
        },
        "test.jaffle_shop.t_doc_1": {
            "resource_type": "test",
            "depends_on": {"nodes": ["model.jaffle_shop.documented"]},
        },
        "test.jaffle_shop.t_doc_2": {
            "resource_type": "test",
            "depends_on": {"nodes": ["model.jaffle_shop.documented"]},
        },
        # Non-model/test node — must be ignored entirely.
        "seed.jaffle_shop.raw": {"resource_type": "seed", "name": "raw"},
    }
}


@pytest.fixture
def manifest() -> Manifest:
    return Manifest.from_dict(MANIFEST_DATA)
