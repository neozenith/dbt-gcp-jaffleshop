"""The I/O + format layer beneath :class:`~adaf.dbt.manifest_view.ManifestView`.

``ManifestView`` owns *normalisation* (records, edges); each projection owns *meaning*. This module
owns the layer below both: reading a dbt compiled-artifact set off disk and presenting it as the two
section/parent_map dicts the view consumes. Splitting it out is ADR-0022's seam extended one level
deeper — the *artifact* owns I/O + format, so the loading mechanism is swappable without the view or
any projection noticing.

Two readers live here. :class:`JsonManifestArtifact` holds the behaviour ``ManifestView`` used to do
inline (``json.loads`` of a ``manifest.json`` path). :class:`ParquetManifestArtifact` reads the columnar
parquet artifact set dbt v2.0 ("Fusion") emits, projecting its rows back into the same section dicts —
via duckdb, imported *inside the class only* so the JSON path (every user today) stays duckdb-free and a
missing duckdb on the parquet path is a loud :class:`ImportError` (``pip install 'adaf[fusion]'``), never
a silent fall back to JSON. :func:`load_artifact` detects which one to build.
"""

# Standard Library
import json
from pathlib import Path
from typing import Any, Protocol


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
    """dbt v2.0 ("Fusion") reader: a directory of ``*.parquet`` artifacts read with duckdb.

    **Assumed on-disk layout (ALPHA / UNVERIFIED — documented here, asserted at read time).** The real
    Fusion artifact schema is alpha and will churn, so this reader pins a *clear, explicit* layout and
    fails loudly if the parquet files don't match it rather than papering over drift:

    * **One parquet file per manifest section** under the target dir — ``nodes.parquet``,
      ``sources.parquet``, ``exposures.parquet``, ``semantic_models.parquet``, ``metrics.parquet`` —
      each row = one node. Missing section files are simply absent sections (a manifest needn't carry
      every section); present ones MUST have the required columns.
    * Each section row carries two **required** columns: ``unique_id`` (the node key) and ``node_json``
      (the node payload as a JSON string). Carrying the payload as JSON is deliberate: node dicts are
      deeply nested and field presence is alpha-unstable, so one opaque JSON column survives schema
      churn where a flattened column-per-field projection would not — ``json.loads`` reconstructs the
      exact dict the JSON path would have yielded, so the two readers are equivalent for the view.
    * **``parent_map.parquet``** carries dbt's compiled child → [parents] lineage: two **required**
      columns ``child`` (the node key) and ``parents`` (the parent id list as a JSON string). Absent
      → an empty parent_map (the view falls back to ``depends_on``), exactly like the JSON path.

    duckdb is imported **inside** this class (never at module top): the JSON path stays duckdb-free, and
    a missing duckdb on the parquet path raises a loud :class:`ImportError` pointing at the
    ``adaf[fusion]`` extra — never a silent fall back to JSON.
    """

    #: Section file stem → manifest section name (here the stem *is* the section name).
    _SECTION_FILES = ("nodes", "sources", "exposures", "semantic_models", "metrics")

    def __init__(self, target_dir: Path | str) -> None:
        try:
            # Third Party — feature-gated: ONLY the parquet path needs duckdb (see class docstring).
            import duckdb
        except ImportError as exc:  # loud, explicit — never a silent fall back to JSON
            raise ImportError(
                "Reading a dbt v2.0 (Fusion) parquet artifact set requires duckdb, which is not "
                "installed. Install the optional extra: pip install 'adaf[fusion]'."
            ) from exc

        self._dir = Path(target_dir)
        con = duckdb.connect(database=":memory:")
        try:
            sections: dict[str, dict[str, Any]] = {}
            for name in self._SECTION_FILES:
                path = self._dir / f"{name}.parquet"
                if not path.exists():
                    continue
                rows = self._read_rows(con, path, ("unique_id", "node_json"))
                sections[name] = {r["unique_id"]: json.loads(r["node_json"]) for r in rows}
            self._sections = sections

            pm_path = self._dir / "parent_map.parquet"
            if pm_path.exists():
                pm_rows = self._read_rows(con, pm_path, ("child", "parents"))
                self._parent_map = {r["child"]: list(json.loads(r["parents"])) for r in pm_rows}
            else:
                self._parent_map = {}
        finally:
            con.close()

    @staticmethod
    def _read_rows(con: Any, path: Path, required: tuple[str, ...]) -> list[dict[str, Any]]:
        """Read one parquet file into a list of row dicts, asserting hard on the ``required`` columns.

        A missing required column raises a clear :class:`ValueError` naming the file and the column(s) —
        alpha schema drift fails loudly here, it does not silently produce an empty/partial section.
        """
        rel = con.execute("SELECT * FROM read_parquet(?)", [str(path)])
        columns = [d[0] for d in rel.description]
        missing = [c for c in required if c not in columns]
        if missing:
            raise ValueError(
                f"parquet artifact '{path}' is missing required column(s) {missing} (has {columns}); "
                "its schema does not match the assumed dbt v2.0 (Fusion) layout."
            )
        return [dict(zip(columns, row, strict=True)) for row in rel.fetchall()]

    def sections(self) -> dict[str, dict[str, Any]]:
        """Each present manifest section as ``{unique_id: node dict}``, reconstructed from ``node_json``."""
        return self._sections

    def parent_map(self) -> dict[str, list[str]]:
        """dbt's compiled ``parent_map`` (child → [parents]); empty when ``parent_map.parquet`` is absent."""
        return self._parent_map


def load_artifact(path: Path | str) -> ManifestArtifact:
    """Detect a dbt artifact set at ``path`` and return the matching reader.

    Precedence (explicit > parquet presence > json): a *directory* containing ``*.parquet`` files is a
    dbt v2.0 ("Fusion") artifact set → :class:`ParquetManifestArtifact` (parquet presence wins);
    otherwise a ``manifest.json`` *file* → :class:`JsonManifestArtifact`. A directory with neither
    cannot be detected and raises a loud :class:`RuntimeError`.
    """
    p = Path(path)
    if p.is_dir():
        if list(p.glob("*.parquet")):
            return ParquetManifestArtifact(p)
        raise RuntimeError(
            f"'{p}' is a directory but contains no *.parquet artifacts and is not a manifest.json file; "
            "cannot detect a dbt manifest artifact."
        )
    return JsonManifestArtifact.load(p)
