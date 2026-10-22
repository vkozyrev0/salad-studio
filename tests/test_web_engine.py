"""The engine: one request in, the page's whole state out, on the core thread.

The engine is what the HTTP layer calls. Driving it directly keeps these tests
about the protocol rather than about sockets: the reply shape, the refusal
shapes, the busy guard, and the confirm token that makes a Yes act on the row
it was issued for.
"""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import profiles  # noqa: E402
import tokens  # noqa: E402
from salad_studio.web import controllers  # noqa: E402
from salad_studio.web.core import Core  # noqa: E402
from salad_studio.web.engine import WebEngine  # noqa: E402
from salad_studio.web.events import Hub  # noqa: E402
from salad_studio.web.registry import Controllers  # noqa: E402
from salad_studio.web.shell import Shell  # noqa: E402


class EngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        # Every test method re-imports the module under a new name unless it is
        # already loaded, so the stubs below are applied to the one module the
        # controller writes through.
        import salad_studio.tokens as pkg_tokens

        self.saved = [
            (profiles.PROFILES_PATH, tokens.LOCAL_PATH),
            (pkg_tokens.LOCAL_PATH, pkg_tokens.default_path,
             pkg_tokens.read_env_token, pkg_tokens.seed_from_defaults),
        ]
        profiles.PROFILES_PATH = Path(self.tmp.name) / "studio-profiles.json"
        # ``read_token`` falls back to ``~/.config/salad`` and then to the
        # environment. A test that saves a key must see its own key back, so
        # both fallbacks point at the temp directory and nothing else.
        for module in (tokens, pkg_tokens):
            module.LOCAL_PATH = Path(self.tmp.name) / "studio-tokens.json"
            module.default_path = lambda _kind: Path(self.tmp.name) / "no-default"
            module.read_env_token = lambda _kind: ""
            module.seed_from_defaults = lambda: []
        self.core = Core(workers=2).start()
        self.hub = Hub()
        self.studio = Shell(self.core, self.hub)
        self.studio.controllers = Controllers(self.studio)
        controllers.install(self.studio.controllers)
        self.studio.services.start(timers=False)
        self.engine = WebEngine(self.studio)

    def tearDown(self) -> None:
        self.studio.services.stop()
        self.core.stop()
        profiles.PROFILES_PATH = self.saved[0][0]
        (tokens.LOCAL_PATH, tokens.default_path, tokens.read_env_token,
         tokens.seed_from_defaults) = self.saved[1]
        self.tmp.cleanup()

    def test_a_page_answers_with_its_state_the_shell_and_the_busy_map(self) -> None:
        reply = self.engine.page("tokens")
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["page"], "tokens")
        self.assertEqual(len(reply["state"]["slots"]), 5)
        self.assertIn("status", reply["shell"])
        self.assertEqual(reply["busy"], {})

    def test_opening_a_page_records_it_on_the_shell(self) -> None:
        self.engine.page("queue")
        self.assertEqual(self.studio.current, "queue")

    def test_saving_a_key_writes_it_and_answers_with_the_new_state(self) -> None:
        status, reply = self.engine.handle(
            {"page": "tokens", "action": "save_key", "args": {"values": {"salad": "sk-test"}}})
        self.assertEqual(status, 200)
        self.assertTrue(reply["ok"])
        self.assertEqual(tokens.read_token("salad"), "sk-test")
        self.assertEqual(reply["shell"]["note"]["level"], "ok")

    def test_a_save_with_every_field_empty_says_so_and_writes_nothing(self) -> None:
        status, reply = self.engine.handle(
            {"page": "tokens", "action": "save_key", "args": {"values": {"salad": "  "}}})
        self.assertEqual(status, 200)
        self.assertEqual(reply["shell"]["note"]["level"], "warn")
        self.assertEqual(tokens.read_token("salad"), "")

    def test_an_unknown_page_or_action_is_an_unknown_action(self) -> None:
        status, reply = self.engine.handle({"page": "nope", "action": "x", "args": {}})
        self.assertEqual(status, 200)
        self.assertFalse(reply["ok"])
        self.assertIn("unknown_action", reply["errorDetail"]["kind"])

    def test_a_payload_missing_its_field_is_refused_at_the_boundary(self) -> None:
        status, reply = self.engine.handle({"page": "tokens", "action": "save_key", "args": {}})
        self.assertEqual(status, 200)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["errorDetail"]["kind"], "bad_payload")

    def test_a_request_without_page_or_action_is_a_400(self) -> None:
        status, reply = self.engine.handle({"page": "tokens"})
        self.assertEqual(status, 400)
        self.assertFalse(reply["ok"])

    def test_a_confirmed_action_acts_on_the_arguments_it_was_issued_for(self) -> None:
        _status, reply = self.engine.handle({"page": "shell", "action": "clean_gallery", "args": {}})
        effect = reply["effects"][0]
        self.assertEqual(effect["kind"], "confirm")
        self.assertTrue(effect["token"])
        status, done = self.engine.handle({"confirm": effect["token"]})
        self.assertEqual(status, 200)
        self.assertTrue(done["ok"])
        self.assertIn("Removed", done["shell"]["note"]["text"])

    def test_a_confirm_token_cannot_be_used_twice(self) -> None:
        _status, reply = self.engine.handle({"page": "shell", "action": "clean_gallery", "args": {}})
        token = reply["effects"][0]["token"]
        self.engine.handle({"confirm": token})
        status, again = self.engine.handle({"confirm": token})
        self.assertEqual(status, 409)
        self.assertFalse(again["ok"])

    def test_a_second_call_while_one_is_in_flight_is_refused_with_409(self) -> None:
        started = time.monotonic()
        self.studio.controllers.get("tokens")
        self.studio.busy["tokens.check_keys"] = True
        status, reply = self.engine.handle({"page": "tokens", "action": "check_keys", "args": {}})
        self.assertEqual(status, 409)
        self.assertEqual(reply["error"]["kind"], "busy")
        self.assertGreaterEqual(time.monotonic() - started, 0)
        self.studio.busy.pop("tokens.check_keys", None)


if __name__ == "__main__":
    unittest.main()
