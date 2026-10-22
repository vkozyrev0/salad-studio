"""Prompt History persistence and reuse."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PKG = TOOLS / "salad_studio"
for p in (str(TOOLS), str(PKG)):
    if p not in sys.path:
        sys.path.insert(0, p)

from salad_studio import prompt_history as ph  # noqa: E402
from tests import _stores  # noqa: E402
from tests._paths import _TempPaths  # noqa: E402


def setUpModule() -> None:
    """A window built here builds a queue, and the queue writes its ledger."""
    _stores.keep_queue_ledger_off_the_user_store()


def tearDownModule() -> None:
    _stores.restore_queue_ledger()


class PromptHistoryStore(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self._old = ph.HISTORY_PATH
        self._old_thumbs = ph.THUMBS_DIR
        ph.HISTORY_PATH = Path(self._td.name) / "studio-prompt-history.json"
        ph.THUMBS_DIR = Path(self._td.name) / "thumbs"
        self.addCleanup(lambda: setattr(ph, "HISTORY_PATH", self._old))
        self.addCleanup(lambda: setattr(ph, "THUMBS_DIR", self._old_thumbs))

    def test_add_list_skip_duplicate_remove(self) -> None:
        self.assertEqual(ph.list_prompts(), [])
        self.assertIsNone(ph.add_prompt("  "))
        a = ph.add_prompt("first prompt")
        self.assertIsNot(a, None)
        self.assertEqual(ph.add_prompt("first prompt"), a)
        ph.add_prompt("second prompt")
        rows = ph.list_prompts()
        self.assertEqual([r["text"] for r in rows], ["second prompt", "first prompt"])
        ph.remove_at(0)
        self.assertEqual([r["text"] for r in ph.list_prompts()], ["first prompt"])
        self.assertTrue(ph.HISTORY_PATH.is_file())

    def test_rating_round_trips_and_clears(self) -> None:
        """The rating is how a render is judged; it belongs with the row."""
        ph.add_prompt("first")
        ph.add_prompt("second")
        self.assertEqual([ph.rating_of(r) for r in ph.list_prompts()], [0, 0])
        self.assertTrue(ph.rate(0, 4))
        self.assertEqual(ph.rating_of(ph.list_prompts()[0]), 4, "index 0 is the newest")
        self.assertEqual(ph.rating_of(ph.list_prompts()[1]), 0, "the other row is untouched")
        self.assertTrue(ph.rate(0, 0))
        self.assertEqual(ph.rating_of(ph.list_prompts()[0]), 0, "0 clears the rating")
        self.assertNotIn("rating", ph.list_prompts()[0], "a cleared rating leaves no field")
        self.assertFalse(ph.rate(9, 3), "a row that is gone is not rated")
        self.assertEqual(ph.rating_of({"rating": "junk"}), 0, "junk reads as unrated")
        self.assertEqual(ph.rating_of({"rating": 99}), 5, "and an out-of-range value clamps")

    def test_preview(self) -> None:
        self.assertEqual(ph.preview("a\nb  c"), "a b c")

    def test_add_request_stores_json_and_skips_duplicate(self) -> None:
        body = {
            "prompt": {
                "74": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "stallion on a hillside", "clip": ["71", 0]},
                },
                "115": {
                    "class_type": "LoraLoader",
                    "inputs": {
                        "lora_name": "https://civitai.com/api/download/models/2795018?token=SECRET",
                        "strength_model": 0.5,
                        "strength_clip": 0.5,
                    },
                },
                "89": {
                    "class_type": "EmptyFlux2LatentImage",
                    "inputs": {"width": 1024, "height": 768, "batch_size": 1},
                },
                "85": {
                    "class_type": "BasicScheduler",
                    "inputs": {
                        "scheduler": "simple",
                        "steps": 40,
                        "denoise": 1,
                    },
                },
                "86": {
                    "class_type": "CFGGuider",
                    "inputs": {"cfg": 5},
                },
                "84": {
                    "class_type": "KSamplerSelect",
                    "inputs": {"sampler_name": "euler"},
                },
            }
        }
        a = ph.add_request(body)
        self.assertIsNot(a, None)
        self.assertEqual(a["text"], "stallion on a hillside")
        lora = a["request"]["prompt"]["115"]["inputs"]["lora_name"]
        self.assertNotIn("SECRET", lora)
        self.assertIn("2795018", lora)
        again = ph.add_request(body)
        self.assertIsNot(again, None)
        self.assertEqual(again["ts"], a["ts"])
        self.assertEqual(again["request"], a["request"])
        self.assertEqual(len(ph.list_prompts()), 1)
        stats = ph.request_stats(a["request"])
        self.assertIn("6 nodes", stats)
        self.assertIn("1 LoRA", stats)
        self.assertIn("civitai:2795018@0.5", stats)
        self.assertIn("1024×768", stats)
        self.assertIn("40 steps", stats)
        self.assertIn("cfg 5", stats)
        self.assertIn("euler", stats)
        self.assertIn("simple", stats)
        # Same prompt, different graph → new row
        body2 = json.loads(json.dumps(body))
        body2["prompt"]["86"]["inputs"]["cfg"] = 1
        b = ph.add_request(body2)
        self.assertIsNot(b, None)
        self.assertIsNot(b, a)
        self.assertEqual([r["text"] for r in ph.list_prompts()], [
            "stallion on a hillside",
            "stallion on a hillside",
        ])

    def test_add_request_strips_credentials_and_every_token(self) -> None:
        """The stored request must not keep a Bearer block or any ``?token=``.

        Only ``lora_name`` was scrubbed, so the documented Salad shape's
        ``credentials`` block landed in the history in clear.
        """
        body = {
            "credentials": {
                "https://civitai.com": {
                    "header": {"key": "Authorization", "value": "Bearer SECRET"}
                }
            },
            "prompt": {
                "1": {
                    "class_type": "LoadImage",
                    "inputs": {"image": "https://example.test/plate.png?token=SECRET2"},
                },
                "2": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "keep me"},
                },
            },
        }
        entry = ph.add_request(body)
        self.assertIsNotNone(entry)
        self.assertNotIn("credentials", entry["request"])
        self.assertNotIn("SECRET", json.dumps(entry["request"]))
        self.assertEqual(
            entry["request"]["prompt"]["2"]["inputs"]["text"], "keep me"
        )
        self.assertIn("credentials", body, "the caller's body must not be mutated")

    def test_attach_image_with_a_ts_that_matches_no_row_attaches_nothing(self) -> None:
        """The documented rule: a ``ts`` no row carries returns None.

        Falling back to the newest row would hand this plate to a different
        render and delete that row's thumbnail, so the miss has to be a miss.
        """
        from PIL import Image

        older, newer = 1_700_000_000_000, 1_700_000_001_000
        ph.HISTORY_PATH.write_text(
            json.dumps(
                [
                    {"text": "the older render", "ts": older},
                    {"text": "the newer render", "ts": newer},
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        src = Path(self._td.name) / "plate.jpg"
        Image.new("RGB", (200, 120), (200, 80, 40)).save(src, "JPEG")
        self.assertIsNone(
            ph.attach_image(src, ts=newer + 1),
            "a ts that matches no row must attach to nothing",
        )
        self.assertEqual(
            [row.get("image") or "" for row in ph.list_prompts()],
            ["", ""],
            "no row may be given the plate, and no thumbnail may be written",
        )
        # The row the ts does name still takes it.
        thumb = ph.attach_image(src, ts=older)
        self.assertIsNot(thumb, None)
        rows = {int(row["ts"]): row for row in ph.list_prompts()}
        self.assertEqual(rows[older]["image"], str(thumb))
        self.assertNotIn("image", rows[newer])

    def test_legacy_text_only_still_loads(self) -> None:
        ph.HISTORY_PATH.write_text(
            json.dumps([{"text": "old prompt", "ts": 1}]) + "\n",
            encoding="utf-8",
        )
        rows = ph.list_prompts()
        self.assertEqual(rows[0]["text"], "old prompt")
        self.assertNotIn("request", rows[0])
        self.assertEqual(ph.request_stats(None), "")

    def test_attach_image_writes_thumb_on_newest_row(self) -> None:
        from PIL import Image

        body = {
            "prompt": {
                "74": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "a tree at dusk", "clip": ["71", 0]},
                }
            }
        }
        entry = ph.add_request(body)
        self.assertIsNot(entry, None)
        src = Path(self._td.name) / "plate.jpg"
        Image.new("RGB", (200, 120), (200, 80, 40)).save(src, "JPEG")
        thumb = ph.attach_image(src)
        self.assertIsNot(thumb, None)
        self.assertTrue(thumb.is_file())
        self.assertEqual(thumb.parent, ph.THUMBS_DIR)
        with Image.open(thumb) as im:
            self.assertEqual(im.size, ph.THUMB_SIZE)
        rows = ph.list_prompts()
        self.assertEqual(rows[0]["image"], str(thumb))
        n = ph.clear_thumbs()
        self.assertGreaterEqual(n, 1)
        self.assertFalse(thumb.is_file())
        self.assertEqual(ph.list_prompts()[0].get("image") or "", "")
        ph.remove_at(0)
        self.assertFalse(thumb.is_file())


def _page_rows(page) -> list[list[str]]:
    """The history table's cells as text, one list per row."""
    out: list[list[str]] = []
    for row in page.table_holder.controls[0].rows:
        out.append([str(cell.content.value) if hasattr(cell.content, "value") else str(cell.content)
                    for cell in row.cells])
    return out



if __name__ == "__main__":
    unittest.main()
