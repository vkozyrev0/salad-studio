"""The assembled studio: every page answers, and the server says so.

This is the test that would have caught a page registered under a name the
rail never asks for, or a controller whose state raises on an empty store. It
builds the studio the way ``python -m salad_studio`` does, with the timers off
so nothing reaches the network, and asks each page for its state.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import profiles  # noqa: E402
import tokens  # noqa: E402
from salad_studio.web import app  # noqa: E402
from salad_studio.web.registry import PAGE_IDS  # noqa: E402


class AssembledStudioTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.saved = (
            profiles.PROFILES_PATH, tokens.LOCAL_PATH,
            tokens.default_path, tokens.read_env_token, tokens.seed_from_defaults,
        )
        profiles.PROFILES_PATH = home / "studio-profiles.json"
        tokens.LOCAL_PATH = home / "studio-tokens.json"
        tokens.default_path = lambda _kind: home / "no-default"
        tokens.read_env_token = lambda _kind: ""
        tokens.seed_from_defaults = lambda: []
        self.studio = app.build(dist=None, timers=False)

    def tearDown(self) -> None:
        self.studio.stop()
        (profiles.PROFILES_PATH, tokens.LOCAL_PATH, tokens.default_path,
         tokens.read_env_token, tokens.seed_from_defaults) = self.saved
        self.tmp.cleanup()

    def test_the_app_opens_on_config_and_wires_the_core_error_sink(self) -> None:
        self.assertEqual(app.START_PAGE, "config")
        self.assertTrue(self.studio.url.endswith("#/config"), self.studio.url)
        self.assertIsNotNone(self.studio.core.on_error, "a timer error must be logged, not raised")

    def test_every_page_the_rail_names_answers_with_a_state(self) -> None:
        for page in PAGE_IDS:
            with self.subTest(page=page):
                reply = self.studio.shell.engine.page(page)
                self.assertTrue(reply["ok"], reply)
                self.assertNotIn("error", reply["state"], reply["state"])

    def test_every_page_registers_a_view_and_at_least_one_action(self) -> None:
        names = set(self.studio.shell.controllers.names())
        for page in PAGE_IDS:
            with self.subTest(page=page):
                own = {name for name in names if name.startswith(page + ".")}
                self.assertIn(f"{page}.view", own)
                self.assertGreater(len(own), 1)

    def test_no_action_name_collides_across_pages(self) -> None:
        names = list(self.studio.shell.controllers.names())
        self.assertEqual(len(names), len(set(names)))

    def test_an_action_on_every_page_keeps_the_reply_shape(self) -> None:
        for page in PAGE_IDS:
            with self.subTest(page=page):
                _status, reply = self.studio.shell.engine.handle(
                    {"page": page, "action": "view", "args": {}})
                self.assertIn("shell", reply)
                self.assertIn("busy", reply)
                self.assertIn("effects", reply)

    def test_the_server_binds_loopback_and_serves_health(self) -> None:
        port = self.studio.server.start(port=0)
        self.assertGreater(port, 0)
        self.assertEqual(self.studio.server.host, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
