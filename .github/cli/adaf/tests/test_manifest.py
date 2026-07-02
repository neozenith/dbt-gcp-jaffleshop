"""Unit tests for the manifest view — pure (synthetic manifest dict, no dbt)."""

# First Party
from adaf.dbt.manifest import Manifest


def _manifest() -> dict:
    return {
        "nodes": {
            "model.p.a": {
                "resource_type": "model",
                "name": "a",
                "original_file_path": "models/a.sql",
                "description": "the a model",
                "columns": {"id": {"description": "pk"}, "x": {"description": ""}},
            },
            "model.p.b": {
                "resource_type": "model",
                "name": "b",
                "original_file_path": "models/b.sql",
                "description": "",
                "columns": {},
            },
            "test.p.t1": {"resource_type": "test", "depends_on": {"nodes": ["model.p.a"]}},
            "test.p.t2": {"resource_type": "test", "depends_on": {"nodes": ["model.p.a"]}},
        }
    }


def test_from_dict_extracts_models_only() -> None:
    m = Manifest.from_dict(_manifest())
    by_path = m.by_path()
    assert set(by_path) == {"models/a.sql", "models/b.sql"}


def test_description_and_columns() -> None:
    a = Manifest.from_dict(_manifest()).by_path()["models/a.sql"]
    assert a.description == "the a model"
    assert a.columns == {"id": "pk", "x": ""}


def test_test_count_attributed_to_model() -> None:
    by_path = Manifest.from_dict(_manifest()).by_path()
    assert by_path["models/a.sql"].test_count == 2  # two test nodes depend on a
    assert by_path["models/b.sql"].test_count == 0
