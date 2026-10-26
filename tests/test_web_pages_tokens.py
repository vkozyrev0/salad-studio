"""Tokens on the web: every row saves what was typed, Check answers its own row.

The store is the temporary one ``_studio`` points the modules at, so a test
never reads or writes the person's own keys.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tokens  # noqa: E402
import salad_studio  # noqa: E402
from tests._studio import studio  # noqa: E402

SLOTS = ("salad", "huggingface", "civitai", "deepseek", "vast")


class SaveTest(unittest.TestCase):
    def test_a_typed_key_lands_in_its_own_slot(self) -> None:
        with studio() as made:
            _status, reply = made.act("tokens", "save_key", {"values": {"deepseek": "sk-typed"}})
            self.assertTrue(reply["ok"], reply.get("error"))
            deepseek = next(s for s in reply["state"]["slots"] if s["id"] == "deepseek")
            self.assertTrue(deepseek["present"])
            self.assertEqual(deepseek["hint"], "set (…yped)")
            self.assertEqual(tokens.read_token("deepseek"), "sk-typed")
            # A slot nobody typed into keeps what it had.
            for kind in SLOTS:
                if kind != "deepseek":
                    self.assertEqual(tokens.read_token(kind) or "", "", kind)

    def test_save_never_puts_a_key_in_the_page_state(self) -> None:
        with studio() as made:
            _status, reply = made.act("tokens", "save_key", {"values": {"salad": "sk-never-shown"}})
            self.assertNotIn("sk-never-shown", str(reply["state"]))
            self.assertFalse([e for e in reply["effects"] if e["kind"] == "reveal"])

    def test_a_payload_naming_an_unknown_slot_is_refused_and_writes_nothing(self) -> None:
        with studio() as made:
            status, reply = made.act("tokens", "save_key",
                                     {"values": {"salad": "sk-ok", "not-a-provider": "x"}})
            self.assertEqual(status, 200)
            self.assertFalse(reply["ok"])
            self.assertEqual(tokens.read_token("salad") or "", "")
            self.assertEqual(salad_studio.tokens.read_token("salad") or "", "")


class CheckTest(unittest.TestCase):
    def test_a_check_reports_its_answer_as_an_effect(self) -> None:
        with studio() as made:
            sub = made.app.hub.subscribe()
            try:
                with mock.patch.object(tokens, "probe_token", return_value={"state": "valid"}):
                    _status, reply = made.act("tokens", "check_keys", {"kinds": ["huggingface"]})
                    self.assertTrue(reply["pending"])
                    done = None
                    for _ in range(200):
                        event = sub.take(0.05)
                        if event and event[0] == "action_done":
                            done = event[1]["reply"]
                            break
            finally:
                made.app.hub.unsubscribe(sub)
            self.assertIsNotNone(done, "the check never finished")
            self.assertEqual([e for e in done["effects"] if e["kind"] == "token_state"],
                             [{"kind": "token_state", "states": {"huggingface": "valid"}}])
            slot = next(s for s in done["state"]["slots"] if s["id"] == "huggingface")
            self.assertEqual(slot["state"], "valid")


class RevealTest(unittest.TestCase):
    def test_show_returns_the_one_saved_key_and_saves_nothing(self) -> None:
        with studio() as made:
            made.act("tokens", "save_key", {"values": {"salad": "sk-reveal"}})
            before = tokens.LOCAL_PATH.read_text(encoding="utf-8")
            _status, reply = made.act("tokens", "reveal", {"id": "salad"})
            self.assertTrue(reply["ok"], reply.get("error"))
            self.assertEqual(reply["effects"], [{"kind": "reveal", "id": "salad", "value": "sk-reveal"}])
            self.assertNotIn("sk-reveal", str(reply["state"]))
            self.assertEqual(tokens.LOCAL_PATH.read_text(encoding="utf-8"), before,
                             "reading a key back writes nothing")

    def test_show_takes_one_row_and_refuses_anything_else(self) -> None:
        with studio() as made:
            for bad in (["salad", "civitai"], ["not-a-provider"]):
                status, reply = made.act("tokens", "reveal", {"id": bad})
                self.assertEqual(status, 200)
                self.assertFalse(reply["ok"], bad)
                self.assertFalse([e for e in reply["effects"] if e["kind"] == "reveal"])

    def test_show_on_an_empty_slot_says_so_and_reveals_nothing(self) -> None:
        with studio() as made:
            _status, reply = made.act("tokens", "reveal", {"id": "vast"})
            self.assertFalse([e for e in reply["effects"] if e["kind"] == "reveal"])
            self.assertEqual(reply["shell"]["note"]["level"], "warn")

    def test_show_never_reaches_a_background_reply(self) -> None:
        """A reveal answers the page that asked; it is not a broadcast."""
        with studio() as made:
            sub = made.app.hub.subscribe()
            try:
                made.act("tokens", "reveal", {"id": "salad"})
                seen = []
                while (event := sub.take(0.1)) is not None:
                    seen.append(event)
                self.assertNotIn("reveal", str(seen), "a reveal is never broadcast")
            finally:
                made.app.hub.unsubscribe(sub)


if __name__ == "__main__":
    unittest.main()
