"""The two deterministic, CHECK-ONLY gates plus the ``list`` action.

* ``deprecations`` — dbt-autofix over the FOLDERS of the selected models. dbt-autofix
  always exits 0, so failure is derived from its ``--json`` stream: any record with a
  ``refactors`` array is a file that needs changes. Folder granularity is deliberate —
  a changed ``x.sql`` drags its sibling ``x.yml`` / ``__sources.yml`` into the scan,
  which is where deprecations usually live. Always a dry-run (``-d``); never mutates.
* ``sqlfluff`` — ``sqlfluff lint`` over the selected model files. Its exit code IS the
  pass/fail signal.

All three route their output through :mod:`adaf.report`: a one-line headline goes to
STDERR and the findings list to STDOUT. The JSON-record→:class:`~adaf.report.Finding`
parsing is split into the pure helpers :func:`_deprecation_findings` and
:func:`_sqlfluff_findings` so it can be unit-tested without invoking the real binaries.
"""

# Standard Library
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

# Local
from adaf import config, report
from adaf.git.gitutil import dirs_of


def _selector_line(path: str, *, changed: set[str], color: bool) -> str:
    """A selector model's listing line: LIGHT grey if modified vs git, DARK grey if unmodified."""
    return report.colorize(path, "white" if path in changed else "grey", color)


def _context_line(display: str, tag: str | None, *, color: bool, hue: str = "grey") -> str:
    """A hop-added node's listing line, coloured by its section HUE (amber upstream / green
    downstream), with a matching ``[type]`` tag for non-model nodes (sources/seeds/snapshots)."""
    text = report.colorize(display, hue, color)
    return f"{text}  {report.colorize(f'[{tag}]', hue, color)}" if tag else text


def list_targets(
    scope: str,
    selector: list[str],
    *,
    color: bool = False,
    bare: bool = False,
    changed: set[str] | None = None,
    upstream: list[tuple[str, str | None]] | None = None,
    downstream: list[tuple[str, str | None]] | None = None,
    built: set[str] | None = None,
) -> int:
    """Print the resolved scope in titled groups (group titles to STDERR, paths to STDOUT).

    Sections are distinguished by HUE, not grey shades (which read too alike across sections):
    selector models are neutral grey — **light grey** when modified vs git, **dark grey** when not —
    while ``--upstream`` nodes are **amber** and ``--downstream`` nodes are **green** (the retro DAG
    palette). Non-model hop nodes carry a matching ``[type]`` tag.

    When ``--upstream``/``--downstream`` add nodes, each direction gets its own ``== … ==`` group title.
    ``bare`` drops ALL group titles and prints one flat, pipeable path list (selector then extras).

    When ``built`` is given (``--defer`` is active), every group is further split into a ``built``
    subgroup (paths in the ``state:modified+`` set a deferred build would rebuild) and a ``deferred``
    subgroup (reused from the baseline) — each under its own ``-- … --`` sub-header on STDERR.
    """
    changed = changed or set()
    upstream = upstream or []
    downstream = downstream or []
    total = len(selector) + len(upstream) + len(downstream)
    noun = "node(s)" if (upstream or downstream) else "model(s)"
    report.render_headline(f"# {scope} — {total} {noun}", color=color, severity="info")

    if bare or (not upstream and not downstream and built is None):
        # Flat list: no group titles. (Also the shape when there's nothing extra to group.)
        for path in selector:
            print(_selector_line(path, changed=changed, color=color))
        for display, tag in upstream:
            print(_context_line(display, tag, color=color, hue="yellow"))
        for display, tag in downstream:
            print(_context_line(display, tag, color=color, hue="green"))
        return 0

    # Emit a group's rows ((rendered line, path key) tuples). With ``built`` active, partition the
    # rows into a built then a deferred sub-section, each under a ``-- … --`` sub-header.
    def _emit(rows: list[tuple[str, str]]) -> None:
        if built is None:
            for line, _ in rows:
                print(line)
            sys.stdout.flush()
            return
        for label, severity, keep in (("built", "warn", True), ("deferred", "ok", False)):
            section = [line for line, key in rows if (key in built) == keep]
            if not section:
                continue
            report.render_headline(f"  -- {label} ({len(section)}) --", color=color, severity=severity)
            for line in section:
                print(line)
            sys.stdout.flush()  # keep sub-section order deterministic when STDOUT is piped

    # Grouped: a titled section per group, titles on STDERR so STDOUT stays a clean path stream.
    def _group(title: str, rows: list[tuple[str, str]]) -> None:
        report.render_headline(f"== {title} ==", color=color, severity="info")
        _emit(rows)

    _group(
        f"selector models ({len(selector)})",
        [(_selector_line(p, changed=changed, color=color), p) for p in selector],
    )
    if upstream:
        _group(
            f"upstream ({len(upstream)})",
            [(_context_line(d, t, color=color, hue="yellow"), d) for d, t in upstream],
        )
    if downstream:
        _group(
            f"downstream ({len(downstream)})",
            [(_context_line(d, t, color=color, hue="green"), d) for d, t in downstream],
        )
    return 0


def _extract_line(ref: dict[str, Any]) -> int | None:
    """Best-effort line number for a dbt-autofix refactor record.

    The current dbt-autofix JSON refactor carries only ``deprecation`` + ``log`` (no
    location), so this returns ``None`` today. We still probe a set of plausible keys —
    flat (``line``/``lineno``/``line_no``/``start_line_no``) and nested under
    ``location``/``range`` — so a future dbt-autofix that adds positions is surfaced
    without a code change. Anything non-integer is ignored.
    """
    flat_keys = ("line", "lineno", "line_no", "line_number", "start_line_no")
    for key in flat_keys:
        value = ref.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    for container_key in ("location", "range"):
        container = ref.get(container_key)
        if isinstance(container, dict):
            for key in (*flat_keys, "start"):
                value = container.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    return value
    return None


def _deprecation_findings(records: list[dict[str, Any]]) -> list[report.Finding]:
    """Flatten dbt-autofix JSON records into ``warn`` Findings (pure; one per refactor).

    ``records`` are the parsed ``--json`` lines (each ``{"file_path", "refactors": [...]}``).
    Project-global files (e.g. ``dbt_project.yml``) recur in every per-dir scan, so the
    first occurrence of a file path wins and later duplicates are dropped. Each refactor
    becomes a Finding pinned to ``deprecation`` (code) and ``log`` (message).
    """
    findings: list[report.Finding] = []
    seen: set[str] = set()
    for record in records:
        file_path = record.get("file_path")
        refactors = record.get("refactors")
        if not file_path or not refactors:
            continue
        if file_path in seen:
            continue
        seen.add(file_path)
        for ref in refactors:
            code = ref.get("deprecation") or ref.get("name")
            findings.append(
                report.Finding(
                    path=file_path,
                    line=_extract_line(ref),
                    severity="warn",
                    code=code,
                    message=ref.get("log", ""),
                )
            )
    return findings


def _deprecation_argv(directory: Path, *, fix: bool) -> list[str]:
    """The dbt-autofix argv for one folder — the single source of truth for both running and
    printing the command. Detection is a dry-run JSON scan (``-d --json``) so findings can be
    parsed reliably; ``fix`` drops both so dbt-autofix rewrites the files in place.
    """
    argv = ["dbt-autofix", "deprecations", "-s", str(directory)]
    return argv if fix else [*argv, "-d", "--json"]


def _sqlfluff_argv(targets: list[str], *, fix: bool, fmt: str | None) -> list[str]:
    """The SQLFluff argv for the selected files — the single source of truth for both running and
    printing the command. ``fix`` applies auto-fixes (``fix --force``); ``fmt`` streams a passthrough
    lint format (e.g. ``github-annotation-native``); otherwise it lints as ``--format json`` (the
    shape adaf parses into Findings).
    """
    if fix:
        return ["sqlfluff", "fix", "--force", *targets]
    return ["sqlfluff", "lint", "--format", fmt or "json", *targets]


def _print_commands(label: str, argvs: list[list[str]], *, color: bool) -> int:
    """Print each subprocess command verbatim instead of running it — one runnable, shell-quoted
    line to STDOUT (pipeable), a headline to STDERR. Lets a user inspect, copy, or run the exact
    command adaf would have shelled out to. Paths are relative to the dbt project root, so the
    printed commands are meant to be run from there. Always returns 0 (nothing was executed).
    """
    report.render_headline(
        f"# {label} — {len(argvs)} command(s); run from the dbt project root", color=color, severity="info"
    )
    for argv in argvs:
        print(shlex.join(argv))
    return 0


def check_deprecations(
    files: list[Path],
    *,
    fix: bool = False,
    commands: bool = False,
    color: bool = False,
    cwd: Path | None = None,
    json_out: Path | None = None,
    quiet: bool = False,
) -> int:
    """dbt-autofix over each folder of the selected files.

    Detection is always a dry-run (``-d --json``) so we can report findings reliably —
    dbt-autofix exits 0 even when it finds deprecated syntax. In ``--fix`` mode we then
    re-run *without* ``-d`` to actually rewrite the files; otherwise we report and exit 1.
    """
    cwd = cwd or config.project_root()
    if not files:
        return report.emit_findings(
            "deprecations",
            [],
            0,
            color=color,
            json_out=json_out,
            quiet=quiet,
            headline="deprecations: no files in scope — skipped.",
            severity="info",
        )
    dirs = dirs_of(files)
    if commands:  # print the exact command(s) we'd run instead of shelling out
        return _print_commands("deprecations", [_deprecation_argv(d, fix=fix) for d in dirs], color=color)
    records: list[dict[str, Any]] = []
    for directory in dirs:
        proc = subprocess.run(
            _deprecation_argv(directory, fix=False),
            cwd=cwd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"dbt-autofix errored on {directory} (exit {proc.returncode}):\n{proc.stderr or proc.stdout}"
            )
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    findings = _deprecation_findings(records)
    files_needing = {f.path for f in findings}

    if fix:
        if not findings:
            report.render_headline(
                "deprecations: nothing to fix — no deprecated dbt syntax in scope.", color=color, severity="ok"
            )
            return 0
        for directory in dirs:  # re-run WITHOUT -d so dbt-autofix rewrites the files
            apply = subprocess.run(
                _deprecation_argv(directory, fix=True),
                cwd=cwd,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
            )
            if apply.returncode != 0:
                raise RuntimeError(
                    f"dbt-autofix --fix errored on {directory} (exit {apply.returncode}):\n"
                    f"{apply.stderr or apply.stdout}"
                )
        report.render_headline(
            f"deprecations: applied fixes to {len(files_needing)} file(s).", color=color, severity="ok"
        )
        for file_path in sorted(files_needing):
            print(f"  fixed {file_path}", file=sys.stderr)
        return 0

    if not findings:
        return report.emit_findings(
            "deprecations",
            [],
            0,
            color=color,
            json_out=json_out,
            quiet=quiet,
            headline="deprecations: OK — no deprecated dbt syntax in scope.",
            severity="ok",
        )
    return report.emit_findings(
        "deprecations",
        findings,
        1,
        color=color,
        json_out=json_out,
        quiet=quiet,
        headline=f"deprecations: {len(files_needing)} file(s) need changes (re-run with --fix to apply).",
        severity="warn",
    )


def _sqlfluff_findings(payload: list[dict[str, Any]]) -> list[report.Finding]:
    """Flatten SQLFluff's ``--format json`` payload into ``error`` Findings (pure).

    ``payload`` is SQLFluff's list of ``{"filepath", "violations": [...]}`` objects. Each
    violation pins line/column from ``start_line_no``/``start_line_pos`` (SQLFluff ≥ 3),
    falling back to ``line_no``/``line_pos`` (SQLFluff 2.x), and carries ``code`` +
    ``description``.
    """
    findings: list[report.Finding] = []
    for record in payload:
        filepath = record.get("filepath", "")
        for v in record.get("violations", []):
            line = v.get("start_line_no", v.get("line_no"))
            col = v.get("start_line_pos", v.get("line_pos"))
            findings.append(
                report.Finding(
                    path=filepath,
                    line=line,
                    col=col,
                    severity="error",
                    code=v.get("code"),
                    message=v.get("description", ""),
                )
            )
    return findings


def check_sqlfluff(
    files: list[Path],
    *,
    fix: bool = False,
    fmt: str | None = None,
    commands: bool = False,
    color: bool = False,
    cwd: Path | None = None,
    json_out: Path | None = None,
    quiet: bool = False,
) -> int:
    """SQLFluff over the selected files. Exit code is the signal.

    Check mode runs ``sqlfluff lint --format json`` (reports violations, touches nothing),
    parses the JSON, and renders Findings through :mod:`adaf.report`. SQLFluff's own exit
    code is preserved as the gate (non-zero when violations exist). ``--fix`` runs
    ``sqlfluff fix --force`` to apply the auto-fixable rules in place — ``--force`` skips the
    interactive confirmation prompt so it never hangs on a TTY-less stdin.

    ``fmt`` (lint only) passes SQLFluff's ``--format`` — e.g. ``github-annotation-native`` so
    the violations surface as inline PR annotations in GitHub Actions; that native output is
    streamed straight through unchanged. Ignored in ``--fix`` mode.
    """
    cwd = cwd or config.project_root()
    if not files:
        return report.emit_findings(
            "sqlfluff",
            [],
            0,
            color=color,
            json_out=json_out,
            quiet=quiet,
            headline="sqlfluff: no files in scope — skipped.",
            severity="info",
        )
    targets = [str(f) for f in files]
    if commands:  # print the exact command we'd run instead of shelling out
        return _print_commands("sqlfluff", [_sqlfluff_argv(targets, fix=fix, fmt=fmt)], color=color)
    if fix:
        fix_proc = subprocess.run(_sqlfluff_argv(targets, fix=True, fmt=None), cwd=cwd, stdin=subprocess.DEVNULL)
        return fix_proc.returncode
    # `--json-out` needs the parsed-findings path, so it takes precedence over the `fmt` passthrough
    # (which streams SQLFluff's native annotation output and parses nothing).
    if fmt and json_out is None:
        # GitHub-annotation path: stream SQLFluff's native annotation output straight through.
        fmt_proc = subprocess.run(_sqlfluff_argv(targets, fix=False, fmt=fmt), cwd=cwd, stdin=subprocess.DEVNULL)
        return fmt_proc.returncode

    proc = subprocess.run(
        _sqlfluff_argv(targets, fix=False, fmt=None),
        cwd=cwd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else []
    except json.JSONDecodeError:
        # Non-JSON stdout (e.g. a config/templater error): surface raw output, keep the gate.
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        return proc.returncode

    findings = _sqlfluff_findings(payload)
    if findings:
        headline, severity = f"sqlfluff: {len(findings)} violation(s) in scope.", "error"
    else:
        headline, severity = "sqlfluff: OK — no violations in scope.", "ok"
    return report.emit_findings(
        "sqlfluff",
        findings,
        proc.returncode,
        color=color,
        json_out=json_out,
        quiet=quiet,
        headline=headline,
        severity=severity,
    )
