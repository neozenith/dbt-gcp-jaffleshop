"""Tests for the artifact I/O layer — the dbt Fusion (v2.0) parquet reader (ParquetManifestArtifact).

The parquet fixture is synthesised in ``tmp_path`` via duckdb itself, matching the VERIFIED Fusion
``dbt parse --write-index`` layout (see ``docs/dbt-fusion-artifacts.md``): one node table
``metadata/parse/nodes/v1_0.parquet`` holding every resource type (typed columns + a ``payload`` JSON
blob), plus the ``metadata/parse/test_metadata/v1_0.parquet`` sidecar. The fixtures intentionally carry
an ``ingested_at`` TIMESTAMPTZ column (as real Fusion does) to lock in that the reader projects only the
columns it needs and never materialises the tz column (which would require pytz).

Run with the optional extra present so these actually execute (not just skip):

    uv run --directory .github/cli/adaf --extra fusion pytest tests/test_artifact.py -q
"""

# Standard Library
import inspect
import json
from pathlib import Path

# Third Party
import pytest

# First Party
from adaf.commands.sdaglint import Artifacts
from adaf.dbt import artifact as artifact_mod
from adaf.dbt.artifact import JsonManifestArtifact, ParquetManifestArtifact, load_artifact
from adaf.dbt.manifest import Manifest
from adaf.dbt.manifest_view import ManifestView

# Optional adaf[fusion] dependency — skip cleanly if it truly can't be installed in the env, but the
# verification command supplies it via `--extra fusion` so the suite runs for real.
duckdb = pytest.importorskip("duckdb")

# The node-table columns the reader projects (mirrors artifact._NODE_COLUMNS), plus the tz `ingested_at`
# the reader must NOT touch. Order here is the INSERT order used by `_write_nodes`.
_NODE_SCHEMA = (
    "unique_id VARCHAR, resource_type VARCHAR, name VARCHAR, package_name VARCHAR, "
    "original_path VARCHAR, description VARCHAR, tags VARCHAR[], fqn VARCHAR[], "
    "depends_on VARCHAR[], payload VARCHAR, ingested_at TIMESTAMPTZ"
)


def _node(uid, rt, *, name="", deps=None, desc="", payload=None, original_path="", tags=None):
    """One nodes/v1_0.parquet row tuple (matching _NODE_SCHEMA order; ingested_at set in SQL)."""
    return (
        uid, rt, name, "p", original_path, desc,
        list(tags or []), uid.split("."), list(deps or []), json.dumps(payload or {}),
    )


def _model_payload(*, patch_path="", columns=None, contract_enforced=None):
    pl = {"__common_attr__": {"patch_path": patch_path}, "__base_attr__": {"columns": columns or {}}}
    if contract_enforced is not None:
        pl["config"] = {"contract": {"enforced": contract_enforced}}
    return pl


def _write_nodes(con, path: Path, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"CREATE OR REPLACE TABLE t ({_NODE_SCHEMA})")
    placeholders = ", ".join(["?"] * 10)  # 10 inserted columns; ingested_at filled by now()
    con.executemany(
        f"INSERT INTO t (unique_id, resource_type, name, package_name, original_path, description, "
        f"tags, fqn, depends_on, payload) VALUES ({placeholders})",
        rows,
    )
    con.execute("UPDATE t SET ingested_at = now()")  # realistic tz column the reader must skip
    con.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")


def _write_test_metadata(con, path: Path, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        "CREATE OR REPLACE TABLE tm (unique_id VARCHAR, test_name VARCHAR, test_namespace VARCHAR, "
        "ingested_at TIMESTAMPTZ)"
    )
    con.executemany("INSERT INTO tm (unique_id, test_name, test_namespace) VALUES (?, ?, ?)", rows)
    con.execute("UPDATE tm SET ingested_at = now()")
    con.execute(f"COPY tm TO '{path}' (FORMAT PARQUET)")


def _write_fusion_target(target: Path) -> None:
    """A tiny but complete Fusion parse artifact set: 2 models, a source, exposure, semantic model,
    a test, and a macro — exercising every section route, contract, freshness, columns and lineage."""
    nodes_pq = target / "metadata/parse/nodes/v1_0.parquet"
    tests_pq = target / "metadata/parse/test_metadata/v1_0.parquet"
    con = duckdb.connect(database=":memory:")
    try:
        rows = [
            _node(
                "model.p.a", "model", name="a", deps=["source.p.raw", "macro.p.m"], desc="A model",
                original_path="models/a.sql",
                payload=_model_payload(
                    patch_path="models/a.yml", columns={"id": {"description": "id col"}}, contract_enforced=True
                ),
            ),
            _node(
                "model.p.b", "model", name="b", deps=["model.p.a"], desc="",  # no description
                original_path="models/b.sql",
                payload=_model_payload(patch_path="models/b.yml", columns={}, contract_enforced=False),
            ),
            _node("source.p.raw", "source", name="raw", deps=[],
                  payload={"__source_attr__": {"freshness": {"warn_after": {"count": 1, "period": "day"}}}}),
            _node("exposure.p.dash", "exposure", name="dash", deps=["model.p.b"], payload={}),
            _node("semantic_model.p.sm", "semantic_model", name="sm", deps=["model.p.b"], payload={}),
            _node("test.p.t1", "test", name="not_null_a", deps=["model.p.a"], payload={}),
            _node("macro.p.m", "macro", name="m", original_path="macros/m.sql"),
        ]
        _write_nodes(con, nodes_pq, rows)
        _write_test_metadata(con, tests_pq, [("test.p.t1", "not_null", None)])
    finally:
        con.close()


def test_parquet_sections_route_by_resource_type(tmp_path) -> None:
    """Every resource type lands in its manifest.json section; depends_on splits nodes vs macros."""
    target = tmp_path / "target"
    _write_fusion_target(target)
    art = ParquetManifestArtifact(target)
    sections = art.sections()

    assert set(sections["nodes"]) == {"model.p.a", "model.p.b", "test.p.t1"}
    assert set(sections["sources"]) == {"source.p.raw"}
    assert set(sections["exposures"]) == {"exposure.p.dash"}
    assert set(sections["semantic_models"]) == {"semantic_model.p.sm"}
    assert set(sections["macros"]) == {"macro.p.m"}
    # depends_on split by the macro. prefix
    assert sections["nodes"]["model.p.a"]["depends_on"] == {"nodes": ["source.p.raw"], "macros": ["macro.p.m"]}
    # parent_map carries node deps only (macros excluded)
    assert art.parent_map()["model.p.a"] == ["source.p.raw"]


def test_projections_over_parquet_are_correct(tmp_path) -> None:
    """The real adaf projections (Manifest + Artifacts) read the reconstructed nodes correctly."""
    target = tmp_path / "target"
    _write_fusion_target(target)
    view = ManifestView.from_artifact(ParquetManifestArtifact(target))

    mani = {m.unique_id: m for m in Manifest.from_view(view).models()}
    assert mani["model.p.a"].description == "A model"
    assert mani["model.p.a"].columns == {"id": "id col"}
    assert mani["model.p.a"].test_count == 1  # test.p.t1 depends on it
    assert mani["model.p.b"].description == ""  # the doc gap
    assert mani["model.p.b"].test_count == 0

    arts = Artifacts.from_view(view)
    assert arts.contracts == frozenset({"model.p.a"})  # only a enforces a contract
    assert arts.exposure_deps == frozenset({"model.p.b"})
    assert arts.semantic_deps == frozenset({"model.p.b"})
    assert arts.fresh_sources == frozenset({"source.p.raw"})


def test_manifest_view_load_routes_parquet_dir(tmp_path) -> None:
    """load_artifact / ManifestView.load detect the Fusion node table and build a working view."""
    target = tmp_path / "target"
    _write_fusion_target(target)
    assert isinstance(load_artifact(target), ParquetManifestArtifact)

    view = ManifestView.load(target)
    assert view.records()["source.p.raw"].resource_type == "source"
    assert set(view.of_type("model")) == {"model.p.a", "model.p.b"}
    assert ("source.p.raw", "model.p.a") in set(view.parent_edges())


def test_parquet_dir_with_only_manifest_json_falls_back(tmp_path) -> None:
    """A dir WITHOUT the Fusion node table but WITH manifest.json routes to the JSON reader."""
    target = tmp_path / "target"
    target.mkdir()
    (target / "manifest.json").write_text(json.dumps({"nodes": {}, "parent_map": {}}), encoding="utf-8")
    assert isinstance(load_artifact(target), JsonManifestArtifact)


def test_missing_required_column_fails_loud(tmp_path) -> None:
    """A node table missing a required column raises a clear error naming the file + column."""
    target = tmp_path / "target"
    nodes_pq = target / "metadata/parse/nodes/v1_0.parquet"
    nodes_pq.parent.mkdir(parents=True)
    con = duckdb.connect(database=":memory:")
    try:
        # Deviant schema: drop `depends_on` entirely.
        con.execute("CREATE TABLE t (unique_id VARCHAR, resource_type VARCHAR, name VARCHAR, "
                    "package_name VARCHAR, original_path VARCHAR, description VARCHAR, "
                    "tags VARCHAR[], fqn VARCHAR[], payload VARCHAR)")
        con.execute("INSERT INTO t VALUES ('model.p.a', 'model', 'a', 'p', 'models/a.sql', '', [], [], '{}')")
        con.execute(f"COPY t TO '{nodes_pq}' (FORMAT PARQUET)")
    finally:
        con.close()

    with pytest.raises(ValueError) as excinfo:
        ParquetManifestArtifact(target)
    message = str(excinfo.value)
    assert "depends_on" in message
    assert "v1_0.parquet" in message


def test_missing_node_table_fails_loud(tmp_path) -> None:
    """A directory that is neither a Fusion node table nor a manifest.json cannot be detected."""
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(RuntimeError, match="cannot detect a dbt manifest artifact"):
        load_artifact(target)


def test_missing_duckdb_is_a_loud_import_error_path() -> None:
    """duckdb is installed here, so assert the loud ImportError path exists in the constructor source.

    (The import is inside __init__ — feature-gated — so it cannot be exercised while duckdb is present.)
    """
    src = inspect.getsource(artifact_mod.ParquetManifestArtifact.__init__)
    assert "import duckdb" in src
    assert "raise ImportError" in src
    assert "adaf[fusion]" in src
