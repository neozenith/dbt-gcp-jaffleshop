"""``sdag generate`` / ``sdag serve`` — the interactive data-product lineage viewer.

A "data product" is a NAMED selector in ``selectors.yml``. We resolve each selector's
membership via ``dbt ls`` (so the full selector grammar is honoured), read the entire
manifest, and build two Cytoscape JSON payloads — the full entity graph and a collapsed
super-graph — which `viewer.py` writes next to a templated HTML/JS viewer.

* ``generate`` writes the assets to ``--output`` (default ``tmp/sdag/``).
* ``serve`` regenerates first, then hosts them over HTTP so a reload always sees fresh assets.

As each selector is resolved on a cache miss, its members are also classified against the lineage
graph (``adaf.dbt.graph``) and the membership + boundary annotation is persisted to that selector's
own cache file (see ``adaf.dbt.cache``); ``adaf sdag check`` lints those boundaries.
"""

# Standard Library
import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# Local
from adaf import config
from adaf.dbt import cache
from adaf.dbt.graph import Graph
from adaf.dbt.ls import ls_member_ids
from adaf.dbt.manifest_view import ManifestView
from adaf.dbt.runner import dbt_parse
from adaf.dbt.selectors import load_selectors
from adaf.sdag import annotations, viewer

log = logging.getLogger(__name__)

# Sentinel for a bare ``--archive`` (no path): write the zip next to the assets as
# ``<output>/sdag.zip``. argparse stores this when the flag is given with no value (``const=``).
ARCHIVE_DEFAULT = "<output>/sdag.zip"

# `dbt ls` spawns a full dbt parse per call (hundreds of MB); cap concurrency so resolving
# ~80 selectors doesn't exhaust memory. IO/subprocess-bound, so a small pool still wins big.
_MAX_LS_WORKERS = min(12, (os.cpu_count() or 4))


def _maybe_parse(args: argparse.Namespace) -> None:
    """`dbt parse` only when warranted: never with --no-parse; otherwise only if the manifest
    is stale (a source file is newer than it). Avoids the slow reparse on a clean tree."""
    if not getattr(args, "parse", True):  # --no-parse: trust the existing manifest
        log.debug("sdag: --no-parse — using the existing manifest as-is")
        return
    if cache.manifest_is_fresh(args.manifest, config.project_root()):
        log.info("sdag: manifest is fresh (no source newer than it) — skipping `dbt parse`")
        return
    log.info("sdag: manifest stale or missing — running `dbt parse`")
    dbt_parse()


def _resolve_all(static: list[tuple[str, str]], args: argparse.Namespace, view: ManifestView) -> dict[str, set[str]]:
    """Resolve every static selector to its member ids — cache hits skip ``dbt ls``; the
    misses are resolved in parallel (bounded pool), with per-selector progress logging.

    On a miss, each selector's members are classified against the lineage graph (inbound /
    outbound / both / inner) and the membership + boundary annotation is persisted to that
    selector's own cache file (``tmp/adaf_cache/selectors/<selector>.json``)."""
    root = config.project_root()
    resolved: dict[str, set[str]] = {}
    todo: list[str] = []
    for name, _desc in static:
        entry = cache.load_selector(root, args.manifest, args.selectors, name)
        if entry is not None:
            resolved[name] = entry.members
        else:
            todo.append(name)
    log.info(
        "sdag: %d/%d selector(s) served from cache; resolving %d via `dbt ls`", len(resolved), len(static), len(todo)
    )
    if todo:
        # The lineage graph is needed only for the misses — derive it from the shared view.
        graph = Graph.from_view(view)
        done = 0
        with ThreadPoolExecutor(max_workers=min(_MAX_LS_WORKERS, len(todo))) as pool:
            futures = {pool.submit(ls_member_ids, name): name for name in todo}
            for future in as_completed(futures):
                name = futures[future]
                members = future.result()  # propagates a failed `dbt ls` (fail loud)
                resolved[name] = members
                # Persist members + boundary annotation to this selector's own inspectable file.
                boundaries = graph.classify(members)
                cache.save_selector(
                    root, args.manifest, args.selectors, name, cache.SelectorCacheEntry(members, boundaries)
                )
                done += 1
                log.info("sdag: [%d/%d] resolved selector %s (%d members)", done, len(todo), name, len(members))
    return resolved


def _build_viewer_graphs(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Resolve EVERY (static) named selector, read the full manifest, and build the two
    Cytoscape JSON payloads. The viewer always renders all data products."""
    _maybe_parse(args)
    log.debug("sdag: reading manifest %s", args.manifest)
    view = ManifestView.load(args.manifest)  # parse once; the viewer + boundary classify share it
    nodes, edges = viewer.display_graph(view)
    # A state:modified selector is a PR-diff selector, not a static data product — `dbt ls`
    # errors on it without --state — so the viewer can only render the static selectors.
    selectors = load_selectors(args.selectors)
    static = [(name, desc) for name, desc, uses_state, _def in selectors if not uses_state]
    skipped = [name for name, _desc, uses_state, _def in selectors if uses_state]
    # Each selector's resolution rule (e.g. `tag:demand`), embedded on its super-node so the viewer
    # sidebar can show why a node is in the product.
    definitions = {name: definition for name, _desc, uses_state, definition in selectors if not uses_state}
    if skipped:
        log.warning(
            "sdag: skipping %d state-based selector(s) not renderable without --state: %s",
            len(skipped),
            ", ".join(skipped),
        )
    resolved = _resolve_all(static, args, view)
    # Enrich each selector's cache file with the full sdag-check compliance results so the viewer
    # can render per-product compliance straight from the cache (members/boundaries are already
    # written by _resolve_all; this adds the obligation rollup + per-node annotations additively).
    root = config.project_root()
    annotations.enrich_all(root, view, resolved)
    # Read the compliance the enrich step just wrote back out of each selector's cache file and embed
    # it in the full graph so the viewer can render per-product compliance panels + per-node badges.
    compliance = viewer.load_selector_compliance(root, list(resolved))
    full_json = viewer.build_full_graph_json(nodes, edges, resolved, compliance)
    super_json = viewer.build_super_graph_json(nodes, edges, resolved, definitions=definitions)
    log.info("sdag: built graphs — %d nodes / %d edges across %d selector(s)", len(nodes), len(edges), len(resolved))
    return full_json, super_json, str(args.manifest)


def _archive_path(args: argparse.Namespace) -> Path | None:
    """Resolve the ``--archive`` option to a zip path, or ``None`` when not requested.

    Bare ``--archive`` (the :data:`ARCHIVE_DEFAULT` sentinel) → ``<output>/sdag.zip``;
    ``--archive PATH`` → ``PATH``."""
    archive = getattr(args, "archive", None)
    if archive is None:
        return None
    return args.output / "sdag.zip" if archive == ARCHIVE_DEFAULT else Path(archive)


def cmd_generate(args: argparse.Namespace) -> int:
    full_json, super_json, source_label = _build_viewer_graphs(args)
    if getattr(args, "inline", False):
        build_id = viewer.write_inline(args.output, full_json, super_json, source_label=source_label)
        target = args.output / viewer.SDAG_HTML
        print(f"sdag standalone written to {target} (build_id={build_id})", file=sys.stderr)
        print(f"open {target} directly in a browser — no server needed (inline)", file=sys.stderr)
    else:
        build_id = viewer.write_outputs(args.output, full_json, super_json, source_label=source_label)
        print(f"sdag assets written to {args.output} (build_id={build_id})", file=sys.stderr)
        print("run `adaf sdag serve` to host it (the multi-file viewer needs a server, not file://)", file=sys.stderr)
    zip_path = _archive_path(args)
    if zip_path is not None:
        entries = viewer.write_archive(args.output, zip_path)
        print(f"sdag archive written to {zip_path} ({len(entries)} entries: {', '.join(entries)})", file=sys.stderr)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    cmd_generate(args)  # always regenerate first so the served bundle is fresh
    viewer.serve(args.output, args.port)
    return 0
