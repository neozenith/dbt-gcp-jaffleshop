"""``adaf list`` (alias ``ls``) — print the resolved target model files for a product scope.

The dry-run preview of every product-scoped command's target set: resolve the scope (changed or
``--all`` models that are also in the named ``--selector``, optionally grown by ``--upstream`` /
``--downstream`` hops) and print the model ``.sql`` files the gates would run on.

Sections are distinguished by HUE, not grey shades: selector models are neutral grey (**light**
when modified vs git, **dark** when not), ``--upstream`` nodes are **amber**, ``--downstream``
nodes are **green** (the retro DAG palette). Non-model hop nodes carry a ``[type]`` tag.

``--macros`` also lists the repo macros the selected models depend on; ``--paths`` previews the gha
trigger globs a ``--paths`` mode would emit and highlights (dark red) the false-positive files those
globs would also match beyond the selector's own members.
"""

# Standard Library
import argparse
import logging
import sys

# Local
from adaf import config, report
from adaf.dbt import scope
from adaf.dbt.ls import ls_model_paths
from adaf.dbt.manifest_view import ManifestView
from adaf.gha import globber
from adaf.gitutil import changed_model_files

log = logging.getLogger(__name__)


def _selector_line(path: str, *, changed: set[str], color: bool) -> str:
    """A selector model's listing line: LIGHT grey if modified vs git, DARK grey if unmodified."""
    return report.colorize(path, "white" if path in changed else "grey", color)


def _context_line(display: str, tag: str | None, *, color: bool, hue: str = "grey") -> str:
    """A hop-added node's listing line, coloured by its section HUE (amber upstream / green
    downstream), with a matching ``[type]`` tag for non-model nodes (sources/seeds/snapshots)."""
    text = report.colorize(display, hue, color)
    return f"{text}  {report.colorize(f'[{tag}]', hue, color)}" if tag else text


def list_targets(
    scope_label: str,
    selector: list[str],
    *,
    color: bool = False,
    bare: bool = False,
    changed: set[str] | None = None,
    upstream: list[tuple[str, str | None]] | None = None,
    downstream: list[tuple[str, str | None]] | None = None,
) -> int:
    """Print the resolved scope, GROUPED like ``defer-diff`` (group titles to STDERR, paths to STDOUT).

    When ``--upstream``/``--downstream`` add nodes, each direction gets its own ``== … ==`` group title.
    ``bare`` drops ALL group titles and prints one flat, pipeable path list (selector then extras).
    """
    changed = changed or set()
    upstream = upstream or []
    downstream = downstream or []
    total = len(selector) + len(upstream) + len(downstream)
    noun = "node(s)" if (upstream or downstream) else "model(s)"
    report.render_headline(f"# {scope_label} — {total} {noun}", color=color, severity="info")

    if bare or (not upstream and not downstream):
        # Flat list: no group titles. (Also the shape when there's nothing extra to group.)
        for path in selector:
            print(_selector_line(path, changed=changed, color=color))
        for display, tag in upstream:
            print(_context_line(display, tag, color=color, hue="yellow"))
        for display, tag in downstream:
            print(_context_line(display, tag, color=color, hue="green"))
        return 0

    # Grouped: a titled section per group, titles on STDERR so STDOUT stays a clean path stream.
    def _group(title: str, lines: list[str]) -> None:
        report.render_headline(f"== {title} ==", color=color, severity="info")
        for line in lines:
            print(line)
        sys.stdout.flush()  # keep group order deterministic when STDOUT is piped (titles are on STDERR)

    _group(f"selector models ({len(selector)})", [_selector_line(p, changed=changed, color=color) for p in selector])
    if upstream:
        _group(f"upstream ({len(upstream)})", [_context_line(d, t, color=color, hue="yellow") for d, t in upstream])
    if downstream:
        down_lines = [_context_line(d, t, color=color, hue="green") for d, t in downstream]
        _group(f"downstream ({len(downstream)})", down_lines)
    return 0


def _git_changed_models(base_ref: str, cwd) -> set[str]:
    """Changed-vs-git model paths for the `list` two-tone highlight — or EMPTY when git context is
    unavailable.

    The highlight inherently needs a git baseline; running against a non-repo (e.g. the multiversion
    Docker fixture) or without the `git` binary means there is no "changed" set to compute. That must
    NOT break `list` (whose core job is to list the scope) — so we degrade the *adornment* (no
    highlight), never the *command*. Only the two git-absence signals are caught; any other error
    still surfaces.
    """
    try:
        return {str(p) for p in changed_model_files(base_ref, cwd=cwd)}
    except (FileNotFoundError, RuntimeError) as exc:
        log.debug("git unavailable (%s); listing without changed-file highlight", exc)
        return set()


def cmd_list(args: argparse.Namespace) -> int:
    sel = scope.from_args(args)
    color = report.should_colorize(args.color, sys.stdout)
    root = config.project_root()
    manifest = config.under_root(config.DEFAULT_MANIFEST)
    assert manifest is not None  # DEFAULT_MANIFEST is a fixed relative path
    view = ManifestView.load(manifest)
    # Split the scope into selector models + the upstream/downstream nodes a hop flag added, so each
    # direction can be a titled group (and the hop nodes render as their own hue).
    selector, upstream, downstream = scope.grouped_scope(sel, view, cwd=root)
    # Highlight git-changed models (vs --base-ref) in a lighter grey so they pop under --all.
    changed = _git_changed_models(sel.base_ref, root)
    rc = list_targets(
        scope.describe(sel),
        selector,
        color=color,
        bare=getattr(args, "bare", False),
        changed=changed,
        upstream=upstream,
        downstream=downstream,
    )
    if getattr(args, "macros", False):
        macro_files = view.dependent_macro_files(scope.resolve_model_ids(sel, view, cwd=root))
        report.render_headline(
            f"dependent macros — {len(macro_files)} repo macro file(s)", color=color, severity="info"
        )
        for path in sorted(macro_files):
            print(path)
    if getattr(args, "paths", None):
        # Preview the gha trigger globs for this mode against the FULL selector membership (matching
        # `gha create`), and flag in dark red the extra files those globs would also fire on.
        discovered = ls_model_paths(sel.selector, cwd=root)
        if getattr(args, "macros", False):
            models = view.of_type("model")
            ids = {u for u, r in models.items() if str(r.raw.get("original_file_path") or "") in discovered}
            discovered |= view.dependent_macro_files(ids)
        globs = globber.discover_to_globs(discovered, args.paths)
        for glob in globs:
            log.info("ls --paths %s — glob checked: %s", args.paths, glob)
        fps = globber.false_positives(globs, globber.universe_sql(root, with_macros=args.macros), canonical=discovered)
        report.render_headline(
            f"--paths {args.paths}: {len(globs)} glob(s), {len(fps)} false positive(s)",
            color=color,
            severity="warn" if fps else "ok",
        )
        for path in sorted(fps):
            print(report.colorize(path, "darkred", color))
    return rc
