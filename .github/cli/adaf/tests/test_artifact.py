"""Tests for the artifact I/O layer — the dbt v2.0 / Fusion parquet reader (ParquetManifestArtifact).

The parquet fixture is synthesised in ``tmp_path`` via duckdb itself, matching the layout
:class:`ParquetManifestArtifact` documents: one ``<section>.parquet`` per manifest section
(``unique_id`` + ``node_json`` columns) plus ``parent_map.parquet`` (``child`` + ``parents``).

Run with the optional extra present so these actually execute (not just skip):

    uv run --directory .github/cli/adaf --with duckdb pytest tests/test_artifact.py -q
"""

# Standard Library
import inspect
import json
from pathlib import Path

# Third Party
import pytest

# First Party
from adaf.dbt import artifact as artifact_mod
from adaf.dbt.artifact import JsonManifestArtifact, ParquetManifestArtifact, load_artifact
from adaf.dbt.manifest_view import ManifestView

# Optional adaf[fusion] dependency — skip cleanly if it truly can't be installed in the env, but the
# verification command supplies it via `--with duckdb` so the suite runs for real.
duckdb = pytest.importorskip("duckdb")


def _manifest() -> dict:
    """A tiny logical manifest: 2 models, a source, an exposure, a semantic model, and a parent_map."""
    return {
        "nodes": {
            "model.p.a": {"resource_type": "model", "name": "a", "depends_on": {"nodes": ["source.p.raw"]}},
            "model.p.b": {"resource_type": "model", "name": "b", "depends_on": {"nodes": ["model.p.a"]}},
        },
        "sources": {
            "source.p.raw": {"name": "raw"},  # no resource_type → defaulted to "source" by the view
        },
        "exposures": {"exposure.p.dash": {"depends_on": {"nodes": ["model.p.b"]}}},
        "semantic_models": {"semantic_model.p.sm": {"name": "sm", "model": "ref('b')"}},
        "parent_map": {
            "source.p.raw": [],
            "model.p.a": ["source.p.raw"],
            "model.p.b": ["model.p.a"],
        },
    }


def _copy_rows(con, path: Path, columns: list[str], rows: list[tuple]) -> None:
    coldefs = ", ".join(f"{c} VARCHAR" for c in columns)
    placeholders = ", ".join("?" for _ in columns)
    con.execute(f"CREATE OR REPLACE TABLE t ({coldefs})")
    if rows:
        con.executemany(f"INSERT INTO t VALUES ({placeholders})", rows)
    con.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")


def _write_parquet_manifest(target_dir: Path, manifest: dict) -> None:
    """Project a logical manifest dict onto the documented Fusion parquet layout under ``target_dir``."""
    target_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(database=":memory:")
    try:
        for section in ("nodes", "sources", "exposures", "semantic_models", "metrics"):
            data = manifest.get(section)
            if not data:
                continue
            rows = [(uid, json.dumps(node)) for uid, node in data.items()]
            _copy_rows(con, target_dir / f"{section}.parquet", ["unique_id", "node_json"], rows)
        parent_map = manifest.get("parent_map") or {}
        if parent_map:
            rows = [(child, json.dumps(parents)) for child, parents in parent_map.items()]
            _copy_rows(con, target_dir / "parent_map.parquet", ["child", "parents"], rows)
    finally:
        con.close()


def test_parquet_sections_and_parent_map_match_json(tmp_path) -> None:
    """ParquetManifestArtifact yields the same section dicts + parent_map as the JSON reader."""
    manifest = _manifest()
    target = tmp_path / "target"
    _write_parquet_manifest(target, manifest)

    parquet = ParquetManifestArtifact(target)
    js = JsonManifestArtifact(manifest)

    for section in ("nodes", "sources", "exposures", "semantic_models"):
        assert parquet.sections()[section] == js.sections()[section]
    # No metrics in the logical manifest → no metrics.parquet → section simply absent (not empty/error).
    assert "metrics" not in parquet.sections()
    assert parquet.parent_map() == js.parent_map()


def test_manifest_view_from_parquet_dir_is_equivalent(tmp_path) -> None:
    """ManifestView.load(parquet_dir) builds a working view: records / of_type / parent_edges all match."""
    manifest = _manifest()
    target = tmp_path / "target"
    _write_parquet_manifest(target, manifest)

    via_parquet = ManifestView.load(target)
    via_dict = ManifestView.from_dict(manifest)

    assert set(via_parquet.records()) == set(via_dict.records())
    assert set(via_parquet.of_type("model")) == {"model.p.a", "model.p.b"}
    assert via_parquet.records()["source.p.raw"].resource_type == "source"  # source default survives
    assert set(via_parquet.section("exposures")) == {"exposure.p.dash"}
    assert set(via_parquet.section("semantic_models")) == {"semantic_model.p.sm"}
    assert set(via_parquet.parent_edges()) == set(via_dict.parent_edges())


def test_load_artifact_routes_parquet_dir(tmp_path) -> None:
    """A directory of *.parquet is detected and routed to ParquetManifestArtifact (parquet presence wins)."""
    target = tmp_path / "target"
    _write_parquet_manifest(target, _manifest())
    assert isinstance(load_artifact(target), ParquetManifestArtifact)


def test_missing_required_column_fails_loud(tmp_path) -> None:
    """A nodes.parquet missing the required node_json column raises a clear error naming file + column."""
    target = tmp_path / "target"
    target.mkdir()
    con = duckdb.connect(database=":memory:")
    try:
        # Deviant schema: unique_id present, node_json replaced by a bogus column.
        _copy_rows(con, target / "nodes.parquet", ["unique_id", "wrong"], [("model.p.a", "x")])
    finally:
        con.close()

    with pytest.raises(ValueError) as excinfo:
        ParquetManifestArtifact(target)
    message = str(excinfo.value)
    assert "node_json" in message
    assert "nodes.parquet" in message


def test_missing_duckdb_is_a_loud_import_error_path() -> None:
    """duckdb is installed here, so assert the loud ImportError path exists in the constructor source.

    (The import is inside __init__ — feature-gated — so it cannot be exercised while duckdb is present.)
    """
    src = inspect.getsource(artifact_mod.ParquetManifestArtifact.__init__)
    assert "import duckdb" in src
    assert "raise ImportError" in src
    assert "adaf[fusion]" in src
