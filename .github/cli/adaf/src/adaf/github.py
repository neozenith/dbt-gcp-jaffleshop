"""Minimal GitHub REST client (stdlib ``urllib``) for the sticky PR comment ``adaf report`` posts.

No third-party HTTP dependency (ADR-0002): ``urllib`` covers the three calls we need — list issue
comments, create a comment, update a comment. Auth is a bearer token (``GITHUB_TOKEN`` on a runner).

The **sticky** behaviour: a hidden HTML-comment marker is embedded in the body, so on every push the
prior comment carrying that marker is found and PATCHed — one evolving comment across N commits,
not N comments.
"""

# Standard Library
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

_ACCEPT = "application/vnd.github+json"
_API_VERSION = "2022-11-28"


def wrap_section(name: str, inner: str) -> str:
    """Wrap ``inner`` markdown in the section's HTML-comment delimiters (so it can be spliced later)."""
    return f"<!-- adaf:{name} -->\n{inner}\n<!-- /adaf:{name} -->"


def _splice_section(body: str, name: str, content: str) -> str:
    """Replace the inner content between ``<!-- adaf:name -->`` and ``<!-- /adaf:name -->`` in ``body``.

    Returns ``body`` unchanged if the section markers are absent (caller falls back to the skeleton)."""
    pattern = re.compile(
        rf"(<!-- adaf:{re.escape(name)} -->\n).*?(\n<!-- /adaf:{re.escape(name)} -->)",
        re.DOTALL,
    )
    return pattern.sub(lambda m: m.group(1) + content + m.group(2), body)


def _api() -> str:
    """The REST base URL — ``GITHUB_API_URL`` (set by every Actions runner; also the test seam) else
    the public API host."""
    return os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")


class GitHubError(RuntimeError):
    """A non-2xx GitHub API response — carries status + body so the failure is loud and debuggable."""


def marker_html(marker: str) -> str:
    """The hidden HTML comment that identifies adaf's sticky comment (invisible in rendered markdown)."""
    return f"<!-- {marker} -->"


def _request(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", _ACCEPT)
    req.add_header("X-GitHub-Api-Version", _API_VERSION)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310 — fixed https api host
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GitHubError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc


def list_issue_comments(repo: str, issue: int, token: str) -> list[dict[str, Any]]:
    """Every comment on an issue/PR (paginated, 100/page)."""
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"{_api()}/repos/{repo}/issues/{issue}/comments?per_page=100&page={page}"
        batch = _request("GET", url, token)
        if not isinstance(batch, list) or not batch:
            break
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return comments


def upsert_section(repo: str, issue: int, *, marker: str, section: str, content: str, skeleton: str, token: str) -> str:
    """Splice ``content`` into the named section of the marker-stamped sticky comment, leaving the OTHER
    section intact. Creates the comment from ``skeleton`` (both sections present) if none exists yet.

    Returns ``"created"`` or ``"updated"``. Two jobs (findings + build) call this concurrently for
    different sections; whichever runs first creates the comment, the second splices its own section in.
    """
    needle = marker_html(marker)
    for comment in list_issue_comments(repo, issue, token):
        body = comment.get("body") or ""
        if needle in body:
            spliced = _splice_section(body, section, content)
            # An existing comment from an older (section-less) layout: rebuild from the skeleton so the
            # section markers exist, then splice — never silently no-op.
            new_body = spliced if f"<!-- adaf:{section} -->" in body else _splice_section(skeleton, section, content)
            _request("PATCH", f"{_api()}/repos/{repo}/issues/comments/{comment['id']}", token, {"body": new_body})
            return "updated"
    _request(
        "POST",
        f"{_api()}/repos/{repo}/issues/{issue}/comments",
        token,
        {"body": _splice_section(skeleton, section, content)},
    )
    return "created"


def upsert_sticky_comment(repo: str, issue: int, body: str, *, token: str, marker: str) -> str:
    """Create the marked comment, or update the prior one carrying ``marker``. Returns ``"created"``
    or ``"updated"``. The marker is prepended to the body if the caller didn't include it."""
    needle = marker_html(marker)
    full_body = body if needle in body else f"{needle}\n{body}"
    for comment in list_issue_comments(repo, issue, token):
        if needle in (comment.get("body") or ""):
            _request(
                "PATCH",
                f"{_api()}/repos/{repo}/issues/comments/{comment['id']}",
                token,
                {"body": full_body},
            )
            return "updated"
    _request("POST", f"{_api()}/repos/{repo}/issues/{issue}/comments", token, {"body": full_body})
    return "created"
