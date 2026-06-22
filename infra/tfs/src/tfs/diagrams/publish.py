"""`tfs diagram-comment` — post (or update) the sticky PR comment for a diagram.

The image files are uploaded by GitHub's own ``actions/upload-artifact`` step; this
command just links that artifact into a sticky PR comment (no ``ci-diagrams``
branch, no git push). Runs only in CI; reads its context from the environment:

  GITHUB_REPOSITORY  owner/repo
  GITHUB_SHA         commit being diagrammed (optional, for display)
  GH_TOKEN           token with pull-requests:write (used by `gh`)
  GITHUB_REF / TFS_PR_NUMBER   to resolve the PR number (refs/pull/<n>/merge)

Pure helpers (marker / body / PR-number) are unit-tested; only the `gh` calls are
IO seams. Hard-fails (no silent skip) if required context is missing.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess

log = logging.getLogger(__name__)


def _require(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        raise RuntimeError(f"diagram-comment requires the {name} environment variable (CI context).")
    return val


def resolve_pr_number(ref: str | None = None, explicit: str | None = None) -> str:
    """PR number from TFS_PR_NUMBER, else parsed from GITHUB_REF (refs/pull/<n>/...)."""
    explicit = explicit if explicit is not None else os.environ.get("TFS_PR_NUMBER")
    if explicit:
        return explicit
    ref = ref if ref is not None else os.environ.get("GITHUB_REF", "")
    m = re.match(r"refs/pull/(\d+)/", ref)
    if not m:
        raise RuntimeError("Cannot resolve PR number from TFS_PR_NUMBER or GITHUB_REF (refs/pull/<n>/...).")
    return m.group(1)


def marker(stack: str) -> str:
    """The hidden HTML marker that makes the comment sticky (one per stack)."""
    return f"<!-- tf-diagram:{stack} -->"


def comment_body(stack: str, env: str, mode: str, png_url: str, svg_url: str, sha: str = "", run_url: str = "") -> str:
    sha_note = f" (`{sha[:12]}`)" if sha else ""
    # png_url/svg_url are the RESOLVED raw blob URLs (Content-Disposition: inline) — see
    # _resolve_inline_url. The PNG embeds inline as an image; the URL is freshly signed
    # per render so it is inherently cache-busting (GitHub camo re-fetches + caches it).
    lines = [
        marker(stack),
        f"### \U0001f4ca `{stack}` — architecture {mode} ({env})",
        "",
        f"![{stack} {env} {mode} diagram]({png_url})",
        "",
        f"Rendered by `tfs diagram {stack} {env} --mode {mode}`. Nodes are coloured by category; "
        "in plan mode, borders mark create (+) / update (~) / replace (±) / delete (-).",
        "",
        f"**Artifacts{sha_note}:** [⬇️ PNG]({png_url}) · [⬇️ SVG (editable in draw.io)]({svg_url}).",
    ]
    # The artifact URL is a short-lived signed link (GitHub caches the image). If it ever
    # shows broken, re-running the workflow re-renders + re-links it. Tell the reader how.
    if run_url:
        lines += [
            "",
            f"> ℹ️ Image broken? Its CI artifact link is short-lived — "
            f"[re-run this workflow]({run_url}) to regenerate and refresh it.",
        ]
    return "\n".join(lines)


def _resolve_inline_url(repo: str, artifact_id: str, token: str) -> str:  # pragma: no cover - gh artifact redirect IO
    """Resolve an `archive: false` artifact id to its servable raw blob URL.

    `…/actions/artifacts/{id}/zip` 302-redirects to a Content-Disposition: inline,
    content-typed blob SAS URL (raw file, not a zip, because the artifact was uploaded
    un-archived). We read that redirect Location WITHOUT downloading the body. The SAS
    is short-lived; GitHub's camo proxy caches the bytes when the comment renders."""
    api = f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip"
    headers = subprocess.run(
        ["curl", "-s", "-D", "-", "-o", "/dev/null", "-H", f"Authorization: Bearer {token}", api],
        check=True, text=True, capture_output=True,
    ).stdout
    for line in headers.splitlines():
        if line.lower().startswith("location:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError(f"no redirect Location for artifact {artifact_id} in {repo} (is it an archive:false upload?)")


def _gh(*args: str) -> str:  # pragma: no cover - subprocess IO seam (gh CLI)
    return subprocess.run(["gh", *args], check=True, text=True, capture_output=True).stdout


def _upsert_comment(repo: str, pr: str, mark: str, body: str) -> None:  # pragma: no cover - gh IO
    existing = _gh(
        "api", f"repos/{repo}/issues/{pr}/comments", "--paginate",
        "--jq", f'.[] | select(.body | contains("{mark}")) | .id',
    ).strip()
    if existing:
        cid = existing.splitlines()[0]
        _gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{cid}", "-f", f"body={body}")
        log.info("updated sticky comment %s on PR #%s", cid, pr)
    else:
        _gh("api", f"repos/{repo}/issues/{pr}/comments", "-f", f"body={body}")
        log.info("created sticky comment on PR #%s", pr)


def post_comment(stack: str, env: str, mode: str, png_artifact_id: str, svg_artifact_id: str) -> None:  # pragma: no cover - gh IO orchestration
    repo = _require("GITHUB_REPOSITORY")
    token = _require("GH_TOKEN")
    pr = resolve_pr_number()
    png_url = _resolve_inline_url(repo, png_artifact_id, token)
    svg_url = _resolve_inline_url(repo, svg_artifact_id, token)
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if run_id else ""
    body = comment_body(stack, env, mode, png_url, svg_url, os.environ.get("GITHUB_SHA", ""), run_url)
    _upsert_comment(repo, pr, marker(stack), body)
    log.info("✅ diagram comment posted to PR #%s", pr)
