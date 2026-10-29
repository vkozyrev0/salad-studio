"""The gallery: the newest renders that have a picture, kept with their metadata.

A plate used to be a file in one output folder. The history is where a render
is recorded, so the gallery reads it there and a finished render shows up with
nothing moved. These tests drive the real studio at the action table.
"""
from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import prompt_history  # noqa: E402
from tests._studio import studio  # noqa: E402

# A 1x1 PNG, written here so the suite needs no fixture on disk.
SEED_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _picture(made) -> Path:
    path = Path(made.tmp.name) / "seed.png"
    path.write_bytes(SEED_BYTES)
    return path


def _render(made, text: str) -> dict:
    """One history entry with a picture attached, as a finished render leaves it."""
    entry = prompt_history.add_request(
        {"prompt": {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": text}}}})
    prompt_history.attach_image(_picture(made), key=entry["key"])
    return prompt_history.list_prompts()[0]


class GalleryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._ctx = studio()
        self.made = self._ctx.__enter__()

    def tearDown(self) -> None:
        self._ctx.__exit__(None, None, None)

    def _plates(self) -> list[dict]:
        return self.made.shell.state_dict()["plates"]

    def test_a_render_with_a_picture_is_a_plate(self) -> None:
        entry = _render(self.made, "a first render")
        self.made.studio.refresh_plates()
        plates = self._plates()
        self.assertEqual([p["name"] for p in plates], [entry["key"]])
        # The page draws this URL in an `img`, which sends no header, so the run token rides in it.
        self.assertEqual(plates[0]["url"],
                         f"/api/thumbs/{Path(entry['image']).name}?token={self.made.token}")

    def test_a_render_without_a_picture_is_not_a_plate(self) -> None:
        prompt_history.add_request({"prompt": {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "no image"}}}})
        self.made.studio.refresh_plates()
        self.assertEqual(self._plates(), [])

    def test_the_newest_render_is_first(self) -> None:
        older = _render(self.made, "older render")
        newer = _render(self.made, "newer render")
        self.made.studio.refresh_plates()
        self.assertEqual([p["name"] for p in self._plates()][:2], [newer["key"], older["key"]])

    def test_opening_a_plate_opens_that_row_picture(self) -> None:
        entry = _render(self.made, "open me")
        opened: list[Path] = []
        self.made.studio.services.open_path = opened.append
        self.made.studio.refresh_plates()
        _status, reply = self.made.act("shell", "open_plate", {"name": entry["key"]})
        self.assertTrue(reply["ok"])
        self.assertEqual([Path(p) for p in opened], [Path(entry["image"])])

    def test_cleaning_the_gallery_keeps_the_history(self) -> None:
        entry = _render(self.made, "clean me")
        thumb = Path(entry["image"])
        self.made.studio.refresh_plates()
        self.assertEqual(len(self._plates()), 1)
        _status, reply = self.made.act("shell", "clean_gallery", {})
        token = reply["effects"][0]["token"]
        self.made.engine.handle({"confirm": token})
        self.assertEqual(self._plates(), [])
        self.assertFalse(thumb.exists())
        rows = prompt_history.list_prompts()
        self.assertEqual(len(rows), 1, "the render is still history")
        self.assertFalse(rows[0].get("image"), "the row keeps no picture")


if __name__ == "__main__":
    unittest.main()
