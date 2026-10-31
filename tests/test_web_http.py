"""The server's wire: one JSON endpoint, the page's files, and a loopback bind.

These tests start the real server on port 0 and speak HTTP to it, so what they
check is what the browser gets: the status code, the content type, the JSON
shape, and that no request from another site can drive the action table.
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio.web import actions, server  # noqa: E402
from salad_studio.web.engine import WebEngine  # noqa: E402
from salad_studio.web.server import TOKEN_HEADER  # noqa: E402


def _quiet(_level: str, _text: str) -> None:
    pass


class _Table:
    """The minimum a studio gives its engine: an action table and a core thread."""

    def __init__(self, table: actions.Registry) -> None:
        from salad_studio.web.core import Core

        self.controllers = type("Controllers", (), {"table": table, "get": lambda _self, _page: None})()
        self.core = Core().start()

    def publish(self) -> None:
        pass


class _Studio:
    """What the engine reads off the studio, with a probe page that answers from the table."""

    def __init__(self, table: _Table) -> None:
        self.controllers = table.controllers
        self.core = table.core
        self.busy: dict[str, bool] = {}

    def state_dict(self) -> dict:
        return {}

    def publish(self) -> None:
        pass

    def say(self, _text: str, *, level: str = "info") -> None:
        pass

    def note(self, _text: str, *, level: str = "info") -> None:
        pass

    def open_page(self, _page: str) -> None:
        pass


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calls: list[dict] = []
        registry = actions.Registry()

        @registry.action("probe.view")
        def _view(_payload: dict, *, ctx: Any = None) -> dict:
            return {}

        @registry.action("probe.echo", need={"text": str})
        def _echo(payload: dict, *, ctx: Any = None) -> dict:
            cls.calls.append(payload)
            return {"text": payload["text"]}

        @registry.action("probe.refuse")
        def _refuse(_payload: dict, *, ctx: Any = None) -> dict:
            raise ValueError("A profile needs a name")

        @registry.action("probe.explode")
        def _explode(_payload: dict, *, ctx: Any = None) -> dict:
            raise KeyError("SECRET_TOKEN")

        cls.table = _Table(registry)
        cls.web = server.StudioServer(registry, dist=None, log=_quiet,
                                      engine=WebEngine(_Studio(cls.table)))
        cls.port = cls.web.start(port=0)
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.token = cls.web.run_token or ""
        cls.thread = threading.Thread(target=cls.web.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.web.shutdown()
        cls.web.server_close()
        cls.table.core.stop()

    def _post(self, body: bytes, path: str = "/api/action", origin: str | None = None,
              token: str | None = None) -> tuple[int, dict]:
        """One POST carrying the run token unless the test passes its own, or none."""
        headers = {"Content-Type": "application/json", TOKEN_HEADER: self.token if token is None else token}
        if origin is not None:
            headers["Origin"] = origin
        req = urllib.request.Request(
            f"{self.base}{path}", data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read())
            finally:
                exc.close()

    def _get(self, path: str, origin: str | None = None) -> Any:
        """One GET carrying the token header; the page's own reads all go this way."""
        headers = {TOKEN_HEADER: self.token}
        if origin is not None:
            headers["Origin"] = origin
        return urllib.request.urlopen(urllib.request.Request(f"{self.base}{path}", headers=headers), timeout=5)

    def _refused(self, req: urllib.request.Request) -> dict:
        """Open a request that must be refused; its status and JSON body."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        try:
            code, body = caught.exception.code, json.loads(caught.exception.read())
        finally:
            caught.exception.close()
        self.assertEqual(code, 403)
        return body

    def _echo(self, text: str = "x") -> bytes:
        return json.dumps({"page": "probe", "action": "echo", "args": {"text": text}}).encode()

    def test_a_well_formed_call_answers_200_with_its_data(self) -> None:
        status, body = self._post(json.dumps({"page": "probe", "action": "echo", "args": {"text": "hi"}}).encode())
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["page"], "probe")
        self.assertEqual(self.calls[-1], {"text": "hi"})

    def test_a_refusal_answers_200_with_an_error_the_page_shows(self) -> None:
        status, body = self._post(json.dumps({"page": "probe", "action": "refuse", "args": {}}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(body["ok"], False)
        self.assertEqual(body["error"], "A profile needs a name")

    def test_an_unplanned_failure_does_not_carry_its_text_to_the_page(self) -> None:
        status, body = self._post(json.dumps({"page": "probe", "action": "explode", "args": {}}).encode())
        self.assertEqual(status, 200)
        self.assertIn("error", body)
        self.assertNotIn("SECRET_TOKEN", json.dumps(body))

    def test_an_unknown_action_is_a_reply_the_page_can_read(self) -> None:
        status, body = self._post(json.dumps({"page": "probe", "action": "nope", "args": {}}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(body["error"], "no action named probe.nope")

    def test_a_body_that_is_not_json_answers_400(self) -> None:
        req = urllib.request.Request(
            f"{self.base}/api/action", data=b"not json", method="POST",
            headers={"Content-Type": "application/json", TOKEN_HEADER: self.token})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 400)

    def test_a_request_with_no_action_answers_400(self) -> None:
        req = urllib.request.Request(
            f"{self.base}/api/action", data=json.dumps({"page": "probe"}).encode(), method="POST",
            headers={"Content-Type": "application/json", TOKEN_HEADER: self.token})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 400)

    def test_a_cross_site_post_is_refused_before_the_table_runs(self) -> None:
        self.calls.clear()
        req = urllib.request.Request(
            f"{self.base}/api/action", data=json.dumps({"page": "probe", "action": "echo", "args": {"text": "x"}}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Origin": "https://evil.example",
                     TOKEN_HEADER: self.token})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.calls, [])

    def test_a_page_loaded_from_this_server_may_post(self) -> None:
        status, _body = self._post(
            json.dumps({"page": "probe", "action": "echo", "args": {"text": "x"}}).encode(), path="/api/action")
        self.assertEqual(status, 200)
        req = urllib.request.Request(
            f"{self.base}/api/action", data=json.dumps({"page": "probe", "action": "echo", "args": {"text": "y"}}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Origin": self.base, TOKEN_HEADER: self.token})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

    def test_a_page_opened_at_localhost_may_post(self) -> None:
        status, _body = self._post(
            json.dumps({"page": "probe", "action": "echo", "args": {"text": "x"}}).encode(),
            origin=f"http://localhost:{self.port}")
        self.assertEqual(status, 200)

    def test_a_page_from_another_port_is_still_refused(self) -> None:
        status, _body = self._post(
            json.dumps({"page": "probe", "action": "echo", "args": {"text": "x"}}).encode(),
            origin=f"http://localhost:{self.port + 1}")
        self.assertEqual(status, 403)

    def test_a_foreign_get_is_refused(self) -> None:
        req = urllib.request.Request(
            f"{self.base}/api/events", headers={"Origin": "https://evil.example", TOKEN_HEADER: self.token})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)

    def test_a_page_at_localhost_may_read(self) -> None:
        req = urllib.request.Request(
            f"{self.base}/api/page/probe",
            headers={"Origin": f"http://localhost:{self.port}", TOKEN_HEADER: self.token})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

    def test_the_health_route_is_gone(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get("/api/health")
        caught.exception.close()
        self.assertEqual(caught.exception.code, 404)

    def test_an_action_table_that_raises_still_answers(self) -> None:
        with mock.patch.object(self.table.controllers.table, "call", side_effect=RuntimeError("SECRET_TOKEN")):
            status, body = self._post(json.dumps({"page": "probe", "action": "echo", "args": {"text": "x"}}).encode())
        self.assertEqual(status, 500)
        self.assertIn("error", body)
        self.assertNotIn("SECRET_TOKEN", json.dumps(body))

    def test_a_body_that_stops_early_answers_instead_of_hanging(self) -> None:
        with mock.patch.object(server, "BODY_TIMEOUT_S", 0.2):
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            try:
                sock.sendall(
                    b"POST /api/action HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    + f"{TOKEN_HEADER}: {self.token}\r\n".encode()
                    + b"Content-Type: application/json\r\nContent-Length: 20\r\n\r\n{"
                )
                sock.settimeout(3)
                reply = sock.recv(4096)
            finally:
                sock.close()
        self.assertRegex(reply, rb"HTTP/1.1 (408|400)")

    def test_a_get_on_the_action_route_answers_405(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get("/api/action")
        caught.exception.close()
        self.assertEqual(caught.exception.code, 405)

    # -- the run token

    def test_the_token_is_long_and_different_every_run(self) -> None:
        other = server.StudioServer(actions.Registry(), dist=None, log=_quiet)
        other.start(port=0)
        try:
            self.assertGreaterEqual(len(self.token), 40)
            self.assertNotEqual(other.run_token, self.token)
        finally:
            other.server_close()

    def test_a_post_with_no_token_is_refused_before_the_action_runs(self) -> None:
        self.calls.clear()
        status, body = self._post(self._echo(), token="")
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["kind"], "unauthorized")
        self.assertEqual(self.calls, [])

    def test_a_post_with_a_wrong_token_is_refused(self) -> None:
        self.calls.clear()
        status, body = self._post(self._echo(), token="not-the-token")
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["kind"], "unauthorized")
        self.assertEqual(self.calls, [])

    def test_a_post_with_the_right_token_runs_the_action(self) -> None:
        status, body = self._post(self._echo("hi"))
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"], body)
        self.assertEqual(self.calls[-1], {"text": "hi"})

    def test_a_cross_site_post_with_the_right_token_is_still_refused(self) -> None:
        self.calls.clear()
        status, body = self._post(self._echo(), origin="https://evil.example")
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["kind"], "cross_origin")
        self.assertEqual(self.calls, [])

    def test_the_token_in_the_query_does_not_stand_in_for_the_header_on_a_post(self) -> None:
        """A cross-site form can put anything in a URL but cannot set a header."""
        self.calls.clear()
        status, _body = self._post(self._echo(), path=f"/api/action?token={self.token}", token="")
        self.assertEqual(status, 403)
        self.assertEqual(self.calls, [])

    def test_a_server_that_never_started_refuses_every_request(self) -> None:
        """A handler built without ``start`` has no token to match, so nothing gets in."""
        web = server.StudioServer(actions.Registry(), dist=None, log=_quiet)
        threading.Thread(target=web.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{web.server_address[1]}"
        try:
            for path in ("/api/page/probe", "/?token=", "/api/events?token=", "/api/action"):
                with self.subTest(path=path):
                    self._refused(urllib.request.Request(f"{base}{path}"))
        finally:
            web.shutdown()
            web.server_close()

    def test_events_with_no_token_is_refused(self) -> None:
        body = self._refused(urllib.request.Request(f"{self.base}/api/events"))
        self.assertEqual(body["error"]["kind"], "unauthorized")

    def test_events_with_the_query_token_streams(self) -> None:
        with urllib.request.urlopen(f"{self.base}/api/events?token={self.token}", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.headers["Content-Type"])
            self.assertTrue(resp.readline().startswith(b":"))

    def test_a_page_read_needs_the_token(self) -> None:
        self._refused(urllib.request.Request(f"{self.base}/api/page/probe"))
        with self._get("/api/page/probe") as resp:
            self.assertEqual(resp.status, 200)

    def test_the_query_token_alone_opens_the_page_route(self) -> None:
        """The header is the page's way; the query is only for what a browser opens itself."""
        self._refused(urllib.request.Request(f"{self.base}/api/page/probe?token={self.token}"))

    def test_a_page_read_from_another_site_is_refused_even_with_the_token(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get("/api/page/probe", origin="https://evil.example")
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)

    def test_the_document_opens_from_the_url_the_server_prints(self) -> None:
        """``/`` and ``/index.html`` take the query token, so the printed URL is the page's."""
        with urllib.request.urlopen(f"{self.base}/?token={self.token}#/config", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("ng build", resp.read().decode(), "no build here, so the page says how to make one")

    def test_the_document_without_the_token_is_refused(self) -> None:
        for path in ("/", "/index.html", "/?token=wrong"):
            with self.subTest(path=path):
                self._refused(urllib.request.Request(f"{self.base}{path}"))

    def test_the_server_binds_loopback_only(self) -> None:
        self.assertEqual(self.web.host, "127.0.0.1")


class StaticFilesTest(unittest.TestCase):
    """The built page is served from disk; a missing build says so in words."""

    @classmethod
    def setUpClass(cls) -> None:
        import tempfile

        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "index.html").write_text("<!doctype html><title>studio</title>", encoding="utf-8")
        (root / "main.js").write_text("console.log('hi')", encoding="utf-8")
        (root / "main-ABCD1234EF.js").write_text("console.log('hashed')", encoding="utf-8")
        (root / "styles-09ZYXWVU.css").write_text("body{}", encoding="utf-8")
        cls.dist = root
        cls.web = server.StudioServer(actions.Registry(), dist=root, log=_quiet)
        cls.port = cls.web.start(port=0)
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.token = cls.web.run_token or ""
        threading.Thread(target=cls.web.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.web.shutdown()
        cls.web.server_close()
        cls.tmp.cleanup()

    def _open(self, path: str) -> Any:
        """The page's own fetch: the token header, as the built Angular app sends it."""
        return urllib.request.urlopen(
            urllib.request.Request(f"{self.base}{path}", headers={TOKEN_HEADER: self.token}), timeout=5)

    def _document(self, path: str = "/") -> Any:
        """A navigation, which carries no header: the token rides in the URL."""
        return urllib.request.urlopen(f"{self.base}{path}?token={self.token}", timeout=5)

    def test_the_root_serves_index(self) -> None:
        with self._document() as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers["Content-Type"])
            self.assertIn(b"<title>studio</title>", resp.read())

    def test_a_script_is_served_with_a_javascript_type(self) -> None:
        with self._open("/main.js") as resp:
            self.assertIn("javascript", resp.headers["Content-Type"])

    def test_a_script_the_page_loads_is_served_without_a_header_or_query(self) -> None:
        """A browser asks for a script with the document's origin and nothing else."""
        for path in ("/main.js", "/main-ABCD1234EF.js", "/styles-09ZYXWVU.css"):
            with self.subTest(path=path):
                with urllib.request.urlopen(f"{self.base}{path}", timeout=5) as resp:
                    self.assertEqual(resp.status, 200)

    def test_a_plate_takes_the_token_in_the_header_not_the_query(self) -> None:
        """The page fetches a plate through its HttpClient, whose interceptor sets the header."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{self.base}/api/thumbs/x.jpg?token={self.token}", timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._open("/api/thumbs/x.jpg")
        caught.exception.close()
        self.assertEqual(caught.exception.code, 404, "a file there is refused on the header, not before it")

    def test_opening_files_does_not_open_the_api(self) -> None:
        """The token still stops a program from driving the studio; only the page's files are open."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{self.base}/api/page/nope", timeout=5)
        body = caught.exception.read()
        caught.exception.close()
        self.assertEqual(json.loads(body)["error"]["kind"], "unauthorized")

    def test_a_path_that_escapes_the_build_directory_is_not_served(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._open("/../etc/passwd")
        caught.exception.close()
        self.assertIn(caught.exception.code, (400, 404))

    def test_a_missing_file_answers_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._open("/nope.js")
        caught.exception.close()
        self.assertEqual(caught.exception.code, 404)

    def test_a_hashed_asset_is_cached_and_the_document_is_not(self) -> None:
        """A new build renames a script, so the old name can never change."""
        for name in ("main-ABCD1234EF.js", "styles-09ZYXWVU.css"):
            with self._open(f"/{name}") as resp:
                policy = resp.headers["Cache-Control"]
            self.assertIn("immutable", policy, name)
        with self._document("/index.html") as resp:
            self.assertIn("no-cache", resp.headers["Cache-Control"])

    def test_a_route_that_would_fail_on_disk_answers_json_404(self) -> None:
        """The root answers before the document root; a failure there is still a missing route."""
        with mock.patch.object(server.StudioHandler, "_static", side_effect=PermissionError("denied")):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self._open("/whatever")
            body = caught.exception.read()
            code = caught.exception.code
            caught.exception.close()
        self.assertEqual(code, 404)
        self.assertEqual(json.loads(body)["error"]["kind"], "not_found")

    def test_a_response_to_a_peer_that_stops_reading_has_a_deadline(self) -> None:
        self.assertEqual(server.StudioHandler.timeout, server.BODY_TIMEOUT_S)


class MissingBuildTest(unittest.TestCase):
    def test_no_build_answers_with_the_command_that_makes_one(self) -> None:
        web = server.StudioServer(actions.Registry(), dist=None, log=_quiet)
        port = web.start(port=0)
        threading.Thread(target=web.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/?token={web.run_token}", timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                body = resp.read().decode()
            self.assertIn("ng build", body)
        finally:
            web.shutdown()
            web.server_close()


if __name__ == "__main__":
    unittest.main()
