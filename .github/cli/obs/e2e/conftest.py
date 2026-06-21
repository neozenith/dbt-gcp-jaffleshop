"""e2e fixtures: build a real obs bundle from seeded data and serve it over HTTP.

No warehouse and no mocks — `build_bundle`/`write_bundle` are the real functions, and a
stdlib threading HTTP server hosts the generated static SPA so Playwright drives it exactly
as a browser would over GitHub Pages. The seeded bundle has three runs (two passing, one
failing) across distinct thread counts so the overview scatter has clickable points.
"""

# Standard Library
import functools
import http.server
import socketserver
import threading
from types import SimpleNamespace

# Third Party
import pytest

# Local
from obs import gantt

_RUN_TEMPLATE = [
    ("Thread-1 (worker)", "model.jaffle_shop.stg_customers", "stg_customers", "model", "success", 0.0, 2.0),
    ("Thread-2 (worker)", "model.jaffle_shop.stg_orders", "stg_orders", "model", "success", 0.0, 4.0),
    ("Thread-1 (worker)", "test.jaffle_shop.nn_customers_id", "nn_customers_id", "test", "FAIL", 2.0, 1.5),
    ("Thread-2 (worker)", "model.jaffle_shop.customers", "customers", "model", "success", 4.0, 7.6),
]


def _run_rows(invocation_id: str, base_minute: int, *, fail: bool) -> list[dict]:
    """One invocation's run-result rows, offset to a distinct minute so wall windows differ."""
    rows = []
    for thread, node_id, name, rtype, status, off, dur in _RUN_TEMPLATE:
        # The planted failing test only fails in the "fail" run.
        st = status if (status != "FAIL" or fail) else "success"
        start = f"2026-06-17T05:{base_minute:02d}:{int(off):02d}.000000Z"
        end = f"2026-06-17T05:{base_minute:02d}:{int(off + dur):02d}.000000Z"
        rows.append(
            {
                "invocation_id": invocation_id,
                "thread_id": thread,
                "node_id": node_id,
                "name": name,
                "resource_type": rtype,
                "status": st,
                "execute_started_at": start,
                "execute_completed_at": end,
                "duration_secs": dur,
            }
        )
    return rows


def _build_fixture_bundle() -> dict:
    invocations = [
        {"invocation_id": "inv-a", "command": "build", "threads": 4, "run_started_at": "2026-06-17T05:10:00Z",
         "git_sha": "aaa1111", "target_name": "prod", "dbt_version": "1.11", "full_refresh": False},
        {"invocation_id": "inv-b", "command": "build", "threads": 16, "run_started_at": "2026-06-18T05:20:00Z",
         "git_sha": "bbb2222", "target_name": "prod", "dbt_version": "1.11", "full_refresh": False},
        {"invocation_id": "inv-c", "command": "build", "threads": 32, "run_started_at": "2026-06-19T05:30:00Z",
         "git_sha": "ccc3333", "target_name": "prod", "dbt_version": "1.11", "full_refresh": False},
    ]
    rows = (
        _run_rows("inv-a", 10, fail=False)
        + _run_rows("inv-b", 20, fail=True)
        + _run_rows("inv-c", 30, fail=False)
    )
    return gantt.build_bundle(invocations, rows, source_label="test.DS.dbt_run_results", days=30)


@pytest.fixture(scope="session")
def site(tmp_path_factory):
    """Generate the bundle, host it, and yield (base_url, newest_run_id)."""
    out = tmp_path_factory.mktemp("obs_site")
    bundle = _build_fixture_bundle()
    gantt.write_bundle(out, bundle)
    newest_run_id = bundle["index"][0]["invocation_id"]  # index is sorted newest-first

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(url=f"http://127.0.0.1:{port}/obs.html", run_id=newest_run_id, dir=out)
    finally:
        httpd.shutdown()
        httpd.server_close()
