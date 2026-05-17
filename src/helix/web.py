"""Minimal mobile / QR-paired gate view (HELIX.md §11, §7.7.3).

§11 specifies a "minimal FastAPI service + static HTML, QR-paired
auth". To keep this an honest **zero-dependency opt-in** (the §11.1
ethos — no new heavy server on the critical path) it is the stdlib
``http.server`` instead; the surface is the same: the queue + one-tap
gate resolution, gated by a paired token.

QR pairing = a random token baked into a URL. Rendering a *scannable*
QR image needs the optional ``qrcode`` package (the ``qr-image``
upgrade); rather than fake an image, the server prints the pairing URL
+ token and says how to get the scannable code. Token auth is advisory
(loopback dev tool), not a security boundary — stated plainly.
"""

from __future__ import annotations

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def _token(app) -> str:
    p = app.store.layout.helix_dir / "web-token"
    if p.exists():
        return p.read_text().strip()
    t = secrets.token_urlsafe(16)
    p.write_text(t)
    return t


def make_handler(app, token: str):
    from helix.cli import _build_queue

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):           # quiet
            pass

        def _send(self, code, payload):
            body = json.dumps(payload, indent=2).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _auth(self, q) -> bool:
            return secrets.compare_digest(
                (q.get("t", [""])[0]), token)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._auth(q):
                return self._send(403, {"error": "bad or missing token "
                                        "(?t=...) — see `helix serve`"})
            if u.path in ("/", "/queue"):
                items = _build_queue(app).collect()
                return self._send(200, {
                    b: [{"title": i.title, "detail": i.detail,
                         "command": i.command} for i in items[b]]
                    for b in items})
            if u.path.startswith("/gate/"):
                proj = u.path[len("/gate/"):]
                # Boundary guard: only operate on a real project. This
                # rejects path-traversal names before they reach any
                # per-project path (security review Vuln 1).
                if not app.projects.exists(proj):
                    return self._send(404, {"error": "no such project"})
                try:
                    return self._send(200, app.workflow().pending(proj))
                except Exception as e:  # noqa: BLE001
                    return self._send(404, {"error": str(e)})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._auth(q):
                return self._send(403, {"error": "bad or missing token"})
            n = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(n).decode())
            if u.path == "/resolve":
                proj = form.get("project", [""])[0]
                opt = form.get("option", [""])[0]
                why = form.get("why", [""])[0]
                # Boundary guard: never pass an unvalidated project name
                # into the workflow / filesystem (security review
                # Vuln 1 — path traversal → arbitrary file write).
                if not app.projects.exists(proj):
                    return self._send(404, {"error": "no such project"})
                try:
                    res = app.workflow().resume(proj, opt, why)
                    return self._send(200, res)
                except Exception as e:  # noqa: BLE001
                    return self._send(400, {"error": str(e)})
            return self._send(404, {"error": "not found"})

    return H


def serve(app, *, host: str = "127.0.0.1", port: int = 8765,
          once: bool = False):
    """Build the paired web view and return ``(httpd, url, token)``.

    The caller drives the returned ``ThreadingHTTPServer``
    (``serve_forever()`` to block, or ``handle_request()`` / a daemon
    thread in tests). ``once`` is accepted for call-site readability
    but does not change what is returned or how the server behaves.
    """
    token = _token(app)
    httpd = ThreadingHTTPServer((host, port), make_handler(app, token))
    real_port = httpd.server_address[1]
    url = f"http://{host}:{real_port}/?t={token}"
    if once:
        return httpd, url, token
    return httpd, url, token
