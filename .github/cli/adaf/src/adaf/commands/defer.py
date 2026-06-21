"""``adaf defer-diff`` — show which models are BUILT vs DEFERRED under a selector.

Against a defer-target baseline (the parsed manifest of ``--defer-ref``, built + cached by
``adaf.dbt.defer``):

* **Built** = the models in dbt's authoritative ``state:modified+`` set that are also in the
  selector — models that differ from the baseline (and their children), which a deferred
  ``dbt build`` would actually run.
* **Deferred** = the rest of the selector's scope — unchanged vs the baseline, so dbt resolves
  their refs to the baseline relations instead of rebuilding them.

``deepdiff`` explains *why* each built model is modified (which node facet changed: the file
``checksum``, its ``config``, ``columns``, or ``depends_on``), turning the build/defer split
into something a reviewer can actually read.
"""

# Standard Library
import argparse
import difflib
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Third Party
from deepdiff import DeepDiff

# Local
from adaf import config, report
from adaf.dbt.defer import defer_state_dir
from adaf.dbt.ls import ls_select_paths
from adaf.dbt.manifest_view import ManifestView
from adaf.dbt.runner import dbt_parse
from adaf.dbt.scope import base_model_files, describe, from_args, hop_context_nodes, resolve_model_files

log = logging.getLogger(__name__)

# Node facets that drive a "would be rebuilt" decision (the same shape dbt's state:modified
# weighs): file content hash, resolved config, declared columns, and upstream refs.
_DIFF_KEYS = ("checksum", "config", "columns", "depends_on")


def _model_nodes_by_path(manifest_path: Path) -> dict[str, dict[str, Any]]:
    """Index a manifest's model nodes by their project-relative ``original_file_path``."""
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return {
        node.get("original_file_path", ""): node
        for node in (data.get("nodes") or {}).values()
        if node.get("resource_type") == "model"
    }


def _why_modified(baseline_node: dict[str, Any], current_node: dict[str, Any]) -> list[str]:
    """Which node facets changed between baseline and current (the deepdiff explanation)."""
    return [key for key in _DIFF_KEYS if DeepDiff(baseline_node.get(key), current_node.get(key), ignore_order=True)]


def _facet_diff_lines(baseline_node: dict[str, Any], current_node: dict[str, Any], *, color: bool) -> list[str]:
    """A colourised, git-style unified diff of each CHANGED node facet (for ``--details``).

    For every facet that differs (checksum/config/columns/depends_on), pretty-print the baseline and
    current values as sorted JSON and run :func:`difflib.unified_diff` over them — then colour the
    hunk like ``git diff``: added lines green, removed red, ``@@`` headers cyan, context dimmed. This
    turns "BUILT (config)" into the actual field-level change a reviewer can read.
    """
    lines: list[str] = []
    for facet in _DIFF_KEYS:
        before, after = baseline_node.get(facet), current_node.get(facet)
        if not DeepDiff(before, after, ignore_order=True):
            continue
        before_s = json.dumps(before, indent=2, sort_keys=True, default=str).splitlines()
        after_s = json.dumps(after, indent=2, sort_keys=True, default=str).splitlines()
        hunk = difflib.unified_diff(
            before_s, after_s, fromfile=f"{facet} @baseline", tofile=f"{facet} @current", lineterm=""
        )
        for ln in hunk:
            if ln.startswith("+"):
                lines.append(report.colorize(ln, "green", color))
            elif ln.startswith("-"):
                lines.append(report.colorize(ln, "red", color))
            elif ln.startswith("@@"):
                lines.append(report.colorize(ln, "cyan", color))
            else:
                lines.append(report.colorize(ln, "dim", color))
    return lines


def _defer_target(args: argparse.Namespace) -> str | None:
    """The target the defer-target parse runs under: ``--defer-target`` if given, else ``--target``."""
    return getattr(args, "defer_target", None) or getattr(args, "target", None)


def cmd_defer_state(args: argparse.Namespace) -> int:
    """Build (or reuse the cache of) the defer-target state for ``--defer-ref`` and print its dir.

    The lone stdout line is the ``--state`` directory, so CI can capture it for a downstream
    ``dbt build --state "$(adaf defer-state …)"``. Progress/logging goes to stderr.
    """
    state_dir = defer_state_dir(args.defer_ref, target=_defer_target(args), force=getattr(args, "force", False))
    print(state_dir)  # stdout: the one machine-readable line (the resolved --state dir)
    return 0


def cmd_defer_diff(args: argparse.Namespace) -> int:
    root = config.project_root()
    sel = from_args(args)
    target = sel.target
    if getattr(args, "parse", False):
        dbt_parse(target=target)
    # The defer-target manifest is parsed under --defer-target (falls back to --target); the live
    # `dbt ls` of the current tree uses --target.
    state_dir = defer_state_dir(args.defer_ref, root=root, target=sel.effective_defer_target)

    # Scope is the SHARED selection — the same --selector / changed-or---all / --upstream /
    # --downstream resolution every other check uses — so the built-vs-deferred split is bounded to
    # exactly the reviewer's slice rather than the whole selector.
    scope = {str(p) for p in resolve_model_files(sel, cwd=root)}
    modified = ls_select_paths("state:modified+", state_dir=state_dir, target=target)  # dbt's built set
    built = sorted(scope & modified)
    deferred = sorted(scope - modified)

    base_nodes = _model_nodes_by_path(state_dir / "manifest.json")
    cur_nodes = _model_nodes_by_path(args.manifest)

    color = report.should_colorize(args.color, sys.stdout)
    report.render_headline(
        f"# defer-diff — {describe(sel)} vs {args.defer_ref} — {len(built)} built / {len(deferred)} deferred",
        color=color,
        severity="info",
    )
    # Disclose non-model nodes a hop flag pulled into scope. defer-diff acts on buildable MODELS, so
    # sources/seeds/snapshots in `N+selector` have no built/deferred status — but listing them keeps
    # `--upstream`/`--downstream` from looking like a no-op when a product's only out-of-scope
    # ancestors are sources (e.g. `--selector demand --upstream 1`).
    hop_ctx = hop_context_nodes(sel, ManifestView.load(args.manifest), cwd=root)
    if hop_ctx:
        report.render_headline(
            f"hop context: {len(hop_ctx)} upstream/downstream non-model node(s) in scope "
            "(no .sql — shown for context, not built/deferred):",
            color=color,
            severity="info",
        )
        for uid, rtype in hop_ctx:
            report.render_note(f"{uid}  [{rtype}]", color=color, indent=2)
    # Models pulled in by --upstream/--downstream that are OUTSIDE the named selector render in a
    # darker grey — context, not the product itself. (scope already holds the expanded model files.)
    external = scope - base_model_files(sel, cwd=root)
    details = getattr(args, "details", False)

    def _grey_if_external(path: str) -> str | None:
        # External (hop-added) models are tinted blue — a distinct hue marking "context from outside
        # the product", clear of the BUILT (amber) / DEFERRED (green) section colours.
        return "blue" if path in external else None

    report.render_headline(
        f"BUILT ({len(built)}) — differ from {args.defer_ref}, would be rebuilt:", color=color, severity="warn"
    )
    for path in built:
        if path in base_nodes:
            why = _why_modified(base_nodes[path], cur_nodes.get(path, {})) or ["changed"]
        else:
            why = ["new model (absent in baseline)"]
        finding = report.Finding(
            path=path, severity="warn", code="BUILT", message=f"({', '.join(why)})", path_color=_grey_if_external(path)
        )
        print(report.render_finding(finding, color=color))
        if details and path in base_nodes:  # git-diff-style field-level changes under the finding
            for ln in _facet_diff_lines(base_nodes[path], cur_nodes.get(path, {}), color=color):
                print(f"  {ln}")
    report.render_headline(
        f"DEFERRED ({len(deferred)}) — unchanged vs {args.defer_ref}, resolved to the baseline:",
        color=color,
        severity="ok",
    )
    deferred_findings = [
        report.Finding(path=path, severity="ok", code="DEFERRED", path_color=_grey_if_external(path))
        for path in deferred
    ]
    report.render_findings(deferred_findings, color=color)
    return 0
