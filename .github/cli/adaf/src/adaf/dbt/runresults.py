"""The run-results artifact seam — the build-summary input for ``adaf report``.

Mirrors :mod:`adaf.dbt.artifact` (the *manifest* seam) one artifact across: a
:class:`RunResultsArtifact` protocol with a JSON reader for ``run_results.json`` (v6) and a parquet
reader for the dbt **Fusion** (v2.0) run set. :func:`load_run_results` detects which to build,
mirroring :func:`adaf.dbt.artifact.load_artifact` (a directory ⇒ parquet wins).

This module deliberately does **not** project the manifest — node ``name``/``original_file_path``
lookups come from :class:`adaf.dbt.manifest_view.ManifestView` (the existing manifest seam, already
format-agnostic across JSON v12 and the Fusion parquet set). Only the run-results shape lives here.

Both readers are exercised for real: the v6 JSON path by every dbt-core line, the parquet path by a
synthesised-fixture unit test AND the multiversion ``run_results`` probe (which captured + verified
the Fusion layout — see :class:`ParquetRunResultsArtifact` + docs/dbt-fusion-artifacts.md).
"""

# Standard Library
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# First Party
from adaf.dbt.artifact import read_parquet_rows

# Union of the status values across the run-results v6 status enums (+ Fusion's "skipped"/"success").
ERROR_STATUSES = frozenset({"error", "fail", "runtime error"})
WARNING_STATUSES = frozenset({"warn", "partial success"})

# The dbt Fusion (v2.0) run set under the target dir — VERIFIED against real `dbt build --write-index`
# output (Fusion 2.0.0-preview.190; captured by the multiversion `run_results` probe — see
# tests/multiversion + docs/dbt-fusion-artifacts.md). `results` is one row per node (with an
# `invocation_id`); `invocations` carries per-invocation `elapsed_secs` + `ingested_at`. Two schema
# versions of the invocations table can coexist (a command writes whichever is current), so both are read.
_FUSION_RESULTS = Path("metadata/run/results/v1_0.parquet")
_FUSION_INVOCATIONS = (Path("metadata/run/invocations/v1_1.parquet"), Path("metadata/run/invocations/v1_0.parquet"))


@dataclass(frozen=True)
class Result:
    """One ``RunResultOutput`` (run-results v6)."""

    unique_id: str
    status: str
    message: str | None = None
    failures: int | None = None


@dataclass(frozen=True)
class RunResults:
    """Subset of ``RunResultsArtifact`` (run-results v6) the build summary needs."""

    generated_at: str | None
    elapsed_time: float
    results: list[Result] = field(default_factory=list)


def status_str(status: Any) -> str:
    """Lowercase a status value (str or enum-like), or ``"unknown"`` for ``None``."""
    if status is None:
        return "unknown"
    return str(getattr(status, "value", status)).lower()


def result_message(result: Result) -> str:
    """Human message for a result: the dbt message, else a failing-row count, else a placeholder."""
    if result.message:
        return str(result.message)
    if result.failures:
        return f"{result.failures} failing rows"
    return "No additional details provided"


class RunResultsArtifact(Protocol):
    """A dbt run-results set, presented as the normalised :class:`RunResults` the summary consumes."""

    def run_results(self) -> RunResults: ...


class JsonRunResultsArtifact:
    """Today's reader: a dbt ``run_results.json`` parsed with :func:`json.loads`."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def load(cls, path: Path | str) -> "JsonRunResultsArtifact":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def run_results(self) -> RunResults:
        results: list[Result] = []
        for item in self._data.get("results") or []:
            if not isinstance(item, dict):
                continue
            uid, status = item.get("unique_id"), item.get("status")
            if not isinstance(uid, str) or not isinstance(status, str):
                continue  # both schema-required; skip malformed entries rather than fabricate
            results.append(Result(uid, status, item.get("message"), item.get("failures")))
        return RunResults(
            generated_at=(self._data.get("metadata") or {}).get("generated_at"),
            elapsed_time=float(self._data.get("elapsed_time") or 0.0),
            results=results,
        )


class ParquetRunResultsArtifact:
    """dbt **Fusion** (v2.0) run-results reader: the parquet run set, read with duckdb.

    **Verified on-disk layout** (Fusion ``dbt build --write-index``, captured by the multiversion probe):

    * ``metadata/run/results/v1_0.parquet`` — one row per node: ``unique_id``, ``status``
      (``success`` / ``error`` / ``skipped`` / …), ``message``, ``failures`` (nullable), plus an
      ``invocation_id`` tying the row to the build that produced it.
    * ``metadata/run/invocations/v1_{0,1}.parquet`` — one row per dbt invocation: ``invocation_id``,
      ``elapsed_secs``, ``ingested_at`` (+ ``command`` etc.). The build invocation supplies the
      summary's ``elapsed_time`` + ``generated_at``.

    Results accumulate across invocations, so the rows of the **most recent** invocation (max
    ``ingested_at``) are taken. duckdb is imported inside the class (the JSON path stays duckdb-free);
    schema drift fails loudly via :func:`adaf.dbt.artifact.read_parquet_rows`.
    """

    def __init__(self, target_dir: Path | str) -> None:
        try:
            # Third Party — feature-gated: only the parquet path needs duckdb (mirrors the manifest reader).
            import duckdb
        except ImportError as exc:  # loud, explicit — never a silent fall back to JSON
            raise ImportError(
                "Reading a dbt Fusion (v2.0) parquet run-results set requires duckdb, which is not "
                "installed. Install the optional extra: pip install 'adaf[fusion]'."
            ) from exc

        self._dir = Path(target_dir)
        results_pq = self._dir / _FUSION_RESULTS
        if not results_pq.exists():
            raise ValueError(
                f"'{self._dir}' is not a dbt Fusion run artifact set: missing '{_FUSION_RESULTS}'. "
                "Run `dbt build --write-index` under the Fusion engine."
            )

        con = duckdb.connect(database=":memory:")
        try:
            rows = read_parquet_rows(
                con, results_pq, ("invocation_id", "unique_id", "status", "message", "failures", "ingested_at")
            )
            if not rows:
                self._rr = RunResults(generated_at=None, elapsed_time=0.0, results=[])
                return
            latest = max(rows, key=lambda r: r["ingested_at"])["invocation_id"]
            results = [
                Result(str(r["unique_id"]), str(r["status"]), r["message"], _int_or_none(r["failures"]))
                for r in rows
                if r["invocation_id"] == latest
            ]
            generated_at, elapsed = self._invocation(con, latest)
            self._rr = RunResults(generated_at=generated_at, elapsed_time=elapsed, results=results)
        finally:
            con.close()

    def _invocation(self, con: Any, invocation_id: Any) -> tuple[str | None, float]:
        """``(generated_at, elapsed_time)`` for ``invocation_id`` from whichever invocations table holds it."""
        for rel in _FUSION_INVOCATIONS:
            path = self._dir / rel
            if not path.exists():
                continue
            for r in read_parquet_rows(con, path, ("invocation_id", "elapsed_secs", "ingested_at")):
                if r["invocation_id"] == invocation_id:
                    generated_at = str(r["ingested_at"]) if r["ingested_at"] is not None else None
                    return generated_at, float(r["elapsed_secs"] or 0.0)
        return (None, 0.0)

    def run_results(self) -> RunResults:
        return self._rr


def _int_or_none(value: Any) -> int | None:
    return int(value) if value is not None else None


def load_run_results(path: Path | str) -> RunResults | None:
    """Detect a dbt run-results set at ``path`` and return its :class:`RunResults`, or ``None`` if absent.

    A *directory* probes the Fusion parquet set FIRST (parquet wins, mirroring
    :func:`adaf.dbt.artifact.load_artifact` — so a Fusion dir exercises the new format), then
    ``run_results.json``. A *file* path is read as JSON. Absence is legitimate (no build ran) → ``None``.
    """
    p = Path(path)
    if p.is_dir():
        if (p / _FUSION_RESULTS).exists():
            return ParquetRunResultsArtifact(p).run_results()
        if (p / "run_results.json").exists():
            return JsonRunResultsArtifact.load(p / "run_results.json").run_results()
        return None
    if not p.exists():
        return None
    return JsonRunResultsArtifact.load(p).run_results()
