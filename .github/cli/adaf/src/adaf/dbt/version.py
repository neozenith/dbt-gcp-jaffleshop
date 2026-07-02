"""Detect the dbt engine's version + capabilities from ``dbt --version``.

The `selector:` selection method — referencing a named YAML selector inside ``--select`` so it can be
intersected with ``state:modified`` in ONE expression — lands in dbt **1.12** (and dbt Fusion 2.x).
On 1.12+, ``adaf ls --flags --state-modified[-plus]`` can emit the **native** expression
(``selector:NAME,state:modified+``) and let dbt do the intersection; on ≤1.11 it must emit the
**backported** equivalent (the seed resolved to concrete model paths by the offline calculator,
because 1.11 cannot combine a named selector with ``state:modified`` in one expression).

The version banner differs per engine: dbt-core prints ``installed: 1.11.11``; Fusion prints
``dbt-fusion 2.0.0-preview.190``; the dbt **Cloud CLI** prints ``dbt Cloud CLI - 0.40.15`` (its OWN
version, not the dbt-core it proxies). :func:`dbt_version` parses these for informational use, and
:func:`_parse_version` is its pure, unit-tested core.

**Capability is PROBED, not inferred from the version** (:func:`supports_selector_method`): the matrix
proved the `selector:` method does NOT track the version number — dbt-core 1.12 has it, but the 2.0
alpha and Fusion do not, despite higher versions. So the only gate that drives flag generation runs a
real ``dbt ls`` probe; the parsed version is advisory.
"""

# Standard Library
import functools
import re

# Local
from adaf.dbt.runner import run_dbt

# The first dbt-core line with the `selector:` method (Fusion 2.x has it too — 2 >= 1.12 by tuple order).
_SELECTOR_METHOD_MIN = (1, 12, 0)

# dbt-core: "  - installed: 1.11.11"; Fusion: "dbt-fusion 2.0.0-preview.190". The Cloud CLI banner
# ("dbt Cloud CLI - 0.40.15") matches NEITHER, so it yields None (→ backport).
_CORE_RE = re.compile(r"installed:\s*(\d+)\.(\d+)\.(\d+)")
_FUSION_RE = re.compile(r"dbt-fusion\s+(\d+)\.(\d+)\.(\d+)")


def _parse_version(banner: str) -> tuple[int, int, int] | None:
    """Extract ``(major, minor, patch)`` from a ``dbt --version`` banner; ``None`` if it is neither a
    dbt-core nor a Fusion banner (e.g. the dbt Cloud CLI, whose banner carries only its own version)."""
    m = _CORE_RE.search(banner) or _FUSION_RE.search(banner)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


@functools.lru_cache(maxsize=1)
def dbt_version() -> tuple[int, int, int] | None:
    """The ``(major, minor, patch)`` of the ``dbt`` on PATH, or ``None`` when undetectable.

    Cached: the binary on PATH does not change within a process. ``None`` for the dbt Cloud CLI (its
    banner reports the CLI version, not the proxied dbt-core version)."""
    return _parse_version(run_dbt(["--version"]))


@functools.lru_cache(maxsize=8)
def supports_selector_method(selector: str) -> bool:
    """Whether the dbt on PATH resolves the 1.12 ``selector:`` method — **PROBED, not inferred** from
    the version, and cached per (process, selector).

    Version number does NOT predict this capability: dbt-core 1.12 has the method, but the dbt-core 2.0
    *alpha* and the dbt **Fusion** engine do NOT, despite higher version strings (verified in
    ``tests/multiversion/`` — their ``dbt ls --select selector:…`` exits non-zero). So we run one live
    ``dbt ls --select selector:<selector>`` (no ``--state`` needed for a bare selector reference):
    exit 0 ⇒ the method resolves ⇒ adaf may emit the native expression; any non-zero exit ⇒ fall back
    to the resolved-paths backport, which runs on every engine. A false negative is harmless (backport
    is always valid); the probe never false-positives (it returns True only on a real success)."""
    try:
        run_dbt(["ls", "--quiet", "--select", f"selector:{selector}", "--resource-type", "model", "--output", "path"])
        return True
    except RuntimeError:
        return False
