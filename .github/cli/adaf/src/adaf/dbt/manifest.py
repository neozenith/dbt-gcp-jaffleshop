"""Read dbt's ``manifest.json`` into the minimal shape the coverage checks need.

The manifest is dbt's compiled source of truth. We extract just two things per model:

* its documentation — the model ``description`` plus each declared column's description;
* its test count — derived by walking every ``test`` node's ``depends_on.nodes`` and
  tallying hits per model (one model can be referenced by many test nodes).

Keying models by ``original_file_path`` lets us join directly against the git
"changed files" set, whose paths are already project-relative (e.g. ``models/staging/stg_orders.sql``).
"""

# Standard Library
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelDoc:
    """The doc/test facts about a single dbt model, distilled from its manifest node."""

    unique_id: str
    name: str
    original_file_path: str
    description: str
    columns: dict[str, str] = field(default_factory=dict)  # column name -> description
    test_count: int = 0


class Manifest:
    """A thin, queryable view over the model nodes of a dbt manifest."""

    def __init__(self, models_by_id: dict[str, ModelDoc]) -> None:
        self._by_id = models_by_id

    @classmethod
    def load(cls, path: Path | str) -> "Manifest":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, data: dict) -> "Manifest":
        nodes = data.get("nodes", {})
        models: dict[str, ModelDoc] = {}
        for uid, node in nodes.items():
            if node.get("resource_type") != "model":
                continue
            columns = {name: (col.get("description") or "") for name, col in (node.get("columns") or {}).items()}
            models[uid] = ModelDoc(
                unique_id=uid,
                name=node.get("name", ""),
                original_file_path=node.get("original_file_path", ""),
                description=node.get("description") or "",
                columns=columns,
            )
        # Second pass: attribute each test node to the model(s) it depends on.
        for node in nodes.values():
            if node.get("resource_type") != "test":
                continue
            for dep in (node.get("depends_on") or {}).get("nodes", []):
                model = models.get(dep)
                if model is not None:
                    model.test_count += 1
        return cls(models)

    def by_path(self) -> dict[str, ModelDoc]:
        """Map ``original_file_path`` -> ModelDoc, for joining against changed files."""
        return {m.original_file_path: m for m in self._by_id.values()}

    def models(self) -> list[ModelDoc]:
        return list(self._by_id.values())
