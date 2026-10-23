"""The engine: one request in, the page's whole state out, on the core thread.

The engine is what the HTTP layer calls. Driving it directly keeps these tests
about the protocol rather than about sockets: the reply shape, the refusal
shapes, the busy guard, and the confirm token that makes a Yes act on the row
it was issued for.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import profiles  # noqa: E402
import prompt_history  # noqa: E402
import tokens  # noqa: E402
from salad_studio.web import controllers, pages  # noqa: E402
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

        self.pkg_tokens = pkg_tokens
        self.history_saved = (prompt_history.HISTORY_PATH, prompt_history.THUMBS_DIR)
        prompt_history.HISTORY_PATH = Path(self.tmp.name) / "studio-prompt-history.json"
        prompt_history.THUMBS_DIR = Path(self.tmp.name) / "studio-prompt-thumbs"
        self.saved = [
            (profiles.PROFILES_PATH,),
            (tokens.LOCAL_PATH, tokens.default_path, tokens.read_env_token, tokens.seed_from_defaults),
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
        self.studio.services.out_dir = Path(self.tmp.name) / "art"
        self.studio.controllers = Controllers(self.studio)
        controllers.install(self.studio.controllers)
        pages.install(self.studio.controllers)
        self.studio.services.start(timers=False)
        self.engine = WebEngine(self.studio)
        # A background action reports through the studio's engine, as app.build
        # wires it; without this the done callback is dropped and a page waits.
        self.studio.engine = self.engine

    def tearDown(self) -> None:
        self.studio.services.stop()
        self.core.stop()
        profiles.PROFILES_PATH = self.saved[0][0]
        (tokens.LOCAL_PATH, tokens.default_path, tokens.read_env_token,
         tokens.seed_from_defaults) = self.saved[1]
        (self.pkg_tokens.LOCAL_PATH, self.pkg_tokens.default_path,
         self.pkg_tokens.read_env_token, self.pkg_tokens.seed_from_defaults) = self.saved[2]
        prompt_history.HISTORY_PATH, prompt_history.THUMBS_DIR = self.history_saved
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

    def test_a_confirm_while_the_action_is_busy_keeps_the_token(self) -> None:
        _status, reply = self.engine.handle({"page": "shell", "action": "clean_gallery", "args": {}})
        token = reply["effects"][0]["token"]
        self.studio.busy["shell.clean_gallery"] = True
        status, busy = self.engine.handle({"confirm": token})
        self.assertEqual(status, 409)
        self.assertEqual(busy["error"]["kind"], "busy")
        self.studio.busy.pop("shell.clean_gallery", None)
        status, done = self.engine.handle({"confirm": token})
        self.assertEqual(status, 200)
        self.assertTrue(done["ok"], "the token survived the busy refusal")

    def test_generate_reaches_the_services_and_clears_the_header(self) -> None:
        """The press must reach the queue, and the header must show it running."""
        from salad_studio.web.services import GenOutcome

        self.studio.form.mode = "vast"
        self.studio.form.gateway = "http://203.0.113.9:8188"
        self.engine.handle({"page": "editor", "action": "set_json", "args": {
            "text": '{"prompt": {"1": {"class_type": "UNETLoader", '
                    '"inputs": {"unet_name": "x.safetensors"}}}}',
            "base": 0,
        }})
        seen: list[tuple] = []
        gate = threading.Event()

        def fake_generate(payload, profile, key, checksum, *, ts=None, history_key=None):
            seen.append((payload, profile.name, key, checksum, ts, history_key))
            gate.wait(2)
            return GenOutcome("done", out=None)

        self.studio.services.generate_sync = fake_generate
        status, reply = self.engine.handle({"page": "shell", "action": "generate", "args": {}})
        self.assertEqual(status, 200)
        self.assertEqual(reply["action"], "generate")
        deadline = time.monotonic() + 5
        while not seen and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(seen), 1, "Generate must reach generate_sync")
        self.assertTrue(self.studio.gen.busy, "the header is busy while the render runs")
        gate.set()
        while self.studio.gen.busy and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.studio.gen.busy, "the header clears when the render ends")

    def test_a_vast_press_refuses_a_typed_salad_gateway(self) -> None:
        self.studio.form.mode = "vast"
        self.studio.form.gateway = "https://typed.salad.cloud/"
        self.engine.handle({"page": "editor", "action": "set_json", "args": {
            "text": '{"prompt": {"1": {"class_type": "UNETLoader", '
                    '"inputs": {"unet_name": "x.safetensors"}}}}',
            "base": 0,
        }})
        _status, reply = self.engine.handle({"page": "shell", "action": "generate", "args": {}})
        bodies = [e["body"] for e in reply["effects"] if e["kind"] == "dialog"]
        self.assertTrue(any("Salad gateway" in body for body in bodies), bodies)
        self.assertFalse(self.studio.gen.busy, "a refused press does not start a render")

    def test_a_page_never_returns_a_raw_key(self) -> None:
        tokens.write_token("salad", "sk-secret-1234")
        reply = self.engine.page("tokens")
        slot = next(s for s in reply["state"]["slots"] if s["id"] == "salad")
        self.assertEqual(slot["value"], "", "the key stays on the server")
        self.assertTrue(slot["present"])
        self.assertNotIn("sk-secret", json.dumps(reply))

    def test_a_second_call_while_one_is_in_flight_is_refused_with_409(self) -> None:
        self.studio.controllers.get("tokens")
        self.studio.busy["tokens.check_keys"] = True
        status, reply = self.engine.handle({"page": "tokens", "action": "check_keys", "args": {}})
        self.assertEqual(status, 409)
        self.assertEqual(reply["error"]["kind"], "busy")
        self.studio.busy.pop("tokens.check_keys", None)

    def test_a_check_naming_one_key_probes_only_that_key(self) -> None:
        """The Tokens page checks a row, so one slow provider cannot hold up the rest."""
        calls: list[str] = []

        def probe(kind: str, key: str | None = None) -> dict[str, str]:
            calls.append(kind)
            return {"state": "valid"}

        with mock.patch.object(tokens, "probe_token", side_effect=probe):
            status, _reply = self.engine.handle(
                {"page": "tokens", "action": "check_keys", "args": {"kinds": ["salad"]}})
            self.assertEqual(status, 200)
            states = self.studio.controllers.get("tokens").states
            deadline = time.monotonic() + 2
            while states.get("salad") != "valid" and time.monotonic() < deadline:
                time.sleep(0.01)

        self.assertEqual(calls, ["salad"], "only the named provider is probed")
        self.assertEqual(states["salad"], "valid")
        self.assertEqual(states["deepseek"], "unknown", "the other rows keep their state")

    def test_a_check_without_kinds_probes_all_five(self) -> None:
        calls: list[str] = []

        def probe(kind: str, key: str | None = None) -> dict[str, str]:
            calls.append(kind)
            return {"state": "valid"}

        with mock.patch.object(tokens, "probe_token", side_effect=probe):
            status, _reply = self.engine.handle({"page": "tokens", "action": "check_keys", "args": {}})
            self.assertEqual(status, 200)
            states = self.studio.controllers.get("tokens").states
            deadline = time.monotonic() + 2
            while len([v for v in states.values() if v == "valid"]) < 5 and time.monotonic() < deadline:
                time.sleep(0.01)

        self.assertEqual(sorted(calls), sorted(kind for kind, _label in controllers.SLOTS))
        self.assertEqual(set(states.values()), {"valid"})

    def test_a_check_of_two_kinds_probes_only_those(self) -> None:
        calls: list[str] = []

        def probe(kind: str, key: str | None = None) -> dict[str, str]:
            calls.append(kind)
            return {"state": "valid"}

        with mock.patch.object(tokens, "probe_token", side_effect=probe):
            _status, _reply = self.engine.handle(
                {"page": "tokens", "action": "check_keys", "args": {"kinds": ["salad", "civitai"]}})
            states = self.studio.controllers.get("tokens").states
            deadline = time.monotonic() + 2
            while states.get("civitai") != "valid" and time.monotonic() < deadline:
                time.sleep(0.01)

        self.assertEqual(sorted(calls), ["civitai", "salad"])

    def test_an_empty_kinds_list_checks_none(self) -> None:
        calls: list[str] = []

        with mock.patch.object(tokens, "probe_token", side_effect=lambda kind, key=None: calls.append(kind)):
            status, reply = self.engine.handle(
                {"page": "tokens", "action": "check_keys", "args": {"kinds": []}})

        self.assertEqual(status, 200)
        self.assertEqual(calls, [])
        self.assertIn("No keys selected", reply["shell"]["note"]["text"])

    def test_a_malformed_kinds_list_is_refused(self) -> None:
        calls: list[str] = []

        with mock.patch.object(tokens, "probe_token", side_effect=lambda kind, key=None: calls.append(kind)):
            status, reply = self.engine.handle(
                {"page": "tokens", "action": "check_keys", "args": {"kinds": "salad"}})

        self.assertEqual(status, 200)
        self.assertFalse(reply["ok"])
        self.assertIn("kinds must be", reply["error"])
        self.assertEqual(calls, [])

        with mock.patch.object(tokens, "probe_token", side_effect=lambda kind, key=None: calls.append(kind)):
            status, reply = self.engine.handle(
                {"page": "tokens", "action": "check_keys", "args": {"kinds": ["nope"]}})
        self.assertEqual(status, 200)
        self.assertFalse(reply["ok"])
        self.assertIn("kinds must be", reply["error"])


if __name__ == "__main__":
    unittest.main()
