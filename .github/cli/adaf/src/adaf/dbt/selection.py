"""Model selection — resolve a scope to concrete model ``.sql`` paths.

Two inputs compose:

* **Scope** (mutually exclusive): ``--changed-only`` (default) or ``--all``.
* **Named selector** (``--selector``, required): the dbt selector that bounds the scope.
  Resolved by shelling out to ``dbt ls`` (see ``adaf.dbt.ls``) so the FULL dbt selector
  grammar is honoured rather than re-implemented.

The resolved set is the **overlap** of the two:

* ``--changed-only`` → git-changed model files that are ALSO in ``dbt ls --selector <name>``
* ``--all``         → every model in ``dbt ls --selector <name>``

That overlap can then be **grown along the lineage** with ``--upstream [n]`` / ``--downstream
[n]``: from the base member set, pull in ancestors up to ``upstream`` hops and descendants up to
``downstream`` hops (``UNBOUNDED`` when the bare flag is given — every ancestor/descendant). Both
default to ``None`` (no expansion), so the behaviour is identical to the overlap above unless a hop
flag is supplied. Hops are counted across the data backbone (model/source/seed/snapshot), but the
returned set is filtered back to models — the same shape the unexpanded resolution returns.
"""

# Standard Library
import argparse
from dataclasses import dataclass
from pathlib import Path

# Local
from adaf import config
from adaf.dbt.defer import defer_state_dir
from adaf.dbt.graph import DATA_RESOURCE_TYPES
from adaf.dbt.ls import ls_model_paths
from adaf.dbt.manifest_view import ManifestView
from adaf.dbt.state_modified import State, StateModified
from adaf.git.gitutil import changed_model_files

# Sentinel for a bare ``--upstream`` / ``--downstream`` (no count): expand without a hop limit.
UNBOUNDED = -1


@dataclass
class Selection:
    # `selector` has no default — it is a required CLI flag (be explicit about scope).
    selector: str
    all_models: bool = False
    base_ref: str = config.DEFAULT_BASE_REF
    defer: bool = False
    defer_ref: str = "main"
    target: str | None = None  # dbt --target (e.g. dev) for the live `dbt ls`
    # dbt --target for the defer-target parse (e.g. the base ref was deployed to `nonprod`).
    # Absent, it falls back to `target` (see `effective_defer_target`).
    defer_target: str | None = None
    # Lineage expansion: hops of ancestors / descendants to fold into the scope. ``None`` = no
    # expansion; ``UNBOUNDED`` = every ancestor/descendant; a positive int = that many hops.
    upstream: int | None = None
    downstream: int | None = None
    # State:modified scope mode (mutually exclusive with --changed-only / --all): bound the scope to
    # the models the offline calculator flags as changed vs the --defer-ref baseline (M), or M + their
    # descendants (M+). The selector itself resolves WITHOUT --state (Cloud-CLI-safe); the modified
    # decision is the faithful offline comparison (see adaf.dbt.state_modified).
    state_modified: bool = False
    state_modified_plus: bool = False
    # state:modified+ within the product, THEN all descendants (crossing the product boundary):
    # ``(selector ∩ state:modified+)+``. Inexpressible as one native dbt expression (the `+` can't bind
    # to an intersection result — the Atom Rule), so it is always resolved to paths + a `+` operator.
    state_modified_plus_plus: bool = False
    # Explicit baseline (the dir holding a prebuilt ``manifest.json``) for the state:modified comparison.
    # When set, it is used AS-IS instead of building one from ``--defer-ref`` via a git worktree — so a
    # caller (CI, the version-matrix harness) can supply a baseline without git, and the same dir flows
    # through to the emitted ``--state`` build flag. ``None`` ⇒ build it from ``--defer-ref``.
    state_dir_override: str | None = None

    @property
    def effective_defer_target(self) -> str | None:
        """The target the defer-target manifest is parsed under — ``defer_target`` if set, else ``target``."""
        return self.defer_target or self.target

    @property
    def scope_is_state_modified(self) -> bool:
        """Whether the scope is bounded by the offline ``state:modified`` calculator (M, M+, or (S∩M+)+)."""
        return self.state_modified or self.state_modified_plus or self.state_modified_plus_plus

    def baseline_state_dir(self, *, cwd: Path | None = None) -> Path:
        """The dir holding the baseline ``manifest.json`` for the state:modified comparison.

        ``--state <dir>`` (``state_dir_override``) wins and is used as-is (no git, no parse); otherwise
        the baseline is built + cached from ``--defer-ref`` (a git worktree parse — needs dbt-core)."""
        if self.state_dir_override:
            return Path(self.state_dir_override)
        if cwd is not None:
            return defer_state_dir(self.defer_ref, root=cwd, target=self.effective_defer_target)
        return defer_state_dir(self.defer_ref, target=self.effective_defer_target)

    @property
    def expands(self) -> bool:
        """Whether any lineage expansion (``--upstream`` / ``--downstream``) is active."""
        return self.upstream is not None or self.downstream is not None


def from_args(args: argparse.Namespace) -> Selection:
    """Build a Selection from parsed argparse flags (shared across every command)."""
    return Selection(
        selector=args.selector,  # argparse enforces --selector as required
        all_models=getattr(args, "all_models", False),
        base_ref=getattr(args, "base_ref", config.DEFAULT_BASE_REF),
        defer=getattr(args, "defer", False),
        defer_ref=getattr(args, "defer_ref", "main"),
        target=getattr(args, "target", None),
        defer_target=getattr(args, "defer_target", None),
        upstream=getattr(args, "upstream", None),
        downstream=getattr(args, "downstream", None),
        state_modified=getattr(args, "state_modified", False),
        state_modified_plus=getattr(args, "state_modified_plus", False),
        state_modified_plus_plus=getattr(args, "state_modified_plus_plus", False),
        state_dir_override=(str(s) if (s := getattr(args, "state", None)) else None),
    )


def _hop_phrase(hops: int, direction: str) -> str:
    """``'all upstream'`` / ``'2 hops downstream'`` for a hop count (``UNBOUNDED`` ⇒ ``all``)."""
    if hops == UNBOUNDED:
        return f"all {direction}"
    unit = "hop" if hops == 1 else "hops"
    return f"{hops} {unit} {direction}"


def describe(selection: Selection) -> str:
    """A short human label for the resolved scope."""
    if selection.state_modified_plus_plus:
        scope = f"(state:modified+ ∩ selector) + descendants vs {selection.defer_ref}"
    elif selection.state_modified_plus:
        scope = f"state:modified+ models vs {selection.defer_ref}"
    elif selection.state_modified:
        scope = f"state:modified models vs {selection.defer_ref}"
    elif selection.all_models:
        scope = "all models"
    else:
        scope = f"changed models vs {selection.base_ref}"
    label = f"{scope} that are also in selector:{selection.selector}"
    if selection.expands:
        parts = []
        if selection.upstream is not None:
            parts.append(_hop_phrase(selection.upstream, "upstream"))
        if selection.downstream is not None:
            parts.append(_hop_phrase(selection.downstream, "downstream"))
        label += " + " + " & ".join(parts)
    if selection.defer:
        label += f" (defer to {selection.defer_ref})"
    return label


def _walk(seeds: set[str], adjacency: dict[str, set[str]], hops: int) -> set[str]:
    """Breadth-first reach from ``seeds`` over ``adjacency`` for up to ``hops`` levels.

    ``hops == UNBOUNDED`` walks until the frontier is exhausted. Returns the reached nodes
    (excluding the seeds themselves). Terminates on any finite graph: ``seen`` only grows.
    """
    seen: set[str] = set()
    frontier = set(seeds)
    depth = 0
    while frontier and (hops == UNBOUNDED or depth < hops):
        nxt: set[str] = set()
        for node in frontier:
            for neighbour in adjacency.get(node, set()):
                if neighbour not in seen:
                    nxt.add(neighbour)
        seen |= nxt
        frontier = nxt
        depth += 1
    return seen


def _expand_hops(base: set[str], view: ManifestView, *, upstream: int | None, downstream: int | None) -> set[str]:
    """Grow ``base`` with up to ``upstream`` ancestor hops and ``downstream`` descendant hops over the
    data backbone, returning ``base`` ∪ reached **backbone nodes** (models AND sources/seeds/snapshots).

    Earlier this filtered the reached set to models only — which silently dropped source/seed/snapshot
    ancestors, so for a product whose only out-of-scope ancestors are dbt sources (the common staging-
    reads-source shape) ``--upstream`` added nothing and looked broken. Hop expansion now keeps every
    reached backbone node; callers that need a models-only view (e.g. :func:`resolve_model_ids`) filter
    at their own boundary. No expansion when both are ``None``.
    """
    if upstream is None and downstream is None:
        return set(base)
    present = set(view.of_type(*DATA_RESOURCE_TYPES))
    parents: dict[str, set[str]] = {}
    children: dict[str, set[str]] = {}
    for parent, child in view.parent_edges(present):
        children.setdefault(parent, set()).add(child)
        parents.setdefault(child, set()).add(parent)
    reached: set[str] = set()
    if upstream is not None:
        reached |= _walk(base, parents, upstream)
    if downstream is not None:
        reached |= _walk(base, children, downstream)
    return set(base) | (reached & present)


def _state_modified_model_paths(selection: Selection, *, cwd: Path) -> set[str]:
    """The selector's models that the offline calculator flags as ``state:modified`` (M) or
    ``state:modified+`` (M+), vs the ``--defer-ref`` baseline.

    The selector ``S`` resolves with a PLAIN ``dbt ls --selector`` (no ``--state`` — the dbt Cloud CLI
    has no such flag), and the modified decision is the faithful OFFLINE comparison of the cached
    baseline manifest against the current ``target/manifest.json`` (no ``dbt ls --select state:modified``
    shell-out). Building the baseline still needs dbt-core (``defer_state_dir`` parses a git worktree)."""
    scoped = ls_model_paths(selection.selector, cwd=cwd, target=selection.target)
    state_dir = selection.baseline_state_dir(cwd=cwd)
    current_path = config.under_root(config.DEFAULT_MANIFEST)
    assert current_path is not None  # DEFAULT_MANIFEST is a fixed relative path, never None
    current = State.load(current_path)
    sm = StateModified.compare(State.load(state_dir / "manifest.json"), current)
    # M when bare; M+ when --state-modified-plus OR --state-modified-plus-plus (which then expands).
    plus = selection.state_modified_plus or selection.state_modified_plus_plus
    base = scoped & sm.model_paths(plus=plus)
    if not selection.state_modified_plus_plus:
        return base
    # (S ∩ M+)+ : grow the in-product modified set with ALL descendants over the current lineage,
    # crossing the product boundary (a consumer of a changed mart, outside the selector, joins here).
    view = current.view
    models = view.of_type("model")
    base_uids = {uid for uid, rec in models.items() if str(rec.raw.get("original_file_path") or "") in base}
    reached = _expand_hops(base_uids, view, upstream=None, downstream=UNBOUNDED)
    expanded = {
        str(models[uid].raw.get("original_file_path"))
        for uid in reached
        if uid in models and models[uid].raw.get("original_file_path")
    }
    return base | expanded


def _base_model_paths(selection: Selection, *, cwd: Path) -> set[str]:
    """The UNEXPANDED overlap as a set of path strings — the (state:modified, changed-and-in-selector,
    or ``--all``) set before any ``--upstream`` / ``--downstream`` hop expansion is applied."""
    if selection.scope_is_state_modified:
        return _state_modified_model_paths(selection, cwd=cwd)
    # --defer resolves the selector against a baseline: honour an explicit --state dir (no git) the
    # same way the state-modified path does, falling back to a git-worktree parse of --defer-ref only
    # when no baseline is supplied. (Without --defer there is no baseline, so no --state.)
    state_dir = selection.baseline_state_dir(cwd=cwd) if selection.defer else None
    scoped = ls_model_paths(selection.selector, cwd=cwd, state_dir=state_dir, target=selection.target)
    if selection.all_models:
        return set(scoped)
    changed = {str(p) for p in changed_model_files(selection.base_ref, cwd=cwd)}
    return changed & scoped


def resolve_model_files(
    selection: Selection, *, cwd: Path | None = None, view: ManifestView | None = None
) -> list[Path]:
    """Resolve a Selection to a concrete, sorted list of model ``.sql`` paths.

    When ``--upstream`` / ``--downstream`` are set, the overlap is grown along the lineage: the
    expanded model unique_ids are mapped back to their ``original_file_path``. A ``view`` is used
    for that traversal; absent one, the manifest at ``config.DEFAULT_MANIFEST`` is loaded (and fails
    loud if missing — the hop flags are an explicit request, not a best-effort).
    """
    cwd = cwd or config.project_root()
    universe = _base_model_paths(selection, cwd=cwd)
    if selection.expands:
        if view is None:
            manifest = config.under_root(config.DEFAULT_MANIFEST)
            assert manifest is not None  # DEFAULT_MANIFEST is a fixed relative path, never None
            view = ManifestView.load(manifest)
        universe = _expand_file_scope(universe, selection, view)
    return sorted((Path(p) for p in universe), key=str)


def _expand_file_scope(paths: set[str], selection: Selection, view: ManifestView) -> set[str]:
    """Map ``paths`` → model ids, expand along the lineage, map the expanded models back to paths.

    Unions the expanded model paths onto the originals so any in-scope path that isn't a manifest
    model (e.g. a freshly added file) is preserved rather than dropped by the round-trip.
    """
    models = view.of_type("model")
    base = {uid for uid, rec in models.items() if str(rec.raw.get("original_file_path") or "") in paths}
    expanded = _expand_hops(base, view, upstream=selection.upstream, downstream=selection.downstream)
    # File-scoped gates act on model .sql files, so map only the reached MODELS back to paths; reached
    # sources/seeds/snapshots have no .sql to lint and are intentionally excluded here (they surface in
    # the id-based scope via `resolve_scope_ids`, e.g. for `list`).
    expanded_paths = {
        str(models[uid].raw.get("original_file_path"))
        for uid in expanded
        if uid in models and models[uid].raw.get("original_file_path")
    }
    return paths | expanded_paths


def resolve_model_ids(selection: Selection, view: ManifestView, *, cwd: Path | None = None) -> set[str]:
    """The scoped set as model ``unique_id``s — the SAME (changed-and-in-selector, or ``--all``)
    resolution as :func:`resolve_model_files`, mapped to unique_ids via each model's
    ``original_file_path`` in the manifest, then grown by any ``--upstream`` / ``--downstream`` hops.

    This is the shared scope primitive for the id-based checks (``sdag check``) so they
    subselect identically to the file-scoped gates — the gates consume the ``.sql`` paths,
    the id-based checks consume the unique_ids of the same set.
    """
    cwd = cwd or config.project_root()
    models = view.of_type("model")
    paths = _base_model_paths(selection, cwd=cwd)
    base = {uid for uid, rec in models.items() if str(rec.raw.get("original_file_path") or "") in paths}
    expanded = _expand_hops(base, view, upstream=selection.upstream, downstream=selection.downstream)
    # Models-only contract: hop expansion may reach sources/seeds/snapshots; keep just the models for
    # the model-centric checks (sdag check). `resolve_scope_ids` returns the rest.
    return expanded & set(models)


def base_model_files(selection: Selection, *, cwd: Path | None = None) -> set[str]:
    """The model ``.sql`` paths of the UNEXPANDED ``--selector`` overlap (before any hop expansion).

    Lets a command tell which of its resolved model files belong to the named data product itself vs
    which were pulled in by ``--upstream``/``--downstream`` (see :func:`external_model_files`)."""
    cwd = cwd or config.project_root()
    return _base_model_paths(selection, cwd=cwd)


def grouped_scope(
    selection: Selection, view: ManifestView, *, cwd: Path | None = None
) -> tuple[list[str], list[tuple[str, str | None]], list[tuple[str, str | None]]]:
    """Split the resolved scope into three ordered groups for ``list``:
    ``(selector_model_paths, upstream_added, downstream_added)``.

    * ``selector_model_paths`` — the base ``--selector`` model ``.sql`` paths (pre hop expansion).
    * ``upstream_added`` / ``downstream_added`` — nodes pulled in by ``--upstream`` / ``--downstream``,
      split by direction, each as ``(display, tag)``: a model → ``(original_file_path, None)``; a
      non-model (source/seed/snapshot) → ``(unique_id, resource_type)``.

    Both extra groups are empty when no hop flag is set. A node reachable both up- and downstream is
    listed once (under upstream)."""
    cwd = cwd or config.project_root()
    models = view.of_type("model")
    base_paths = _base_model_paths(selection, cwd=cwd)
    selector = sorted(base_paths)
    if not selection.expands:
        return selector, [], []
    base_ids = {uid for uid, rec in models.items() if str(rec.raw.get("original_file_path") or "") in base_paths}
    records = view.records()

    def _entries(added: set[str]) -> list[tuple[str, str | None]]:
        out: list[tuple[str, str | None]] = []
        for uid in sorted(added):
            if uid in models:
                out.append((str(models[uid].raw.get("original_file_path") or "") or uid, None))
            else:
                rec = records.get(uid)
                out.append((uid, rec.resource_type if rec else "?"))
        return out

    up = (
        _expand_hops(base_ids, view, upstream=selection.upstream, downstream=None) - base_ids
        if selection.upstream is not None
        else set()
    )
    down = (
        _expand_hops(base_ids, view, upstream=None, downstream=selection.downstream) - base_ids
        if selection.downstream is not None
        else set()
    )
    down -= up  # a node reachable both ways lists once, under upstream
    return selector, _entries(up), _entries(down)


def hop_context_nodes(selection: Selection, view: ManifestView, *, cwd: Path | None = None) -> list[tuple[str, str]]:
    """The NON-model nodes (sources/seeds/snapshots) that ``--upstream``/``--downstream`` pulled into
    scope, as sorted ``(unique_id, resource_type)`` pairs.

    These nodes have no ``.sql``, so the file-scoped gates (docscov, testcov, sqlfluff,
    deprecations) can't act on them — but a command that silently drops them makes a hop flag look
    like a no-op (e.g. ``--upstream 1`` on a product whose only out-of-scope ancestors are sources).
    Commands call this to DISCLOSE what the hop added so the flag is never invisible. Empty when no
    hop flag is set.
    """
    if not selection.expands:
        return []
    models = set(view.of_type("model"))
    records = view.records()
    added = resolve_scope_ids(selection, view, cwd=cwd) - models
    return [(uid, records[uid].resource_type if uid in records else "?") for uid in sorted(added)]


def resolve_scope_ids(selection: Selection, view: ManifestView, *, cwd: Path | None = None) -> set[str]:
    """The FULL expanded-backbone scope as unique_ids — models PLUS any sources/seeds/snapshots pulled
    in by ``--upstream`` / ``--downstream``. Unlike :func:`resolve_model_ids` (models only), this keeps
    every reached backbone node, so callers like ``list`` can show that a hop flag actually grew the
    scope across the model/source boundary. Identical to the models-only set when no hop flag is given.
    """
    cwd = cwd or config.project_root()
    models = view.of_type("model")
    paths = _base_model_paths(selection, cwd=cwd)
    base = {uid for uid, rec in models.items() if str(rec.raw.get("original_file_path") or "") in paths}
    return _expand_hops(base, view, upstream=selection.upstream, downstream=selection.downstream)
