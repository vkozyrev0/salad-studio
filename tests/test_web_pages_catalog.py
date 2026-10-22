"""Prompt Catalog as a controller: its view, its writes, and what it refuses.

Every call goes through the action table, with a context built by hand, so the
tests see exactly what the engine would return. A stub Editor stands in for
the editor controller, which is another page's file.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import prompt_catalog  # noqa: E402
from salad_studio.web.pages import CatalogController  # noqa: E402
from salad_studio.web.registry import ActionContext, Controllers  # noqa: E402

REQUEST = {"prompt": {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "klein.safetensors"}}}}


class StubEditor:
    """The two methods Catalog uses: the JSON as typed, and a whole request replaced."""

    def __init__(self, body: dict[str, Any] | None) -> None:
        self.body = body
        self.loaded: dict[str, Any] | None = None

    def text(self) -> str:
        return "not json" if self.body is None else json.dumps(self.body)

    def set_payload(self, body: dict[str, Any]) -> None:
        self.loaded = body
        self.body = body


class StubStudio:
    def __init__(self) -> None:
        self.editor: StubEditor | None = None
        self.controllers = None
        self.confirms: dict[str, tuple[str, str, dict[str, Any]]] = {}

    def issue_confirm(self, page: str, action: str, args: dict[str, Any]) -> str:
        token = f"c_{len(self.confirms)}"
        self.confirms[token] = (page, action, dict(args))
        return token


class CatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = prompt_catalog.CATALOG_PATH
        prompt_catalog.CATALOG_PATH = Path(self.tmp.name) / "studio-prompt-catalog.json"
        self.stub = StubStudio()
        self.stub.controllers = _ControllersWithEditor(self.stub)
        self.controller = CatalogController(self.stub)
        table = Controllers(self.stub).table
        self.controller.register(table)
        self.table = table

    def tearDown(self) -> None:
        prompt_catalog.CATALOG_PATH = self.saved
        self.tmp.cleanup()

    def call(self, action: str, args: dict[str, Any] | None = None, *, confirmed: bool = False) -> Any:
        self.ctx = ActionContext(self.stub, "catalog", action, dict(args or {}), confirmed=confirmed)
        result = self.table.call(f"catalog.{action}", dict(args or {}), ctx=self.ctx)
        self.assertIsNone(result.error, result.error)
        return result.data

    def add_one(self, name: str = "Portrait", description: str = "a face") -> dict[str, Any]:
        """Add through the action, then answer with the entry as the store now holds it."""
        self.stub.editor = StubEditor(REQUEST)
        self.call("add", {"name": name, "description": description})
        newest = self.call("view")["rows"][0]["id"]
        return prompt_catalog.get_entry(newest)

    def test_the_view_lists_the_columns_and_the_headers_cells(self) -> None:
        self.assertEqual(self.call("view")["columns"],
                         ["Added", "Short name", "Description", "Prompt", "Graph"])
        entry = self.add_one()
        state = self.call("view")
        self.assertEqual(len(state["rows"]), 1)
        row = state["rows"][0]
        self.assertEqual(row["id"], entry["id"])
        self.assertEqual(row["cells"][1], "Portrait")
        self.assertEqual(row["cells"][2], "a face")
        self.assertIn("nodes", row["cells"][4])
        self.assertEqual(state["empty"], "")

    def test_an_empty_catalog_names_what_to_do(self) -> None:
        state = self.call("view")
        self.assertEqual(state["rows"], [])
        self.assertIn("No kept prompts yet", state["empty"])

    def test_add_copies_the_editor_json_under_the_name(self) -> None:
        self.stub.editor = StubEditor(REQUEST)
        state = self.call("add", {"name": "Portrait", "description": "a face"})
        entry = prompt_catalog.find_by_name("Portrait")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["request"]["prompt"], REQUEST["prompt"])
        self.assertEqual(state["status"], "Copied 'Portrait' from the Prompt Editor")
        self.assertEqual(self.ctx.note_text, ("Catalog: added Portrait", "ok"))
        self.assertEqual([row["name"] for row in state["rows"]], ["Portrait"])

    def test_add_without_a_name_asks_and_writes_nothing(self) -> None:
        self.stub.editor = StubEditor(REQUEST)
        self.call("add", {"name": "  "})
        self.assertEqual(self.ctx.effects[0]["body"], "Give the prompt a short name first.")
        self.assertEqual(prompt_catalog.list_entries(), [])

    def test_save_meta_renames_the_selected_entry(self) -> None:
        entry = self.add_one()
        state = self.call("save_meta", {"id": entry["id"], "name": "Profile", "description": "new words"})
        saved = prompt_catalog.get_entry(entry["id"])
        self.assertEqual((saved["name"], saved["description"]), ("Profile", "new words"))
        self.assertEqual(state["status"], "Saved 'Profile'")
        self.assertEqual(self.ctx.note_text, ("Saved 'Profile'", "ok"))

    def test_save_meta_refuses_to_take_another_entry_name(self) -> None:
        self.add_one("Portrait")
        other = self.add_one("Landscape")
        self.call("save_meta", {"id": other["id"], "name": "Portrait", "description": ""})
        dialog = self.ctx.effects[0]
        self.assertEqual(dialog["level"], "error")
        self.assertIn("already a catalog entry", dialog["body"])
        self.assertEqual(prompt_catalog.get_entry(other["id"])["name"], "Landscape")

    def test_delete_asks_first_and_the_yes_removes_that_entry(self) -> None:
        portrait = self.add_one("Portrait")
        self.add_one("Landscape")
        state = self.call("delete", {"id": portrait["id"]})
        self.assertEqual(len(prompt_catalog.list_entries()), 2, "the ask wrote nothing")
        effect = self.ctx.effects[0]
        self.assertEqual(effect["kind"], "confirm")
        self.assertIn("'Portrait'", effect["body"])
        self.assertEqual(sorted(row["name"] for row in state["rows"]), ["Landscape", "Portrait"])
        page, action, args = self.stub.confirms[effect["token"]]
        self.assertEqual((page, action, args), ("catalog", "delete", {"id": portrait["id"]}))
        done = self.call(action, args, confirmed=True)
        self.assertIsNone(prompt_catalog.find_by_name("Portrait"))
        self.assertEqual(self.ctx.note_text, ("Deleted 'Portrait'", "ok"))
        self.assertEqual([row["name"] for row in done["rows"]], ["Landscape"])

    def test_load_puts_the_entry_json_in_the_editor_and_opens_it(self) -> None:
        entry = self.add_one()
        self.stub.editor = StubEditor(None)
        state = self.call("load", {"id": entry["id"]})
        self.assertEqual(self.stub.editor.loaded, REQUEST)
        self.assertEqual(self.ctx.effects, [{"kind": "navigate", "page": "editor"}])
        self.assertEqual(state["status"], "Loaded 'Portrait' into the Prompt Editor")

    def test_update_json_replaces_the_entry_with_the_editor_json(self) -> None:
        entry = self.add_one()
        newer = {"prompt": {"7": {"class_type": "KSampler", "inputs": {}}}}
        self.stub.editor = StubEditor(newer)
        self.call("update_json", {"id": entry["id"]})
        self.assertEqual(prompt_catalog.get_entry(entry["id"])["request"]["prompt"], newer["prompt"])
        self.assertEqual(self.ctx.note_text, ("Updated the JSON of 'Portrait'", "ok"))

    def test_an_invalid_editor_json_is_a_dialog_not_a_write(self) -> None:
        entry = self.add_one()
        self.stub.editor = StubEditor(None)
        self.call("update_json", {"id": entry["id"]})
        self.assertEqual(self.ctx.effects[0]["level"], "error")
        self.assertIn("Prompt Editor JSON is invalid", self.ctx.effects[0]["body"])
        self.assertEqual(prompt_catalog.get_entry(entry["id"])["request"], REQUEST)

    def test_an_unknown_entry_is_refused_with_a_dialog(self) -> None:
        state = self.call("save_meta", {"id": "gone", "name": "x", "description": ""})
        self.assertEqual(self.ctx.effects[0]["body"], "Select a catalog entry first.")
        self.assertEqual(state["rows"], [])

    def test_an_action_missing_its_id_is_refused_and_reads_nothing(self) -> None:
        result = self.table.call("catalog.load", {}, ctx=ActionContext(self.stub, "catalog", "load", {}))
        self.assertEqual(result.error.kind, "refused")
        self.assertEqual(result.error.message, "id is required")

    def test_a_name_that_is_not_text_is_refused(self) -> None:
        self.stub.editor = StubEditor(REQUEST)
        result = self.table.call("catalog.add", {"name": 7}, ctx=ActionContext(self.stub, "catalog", "add", {}))
        self.assertEqual(result.error.kind, "refused")
        self.assertEqual(prompt_catalog.list_entries(), [])


class _ControllersWithEditor:
    def __init__(self, studio: StubStudio) -> None:
        self.studio = studio

    def get(self, page_id: str) -> Any:
        return self.studio.editor if page_id == "editor" else None


if __name__ == "__main__":
    unittest.main()
