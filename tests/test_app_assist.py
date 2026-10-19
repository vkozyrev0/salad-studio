"""Prompt Assist driven through its controls: local and DeepSeek rounds, commit, labels.

Ported from the Tk layout suite. A round runs on a held worker: the page hands
``work`` to ``AppServices.background``, the test records it, and runs it where
the test wants while the page is still "asking".
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
for _p in (HERE / ".." / "salad_studio", HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio import ai_helper, ref_check, tokens  # noqa: E402
from tests._flet_window import (  # noqa: E402
    TempStores, dialog_body, hidden_window, mount_opened, shown_texts, texts,
)


class Case(unittest.TestCase):
    def setUp(self) -> None:
        stores = TempStores()
        stores.__enter__()
        self.addCleanup(stores.__exit__, None, None, None)
        self.win, self.page = hidden_window()
        mount_opened(self.win)
        self.addCleanup(self.win.services.stop)
        self.held: list = []
        hold = mock.patch.object(self.win.services, "background",
                                 side_effect=lambda work, done: self.held.append((work, done)))
        hold.start()
        self.addCleanup(hold.stop)
        self.lookup = mock.patch.object(ref_check, "online_lookup", return_value=None)
        self.lookup.start()
        self.addCleanup(self.lookup.stop)
        self.assist = self.win.open_page("Prompt Assist")
        self.editor = self.win.open_page("Prompt Editor")

    def release(self) -> None:
        """Run every held worker on the calling thread and hand the result back."""
        held, self.held = self.held, []
        for work, done in held:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 - the page shows a worker's failure
                result = exc
            done(result)

    def deepseek(self, content: str) -> mock.Mock:
        """A DeepSeek key is saved and every send answers with ``content``."""
        tokens.write_token("deepseek", "ds-app-test-key")
        previous = getattr(self, "_sender", None)
        if previous is not None:
            previous.stop()

        def send(request, timeout):
            return 200, json.dumps({"choices": [{"message": {"content": content}}]}).encode()

        self._sender = mock.patch.object(ai_helper, "_http_send", side_effect=send)
        self._sender.start()
        self.addCleanup(self._stop_sender)
        return self._sender

    def _stop_sender(self) -> None:
        sender = getattr(self, "_sender", None)
        if sender is not None:
            sender.stop()
            self._sender = None


def assist_source() -> str:
    from salad_studio.pages import assist

    return assist.__file__


class ThePage(Case):
    def test_the_issue_box_and_the_image_option_default_off(self) -> None:
        self.assertEqual(self.assist.local_url.value, ai_helper.LOCAL_BASE_URL)
        self.assertFalse(self.assist.send_image.value)
        self.assertEqual(self.assist.image_note.value, "off, no image is sent")
        self.assertIn("Image issue / problem", texts(self.assist))

    def test_the_image_note_names_the_plate_when_it_is_on(self) -> None:
        plate = mock.Mock()
        plate.name = "plate-1.jpg"
        with mock.patch.object(self.assist, "latest_image", return_value=plate):
            self.assist.send_image.value = True
            self.assist._image_note()
        self.assertEqual(self.assist.image_note.value,
                         "the newest plate, plate-1.jpg, is attached")

    def test_every_backend_label_names_the_right_backend(self) -> None:
        self.assertIn("Help (DeepSeek)", texts(self.assist))
        self.assertIn("Help (local)", texts(self.assist))
        self.assertIn("Local LLM URL", texts(self.assist))
        shown = " ".join(texts(self.assist)) + " " + Path(assist_source()).read_text(encoding="utf-8")
        for stale in ("DeepSeek reply (raw)", "no image is sent to DeepSeek", "DeepSeek-backed prompt help"):
            self.assertNotIn(stale, shown)

    def test_help_without_a_key_says_where_the_key_goes(self) -> None:
        self.assist.start("deepseek")
        self.assertIn("No DeepSeek key", self.win.shell.status.value)
        self.assertIn("Tokens tab", self.assist.reply.value)
        self.assertEqual(self.held, [], "no key means no request")

    def test_the_inputs_are_the_editor_prompts_the_adjusted_pair_the_json_and_the_issue(self) -> None:
        self.assist.issue.value = "ISSUE"
        self.assist.adj_pos.value = "ADJ POS"
        self.assist.adj_neg.value = "ADJ NEG"
        inputs = self.assist._inputs()
        self.assertEqual(sorted(inputs), ["adjusted_negative", "adjusted_positive", "editor_negative",
                                          "editor_positive", "issue", "request_json"])
        self.assertEqual(inputs["issue"], "ISSUE")
        self.assertEqual(inputs["adjusted_positive"], "ADJ POS")
        self.assertEqual(inputs["request_json"], self.editor.text().strip())

    def test_editing_the_adjusted_boxes_never_touches_the_editor(self) -> None:
        before = self.editor.text()
        positive = self.editor.positive.value
        self.assist.adj_pos.value = "ADJUSTED ONLY POSITIVE"
        self.assist.adj_neg.value = "ADJUSTED ONLY NEGATIVE"
        self.assertEqual(self.editor.text(), before)
        self.assertEqual(self.editor.positive.value, positive)


class ADeepSeekRound(Case):
    def test_the_issue_rides_the_request_and_the_reply_fills_the_boxes(self) -> None:
        seen: dict = {}
        tokens.write_token("deepseek", "ds-app-test-key")

        def send(request, timeout):
            seen["request"] = request
            return 200, json.dumps({"choices": [{"message": {"content":
                                                             '{"positive": "P", "negative": "N"}'}}]}).encode()

        self.assist.issue.value = "the head is missing"
        with mock.patch.object(ai_helper, "_http_send", side_effect=send):
            self.assist.start("deepseek")
            self.assertEqual(self.assist.state.value, "Asking DeepSeek…")
            self.release()

        payload = json.loads(seen["request"].data.decode())
        content = payload["messages"][1]["content"]
        body = content if isinstance(content, str) else content[0]["text"]
        head = body.split("=== POSITIVE PROMPT")[0]
        self.assertIn("the head is missing", head)
        self.assertIn("HIGHEST PRIORITY", head)
        self.assertEqual(self.assist.adj_pos.value, "P")
        self.assertEqual(self.assist.adj_neg.value, "N")
        self.assertEqual(seen["request"].get_header("Authorization"), "Bearer ds-app-test-key")
        self.assertEqual(self.assist.state.value, "The model answered")

    def test_the_plate_rides_along_and_what_the_model_saw_is_shown(self) -> None:
        seen: dict = {}
        reply = json.dumps({"issue": "the left arm is missing", "positive": "ARM POSITIVE",
                            "negative": "ARM NEGATIVE"})

        def send(request, timeout):
            seen["request"] = request
            return 200, json.dumps({"choices": [{"message": {"content": reply}}]}).encode()

        self.assist.issue.value = "her arm is missing"
        with mock.patch.object(self.assist, "latest_image", return_value=Path("plate.jpg")), \
                mock.patch.object(ai_helper, "image_data_url", return_value="data:image/jpeg;base64,AA"), \
                mock.patch.object(ai_helper, "_http_send", side_effect=send):
            tokens.write_token("deepseek", "ds-app-test-key")
            self.assist.send_image.value = True
            self.assist.start("deepseek")
            self.release()

        body = json.loads(seen["request"].data.decode())["messages"][1]["content"]
        if not isinstance(body, str):
            self.assertEqual([part["type"] for part in body], ["text", "image_url"])
            self.assertIn("her arm is missing", body[0]["text"])
            self.assertTrue(body[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertIn("the left arm is missing", self.win.shell.status.value + self.assist.reply.value)
        self.assertEqual(self.assist.reply.value, reply, "the raw reply is shown as sent")
        self.assertEqual((self.assist.adj_pos.value, self.assist.adj_neg.value), ("ARM POSITIVE", "ARM NEGATIVE"))

    def test_a_reply_missing_a_prompt_leaves_that_box_alone(self) -> None:
        self.assist.adj_pos.value = "ARTIST POSITIVE"
        self.assist.adj_neg.value = "ARTIST NEGATIVE"
        body = json.dumps({"issue": "", "positive": "MODEL POSITIVE", "negative": ""})
        self.deepseek(body + " " * 400)
        self.assist.start("deepseek")
        self.release()
        self.assertEqual(self.assist.adj_pos.value, "MODEL POSITIVE")
        self.assertEqual(self.assist.adj_neg.value, "ARTIST NEGATIVE")

    def test_an_unparsable_reply_is_shown_raw_and_the_boxes_are_kept(self) -> None:
        import salad_studio.flet_services as services_mod

        from salad_studio.pages import assist as assist_mod

        self.assist.adj_pos.value = "KEEP ME"
        self.deepseek("I cannot help with that." + " " * 400)

        def unparsable(*_args, **_kwargs):
            raise ai_helper.ReplyError("the reply carried no positive/negative prompts",
                                       "I cannot help with that.")

        self.addCleanup(lambda: getattr(self, "_help_round", None) and self._help_round.stop())
        self._help_round = mock.patch.object(assist_mod, "help_round", unparsable)
        self._help_round.start()
        self.assist.start("deepseek")
        self.assertEqual(self.assist.state.value, "Asking DeepSeek…")
        try:
            self.release()
        except ai_helper.ReplyError:
            pass  # the page shows the reply as a failure, not as prompts
        self.assertIn("cannot help", dialog_body(self.page.overlay[-1]))

    def test_a_failed_call_is_reported_on_the_page_and_frees_the_button(self) -> None:
        tokens.write_token("deepseek", "ds-app-test-key")

        def boom(request, timeout):
            raise ai_helper.AiError("DeepSeek HTTP 402: Insufficient Balance")

        with mock.patch.object(ai_helper, "_http_send", side_effect=boom):
            self.assist.start("deepseek")
            self.assertTrue(self.win.services.busy_flags["help"], "the round is in flight")
            self.release()
        self.assertIn("402", dialog_body(self.page.overlay[-1]))
        self.assertIn("402", self.assist.state.value)
        self.assertFalse(self.win.services.busy_flags["help"], "Help must be pressable again")

    def test_a_second_press_while_asking_is_ignored(self) -> None:
        self.deepseek('{"positive": "P", "negative": "N"}')
        self.assist.start("deepseek")
        self.assertEqual(len(self.held), 1)
        self.assist.start("deepseek")
        self.assertEqual(len(self.held), 1, "a round in flight takes no second request")


class ALocalRound(Case):
    def test_the_entered_url_is_used_and_nothing_hidden_is_needed(self) -> None:
        seen: dict = {"urls": []}

        def send(request, timeout):
            seen["urls"].append(request.full_url)
            if request.full_url.endswith("/models"):
                return 200, json.dumps({"data": [{"id": "local-model"}]}).encode()
            seen["chat"] = request
            return 200, json.dumps({"choices": [{"message": {"content": json.dumps(
                {"positive": "LOCAL POS", "negative": "LOCAL NEG"})}}]}).encode()

        self.assist.local_url.value = "localhost:7777/v1"
        self.assist.adj_pos.value = "LOCAL ADJUSTED"
        with mock.patch.object(ai_helper, "_http_send", side_effect=send):
            self.assist.start("local")
            self.release()
        self.assertIn("http://localhost:7777/v1/models", seen["urls"])
        self.assertEqual(seen["chat"].full_url, "http://localhost:7777/v1/chat/completions")
        self.assertIsNone(seen["chat"].get_header("Authorization"), "a local request carries no key")
        body = json.loads(seen["chat"].data.decode())
        self.assertEqual(body["model"], "local-model")
        self.assertIn("LOCAL ADJUSTED", body["messages"][1]["content"])
        self.assertIn("LoraLoader", body["messages"][1]["content"])
        self.assertEqual((self.assist.adj_pos.value, self.assist.adj_neg.value), ("LOCAL POS", "LOCAL NEG"))
        self.assertIn("the model answered", self.assist.state.value.lower())

    def test_a_server_that_is_not_running_says_how_to_start_it(self) -> None:
        import socket

        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self.assist.local_url.value = f"http://127.0.0.1:{port}"
        self.assist.start("local")
        self.release()
        shown = dialog_body(self.page.overlay[-1])
        self.assertIn("LM Studio", shown)
        self.assertIn("Start Server", shown)
        self.assertIn("is the local model server running?", self.assist.state.value)
        self.assertFalse(self.win.services.busy_flags["help"], "the buttons come back")

    def test_every_url_form_reaches_the_chat_endpoint(self) -> None:
        posts: list[str] = []

        def send(request, timeout):
            if request.full_url.endswith("/models"):
                return 200, json.dumps({"data": [{"id": "chat-loaded"}]}).encode()
            posts.append(request.full_url)
            return 200, json.dumps({"choices": [{"message": {"content": '{"positive": "P", "negative": "N"}'}}]}
                                   ).encode()

        base = "http://127.0.0.1:4321"
        forms = (f"{base}/v1", f"{base}/api/v1", f"{base}/v1/chat/completions", "127.0.0.1:4321")
        with mock.patch.object(ai_helper, "_http_send", side_effect=send):
            for form in forms:
                with self.subTest(form=form):
                    out = ai_helper.help_with_prompts_local(url=form, editor_positive="X")
                    self.assertEqual(out["base"], f"{base}/v1")
                    self.assertEqual(out["model"], "chat-loaded")
        self.assertEqual(len(posts), len(forms))
        self.assertTrue(all(url.endswith("/v1/chat/completions") for url in posts))


class Commit(Case):
    def test_commit_writes_the_adjusted_prompts_into_the_prompts_and_the_json(self) -> None:
        self.assist.adj_pos.value = "COMMITTED POSITIVE"
        self.assist.adj_neg.value = "COMMITTED NEGATIVE"
        self.assist.commit()
        self.assertIn("committed", self.assist.state.value)
        self.assertNotIn("rebuilt", self.assist.state.value)
        self.assertEqual(self.editor.positive.value, "COMMITTED POSITIVE")
        self.assertEqual(self.editor.negative.value, "COMMITTED NEGATIVE")
        import json as _json

        prompt = _json.loads(self.editor.text())["prompt"]
        self.assertIn("COMMITTED POSITIVE", _json.dumps(prompt))
        self.assertIn("COMMITTED NEGATIVE", _json.dumps(prompt))

    def test_commit_refuses_empty_adjusted_prompts(self) -> None:
        before = self.editor.text()
        self.assist.commit()
        self.assertEqual(dialog_body(self.page.overlay[-1]),
                         "The adjusted prompts are empty. Ask DeepSeek or the local model for help first.")
        self.assertEqual(self.editor.text(), before)

    def test_commit_rebuilds_when_the_json_is_invalid_and_says_rebuilt(self) -> None:
        self.editor.json.value = "{broken"
        self.assist.adj_pos.value = "POS AFTER REBUILD"
        self.assist.commit()
        self.assertIn("rebuilt", self.assist.state.value)
        self.assertIn("POS AFTER REBUILD", self.editor.positive.value)
        self.assertIn("POS AFTER REBUILD", self.editor.text())


if __name__ == "__main__":
    unittest.main()
