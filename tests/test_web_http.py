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
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio.web import actions, server  # noqa: E402


def _quiet(_level: str, _text: str) -> None:
    pass


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calls: list[dict] = []
        registry = actions.Registry()

        @registry.action("echo", need={"text": str})
        def _echo(payload: dict) -> dict:
            cls.calls.append(payload)
            return {"text": payload["text"]}

        @registry.action("refuse")
        def _refuse(_payload: dict) -> dict:
            raise ValueError("A profile needs a name")

        @registry.action("explode")
        def _explode(_payload: dict) -> dict:
            raise KeyError("SECRET_TOKEN")

        cls.web = server.StudioServer(registry, dist=None, log=_quiet)
        cls.port = cls.web.start(port=0)
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.web.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.web.shutdown()
        cls.web.server_close()

    def _post(self, body: bytes, path: str = "/api/action", origin: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
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

    def test_a_well_formed_call_answers_200_with_its_data(self) -> None:
        status, body = self._post(json.dumps({"action": "echo", "payload": {"text": "hi"}}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True, "data": {"text": "hi"}})

    def test_a_refusal_answers_200_with_an_error_the_page_shows(self) -> None:
        status, body = self._post(json.dumps({"action": "refuse", "payload": {}}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(body["ok"], False)
        self.assertEqual(body["error"]["kind"], "refused")
        self.assertEqual(body["error"]["message"], "A profile needs a name")

    def test_an_unplanned_failure_does_not_carry_its_text_to_the_page(self) -> None:
        status, body = self._post(json.dumps({"action": "explode", "payload": {}}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(body["error"]["kind"], "failed")
        self.assertNotIn("SECRET_TOKEN", json.dumps(body))

    def test_an_unknown_action_answers_400(self) -> None:
        status, body = self._post(json.dumps({"action": "nope", "payload": {}}).encode())
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["kind"], "unknown_action")

    def test_a_body_that_is_not_json_answers_400(self) -> None:
        req = urllib.request.Request(
            f"{self.base}/api/action", data=b"not json", method="POST",
            headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 400)

    def test_a_request_with_no_action_answers_400(self) -> None:
        req = urllib.request.Request(
            f"{self.base}/api/action", data=json.dumps({"payload": {}}).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 400)

    def test_a_cross_site_post_is_refused_before_the_table_runs(self) -> None:
        self.calls.clear()
        req = urllib.request.Request(
            f"{self.base}/api/action", data=json.dumps({"action": "echo", "payload": {"text": "x"}}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Origin": "https://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.calls, [])

    def test_a_page_loaded_from_this_server_may_post(self) -> None:
        status, _body = self._post(
            json.dumps({"action": "echo", "payload": {"text": "x"}}).encode(), path="/api/action")
        self.assertEqual(status, 200)
        req = urllib.request.Request(
            f"{self.base}/api/action", data=json.dumps({"action": "echo", "payload": {"text": "y"}}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Origin": self.base})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

    def test_a_page_opened_at_localhost_may_post(self) -> None:
        status, _body = self._post(
            json.dumps({"action": "echo", "payload": {"text": "x"}}).encode(),
            origin=f"http://localhost:{self.port}")
        self.assertEqual(status, 200)

    def test_a_page_from_another_port_is_still_refused(self) -> None:
        status, _body = self._post(
            json.dumps({"action": "echo", "payload": {"text": "x"}}).encode(),
            origin=f"http://localhost:{self.port + 1}")
        self.assertEqual(status, 403)

    def test_a_foreign_get_is_refused(self) -> None:
        req = urllib.request.Request(f"{self.base}/api/health", headers={"Origin": "https://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)

    def test_a_page_at_localhost_may_read(self) -> None:
        req = urllib.request.Request(
            f"{self.base}/api/health", headers={"Origin": f"http://localhost:{self.port}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

    def test_an_action_table_that_raises_still_answers(self) -> None:
        with mock.patch.object(self.web.registry, "call", side_effect=RuntimeError("SECRET_TOKEN")):
            status, body = self._post(json.dumps({"action": "echo", "payload": {"text": "x"}}).encode())
        self.assertEqual(status, 500)
        self.assertEqual(body["error"]["kind"], "failed")
        self.assertNotIn("SECRET_TOKEN", json.dumps(body))

    def test_a_body_that_stops_early_answers_instead_of_hanging(self) -> None:
        with mock.patch.object(server, "BODY_TIMEOUT_S", 0.2):
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            try:
                sock.sendall(
                    b"POST /api/action HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\nContent-Length: 20\r\n\r\n{"
                )
                sock.settimeout(3)
                reply = sock.recv(4096)
            finally:
                sock.close()
        self.assertRegex(reply, rb"HTTP/1.1 (408|400)")

    def test_a_get_on_the_action_route_answers_405(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{self.base}/api/action", timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 405)

    def test_the_events_route_serves_an_event_stream(self) -> None:
        with urllib.request.urlopen(f"{self.base}/api/events", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.headers["Content-Type"])
            first = resp.readline()
            self.assertTrue(first.startswith(b":") or first.startswith(b"event:"), first)

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
        cls.dist = root
        cls.web = server.StudioServer(actions.Registry(), dist=root, log=_quiet)
        cls.port = cls.web.start(port=0)
        cls.base = f"http://127.0.0.1:{cls.port}"
        threading.Thread(target=cls.web.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.web.shutdown()
        cls.web.server_close()
        cls.tmp.cleanup()

    def test_the_root_serves_index(self) -> None:
        with urllib.request.urlopen(f"{self.base}/", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers["Content-Type"])
            self.assertIn(b"<title>studio</title>", resp.read())

    def test_a_script_is_served_with_a_javascript_type(self) -> None:
        with urllib.request.urlopen(f"{self.base}/main.js", timeout=5) as resp:
            self.assertIn("javascript", resp.headers["Content-Type"])

    def test_a_path_that_escapes_the_build_directory_is_not_served(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{self.base}/../etc/passwd", timeout=5)
        caught.exception.close()
        self.assertIn(caught.exception.code, (400, 404))

    def test_a_missing_file_answers_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{self.base}/nope.js", timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 404)


class MissingBuildTest(unittest.TestCase):
    def test_no_build_answers_with_the_command_that_makes_one(self) -> None:
        web = server.StudioServer(actions.Registry(), dist=None, log=_quiet)
        port = web.start(port=0)
        threading.Thread(target=web.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                body = resp.read().decode()
            self.assertIn("ng build", body)
        finally:
            web.shutdown()
            web.server_close()


if __name__ == "__main__":
    unittest.main()
