"""``check deprecations`` — dbt-autofix over the folders of the selected models.

dbt-autofix ALWAYS exits 0 (even when it finds deprecated syntax), so in CHECK mode we
derive failure from its ``--json`` (JSONL) stream: any record carrying a ``refactors``
array is a file that needs changes. A genuine tool error (non-zero exit) is re-raised so
it aborts loudly rather than reading as "clean".

``--fix`` drops the ``-d`` (dry-run) flag so dbt-autofix actually rewrites the files; in
fix mode the report lists what was changed and is always ``ok`` (the fix succeeded).

Scanning at folder granularity (``-s <dir>``) is deliberate: a changed ``stg_orders.sql``
drags its sibling ``stg_orders.yml`` / ``__sources.yml`` into the scan, which is where the
deprecations actually live. The human report shows each refactor's description (so an agent
sees WHAT to change), and the raw dbt-autofix JSONL is kept in the ToolLog.
"""

# Standard Library
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

# Local
from adaf import config, selection, style
from adaf.formatting import render_from_args
from adaf.gitutil import dirs_of
from adaf.toollog import ToolLog, run_tool

log = logging.getLogger(__name__)

INFO = logging.INFO
ERROR = logging.ERROR


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


@dataclass
class DeprecationsReport:
    name = "deprecations"
    mode: str  # "check" or "fix"
    scope: str
    scanned_dirs: list[str]
    records: list[dict]
    logs: list[ToolLog] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # In fix mode the tool succeeded (errors raise), so applying changes is success.
        return True if self.mode == "fix" else not self.records

    @property
    def files(self) -> list[str]:
        return sorted({r["file_path"] for r in self.records})

    def summary(self) -> str:
        if not self.scanned_dirs:
            return "nothing to check"
        if self.mode == "fix":
            return f"{len(self.files)} file(s) fixed" if self.files else "nothing to fix"
        return "no deprecations" if self.ok else f"{len(self.files)} file(s) affected"

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "mode": self.mode,
            "scope": self.scope,
            "scanned_dirs": self.scanned_dirs,
            "files": self.files,
            "deprecations": [{"file_path": r["file_path"], "refactors": r["refactors"]} for r in self.records],
            "logs": [tool_log.to_dict() for tool_log in self.logs],
        }

    def human_lines(self, *, show_passes: bool = False) -> list[tuple[int, str]]:
        # Summary only — the per-refactor descriptions live in the native tool log (below, on
        # failure / --show-logs). Here we list the affected files. Failures-only: a clean check
        # collapses to its one-line verdict; fix mode always reports what it applied.
        label = style.section("deprecations")
        if not self.scanned_dirs:
            return [(INFO, f"{label}  {style.dim('no models to scan — nothing to do.')}")]
        if self.mode != "fix" and self.ok and not show_passes:
            return [(INFO, f"{label}  {style.passed('no dbt deprecations found')}")]
        if self.mode == "fix":
            if self.files:
                lines: list[tuple[int, str]] = [(INFO, f"{label}  {style.passed('applied deprecation fixes')}")]
                lines += [(INFO, style.pass_item(fp)) for fp in self.files]
                return lines
            return [(INFO, f"{label}  {style.passed('nothing to fix')}")]
        if self.records:
            lines = [(ERROR, f"{label}  {style.failed('dbt deprecations detected — see tool logs')}")]
            lines += [(ERROR, style.fail_item(fp)) for fp in self.files]
            lines.append((ERROR, style.dim("   apply with: adaf check deprecations --fix")))
            return lines
        return [(INFO, f"{label}  {style.passed('no dbt deprecations found')}")]


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
