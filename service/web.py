"""The local frontend's web server. Standard library only.

It listens on 127.0.0.1 only, on a random free port unless PWI_FRONTEND_PORT
sets one. At each start the service makes a new login code and session secret,
and writes the port and a login link to $XDG_RUNTIME_DIR/pwi/frontend.json,
owner-only; `pwi open` reads it and opens the browser. Visiting the link sets
an HttpOnly, SameSite=Strict session cookie. Every request is checked for the
Host header (against DNS rebinding) and the cookie; every request that changes
something must also come from the frontend's own origin.
"""

import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import threading
from contextlib import closing
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import admin
import paths
import sources
import store

STATIC_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"
INFO_PATH = paths.RUNTIME_DIR / "frontend.json"
COOKIE = "pwi_session"
MAX_BODY = 1 << 20
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}
PAGE = ("<!doctype html><html lang=en><meta charset=utf-8><title>Work layer</title>"
        "<body><h1>{title}</h1><p>{text}</p></body></html>")
log = logging.getLogger("pwi")


def routes():
    """(method, path pattern, function(app, db, match, query, body)) for the JSON API."""
    one = lambda q, k: q.get(k, [None])[0] or None  # noqa: E731
    return [
        ("GET", r"/api/status", lambda app, db, m, q, b: admin.status(db, app.version)),
        ("POST", r"/api/collect", lambda app, db, m, q, b: admin.collect_now(app.store_path)),
        ("POST", r"/api/cleanup", lambda app, db, m, q, b: admin.cleanup_now(app.store_path)),
        ("GET", r"/api/audit", lambda app, db, m, q, b: admin.audit_entries(db, one(q, "limit") or 200)),
        ("GET", r"/api/sources", lambda app, db, m, q, b: sources.list_sources(db)),
        ("POST", r"/api/sources", lambda app, db, m, q, b: admin.add_sources(db, b.get("path"))),
        ("PUT", r"/api/sources/(\d+)", lambda app, db, m, q, b: admin.set_source_enabled(db, int(m[1]), b.get("enabled"))),
        ("GET", r"/api/projects", lambda app, db, m, q, b: admin.projects(db)),
        ("PUT", r"/api/projects/([^/]+)", lambda app, db, m, q, b: admin.update_project(db, unquote(m[1]), b)),
        ("GET", r"/api/events", lambda app, db, m, q, b: admin.events(
            db, one(q, "project"), one(q, "day"), one(q, "q"), one(q, "source"), one(q, "limit") or 200)),
        ("GET", r"/api/claims", lambda app, db, m, q, b: admin.claims(
            db, one(q, "status"), one(q, "project"), one(q, "q"), one(q, "limit") or 200)),
        ("GET", r"/api/claims/([^/]+)", lambda app, db, m, q, b: admin.claim_history(db, unquote(m[1]))),
        ("POST", r"/api/impact", lambda app, db, m, q, b: admin.impact(db, b.get("items"))),
        ("POST", r"/api/delete", lambda app, db, m, q, b: admin.delete(db, b.get("items"), b.get("decisions") or {})),
        ("GET", r"/api/labels", lambda app, db, m, q, b: admin.labels(db)),
        ("POST", r"/api/labels", lambda app, db, m, q, b: admin.add_label(db, b.get("type"), b.get("id"))),
        ("DELETE", r"/api/labels/([^/]+)/(.+)", lambda app, db, m, q, b: admin.remove_label(db, unquote(m[1]), unquote(m[2]))),
        ("GET", r"/api/retention", lambda app, db, m, q, b: admin.retention_settings(db)),
        ("PUT", r"/api/retention/([a-z_]+)", lambda app, db, m, q, b: admin.set_retention(db, m[1], b.get("days"))),
    ]


class Handler(BaseHTTPRequestHandler):
    app = None  # set by Frontend
    protocol_version = "HTTP/1.1"
    server_version = "pwi"
    sys_version = ""

    def log_message(self, fmt, *args):
        log.debug("frontend: " + fmt, *args)

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_PUT(self):
        self.handle_request("PUT")

    def do_DELETE(self):
        self.handle_request("DELETE")

    def send(self, status, body, content_type="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        for name, value in {**SECURITY_HEADERS, **(headers or {})}.items():
            self.send_header(name, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_json(self, status, value):
        self.send(status, json.dumps(value, ensure_ascii=False))

    def send_page(self, status, title, text):
        self.send(status, PAGE.format(title=title, text=text), "text/html; charset=utf-8")

    def handle_request(self, method):
        try:
            app = self.app
            if self.headers.get("Host") not in app.hosts:
                return self.send_page(403, "Wrong address", "Open the frontend with: pwi open")
            url = urlsplit(self.path)
            if url.path == "/login" and method == "GET":
                return self.login(url)
            if not self.signed_in():
                if url.path.startswith("/api/"):
                    return self.send_json(401, {"error": "Not signed in. Open the frontend again with: pwi open"})
                return self.send_page(401, "Sign in from the terminal", "Open the frontend with: pwi open")
            if method != "GET" and self.headers.get("Origin") not in app.origins:
                return self.send_json(403, {"error": "Changes are only accepted from the frontend itself."})
            if url.path.startswith("/api/"):
                return self.api(method, url)
            if method != "GET":
                return self.send_json(405, {"error": "Not allowed."})
            return self.static(url.path)
        except Exception:
            log.exception("frontend request %s %s failed", method, self.path)
            self.send_json(500, {"error": "The service hit an error. See: journalctl --user -u pwi"})

    def login(self, url):
        query = parse_qs(url.query)
        code = query.get("code", [""])[0]
        if not hmac.compare_digest(code.encode(), self.app.login_code.encode()):
            return self.send_page(403, "This link has expired",
                                  "The service has restarted since it was made. Open the frontend again with: pwi open")
        section = query.get("to", [""])[0]  # a section to open, e.g. pwi open claims; never another site
        location = f"/#{section}" if re.fullmatch(r"[a-z]{1,20}", section) else "/"
        self.send(303, b"", "text/plain", {"Location": location,
                                           "Set-Cookie": f"{COOKIE}={self.app.session}; HttpOnly; SameSite=Strict; Path=/"})

    def signed_in(self):
        try:
            morsel = SimpleCookie(self.headers.get("Cookie", "")).get(COOKIE)
        except CookieError:
            return False
        return morsel is not None and hmac.compare_digest(morsel.value.encode(), self.app.session.encode())

    def api(self, method, url):
        body = {}
        if method in ("POST", "PUT", "DELETE"):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self.send_json(413, {"error": "That request is too large."})
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return self.send_json(400, {"error": "The request isn't valid JSON."})
            if not isinstance(body, dict):
                return self.send_json(400, {"error": "The request must be a JSON object."})
        query = parse_qs(url.query)
        for verb, pattern, handler in self.app.routes:
            match = re.fullmatch(pattern, url.path)
            if match and verb == method:
                try:
                    with closing(store.connect(self.app.store_path)) as db:
                        return self.send_json(200, handler(self.app, db, match, query, body))
                except admin.Invalid as e:
                    return self.send_json(400, {"error": str(e)})
        return self.send_json(404, {"error": "No such page."})

    def static(self, path):
        root = self.app.static_dir.resolve()
        if not (root / "index.html").exists():
            return self.send_page(503, "The frontend isn't built", "Run npm run build in frontend/, then install again.")
        target = (root / path.lstrip("/")).resolve() if path not in ("", "/") else root / "index.html"
        if root not in target.parents and target != root / "index.html":
            return self.send_json(404, {"error": "No such page."})
        if not target.is_file():
            target = root / "index.html"
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if kind in ("text/html", "text/css", "text/javascript", "application/javascript", "image/svg+xml"):
            kind += "; charset=utf-8"
        self.send(200, target.read_bytes(), kind)


class Frontend:
    def __init__(self, store_path, version, port=0, static_dir=STATIC_DIR):
        self.store_path, self.version, self.static_dir = store_path, version, static_dir
        self.login_code = secrets.token_urlsafe(24)
        self.session = secrets.token_urlsafe(32)
        self.routes = routes()
        handler = type("FrontendHandler", (Handler,), {"app": self})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.origins = {f"http://{h}" for h in self.hosts}
        self.thread = None

    @property
    def login_url(self):
        return f"http://127.0.0.1:{self.port}/login?code={self.login_code}"

    def start(self):
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="frontend", daemon=True)
        self.thread.start()
        INFO_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(INFO_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"port": self.port, "login_url": self.login_url, "pid": os.getpid()}, f)
        log.info("frontend on http://127.0.0.1:%d (open it with: pwi open)", self.port)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        INFO_PATH.unlink(missing_ok=True)
