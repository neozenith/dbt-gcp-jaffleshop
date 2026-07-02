"""Exhaustive parametrised tests for `adaf ls --flags` composition (`adaf.dbt.selectorflags`).

Covers the PURE composition (dbt graph-operator syntax + seed intersection + flag string) directly —
no dbt shell-out. `compose()`'s `dbt ls` calls are exercised by the real-project smoke, not here.
"""

# Third Party
import pytest

# First Party
from adaf.dbt.selection import UNBOUNDED, Selection, describe
from adaf.dbt.selectorflags import BuildFlags, apply_operators

A = "models/stg_orders.sql"
B = "models/fct_orders.sql"


# ── apply_operators: every dbt graph-operator shape ──────────────────────────────────────────────
@pytest.mark.parametrize(
    "upstream,downstream,expected",
    [
        (None, None, "m"),  # no expansion
        (1, None, "1+m"),  # N ancestors
        (2, None, "2+m"),
        (None, 1, "m+1"),  # N descendants
        (None, 3, "m+3"),
        (1, 2, "1+m+2"),  # both, bounded
        (UNBOUNDED, None, "+m"),  # bare --upstream ⇒ all ancestors
        (None, UNBOUNDED, "m+"),  # bare --downstream ⇒ all descendants
        (UNBOUNDED, UNBOUNDED, "+m+"),  # both unbounded
        (UNBOUNDED, 2, "+m+2"),  # mixed
        (0, 0, "0+m+0"),  # explicit zero hops pass through verbatim (caller's intent)
    ],
)
def test_apply_operators(upstream: int | None, downstream: int | None, expected: str) -> None:
    assert apply_operators("m", upstream, downstream) == expected


# ── BuildFlags rendering: select union + state/defer appending + empty seed ───────────────────────
@pytest.mark.parametrize(
    "select,state_dir,defer,expected",
    [
        ((), None, False, ""),  # empty seed ⇒ nothing to build
        ((), "d", True, ""),  # empty seed even when deferring
        (("a",), None, False, "--select a"),
        (("a", "b"), None, False, "--select a b"),  # union = space-separated
        (("a",), "d", True, "--select a --state d --defer"),
        (("a", "b"), "d", True, "--select a b --state d --defer"),
        (("a",), "d", False, "--select a"),  # state only when defer
    ],
)
def test_buildflags_str(select: tuple[str, ...], state_dir: str | None, defer: bool, expected: str) -> None:
    flags = BuildFlags(select=select, state_dir=state_dir, defer=defer)
    assert str(flags) == expected
    assert bool(flags) is (expected != "")  # falsy when there is nothing to build


def test_buildflags_native_1_12_selector_expression() -> None:
    # The dbt 1.12 native form: ONE select atom intersecting the named selector with state:modified+.
    flags = BuildFlags(select=("selector:matrix_demo,state:modified+",), state_dir="dir", defer=True)
    assert str(flags) == "--select selector:matrix_demo,state:modified+ --state dir --defer"


# ── BuildFlags.from_seed: the full seed → flags composition ───────────────────────────────────────
def test_from_seed_defer_intersects_modified_with_selector() -> None:
    # selector has {A, B}; only A changed ⇒ seed = {A}, deferring the rest.
    out = BuildFlags.from_seed({A, B}, {A, "models/other.sql"}, defer=True, state_dir="dir", upstream=None, downstream=None)
    assert out.select == (A,)
    assert str(out) == f"--select {A} --state dir --defer"


def test_from_seed_defer_downstream_applies_to_seed_path() -> None:
    # editing A with bare --downstream ⇒ A + all descendants (dbt traverses the graph from A).
    out = BuildFlags.from_seed({A, B}, {A}, defer=True, state_dir="dir", upstream=None, downstream=UNBOUNDED)
    assert str(out) == f"--select {A}+ --state dir --defer"


def test_from_seed_defer_empty_seed_when_nothing_modified_in_scope() -> None:
    # A non-product model changed (not in the selector) ⇒ empty seed ⇒ empty flags (caller skips build).
    out = BuildFlags.from_seed({A, B}, {"models/unrelated.sql"}, defer=True, state_dir="dir", upstream=None, downstream=2)
    assert out.empty
    assert str(out) == ""


def test_from_seed_non_defer_is_whole_selector() -> None:
    # no --defer ⇒ seed is every model in the selector (modified is ignored / None).
    out = BuildFlags.from_seed({A, B}, None, defer=False, state_dir=None, upstream=None, downstream=1)
    assert str(out) == f"--select {B}+1 {A}+1"  # sorted: fct_orders < stg_orders


def test_from_seed_paths_are_sorted_deterministic() -> None:
    out = BuildFlags.from_seed({B, A}, {A, B}, defer=True, state_dir="dir", upstream=1, downstream=UNBOUNDED)
    assert str(out) == f"--select 1+{B}+ 1+{A}+ --state dir --defer"  # B sorts before A


# ── --state-modified[-plus] scope mode (pure: the Selection label + predicate) ───────────────────
def test_state_modified_scope_describe_and_predicate() -> None:
    m = Selection(selector="demand", state_modified=True, defer_ref="main")
    mp = Selection(selector="demand", state_modified_plus=True, defer_ref="main")
    mpp = Selection(selector="demand", state_modified_plus_plus=True, defer_ref="main")
    plain = Selection(selector="demand")
    assert m.scope_is_state_modified and mp.scope_is_state_modified and mpp.scope_is_state_modified
    assert not plain.scope_is_state_modified
    assert "state:modified models vs main" in describe(m)
    assert "state:modified+ models vs main" in describe(mp)
    assert "+ descendants vs main" in describe(mpp)  # (S ∩ M+)+ crosses the product boundary
