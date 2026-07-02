"""`adaf report` — summarise the checks + the dbt build into ONE sticky PR comment with TWO sections.

The comment is split into two marker-delimited sections that update **independently** (ADR-0029):

* ``findings`` — the per-check quality-gate findings (the ``--json-out`` artifacts). Posted by a job
  that needs only the checks, so it lands fast — NOT blocked on the (slower) dbt build.
* ``build`` — the dbt run-results summary + the EDR report link. Posted by the build job once it has
  ``run_results.json``.

Each invocation renders + upserts ONE section (``--section findings|build``), splicing it into the
existing comment without clobbering the other section (see :func:`adaf.github.upsert_section`); the
first job to run creates the comment from a skeleton carrying both sections. ``--section all``
(default) renders the whole comment in one shot (used by ``--dry-run`` / local preview). Manifest
node lookups reuse :class:`adaf.dbt.manifest_view.ManifestView`; run-results come from the
:mod:`adaf.dbt.runresults` seam (JSON or Fusion parquet).
"""

# Standard Library
import argparse
import json
import logging
import os
from collections import Counter
from pathlib import Path
from typing import Any

# First Party
from adaf import github
from adaf.dbt import runresults
from adaf.dbt.manifest_view import ManifestView, NodeRecord

log = logging.getLogger(__name__)

DEFAULT_MARKER = "adaf-report"
SECTIONS = ("findings", "build")


def _load_findings(findings_dir: Path) -> list[dict[str, Any]]:
    """Read every ``*.json`` findings artifact under ``findings_dir`` (sorted by filename)."""
    results: list[dict[str, Any]] = []
    for path in sorted(findings_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "check" in data:
            results.append(data)
    return results


def _load_records(manifest_path: Path) -> dict[str, NodeRecord]:
    """Node records keyed by ``unique_id`` from the manifest seam, or ``{}`` if the manifest is absent."""
    if not manifest_path.exists():
        return {}
    return ManifestView.load(manifest_path).records()


def _node_label(records: dict[str, NodeRecord], uid: str) -> tuple[str, str]:
    """``(name, file_path)`` for ``uid`` from the manifest records (falling back to the uid / ``-``)."""
    rec = records.get(uid)
    if rec is None:
        return uid, "-"
    raw = rec.raw
    name = raw.get("name") or uid
    file_path = raw.get("original_file_path") or raw.get("path") or "-"
    return str(name), str(file_path)


def _md_cell(text: object) -> str:
    """Escape a value for a markdown table cell (pipes + newlines), truncating runaway messages."""
    cell = str(text).replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
    return cell[:217] + "..." if len(cell) > 220 else cell


def _render_gates(check_results: list[dict[str, Any]]) -> str:
    if not check_results:
        return "_No check artifacts found._"
    lines = ["| Check | Result | Findings |", "|---|---|---:|"]
    for result in check_results:
        findings = result.get("findings") or []
        n = len(findings) if isinstance(findings, list) else 0
        passed = int(result.get("exit_code", 0) or 0) == 0
        lines.append(f"| {result.get('check', '?')} | {'✅ pass' if passed else '❌ fail'} | {'—' if n == 0 else n} |")
    return "\n".join(lines)


def _render_findings_details(check_results: list[dict[str, Any]]) -> str:
    """One collapsible ``<details>`` PER CHECK that has findings (empty string if nothing has findings)."""
    blocks: list[str] = []
    for result in check_results:
        findings = result.get("findings")
        if not isinstance(findings, list) or not findings:
            continue
        rows = ["| Severity | Location | Code | Message |", "|---|---|---|---|"]
        for f in findings:
            if not isinstance(f, dict):
                continue
            loc = str(f.get("path", ""))
            if f.get("line") is not None:
                loc += f":{f['line']}"
            cells = (f.get("severity", ""), loc, f.get("code") or "", f.get("message", ""))
            rows.append("| " + " | ".join(_md_cell(c) for c in cells) + " |")
        check = result.get("check", "?")
        blocks.append(
            f"<details><summary><code>{check}</code> — {len(findings)} finding(s)</summary>\n\n"
            + "\n".join(rows)
            + "\n\n</details>"
        )
    return "\n\n".join(blocks)


def render_findings_section(check_results: list[dict[str, Any]]) -> str:
    """The inner markdown of the ``findings`` section (quality-gate table + collapsible detail)."""
    parts = ["### Quality gates", _render_gates(check_results)]
    details = _render_findings_details(check_results)
    if details:
        parts.append(details)
    return "\n\n".join(parts)


def render_build_section(
    run_results: runresults.RunResults | None,
    records: dict[str, NodeRecord],
    *,
    edr_url: str | None,
    sdag_url: str | None = None,
    docs_url: str | None = None,
) -> str:
    """The inner markdown of the ``build`` section (dbt run-results summary + EDR / sdag / dbt-docs links)."""
    parts = ["### dbt build"]
    if run_results is None:
        parts.append("_No `run_results.json` — dbt build did not produce results._")
    else:
        counts: Counter[str] = Counter(runresults.status_str(r.status) for r in run_results.results)
        count_rows = ["| Status | Count |", "|---|---:|", *(f"| {s} | {counts[s]} |" for s in sorted(counts))]
        bad = runresults.ERROR_STATUSES | runresults.WARNING_STATUSES
        problems = [r for r in run_results.results if runresults.status_str(r.status) in bad]
        if problems:
            prob_rows = ["| Status | Node | File | Details |", "|---|---|---|---|"]
            for r in problems:
                name, file_path = _node_label(records, r.unique_id)
                cells = (runresults.status_str(r.status), name, file_path, runresults.result_message(r))
                prob_rows.append("| " + " | ".join(_md_cell(c) for c in cells) + " |")
            problem_table = "\n".join(prob_rows)
        else:
            problem_table = "No warnings or failures detected."
        header = (
            f"**{len(run_results.results)} result(s)** · generated {run_results.generated_at or 'unknown'} "
            f"· {run_results.elapsed_time:.1f}s"
        )
        parts.append(f"{header}\n\n" + "\n".join(count_rows) + f"\n\n{problem_table}")
    links = []
    if edr_url:
        links.append(f"📊 [Download `edr-report` artifact]({edr_url})")
    if sdag_url:
        links.append(f"🕸️ [Download `sdag-viewer` artifact]({sdag_url})")
    if docs_url:
        links.append(f"📚 [Download `dbt-docs` artifact]({docs_url})")
    if links:
        parts.append(" · ".join(links))
    return "\n\n".join(parts)


def render_skeleton(title: str, marker: str) -> str:
    """The full comment with BOTH sections as 'pending' placeholders — used to CREATE the comment
    when neither job has posted yet. Each job then splices its own section in."""
    return _assemble(title, marker, {"findings": "_Quality gates pending…_", "build": "_dbt build pending…_"})


def _assemble(title: str, marker: str, sections: dict[str, str]) -> str:
    body = [github.marker_html(marker), f"## 🛡️ ADAF checks — {title}"]
    for name in SECTIONS:
        body.append(github.wrap_section(name, sections[name]))
    body.append("<sub>Each section updates independently as its job finishes.</sub>")
    return "\n\n".join(body) + "\n"


def _resolve_pr(args: argparse.Namespace) -> int | None:
    if args.pr is not None:
        return int(args.pr)
    for env in ("DBT_PR_NUMBER", "PR_NUMBER"):
        val = os.getenv(env, "").strip()
        if val.isdigit():
            return int(val)
    parts = os.getenv("GITHUB_REF", "").split("/")  # refs/pull/<n>/merge
    if len(parts) >= 3 and parts[1] == "pull" and parts[2].isdigit():
        return int(parts[2])
    return None


def _render_section(section: str, args: argparse.Namespace) -> str:
    """Render the inner markdown for one section from its inputs."""
    if section == "findings":
        return render_findings_section(_load_findings(args.findings_dir))
    run_results = runresults.load_run_results(args.run_results)
    records = _load_records(args.manifest)
    edr_url = (args.edr_url or os.getenv("EDR_REPORT_URL", "")).strip() or None
    sdag_url = (args.sdag_url or os.getenv("SDAG_VIEWER_URL", "")).strip() or None
    docs_url = (args.docs_url or os.getenv("DBT_DOCS_URL", "")).strip() or None
    return render_build_section(run_results, records, edr_url=edr_url, sdag_url=sdag_url, docs_url=docs_url)


def cmd_report(args: argparse.Namespace) -> int:
    """Render the requested section(s) and upsert them into the sticky PR comment (or print on --dry-run)."""
    title = args.selector or os.getenv("DBT_SELECTOR", "") or "this PR"
    wanted = list(SECTIONS) if args.section == "all" else [args.section]

    if args.dry_run:  # local preview: render the whole comment with the wanted sections filled
        filled = {name: (_render_section(name, args) if name in wanted else f"_{name} pending…_") for name in SECTIONS}
        print(_assemble(title, args.marker, filled))
        return 0

    repo = args.repo or os.getenv("GITHUB_REPOSITORY", "")
    token = args.token or os.getenv("GITHUB_TOKEN", "")
    pr = _resolve_pr(args)
    missing = [
        n for n, v in (("--repo/GITHUB_REPOSITORY", repo), ("--token/GITHUB_TOKEN", token), ("--pr", pr)) if not v
    ]
    if missing:
        raise SystemExit(f"adaf report: missing required context: {', '.join(missing)} (use --dry-run to preview)")
    assert pr is not None  # narrowed by the `missing` guard above

    skeleton = render_skeleton(title, args.marker)
    for section in wanted:
        content = _render_section(section, args)
        action = github.upsert_section(
            repo, pr, marker=args.marker, section=section, content=content, skeleton=skeleton, token=token
        )
        log.info("adaf report: %s '%s' section on %s#%d", action, section, repo, pr)
    return 0
