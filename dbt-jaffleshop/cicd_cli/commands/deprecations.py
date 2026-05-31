"""``check deprecations`` — dbt-autofix over the folders of the selected models.

dbt-autofix ALWAYS exits 0 (even when it finds deprecated syntax), so in CHECK mode we
derive failure from its ``--json`` (JSONL) stream: any record carrying a ``refactors``
array is a file that needs changes. A genuine tool error (non-zero exit) is re-raised so
it aborts loudly rather than reading as "clean".

``--fix`` drops the ``-d`` (dry-run) flag so dbt-autofix actually rewrites the files; in
fix mode the report lists what was changed and is always ``ok`` (the fix succeeded).

Scanning at folder granularity (``-s <dir>``) is deliberate: a changed ``stg_orders.sql``
drags its sibling ``stg_orders.yml`` / ``__sources.yml`` into the scan, which is where the
deprecations actually live.
"""

# Standard Library
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Local
from cicd_cli import config, selection
from cicd_cli.formatting import render
from cicd_cli.gitutil import dirs_of

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


def scan_dir(directory: Path, *, cwd: Path, fix: bool = False) -> list[dict]:
    """Run dbt-autofix against one directory (dry-run unless ``fix``); fail loud on tool error."""
    cmd = ["dbt-autofix", "deprecations", "--json", "-s", str(directory)]
    if not fix:
        cmd.append("-d")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"dbt-autofix errored on {directory} (exit {proc.returncode}):\n{proc.stderr or proc.stdout}"
        )
    return parse_autofix_output(proc.stdout)


@dataclass
class DeprecationsReport:
    name = "deprecations"
    mode: str  # "check" or "fix"
    scope: str
    scanned_dirs: list[str]
    records: list[dict]

    @property
    def ok(self) -> bool:
        # In fix mode the tool succeeded (errors raise), so applying changes is success.
        return True if self.mode == "fix" else not self.records

    @property
    def files(self) -> list[str]:
        return sorted({r["file_path"] for r in self.records})

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "mode": self.mode,
            "scope": self.scope,
            "scanned_dirs": self.scanned_dirs,
            "files": self.files,
            "deprecations": [{"file_path": r["file_path"], "refactors": r["refactors"]} for r in self.records],
        }

    def human_lines(self) -> list[tuple[int, str]]:
        if not self.scanned_dirs:
            return [(INFO, f"deprecations: no models to scan ({self.scope}) — nothing to do.")]
        action = "applying fixes in" if self.mode == "fix" else "scanning"
        lines: list[tuple[int, str]] = [(INFO, f"deprecations: {action} folders — {self.scope}:")]
        lines += [(INFO, f"  {d}") for d in self.scanned_dirs]
        if self.mode == "fix":
            if self.files:
                lines.append((INFO, "✓ applied deprecation fixes to:"))
                lines += [(INFO, f"  {fp}") for fp in self.files]
            else:
                lines.append((INFO, "✓ nothing to fix"))
        elif self.records:
            lines.append((ERROR, "✗ dbt deprecations detected in:"))
            lines += [(ERROR, f"  {fp}") for fp in self.files]
            lines.append((ERROR, "  Apply with: cicd_cli check deprecations --fix"))
        else:
            lines.append((INFO, "✓ no dbt deprecations found"))
        return lines


def run(files: list[Path], *, scope: str, fix: bool = False, cwd: Path | None = None) -> DeprecationsReport:
    """Lift the selected model files to their folders and run dbt-autofix over each."""
    cwd = cwd or config.PROJECT_ROOT
    dirs = dirs_of(files)
    records: list[dict] = []
    for directory in dirs:
        records.extend(scan_dir(directory, cwd=cwd, fix=fix))
    return DeprecationsReport("fix" if fix else "check", scope, [str(d) for d in dirs], records)


def cmd(args) -> int:
    sel = selection.from_args(args)
    files = selection.resolve_model_files(sel)
    report = run(files, scope=selection.describe(sel), fix=args.fix)
    return render(report, as_json=args.as_json)
