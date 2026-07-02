"""Regression tests for lineage hop expansion against a SOURCE-FED product (T26 / T27).

The hop bug (T26) was that ``--upstream`` / ``--downstream`` was a silent no-op for a product
whose only out-of-scope 1-hop ancestors are dbt *sources*: ``_expand_hops`` filtered its reached
set down to models, dropping every source it had just walked to. It shipped because the existing
suite (``test_selectors.py``) only exercised the pure ``_expand_hops`` helper against a tiny
models-only chain — never the realistic shape that actually failed: a product of models fed by
sources, with downstream consumer models hanging off it.

This module closes that gap by exercising the REAL resolution code in :mod:`adaf.dbt.selection`
against a committed, realistic ``manifest.json`` fixture (loaded through the real
:meth:`ManifestView.load` JSON path — no network, no dbt, belongs in ``make ci``). The fixture's
backbone is exactly the failure shape::

    source.s1 ─▶ stg_a ┐
                        ├─▶ fct ─▶ downstream_consumer   (downstream_consumer is OUTSIDE the product)
    source.s2 ─▶ stg_b ┘
    product (tagged) = {stg_a, stg_b, fct}

Offline-testability limitation (handled WITHOUT mocks)
------------------------------------------------------
The PUBLIC entry points :func:`resolve_model_ids` / :func:`resolve_scope_ids` /
:func:`resolve_model_files` cannot be driven offline: each first calls ``_base_model_paths`` →
``ls_model_paths`` which shells out to ``dbt ls`` (and, for ``--changed-only``, ``changed_model_files``
which shells ``git``). Per the project's no-mocks rule (``.claude/rules/python/tests.md``) we do NOT
patch that subprocess away. Instead we test the exact pure seams those functions delegate to AFTER
the dbt-dependent base resolution:

* :func:`_expand_hops` — where the regression lived (the dropped-sources filter); drives the
  id-level scope. ``resolve_scope_ids`` returns its result verbatim; ``resolve_model_ids`` returns it
  intersected with the model set; both first build ``base`` from ``_base_model_paths`` via the same
  ``original_file_path`` lookup we reproduce in :func:`_base_ids_from_paths` below.
* :func:`_expand_file_scope` — the real round-trip ``resolve_model_files`` uses (paths → model ids →
  expand → back to model ``.sql`` paths).

So the dbt-dependent ``_base_model_paths`` step is the ONLY thing not exercised here; everything
downstream of it (the part that carried the bug) is covered against the real functions.
"""

# Standard Library
from pathlib import Path

# Third Party
import pytest

# First Party
from adaf.dbt.manifest_view import ManifestView
from adaf.dbt.selection import (
    UNBOUNDED,
    Selection,
    _expand_file_scope,
    _expand_hops,
)

FIXTURE = Path(__file__).parent / "fixtures" / "manifest_source_fed_product.json"

# Backbone ids in the fixture (see module docstring).
STG_A = "model.adaf_demo.stg_a"
STG_B = "model.adaf_demo.stg_b"
FCT = "model.adaf_demo.fct"
CONSUMER = "model.adaf_demo.downstream_consumer"
SRC_1 = "source.adaf_demo.raw.s1"
SRC_2 = "source.adaf_demo.raw.s2"

# The tagged data product: models fed ONLY by sources at their 1-hop boundary.
PRODUCT = {STG_A, STG_B, FCT}

# original_file_path of each product model — the join key `_base_model_paths` would feed in.
PRODUCT_PATHS = {"models/staging/stg_a.sql", "models/staging/stg_b.sql", "models/marts/fct.sql"}
FCT_PATH = {"models/marts/fct.sql"}


@pytest.fixture
def view() -> ManifestView:
    """The real ManifestView loaded from the committed fixture via the on-disk JSON path."""
    return ManifestView.load(FIXTURE)


def _base_ids_from_paths(view: ManifestView, paths: set[str]) -> set[str]:
    """Reproduce the EXACT base-id derivation `resolve_model_ids` / `resolve_scope_ids` perform.

    Both functions build ``base`` as the model unique_ids whose ``original_file_path`` is in the
    (dbt-resolved) path set. Reproducing only that one line lets the tests start from a path set —
    the way the public functions do — without invoking ``dbt ls``.
    """
    models = view.of_type("model")
    return {uid for uid, rec in models.items() if str(rec.raw.get("original_file_path") or "") in paths}


def _scope_ids(view: ManifestView, paths: set[str], *, upstream: int | None, downstream: int | None) -> set[str]:
    """Mirror of :func:`resolve_scope_ids`'s body (full backbone scope, sources kept)."""
    base = _base_ids_from_paths(view, paths)
    return _expand_hops(base, view, upstream=upstream, downstream=downstream)


def _model_ids(view: ManifestView, paths: set[str], *, upstream: int | None, downstream: int | None) -> set[str]:
    """Mirror of :func:`resolve_model_ids`'s body (scope intersected back to models only)."""
    models = view.of_type("model")
    return _scope_ids(view, paths, upstream=upstream, downstream=downstream) & set(models)


# ─── sanity: the path→id mapping the resolve_* functions rely on ───────────────


def test_product_paths_map_to_product_models(view: ManifestView) -> None:
    assert _base_ids_from_paths(view, PRODUCT_PATHS) == PRODUCT


# ─── the T26 regression: scope crosses the model/source boundary ───────────────


def test_scope_upstream1_crosses_source_boundary(view: ManifestView) -> None:
    """`resolve_scope_ids`-shape: --upstream 1 pulls in the source ancestors the base lacked.

    This is the exact regression — for a source-fed product the base set has no out-of-scope models
    upstream, only sources, so the dropped-sources bug made --upstream add NOTHING.
    """
    base = _scope_ids(view, PRODUCT_PATHS, upstream=None, downstream=None)
    expanded = _scope_ids(view, PRODUCT_PATHS, upstream=1, downstream=None)

    assert base == PRODUCT  # no expansion ⇒ just the product
    assert {SRC_1, SRC_2} <= expanded  # the sources crossed in
    assert expanded - base == {SRC_1, SRC_2}  # and they are exactly what the hop added


def test_demand_shape_grows_by_exactly_its_source_ancestors(view: ManifestView) -> None:
    """The demand shape specifically: a base whose ONLY 1-hop ancestors are sources grows by exactly
    those sources — no more, no fewer (no models leak in, no sources are dropped)."""
    base = _base_ids_from_paths(view, PRODUCT_PATHS)
    expanded = _expand_hops(base, view, upstream=1, downstream=None)
    assert expanded - base == {SRC_1, SRC_2}


# ─── resolve_model_ids contract: models-only, but still grows on model lineage ──


def test_model_ids_upstream1_stays_models_only_for_source_fed_product(view: ManifestView) -> None:
    """models-only view of the SAME --upstream 1: the sources are filtered back out, so a source-fed
    product's model set is unchanged (this is correct — it is also why the scope view above matters)."""
    models_only = _model_ids(view, PRODUCT_PATHS, upstream=1, downstream=None)
    assert models_only == PRODUCT
    assert not (models_only & {SRC_1, SRC_2})  # no source ever leaks into the models-only set


def test_model_ids_grows_when_upstream_models_exist(view: ManifestView) -> None:
    """When the 1-hop ancestors ARE models, the models-only set genuinely grows: from {fct} alone,
    --upstream 1 reaches stg_a and stg_b (its model parents)."""
    base = _model_ids(view, FCT_PATH, upstream=None, downstream=None)
    grown = _model_ids(view, FCT_PATH, upstream=1, downstream=None)
    assert base == {FCT}
    assert grown == {FCT, STG_A, STG_B}


def test_model_ids_downstream1_includes_consumer(view: ManifestView) -> None:
    """--downstream 1 from {fct} pulls in the out-of-product consumer model."""
    grown = _model_ids(view, FCT_PATH, upstream=None, downstream=1)
    assert grown == {FCT, CONSUMER}


# ─── hop COUNT is honoured (1 vs unbounded vs 0/None) ──────────────────────────


def test_hop_count_one_vs_unbounded_differ(view: ManifestView) -> None:
    one = _scope_ids(view, FCT_PATH, upstream=1, downstream=None)
    unbounded = _scope_ids(view, FCT_PATH, upstream=UNBOUNDED, downstream=None)
    assert one == {FCT, STG_A, STG_B}  # 1 hop: only the direct model parents
    assert unbounded == {FCT, STG_A, STG_B, SRC_1, SRC_2}  # all the way up to the sources
    assert one != unbounded


def test_zero_and_none_hops_are_just_base(view: ManifestView) -> None:
    base = _scope_ids(view, FCT_PATH, upstream=None, downstream=None)
    assert base == {FCT}
    assert _scope_ids(view, FCT_PATH, upstream=0, downstream=0) == {FCT}


# ─── _expand_file_scope: the real path round-trip resolve_model_files uses ──────


def test_file_scope_downstream_includes_consumer_sql(view: ManifestView) -> None:
    """`resolve_model_files`-shape: --downstream 1 from the fct file adds the consumer's .sql path."""
    sel = Selection(selector="demand", all_models=True, downstream=1)
    expanded = _expand_file_scope(FCT_PATH, sel, view)
    assert "models/marts/downstream_consumer.sql" in expanded
    assert FCT_PATH <= expanded


def test_file_scope_upstream_includes_model_parents_excludes_sources(view: ManifestView) -> None:
    """File scope adds upstream MODEL .sql paths but NOT sources — sources have no .sql to lint, so
    the file-scoped gates correctly never receive them (the id scope above is where they surface)."""
    sel = Selection(selector="demand", all_models=True, upstream=1)
    expanded = _expand_file_scope(FCT_PATH, sel, view)
    assert {"models/staging/stg_a.sql", "models/staging/stg_b.sql"} <= expanded
    # The source's _sources.yml must never be pulled in as a model path.
    assert "models/staging/_sources.yml" not in expanded


def test_file_scope_source_fed_product_upstream_is_unchanged(view: ManifestView) -> None:
    """A source-fed product expanded --upstream 1 at the FILE layer is unchanged: its only ancestors
    are sources (no .sql), so the file-scoped gate sees exactly the product files — the regression is
    only observable at the id/scope layer, which is why `resolve_scope_ids` exists."""
    sel = Selection(selector="demand", all_models=True, upstream=1)
    expanded = _expand_file_scope(PRODUCT_PATHS, sel, view)
    assert expanded == PRODUCT_PATHS
