"""Import as a controller: the paste it holds, the knobs, the issues, the convert.

A real ``Core`` runs the background work, so a convert is waited for the way the
page waits for it: the stream is polled until ``action_done`` names the action.
Nothing here reaches Civitai: the store modules' paths point at a temp
directory, and the two functions that would call out are replaced.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _stores  # noqa: E402
import comfy_import  # noqa: E402
import lora_store  # noqa: E402
import prompt_history  # noqa: E402
from salad_studio.web.core import Core  # noqa: E402
from salad_studio.web.engine import WebEngine as Engine  # noqa: E402
from salad_studio.web.events import Hub  # noqa: E402
from salad_studio.web.pages.import_page import (  # noqa: E402
    EMPTY_REFUSAL, NOTHING_TO_CONVERT, STASH_CHARS, ImportController,
)
from salad_studio.web.registry import ActionContext, Controllers  # noqa: E402
from test_comfy_import import DISTILLED, DISTILLED_META  # noqa: E402

WORKFLOW = json.dumps(DISTILLED)


def setUpModule() -> None:
    _stores.keep_queue_ledger_off_the_user_store()


def tearDownModule() -> None:
    _stores.restore_queue_ledger()


class StubEditor:
    def __init__(self) -> None:
        self.loaded: dict[str, Any] | None = None

    def set_payload(self, body: dict[str, Any]) -> None:
        self.loaded = body

    def text(self) -> str:
        return json.dumps(self.loaded or {})


class StubServices:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def log(self, level: str, text: str) -> None:
        self.lines.append(f"{level} {text}")


class StubStudio:
    def __init__(self, core: Core, hub: Hub) -> None:
        self.core = core
        self.hub = hub
        self.services = StubServices()
        self.controllers = None
        self.engine = None
        self.confirms: dict[str, tuple[str, str, dict[str, Any]]] = {}
        self.ids = 0
        self.busy: dict[str, bool] = {}
        self.note_line: tuple[str, str] | None = None
        self.shell = self
        # The editor reads these the moment it is built, to open on the request
        # its settings describe.
        from salad_studio.web.form import Form

        self.form = Form()
        self.profile = None

    def note(self, text: str, *, level: str = "info") -> None:
        self.note_line = (text, level)

    say = note

    def state_dict(self) -> dict[str, Any]:
        note = self.note_line or ("", "info")
        return {"note": {"text": note[0], "level": note[1]}}

    def publish(self) -> None:
        pass

    def stored_profile(self):
        return None

    def next_reply_id(self) -> str:
        self.ids += 1
        return f"r{self.ids}"

    def publish_done(self, action_id: str, ctx: ActionContext, result: Any) -> None:
        self.engine.finish(action_id, ctx, result)

    def issue_confirm(self, page: str, action: str, args: dict[str, Any]) -> str:
        token = f"c_{len(self.confirms)}"
        self.confirms[token] = (page, action, dict(args))
        return token


class ImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (lora_store.EXTRAS_PATH, prompt_history.HISTORY_PATH,
                      prompt_history.THUMBS_DIR, comfy_import.ls.find_by_loader_name)
        lora_store.EXTRAS_PATH = Path(self.tmp.name) / "studio-loras.json"
        prompt_history.HISTORY_PATH = Path(self.tmp.name) / "studio-prompt-history.json"
        prompt_history.THUMBS_DIR = Path(self.tmp.name) / "studio-prompt-thumbs"
        # The catalog is a known LoraLoader name away from a Civitai search.
        comfy_import.ls.find_by_loader_name = lambda name, extras_path=None: None
        self.core = Core(workers=2).start()
        self.hub = Hub()
        self.stream = self.hub.subscribe()
        self.studio = StubStudio(self.core, self.hub)
        self.editor = StubEditor()
        self.studio.controllers = _ControllersWithEditor(self.studio, self.editor)
        self.controller = ImportController(self.studio)
        self.table = self.studio.controllers.table
        self.controller.register(self.table)
        self.studio.engine = Engine(self.studio)

    def tearDown(self) -> None:
        self.core.stop()
        (lora_store.EXTRAS_PATH, prompt_history.HISTORY_PATH,
         prompt_history.THUMBS_DIR, comfy_import.ls.find_by_loader_name) = self.saved
        self.tmp.cleanup()

    def call(self, action: str, args: dict[str, Any] | None = None) -> Any:
        self.ctx = ActionContext(self.studio, "import", action, dict(args or {}))
        result = self.table.call(f"import.{action}", dict(args or {}), ctx=self.ctx)
        self.assertIsNone(result.error, result.error)
        return result.data

    def wait(self, action: str, timeout: float = 20.0) -> dict[str, Any]:
        """The reply the live stream would deliver for a background action."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.stream.take(0.05)
            if event is None:
                continue
            name, data = event
            if name == "action_done":
                return data["reply"]
        self.fail(f"{action} did not finish")

    def dialogs(self) -> list[dict[str, Any]]:
        return [e for e in self.ctx.effects if e["kind"] == "dialog"]

    # -- the view

    def test_the_view_carries_the_paste_the_knobs_and_the_issues(self) -> None:
        state = self.call("view")
        self.assertEqual([k["key"] for k in state["knobs"]], ["cfg", "seed", "steps", "width", "height"])
        self.assertEqual(state["knobs"][0], {"key": "cfg", "label": "CFG", "value": ""})
        self.assertEqual(state["scheduler"], "Flux2 (Klein)")
        self.assertEqual(state["scheduler_labels"], ["Flux2 (Klein)", "Simple (Civitai)"])
        self.assertEqual(state["unet"], "")
        self.assertEqual(state["issues"], [], "an empty list means the page shows nothing")
        self.assertEqual(state["workflow"], "")
        self.assertEqual(state["meta"], "")

    def test_the_state_holds_no_call_to_action_flags(self) -> None:
        state = self.call("view")
        self.assertEqual(set(state), {"url", "meta", "workflow", "stashed", "knobs", "scheduler",
                                      "scheduler_labels", "unet", "unet_labels", "issues", "notes",
                                      "inspected"})

    # -- the paste and the knobs

    def test_fill_reads_the_paste_and_returns_the_knobs_as_a_list(self) -> None:
        state = self.call("fill_knobs", {"meta": DISTILLED_META, "workflow": WORKFLOW})
        values = {k["key"]: k["value"] for k in state["knobs"]}
        self.assertEqual(values, {"cfg": "1", "seed": "824168918863563", "steps": "4",
                                  "width": "1280", "height": "1920"})
        self.assertEqual(state["scheduler"], "Flux2 (Klein)")
        self.assertEqual(state["unet"], "Distilled 9B")
        self.assertTrue(state["inspected"])
        self.assertEqual(state["issues"], [])
        self.assertTrue(any("ReferenceLatent" in n for n in state["notes"]))
        self.assertEqual(self.ctx.note_text, ("Import knobs filled from paste", "info"))

    def test_fill_with_nothing_pasted_refuses_in_both_places(self) -> None:
        state = self.call("fill_knobs", {})
        self.assertEqual(self.dialogs()[0]["body"], EMPTY_REFUSAL)
        self.assertEqual(self.ctx.note_text, (f"Refused: {EMPTY_REFUSAL}", "warn"))
        self.assertFalse(state["inspected"])

    def test_a_paste_the_page_sent_is_held_and_the_box_shows_a_summary(self) -> None:
        state = self.call("set_paste", {"workflow": WORKFLOW + " " * (STASH_CHARS + 1)})
        self.assertTrue(state["stashed"])
        self.assertEqual(state["workflow"][:1], "[")

    def test_a_large_paste_moves_into_the_stash_and_the_box_shows_a_summary(self) -> None:
        big = WORKFLOW + " " * (STASH_CHARS + 1)
        state = self.call("set_paste", {"workflow": big})
        self.assertTrue(state["stashed"])
        self.assertIn(f"{len(big):,} characters", state["workflow"])
        filled = self.call("fill_knobs", {"workflow": state["workflow"]})
        self.assertEqual({k["key"]: k["value"] for k in filled["knobs"]}["steps"], "4",
                         "the fill reads the held paste, not the summary")

    def test_fill_only_empty_keeps_a_knob_the_user_typed(self) -> None:
        self.call("set_paste", {"workflow": WORKFLOW, "meta": DISTILLED_META})
        state = self.call("fill_knobs", {"only_empty": True, "steps": "8"})
        self.assertEqual({k["key"]: k["value"] for k in state["knobs"]}["steps"], "8")

    def test_clear_import_drops_the_paste_and_the_knobs(self) -> None:
        self.call("set_paste", {"workflow": WORKFLOW, "meta": DISTILLED_META})
        self.call("fill_knobs", {})
        state = self.call("clear_import")
        self.assertEqual([k["value"] for k in state["knobs"]], ["", "", "", "", ""])
        self.assertEqual(state["workflow"], "")
        self.assertEqual(state["meta"], "")
        self.assertFalse(state["inspected"])
        self.assertEqual(self.ctx.note_text, ("Import paste cleared", "info"))

    # -- convert

    def test_convert_refuses_an_empty_paste(self) -> None:
        state = self.call("convert", {})
        self.assertEqual(self.dialogs()[0]["body"], NOTHING_TO_CONVERT)
        self.assertEqual(self.ctx.note_text, (f"Refused: {NOTHING_TO_CONVERT}", "warn"))
        self.assertIsNone(self.editor.loaded)

    def test_convert_lands_the_request_in_the_editor_and_opens_it(self) -> None:
        self.call("set_paste", {"workflow": WORKFLOW, "meta": DISTILLED_META})
        started = self.call("convert", {})
        self.assertEqual(started["knobs"][0]["label"], "CFG")
        reply = self.wait("convert")
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertEqual(set(self.editor.loaded), {"prompt", "convert_output", "refs"})
        self.assertIn("flux-2-klein-9b-fp8", json.dumps(self.editor.loaded))
        self.assertIn({"kind": "navigate", "page": "editor"}, reply["effects"])
        self.assertEqual(reply["shell"]["note"], {"text": "Imported Civitai workflow to Prompt Editor",
                                                  "level": "ok"})
        state = self.controller.state()
        self.assertTrue(state["inspected"])
        self.assertTrue(all(isinstance(n, str) for n in state["issues"] + state["notes"]))
        self.assertTrue(any("imported Civitai paste" in line for line in self.studio.services.lines))
        self.assertFalse(self.controller.state()["stashed"], "the held paste is spent")

    # -- fetch

    def test_fetch_asks_for_a_url_before_any_network_call(self) -> None:
        with mock.patch.object(comfy_import, "fetch_civitai_image_pastes") as fetch:
            self.call("fetch_civitai", {"url": "not a link"})
            fetch.assert_not_called()
        self.assertIn("Paste a Civitai image URL", self.dialogs()[0]["body"])

    def test_fetch_fills_the_paste_from_the_stubbed_site(self) -> None:
        stubbed = {"image_id": "123", "metadata": DISTILLED_META, "workflow": WORKFLOW, "tool": "Comfy"}
        with mock.patch.object(comfy_import, "fetch_civitai_image_pastes", return_value=stubbed), \
                mock.patch.object(comfy_import.ls, "write_extra"):
            self.call("fetch_civitai", {"url": "https://civitai.com/images/123"})
            reply = self.wait("fetch_civitai")
        self.assertTrue(reply["ok"], reply.get("error"))
        state = self.controller.state()
        self.assertEqual(state["url"], "https://civitai.com/images/123")
        self.assertEqual(state["meta"], DISTILLED_META)
        self.assertEqual({k["key"]: k["value"] for k in state["knobs"]}["steps"], "4")
        self.assertEqual(reply["shell"]["note"], {"text": "Fetched 123 (Comfy)", "level": "ok"})


class ConvertRefusalTest(unittest.TestCase):
    """Through the real engine, so the reply a refusal ends in is the one the page reads."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = comfy_import.import_to_request
        self.core = Core(workers=2).start()
        self.hub = Hub()
        self.stream = self.hub.subscribe()
        self.studio = StubStudio(self.core, self.hub)
        studio = self.studio

        import salad_studio.web.pages as pages

        self.studio.controllers = Controllers(studio)
        pages.install(self.studio.controllers)
        self.studio.engine = Engine(studio)
        self.engine = self.studio.engine

    def tearDown(self) -> None:
        comfy_import.import_to_request = self.saved
        self.core.stop()
        self.tmp.cleanup()

    def test_a_convert_the_store_refuses_answers_with_a_dialog(self) -> None:
        comfy_import.import_to_request = mock.Mock(side_effect=ValueError("no sampler"))
        _status, started = self.engine.handle({"page": "import", "action": "set_paste",
                                               "args": {"meta": "Steps: 4, Seed: 1, Model: flux-2-klein-9b"}})
        self.assertTrue(started["ok"])
        _status, reply = self.engine.handle({"page": "import", "action": "convert", "args": {}})
        self.assertTrue(reply["pending"])
        deadline = time.monotonic() + 10
        done = None
        while time.monotonic() < deadline and done is None:
            event = self.stream.take(0.2)
            if event and event[0] == "action_done":
                done = event[1]["reply"]
        self.assertIsNotNone(done, "the refusal was never published")
        self.assertEqual(done["effects"], [{"kind": "dialog", "title": "Salad Studio",
                                            "body": "Cannot convert Civitai paste: no sampler",
                                            "level": "error"}])
        self.assertEqual(done["shell"]["note"], {"text": "Refused: cannot convert the Civitai paste",
                                                 "level": "error"})
        comfy_import.import_to_request.assert_called_once()


class _ControllersWithEditor(Controllers):
    def __init__(self, studio: StubStudio, editor: StubEditor) -> None:
        super().__init__(studio)
        self.editor = editor

    def get(self, page_id: str) -> Any:
        return self.editor if page_id == "editor" else super().get(page_id)


if __name__ == "__main__":
    unittest.main()
