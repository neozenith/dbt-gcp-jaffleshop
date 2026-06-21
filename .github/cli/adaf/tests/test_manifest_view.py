"""Unit tests for the shared ManifestView seam — pure (synthetic manifest dict, no dbt)."""

# Standard Library
import json

# First Party
from adaf.dbt.artifact import JsonManifestArtifact
from adaf.dbt.manifest_view import ManifestView


def _manifest() -> dict:
    return {
        "nodes": {
            "model.p.a": {"resource_type": "model", "name": "a", "depends_on": {"nodes": ["source.p.raw"]}},
            "model.p.b": {"resource_type": "model", "name": "b", "depends_on": {"nodes": ["model.p.a"]}},
            "test.p.t": {"resource_type": "test", "name": "t", "depends_on": {"nodes": ["model.p.a"]}},
        },
        "sources": {
            "source.p.raw": {"name": "raw"},  # no resource_type → defaulted to "source"
        },
        "exposures": {"exposure.p.dash": {"depends_on": {"nodes": ["model.p.b"]}}},
        "parent_map": {
            "source.p.raw": [],
            "model.p.a": ["source.p.raw"],
            "model.p.b": ["model.p.a"],
            "test.p.t": ["model.p.a"],
        },
    }


def test_records_default_source_resource_type() -> None:
    view = ManifestView.from_dict(_manifest())
    recs = view.records()
    assert recs["source.p.raw"].resource_type == "source"  # defaulted from the sources section
    assert recs["source.p.raw"].section == "sources"
    assert recs["model.p.a"].section == "nodes"
    assert set(recs) == {"model.p.a", "model.p.b", "test.p.t", "source.p.raw"}


def test_of_type_filters() -> None:
    view = ManifestView.from_dict(_manifest())
    assert set(view.of_type("model")) == {"model.p.a", "model.p.b"}
    assert set(view.of_type("model", "source")) == {"model.p.a", "model.p.b", "source.p.raw"}
    assert set(view.of_type("test")) == {"test.p.t"}


def test_parent_edges_default_keeps_all_present_endpoints() -> None:
    edges = set(ManifestView.from_dict(_manifest()).parent_edges())
    # Every parent_map edge whose endpoints are both present, INCLUDING the model→test edge.
    assert edges == {
        ("source.p.raw", "model.p.a"),
        ("model.p.a", "model.p.b"),
        ("model.p.a", "test.p.t"),
    }


def test_parent_edges_filtered_to_a_subset() -> None:
    view = ManifestView.from_dict(_manifest())
    data_nodes = {"model.p.a", "model.p.b", "source.p.raw"}  # exclude the test node
    edges = set(view.parent_edges(data_nodes))
    assert edges == {("source.p.raw", "model.p.a"), ("model.p.a", "model.p.b")}  # model→test dropped


def test_parent_edges_falls_back_to_depends_on_without_parent_map() -> None:
    data = _manifest()
    del data["parent_map"]
    edges = set(ManifestView.from_dict(data).parent_edges({"model.p.a", "model.p.b", "source.p.raw"}))
    assert edges == {("source.p.raw", "model.p.a"), ("model.p.a", "model.p.b")}


def test_section_returns_dict_or_empty() -> None:
    view = ManifestView.from_dict(_manifest())
    assert set(view.section("exposures")) == {"exposure.p.dash"}
    assert view.section("semantic_models") == {}  # absent section → empty dict, never None


def test_load_reads_from_disk(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")
    view = ManifestView.load(path)
    assert "model.p.a" in view.records()


def test_json_artifact_sections_match_view(tmp_path) -> None:
    """JsonManifestArtifact over a fixture manifest exposes the same sections the view reads today."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")
    artifact = JsonManifestArtifact.load(path)

    # Every dict section the manifest carries is exposed, including parent_map separately.
    assert set(artifact.sections()) == {"nodes", "sources", "exposures", "parent_map"}
    assert set(artifact.sections()["nodes"]) == {"model.p.a", "model.p.b", "test.p.t"}
    assert artifact.parent_map()["model.p.a"] == ["source.p.raw"]

    # Building the view from the artifact is byte-for-byte equivalent to from_dict on the raw manifest.
    via_artifact = ManifestView.from_artifact(artifact)
    via_dict = ManifestView.from_dict(_manifest())
    assert set(via_artifact.records()) == set(via_dict.records())
    assert set(via_artifact.section("exposures")) == set(via_dict.section("exposures"))
    assert set(via_artifact.parent_edges()) == set(via_dict.parent_edges())
