"""The Prompt History page: a row per request, its rating, and the one-row body.

The list must stay small, so the state never carries a row's request JSON and
fetches it only through ``history.body``. A row is addressed by its timestamp,
which is what keeps a delete safe while a render adds a row above it.
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

import prompt_history  # noqa: E402
from salad_studio import prompt_history as pkg_history  # noqa: E402
from salad_studio.web.core import Core  # noqa: E402
from salad_studio.web.engine import WebEngine  # noqa: E402
from salad_studio.web.events import Hub  # noqa: E402
from salad_studio.web.pages.editor import EditorController  # noqa: E402
from salad_studio.web.pages.history import HistoryController  # noqa: E402
from salad_studio.web.registry import ActionContext, Controllers  # noqa: E402
from salad_studio.web.shell import Shell  # noqa: E402


class Recalled:
    """The editor's own controller, built over the same studio, so Reuse is
    judged by what the editor then shows and not by a stand-in that cannot
    fail. ``calls`` records what reached it."""

    def __init__(self, studio) -> None:
        self.editor = EditorController(studio)
        self.calls: list[tuple] = []
        original = self.editor.recall

        def recall(payload, *, ctx=None):
            self.calls.append((payload.get("request"), payload.get("text")))
            return original(payload, ctx=ctx)

        self.editor.recall = recall

    @property
    def positive(self) -> str:
        return self.editor.positive

    @property
    def nodes(self) -> int:
        return len(self.editor.model.nodes)


def request(text: str) -> dict:
    return {"prompt": {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": text}}},
            "big": "x" * 6000}


class HistoryPageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.saved = [(m, m.HISTORY_PATH, m.THUMBS_DIR) for m in (prompt_history, pkg_history)]
        for module, _hist, _thumbs in self.saved:
            module.HISTORY_PATH = root / "studio-prompt-history.json"
            module.THUMBS_DIR = root / "studio-prompt-thumbs"
        self.older = {"text": "an older prompt", "ts": 1_700_000_000}
        self.newer = {"text": "a newer prompt", "request": request("a newer prompt"),
                      "ts": 1_700_000_100, "rating": 3, "image": str(root / "gone.jpg")}
        prompt_history._save([self.newer, self.older])
        self.core = Core(workers=2).start()
        self.hub = Hub()
        self.studio = Shell(self.core, self.hub)
        self.studio.controllers = Controllers(self.studio)
        self.page = HistoryController(self.studio)
        self.studio.controllers.add(self.page)
        self.editor = Recalled(self.studio)
        self.studio.controllers.add(self.editor.editor)

    def tearDown(self) -> None:
        self.core.stop()
        for module, hist, thumbs in self.saved:
            module.HISTORY_PATH = hist
            module.THUMBS_DIR = thumbs
        self.tmp.cleanup()

    def call(self, action: str, args: dict | None = None, *, confirmed: bool = False):
        ctx = ActionContext(self.studio, "history", action, args or {}, confirmed=confirmed)
        result = self.studio.controllers.table.call(f"history.{action}", dict(args or {}), ctx=ctx)
        self.assertIsNone(result.error, result.error)
        return result.data, ctx

    def row(self, state: dict, ts: int) -> dict:
        return next(r for r in state["rows"] if r["ts"] == ts)

    def test_a_row_carries_its_prompt_graph_id_and_rating_but_never_its_request(self) -> None:
        state, _ctx = self.call("view")
        self.assertEqual(state["columns"], ["When", "Prompt", "Graph", "Rating", "Image"])
        self.assertEqual(state["count"], 2)
        row = self.row(state, self.newer["ts"])
        self.assertEqual(row["id"], str(self.newer["ts"]))
        self.assertEqual(row["prompt"], "a newer prompt")
        self.assertIn("1 nodes", row["graph"])
        self.assertEqual(row["rating"], 3)
        self.assertNotIn("request", row)
        for r in state["rows"]:
            self.assertNotIn("x" * 100, repr(r))

    def test_a_missing_thumbnail_is_left_out_and_a_present_one_is_a_url(self) -> None:
        thumb = Path(self.tmp.name) / "thumb-42.jpg"
        thumb.write_bytes(b"jpeg bytes")
        rows = prompt_history.list_prompts()
        rows[0]["image"] = str(thumb)
        prompt_history._save(rows)
        state, _ctx = self.call("view")
        self.assertEqual(self.row(state, self.newer["ts"])["image"], "/api/thumbs/thumb-42.jpg")
        self.assertEqual(self.row(state, self.older["ts"])["image"], "")

    def test_an_empty_history_says_so(self) -> None:
        prompt_history._save([])
        state, _ctx = self.call("view")
        self.assertEqual(state["rows"], [])
        self.assertTrue(state["empty_text"])

    def test_body_returns_the_one_request_the_editor_asks_for(self) -> None:
        state, ctx = self.call("body", {"id": str(self.newer["ts"])})
        self.assertEqual(ctx.note_text[1], "ok")
        self.assertEqual(self.editor.calls, [(request("a newer prompt"), "a newer prompt")])
        self.assertEqual(state["count"], 2)

    def test_rating_is_a_number_and_the_store_keeps_it(self) -> None:
        self.call("select", {"id": str(self.older["ts"])})
        state, ctx = self.call("rate", {"stars": 4})
        self.assertEqual(self.row(state, self.older["ts"])["rating"], 4)
        self.assertEqual(prompt_history.list_prompts()[1]["rating"], 4)
        self.assertEqual(ctx.note_text[1], "info")
        state, _ctx = self.call("rate", {"stars": 0})
        self.assertEqual(self.row(state, self.older["ts"])["rating"], 0)
        self.assertEqual(prompt_history.rating_of(prompt_history.list_prompts()[1]), 0)

    def test_rating_without_a_selection_changes_nothing(self) -> None:
        _state, ctx = self.call("rate", {"stars": 5})
        self.assertEqual(ctx.note_text[1], "warn")
        self.assertEqual(prompt_history.list_prompts()[0]["rating"], 3)

    def test_reuse_navigates_to_the_editor_with_the_selected_request(self) -> None:
        self.call("select", {"id": str(self.newer["ts"])})
        _state, ctx = self.call("reuse")
        self.assertIn({"kind": "navigate", "page": "editor"}, ctx.effects)
        self.assertEqual(self.editor.calls, [(request("a newer prompt"), "a newer prompt")])
        self.assertEqual(self.editor.positive, "a newer prompt", "the editor shows the saved prompt")

    def test_reuse_keeps_the_two_entries_saved_in_one_second_apart(self) -> None:
        """Two rows can share a timestamp. Each id must still name one entry."""
        twin = {"text": "a second in the same second", "ts": self.newer["ts"],
                "request": request("a second in the same second")}
        prompt_history._save([twin, self.newer, self.older])
        state, _ctx = self.call("view")
        ids = [row["id"] for row in state["rows"]]
        self.assertEqual(len(ids), len(set(ids)), f"two rows share an id: {ids}")
        self.assertEqual(ids[0], str(self.newer["ts"]), "the newest row keeps the plain timestamp")

        self.call("select", {"id": ids[0]})
        self.call("reuse")
        self.assertEqual(self.editor.positive, "a second in the same second")

        self.call("select", {"id": ids[1]})
        self.call("reuse")
        self.assertEqual(self.editor.positive, "a newer prompt", "the older twin is its own row")

    def test_reuse_of_a_bare_prompt_rebuilds_a_request_around_the_text(self) -> None:
        """A bare prompt has no JSON to patch, so the editor builds one from the form."""
        self.call("select", {"id": str(self.older["ts"])})
        self.call("reuse")
        self.assertEqual(self.editor.positive, "an older prompt")
        self.assertGreater(self.editor.nodes, 1, "the text needs a whole request around it")

    def test_reuse_without_a_selection_asks_for_one(self) -> None:
        _state, ctx = self.call("reuse")
        self.assertEqual(ctx.effects[0]["kind"], "dialog")
        self.assertEqual(self.editor.calls, [])

    def test_delete_asks_first_and_the_yes_removes_the_row_it_was_issued_for(self) -> None:
        self.call("select", {"id": str(self.newer["ts"])})
        _state, ctx = self.call("delete")
        self.assertEqual([e["kind"] for e in ctx.effects], ["confirm"])
        self.assertEqual(len(prompt_history.list_prompts()), 2)

        engine = WebEngine(self.studio)
        _status, done = engine.handle({"confirm": ctx.effects[0]["token"]})
        self.assertTrue(done["ok"])
        self.assertEqual([r["ts"] for r in done["state"]["rows"]], [self.older["ts"]])
        self.assertIsNone(done["state"]["selected"])

    def test_a_row_added_above_the_selection_does_not_move_the_delete(self) -> None:
        self.call("select", {"id": str(self.older["ts"])})
        added = prompt_history.add_prompt("a prompt typed after the selection")
        self.assertIsNotNone(added)
        self.call("delete", confirmed=True)
        self.assertEqual([r["text"] for r in prompt_history.list_prompts()],
                         ["a prompt typed after the selection", "a newer prompt"])

    def test_a_selection_that_has_gone_is_refused(self) -> None:
        self.call("select", {"id": str(self.older["ts"])})
        prompt_history.remove_at(1)
        _state, ctx = self.call("delete", confirmed=True)
        self.assertEqual(ctx.note_text[1], "warn")
        self.assertEqual(len(prompt_history.list_prompts()), 1)


if __name__ == "__main__":
    unittest.main()
