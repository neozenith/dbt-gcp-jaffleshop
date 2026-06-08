"""The ADAF rule catalogue — the single source of truth.

``catalog.json`` (validated by ``catalog.schema.json``) defines every taxonomy
rule and its metadata. Every consumer derives from here so nothing can drift:

* ``adaf check taxonomy`` reads ``detection`` to know which rules it gates;
* ``adaf review`` builds the LLM prompt catalogue AND injects ``rule_codes()``
  into the output schema's ``rule_code`` enum at call time;
* the docs vignettes are pointed to by each rule's ``doc``;
* the developer skill maps findings → DAMA dimension + vignette.

Loaded via ``importlib.resources`` so the data ships in the wheel and resolves
identically from source (``uv run``) or installed (``uvx``).
"""

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

_PKG = "adaf.rules"
_CATALOG = "catalog.json"
_SCHEMA = "catalog.schema.json"
_REVIEW_SCHEMA = "review-output.schema.json"


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    """The whole catalogue document (version, reference dicts, rules)."""
    return json.loads((files(_PKG) / _CATALOG).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    """The catalogue's JSON Schema (the field spec / validator)."""
    return json.loads((files(_PKG) / _SCHEMA).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_review_schema() -> dict[str, Any]:
    """The `adaf review` LLM output contract (the on-disk enum is a stale placeholder — it is
    overwritten from the catalogue by ``review_response_format`` before every call)."""
    return json.loads((files(_PKG) / _REVIEW_SCHEMA).read_text(encoding="utf-8"))


def review_response_format() -> dict[str, Any]:
    """The GitHub Models ``response_format`` for a review, with the ``rule_code`` enum injected
    from the catalogue so the LLM's allowed rule codes can NEVER drift from the SSoT — the core
    no-drift invariant of ADR-0005 (previously enforced only inside the review action)."""
    schema = json.loads(json.dumps(load_review_schema()))  # deep copy before mutating
    (schema["properties"]["models"]["items"]["properties"]["findings"]["items"]["properties"]["rule_code"][
        "enum"
    ]) = rule_codes()
    for k in ("$schema", "title", "description"):
        schema.pop(k, None)
    return {"type": "json_schema", "json_schema": {"name": "testing_taxonomy_review", "strict": True, "schema": schema}}


def all_rules() -> list[dict[str, Any]]:
    """Every rule, in catalogue order."""
    return load_catalog()["rules"]


def rule_codes() -> list[str]:
    """Ordered rule codes — the exact set injected into the review output schema's
    ``rule_code`` enum, so the catalogue and the LLM's allowed outputs can't drift."""
    return [r["code"] for r in all_rules()]


def get_rule(code: str) -> dict[str, Any] | None:
    """One rule by code, or ``None`` if unknown."""
    return next((r for r in all_rules() if r["code"] == code), None)


def validate_catalog() -> list[str]:
    """Validate ``catalog.json`` against its meta-schema.

    Returns a sorted list of human-readable error strings; an empty list means the
    catalogue is valid. This is the programmatic form of the SSoT guard.
    """
    validator = Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(load_catalog()), key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors]
