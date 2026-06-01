"""Read dbt's catalog.json — the RESOLVED (actual warehouse) columns per model.

`dbt docs generate` queries the warehouse information schema to build catalog.json, so its
column set is the model's ACTUAL columns — unlike manifest.json, which only knows the columns
DECLARED in YAML. The `columns` check joins the two: the actual column set (catalog) against
which of those columns carry a description (manifest YAML). Generating the catalog therefore
requires a warehouse build/connection, which `dbt parse` does not.
"""

# Standard Library
import json
from pathlib import Path


class Catalog:
    """The actual (warehouse-resolved) columns of each model, keyed by ``unique_id``."""

    def __init__(self, columns_by_id: dict[str, list[str]]) -> None:
        self._by_id = columns_by_id

    @classmethod
    def load(cls, path: Path | str) -> "Catalog":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, data: dict) -> "Catalog":
        by_id = {uid: list((node.get("columns") or {}).keys()) for uid, node in data.get("nodes", {}).items()}
        return cls(by_id)

    def columns_for(self, unique_id: str) -> list[str] | None:
        """Actual columns for a model (in catalog/index order); None if it isn't catalogued."""
        return self._by_id.get(unique_id)
