"""Read named selectors out of dbt's ``selectors.yml`` (ruamel round-trip).

Shared by the sdag viewer (which products to render) and ``gha create`` (validating the
product name). ruamel preserves comments + ordering, which matters when other tooling
round-trips the same file.
"""

# Standard Library
import io
from pathlib import Path
from typing import Any

# Third Party
from ruamel.yaml import YAML

_yaml = YAML()


def _uses_state(definition: Any) -> bool:
    """True if a selector definition references the ``state`` method (e.g. ``state:modified``).

    Such selectors are PR-diff selectors — ``dbt ls`` errors on them without ``--state`` — so
    the sdag viewer skips them (they aren't static data products)."""
    if isinstance(definition, str):
        return "state:" in definition
    if isinstance(definition, dict):
        if str(definition.get("method", "")).lower() == "state":
            return True
        return any(_uses_state(v) for v in definition.values())
    if isinstance(definition, list):
        return any(_uses_state(v) for v in definition)
    return False


def _definition_str(definition: Any) -> str:
    """A display-ready YAML string for a selector's ``definition`` (``tag:demand`` stays as-is; a
    structured union/intersection definition is rendered as block YAML for the viewer's code block)."""
    if definition is None:
        return ""
    if isinstance(definition, str):
        return definition
    buf = io.StringIO()
    _yaml.dump(definition, buf)  # ruamel CommentedMap/Seq → block-style YAML, key order preserved
    return buf.getvalue().strip()


def load_selectors(path: Path | str) -> list[tuple[str, str, bool, str]]:
    """Read named selectors from ``selectors.yml`` → ``[(name, description, uses_state, definition), ...]``.

    ``definition`` is the selector's resolution rule (e.g. ``tag:demand``) as a display string — the
    sdag viewer embeds it on each selector's super-node so the sidebar can show *why* a node is in
    the product."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"selectors file not found at '{p}'. Expected dbt's selectors.yml.")
    data = _yaml.load(p.read_text(encoding="utf-8")) or {}
    sels = data.get("selectors") or []
    if not isinstance(sels, list):
        raise ValueError(f"selectors.yml: top-level `selectors` must be a list, got {type(sels).__name__}")
    out: list[tuple[str, str, bool, str]] = []
    for sel in sels:
        name = sel.get("name") if isinstance(sel, dict) else None
        if not name:
            raise ValueError(f"selector missing `name`: {sel!r}")
        definition = sel.get("definition")
        out.append((name, (sel.get("description") or "").strip(), _uses_state(definition), _definition_str(definition)))
    return out


def selector_names(path: Path | str) -> list[str]:
    """Just the names of the named selectors, in file order."""
    return [name for name, _desc, _state, _def in load_selectors(path)]
