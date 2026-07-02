"""The selector definition is embedded on its super-node so the viewer sidebar can show it (pure)."""

# First Party
from adaf.sdag.viewer import build_super_graph_json


def _supers(out: dict) -> dict[str, dict]:
    return {e["data"]["id"]: e["data"] for e in out["elements"] if e["data"].get("kind") == "super"}


def test_super_node_embeds_selector_definition() -> None:
    nodes = {"model.p.a": {"resource_type": "model"}, "model.p.b": {"resource_type": "model"}}
    resolved = {"demand": {"model.p.a", "model.p.b"}}
    out = build_super_graph_json(nodes, [], resolved, definitions={"demand": "tag:demand"})
    assert _supers(out)["demand"]["definition"] == "tag:demand"


def test_super_node_definition_defaults_empty_when_absent() -> None:
    nodes = {"model.p.a": {"resource_type": "model"}}
    resolved = {"demand": {"model.p.a"}}
    # No definitions passed → the key is present but empty (never missing, so the JS lookup is safe).
    assert _supers(build_super_graph_json(nodes, [], resolved))["demand"]["definition"] == ""
