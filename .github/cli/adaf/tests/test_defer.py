"""Tests for ``adaf.commands.defer`` pure helpers.

The built-vs-deferred preview is no longer a standalone ``defer-diff`` subcommand — it is now part of
``adaf ls --defer`` (rendered by ``checks.list_targets``; see ``test_checks.py``). What remains here
is :func:`built_model_paths`, the faithful ``state:modified+`` (``M+``) set the ``built`` subgroup is
keyed on. It is exercised against real on-disk manifests (no dbt, no mocks): a ``--state`` baseline vs
a current manifest, with the verdict coming from :mod:`adaf.dbt.state_modified`.
"""

# Standard Library
import json
from pathlib import Path
from typing import Any

# First Party
from adaf.commands.defer import built_model_paths
from adaf.dbt.selection import Selection


def _model(uid: str, **over: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "unique_id": uid,
        "resource_type": "model",
        "name": uid.split(".")[-1],
        "original_file_path": f"models/{uid.split('.')[-1]}.sql",
        "raw_code": "select 1",
        "fqn": ["proj", uid.split(".")[-1]],
        "unrendered_config": {"materialized": "view"},
        "config": {},
        "columns": {},
        "description": "",
        "depends_on": {"nodes": [], "macros": []},
        "contract": {"enforced": False, "checksum": None},
        "access": "protected",
        "latest_version": None,
        "deprecation_date": None,
    }
    node.update(over)
    return node


def _write_manifest(path: Path, nodes: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"nodes": {n["unique_id"]: n for n in nodes}, "sources": {}, "macros": {}}))


def test_built_model_paths_is_the_modified_plus_set(tmp_path: Path) -> None:
    # Baseline {a -> b}; current adds a NEW model c (downstream of b). M+ = the new model + nothing
    # else (a, b unchanged) -> {c}. `--state` (state_dir_override) supplies the baseline, no git.
    base_dir = tmp_path / "base"
    a = _model("model.p.a")
    b = _model("model.p.b", depends_on={"nodes": ["model.p.a"], "macros": []})
    _write_manifest(base_dir / "manifest.json", [a, b])

    current = tmp_path / "target" / "manifest.json"
    c = _model("model.p.c", depends_on={"nodes": ["model.p.b"], "macros": []})  # brand-new model
    _write_manifest(current, [a, b, c])

    sel = Selection(selector="x", state_dir_override=str(base_dir))
    got = built_model_paths(sel, current, root=tmp_path)
    assert got == {"models/c.sql"}  # only the new model is state:modified+


def test_built_model_paths_empty_when_nothing_changed(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    a = _model("model.p.a")
    _write_manifest(base_dir / "manifest.json", [a])
    current = tmp_path / "target" / "manifest.json"
    _write_manifest(current, [a])  # identical -> no model is built
    sel = Selection(selector="x", state_dir_override=str(base_dir))
    assert built_model_paths(sel, current, root=tmp_path) == set()
