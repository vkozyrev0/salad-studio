"""Prompt Catalog store: named, described request JSONs kept on disk."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for p in (str(TOOLS), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from salad_studio import prompt_catalog as pc  # noqa: E402


def _body(text: str) -> dict:
    """A minimal Prompt Editor request body carrying one CLIP prompt."""
    return {
        "prompt": {
            "74": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": text, "clip": ["71", 0]},
            },
            "70": {
                "class_type": "UNETLoader",
                "inputs": {
                    "unet_name": "flux-2-klein-base-9b-fp8.safetensors",
                    "weight_dtype": "default",
                },
            },
            "66": {
                "class_type": "EmptyFlux2LatentImage",
                "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
            },
        },
        "convert_output": {"format": "jpeg"},
    }


class CatalogStore(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self._old = pc.CATALOG_PATH
        self.path = Path(self._td.name) / "studio-prompt-catalog.json"
        pc.CATALOG_PATH = self.path
        self.addCleanup(lambda: setattr(pc, "CATALOG_PATH", self._old))

    def test_missing_and_unreadable_files_read_as_empty(self) -> None:
        self.assertEqual(pc.list_entries(), [])
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(pc.list_entries(), [])
        self.path.write_text('{"items": []}', encoding="utf-8")
        self.assertEqual(pc.list_entries(), [])
        self.path.write_text("[]", encoding="utf-8")
        self.assertEqual(pc.list_entries(), [])

    def test_add_then_read_back_through_disk(self) -> None:
        entry = pc.add_entry("Cover scene", "Overalls, landscape, wordmark", _body("a stool"))
        self.assertTrue(self.path.is_file())
        self.assertEqual(entry["name"], "Cover scene")
        self.assertEqual(entry["description"], "Overalls, landscape, wordmark")
        self.assertTrue(entry["id"])
        # A fresh read (no in-memory state) sees the same entry.
        rows = pc.list_entries()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], entry["id"])
        self.assertEqual(rows[0]["request"], _body("a stool"))
        found = pc.get_entry(entry["id"])
        assert found is not None
        self.assertEqual(found["name"], "Cover scene")
        self.assertEqual(pc.find_by_name("cover SCENE")["id"], entry["id"])

    def test_entries_are_newest_first(self) -> None:
        first = pc.add_entry("one", "", _body("first"))
        second = pc.add_entry("two", "", _body("second"))
        self.assertEqual([r["name"] for r in pc.list_entries()], ["two", "one"])
        # Two entries added in the same second still get distinct ids.
        self.assertNotEqual(first["id"], second["id"])

    def test_short_name_is_required(self) -> None:
        for blank in ("", "   ", "\t"):
            with self.subTest(name=repr(blank)):
                with self.assertRaises(ValueError):
                    pc.add_entry(blank, "d", _body("x"))
        self.assertEqual(pc.list_entries(), [])

    def test_request_needs_a_prompt_object(self) -> None:
        for bad in ({}, {"prompt": []}, {"prompt": "text"}, None):
            with self.subTest(request=repr(bad)):
                with self.assertRaises(ValueError):
                    pc.add_entry("name", "", bad)  # type: ignore[arg-type]
        self.assertEqual(pc.list_entries(), [])

    def test_duplicate_name_is_rejected_and_leaves_the_entry_alone(self) -> None:
        first = pc.add_entry("Cover scene", "original", _body("keep me"))
        with self.assertRaises(ValueError) as ctx:
            pc.add_entry("  cover scene  ", "dupe", _body("other"))
        self.assertIn("already in the catalog", str(ctx.exception))
        rows = pc.list_entries()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], first["id"])
        self.assertEqual(rows[0]["description"], "original")
        self.assertEqual(rows[0]["request"], _body("keep me"))

    def test_update_request_and_metadata(self) -> None:
        entry = pc.add_entry("Cover scene", "d", _body("v1"))
        updated = pc.update_entry(entry["id"], request=_body("v2"))
        self.assertEqual(updated["request"], _body("v2"))
        self.assertEqual(updated["name"], "Cover scene")
        renamed = pc.update_entry(
            entry["id"], name="Cover scene v2", description="second pass"
        )
        self.assertEqual(renamed["name"], "Cover scene v2")
        self.assertEqual(renamed["description"], "second pass")
        self.assertEqual(renamed["request"], _body("v2"))
        on_disk = pc.get_entry(entry["id"])
        assert on_disk is not None
        self.assertEqual(on_disk["name"], "Cover scene v2")
        self.assertEqual(on_disk["request"], _body("v2"))

    def test_update_rejects_unknown_id_and_blank_rename(self) -> None:
        entry = pc.add_entry("Cover scene", "d", _body("v1"))
        with self.assertRaises(ValueError):
            pc.update_entry("no-such-id", description="x")
        with self.assertRaises(ValueError):
            pc.update_entry(entry["id"], name="   ")
        with self.assertRaises(ValueError):
            pc.update_entry(entry["id"], request={"nope": 1})
        still = pc.get_entry(entry["id"])
        assert still is not None
        self.assertEqual(still["name"], "Cover scene")
        self.assertEqual(still["description"], "d")

    def test_update_rename_onto_another_entry_is_rejected(self) -> None:
        one = pc.add_entry("one", "", _body("1"))
        pc.add_entry("two", "", _body("2"))
        with self.assertRaises(ValueError):
            pc.update_entry(one["id"], name="two")
        self.assertEqual(pc.get_entry(one["id"])["name"], "one")

    def test_remove_entry(self) -> None:
        entry = pc.add_entry("Cover scene", "d", _body("v1"))
        self.assertTrue(pc.remove_entry(entry["id"]))
        self.assertEqual(pc.list_entries(), [])
        self.assertFalse(pc.remove_entry(entry["id"]))

    def test_civitai_token_is_stripped_before_storing(self) -> None:
        body = _body("a stool")
        body["prompt"]["80"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["70", 0],
                "clip": ["71", 0],
                "lora_name": "https://civitai.com/api/download/models/3088444?token=SUPERSECRET",
                "strength_model": 1.0,
                "strength_clip": 1.0,
            },
        }
        entry = pc.add_entry("With a gated LoRA", "", body)
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("SUPERSECRET", raw)
        stored = str(entry["request"]["prompt"]["80"]["inputs"]["lora_name"])
        self.assertNotIn("token", stored)
        self.assertIn("3088444", stored)

    def test_entry_stats_describes_the_graph(self) -> None:
        entry = pc.add_entry("Cover scene", "", _body("a stool"))
        stats = pc.entry_stats(entry)
        self.assertIn("3 nodes", stats)
        self.assertIn("1024×1024", stats)
        self.assertEqual(pc.entry_stats(None), "")

    def test_corrupt_rows_are_skipped_not_fatal(self) -> None:
        good = pc.add_entry("good", "", _body("x"))
        self.path.write_text(
            json.dumps(
                [
                    {"name": "no request"},
                    {"request": _body("y")},
                    "not a row",
                    {"id": good["id"], "name": "good", "request": _body("x"), "ts": 1},
                ]
            ),
            encoding="utf-8",
        )
        rows = pc.list_entries()
        self.assertEqual([r["name"] for r in rows], ["good"])


if __name__ == "__main__":
    unittest.main()
