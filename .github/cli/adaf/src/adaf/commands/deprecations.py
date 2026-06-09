"""``check deprecations`` — dbt-autofix over the folders of the selected models.

dbt-autofix ALWAYS exits 0 (even when it finds deprecated syntax), so in CHECK mode we
derive failure from its ``--json`` (JSONL) stream: any record carrying a ``refactors``
array is a file that needs changes. A genuine tool error (non-zero exit) is re-raised so
it aborts loudly rather than reading as "clean".

``--fix`` drops the ``-d`` (dry-run) flag so dbt-autofix actually rewrites the files; in
fix mode the report lists what was changed and is always ``ok`` (the fix succeeded).

Scanning at folder granularity (``-s <dir>``) is deliberate: a changed ``stg_orders.sql``
drags its sibling ``stg_orders.yml`` / ``__sources.yml`` into the scan, which is where the
deprecations actually live. The result dataclass lives in ``adaf.reports.deprecations``.
"""

# Standard Library
import json
import logging
from pathlib import Path

# Local
from adaf import config, selection
from adaf.gitutil import dirs_of
from adaf.reports.deprecations import DeprecationsReport
from adaf.utils.formatting import render_from_args
from adaf.utils.toollog import ToolLog, run_tool

log = logging.getLogger(__name__)

__all__ = ["DeprecationsReport", "parse_autofix_output", "scan_dir", "run", "cmd"]


def parse_autofix_output(stdout: str) -> list[dict]:
    """From dbt-autofix's JSONL, keep only records that carry refactors (files to change)."""
    records: list[dict] = []
    for line in stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        record = json.loads(text)
        if record.get("refactors"):
            records.append(record)
    return records


def scan_dir(directory: Path, *, cwd: Path, fix: bool = False) -> tuple[list[dict], ToolLog]:
    """Scan one directory; return (structured records, NATIVE coloured tool transcript).

    Two invocations, deliberately sequenced:
      1. detection — a robust JSON **dry-run** (always non-mutating) parsed into records.
      2. display   — the tool's NATIVE (non-JSON, coloured) output for the log block: a
         dry-run in check mode, the real **apply** in fix mode. So in ``--fix`` the file is
         rewritten exactly once (here), never by the detection run.
    """
    base = ["dbt-autofix", "deprecations", "-s", str(directory)]
    detect = run_tool([*base, "-d", "--json"], cwd=cwd)
    if detect.failed:
        raise RuntimeError(
            f"dbt-autofix errored on {directory} (exit {detect.returncode}):\n{detect.stderr or detect.stdout}"
        )
    records = parse_autofix_output(detect.stdout)
    native = run_tool(base if fix else [*base, "-d"], cwd=cwd, tty=True)
    if native.failed:
        raise RuntimeError(f"dbt-autofix errored on {directory} (exit {native.returncode}):\n{native.stdout}")
    return records, native


def run(files: list[Path], *, scope: str, fix: bool = False, cwd: Path | None = None) -> DeprecationsReport:
    """Lift the selected model files to their folders and run dbt-autofix over each."""
    cwd = cwd or config.PROJECT_ROOT
    dirs = dirs_of(files)
    records: list[dict] = []
    logs: list[ToolLog] = []
    seen_paths: set[str] = set()
    for directory in dirs:
        dir_records, tool_log = scan_dir(directory, cwd=cwd, fix=fix)
        # dbt-autofix reports project-global files (e.g. dbt_project.yml) in EVERY per-dir
        # scan, so dedupe by file_path — first occurrence wins (the findings are identical).
        for record in dir_records:
            if record["file_path"] not in seen_paths:
                seen_paths.add(record["file_path"])
                records.append(record)
        logs.append(tool_log)
    return DeprecationsReport("fix" if fix else "check", scope, [str(d) for d in dirs], records, logs=logs)


def cmd(args) -> int:
    sel = selection.from_args(args)
    files = selection.resolve_model_files(sel)
    report = run(files, scope=selection.describe(sel), fix=args.fix)
    return render_from_args(report, args)
