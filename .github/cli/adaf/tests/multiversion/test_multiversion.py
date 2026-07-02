"""dbt version-matrix integration suite — the real thing, not a skip-scaffold.

Every engine in the matrix is built from ONE parametrised Dockerfile (``tests/multiversion/docker/Dockerfile``)
by passing that engine's **build args**: the image pip-installs that exact dbt-core + adapter pin plus
adaf, ``dbt parse``s the committed ``fixture/`` project under it, runs adaf's read-only gates against
the resulting artifact, and snapshots their stdout / stderr / exit codes against a committed per-LINE
golden (``goldens/<capability>/<series-id>.txt``). A diff is the regression signal: if a new dbt parser
drops or renames a manifest field one of adaf's projections reads, the snapshot diverges and the test
fails loudly (escalators-not-stairs — never a silent skip).

The matrix is defined as version LINES, not fixed pins: a :class:`Series` per dbt-core line (1.11 / 1.12
/ 2.0) carries the line's PROPERTIES (parser flag, adaf extra, fixture spec profile) and a PEP 440
``specifier``; the concrete patch is **resolved from PyPI when the test runs** (:func:`_resolve_dbt_core`).
So a fresh prerelease — or the GA that supersedes it — auto-enrols in the matrix the moment it lands on
PyPI, with no edit here: lines that ``track_prereleases`` take the newest alpha/beta/rc, and a later GA
wins automatically by being the higher version. Each ``Series`` resolves to a concrete :class:`Engine`
(a plain pip install of that dbt-core + ``dbt-duckdb`` into an isolated venv), whose ``name`` is the
resolved version (``dbt2-0-0a2``) — but the GOLDENS are keyed by the STABLE line id (``dbt-2.0``).

That split is deliberate. The gate goldens (``list`` / ``docscov`` / ``testcov`` / ``sdag-check``) are
version-INDEPENDENT (they depend only on the fixture spec profile), so a new patch with unchanged
behaviour re-passes them automatically; only the version-bearing ``parse`` golden differs across a
float, so a newly-resolved version surfaces as a single deliberate ``parse`` re-baseline that records
exactly which version is now under test. A genuine behavioural change (a dropped field, a new parquet
artifact kind) still diverges a gate golden and fails loudly.

Marked ``multiversion`` and **deselected by default** (see pyproject ``addopts``), so ``make ci`` never
builds an image OR hits PyPI (the resolve lives in the test body, not at collection). ``testcontainers``
and ``packaging`` are HARD dev dependencies, imported unconditionally below: if missing the suite ERRORS
LOUDLY (never skips) — deselection by marker, not absence of a dep, is what keeps Docker off ci. Run the
suite with ``make -C .github/cli/adaf adaf-multiversion-ci`` (which re-selects it with ``-m multiversion``).

Re-baseline deliberately, never automatically: ``ADAF_GOLDEN_UPDATE=1`` (the ``…-rebaseline`` target)
writes goldens for the lines that ran; review the diff and commit it (the ``parse`` golden's version
bump is the record of which prerelease/GA the line now tracks).
"""

# Standard Library
import functools
import io
import json
import os
import re
import shutil
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Third Party — HARD dependencies (dev group). No importorskip: the suite REQUIRES these and must
# error loudly if they are absent (escalators-not-stairs); the `multiversion` marker, not a missing
# import, is what keeps this off `make ci`.
import docker
import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
from testcontainers.core.image import DockerImage

HERE = Path(__file__).resolve().parent  # tests/multiversion
ADAF_ROOT = HERE.parents[1]  # .github/cli/adaf
REPO_ROOT = ADAF_ROOT.parents[2]  # repo root (.github/cli/adaf -> .github/cli -> .github -> repo)
DOCKER_DIR = HERE / "docker"
DOCKERFILE = DOCKER_DIR / "Dockerfile"  # the SINGLE, ARG-parametrised Dockerfile for every engine
FIXTURE_DIR = HERE / "fixture"
GOLDENS_DIR = HERE / "goldens"
BUILD_ROOT = REPO_ROOT / "tmp" / "multiversion"  # project-local tmp (never system /tmp)

SELECTOR = "matrix_demo"
UPDATE = os.environ.get("ADAF_GOLDEN_UPDATE") == "1"

# Where each engine parses the fixture inside the container, and where we persist a copy of that
# parsed `target/` back onto the host for inspection after the run (one dir per engine, so every
# engine's artifacts — manifest.json, or whatever a v2.0 engine emits — survive the run).
CONTAINER_TARGET = "/fixture/target"  # harness.py: `dbt parse --target-path /fixture/target`

# Runtime artifacts that must NOT enter the build context (force a genuine in-container parse).
_FIXTURE_EXCLUDE = shutil.ignore_patterns("target", "logs", "tmp", "*.duckdb", ".user.yml")

# Per-PROFILE fixture variants: a file named ``<base>__<profile>.<ext>`` (profile = ``legacy`` |
# ``inline``) is staged ONLY into a line whose ``spec_profile`` matches, with the ``__<profile>``
# suffix stripped to ``<base>.<ext>``. This lets one fixture carry the dbt semantic-layer spec each
# line needs — the legacy standalone ``semantic_models:`` resource (dbt ≤1.11) vs the inline
# ``semantic_model:`` block (dbt 1.12+/2.0), which are mutually exclusive and cannot share one file.
# Keying on the profile (not a version id) is what keeps the variants stable as a line's pin floats.
_VARIANT_RE = re.compile(r"__([A-Za-z0-9.\-]+)(\.(?:ya?ml|sql))$")


PYPI_DBT_CORE_JSON = "https://pypi.org/pypi/dbt-core/json"


@functools.lru_cache(maxsize=1)
def _pypi_dbt_core_versions() -> tuple[Version, ...]:
    """Every installable (non-yanked, has-files) dbt-core version on PyPI, ascending.

    Fetched ONCE per process and ONLY from a running test body — never at import/collection — so
    ``make ci`` (which deselects this suite by the ``multiversion`` marker before any test body runs)
    makes no network call and stays offline. A network or parse failure raises **loudly**: there is
    deliberately NO offline fallback to a hard-coded version list, because silently substituting one
    would hide that the matrix had stopped discovering new releases (escalators-not-stairs).
    """
    try:
        with urllib.request.urlopen(PYPI_DBT_CORE_JSON, timeout=30) as resp:  # noqa: S310 (https only)
            payload = json.load(resp)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"could not reach PyPI ({PYPI_DBT_CORE_JSON}) to discover dbt-core releases: {exc}. "
            f"The multiversion matrix resolves its pins from PyPI and needs network."
        ) from exc
    versions: list[Version] = []
    for raw, files in (payload.get("releases") or {}).items():
        if not files or all(f.get("yanked") for f in files):
            continue  # no distributable files, or every file yanked → not installable, skip
        try:
            versions.append(Version(raw))
        except InvalidVersion:
            continue
    if not versions:
        raise RuntimeError(f"PyPI returned no installable dbt-core versions at {PYPI_DBT_CORE_JSON}")
    return tuple(sorted(versions))


def _resolve_dbt_core(specifier: str, *, track_prereleases: bool) -> Version:
    """The newest dbt-core on PyPI matching ``specifier``.

    With ``track_prereleases`` the alphas/betas/rcs of the line are eligible — and a later GA still
    wins, being the higher version — so a line auto-promotes prerelease → GA the instant the GA
    publishes. Raises loudly when nothing matches (a moved line is a finding, not a silent skip).
    """
    spec = SpecifierSet(specifier, prereleases=track_prereleases)
    eligible = [v for v in _pypi_dbt_core_versions() if v in spec]
    if not eligible:
        raise RuntimeError(
            f"no dbt-core release on PyPI satisfies {specifier!r} (track_prereleases={track_prereleases}). "
            f"Has the version line moved on? Update the matching Series specifier."
        )
    return max(eligible)


@dataclass(frozen=True)
class Engine:
    """One CONCRETE row of the matrix — a ``Series`` resolved to an exact dbt-core version. Carries the
    build args the SINGLE Dockerfile is parametrised by, so images differ only in their ``buildargs``
    (there is no per-engine Dockerfile). Every engine is a plain pip install of dbt-core + an adapter
    into an isolated venv."""

    name: str  # the resolved version id, e.g. "dbt1-12-0b3" — baked as ENGINE_NAME + shown in logs
    dbt_core_spec: str  # pip spec for the resolved dbt-core, e.g. "dbt-core==1.12.0b3"
    series_id: str  # the owning line's STABLE id (e.g. "dbt-1.12") — the golden key + host dir name
    spec_profile: str  # "legacy" | "inline" — which fixture semantic-layer variant to stage
    dbt_adapter_spec: str = "dbt-duckdb==1.10.1"  # pip spec for the adapter
    parse_flags: str = ""  # extra `dbt parse` flags, e.g. "--use-v2-parser" / "--write-index"
    adaf_install_spec: str = "/opt/adaf_pkg"  # or "/opt/adaf_pkg[fusion]" for the parquet reader
    pip_prerelease: str = "disallow"  # uv --prerelease: "allow" for pre-release pins (beta / alpha)
    kind: str = "pip"  # "pip" (dbt-core+adapter venv) | "fusion" (Rust binary via the CDN installer)

    def build_args(self) -> dict[str, str]:
        """The exact ``buildargs`` dict handed to the single Dockerfile for this engine."""
        return {
            "ENGINE_NAME": self.name,
            "ENGINE_KIND": self.kind,
            "DBT_CORE_SPEC": self.dbt_core_spec,
            "DBT_ADAPTER_SPEC": self.dbt_adapter_spec,
            "PARSE_FLAGS": self.parse_flags,
            "ADAF_INSTALL_SPEC": self.adaf_install_spec,
            "SELECTOR": SELECTOR,
            "PIP_PRERELEASE": self.pip_prerelease,
        }


@dataclass(frozen=True)
class Series:
    """A dbt-core version LINE the matrix tracks. The concrete patch is resolved from PyPI when the
    test RUNS (see :func:`_pypi_dbt_core_versions`), so a fresh prerelease — or the GA that supersedes
    it — auto-joins the matrix the moment it lands on PyPI, with no edit here. Only version-line
    PROPERTIES live on the Series (parser flag, adaf extra, fixture spec profile); the patch floats.

    Because the line ``id`` is stable across that float, the goldens are keyed by it: a new patch with
    UNCHANGED gate behaviour re-passes the gate goldens automatically, and only the version-bearing
    ``parse`` golden needs a (deliberate) one-line re-baseline that records the new version."""

    id: str  # STABLE pytest param id AND golden key, e.g. "dbt-1.12" — never the floating version
    specifier: str  # PEP 440 line, e.g. ">=1.12.0a0,<1.13" (ignored for kind="fusion": not on PyPI)
    spec_profile: str  # "legacy" | "inline" — selects the fixture's semantic-layer variant
    track_prereleases: bool = False  # True ⇒ alphas/betas/rcs eligible (a later GA still wins)
    dbt_adapter_spec: str = "dbt-duckdb==1.10.1"
    parse_flags: str = ""
    adaf_install_spec: str = "/opt/adaf_pkg"
    kind: str = "pip"  # "pip" (resolved from PyPI) | "fusion" (Rust binary, floats to CDN latest)

    def resolve(self) -> Engine:
        """Resolve this line to a concrete :class:`Engine` to build.

        pip lines pin to their newest matching PyPI release. The fusion line does NOT touch PyPI (the
        Fusion engine ships only via the public CDN installer, which always fetches the latest); its
        concrete version is discovered at run time from ``dbt --version`` and recorded in the parse
        golden — so "float to latest" holds for Fusion exactly as it does for the pip lines."""
        if self.kind == "fusion":
            return Engine(
                name="dbt-fusion",
                dbt_core_spec="dbt-fusion (public CDN installer, latest)",
                series_id=self.id,
                spec_profile=self.spec_profile,
                parse_flags=self.parse_flags or "--write-index",
                adaf_install_spec=self.adaf_install_spec,
                kind="fusion",
            )
        version = _resolve_dbt_core(self.specifier, track_prereleases=self.track_prereleases)
        return Engine(
            name=f"dbt{str(version).replace('.', '-')}",
            dbt_core_spec=f"dbt-core=={version}",
            series_id=self.id,
            spec_profile=self.spec_profile,
            dbt_adapter_spec=self.dbt_adapter_spec,
            parse_flags=self.parse_flags,
            adaf_install_spec=self.adaf_install_spec,
            pip_prerelease="allow" if self.track_prereleases else "disallow",
        )


# The matrix as version LINES, not pins. Each line floats to its newest PyPI release at test time, so
# new prereleases and the eventual GA enrol automatically. `spec_profile` picks the fixture's
# semantic-layer form (legacy standalone `semantic_models:` for ≤1.11; inline `semantic_model:` for
# 1.12+/2.0) — see the fixture `__<profile>` variants.
SERIES: list[Series] = [
    # Stable maintenance line — GA Python parser, the clean reference row. Floats to the latest 1.11
    # PATCH; never a prerelease.
    Series(id="dbt-1.11", specifier=">=1.11,<1.12", spec_profile="legacy"),
    # The 1.12 line — Rust v2 parser via the opt-in `--use-v2-parser`. Tracks the latest 1.12
    # prerelease today and auto-promotes to the 1.12.0 GA when it publishes (GA > any 1.12 prerelease).
    Series(
        id="dbt-1.12",
        specifier=">=1.12.0a0,<1.13",
        spec_profile="inline",
        track_prereleases=True,
        parse_flags="--use-v2-parser",
    ),
    # The 2.0 line — dbt-core 2.0 from PyPI (alphas now → beta → GA). NOTE: pip dbt-core 2.0 still emits
    # a v12 JSON manifest.json (NOT the v20 parquet set — that is Fusion-only; see the dbt-fusion row and
    # docs/dbt-fusion-artifacts.md). Installs adaf[fusion] anyway so the row is ready if that changes.
    Series(
        id="dbt-2.0",
        specifier=">=2.0.0a0,<3",
        spec_profile="inline",
        track_prereleases=True,
        adaf_install_spec="/opt/adaf_pkg[fusion]",
    ),
    # The dbt FUSION engine — the Rust binary (NOT on PyPI; installed from the public CDN, floats to
    # latest). This is the row that truly exercises the v20 PARQUET artifact set: it parses with
    # `--write-index` and adaf reads `target/metadata/parse/*.parquet` via ParquetManifestArtifact.
    Series(
        id="dbt-fusion",
        specifier="",  # unused: fusion is not resolved from PyPI
        spec_profile="inline",
        kind="fusion",
        parse_flags="--write-index",
        adaf_install_spec="/opt/adaf_pkg[fusion]",
    ),
]


def _stage_context(series_id: str, profile: str) -> Path:
    """Assemble a minimal build context under ``tmp/multiversion/<series-id>/context``: the adaf
    package (pyproject + src), the fixture (sans runtime artifacts) overlaid with this line's spec
    ``profile`` variant, the shared runner, and the SINGLE Dockerfile.

    Staging keeps the Docker build context tiny and deterministic — building straight from the adaf
    tree would tar the whole repo subtree (including ``tmp/`` venvs) into the daemon.
    """
    ctx = BUILD_ROOT / series_id / "context"
    if ctx.exists():
        shutil.rmtree(ctx)
    pkg = ctx / "adaf_pkg"
    pkg.mkdir(parents=True)
    shutil.copy(ADAF_ROOT / "pyproject.toml", pkg / "pyproject.toml")
    shutil.copytree(ADAF_ROOT / "src", pkg / "src")
    _stage_fixture(profile, ctx / "fixture")
    shutil.copy(DOCKER_DIR / "harness.py", ctx / "harness.py")
    shutil.copy(DOCKERFILE, ctx / "Dockerfile")
    return ctx


def _stage_fixture(profile: str, dest: Path) -> None:
    """Copy the fixture into ``dest``, resolving per-PROFILE ``__<profile>`` variants.

    Every non-variant file is copied as-is; a ``<base>__<profile>.<ext>`` file is copied **only** when
    ``<profile>`` matches this line's spec profile, renamed to ``<base>.<ext>``. Variants for the other
    profile are skipped, so each engine's context carries exactly the dbt semantic-layer spec form its
    line understands (legacy standalone ``semantic_models:`` vs the inline ``semantic_model:`` block).

    Keying on the spec PROFILE (not the version) is what lets a line's pin float: a new ``dbt-1.12``
    prerelease still stages the ``inline`` variant without renaming any fixture file.
    """

    def _ignore(dirpath: str, names: list[str]) -> set[str]:
        skip = set(_FIXTURE_EXCLUDE(dirpath, names))
        skip.update(n for n in names if _VARIANT_RE.search(n))  # all variants out of the base copy
        return skip

    shutil.copytree(FIXTURE_DIR, dest, ignore=_ignore)
    for src in FIXTURE_DIR.rglob("*"):
        m = _VARIANT_RE.search(src.name)
        if not src.is_file() or m is None or m.group(1) != profile:
            continue
        out = dest / src.relative_to(FIXTURE_DIR).parent / _VARIANT_RE.sub(r"\2", src.name)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, out)


def _copy_target_out(container: "docker.models.containers.Container", series_id: str) -> Path:
    """Persist the container's parsed ``/fixture/target`` onto the host at
    ``tmp/multiversion/<series-id>/target/`` so every line's artifacts survive the run for inspection
    (``docker cp`` semantics via docker-py ``get_archive``).

    Using ``get_archive`` (rather than a bind-mount) captures whatever the engine actually wrote —
    ``manifest.json``, or a v2.0 engine's own artifact tree (parquet etc.) — as an exact tar of
    container state, with no Docker-Desktop bind-mount or root-ownership quirks. The host dir is wiped
    first so stale artifacts from a prior run can never mislead.
    """
    dest_parent = BUILD_ROOT / series_id
    dest = dest_parent / "target"
    if dest.exists():
        shutil.rmtree(dest)
    dest_parent.mkdir(parents=True, exist_ok=True)
    # get_archive yields a tar stream whose members are rooted at `target/`; extracting into
    # dest_parent reconstitutes `tmp/multiversion/<series-id>/target/...`.
    bits, _stat = container.get_archive(CONTAINER_TARGET)
    stream = io.BytesIO(b"".join(bits))
    with tarfile.open(fileobj=stream) as tar:
        tar.extractall(dest_parent, filter="data")
    return dest


def _run_engine(engine: Engine) -> dict[str, object]:
    """Build the engine's image FROM THE ONE DOCKERFILE with its build args (testcontainers
    ``DockerImage(..., buildargs=...)``), run its container (docker-py), persist the parsed
    ``target/`` back to the host, and return the parsed JSON result. Build logs are streamed to
    stdout for evidence (-s).

    The container is run **detached** (not the old one-shot ``remove=True``) so it survives long
    enough to ``docker cp`` its ``/fixture/target`` out before removal — the JSON result still comes
    from its stdout exactly as before."""
    sid = engine.series_id  # host-side key (context dir, image tag, goldens); engine.name is the version
    ctx = _stage_context(sid, engine.spec_profile)
    args = engine.build_args()
    print(f"\n===== [{sid}] docker build ({engine.dbt_core_spec}) ({ctx}) =====", flush=True)
    print(f"      build args: {json.dumps(args)}", flush=True)
    with DockerImage(path=ctx, tag=f"adaf-mv-{sid}:test", clean_up=True, buildargs=args) as image:
        for line in image.get_logs():
            stream = line.get("stream") if isinstance(line, dict) else None
            if stream:
                print(stream, end="", flush=True)
        client = docker.from_env()
        print(f"===== [{sid}] docker run =====", flush=True)
        container = client.containers.run(str(image), detach=True, stdout=True, stderr=False)
        try:
            container.wait()
            raw = container.logs(stdout=True, stderr=False)
            dest = _copy_target_out(container, sid)
            print(f"===== [{sid}] target persisted -> {dest} =====", flush=True)
        finally:
            container.remove(force=True)
    data: dict[str, object] = json.loads(raw.decode("utf-8"))
    (BUILD_ROOT / sid / "result.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _slug(label: str) -> str:
    """Capability label → directory-safe slug (``sdag check`` → ``sdag-check``)."""
    return label.strip().replace(" ", "-")


def _render_goldens(data: dict[str, object]) -> dict[str, str]:
    """Render ONE golden per capability, keyed by capability slug.

    The layout is ``goldens/<capability>/<engine>.txt`` so a single capability can be diffed straight
    across versions (the engine/version is the filename, not in-file noise). Capabilities are the
    ``parse`` metadata pseudo-gate plus each adaf gate (``list`` / ``docscov`` / ``testcov`` /
    ``sdag-check``). All paths inside are stable container paths and versions come from exact pins, so
    the rendering is portable across machines with no normalisation needed.
    """
    versions = data["versions"]
    assert isinstance(versions, dict)
    parse = data["parse"]
    assert isinstance(parse, dict)
    out: dict[str, str] = {}

    # `parse` capability — the per-engine ARTIFACT capture: versions, the format of each dbt artifact
    # (manifest / run_results / catalog — json vs the Fusion parquet set), the parse/build/docs exit
    # codes, and the real listing of `target/metadata` (so a new Fusion parquet artifact surfaces here).
    # Only deterministic fields: dbt's stdout/stderr tails carry wall-clock timestamps and per-run
    # durations (`[31ms]`), so they stay in result.json for debugging but are NOT enshrined in the golden.
    build = data["build"]
    assert isinstance(build, dict)
    docs = data["docs_generate"]
    assert isinstance(docs, dict)
    metadata_files = data.get("metadata_files") or []
    assert isinstance(metadata_files, list)
    ver = ", ".join(f"{k}=={v}" for k, v in sorted(versions.items()))
    out["parse"] = (
        "\n".join(
            [
                f"# versions: {ver}",
                f"# manifest artifact: {data['manifest_kind']}",
                f"# run_results artifact: {data['run_results_kind']}",
                f"# catalog artifact: {data['catalog_kind']}",
                f"--- dbt parse exit: {parse['exit']}",
                f"--- dbt build exit: {build['exit']}",
                f"--- dbt docs generate exit: {docs['exit']}",
                "--- target/metadata files:",
                *(f"  {p}" for p in metadata_files),
            ]
        )
        + "\n"
    )

    # One golden per adaf gate — just that gate's invocation + exit/stdout/stderr.
    gates = data["gates"]
    assert isinstance(gates, list)
    for g in gates:
        argv = " ".join(str(a) for a in g["argv"])
        out[_slug(str(g["label"]))] = (
            "\n".join(
                [
                    f"## gate: adaf {argv}",
                    f"--- exit: {g['exit']}",
                    "--- stdout:",
                    str(g["stdout"]).rstrip("\n"),
                    "--- stderr:",
                    str(g["stderr"]).rstrip("\n"),
                ]
            )
            + "\n"
        )
    return out


@pytest.mark.multiversion
@pytest.mark.parametrize("series", [pytest.param(s, id=s.id) for s in SERIES])
def test_series_matches_golden(series: Series) -> None:
    # Resolve the line's pin from PyPI HERE (in the test body, never at collection) so `make ci`,
    # which deselects this suite by marker before any body runs, never touches the network. A new
    # prerelease or GA on this line is picked up automatically by this resolve.
    engine = series.resolve()
    print(f"\n[{series.id}] resolved to {engine.dbt_core_spec} (engine id {engine.name})", flush=True)

    data = _run_engine(engine)
    actual = _render_goldens(data)

    if UPDATE:
        for capability, text in actual.items():
            golden = GOLDENS_DIR / capability / f"{series.id}.txt"
            golden.parent.mkdir(parents=True, exist_ok=True)
            golden.write_text(text, encoding="utf-8")
        print(f"\n[{series.id}] goldens written: {sorted(actual)} ({engine.dbt_core_spec})", flush=True)
        return

    for capability, text in actual.items():
        golden = GOLDENS_DIR / capability / f"{series.id}.txt"
        assert golden.exists(), (
            f"no committed golden for capability '{capability}' / line '{series.id}' at {golden} "
            f"(resolved {engine.dbt_core_spec}). This line ran for real — re-baseline with "
            f"`make -C .github/cli/adaf adaf-multiversion-rebaseline` and commit it."
        )
        expected = golden.read_text(encoding="utf-8")
        assert text == expected, (
            f"adaf '{capability}' output for line '{series.id}' ({engine.dbt_core_spec}) drifted from "
            f"goldens/{capability}/{series.id}.txt.\nInspect tmp/multiversion/{series.id}/result.json, "
            f"confirm the diff is an intended dbt change (not an adaf regression), then re-baseline. "
            f"Actual:\n{text}"
        )
