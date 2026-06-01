"""ToolLog — capture the FULL transcript of every underlying-tool invocation.

The check commands shell out to real tools (sqlfluff, dbt-autofix, dbt). When a check
fails, the actionable signal — which file, which line, which rule, the dbt-templater
compile error — lives in that tool's output. A coding agent needs it verbatim, especially
for findings the tool can't auto-fix (it has to fix those by hand).

So every subprocess goes through :func:`run_tool`, which records the command, exit code,
and output. Two capture modes:

* default (``tty=False``): ``subprocess.run`` capturing stdout and stderr separately.
* ``tty=True``: run under a pseudo-terminal so the tool believes it's on a real terminal
  and emits its NATIVE output — ANSI colour and all (sqlfluff/click and dbt-autofix/rich
  both gate colour on ``isatty()``). A pty has a single stream, so stdout+stderr merge.

Reports carry their ToolLogs; the renderer prints them on failure (or always with
``--show-logs``), and ``--json`` always includes them.
"""

# Standard Library
import os
import pty
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolLog:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def failed(self) -> bool:
        return self.returncode != 0

    def to_dict(self) -> dict:
        return {
            "command": " ".join(self.command),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }

    def human_block(self) -> list[str]:
        """Render as a readable transcript: the command line, then stdout, then stderr."""
        lines = [f"$ {' '.join(self.command)}  (exit {self.returncode})"]
        lines += [f"  {ln}" for ln in self.stdout.splitlines()]
        lines += [f"  [stderr] {ln}" for ln in self.stderr.splitlines()]
        return lines


def _capture_via_pty(command: list[str], cwd: Path) -> tuple[int, str]:
    """Run ``command`` with stdout+stderr on a pty so it emits TTY-native (coloured) output.

    A pty multiplexes both streams into one, so the returned text is the tool's combined
    transcript exactly as a terminal would show it (ANSI escapes preserved).
    """
    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=slave, stderr=slave)
    finally:
        os.close(slave)  # the child holds its own dup; closing ours lets read() hit EOF on exit
    chunks: list[bytes] = []
    try:
        while True:
            try:
                data = os.read(master, 65536)
            except OSError:  # pty master raises EIO at EOF on some platforms (e.g. Linux)
                break
            if not data:
                break
            chunks.append(data)
    finally:
        os.close(master)
    returncode = proc.wait()
    return returncode, b"".join(chunks).decode("utf-8", errors="replace")


def run_tool(command: list[str], *, cwd: Path, stdin_devnull: bool = True, tty: bool = False) -> ToolLog:
    """Run an underlying tool, capturing command + exit code + output.

    ``tty=True`` preserves the tool's native coloured output (see module docstring); stderr is
    merged into stdout in that mode. ``stdin`` is closed so a tool that prompts fails fast in CI
    instead of hanging on a TTY-less stdin.
    """
    if tty:
        returncode, output = _capture_via_pty(command, cwd)
        return ToolLog(list(command), returncode, output, "")
    proc = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL if stdin_devnull else None,
    )
    return ToolLog(list(command), proc.returncode, proc.stdout, proc.stderr)
