"""Manifest-backed coverage gates: documentation and test coverage of selected models.

Unlike the shell-out gates in ``checks.py``, these read dbt's ``manifest.json`` directly
and join it against the resolved model files:

* ``docs``  — a model passes if its ``description`` is non-empty.
* ``tests`` — a model passes if at least one test node depends on it (``test_count > 0``).

A selected file absent from the manifest fails the check with a "not in manifest" reason —
the usual cause is a stale manifest, so re-run ``dbt parse`` (or pass ``--parse``).

A gap doesn't live in the model's ``.sql`` — a missing description or test is declared in the
model's *schema* YAML. So each gap finding is anchored at that schema file, resolved from the
manifest node's ``patch_path`` (``"<project>://models/.../_schema.yml"`` → repo-relative path),
and at the line of the model's ``- name: <model>`` entry when it can be found by a best-effort
scan. When ``patch_path`` is absent/unresolvable the finding falls back to the ``.sql`` path with
no line — never a fabricated one.
"""

# Standard Library
from pathlib import Path

# Local
from adaf import report
from adaf.dbt.manifest import Manifest, ModelDoc
from adaf.dbt.manifest_view import ManifestView
from adaf.dbt.runner import dbt_parse

# One-shot remediation guidance, emitted once per run (not per finding) when gaps exist. The findings
# already point at ``schema.yml:line``; this tells the user what to put there, and links the dbt docs.
_DOCSCOV_GUIDANCE = (
    "docscov: to fix, add a `description:` for the model in its schema YAML (`_*.yml`) — "
    "https://docs.getdbt.com/reference/resource-properties/description"
)
_TESTCOV_GUIDANCE = (
    "testcov: to fix, add `data_tests:` (or `tests:`) under the model or its columns in the schema YAML — "
    "https://docs.getdbt.com/reference/resource-properties/data-tests"
)


def load_manifest(path: Path, *, parse: bool = False, target: str | None = None, cwd: Path | None = None) -> Manifest:
    """Load the manifest, optionally refreshing it first via ``dbt parse`` (fail loud)."""
    if parse:
        dbt_parse(cwd, target=target)
    if not Path(path).exists():
        raise FileNotFoundError(f"dbt manifest not found at '{path}'. Run `dbt parse` or pass --parse.")
    return Manifest.load(path)


def _strip_scheme(patch_path: str) -> str:
    """``"<project>://models/.../_schema.yml"`` → ``"models/.../_schema.yml"`` (pass through if no scheme)."""
    _, sep, rest = patch_path.partition("://")
    return rest if sep else patch_path


def _schema_index(manifest_path: Path | None) -> dict[str, str]:
    """Map each model's ``.sql`` ``original_file_path`` → its repo-relative schema YAML (from ``patch_path``).

    Built read-only from a :class:`~adaf.dbt.manifest_view.ManifestView` because the
    :class:`~adaf.dbt.manifest.Manifest` projection doesn't carry ``patch_path``. Empty when no path is
    given (the caller then falls back to the ``.sql`` location); a model with no ``patch_path`` is simply
    omitted.
    """
    if manifest_path is None or not Path(manifest_path).exists():
        return {}
    view = ManifestView.load(manifest_path)
    index: dict[str, str] = {}
    for rec in view.of_type("model").values():
        node = rec.raw
        original = str(node.get("original_file_path") or "")
        patch = node.get("patch_path")
        if original and patch:
            index[original] = _strip_scheme(str(patch))
    return index


def _find_model_line(schema_file: Path, model_name: str) -> int | None:
    """Best-effort 1-based line of the model's entry in its schema YAML; ``None`` if not found.

    Matches a ``- name: <model>`` or ``name: <model>`` line (quotes and a trailing ``#`` comment
    tolerated). Never guesses — a missing file or unmatched name yields ``None``, not a fabricated line.
    """
    if not schema_file.exists():
        return None
    for lineno, raw in enumerate(schema_file.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        for prefix in ("- name:", "name:"):
            if stripped.startswith(prefix):
                value = stripped[len(prefix) :].split("#", 1)[0].strip().strip("'\"")
                if value == model_name:
                    return lineno
    return None


def _coverage_finding(
    sql_path: Path, model: ModelDoc | None, schema_index: dict[str, str], *, code: str, reason: str
) -> report.Finding:
    """Build one warn-level finding for a gap model, anchored at its schema YAML when resolvable.

    A model missing from the manifest has no ``patch_path``, so it falls back to the ``.sql`` path with
    the stale-manifest reason. Otherwise the finding points at the schema YAML (and its model line, when
    a best-effort scan finds one); absent a ``patch_path`` it falls back to the ``.sql`` path, ``line=None``.
    """
    if model is None:
        message = "not in manifest (run `dbt parse`?)"
        return report.Finding(path=str(sql_path), line=None, severity="warn", code=code, message=message)
    schema_rel = schema_index.get(model.original_file_path)
    if schema_rel:
        line = _find_model_line(Path(schema_rel), model.name)
        return report.Finding(path=schema_rel, line=line, severity="warn", code=code, message=reason)
    return report.Finding(path=str(sql_path), line=None, severity="warn", code=code, message=reason)


def check_docs(
    files: list[Path],
    manifest: Manifest,
    *,
    scope: str,
    color: bool = False,
    manifest_path: Path | None = None,
    json_out: Path | None = None,
    quiet: bool = False,
) -> int:
    """Report selected models with no description. Non-zero if any are undocumented."""
    if not quiet:
        report.render_headline(f"# docscov — documentation coverage — {scope}", color=color, severity="info")
    if not files:
        return report.emit_findings(
            "docscov",
            [],
            0,
            color=color,
            json_out=json_out,
            quiet=quiet,
            headline="docscov: no files in scope — skipped.",
            severity="ok",
        )
    by_path = manifest.by_path()
    gaps = [(f, by_path.get(str(f))) for f in files]
    gaps = [(f, m) for f, m in gaps if m is None or not m.description.strip()]
    if not gaps:
        return report.emit_findings(
            "docscov",
            [],
            0,
            color=color,
            json_out=json_out,
            quiet=quiet,
            headline=f"docscov: OK — all {len(files)} selected model(s) have a description.",
            severity="ok",
        )
    index = _schema_index(manifest_path)
    findings = [_coverage_finding(f, m, index, code="DOCSCOV", reason="no description") for f, m in gaps]
    rc = report.emit_findings(
        "docscov",
        findings,
        1,
        color=color,
        json_out=json_out,
        quiet=quiet,
        headline=f"docscov: {len(gaps)} of {len(files)} model(s) missing a description:",
        severity="warn",
    )
    if not quiet:
        report.render_headline(_DOCSCOV_GUIDANCE, color=color, severity="info")
    return rc


def check_tests(
    files: list[Path],
    manifest: Manifest,
    *,
    scope: str,
    color: bool = False,
    manifest_path: Path | None = None,
    json_out: Path | None = None,
    quiet: bool = False,
) -> int:
    """Report selected models with no tests. Non-zero if any are untested."""
    if not quiet:
        report.render_headline(f"# testcov — test coverage — {scope}", color=color, severity="info")
    if not files:
        return report.emit_findings(
            "testcov",
            [],
            0,
            color=color,
            json_out=json_out,
            quiet=quiet,
            headline="testcov: no files in scope — skipped.",
            severity="ok",
        )
    by_path = manifest.by_path()
    gaps = [(f, by_path.get(str(f))) for f in files]
    gaps = [(f, m) for f, m in gaps if m is None or m.test_count <= 0]
    if not gaps:
        return report.emit_findings(
            "testcov",
            [],
            0,
            color=color,
            json_out=json_out,
            quiet=quiet,
            headline=f"testcov: OK — all {len(files)} selected model(s) have at least one test.",
            severity="ok",
        )
    index = _schema_index(manifest_path)
    findings = [_coverage_finding(f, m, index, code="TESTCOV", reason="no tests") for f, m in gaps]
    rc = report.emit_findings(
        "testcov",
        findings,
        1,
        color=color,
        json_out=json_out,
        quiet=quiet,
        headline=f"testcov: {len(gaps)} of {len(files)} model(s) untested:",
        severity="warn",
    )
    if not quiet:
        report.render_headline(_TESTCOV_GUIDANCE, color=color, severity="info")
    return rc
