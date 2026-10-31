"""The studio's local server: the page's files, the action route, the event stream.

Three routes and nothing else. ``POST /api/action`` runs one action from the
table. ``GET /api/events`` holds one server-sent event stream open.
Everything else is a file from the built Angular app.

Loopback only, checked twice: the socket binds ``127.0.0.1``, and a request
whose ``Origin`` names another site is refused before the action table runs.
That second check is what keeps a page on the open internet from driving a
server that holds the user's provider keys, because a browser sends the origin
on every cross-site POST and this server needs no cookie to be useful to it.

A third check covers what a browser never sends an origin for: another program
on this machine. ``start`` mints a token, the terminal prints it in the page's
URL, and every request must carry it back, in ``X-Studio-Token`` or, where a
browser navigates or opens a stream on its own, in ``?token=``. A server that
was never started has no token, and then every request is refused.
"""
from __future__ import annotations

import json
import mimetypes
import re
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

from salad_studio.web import events
from salad_studio.web.actions import Registry

HOST = "127.0.0.1"
MAX_BODY = 8 * 1024 * 1024
BODY_TIMEOUT_S = 15.0
EVENT_WAIT_S = 15.0
TOKEN_HEADER = "X-Studio-Token"
_EVENTS = "/api/events"
# A build names each script and stylesheet by its content hash; anything else
# is the document or a public file, which keeps `no-cache`.
HASHED = "private, max-age=31536000, immutable"

MISSING_BUILD = """<!doctype html><meta charset="utf-8">
<title>Salad Studio</title>
<body style="font:14px/1.6 system-ui;padding:2rem;max-width:44rem">
<h1>Build the page first</h1>
<p>The server is running, but <code>ui/dist</code> has no build in it.</p>
<pre>cd ui
npm install
npx ng build</pre>
<p>Then reload this page.</p>
"""


class StudioServer(ThreadingHTTPServer):
    """The HTTP server plus the action table and the event hub every request shares."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, registry: Registry | None, *, dist: Path | None,
                 log: Callable[[str, str], None] | None = None,
                 engine: Any = None, hub: events.Hub | None = None) -> None:
        self.registry = registry
        self.engine = engine
        self.dist = Path(dist) if dist is not None else None
        self.hub = hub if hub is not None else events.Hub()
        self.log = log or (lambda _level, _text: None)
        self.run_token: str | None = None
        super().__init__((HOST, 0), StudioHandler)
        self.requested_port = 0

    @property
    def host(self) -> str:
        return HOST

    def start(self, port: int = 0) -> int:
        """Bind ``port`` (0 for any free one) and return the port actually used.

        ``super().__init__`` already bound a free port; a caller that names one
        gets the socket closed and bound again, which is the only way this
        stdlib server takes a fixed port.
        """
        if port:
            self.server_close()
            ThreadingHTTPServer.__init__(self, (HOST, port), StudioHandler)
        self.requested_port = int(port)
        self.run_token = secrets.token_urlsafe(32)
        return int(self.server_address[1])

    def handle_error(self, request: Any, client_address: Any) -> None:
        """A closed tab is not a server error; keep the terminal for real ones."""
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class StudioHandler(BaseHTTPRequestHandler):
    server: StudioServer
    protocol_version = "HTTP/1.1"
    # The body read has its own timeout; a peer that stops reading a response
    # needs the same bound, and neither that read's reset nor this one should
    # leak back to a request the client already answered.
    timeout = BODY_TIMEOUT_S

    def log_message(self, _fmt: str, *_args: Any) -> None:
        pass

    # -- routing

    def do_GET(self) -> None:
        path, query = _split(self.path)
        if path.startswith("/api/") and not self._same_origin():
            return self._json(403, {"error": {"kind": "cross_origin",
                                              "message": "this server answers its own page only"}})
        # The stream cannot carry a header, so it alone takes the token in the URL.
        # A plate's picture goes through the page's HttpClient like every other
        # read, and that interceptor sets the header.
        if path.startswith("/api/") and not self._carries(query, path == _EVENTS):
            return self._unauthorized()
        if path == "/api/events":
            return self._events()
        if path == "/api/action":
            return self._json(405, {"error": {"kind": "method", "message": "POST an action"}})
        if path.startswith("/api/page/"):
            if self.server.engine is None:
                return self._json(404, {"error": {"kind": "not_found", "message": path}})
            return self._json(200, self.server.engine.page(path[len("/api/page/"):]))
        if path.startswith("/api/plates/"):
            return self._plate(path[len("/api/plates/"):])
        if path.startswith("/api/thumbs/"):
            return self._thumb(path[len("/api/thumbs/"):])
        if path.startswith("/api/"):
            return self._json(404, {"error": {"kind": "not_found", "message": path}})
        # A route it cannot serve is a 404, the same answer `/api` gives for a
        # name it does not know, rather than a 500 and a traceback on stderr.
        if path in ("/", "/index.html"):
            return self._document(query)
        # The token stops a program from driving the API; it cannot gate the
        # page's own files. A browser fetches a script, a stylesheet or a
        # font with no header and, on navigation, no query, so a check here
        # would only ever answer 403 and the page would never start. The
        # document above is what carries the token, and it is what names
        # these files.
        try:
            return self._static(path)
        except Exception:  # noqa: BLE001 - an unknown route is a 404, not a broken server
            return self._json(404, {"error": {"kind": "not_found", "message": path}})

    def do_POST(self) -> None:
        path, query = _split(self.path)
        if path != "/api/action":
            return self._json(405, {"error": {"kind": "method", "message": path}})
        # The origin goes first: a page from another site that somehow learns
        # the token must not get the token check's answer. The token is checked
        # before the body is read, so a refused request costs no upload.
        if not self._same_origin():
            return self._json(403, {"error": {"kind": "cross_origin",
                                              "message": "this server answers its own page only"}})
        if not self._carries(query, query_token=False):
            return self._unauthorized()
        body = self._body()
        if body is None:
            return
        try:
            request = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._json(400, {"error": {"kind": "bad_payload", "message": "body must be JSON"}})
        if not isinstance(request, dict) or not isinstance(request.get("action"), str):
            return self._json(400, {"error": {"kind": "bad_payload", "message": "action is required"}})
        if self.server.engine is not None:
            try:
                status, payload = self.server.engine.handle(request)
            except Exception:  # noqa: BLE001 - a dying handler thread would hang the page
                self.server.log("error", "the action handler failed before it could answer")
                return self._json(500, {"error": {"kind": "failed",
                                                  "message": "the action failed; see the Studio log"}})
            return self._json(status, payload)
        return self._json(503, {"error": {"kind": "not_ready",
                                          "message": "the studio is not accepting actions yet"}})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Allow", "GET, POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- the action route

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        parsed = urlsplit(origin)
        if parsed.scheme != "http" or parsed.port != self.server.server_address[1]:
            return False
        # A page opened at localhost is the same page; the bind is loopback
        # either way, and a bookmark should not make every action a 403.
        return (parsed.hostname or "").lower() in ("127.0.0.1", "localhost", "::1")

    def _carries(self, query: str, query_token: bool) -> bool:
        """Whether this request carries the token ``start`` minted.

        A server that was never started has none, so nothing carries it.
        """
        wanted = getattr(self.server, "run_token", None)
        if not wanted:
            return False
        given = self.headers.get(TOKEN_HEADER) or ""
        if query_token:
            given = given or (parse_qs(query).get("token") or [""])[0]
        return secrets.compare_digest(given.encode(), wanted.encode())

    def _vary_token(self) -> None:
        """These files are cached for an hour, and a browser can fetch them with or without a query."""
        self.send_header("Vary", TOKEN_HEADER)

    def _unauthorized(self) -> None:
        self._json(403, {"error": {"kind": "unauthorized",
                                   "message": "missing or wrong run token; open the URL the server printed"}})
        # A refused POST still has its body in the socket. Left there, it is
        # parsed as the next request on a kept-alive connection and the real
        # one goes unanswered; closing the connection is the cheap way out.
        self.close_connection = True

    def _body(self) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": {"kind": "bad_payload", "message": "bad Content-Length"}})
            return None
        if length > MAX_BODY:
            self._json(413, {"error": {"kind": "too_large", "message": "body is too large"}})
            return None
        if length == 0:
            return b""
        try:
            self.connection.settimeout(BODY_TIMEOUT_S)
            data = self.rfile.read(length)
        except (TimeoutError, OSError):
            data = None
        finally:
            self.connection.settimeout(None)
        if data is None:
            self.close_connection = True
            self._json(408, {"error": {"kind": "timeout",
                                       "message": "the body was not received in time"}})
            return None
        if len(data) < length:
            self.close_connection = True
            self._json(400, {"error": {"kind": "bad_payload",
                                       "message": "the body ended before Content-Length"}})
            return None
        return data

    def _json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _plate(self, name: str) -> None:
        """One generated plate by name. A name that is not a bare file in the output is refused."""
        services = getattr(getattr(self.server.engine, "studio", None), "services", None)
        path = services.plate_path(unquote(name)) if services is not None else None
        if path is None:
            return self._json(404, {"error": {"kind": "not_found", "message": "no such plate"}})
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/png" if path.suffix.lower() == ".png" else "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=3600")
        self._vary_token()
        self.end_headers()
        self.wfile.write(data)

    def _thumb(self, name: str) -> None:
        """One picture's thumbnail, decoded once and kept until the file changes.

        A history row's ``image`` is a file the request saved beside the history
        store, not a plate in the output folder, so the name is looked for in
        both places before the request is refused.
        """
        services = getattr(getattr(self.server.engine, "studio", None), "services", None)
        path = services.picture_path(unquote(name)) if services is not None else None
        png = services.thumbnail(path) if path is not None else None
        if png is None:
            return self._json(404, {"error": {"kind": "not_found", "message": "no such thumb"}})
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(png)))
        self.send_header("Cache-Control", "private, max-age=3600")
        self._vary_token()
        self.end_headers()
        self.wfile.write(png)

    # -- the event stream

    def _events(self) -> None:
        sub = self.server.hub.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self.wfile.write(events.HELLO)
            self.wfile.flush()
            while True:
                if not sub.ready.wait(EVENT_WAIT_S):
                    # A comment line on a quiet stream keeps a proxy from closing it.
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                sub.ready.clear()
                while True:
                    try:
                        item = sub.take(timeout=0)
                    except events.StreamEnded:
                        item = None
                        break
                    if item is None:
                        break
                    name, data = item
                    self.wfile.write(events.frame(name, data))
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.server.hub.unsubscribe(sub)
            self.close_connection = True

    # -- the page

    def _document(self, query: str) -> None:
        """The page itself, refused without the token so a foreign document cannot embed it."""
        if not self._carries(query, query_token=True):
            return self._unauthorized()
        self._static("/index.html")

    def _static(self, path: str) -> None:
        root = self.server.dist
        if root is None or not (root / "index.html").is_file():
            data = MISSING_BUILD.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        rel = path.lstrip("/") or "index.html"
        target = (root / rel).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            return self._json(400, {"error": {"kind": "bad_path", "message": path}})
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            # A deep link (a bookmark typed without the hash) gets the one
            # document; a missing script or stylesheet is a real 404, so a
            # stale build shows as a missing asset instead of a page that
            # loads and then does nothing.
            if "." in target.name:
                return self._json(404, {"error": {"kind": "not_found", "message": path}})
            target = root / "index.html"
        data = target.read_bytes()
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        # Angular names a hashed script or stylesheet after its own bytes, so a
        # new build gives it a new name and the old one can never change. The
        # document keeps `no-cache`, because it is the file that names them.
        self.send_header("Cache-Control", HASHED if _hashed(target.name) else "no-cache")
        self.end_headers()
        self.wfile.write(data)


def _split(target: str) -> tuple[str, str]:
    """A request target as its path and its raw query."""
    parts = urlsplit(target)
    return parts.path, parts.query


def _hashed(name: str) -> bool:
    """Whether Angular gave this file its content hash, as in ``main-ABCDEFGH.js``."""
    return bool(_HASHED_NAME.match(name))


_HASHED_NAME = re.compile(r"^.+-[A-Za-z0-9_]{8,}\.(?:m?js|css)$")


def serve(registry: Registry, *, dist: Path | None, port: int,
          log: Callable[[str, str], None] | None = None) -> StudioServer:
    """Bind the server and start serving on a background thread. Returns it for shutdown."""
    web = StudioServer(registry, dist=dist, log=log)
    web.start(port=port)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    return web
