"""Prompt Assist through the engine: a Help round trip on a worker, then a commit.

The round trip is the real ``ai_helper`` code. Its HTTP call is replaced by a
sender that builds a genuine chat-completions body in memory, so the parsing,
the reply contract and the request the service would see are all exercised
and nothing touches the network.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ai_helper  # noqa: E402
import lora_store  # noqa: E402
import prompt_catalog  # noqa: E402
import tokens  # noqa: E402
from salad_studio import profiles, request_json  # noqa: E402
import salad_studio.ai_helper as pkg_ai_helper  # noqa: E402
import salad_studio.lora_store as pkg_lora  # noqa: E402
import salad_studio.prompt_catalog as pkg_catalog  # noqa: E402
import salad_studio.tokens as pkg_tokens  # noqa: E402
from salad_studio.web.core import Core  # noqa: E402
from salad_studio.web.engine import WebEngine  # noqa: E402
from salad_studio.web.events import Hub  # noqa: E402
from salad_studio.web.pages import add_all  # noqa: E402
from salad_studio.web.pages import editor as editor_page  # noqa: E402
from salad_studio.web.pages.assist import COMMITTED  # noqa: E402
from salad_studio.web.registry import Controllers  # noqa: E402
from salad_studio.web.shell import Shell  # noqa: E402

ANSWER = '{"positive": "a sharper watercolour portrait", "negative": "blurry, dark"}'


def klein() -> dict:
    return request_json.build_request(prompt_text="a watercolour portrait", negative_text="blurry",
                                      graph="klein", width=1024, height=1024, steps=20, seed=1,
                                      selected_ids=[])


def completion(content: str) -> bytes:
    """A chat-completions response body, as DeepSeek and LM Studio both send it."""
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


class AssistTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        here = Path(self.tmp.name)
        self.restore = [
            (profiles, "PROFILES_PATH", profiles.PROFILES_PATH),
            (lora_store, "EXTRAS_PATH", lora_store.EXTRAS_PATH),
            (pkg_lora, "EXTRAS_PATH", pkg_lora.EXTRAS_PATH),
            (prompt_catalog, "CATALOG_PATH", prompt_catalog.CATALOG_PATH),
            (pkg_catalog, "CATALOG_PATH", pkg_catalog.CATALOG_PATH),
            (tokens, "LOCAL_PATH", tokens.LOCAL_PATH),
            (tokens, "default_path", tokens.default_path),
            (tokens, "read_env_token", tokens.read_env_token),
            (tokens, "seed_from_defaults", tokens.seed_from_defaults),
            (pkg_tokens, "LOCAL_PATH", pkg_tokens.LOCAL_PATH),
            (pkg_tokens, "default_path", pkg_tokens.default_path),
            (pkg_tokens, "read_env_token", pkg_tokens.read_env_token),
            (pkg_tokens, "seed_from_defaults", pkg_tokens.seed_from_defaults),
        ]
        profiles.PROFILES_PATH = here / "studio-profiles.json"
        lora_store.EXTRAS_PATH = pkg_lora.EXTRAS_PATH = here / "studio-loras.json"
        prompt_catalog.CATALOG_PATH = pkg_catalog.CATALOG_PATH = here / "studio-prompt-catalog.json"
        # read_token falls back to ~/.config/salad and then to the environment;
        # both fallbacks point at the temp directory and nothing else.
        for module in (tokens, pkg_tokens):
            module.LOCAL_PATH = here / "studio-tokens.json"
            module.default_path = lambda _kind: here / "no-default"
            module.read_env_token = lambda _kind: ""
            module.seed_from_defaults = lambda: []
        self.sent: list[tuple[str, str, dict]] = []  # (url, body, headers) per request the module would send
        self.reply = ANSWER
        self.sender_error: Exception | None = None
        self.holds: list[tuple[str, str]] = []  # (action, fields) captured before the event fires
        self.effects: list[dict] = []  # the effect half of the last done event
        for module in (ai_helper, pkg_ai_helper):
            patcher = mock.patch.object(module, "_http_send", self.send)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.core = Core(workers=2).start()
        self.hub = Hub()
        self.studio = Shell(self.core, self.hub)
        self.studio.services.out_dir = Path(self.tmp.name) / "art"
        self.studio.controllers = Controllers(self.studio)
        add_all(self.studio.controllers)
        self.studio.services.start(timers=False)
        self.engine = WebEngine(self.studio)
        # ``publish_done`` hands a finished background action back through the
        # studio's engine. Without this, it finds none and the action stays busy.
        self.studio.engine = self.engine

    def tearDown(self) -> None:
        self.studio.services.stop()
        self.core.stop()
        for module, name, value in self.restore:
            setattr(module, name, value)
        self.tmp.cleanup()

    # -- helpers

    def send(self, request, timeout: int) -> tuple[int, bytes]:
        if str(request.full_url).endswith("/models"):
            # The local backend lists the server's models before it picks one.
            return 200, json.dumps({"data": [{"id": "qwen2.5-vl-7b"}]}).encode("utf-8")
        body = request.data.decode("utf-8") if request.data is not None else ""
        self.sent.append((request.full_url, body, dict(request.headers)))
        if self.sender_error is not None:
            raise self.sender_error
        return 200, completion(self.reply)

    def call(self, page: str, action: str, args: dict | None = None) -> dict:
        status, reply = self.engine.handle({"page": page, "action": action, "args": args or {}})
        self.assertEqual(status, 200, reply)
        self.assertTrue(reply["ok"], reply.get("error"))
        return reply

    def act(self, action: str, args: dict | None = None) -> dict:
        return self.call("assist", action, args)

    def editor(self):
        return self.studio.controllers.get("editor")

    def next_event(self, sub, name: str, seconds: float = 10.0) -> dict:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            item = sub.take(0.1)
            if item is not None and item[0] == name:
                return item[1]
        self.fail(f"no {name} event arrived")

    def hold(self):
        """Record each event's fields as the stream hands it out, before the test sees it.

        An event carries the whole page state by reference. The next action
        mutates that same dict, so by the time a test reads an event it may
        show a later state; these snapshots show what was sent at send time.
        """
        sub = self.hub.subscribe()
        inner = sub.take

        def take(timeout: float):
            item = inner(timeout)
            if item is not None and item[0] == "action_done":
                reply = item[1].get("reply") or {}
                self.holds.append((reply.get("page", ""), json.dumps(reply.get("state") or {})))
                self.effects = json.loads(json.dumps(reply.get("effects") or []))
            return item
        sub.take = take
        return sub

    def ask(self, backend: str = "local", edited: dict | None = None) -> dict:
        """Press Help, answer, and return the page state the done event carried, as it was sent."""
        sub = self.hold()
        reply = self.act("help", {"backend": backend, "edited": edited or {}})
        self.assertTrue(reply["pending"])
        event = self.next_event(sub, "action_done")
        self.assertEqual(event["id"], reply["id"])
        self.assertFalse(event["reply"]["pending"])
        return json.loads(self.holds[-1][1])

    # -- the view

    def test_the_view_carries_the_boxes_and_the_image_note(self) -> None:
        state = self.engine.page("assist")["state"]
        self.assertEqual(set(state), {"localUrl", "sendImage", "imageNote", "issue", "positive",
                                      "negative", "reply", "status"})
        self.assertEqual(state["localUrl"], ai_helper.LOCAL_BASE_URL)
        self.assertFalse(state["sendImage"])
        self.assertEqual(state["imageNote"], "off, no image is sent")
        self.assertEqual(set(state["status"]), {"text", "level"})

    # -- the round trip

    def test_help_answers_at_once_and_finishes_through_action_done(self) -> None:
        self.editor().set_payload(klein())
        state = self.ask("local", {"issue": "the hands are wrong", "localUrl": "http://box:1234/v1"})
        url, body, _headers = next(row for row in self.sent if not row[0].endswith("/models"))
        self.assertEqual(url, "http://box:1234/v1/chat/completions")
        self.assertEqual(self.engine.page("assist")["state"]["localUrl"], "http://box:1234/v1")
        prompt = json.dumps(json.loads(body)["messages"])
        self.assertIn("the hands are wrong", prompt)
        self.assertIn("a watercolour portrait", prompt)
        self.assertEqual(state["status"], {"text": "The model answered", "level": "info"})
        self.assertEqual(state["positive"], "a sharper watercolour portrait")
        self.assertEqual(state["negative"], "blurry, dark")
        self.assertIn("sharper watercolour portrait", state["reply"])

    def test_help_shows_that_it_is_asking_before_the_model_answers(self) -> None:
        self.act("help", {"backend": "local"})
        self.assertEqual(self.engine.page("assist")["state"]["status"]["text"], "Asking the local model…")

    def test_help_with_deepseek_sends_the_saved_key(self) -> None:
        tokens.write_token("deepseek", "sk-test-key")
        state = self.ask("deepseek")
        url, _body, headers = next(row for row in self.sent if not row[0].endswith("/models"))
        self.assertIn("api.deepseek.com", url)
        self.assertEqual(headers["Authorization"], "Bearer sk-test-key")
        self.assertEqual(state["positive"], "a sharper watercolour portrait")

    def test_deepseek_without_a_key_asks_before_spending_a_call(self) -> None:
        reply = self.act("help", {"backend": "deepseek"})
        self.assertFalse(reply["pending"])
        self.assertEqual(reply["effects"][0]["kind"], "confirm")
        self.assertEqual(self.sent, [])

    def test_a_confirmed_help_with_no_key_answers_with_the_refusal(self) -> None:
        asked = self.act("help", {"backend": "deepseek"})
        status, done = self.engine.handle({"confirm": asked["effects"][0]["token"]})
        self.assertEqual(status, 200)
        self.assertTrue(done["ok"], done.get("error"))
        self.assertIn("No DeepSeek key", done["state"]["reply"])
        self.assertEqual(done["state"]["status"]["level"], "error")
        self.assertEqual(self.sent, [])

    def test_a_reply_without_prompts_is_shown_raw_and_leaves_the_boxes(self) -> None:
        self.reply = "I could not tell what the image shows."
        state = self.ask("local")
        self.assertEqual(self.effects[-1]["kind"], "dialog")
        self.assertEqual(state["reply"], self.reply)
        self.assertEqual(state["positive"], "")
        self.assertEqual(state["status"]["level"], "error")

    def test_a_failed_call_is_a_dialog_and_an_error(self) -> None:
        self.sender_error = OSError("connection refused")
        state = self.ask("local")
        self.assertEqual(self.effects[-1]["kind"], "dialog")
        self.assertEqual(state["status"]["level"], "error")
        self.assertIn("connection refused", state["status"]["text"])
        self.assertFalse(self.studio.busy.get("assist.help"))

    # -- the commit

    def test_commit_writes_the_adjusted_prompts_into_the_editor(self) -> None:
        self.editor().set_payload(klein())
        self.act("commit", {"edited": {"positive": "a crisp portrait", "negative": "soft"}})
        self.assertEqual(self.studio.note_line.text, COMMITTED)
        self.assertEqual(self.studio.note_line.level, "ok")
        view = self.editor().state()
        self.assertEqual((view["positive"], view["negative"]), ("a crisp portrait", "soft"))
        prompt = editor_page.parse(view["json"]).prompt
        self.assertEqual(editor_page.prompt_texts(prompt), ("a crisp portrait", "soft"))
        self.assertIn("convert_output", json.loads(view["json"]))

    def test_commit_with_both_prompts_empty_is_refused(self) -> None:
        before = self.editor().state()
        reply = self.act("commit", {"edited": {"positive": "  ", "negative": ""}})
        self.assertEqual(reply["effects"][0]["kind"], "dialog")
        self.assertEqual(self.editor().state()["json"], before["json"])

    def test_a_help_then_commit_lands_the_models_prompts_in_the_editor(self) -> None:
        self.editor().set_payload(klein())
        state = self.ask("local")
        self.act("commit", {"edited": {"positive": state["positive"], "negative": state["negative"]}})
        view = self.editor().state()
        self.assertEqual((view["positive"], view["negative"]),
                         ("a sharper watercolour portrait", "blurry, dark"))


if __name__ == "__main__":
    unittest.main()
