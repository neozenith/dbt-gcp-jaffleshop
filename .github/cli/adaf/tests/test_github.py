"""Unit tests for the sticky-comment GitHub client (`adaf.github`) — against a REAL local HTTP server.

No mocks (project rule): a stdlib ``http.server`` stands in for the GitHub REST API, pointed at via
``GITHUB_API_URL`` (the same env var real Actions runners set). The server keeps in-memory comment
state so create-then-update is exercised end to end.
"""

# Standard Library
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Third Party
import pytest

# First Party
from adaf import github


class _FakeGitHub(BaseHTTPRequestHandler):
    comments: list[dict[str, object]] = []
    next_id: int = 100

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - matches base API name
        pass  # silence the default stderr access log

    def _send(self, code: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        self._send(200, type(self).comments)

    def do_POST(self) -> None:  # noqa: N802
        cls = type(self)
        comment = {"id": cls.next_id, "body": self._read_json().get("body", "")}
        cls.next_id += 1
        cls.comments.append(comment)
        self._send(201, comment)

    def do_PATCH(self) -> None:  # noqa: N802
        cid = int(self.path.rstrip("/").split("/")[-1])
        body = self._read_json().get("body", "")
        for c in type(self).comments:
            if c["id"] == cid:
                c["body"] = body
        self._send(200, {"id": cid, "body": body})


@pytest.fixture()
def github_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _FakeGitHub.comments = []
    _FakeGitHub.next_id = 100
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeGitHub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    monkeypatch.setenv("GITHUB_API_URL", f"http://{host}:{port}")
    try:
        yield
    finally:
        server.shutdown()
        thread.join()


def test_upsert_creates_then_updates_same_comment(github_server: None) -> None:
    first = github.upsert_sticky_comment("o/r", 7, "first body", token="t", marker="adaf-report")
    assert first == "created"
    assert len(_FakeGitHub.comments) == 1
    assert "<!-- adaf-report -->" in str(_FakeGitHub.comments[0]["body"])

    second = github.upsert_sticky_comment("o/r", 7, "second body", token="t", marker="adaf-report")
    assert second == "updated"
    assert len(_FakeGitHub.comments) == 1  # SAME comment, not a new one
    assert "second body" in str(_FakeGitHub.comments[0]["body"])


def test_upsert_ignores_unmarked_comments(github_server: None) -> None:
    _FakeGitHub.comments.append({"id": 1, "body": "a human comment, no marker"})
    action = github.upsert_sticky_comment("o/r", 7, "body", token="t", marker="adaf-report")
    assert action == "created"  # didn't hijack the human comment
    assert len(_FakeGitHub.comments) == 2


def _skeleton() -> str:
    return (
        github.marker_html("adaf-report")
        + "\n## ADAF\n"
        + github.wrap_section("findings", "_pending_")
        + "\n"
        + github.wrap_section("build", "_pending_")
        + "\n"
    )


def test_upsert_section_updates_two_sections_on_one_comment(github_server: None) -> None:
    sk = _skeleton()
    # findings job runs first → creates the comment, fills ONLY the findings section
    a = github.upsert_section("o/r", 7, marker="adaf-report", section="findings", content="FINDINGS-V1", skeleton=sk, token="t")
    assert a == "created"
    assert len(_FakeGitHub.comments) == 1
    body = str(_FakeGitHub.comments[0]["body"])
    assert "FINDINGS-V1" in body and "_pending_" in body  # build still pending

    # build job runs second → updates the SAME comment, fills build, leaves findings intact
    b = github.upsert_section("o/r", 7, marker="adaf-report", section="build", content="BUILD-V1", skeleton=sk, token="t")
    assert b == "updated"
    assert len(_FakeGitHub.comments) == 1
    body = str(_FakeGitHub.comments[0]["body"])
    assert "FINDINGS-V1" in body and "BUILD-V1" in body  # both sections now present

    # findings job re-runs (next push) → only its section changes
    github.upsert_section("o/r", 7, marker="adaf-report", section="findings", content="FINDINGS-V2", skeleton=sk, token="t")
    body = str(_FakeGitHub.comments[0]["body"])
    assert "FINDINGS-V2" in body and "BUILD-V1" in body and "FINDINGS-V1" not in body
