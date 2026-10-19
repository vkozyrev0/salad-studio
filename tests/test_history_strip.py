"""The bottom history strip, driven as a user drives it: thumbnails, empty state, click, arrows.

The strip builds without a client, so the tests hand it the same ``(name, png)``
list the window builds and then click the shipped handlers, where a Flet page
would dispatch them.
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import flet as ft
from PIL import Image

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PKG = TOOLS / "salad_studio"
for p in (str(TOOLS), str(PKG)):
    if p not in sys.path:
        sys.path.insert(0, p)

from salad_studio import flet_theme  # noqa: E402
from salad_studio.flet_shell import HistoryStrip  # noqa: E402

EMPTY_TEXT = "No plates yet. A finished render appears here."


def _thumbnail(path: Path) -> bytes | None:
    """The window's own thumbnail, read off a real file."""
    try:
        with Image.open(path) as img:
            img.thumbnail((ShowingThumbs.THUMB, ShowingThumbs.THUMB))
            out = io.BytesIO()
            img.convert("RGB").save(out, "PNG")
            return out.getvalue()
    except OSError:
        return None


def run_click(control: ft.Control) -> None:
    """Deliver the click a user makes on a control."""
    handler = getattr(control, "on_click", None)
    assert handler is not None, f"{type(control).__name__} has no click handler"
    handler(ft.ControlEvent(str(control), "click"))


def visible_thumbs(strip: HistoryStrip) -> list[ft.Container]:
    return [c for c in strip.list.controls if c.visible]


class StripWithoutAClient(unittest.TestCase):
    THUMB = 140

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.colors = flet_theme.canvas_colors(True)

    def _jpeg(self, name: str, size: tuple[int, int], colour: tuple[int, int, int]) -> Path:
        """A JPEG as the generator writes one: saved with PIL, then re-read from disk."""
        path = self.dir / name
        Image.new("RGB", size, colour).save(path, quality=95)
        return path

    def _strip(self, opens: list[object] | None = None) -> HistoryStrip:
        seen = opens if opens is not None else []
        return HistoryStrip(self.colors, on_open=seen.append)


class ShowingThumbs(StripWithoutAClient):
    def test_an_empty_strip_says_so_in_those_words(self) -> None:
        strip = self._strip()
        strip.show([], lambda _i: None)

        self.assertTrue(strip.empty.visible, "the empty state is what an empty gallery shows")
        self.assertEqual(strip.empty.value, EMPTY_TEXT)
        self.assertFalse(strip.list.visible, "an empty gallery shows no thumbnails")
        self.assertEqual(strip.list.controls, [])

    def test_one_real_jpeg_shows_one_thumbnail_of_that_file(self) -> None:
        src = self._jpeg("solid.jpg", (300, 180), (200, 40, 60))
        strip = self._strip()

        strip.show([("solid", _thumbnail(src))], lambda _i: None)

        thumbs = visible_thumbs(strip)
        self.assertEqual(len(thumbs), 1, "one plate places exactly one thumbnail")
        self.assertNotIn("?", [c.content.value for c in thumbs if isinstance(c.content, ft.Text)],
                         "a readable file must not render the placeholder")
        image = thumbs[0].content
        self.assertIsInstance(image, ft.Image)
        self.assertIsInstance(image.src, bytes)
        with Image.open(io.BytesIO(image.src)) as shown:
            width, height = shown.size
            self.assertLessEqual(max(width, height), self.THUMB, "the plate fits the thumb box")
            self.assertEqual((width, height), (self.THUMB, round(self.THUMB * 180 / 300)),
                             "the plate keeps its shape, scaled to the box")
            pixel = shown.convert("RGB").getpixel((width // 2, height // 2))
        for got, want in zip(pixel, (200, 40, 60)):
            self.assertLessEqual(abs(got - want), 10, f"centre pixel {pixel} is not the file's colour")

    def test_thumbs_keep_the_newest_first_order_and_each_can_be_named(self) -> None:
        strip = self._strip()

        strip.show([("plate2", b"newest"), ("plate1", b"middle"), ("plate0", b"oldest")],
                   lambda _i: None)

        shown = visible_thumbs(strip)
        self.assertEqual(len(shown), 3)
        self.assertEqual([c.content.src for c in shown], [b"newest", b"middle", b"oldest"],
                         "the list the window hands over is shown left to right, untouched")
        self.assertEqual([c.tooltip for c in shown], ["plate2", "plate1", "plate0"])

    def test_each_thumb_opens_the_plate_in_its_own_position(self) -> None:
        opened: list[str] = []
        strip = self._strip()
        strip.show([("newest", b"n"), ("middle", b"m"), ("oldest", b"o")], opened.append)

        for thumb in visible_thumbs(strip):
            run_click(thumb)

        self.assertEqual(opened, [0, 1, 2], "a click reports the plate the user pointed at")

    def test_a_plate_without_a_thumbnail_still_shows_and_opens(self) -> None:
        strip = self._strip()
        strip.show([("missing", None)], lambda _i: None)

        thumbs = visible_thumbs(strip)
        self.assertEqual(len(thumbs), 1, "an unreadable plate keeps its slot")
        self.assertIsInstance(thumbs[0].content, ft.Text)
        self.assertEqual(thumbs[0].content.value, "?")
        self.assertEqual(thumbs[0].tooltip, "missing")
        self.assertTrue(callable(thumbs[0].on_click), "an unreadable plate is still clickable")

    def test_showing_a_new_list_replaces_the_old_one(self) -> None:
        strip = self._strip()
        strip.show([("a", b"a"), ("b", b"b"), ("c", b"c")], lambda _i: None)
        self.assertEqual(len(visible_thumbs(strip)), 3)

        strip.show([("only", b"x")], lambda _i: None)
        self.assertEqual([c.content.src for c in visible_thumbs(strip)], [b"x"])

        strip.show([], lambda _i: None)
        self.assertEqual(visible_thumbs(strip), [])
        self.assertTrue(strip.empty.visible, "the empty words come back when the list empties")


class Scrolling(unittest.TestCase):
    def setUp(self) -> None:
        self.colors = flet_theme.canvas_colors(True)
        self.strip = HistoryStrip(self.colors, on_open=lambda _p: None)
        self.strip.show([(f"p{n}", b"x") for n in range(5)], lambda _i: None)
        arrows = self.strip.content.controls
        self.left, self.right = arrows[0], arrows[-1]

    def test_the_arrows_sit_on_either_side_and_point_outward(self) -> None:
        self.assertEqual(self.left.content, "◀")
        self.assertEqual(self.right.content, "▶")
        self.assertEqual(self.left.tooltip, "Older")
        self.assertEqual(self.right.tooltip, "Newer")

    def test_the_arrows_scroll_the_strip(self) -> None:
        """The click reaches the list: the right arrow walks up, the left arrow walks back."""
        rests = [0, 120]
        moves: list[float] = []
        self.strip.list.scroll_to = lambda **kw: moves.append(kw["offset"])

        for rest, click in zip(rests, (self.right, self.left)):
            with patch.object(type(self.strip.list), "scroll_offset", rest, create=True):
                run_click(click)

        self.assertEqual(len(moves), 2, "each arrow press scrolls the list once")
        self.assertGreater(moves[0], rests[0], "the right arrow walks toward the newer plates")
        self.assertLess(moves[1], rests[1], "the left arrow walks back toward the oldest")


if __name__ == "__main__":
    unittest.main()
