"""Local HTTP host for the generated viewer bundle (the ``serve`` half).

Kept separate from the Gantt engine (``gantt.py``) so the pure transform never imports
``http``/``socketserver``. ``no-store`` headers mean a browser reload always re-fetches the
freshly-regenerated bundle (``index.json`` + ``runs/<id>.json``) + assets.
"""

# Standard Library
import http.server
import logging
import socketserver
from pathlib import Path
from typing import Any

# Local
from obs.gantt import OBS_HTML

log = logging.getLogger(__name__)


def serve(output_dir: Path, port: int) -> None:
    """Host ``output_dir`` over HTTP with no-store headers; Ctrl-C to stop."""

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, directory=str(output_dir), **kw)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            super().end_headers()

        def log_message(self, format: str, *fargs: Any) -> None:
            log.debug("http: %s", format % fargs if fargs else format)

    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(("127.0.0.1", port), _Handler)
    except OSError as exc:
        if exc.errno == 48 or "in use" in str(exc).lower():
            raise RuntimeError(
                f"port {port} is already in use — stop the other server or pass a different --port."
            ) from exc
        raise

    with httpd:
        url = f"http://localhost:{port}/{OBS_HTML}"
        log.info("serving %s on %s (Ctrl-C to stop)", output_dir, url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            log.info("shutting down")
