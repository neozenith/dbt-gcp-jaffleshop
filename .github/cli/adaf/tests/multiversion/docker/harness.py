#!/usr/bin/env python3
"""In-container gate harness — parse the fixture under one dbt engine, run adaf's read-only gates
against the resulting artifact, and emit a single JSON document on stdout.

This script is COPYed into the single per-engine image (``tests/multiversion/docker/Dockerfile``) as
``/harness.py`` and
is the image ENTRYPOINT. It is intentionally **stdlib-only** so it runs on the base image's
interpreter without any install, and it never imports adaf or dbt — it shells out to both, exactly
as a CI job would, so the test exercises the real binaries the engine ships.

Contract (the artifact every engine produces, consumed by ``tests/multiversion/test_multiversion.py``):

* Reads its configuration from the environment the Dockerfile bakes in:
  ``ENGINE_NAME``, ``DBT_BIN`` (the engine's ``dbt`` binary), ``ADAF_PY`` (the python whose venv has
  adaf installed), ``PARSE_FLAGS`` (e.g. ``--use-v2-parser``), ``SELECTOR``, and ``VERSION_PKGS`` (a
  comma list of pip distributions whose versions to report).
* ``dbt parse``s ``/fixture`` into ``/fixture/target``, detects whether the artifact is JSON
  (``manifest.json``) or the Fusion parquet set (``metadata/parse/nodes/v1_0.parquet`` — a v2.0
  engine writes both, parquet wins), then runs each adaf gate against it, capturing stdout / stderr /
  exit code per gate.
* Prints ONE JSON object to stdout (nothing else goes to stdout — diagnostics go to stderr) so the
  container's stdout is a clean, parseable result. The process ALWAYS exits 0: a gate's non-zero exit
  is *data* in the JSON, not a process failure (a real parse/engine failure is still captured in the
  JSON and surfaces as a golden mismatch in the test — escalators-not-stairs, never a silent skip).
"""

# Standard Library
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURE = Path("/fixture")
TARGET = FIXTURE / "target"

# The one model this harness mutates to give `state:modified` something to detect: append a comment to
# its SQL in a throwaway copy of the project, re-parse, and corroborate the modified set.
SM_MUTATE_REL = Path("models") / "staging" / "stg_orders.sql"

ENGINE = os.environ["ENGINE_NAME"]
ENGINE_KIND = os.environ.get("ENGINE_KIND", "pip")  # "pip" (dbt-core venv) | "fusion" (Rust binary)
DBT_BIN = os.environ["DBT_BIN"]
ADAF_PY = os.environ["ADAF_PY"]
SELECTOR = os.environ.get("SELECTOR", "matrix_demo")
PARSE_FLAGS = os.environ.get("PARSE_FLAGS", "").split()
VERSION_PKGS = [p for p in os.environ.get("VERSION_PKGS", "").split(",") if p]

# Flags valid for `dbt build` / `docs generate` (a SUBSET of PARSE_FLAGS). `--write-index` (Fusion)
# makes them emit the parquet run/catalog set and IS accepted; parse-only flags like `--use-v2-parser`
# (dbt 1.12) are NOT accepted by `docs generate` (it exits 2) — so they are forwarded to `parse` only.
_BUILD_DOCS_FLAGS = [f for f in PARSE_FLAGS if f == "--write-index"]

# Where the Fusion engine writes its parquet metadata artifact set under the target dir (verified
# against `dbt parse --write-index`; see src/adaf/dbt/artifact.py). Its presence is how a Fusion run is
# distinguished from a dbt-core run (which writes only manifest.json) — Fusion writes BOTH.
FUSION_NODES_REL = Path("metadata") / "parse" / "nodes" / "v1_0.parquet"

# VERIFIED paths of the run-results + catalog parquet a Fusion `--write-index` build/docs emits
# (captured by this probe; see src/adaf/dbt/runresults.py + docs/dbt-fusion-artifacts.md). The full
# `_metadata_listing()` below still records EVERY file under `target/metadata`, so any future new
# parquet artifact (or a path move) still surfaces in the golden.
FUSION_RUN_RESULTS_REL = Path("metadata") / "run" / "results" / "v1_0.parquet"
FUSION_CATALOG_REL = Path("metadata") / "catalog" / "columns" / "v1_0.parquet"


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
    """Resolve deterministic version strings for the golden header.

    pip engines: the installed version of each ``VERSION_PKGS`` distribution, read via the dbt venv's
    own interpreter (``importlib.metadata``). Fusion is a single Rust binary with no venv/distribution
    metadata, so its version is read from ``dbt --version`` (e.g. ``dbt-fusion 2.0.0-preview.190``)."""
    if ENGINE_KIND == "fusion":
        proc = subprocess.run([DBT_BIN, "--version"], capture_output=True, text=True, check=True, env=_env())
        first = next((ln for ln in proc.stdout.splitlines() if ln.strip()), "dbt-fusion unknown")
        parts = first.split()
        name = parts[0] if parts else "dbt-fusion"
        ver = parts[1] if len(parts) > 1 else "unknown"
        return {name: ver}
    dbt_py = Path(DBT_BIN).parent / "python"
    code = "import importlib.metadata as m,json,sys;print(json.dumps({n:m.version(n) for n in sys.argv[1:]}))"
    proc = subprocess.run(
        [str(dbt_py), "-c", code, *VERSION_PKGS], capture_output=True, text=True, check=True
    )
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


def _build() -> dict[str, object]:
    """`dbt build` the fixture (duckdb adapter, in-container) — the step that emits ``run_results.json``
    (and, under a Fusion ``--write-index``, the run-results parquet we capture). Only ``--write-index``
    is forwarded (see :data:`_BUILD_DOCS_FLAGS`); parse-only flags like ``--use-v2-parser`` are not."""
    cmd = [
        DBT_BIN, "build",
        "--project-dir", str(FIXTURE),
        "--profiles-dir", str(FIXTURE),
        "--target-path", str(TARGET),
        "--selector", SELECTOR,
        *_BUILD_DOCS_FLAGS,
    ]
    proc = _run(cmd)
    return {
        "cmd": cmd,
        "exit": proc.returncode,
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-25:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-25:]),
    }


def _docs_generate() -> dict[str, object]:
    """`dbt docs generate` — the step that emits ``catalog.json`` (and any Fusion catalog parquet)."""
    cmd = [
        DBT_BIN, "docs", "generate",
        "--project-dir", str(FIXTURE),
        "--profiles-dir", str(FIXTURE),
        "--target-path", str(TARGET),
        *_BUILD_DOCS_FLAGS,
    ]
    proc = _run(cmd)
    return {
        "cmd": cmd,
        "exit": proc.returncode,
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-25:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-25:]),
    }


def _detect_artifact(json_name: str, parquet_rel: Path) -> str:
    """``"parquet"`` (Fusion set present) | ``"json"`` (the v6/v1 JSON present) | ``"missing"``.

    Parquet wins when both exist (the Fusion row is meant to exercise the new format), mirroring
    :func:`_detect_manifest`."""
    if (TARGET / parquet_rel).exists():
        return "parquet"
    if (TARGET / json_name).exists():
        return "json"
    return "missing"


def _metadata_listing() -> list[str]:
    """Every file actually written under ``target/metadata`` (sorted, target-relative).

    This is the ROBUST capture: it records the real Fusion parquet artifact set regardless of our
    guessed probe paths, so a run-results/catalog parquet at an unexpected location still appears in the
    golden — the signal to capture its schema and write the reader."""
    base = TARGET / "metadata"
    if not base.exists():
        return []
    return sorted(str(p.relative_to(TARGET)) for p in base.rglob("*") if p.is_file())


def _detect_manifest() -> tuple[str, str]:
    """Return (manifest_kind, manifest_arg) — the artifact format and the value to pass adaf's
    ``--manifest``.

    The Fusion parquet set is probed FIRST: a Fusion run writes BOTH the parquet metadata set AND a
    (v12-schema) ``manifest.json``, and we want this row to exercise the NEW parquet path, so its
    presence wins. The arg is then the target DIRECTORY (adaf's ``load_artifact`` finds the node table
    under it). A dbt-core run writes only ``manifest.json`` → JSON path, arg = the file itself."""
    if (TARGET / FUSION_NODES_REL).exists():
        return "parquet", str(TARGET)
    if (TARGET / "manifest.json").exists():
        return "json", str(TARGET / "manifest.json")
    return "missing", str(TARGET / "manifest.json")


def _gates(manifest_arg: str) -> list[dict[str, object]]:
    sel = ["--all", "--selector", SELECTOR]
    man = ["--manifest", manifest_arg]
    specs: list[tuple[str, list[str]]] = [
        ("list", ["list", *sel]),
        ("docscov", ["docscov", *sel, *man]),
        ("testcov", ["testcov", *sel, *man]),
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


def _ls_paths(argv: list[str], cwd: Path) -> tuple[int, list[str]]:
    """Run a list-producing command (``dbt ls`` / ``adaf list``) and return ``(exit, sorted .sql paths)``."""
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=_env())
    return proc.returncode, sorted(ln.strip() for ln in proc.stdout.splitlines() if ln.strip().endswith(".sql"))


def _build_mutant() -> Path:
    """Copy the fixture, append a comment to one model, and parse it; return the mutated project dir.

    Its baseline is the pristine ``TARGET`` (parsed in :func:`main` from the unmutated fixture); its
    current manifest is ``<proj>/target/manifest.json``. The caller cleans up ``proj.parent``."""
    proj = Path(tempfile.mkdtemp()) / "proj"
    shutil.copytree(FIXTURE, proj, ignore=shutil.ignore_patterns("target", "logs", "tmp", "*.duckdb", ".user.yml"))
    mutant = proj / SM_MUTATE_REL
    mutant.write_text(mutant.read_text() + "\n-- adaf state:modified corroboration\n")
    _run([DBT_BIN, "parse", "--project-dir", str(proj), "--profiles-dir", str(proj),
          "--target-path", str(proj / "target"), *PARSE_FLAGS])
    return proj


def _state_modified_selector(proj: Path) -> dict[str, object]:
    """Demonstrate the named-selector ∩ state:modified scope modes per engine, driven through
    ``adaf ls`` (the subcommand having been folded in). For each of the three modes:

    * ``--state-modified``       (``S ∩ M``)      — native ``selector:NAME,state:modified``  on 1.12+
    * ``--state-modified-plus``  (``S ∩ M+``)     — native ``selector:NAME,state:modified+`` on 1.12+
    * ``--state-modified-plus-plus`` (``(S ∩ M+)+``) — NO native form (the `+` can't bind to an
      intersection result, the Atom Rule); always resolved ``<path>+`` atoms. This one CROSSES the
      product boundary to pull in the untagged ``report_orders`` consumer of a changed mart.

    it compares three things and records them in the golden:
      (1) ``adaf ls <mode>``                — the resolved set;
      (2) ``dbt ls <adaf ls --flags <mode>>`` — adaf's emitted flags (native vs backport, visibly
          different per engine) fed back to dbt, which MUST reproduce (1);
      (3) the dbt-native ``selector:NAME,state:modified[+]`` (M / M+ only), where the engine has the
          method — which MUST also equal (1).
    ``exit`` is 1 if any mode's adaf set disagrees with its own emitted flags, or with the native
    form where the engine supports it."""
    base = str(TARGET)  # the pristine baseline dir (the dbt --state side)

    def _adaf(mode: str, *extra: str) -> tuple[int, list[str]]:
        return _ls_paths(
            [ADAF_PY, "-m", "adaf", "list", "--selector", SELECTOR, mode, "--state", base,
             "--project-dir", str(proj), "--color", "never", *extra], proj)

    def _adaf_flags(mode: str) -> str:
        return subprocess.run(
            [ADAF_PY, "-m", "adaf", "list", "--selector", SELECTOR, mode, "--state", base,
             "--project-dir", str(proj), "--color", "never", "--flags"],
            cwd=proj, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=_env()).stdout.strip()

    modes: list[tuple[str, str | None]] = [
        ("--state-modified", "state:modified"),
        ("--state-modified-plus", "state:modified+"),
        ("--state-modified-plus-plus", None),  # (S ∩ M+)+ — no native one-expression form (Atom Rule)
    ]
    lines = [f"selector: {SELECTOR}   (baseline: pristine TARGET)"]
    overall_ok = True
    for mode, native_sel in modes:
        _, adaf_set = _adaf(mode, "--bare")
        flags = _adaf_flags(mode)
        _, fed_set = _ls_paths(
            [DBT_BIN, "ls", "--quiet", "--resource-type", "model", "--output", "path", *shlex.split(flags)], proj)
        adaf_eq_fed = adaf_set == fed_set
        mode_ok = adaf_eq_fed
        block = [
            f"--- {mode}:",
            *(f"  {p}" for p in adaf_set),
            f"  flags: {flags}",
            f"  dbt ls <flags> == adaf: {adaf_eq_fed}",
        ]
        if native_sel is not None:
            nat_rc, native_set = _ls_paths(
                [DBT_BIN, "ls", "--quiet", "--resource-type", "model", "--output", "path",
                 "--select", f"selector:{SELECTOR},{native_sel}", "--state", base, "--no-defer"], proj)
            native_ok = nat_rc == 0
            adaf_eq_native = native_ok and adaf_set == native_set
            note = str(adaf_eq_native) if native_ok else "n/a (no selector: method on this engine)"
            block.append(f"  native `selector:{SELECTOR},{native_sel}` (exit {nat_rc}) == adaf: {note}")
            mode_ok = mode_ok and (adaf_eq_native or not native_ok)
        else:
            block.append("  native: n/a — (S ∩ M+)+ has no one-expression form (Atom Rule)")
        lines.extend(block)
        overall_ok = overall_ok and mode_ok
    return {
        "label": "state-modified-selector",
        "argv": ["state-modified-selector", "(M / M+ / (S∩M+)+ via adaf ls)"],
        "exit": 0 if overall_ok else 1,
        "stdout": "\n".join(lines) + "\n",
        "stderr": "",
    }


def _ls_defer(proj: Path) -> dict[str, object]:
    """``adaf ls --all --defer``: each existing group split into a ``built`` (``state:modified+``) and a
    ``deferred`` sub-section, each under its own ``-- … --`` sub-header (stderr), paths built-first
    (stdout). Uses the prebuilt ``--state`` baseline (the pristine TARGET) so the M+ split resolves
    without a git worktree, against the SAME mutated manifest the state-modified-selector gate uses."""
    base = str(TARGET)
    r = subprocess.run(
        [ADAF_PY, "-m", "adaf", "list", "--selector", SELECTOR, "--all", "--state", base,
         "--defer", "--project-dir", str(proj), "--color", "never"],
        cwd=proj, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=_env())
    return {
        "label": "ls-defer",
        "argv": ["list", "--selector", SELECTOR, "--all", "--defer"],
        "exit": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    versions = _versions()
    _log(f"versions: {versions}")
    parse = _parse()
    _log(f"parse exit: {parse['exit']}")
    kind, manifest_arg = _detect_manifest()
    _log(f"manifest: {kind} -> {manifest_arg}")
    gates = _gates(manifest_arg)
    # Build ONE mutated project (a model edited + re-parsed), then drive the state:modified scope modes
    # through `adaf ls` against it — appended as a gate-shaped `state-modified-selector` capability
    # (its own goldens/state-modified-selector/<engine>.txt): M / M+ / (S∩M+)+ vs native + round-trip.
    proj = _build_mutant()
    try:
        gates.append(_state_modified_selector(proj))
        gates.append(_ls_defer(proj))  # the --defer built/deferred subgroup split, same mutated baseline
    finally:
        shutil.rmtree(proj.parent, ignore_errors=True)
    # Proactively capture the run-results + catalog artifacts (build then docs generate), recording the
    # format each engine emits — so a future Fusion parquet run_results/catalog surfaces as a golden diff.
    build = _build()
    _log(f"build exit: {build['exit']}")
    docs = _docs_generate()
    _log(f"docs generate exit: {docs['exit']}")
    run_results_kind = _detect_artifact("run_results.json", FUSION_RUN_RESULTS_REL)
    catalog_kind = _detect_artifact("catalog.json", FUSION_CATALOG_REL)
    result = {
        "engine": ENGINE,
        "versions": versions,
        "manifest_kind": kind,
        "run_results_kind": run_results_kind,
        "catalog_kind": catalog_kind,
        "parse": parse,
        "build": build,
        "docs_generate": docs,
        "metadata_files": _metadata_listing(),
        "gates": gates,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
