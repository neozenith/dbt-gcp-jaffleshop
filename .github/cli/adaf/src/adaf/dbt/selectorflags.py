"""`adaf ls --flags` — emit the dbt ``--select``/``--state``/``--defer`` flags to feed ``dbt build``.

The named selector is the **entry point** into the graph; the emitted flags select a *seed* of models
and let dbt traverse the lineage from it (ADR-0030):

* **with ``--defer``, no hops** (the canonical CI build path): the seed is the intersection
  ``selector ∩ state:modified+`` (``S ∩ M+`` — the changed-in-product models AND their in-product
  descendants), the SAME set ``adaf ls --defer`` previews. ``M+`` is computed offline by the faithful
  calculator (:mod:`adaf.dbt.state_modified`) over the baseline + current manifests — no second
  ``dbt ls`` shell-out — and ``S`` still resolves via one ``dbt ls --selector``. The seed is emitted as
  concrete ``<path>`` atoms (dbt graph operators can't attach to the *result* of an intersection);
  ``--state <defer-dir> --defer`` is appended so unchanged refs defer to the baseline. An empty seed
  (nothing modified in scope) emits an empty string — the caller skips the build.
* **with ``--defer`` AND ``--upstream`` / ``--downstream``**: the cross-boundary mode. The seed is the
  DIRECT change set ``S ∩ M`` and each path gets a graph operator (``N+``/``+N``, bare ⇒ ``+``) so dbt
  traverses out of the product from the change ( ``(S ∩ M)+`` / ``+(S ∩ M)`` — a non-product model
  downstream of a changed product model DOES build). This is the distinct interface for the operator-on-
  intersection shape the Atom Rule forbids expressing in one expression.
* **without ``--defer``**: the seed is every model in the selector (hops still attach as operators).

The shell-out lives in :func:`compose`; the pure composition (seed intersection, operator attachment,
flag rendering) is the :class:`BuildFlags` dataclass — its :meth:`BuildFlags.from_seed` is what the
exhaustive parametrised suite drives directly, and ``str(flags)`` / :meth:`BuildFlags.to_args` are the
one mapping to a real ``dbt build`` invocation.
"""

# Standard Library
from dataclasses import dataclass, field
from pathlib import Path

# Local
from adaf import config
from adaf.dbt.defer import defer_state_dir
from adaf.dbt.ls import ls_model_paths
from adaf.dbt.selection import UNBOUNDED, Selection
from adaf.dbt.state_modified import State, StateModified
from adaf.dbt.version import supports_selector_method


def _operator(hops: int | None, *, prefix: bool) -> str:
    """The dbt graph operator for ``hops``: ``None`` ⇒ ``""``; ``UNBOUNDED`` ⇒ ``"+"``; ``N`` ⇒ ``"N+"``
    (prefix, upstream) or ``"+N"`` (suffix, downstream)."""
    if hops is None:
        return ""
    if hops == UNBOUNDED:
        return "+"
    return f"{hops}+" if prefix else f"+{hops}"


def apply_operators(atom: str, upstream: int | None, downstream: int | None) -> str:
    """Attach the upstream/downstream graph operators to a single selection ``atom`` (pure).

    ``2+atom`` (2 ancestors), ``atom+`` (all descendants), ``1+atom+3``, etc. — exactly dbt's syntax."""
    return f"{_operator(upstream, prefix=True)}{atom}{_operator(downstream, prefix=False)}"


@dataclass(frozen=True)
class BuildFlags:
    """The resolved ``dbt build`` selection — one value that maps 1:1 to a dbt invocation.

    ``select`` holds the operator-applied seed atoms (space-unioned into one ``--select``); ``state_dir``
    + ``defer`` carry the deferral coordinates. :meth:`from_seed` is the curated composition (intersect
    the selector with the modified set, sort, attach graph operators, attach state/defer); :meth:`to_args`
    / ``str()`` render the dbt flag string. An empty ``select`` is falsy — "nothing to build" — so the
    caller can ``if flags: ...`` exactly as before.
    """

    select: tuple[str, ...]
    state_dir: str | None = None
    defer: bool = field(default=False)

    @classmethod
    def from_seed(
        cls,
        in_selector: set[str],
        modified: set[str] | None,
        *,
        defer: bool,
        state_dir: str | None,
        upstream: int | None,
        downstream: int | None,
    ) -> "BuildFlags":
        """Curate the build flags from the resolved sets (the PURE composition — no dbt, test-driven).

        The seed is ``in_selector ∩ modified`` when deferring (build only the changed-in-product set),
        else the whole selector. Each seed path gets the upstream/downstream graph operators; the result
        is sorted for determinism. An empty seed yields empty (falsy) flags.
        """
        seed = (in_selector & modified) if (defer and modified is not None) else in_selector
        atoms = tuple(apply_operators(path, upstream, downstream) for path in sorted(seed))
        return cls(select=atoms, state_dir=state_dir if defer else None, defer=defer)

    @property
    def empty(self) -> bool:
        """True when there is nothing to build (no seed atoms)."""
        return not self.select

    def to_args(self) -> list[str]:
        """The dbt CLI argument list: ``--select <atoms…>`` then ``--state <dir> --defer`` when deferring."""
        if not self.select:
            return []
        args = ["--select", *self.select]
        if self.defer and self.state_dir is not None:
            args += ["--state", self.state_dir, "--defer"]
        return args

    def __bool__(self) -> bool:
        return not self.empty

    def __str__(self) -> str:
        return " ".join(self.to_args())


def _offline_modified(state_dir: Path, *, plus: bool) -> set[str]:
    """The modified model paths (M or M+) from the cached baseline vs the current ``target/manifest.json``
    — the offline calculator, no ``dbt ls --select state:modified`` shell-out."""
    current_path = config.under_root(config.DEFAULT_MANIFEST)
    assert current_path is not None  # DEFAULT_MANIFEST is a fixed relative path, never None
    return StateModified.compare(State.load(state_dir / "manifest.json"), State.load(current_path)).model_paths(
        plus=plus
    )


def compose(sel: Selection) -> BuildFlags:
    """Resolve the seed and return the :class:`BuildFlags` for ``sel``.

    Three modes, all leaning on the offline calculator for the modified decision:

    * ``--state-modified`` / ``--state-modified-plus``: seed = ``S ∩ M`` / ``S ∩ M+``, with ``S``
      resolved by a PLAIN ``dbt ls --selector`` (Cloud-CLI-safe) — the recommended flag-generation path.
    * ``--defer`` (no scope flag): the canonical ``S ∩ M+``, but ``S`` resolves via ``dbt ls --state``
      (dbt-core only); hops switch the seed to ``S ∩ M`` plus per-path operators (the cross-boundary mode).
    * neither: the whole selector (one ``dbt ls --selector``).

    The first two emit ``--state <dir> --defer`` so a downstream ``dbt build`` defers unchanged refs.
    """
    if sel.scope_is_state_modified:
        state_dir = sel.baseline_state_dir()
        in_selector = ls_model_paths(sel.selector, target=sel.target)  # plain ls — no --state (Cloud-CLI-safe)
        if sel.state_modified_plus_plus:
            # (S ∩ M+)+ — descendants of the in-product modified set, crossing the boundary. Inexpressible
            # natively (the `+` can't bind to an intersection result, the Atom Rule), so ALWAYS resolved
            # to `<path>+` atoms (each seed path unioned with all its descendants).
            seed = in_selector & _offline_modified(state_dir, plus=True)
            return BuildFlags.from_seed(
                seed, None, defer=True, state_dir=str(state_dir), upstream=None, downstream=UNBOUNDED
            )
        plus = sel.state_modified_plus
        # dbt 1.12+ intersects the named selector with state:modified in ONE native expression; ≤1.11
        # (and the Cloud CLI, undetectable) cannot, so backport by resolving S ∩ M[+] to paths offline.
        # Hops force the backport on every engine too — `(S ∩ M)+` is inexpressible natively (Atom Rule).
        if not sel.expands and supports_selector_method(sel.selector):
            atom = f"selector:{sel.selector},state:modified" + ("+" if plus else "")
            return BuildFlags(select=(atom,), state_dir=str(state_dir), defer=True)
        seed = in_selector & _offline_modified(state_dir, plus=plus)
        return BuildFlags.from_seed(
            seed, None, defer=True, state_dir=str(state_dir), upstream=sel.upstream, downstream=sel.downstream
        )

    if not sel.defer:
        in_selector = ls_model_paths(sel.selector, target=sel.target)
        return BuildFlags.from_seed(
            in_selector, None, defer=False, state_dir=None, upstream=sel.upstream, downstream=sel.downstream
        )

    state_dir = defer_state_dir(sel.defer_ref, target=sel.effective_defer_target)
    in_selector = ls_model_paths(sel.selector, state_dir=state_dir, target=sel.target)
    # Canonical default uses M+ (the `+` is baked into the seed, no per-path operator); the hop modes
    # expand the DIRECT change set M out of the product via operators ((S ∩ M)+ / +(S ∩ M)).
    modified = _offline_modified(state_dir, plus=not sel.expands)
    return BuildFlags.from_seed(
        in_selector,
        modified,
        defer=True,
        state_dir=str(state_dir),
        upstream=sel.upstream,
        downstream=sel.downstream,
    )
