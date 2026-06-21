#!/usr/bin/env python3
"""In-container gate harness — parse the fixture under one dbt engine, run adaf's read-only gates
against the resulting artifact, and emit a single JSON document on stdout.

This script is COPYed into the single per-engine image (``tests/multiversion/docker/Dockerfile``) as
``/harness.py`` and is the image ENTRYPOINT. It is intentionally **stdlib-only** so it runs on the
base image's interpreter without any install, and it never imports adaf or dbt — it shells out to
both, exactly as a CI job would, so the test exercises the real binaries the engine ships.

Contract (the artifact every engine produces, consumed by ``tests/multiversion/test_multiversion.py``):

* Reads its configuration from the environment the Dockerfile bakes in: ``ENGINE_NAME``, ``DBT_BIN``
  (the engine's ``dbt`` binary), ``ADAF_PY`` (the python whose venv has adaf installed),
  ``PARSE_FLAGS`` (e.g. ``--use-v2-parser``), ``SELECTOR``, and ``VERSION_PKGS``.
* ``dbt parse``s ``/fixture`` into ``/fixture/target``, detects whether the artifact is JSON
  (``manifest.json``) or parquet (a ``*.parquet`` directory — a v2.0 engine), then runs each adaf
  gate against it, capturing stdout / stderr / exit code per gate.
* Prints ONE JSON object to stdout (nothing else goes to stdout — diagnostics go to stderr). The
  process ALWAYS exits 0: a gate's non-zero exit is *data* in the JSON, not a process failure (a real
  parse/engine failure is still captured in the JSON and surfaces as a golden mismatch in the test —
  escalators-not-stairs, never a silent skip).
"""

# Standard Library
import json
import os
import subprocess
import sys
from pathlib import Path

FIXTURE = Path("/fixture")
TARGET = FIXTURE / "target"

ENGINE = os.environ["ENGINE_NAME"]
DBT_BIN = os.environ["DBT_BIN"]
ADAF_PY = os.environ["ADAF_PY"]
SELECTOR = os.environ.get("SELECTOR", "matrix_demo")
PARSE_FLAGS = os.environ.get("PARSE_FLAGS", "").split()
VERSION_PKGS = [p for p in os.environ.get("VERSION_PKGS", "").split(",") if p]


def _log(msg: str) -> None:
    """Diagnostics to stderr only — stdout is reserved for the single JSON result."""
    print(f"[harness:{ENGINE}] {msg}", file=sys.stderr, flush=True)


def _env() -> dict[str, str]:
    """Subprocess env: the engine's ``dbt`` first on PATH (so adaf's ``dbt ls`` shell-out hits the
    SAME engine that wrote the manifest), colour off, no anonymous stats / version pings."""
    env = dict(os.environ)
    env["PATH"] = f"{Path(DBT_BIN).parent}{os.pathsep}{env.get('PATH', '')}"
    env["NO_COLOR"] = "1"
    env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
    env["DO_NOT_TRACK"] = "1"
    return env


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    _log("exec: " + " ".join(cmd))
    return subprocess.run(cmd, cwd=FIXTURE, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=_env())


def _versions() -> dict[str, str]:
    """Resolve deterministic version strings for the golden header: the installed version of each
    ``VERSION_PKGS`` distribution, read via the dbt venv's own interpreter (``importlib.metadata``)."""
    dbt_py = Path(DBT_BIN).parent / "python"
    code = "import importlib.metadata as m,json,sys;print(json.dumps({n:m.version(n) for n in sys.argv[1:]}))"
    proc = subprocess.run([str(dbt_py), "-c", code, *VERSION_PKGS], capture_output=True, text=True, check=True)
    versions: dict[str, str] = json.loads(proc.stdout)
    return versions


def _parse() -> dict[str, object]:
    cmd = [
        DBT_BIN, "parse",
        "--project-dir", str(FIXTURE),
        "--profiles-dir", str(FIXTURE),
        "--target-path", str(TARGET),
        *PARSE_FLAGS,
    ]
    proc = _run(cmd)
    return {
        "cmd": cmd,
        "exit": proc.returncode,
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-20:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:]),
    }


def _detect_manifest() -> tuple[str, str]:
    """Return (manifest_kind, manifest_arg) — the artifact format and the value to pass adaf's
    ``--manifest``. JSON → the ``manifest.json`` file; parquet → the target DIRECTORY (adaf's
    ``load_artifact`` detects a ``*.parquet`` dir as a v2.0 engine's artifact set)."""
    if (TARGET / "manifest.json").exists():
        return "json", str(TARGET / "manifest.json")
    if list(TARGET.glob("*.parquet")):
        return "parquet", str(TARGET)
    return "missing", str(TARGET / "manifest.json")


def _gates(manifest_arg: str) -> list[dict[str, object]]:
    """The adaf read-only gates the matrix snapshots. ``list`` and ``sdag check`` are product-scoped
    (``--selector``); ``check docs`` / ``check tests`` use the changed/all selection (``--all`` over
    the tiny fixture covers exactly the matrix_demo models). Each gate runs against the engine's own
    parsed artifact (JSON or parquet)."""
    sel = ["--all", "--selector", SELECTOR]
    man = ["--manifest", manifest_arg]
    specs: list[tuple[str, list[str]]] = [
        ("list", ["list", *sel]),
        ("docs", ["check", "docs", "--all", *man]),
        ("tests", ["check", "tests", "--all", *man]),
        ("sdag check", ["sdag", "check", *sel, *man]),
    ]
    out: list[dict[str, object]] = []
    for label, argv in specs:
        proc = _run([ADAF_PY, "-m", "adaf", *argv, "--project-dir", str(FIXTURE), "--color", "never"])
        out.append(
            {
                "label": label,
                "argv": argv,
                "exit": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        )
    return out


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    versions = _versions()
    _log(f"versions: {versions}")
    parse = _parse()
    _log(f"parse exit: {parse['exit']}")
    kind, manifest_arg = _detect_manifest()
    _log(f"manifest: {kind} -> {manifest_arg}")
    gates = _gates(manifest_arg)
    result = {
        "engine": ENGINE,
        "versions": versions,
        "manifest_kind": kind,
        "parse": parse,
        "gates": gates,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
