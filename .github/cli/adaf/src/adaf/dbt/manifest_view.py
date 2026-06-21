"""The single seam every manifest projection builds on — parse dbt's ``manifest.json`` ONCE.

dbt's ``manifest.json`` is the CLI's central artifact, and several projections read it: the coverage
view (``adaf.dbt.manifest.Manifest``), the lineage graph (``adaf.graph.Graph``), the boundary-lint
artifact sets (``adaf.commands.sdaglint.Artifacts``), and the sdag viewer's display graph
(``adaf.viewer``). Each used to re-do the same mechanical work — read the file, iterate the
``nodes`` + ``sources`` sections (defaulting a source's ``resource_type``), flatten ``parent_map``
into edges, and find the ``test`` nodes. That duplication lived in several places; a dbt schema
change meant several edits.

``ManifestView`` owns exactly that mechanical layer and nothing domain-specific: it does NOT know
what a "contract" or a "boundary" is. The projections that share it keep their own meaning, building
from a view via a ``from_view`` constructor (``Manifest``, ``Graph``, and the lint ``Artifacts``);
their existing ``load`` / ``from_dict`` entry points remain as thin wrappers, so call sites and tests
are unchanged. (The deterministic detectors in ``adaf.taxonomy`` still read the manifest directly —
they are not yet migrated onto the view.)

Pure: the only I/O is delegated to a :class:`~adaf.dbt.artifact.ManifestArtifact` in ``load``;
everything else operates on the parsed dict. The artifact seam is what makes "the manifest is one
JSON file on disk" swappable (the dbt Fusion / v2.0 parquet set) without the view or any projection
noticing — see ``docs/dbt-fusion-artifacts.md``.
"""

# Standard Library
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# First Party
from adaf.dbt.artifact import ManifestArtifact, load_artifact


@dataclass(frozen=True)
class NodeRecord:
    """One manifest node, normalised just enough to route on: its id, which section it came from
    (``nodes`` vs ``sources``), its (source-defaulted) ``resource_type``, and the raw node dict.

    Projections read whatever else they need (``description``, ``config``, ``freshness``, …) off
    ``raw`` — those fields are projection-specific, so they stay out of this shared record.
    """

    unique_id: str
    section: str  # "nodes" | "sources"
    resource_type: str
    raw: dict[str, Any]


class ManifestView:
    """A parse-once view over a dbt ``manifest.json``; the shared substrate for every projection."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        records: dict[str, NodeRecord] = {}
        for section in ("nodes", "sources"):
            for uid, node in (data.get(section) or {}).items():
                rt = node.get("resource_type") or ("source" if section == "sources" else "")
                records[uid] = NodeRecord(uid, section, rt, node)
        self._records = records

    @classmethod
    def load(cls, path: Path | str) -> "ManifestView":
        """Load a manifest from disk via the artifact seam; fail loud if it is missing.

        ``path`` is detected by :func:`~adaf.dbt.artifact.load_artifact` (a ``manifest.json`` file →
        JSON reader; a Fusion target dir with ``metadata/parse/nodes/v1_0.parquet`` → the parquet
        reader), then the view is built from the artifact's sections + parent_map.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"dbt manifest not found at '{p}'. Run `dbt parse` or pass --parse.")
        return cls.from_artifact(load_artifact(p))

    @classmethod
    def from_artifact(cls, artifact: ManifestArtifact) -> "ManifestView":
        """Build a view from any :class:`~adaf.dbt.artifact.ManifestArtifact` (the format-agnostic seam)."""
        return cls({**artifact.sections(), "parent_map": artifact.parent_map()})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ManifestView":
        """Build a view from an already-parsed manifest dict (for tests / callers holding the dict)."""
        return cls(data)

    def records(self) -> dict[str, NodeRecord]:
        """Every data-section node (``nodes`` + ``sources``) keyed by ``unique_id``."""
        return self._records

    def of_type(self, *resource_types: str) -> dict[str, NodeRecord]:
        """The subset of :meth:`records` whose ``resource_type`` is one of ``resource_types``."""
        wanted = frozenset(resource_types)
        return {uid: rec for uid, rec in self._records.items() if rec.resource_type in wanted}

    def section(self, name: str) -> dict[str, Any]:
        """A top-level manifest section as a dict (e.g. ``exposures``, ``semantic_models``)."""
        sec = self._data.get(name)
        return sec if isinstance(sec, dict) else {}

    def dependent_macro_files(self, model_ids: set[str]) -> set[str]:
        """Project-relative ``.sql`` files of THIS project's macros that ``model_ids`` depend on.

        Reads each model's ``depends_on.macros`` and maps the macro ids to their
        ``original_file_path``, keeping only macros from the ROOT project — package macros live under
        ``dbt_packages/`` at runtime, never in the repo, so they are never valid trigger paths."""
        root_pkg = (self._data.get("metadata") or {}).get("project_name")
        macros = self.section("macros")
        nodes = self.of_type("model")
        macro_ids: set[str] = set()
        for mid in model_ids:
            rec = nodes.get(mid)
            if rec is not None:
                macro_ids |= set((rec.raw.get("depends_on") or {}).get("macros", []))
        files: set[str] = set()
        for macro_id in macro_ids:
            m = macros.get(macro_id)
            if isinstance(m, dict) and m.get("package_name") == root_pkg:
                ofp = m.get("original_file_path")
                if isinstance(ofp, str) and ofp:
                    files.add(ofp)
        return files

    def parent_edges(self, present: set[str] | None = None) -> list[tuple[str, str]]:
        """Directed ``(parent, child)`` lineage edges, kept only when BOTH endpoints are ``present``.

        Prefers dbt's compiled ``parent_map`` (child → [parents]); falls back to each node's
        ``depends_on.nodes`` when no ``parent_map`` is present. ``present`` defaults to every node in
        the view — pass a narrower set (e.g. just the data nodes) to filter the lineage to it.
        """
        nodes = set(self._records) if present is None else present
        parent_map = self._data.get("parent_map") or {}
        if parent_map:
            return [
                (parent, child)
                for child, parents in parent_map.items()
                for parent in (parents or [])
                if parent in nodes and child in nodes
            ]
        edges: list[tuple[str, str]] = []
        for uid, rec in self._records.items():
            if uid not in nodes:
                continue
            for parent in (rec.raw.get("depends_on") or {}).get("nodes", []):
                if parent in nodes:
                    edges.append((parent, uid))
        return edges
