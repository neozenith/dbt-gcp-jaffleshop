"""The I/O + format layer beneath :class:`~adaf.dbt.manifest_view.ManifestView`.

``ManifestView`` owns *normalisation* (records, edges); each projection owns *meaning*. This module
owns the layer below both: reading a dbt compiled-artifact set off disk and presenting it as the two
section/parent_map dicts the view consumes. It extends the ManifestView seam (ADR-0005) one level
deeper — the *artifact* owns I/O + format, so the loading mechanism is swappable without the view or
any projection noticing.

Two readers live here. :class:`JsonManifestArtifact` holds the behaviour ``ManifestView`` used to do
inline (``json.loads`` of a ``manifest.json`` path). :class:`ParquetManifestArtifact` reads the columnar
parquet metadata artifact set the dbt **Fusion** engine (dbt v2.0) emits with ``--write-index``,
projecting its rows back into the same section dicts — via duckdb, imported *inside the class only* so
the JSON path (every dbt-core user today) stays duckdb-free and a missing duckdb on the parquet path is
a loud :class:`ImportError` (``pip install 'adaf[fusion]'``), never a silent fall back to JSON.
:func:`load_artifact` detects which one to build.

The parquet layout below is VERIFIED against real Fusion output (2.0.0-preview.190, ``dbt parse
--write-index``) — see ``docs/dbt-fusion-artifacts.md`` for the captured schema and how it was probed.
Note Fusion *also* still writes a (v12-schema) ``manifest.json`` alongside the parquet; the parquet set
is the new "v20" artifact and is what this reader exercises.
"""

# Standard Library
import json
from pathlib import Path
from typing import Any, Protocol

# Parquet metadata artifacts a Fusion `dbt parse --write-index` writes, relative to the target dir.
# Everything the gates need is in `nodes` (one row per resource of EVERY type, keyed by resource_type,
# carrying typed columns + a rich `payload` JSON blob); `test_metadata` is a sidecar carrying each
# data test's namespace/name (the Elementary volume-anomaly heuristic reads it).
_FUSION_NODES = "metadata/parse/nodes/v1_0.parquet"
_FUSION_TEST_META = "metadata/parse/test_metadata/v1_0.parquet"
_FUSION_GENERATION = "metadata/parse/generation.parquet"  # best-effort: carries project_name

# Exactly the node columns the reader consumes. Selecting an explicit projection (not ``SELECT *``)
# is deliberate: every Fusion artifact carries an ``ingested_at`` TIMESTAMP-WITH-TIME-ZONE column we
# never use, and duckdb can only materialise a tz column when ``pytz`` is installed — projecting the
# columns we need keeps the parquet path's only third-party dep duckdb (no pytz), and is leaner.
_NODE_COLUMNS = (
    "unique_id",
    "resource_type",
    "name",
    "package_name",
    "original_path",
    "description",
    "tags",
    "fqn",
    "depends_on",
    "payload",
)


class ManifestArtifact(Protocol):
    """A dbt compiled-artifact set, presented as the dicts :class:`ManifestView` builds its view from.

    ``sections`` returns the top-level manifest sections by name (``nodes``, ``sources``,
    ``exposures``, ``semantic_models``, ``metrics``, …); ``parent_map`` returns dbt's compiled
    child → [parents] lineage map (empty when the artifact carries none).
    """

    def sections(self) -> dict[str, dict[str, Any]]: ...

    def parent_map(self) -> dict[str, list[str]]: ...


class JsonManifestArtifact:
    """Today's reader: a dbt ``manifest.json`` parsed with :func:`json.loads` (the behaviour lifted
    verbatim out of ``ManifestView.load``)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def load(cls, path: Path | str) -> "JsonManifestArtifact":
        """Read + parse a ``manifest.json`` from disk (the only I/O)."""
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def sections(self) -> dict[str, dict[str, Any]]:
        """Every dict-valued top-level section of the manifest, keyed by section name."""
        return {name: section for name, section in self._data.items() if isinstance(section, dict)}

    def parent_map(self) -> dict[str, list[str]]:
        """dbt's compiled ``parent_map`` (child → [parents]); empty when the manifest omits it."""
        return self._data.get("parent_map") or {}


class ParquetManifestArtifact:
    """dbt **Fusion** (v2.0) reader: the parquet metadata artifact set, read with duckdb.

    **Verified on-disk layout** (Fusion ``dbt parse --write-index``; see
    ``docs/dbt-fusion-artifacts.md``). Unlike dbt-core's ``manifest.json`` — which splits resources
    across top-level sections (``nodes`` / ``sources`` / ``exposures`` / …) — Fusion writes ONE node
    table holding every resource type:

    * ``metadata/parse/nodes/v1_0.parquet`` — one row per resource of EVERY ``resource_type``
      (model, test, source, exposure, semantic_model, metric, macro, …). Required columns:
      ``unique_id``, ``resource_type``, ``depends_on`` (a LIST of parent unique_ids — models AND
      sources AND macros, split here by the ``macro.`` id prefix into ``depends_on.{nodes,macros}``).
      Other typed columns used directly: ``name``, ``package_name``, ``original_path``,
      ``description``, ``tags``, ``fqn``. A ``payload`` JSON column carries the rich node from which
      the per-projection extras are read: ``__common_attr__.patch_path`` (docscov schema anchoring),
      ``config`` (``contract.enforced`` for the sdag contract rule), ``__base_attr__.columns``
      (per-column descriptions), and ``__source_attr__.freshness`` (sources only).
    * ``metadata/parse/test_metadata/v1_0.parquet`` — sidecar: each test's ``test_name`` /
      ``test_namespace``, surfaced as the node's ``test_metadata`` so the Elementary volume heuristic
      works exactly as on the JSON path.

    Rows are routed back into the manifest.json section layout (sources → ``sources``, exposures →
    ``exposures``, …; everything else → ``nodes``) so :class:`ManifestView` and every projection are
    format-agnostic. duckdb is imported **inside** this class (never at module top): the JSON path
    stays duckdb-free, and a missing duckdb raises a loud :class:`ImportError` pointing at the
    ``adaf[fusion]`` extra — never a silent fall back to JSON. Schema drift fails loudly in
    :meth:`_read_rows` (a missing required column names the file + column) — escalators-not-stairs.
    """

    #: dbt ``resource_type`` → manifest section name. Types not listed land in ``nodes`` (mirroring
    #: manifest.json, which lumps models/tests/snapshots/seeds/analyses/operations into ``nodes``).
    _SECTION_BY_TYPE = {
        "source": "sources",
        "exposure": "exposures",
        "semantic_model": "semantic_models",
        "metric": "metrics",
        "saved_query": "saved_queries",
        "macro": "macros",
        "docs_macro": "docs",
    }

    def __init__(self, target_dir: Path | str) -> None:
        try:
            # Third Party — feature-gated: ONLY the parquet path needs duckdb (see class docstring).
            import duckdb
        except ImportError as exc:  # loud, explicit — never a silent fall back to JSON
            raise ImportError(
                "Reading a dbt Fusion (v2.0) parquet artifact set requires duckdb, which is not "
                "installed. Install the optional extra: pip install 'adaf[fusion]'. "
                "See docs/dbt-fusion-artifacts.md."
            ) from exc

        self._dir = Path(target_dir)
        nodes_pq = self._dir / _FUSION_NODES
        if not nodes_pq.exists():
            raise ValueError(
                f"'{self._dir}' is not a dbt Fusion parse artifact set: missing '{_FUSION_NODES}'. "
                "Run `dbt parse --write-index` under the Fusion engine. See docs/dbt-fusion-artifacts.md."
            )

        con = duckdb.connect(database=":memory:")
        try:
            test_meta = self._load_test_metadata(con)
            sections: dict[str, dict[str, Any]] = {}
            parent_map: dict[str, list[str]] = {}
            for r in self._read_rows(con, nodes_pq, _NODE_COLUMNS):
                uid = r["unique_id"]
                rt = r["resource_type"]
                deps = [str(d) for d in (r.get("depends_on") or [])]
                node_deps = [d for d in deps if not d.startswith("macro.")]
                macro_deps = [d for d in deps if d.startswith("macro.")]
                parent_map[uid] = node_deps
                node = self._build_node(r, rt, node_deps, macro_deps, test_meta.get(uid))
                sections.setdefault(self._SECTION_BY_TYPE.get(rt, "nodes"), {})[uid] = node
            meta = self._load_metadata(con)
            if meta:
                sections["metadata"] = meta
            self._sections = sections
            self._parent_map = parent_map
        finally:
            con.close()

    @staticmethod
    def _build_node(
        r: dict[str, Any], rt: str, node_deps: list[str], macro_deps: list[str], test_meta: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Reconstruct one manifest.json-shaped node dict from a parquet row (typed cols + payload)."""
        node: dict[str, Any] = {
            "unique_id": r["unique_id"],
            "resource_type": rt,
            "name": r.get("name") or "",
            "package_name": r.get("package_name") or "",
            "original_file_path": r.get("original_path") or "",
            "description": r.get("description") or "",
            "tags": list(r.get("tags") or []),
            "fqn": list(r.get("fqn") or []),
            "depends_on": {"nodes": node_deps, "macros": macro_deps},
        }
        if rt == "macro":  # macros only need path + package (dependent_macro_files); skip payload parse
            return node

        payload = json.loads(r["payload"]) if r.get("payload") else {}
        common = payload.get("__common_attr__") or {}
        base_attr = payload.get("__base_attr__") or {}
        config = payload.get("config") or {}
        node["patch_path"] = common.get("patch_path")
        node["config"] = config
        node["columns"] = {
            name: {"description": (col or {}).get("description") or ""}
            for name, col in (base_attr.get("columns") or {}).items()
        }
        if rt == "source":
            src_attr = payload.get("__source_attr__") or {}
            freshness = src_attr.get("freshness")
            node["freshness"] = freshness if freshness is not None else config.get("freshness")
        if rt == "test" and test_meta is not None:
            node["test_metadata"] = test_meta
        return node

    def _load_test_metadata(self, con: Any) -> dict[str, dict[str, Any]]:
        """``{test_uid: {"namespace": …, "name": …}}`` from the test_metadata sidecar (empty if absent)."""
        path = self._dir / _FUSION_TEST_META
        if not path.exists():
            return {}
        rows = self._read_rows(con, path, ("unique_id", "test_name", "test_namespace"))
        return {r["unique_id"]: {"namespace": r.get("test_namespace"), "name": r.get("test_name")} for r in rows}

    def _load_metadata(self, con: Any) -> dict[str, Any]:
        """Best-effort ``metadata`` section (just ``project_name``, used by dependent_macro_files).

        Best-effort by design: ``project_name`` is not consumed by any boundary/coverage gate, only by
        the gha ``--macros`` path, so an older Fusion build without ``generation.parquet`` is not a
        gate failure (this is environment variance, not a dropped requirement)."""
        path = self._dir / _FUSION_GENERATION
        if not path.exists():
            return {}
        rows = self._read_rows(con, path, ("project_name",))
        return {"project_name": rows[0]["project_name"]} if rows else {}

    @staticmethod
    def _read_rows(con: Any, path: Path, columns: tuple[str, ...]) -> list[dict[str, Any]]:
        """Read exactly ``columns`` from one parquet file into a list of row dicts.

        The columns are validated against the file's schema first; a missing one raises a clear
        :class:`ValueError` naming the file and the column(s) — schema drift fails loudly, it does not
        silently produce an empty/partial section. Only the requested columns are projected (never
        ``SELECT *``) so the unused tz-aware ``ingested_at`` column is never materialised (see
        :data:`_NODE_COLUMNS`).
        """
        available = [d[0] for d in con.execute("SELECT * FROM read_parquet(?) LIMIT 0", [str(path)]).description]
        missing = [c for c in columns if c not in available]
        if missing:
            raise ValueError(
                f"parquet artifact '{path}' is missing required column(s) {missing} (has {available}); "
                "its schema does not match the verified dbt Fusion layout. See "
                "ParquetManifestArtifact docs and docs/dbt-fusion-artifacts.md."
            )
        col_sql = ", ".join(f'"{c}"' for c in columns)
        rel = con.execute(f"SELECT {col_sql} FROM read_parquet(?)", [str(path)])  # noqa: S608 (idents validated above)
        return [dict(zip(columns, row, strict=True)) for row in rel.fetchall()]

    def sections(self) -> dict[str, dict[str, Any]]:
        """Each manifest section as ``{unique_id: node dict}``, rebuilt from the parquet node table."""
        return self._sections

    def parent_map(self) -> dict[str, list[str]]:
        """child → [parents] lineage, derived from each node's ``depends_on`` (node ids only)."""
        return self._parent_map


def load_artifact(path: Path | str) -> ManifestArtifact:
    """Detect a dbt artifact set at ``path`` and return the matching reader.

    A *directory* is probed for a Fusion parse artifact set first (``metadata/parse/nodes/v1_0.parquet``)
    → :class:`ParquetManifestArtifact`; failing that, a ``manifest.json`` *inside* the directory →
    :class:`JsonManifestArtifact` (Fusion writes both, so the parquet probe wins to exercise the new
    format). A *file* path is read as JSON directly. A directory with neither raises a loud
    :class:`RuntimeError`.
    """
    p = Path(path)
    if p.is_dir():
        if (p / _FUSION_NODES).exists():
            return ParquetManifestArtifact(p)
        if (p / "manifest.json").exists():
            return JsonManifestArtifact.load(p / "manifest.json")
        raise RuntimeError(
            f"'{p}' is a directory with neither a Fusion parse artifact set ('{_FUSION_NODES}') nor a "
            "manifest.json file; cannot detect a dbt manifest artifact."
        )
    return JsonManifestArtifact.load(p)
