"""Prompt Editor through the engine: the state a page draws, and the one write path.

Every request goes through ``WebEngine.handle``, which is what the HTTP layer
calls, so these tests see the reply a browser would get. The editor is shared
state, so the tests that need another page write into it drive that page's own
actions: Catalog's Copy and Load, with their store in a temp directory.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# The page modules run as top-level modules, so these are the copies that read
# and write the stores. The package copies are imported only to name them:
# a test that redirects one and not the other edits the user's own store.
import lora_store  # noqa: E402
import prompt_catalog  # noqa: E402
import tokens  # noqa: E402
from salad_studio import profiles, request_json  # noqa: E402
import salad_studio.lora_store as pkg_lora  # noqa: E402
import salad_studio.prompt_catalog as pkg_catalog  # noqa: E402
import salad_studio.tokens as pkg_tokens  # noqa: E402
from salad_studio.web.core import Core  # noqa: E402
from salad_studio.web.engine import WebEngine  # noqa: E402
from salad_studio.web.events import Hub  # noqa: E402
from salad_studio.web.pages import add_all  # noqa: E402
from salad_studio.web.pages import editor as editor_page  # noqa: E402
from salad_studio.web.pages.editor import EditorController  # noqa: E402
from salad_studio.web.registry import Controllers  # noqa: E402
from salad_studio.web.shell import Shell  # noqa: E402


def klein(text: str = "a watercolour portrait", negative: str = "blurry") -> dict:
    return request_json.build_request(prompt_text=text, negative_text=negative, graph="klein",
                                      width=1024, height=1024, steps=20, seed=1, selected_ids=[])


def edges_of(request: dict) -> list[dict]:
    """Every link in the request: source, target and the input it enters. The layout sorts them."""
    out = []
    for target, node in request["prompt"].items():
        for key, value in node.get("inputs", {}).items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                out.append((value[0], target, key))
    return sorted(out)


def text_encode_id(prompt: dict, text: str) -> str:
    return next(nid for nid, node in prompt.items()
                if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode"
                and node.get("inputs", {}).get("text") == text)


class EditorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        here = Path(self.tmp.name)
        # Every store the editor or a page writing into it reads, by both
        # module names, kept so tearDown can put the user's paths back.
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
        self.core = Core(workers=2).start()
        self.hub = Hub()
        self.studio = Shell(self.core, self.hub)
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

    def call(self, page: str, action: str, args: dict | None = None) -> dict:
        status, reply = self.engine.handle({"page": page, "action": action, "args": args or {}})
        self.assertEqual(status, 200, reply)
        self.assertTrue(reply["ok"], reply.get("error"))
        return reply

    def act(self, action: str, args: dict | None = None) -> dict:
        return self.call("editor", action, args)

    def editor(self) -> EditorController:
        return self.studio.controllers.get("editor")

    def set_json(self, text: str, base: int) -> dict:
        return self.act("set_json", {"text": text, "base": base})

    def wait_until(self, done, seconds: float = 5.0) -> None:
        deadline = time.monotonic() + seconds
        while not done() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(done(), "the background action did not finish")

    def next_event(self, sub, name: str, seconds: float = 5.0) -> dict:
        """The next event called ``name`` on this stream, skipping the others."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            item = sub.take(0.1)
            if item is not None and item[0] == name:
                return item[1]
        self.fail(f"no {name} event arrived")

    def copy_and_load_through_catalog(self, request: dict) -> dict:
        """The user's path: Copy from Prompt Editor, empty the editor, Load into Prompt Editor."""
        self.editor().set_payload(request)
        added = self.call("catalog", "add", {"name": "kept prompt", "description": ""})
        entry_id = added["state"]["rows"][0]["id"]
        self.editor().set_payload(editor_page.empty_payload())
        return self.call("catalog", "load", {"id": entry_id})

    # -- the view

    def test_the_view_reads_state_and_writes_nothing(self) -> None:
        self.set_json(json.dumps(klein()), self.editor().rev)
        before = self.editor().state()
        for _ in range(3):
            self.engine.page("editor")
        self.assertEqual(self.editor().state(), before)

    def test_the_view_carries_the_fields_the_page_draws(self) -> None:
        state = self.engine.page("editor")["state"]
        self.assertEqual(set(state), {"json", "positive", "negative", "status", "errors", "graph", "rev"})
        self.assertIsInstance(state["rev"], int)
        self.assertEqual(set(state["status"]), {"text", "level"})
        self.assertIsInstance(state["errors"], list)
        self.assertEqual(state["graph"]["nodes"], [])
        self.assertEqual(state["graph"]["edges"], [])
        json.loads(state["json"])

    def test_a_valid_edit_lays_out_the_graph_and_fills_the_boxes(self) -> None:
        state = self.set_json(json.dumps(klein()), self.editor().rev)["state"]
        self.assertEqual(state["positive"], "a watercolour portrait")
        self.assertEqual(state["negative"], "blurry")
        self.assertEqual(state["status"], {"text": "JSON valid", "level": "info"})
        self.assertEqual({n["id"] for n in state["graph"]["nodes"]}, set(klein()["prompt"]))
        self.assertEqual(sorted((e["source"], e["target"], e["target_key"]) for e in state["graph"]["edges"]),
                         edges_of(klein()))
        node = next(n for n in state["graph"]["nodes"]
                    if n["class"] == "CLIPTextEncode" and "negative" in n["title"].lower())
        self.assertEqual(node["note"], "blurry")
        self.assertEqual(set(node["rect"]), {"x", "y", "w", "h"})
        self.assertTrue(node["ports"])
        self.assertTrue(node["rows"])
        edge = next(e for e in state["graph"]["edges"]
                    if e["source"] == text_encode_id(klein()["prompt"], "blurry") and e["target"] == "63")
        self.assertEqual(edge["target_key"], "negative")
        self.assertEqual(set(edge), {"source", "source_key", "target", "target_key", "color"})
        self.assertTrue(edge["color"].startswith("#"))

    def test_broken_json_is_kept_and_reported(self) -> None:
        state = self.set_json('{"prompt": {nope}}', self.editor().rev)["state"]
        self.assertEqual(state["json"], '{"prompt": {nope}}')
        self.assertEqual(len(state["errors"]), 1)
        self.assertIn("line 1", state["errors"][0])

    def test_validate_reports_broken_json_in_the_status(self) -> None:
        self.set_json("{", self.editor().rev)
        state = self.act("validate")["state"]
        self.assertEqual(state["status"]["level"], "error")
        self.assertIn("line 1", state["status"]["text"])

    def test_typing_a_prompt_keeps_every_card_where_it_was(self) -> None:
        self.set_json(json.dumps(klein()), self.editor().rev)
        first = self.engine.page("editor")["state"]["graph"]["nodes"]
        reply = self.set_json(json.dumps(klein(negative="blurry, dark")), self.editor().rev)
        self.assertEqual([n["rect"] for n in reply["state"]["graph"]["nodes"]], [n["rect"] for n in first])

    # -- one revision guards every late write

    def test_a_stale_keystroke_is_ignored(self) -> None:
        stale = self.set_json(json.dumps(klein()), self.editor().rev)
        self.copy_and_load_through_catalog(klein("from an import"))
        late = self.set_json(json.dumps(klein()), stale["state"]["rev"])
        self.assertEqual(late["state"]["positive"], "from an import")
        self.assertEqual(late["state"]["status"]["level"], "warn")

    def test_typing_the_same_text_again_is_taken_and_keeps_the_view(self) -> None:
        first = self.set_json(json.dumps(klein()), self.editor().rev)["state"]
        again = self.set_json(json.dumps(klein()), first["rev"])["state"]
        self.assertEqual(again["graph"]["nodes"], first["graph"]["nodes"])
        self.assertEqual(again["status"]["level"], "info")

    # -- the editor is shared state

    def test_another_page_loading_into_the_editor_shows_in_the_editor_view(self) -> None:
        loaded = self.copy_and_load_through_catalog(klein("from the catalog"))
        self.assertIn({"kind": "navigate", "page": "editor"}, loaded["effects"])
        view = self.engine.page("editor")["state"]
        self.assertEqual(view["positive"], "from the catalog")
        self.assertEqual(json.loads(view["json"]), klein("from the catalog"))
        self.assertEqual({n["id"] for n in view["graph"]["nodes"]}, set(klein()["prompt"]))

    def test_rebuilding_from_config_works_and_answers_when_it_lands(self) -> None:
        self.set_json(json.dumps(klein()), self.editor().rev)
        sub = self.hub.subscribe()
        reply = self.act("rebuild_from_config")
        self.assertTrue(reply["pending"], "the rebuild answers at once and finishes through action_done")
        done = self.next_event(sub, "action_done")
        self.assertEqual(done["id"], reply["id"])
        self.assertFalse(done["reply"]["pending"])
        self.assertEqual(done["reply"]["state"]["positive"], "")
        self.assertEqual(done["reply"]["shell"]["note"],
                         {"text": "Rebuilt the request from Prompt Settings", "level": "ok"})
        view = self.engine.page("editor")["state"]
        self.assertEqual((view["positive"], view["negative"]), ("", ""))
        self.assertEqual({n["id"] for n in view["graph"]["nodes"]}, set(klein()["prompt"]))
        self.assertEqual(self.studio.note_line.text, "Rebuilt the request from Prompt Settings")

    def test_a_refused_rebuild_names_the_knob_and_leaves_the_editor_alone(self) -> None:
        before = self.set_json(json.dumps(klein()), self.editor().rev)["state"]
        self.studio.form.width = "wide"
        reply = self.act("rebuild_from_config")
        self.assertFalse(reply["pending"])
        self.assertEqual(reply["state"]["status"]["level"], "warn")
        self.assertIn("Width", reply["state"]["status"]["text"])
        self.assertEqual(reply["state"]["json"], before["json"])

    # -- prompts

    def test_a_prompt_edit_patches_the_json_and_keeps_the_view(self) -> None:
        self.set_json(json.dumps(klein()), self.editor().rev)
        before = self.engine.page("editor")["state"]["graph"]["nodes"]
        state = self.act("set_prompt", {"positive": "a sharper portrait", "negative": "soft"})["state"]
        prompt = json.loads(state["json"])["prompt"]
        self.assertEqual((state["positive"], state["negative"]), ("a sharper portrait", "soft"))
        self.assertEqual(editor_page.prompt_texts(prompt), ("a sharper portrait", "soft"))
        self.assertIn("convert_output", json.loads(state["json"]))
        self.assertEqual([n["rect"] for n in state["graph"]["nodes"]], [n["rect"] for n in before])

    def test_a_prompt_edit_while_the_json_is_broken_is_refused(self) -> None:
        self.set_json("{", self.editor().rev)
        state = self.act("set_prompt", {"positive": "x", "negative": ""})["state"]
        self.assertEqual(state["json"], "{")
        self.assertTrue(state["errors"])

    # -- validation, as a list of lines

    def test_validate_answers_with_one_line_per_problem(self) -> None:
        state = self.act("validate")["state"]
        self.assertEqual(state["status"]["level"], "error")
        self.assertTrue(state["errors"])
        self.assertEqual(state["status"]["text"].split("\n"), state["errors"])

    def test_validate_passes_a_klein_request(self) -> None:
        self.set_json(json.dumps(klein()), self.editor().rev)
        state = self.act("validate")["state"]
        self.assertEqual(state["errors"], [])
        self.assertEqual(state["status"], {"text": "JSON valid", "level": "info"})

    # -- refused edits

    def test_move_node_to_an_unknown_id_is_refused_and_changes_nothing(self) -> None:
        before = self.set_json(json.dumps(klein()), self.editor().rev)["state"]
        status, reply = self.engine.handle(
            {"page": "editor", "action": "move_node", "args": {"id": "nope", "x": 1.0, "y": 2.0}})
        self.assertEqual(status, 200)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["errorDetail"]["kind"], "refused")
        self.assertEqual(reply["state"], before)

    def test_set_json_without_a_base_revision_is_refused_at_the_boundary(self) -> None:
        before = self.editor().state()
        status, reply = self.engine.handle({"page": "editor", "action": "set_json", "args": {"text": "{}"}})
        self.assertEqual(status, 200)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["errorDetail"]["kind"], "bad_payload")
        self.assertEqual(self.editor().state(), before)

    def test_swap_with_fewer_than_two_selected_is_refused_and_says_why(self) -> None:
        before = self.set_json(json.dumps(klein()), self.editor().rev)["state"]
        state = self.act("swap_selected")["state"]
        self.assertEqual(state["status"], {"text": "Select two nodes first.", "level": "warn"})
        self.assertEqual(state["json"], before["json"])

    def test_swap_exchanges_the_two_text_encodes_and_clears_the_selection(self) -> None:
        self.set_json(json.dumps(klein()), self.editor().rev)
        prompt = json.loads(self.editor().state()["json"])["prompt"]
        pair = (text_encode_id(prompt, "a watercolour portrait"), text_encode_id(prompt, "blurry"))
        self.editor().model = self.editor().model.with_selection(pair)
        state = self.act("swap_selected")["state"]
        self.assertEqual((state["positive"], state["negative"]), ("blurry", "a watercolour portrait"))
        self.assertEqual(state["status"]["level"], "info")
        self.assertFalse(any(n["selected"] for n in state["graph"]["nodes"]))

    # -- the view position

    def test_move_node_moves_the_card_and_leaves_the_json_alone(self) -> None:
        before = self.set_json(json.dumps(klein()), self.editor().rev)["state"]
        node_id = text_encode_id(json.loads(before["json"])["prompt"], "blurry")
        state = self.act("move_node", {"id": node_id, "x": 40.0, "y": 900.0})["state"]
        self.assertEqual(state["json"], before["json"])
        node = next(n for n in state["graph"]["nodes"] if n["id"] == node_id)
        self.assertEqual((node["rect"]["x"], node["rect"]["y"]), (40.0, 900.0))
        self.assertGreater(state["rev"], before["rev"])

    def test_rebuild_from_json_puts_the_cards_back(self) -> None:
        before = self.set_json(json.dumps(klein()), self.editor().rev)["state"]
        node_id = text_encode_id(json.loads(before["json"])["prompt"], "blurry")
        self.act("move_node", {"id": node_id, "x": 40.0, "y": 900.0})
        state = self.act("rebuild_from_json")["state"]
        node = next(n for n in state["graph"]["nodes"] if n["id"] == node_id)
        self.assertNotEqual(node["rect"]["y"], 900.0)
        self.assertIn("Rebuilt", state["status"]["text"])
        self.assertEqual(state["status"]["level"], "info")


if __name__ == "__main__":
    unittest.main()
