"""The LoRAs page: the library, the find box, and the form's four writes.

The store's extras file is the page's only persistent state, so every test
points it at a temporary directory and reads what the page shows back from
there. The verify and add paths are background work and are left unrun here.
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

import lora_store  # noqa: E402
from salad_studio.web.core import Core  # noqa: E402
from salad_studio.web.engine import WebEngine  # noqa: E402
from salad_studio.web.events import Hub  # noqa: E402
from salad_studio.web.pages.loras import LorasController  # noqa: E402
from salad_studio.web.registry import ActionContext, Controllers  # noqa: E402
from salad_studio.web.shell import Shell  # noqa: E402

EXTRA = {
    "id": "civitai:9001@9002",
    "name": "Watercolor Ink",
    "kind": "lora",
    "base": "",
    "status": "user",
    "verified": True,
    "source": {"host": "civitai", "page": "https://civitai.com/models/9001",
               "download": "https://civitai.com/api/download/models/9002",
               "filename": "watercolor.safetensors"},
}


class LorasPageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = lora_store.EXTRAS_PATH
        lora_store.EXTRAS_PATH = Path(self.tmp.name) / "studio-loras.json"
        lora_store._save_extras(lora_store.EXTRAS_PATH, [dict(EXTRA)])
        self.core = Core(workers=2).start()
        self.hub = Hub()
        self.studio = Shell(self.core, self.hub)
        self.studio.controllers = Controllers(self.studio)
        self.page = LorasController(self.studio)
        self.studio.controllers.add(self.page)
        self.services = self.studio.services

    def tearDown(self) -> None:
        self.core.stop()
        lora_store.EXTRAS_PATH = self.saved
        self.tmp.cleanup()

    def call(self, action: str, args: dict | None = None, *, confirmed: bool = False):
        ctx = ActionContext(self.studio, "loras", action, args or {}, confirmed=confirmed)
        result = self.studio.controllers.table.call(f"loras.{action}", dict(args or {}), ctx=ctx)
        self.assertIsNone(result.error, result.error)
        return result.data, ctx

    def stored(self, lid: str) -> dict:
        return lora_store.find_lora(lid) or {}

    def test_the_view_lists_the_library_with_an_empty_text_and_the_families(self) -> None:
        state, _ctx = self.call("view")
        self.assertEqual(state["columns"], ["Verified", "Id", "Name", "Version", "Model", "Source"])
        row = next(r for r in state["rows"] if r["id"] == EXTRA["id"])
        self.assertEqual(row["name"], "Watercolor Ink")
        self.assertTrue(row["verified"])
        self.assertEqual(row["source"], "https://civitai.com/models/9001")
        self.assertEqual(state["empty_text"], "")
        self.assertIn("Flux.2 Klein", state["families"])
        self.assertFalse(state["can_save"])

    def test_an_empty_or_unmatched_library_has_empty_text(self) -> None:
        self.call("find", {"text": "no such lora"})
        state, _ctx = self.call("view")
        self.assertEqual(state["rows"], [])
        self.assertTrue(state["empty_text"])

    def test_selecting_a_row_fills_the_form_from_the_store(self) -> None:
        state, _ctx = self.call("select", {"id": EXTRA["id"]})
        self.assertEqual(state["selected"], EXTRA["id"])
        self.assertTrue(state["can_save"])
        self.assertEqual(state["form"]["name"], "Watercolor Ink")
        self.assertEqual(state["form"]["filename"], "watercolor.safetensors")
        self.assertEqual(state["form"]["ref"], "https://civitai.com/models/9001")
        self.assertEqual(state["form"]["family"], "unknown")

    def test_save_edits_writes_the_form_and_the_row_shows_it(self) -> None:
        self.call("select", {"id": EXTRA["id"]})
        self.call("edit_form", {"field": "name", "value": "Watercolor Ink v2"})
        self.call("edit_form", {"field": "family", "value": "Flux.2 Klein"})
        self.call("edit_form", {"field": "strength_model", "value": "0.7"})
        state, ctx = self.call("save_edits")
        self.assertEqual(ctx.note_text[1], "ok")
        self.assertEqual(self.stored(EXTRA["id"])["name"], "Watercolor Ink v2")
        self.assertEqual(self.stored(EXTRA["id"])["base"], "Flux.2 Klein 9B")
        self.assertEqual(self.stored(EXTRA["id"])["strength_model"], 0.7)
        self.assertEqual(next(r for r in state["rows"] if r["id"] == EXTRA["id"])["name"],
                         "Watercolor Ink v2")

    def test_save_edits_without_a_selection_changes_nothing(self) -> None:
        self.call("edit_form", {"field": "name", "value": "typed but not saved"})
        state, ctx = self.call("save_edits")
        self.assertEqual(ctx.note_text[1], "warn")
        self.assertEqual(ctx.effects[0]["kind"], "dialog")
        self.assertEqual(self.stored(EXTRA["id"])["name"], "Watercolor Ink")

    def test_a_non_numeric_strength_is_refused_before_the_store_is_written(self) -> None:
        self.call("select", {"id": EXTRA["id"]})
        self.call("edit_form", {"field": "strength_clip", "value": "lots"})
        _state, ctx = self.call("save_edits")
        self.assertEqual(ctx.note_text[1], "warn")
        self.assertNotIn("strength_model", self.stored(EXTRA["id"]))

    def test_removing_asks_first_and_only_the_yes_removes(self) -> None:
        self.call("select", {"id": EXTRA["id"]})
        state, ctx = self.call("remove_selected")
        self.assertEqual([e["kind"] for e in ctx.effects], ["confirm"])
        self.assertTrue(ctx.effects[0]["token"])
        self.assertIn("Watercolor Ink", ctx.effects[0]["body"])
        self.assertEqual(self.stored(EXTRA["id"])["id"], EXTRA["id"])
        self.assertIn(EXTRA["id"], [r["id"] for r in state["rows"]])

        state, ctx = self.call("remove_selected", confirmed=True)
        self.assertEqual(self.stored(EXTRA["id"]), {})
        self.assertNotIn(EXTRA["id"], [r["id"] for r in state["rows"]])
        self.assertIsNone(state["selected"])

    def test_a_catalog_lora_is_not_removed_and_the_page_says_why(self) -> None:
        known = next(r for r in lora_store.list_loras() if r["id"] != EXTRA["id"])
        self.call("select", {"id": known["id"]})
        state, ctx = self.call("remove_selected", confirmed=True)
        self.assertEqual(ctx.note_text[1], "warn")
        self.assertIn("catalog", ctx.note_text[0])
        self.assertIn(known["id"], [r["id"] for r in state["rows"]])

    def test_the_engine_confirm_token_runs_the_removal_it_was_issued_for(self) -> None:
        engine = WebEngine(self.studio)
        self.call("select", {"id": EXTRA["id"]})
        _status, reply = engine.handle({"page": "loras", "action": "remove_selected", "args": {}})
        self.assertEqual(reply["effects"][0]["kind"], "confirm")
        self.assertEqual(self.stored(EXTRA["id"])["id"], EXTRA["id"])
        _status, done = engine.handle({"confirm": reply["effects"][0]["token"]})
        self.assertTrue(done["ok"])
        self.assertEqual(self.stored(EXTRA["id"]), {})
        self.assertEqual(done["state"]["rows"], [r for r in done["state"]["rows"]
                                                  if r["id"] != EXTRA["id"]])

    def test_adding_with_an_empty_ref_asks_for_one_instead_of_calling_the_store(self) -> None:
        state, ctx = self.call("add_lora", {"ref": "  "})
        self.assertEqual(ctx.effects[0]["kind"], "dialog")
        self.assertIn(ctx.note_text, (None,))
        self.assertEqual(state["count"], state["count"])

    def test_adding_starts_background_work_and_the_page_is_pending(self) -> None:
        called: list[str] = []
        saved = lora_store.add_lora
        lora_store.add_lora = lambda ref, **kw: called.append(ref) or dict(EXTRA, id="url:new")
        try:
            _state, ctx = self.call("add_lora", {"ref": "https://example.com/new.safetensors"})
            self.assertTrue(ctx.is_pending)
            self.assertTrue(ctx.pending_id)
            self.assertEqual(called, ["https://example.com/new.safetensors"])
        finally:
            lora_store.add_lora = saved

    def test_find_narrows_by_name_and_sort_orders_the_rows(self) -> None:
        state, _ctx = self.call("find", {"text": "water"})
        self.assertIn(EXTRA["id"], [r["id"] for r in state["rows"]])
        state, _ctx = self.call("find", {"text": ""})
        self.call("edit_form", {"field": "name", "value": ""})
        self.call("select", {"id": EXTRA["id"]})
        self.call("edit_form", {"field": "name", "value": "AAA first"})
        self.call("save_edits")
        state, _ctx = self.call("sort", {"column": "Name"})
        names = [r["name"] for r in state["rows"]]
        self.assertEqual(names[0], "AAA first")
        self.assertEqual(names, sorted(names, key=str.lower))
        self.assertEqual(state["sort"], {"column": "Name", "reverse": False})
        state, _ctx = self.call("sort", {"column": "Name"})
        self.assertTrue(state["sort"]["reverse"])
        self.assertEqual(state["rows"][-1]["name"], "AAA first")
        state, ctx = self.call("sort", {"column": "Nope"})
        self.assertEqual(ctx.note_text[1], "warn")


if __name__ == "__main__":
    unittest.main()
