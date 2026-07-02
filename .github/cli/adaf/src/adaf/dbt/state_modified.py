"""A faithful, offline re-implementation of dbt's ``state:modified`` over two manifests.

``adaf`` used to delegate the modified decision entirely to ``dbt ls --select state:modified``.
This module is the faithful alternative: a PURE function that reads a baseline + current
``manifest.json`` (already parsed to dicts) and computes the modified set itself — no warehouse, no
adapter, no ``dbt`` subprocess. dbt's ``WritableManifest`` already serialises every field the
comparison needs (``raw_code``, ``unrendered_config``, ``checksum``, ``fqn``, ``contract.checksum``,
per-macro ``macro_sql``, ``depends_on.macros``), so two JSON files are sufficient.

Ported verbatim from dbt-core 1.11.11 (see
``docs/research/resources/state-modified-calculator.md`` for the porting spec and the file:line
citations). The guiding rule is **faithful beats correct**: where dbt has a quirk (a new *source* is
NOT modified; ``Metric`` filter/metadata are ``TODO return True`` stubs) this matches the quirk
rather than "fixing" it — the job is to agree with ``dbt ls`` bug-for-bug.

Scope (v1): the data backbone (``model`` / ``seed`` / ``snapshot`` / ``source``) and generic tests
are compared with their type-specific facet ladders; other resource types fall back to the base
ladder. That is sufficient for the build seed (``--flags``) and ``ls --defer``, both of which act on
models. Fusion (v2.0) parquet manifests are out of scope — they do not serialise ``unrendered_config``
or ``raw_code`` (``dbt.artifact.ParquetManifestArtifact``), so this module requires dbt-core JSON.

The primary API is two dataclasses: :class:`State` (a parsed manifest, leaning on
:class:`~adaf.dbt.manifest_view.ManifestView` for all loading + node mechanics) and
:class:`StateModified` (the verdict comparing a baseline ``State`` to a current one — ``M``, ``M+``,
and the model-path projections the build seed and ``ls --defer`` consume). Thin module-level
functions wrap them for simple callers (and the hand-built-manifest unit tests).
"""

# Standard Library
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Local
from adaf.dbt.manifest_view import ManifestView, NodeRecord

# dbt config keys compared SEPARATELY by ``same_database_representation`` (database/schema/alias) or
# excluded from the content comparison entirely (tags/group are ``CompareBehavior.Exclude``). They are
# subtracted from the ``same_config`` key set so a renamed alias/schema doesn't double-count.
# Source: ``dbt/contracts/graph/model_config.py`` CompareBehavior.Exclude + same_database_representation.
_CONFIG_EXCLUDE = frozenset({"alias", "schema", "database", "tags", "group"})

# The database-coordinate keys ``same_database_representation`` reads off ``unrendered_config``.
_RELATION_KEYS = ("database", "schema", "alias")


# ── individual facet comparisons (each: are these two nodes the same on THIS axis?) ──────────────


def _same_body(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """``same_body`` — the authored template ``raw_code`` (pre-compile, pre-Jinja)."""
    return new.get("raw_code") == old.get("raw_code")


def _same_seeds(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """``same_seeds`` — a seed's ``checksum`` object (FileHash); the SeedNode override of same_body."""
    return new.get("checksum") == old.get("checksum")


def _same_config(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """``same_config`` — ``unrendered_config`` minus the excluded keys, ``.get``-comparing each key.

    ``.get`` (not dict ``==``) is deliberate: dbt's ``compare_key`` treats a missing key as ``None``,
    so an unset key on one side equals an explicit ``None`` on the other.
    """
    nu = new.get("unrendered_config") or {}
    ou = old.get("unrendered_config") or {}
    keys = (set(nu) | set(ou)) - _CONFIG_EXCLUDE
    return all(nu.get(k) == ou.get(k) for k in keys)


def _same_database_representation(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """``same_database_representation`` — database/schema/alias read off ``unrendered_config``."""
    nu = new.get("unrendered_config") or {}
    ou = old.get("unrendered_config") or {}
    return all(nu.get(k) == ou.get(k) for k in _RELATION_KEYS)


def _same_fqn(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """``same_fqn`` — the fully-qualified-name path list."""
    return new.get("fqn") == old.get("fqn")


def _same_persisted_description(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """``same_persisted_description`` — only counts when ``persist_docs`` is on; else always same.

    Relation docs gate the model ``description``; column docs gate each column's ``description``.
    """
    persist = ((new.get("config") or {}).get("persist_docs")) or {}
    if persist.get("relation") and new.get("description") != old.get("description"):
        return False
    if persist.get("columns"):
        ncols = new.get("columns") or {}
        ocols = old.get("columns") or {}
        for name in set(ncols) | set(ocols):
            if (ncols.get(name) or {}).get("description") != (ocols.get(name) or {}).get("description"):
                return False
    return True


def _same_contract(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """``same_contract`` (models) — an ``enforced`` transition or a ``contract.checksum`` change.

    Faithful to the modified-set membership (the boolean), not to dbt's breaking-change *raise* for
    versioned models — reproducing the exception is a documented non-goal (NG: see the spec).
    """
    nc = new.get("contract") or {}
    oc = old.get("contract") or {}
    if not nc.get("enforced") and not oc.get("enforced"):
        return True
    if nc.get("enforced") != oc.get("enforced"):
        return False
    return nc.get("checksum") == oc.get("checksum")


def _same_ref_representation(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """``same_ref_representation`` (models) — how downstream refs resolve: version/access/deprecation."""
    return (
        new.get("latest_version") == old.get("latest_version")
        and new.get("access") == old.get("access")
        and new.get("deprecation_date") == old.get("deprecation_date")
    )


def _same_quoting(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """``same_quoting`` (sources) — the identifier quoting policy."""
    return new.get("quoting") == old.get("quoting")


def _same_freshness(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """``same_freshness`` (sources) — the freshness policy and its ``loaded_at_field``."""
    return new.get("freshness") == old.get("freshness") and new.get("loaded_at_field") == old.get("loaded_at_field")


def _same_external(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """``same_external`` (sources) — the external-table descriptor."""
    return new.get("external") == old.get("external")


# Facet name -> comparator, per resource type. The list order mirrors dbt's ``same_contents`` AND-chain.
# Each facet name doubles as the human-readable reason emitted when it differs.
def _facet_diffs(new: dict[str, Any], old: dict[str, Any], rtype: str) -> list[str]:
    """The facet names on which ``new`` differs from ``old`` — the per-type ``same_contents`` ladder.

    Empty list ⇒ the nodes are the same on every facet (``same_contents`` is True). The type dispatch
    mirrors the dbt class overrides: ``SourceDefinition`` has its own ladder; ``SeedNode`` swaps body
    for ``same_seeds``; ``GenericTestNode`` compares only config+fqn; ``ModelNode`` adds contract +
    ref-representation; everything else uses the base six-facet ladder.
    """
    if rtype == "source":
        checks = [
            ("relation", _same_database_representation),
            ("fqn", _same_fqn),
            ("config", _same_config),
            ("quoting", _same_quoting),
            ("freshness", _same_freshness),
            ("external", _same_external),
        ]
    elif rtype == "test":  # generic data test: config + fqn only (singular tests would use the base ladder)
        checks = [("config", _same_config), ("fqn", _same_fqn)]
    else:
        body = _same_seeds if rtype == "seed" else _same_body
        checks = [
            ("body", body),
            ("config", _same_config),
            ("persisted_descriptions", _same_persisted_description),
            ("relation", _same_database_representation),
            ("fqn", _same_fqn),
        ]
        if rtype == "model":
            checks += [("contract", _same_contract), ("ref_representation", _same_ref_representation)]
    return [name for name, same in checks if not same(new, old)]


# ── macro closure (recursive, macro_sql only) ────────────────────────────────────────────────────


def _modified_macros(baseline_macros: dict[str, Any], current_macros: dict[str, Any]) -> set[str]:
    """The macro unique_ids whose ``macro_sql`` changed, plus any added or removed macro.

    Only ``macro_sql`` is compared — dbt's ``Macro.same_contents`` is "the only thing that makes one
    macro different is its content". ``arguments``/``name``/``patch_path`` are intentionally ignored.
    """
    modified = {
        uid
        for uid, m in current_macros.items()
        if (baseline_macros.get(uid) or {}).get("macro_sql") != m.get("macro_sql")
    }
    modified |= {uid for uid in baseline_macros if uid not in current_macros}  # removed
    return modified


def _depends_macros(node: dict[str, Any]) -> list[str]:
    """A node's directly-declared macro dependencies (``depends_on.macros``)."""
    return list((node.get("depends_on") or {}).get("macros") or [])


def _macro_closure_modified(node: dict[str, Any], current_macros: dict[str, Any], modified_macros: set[str]) -> bool:
    """Whether any macro in ``node``'s RECURSIVE ``depends_on.macros`` closure was modified.

    Mirrors dbt's ``recursively_check_macros_modified``: walk the node's macros, and each macro's own
    ``depends_on.macros``, until a modified one is found or the closure is exhausted. A ``None`` macro
    id raises (dbt raises ``CompilationError``) — escalators-not-stairs, never a silent skip.
    """
    seen: set[str] = set()
    stack = _depends_macros(node)
    while stack:
        uid = stack.pop()
        if uid is None:  # dbt: a macro dependency that never resolved is a compile error, not a skip
            raise ValueError(f"node '{node.get('unique_id')}' depends on an unresolved (None) macro id")
        if uid in seen:
            continue
        seen.add(uid)
        if uid in modified_macros:
            return True
        macro = current_macros.get(uid)
        if macro is not None:
            stack.extend(_depends_macros(macro))
    return False


# ── State + StateModified (the ergonomic representation) ──────────────────────────────────────────


@dataclass(frozen=True)
class State:
    """A parsed dbt manifest as the calculator sees it — comparable nodes, macros, and lineage.

    A thin envelope over :class:`~adaf.dbt.manifest_view.ManifestView`: it owns NO manifest
    mechanics, delegating section parsing, source-defaulted resource types, and ``parent_map`` edges
    to the view so a manifest-schema change is absorbed in exactly one place. Construct from a path
    (:meth:`load`, via the Fusion-aware artifact seam) or a parsed dict (:meth:`from_manifest`).
    """

    view: ManifestView

    @classmethod
    def load(cls, path: Path | str) -> "State":
        """Load a manifest from disk via the artifact seam (fails loud if missing; Fusion-aware)."""
        return cls(ManifestView.load(path))

    @classmethod
    def from_manifest(cls, data: dict[str, Any]) -> "State":
        """Build from an already-parsed manifest dict (the hand-built-manifest unit tests use this)."""
        return cls(ManifestView.from_dict(data))

    @property
    def records(self) -> dict[str, NodeRecord]:
        """Every comparable node (``nodes`` + ``sources``) keyed by unique_id, resource_type resolved."""
        return self.view.records()

    @property
    def macros(self) -> dict[str, Any]:
        """The ``macros`` section keyed by unique_id (each carries ``macro_sql`` + ``depends_on``)."""
        return self.view.section("macros")

    @property
    def models(self) -> dict[str, NodeRecord]:
        """The ``model`` nodes keyed by unique_id — for projecting a verdict back to ``.sql`` paths."""
        return self.view.of_type("model")

    def child_map(self) -> dict[str, set[str]]:
        """``{parent_uid: {child_uids}}`` over the lineage — the descendant adjacency ``M+`` walks."""
        children: dict[str, set[str]] = {}
        for parent, child in self.view.parent_edges():
            children.setdefault(parent, set()).add(child)
        return children


def _expand_descendants(direct: dict[str, list[str]], child_map: dict[str, set[str]]) -> dict[str, list[str]]:
    """BFS the lineage from the directly-modified nodes, tagging reached descendants ``["downstream"]``."""
    result = dict(direct)
    seen = set(direct)
    frontier = set(direct)
    while frontier:
        nxt: set[str] = set()
        for node_id in frontier:
            for child in child_map.get(node_id, ()):
                if child not in seen:
                    seen.add(child)
                    nxt.add(child)
                    result.setdefault(child, ["downstream"])
        frontier = nxt
    return result


@dataclass(frozen=True)
class StateModified:
    """The ``state:modified`` verdict between a baseline and a current :class:`State`.

    ``direct`` is ``M`` (``{unique_id: [reason facets]}``); ``plus`` is ``M+`` (``M`` plus every
    lineage descendant, the extra ones tagged ``["downstream"]``). The ``model_*`` projections map
    either verdict to the project-relative ``.sql`` paths the build seed and ``ls --defer`` consume.
    """

    direct: dict[str, list[str]]
    plus: dict[str, list[str]]
    current: State

    @classmethod
    def compare(cls, baseline: State, current: State) -> "StateModified":
        """Compute ``M`` and ``M+`` by comparing ``current`` against ``baseline`` (the faithful port).

        A node is modified when its per-type ``same_contents`` differs on any facet OR a macro in its
        recursive closure changed (``"macros"``) OR it is new (``"new"``). A NEW *source* is NOT
        modified (dbt's ``SourceDefinition.same_contents(None)`` is True). Removed nodes are never
        emitted (dbt compares them only for breaking-change side effects).
        """
        base_nodes = {uid: rec.raw for uid, rec in baseline.records.items()}
        macros = current.macros
        modified_macros = _modified_macros(baseline.macros, macros)
        direct: dict[str, list[str]] = {}
        for uid, rec in current.records.items():
            new = rec.raw
            old = base_nodes.get(uid)
            reasons: list[str] = []
            if old is None:
                if rec.resource_type != "source":  # new non-source ⇒ modified; new source ⇒ not (dbt quirk)
                    reasons.append("new")
            else:
                reasons.extend(_facet_diffs(new, old, rec.resource_type))
            if _macro_closure_modified(new, macros, modified_macros) and "macros" not in reasons:
                reasons.append("macros")
            if reasons:
                direct[uid] = reasons
        return cls(direct=direct, plus=_expand_descendants(direct, current.child_map()), current=current)

    def verdict(self, *, plus: bool) -> dict[str, list[str]]:
        """The ``{unique_id: reasons}`` map — ``M+`` when ``plus`` else ``M``."""
        return self.plus if plus else self.direct

    def model_reasons(self, *, plus: bool) -> dict[str, list[str]]:
        """``{original_file_path: reasons}`` for the modified MODELS (``ls --defer`` reads this)."""
        out: dict[str, list[str]] = {}
        for uid, reasons in self.verdict(plus=plus).items():
            rec = self.current.models.get(uid)
            path = rec and rec.raw.get("original_file_path")
            if path:
                out[str(path)] = reasons
        return out

    def model_paths(self, *, plus: bool) -> set[str]:
        """The modified MODEL ``.sql`` paths — the seed the ``--flags`` build intersects."""
        return set(self.model_reasons(plus=plus))


# ── thin module-level wrappers (back-compat; simple callers + hand-built-manifest unit tests) ─────


def modified(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, list[str]]:
    """``M`` from two manifest dicts — see :meth:`StateModified.compare`."""
    return StateModified.compare(State.from_manifest(baseline), State.from_manifest(current)).direct


def modified_plus(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, list[str]]:
    """``M+`` from two manifest dicts — see :meth:`StateModified.compare`."""
    return StateModified.compare(State.from_manifest(baseline), State.from_manifest(current)).plus


def modified_model_reasons(baseline: dict[str, Any], current: dict[str, Any], *, plus: bool) -> dict[str, list[str]]:
    """``{original_file_path: reasons}`` for modified models — see :meth:`StateModified.model_reasons`."""
    return StateModified.compare(State.from_manifest(baseline), State.from_manifest(current)).model_reasons(plus=plus)


def modified_model_paths(baseline: dict[str, Any], current: dict[str, Any], *, plus: bool) -> set[str]:
    """The modified MODEL ``.sql`` paths — see :meth:`StateModified.model_paths`."""
    return StateModified.compare(State.from_manifest(baseline), State.from_manifest(current)).model_paths(plus=plus)
