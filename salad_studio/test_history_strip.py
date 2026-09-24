"""History-strip tests: drive the live HistoryStrip on a withdrawn Tk root.

Covers the module's behavioral surface the audit flagged as untested
(M17): `set_paths`, `_rebuild`, `_photo_for`, `_load_thumb`,
`_layout_thumbs`, `_scroll_left`, `_scroll_right`, `_scroll_pixels`,
`_on_mousewheel`, `_emit_open`.

The root is created and withdrawn before any widget work, so no window
is ever shown. `test_theme.py` covers only the palette; this module
covers what the strip does with real files.
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterable, Sequence

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

try:
    import tkinter as tk
except ImportError as _tk_err:  # pragma: no cover - host without Tcl
    tk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR: object = _tk_err
else:
    _TK_IMPORT_ERROR = None

try:
    from PIL import Image
except ImportError as _pil_err:  # pragma: no cover - host without Pillow
    Image = None  # type: ignore[assignment]
    _PIL_IMPORT_ERROR: object = _pil_err
else:
    _PIL_IMPORT_ERROR = None

_TK_OK = tk is not None
_TK_ERROR: object = _TK_IMPORT_ERROR

# JPEG is lossy, so a decoded solid fill is only approximately the value
# that was written.
_JPEG_TOLERANCE = 10


def setUpModule() -> None:
    """Probe Tk once; every test skips cleanly when Tcl cannot start."""
    global _TK_OK, _TK_ERROR
    if tk is None:
        return
    try:
        root = tk.Tk()
    except tk.TclError as e:
        _TK_OK = False
        _TK_ERROR = e
        return
    root.withdraw()
    root.destroy()


class _Event:
    """Stand-in for a Tk event object; handlers read delta/num only."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
@unittest.skipIf(Image is None, f"Pillow unavailable: {_PIL_IMPORT_ERROR}")
class HistoryStripOnWithdrawnRoot(unittest.TestCase):
    """Construct the shipped HistoryStrip on a hidden root and drive it."""

    THUMB: Sequence[int] = (64, 64)

    def setUp(self) -> None:
        if not _TK_OK:
            self.skipTest(f"Tk cannot initialize: {_TK_ERROR}")
        from salad_studio.history_strip import HistoryStrip
        from salad_studio.theme import apply_theme

        self.HistoryStrip = HistoryStrip
        self.apply_theme = apply_theme
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

        self.opens: list[Path] = []
        self.root = tk.Tk()
        self.root.withdraw()  # no window may ever appear on screen
        self.addCleanup(self._destroy_root)
        apply_theme(self.root)
        self.strip = HistoryStrip(
            self.root,
            on_open=self.opens.append,
            thumb_size=self.THUMB,
        )
        self.strip.pack(fill="both", expand=True)
        self.root.update_idletasks()
        self.canvas = self.strip.canvas

    def _destroy_root(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass

    # ---- fixtures / observables -------------------------------------

    def _jpeg(self, name: str, size: tuple[int, int], colour: tuple[int, int, int]) -> Path:
        path = self.dir / name
        Image.new("RGB", size, colour).save(path)
        return path

    def _thumb_items(self) -> tuple[int, ...]:
        return tuple(self.canvas.find_withtag("thumb"))

    def _region(self) -> tuple[int, int, int, int]:
        raw = str(self.canvas.cget("scrollregion")).split()
        self.assertEqual(len(raw), 4, f"unparsable scrollregion {raw!r}")
        return tuple(int(float(v)) for v in raw)  # type: ignore[return-value]

    def _left(self) -> float:
        return float(self.canvas.xview()[0])

    def _bbox(self, item: int) -> tuple[int, int, int, int]:
        box = self.canvas.bbox(item)
        self.assertIsNotNone(box, "thumb item has no bounding box")
        self.assertEqual(len(box), 4, f"unparsable bbox {box!r}")
        return (int(box[0]), int(box[1]), int(box[2]), int(box[3]))

    def _pixel(self, item: int, x: int, y: int) -> tuple[int, int, int]:
        """Read a pixel out of the Tk photo the canvas is displaying."""
        name = str(self.canvas.itemcget(item, "image"))
        self.assertTrue(name, "canvas image item has no photo")
        return tuple(int(v) for v in self.root.tk.call(name, "get", x, y))  # type: ignore[return-value]

    def _assert_close(
        self,
        got: Sequence[int],
        want: Sequence[int],
        *,
        tolerance: int = _JPEG_TOLERANCE,
        msg: str = "",
    ) -> None:
        self.assertEqual(len(got), len(want), msg)
        for g, w in zip(got, want, strict=False):
            self.assertLessEqual(abs(g - w), tolerance, f"{msg}: {tuple(got)} != {tuple(want)}")

    def _click_thumb(self, item: int) -> None:
        """Run the shipped <Button-1> binding for a thumb item.

        The root is withdrawn (no window may appear), so Tk cannot deliver
        a real pointer event. Tk keeps the binding as a Tcl command; calling
        it with the substitution values tkinter expects executes the very
        binding a real click would, including the shipped callback.
        """
        script = str(self.canvas.tag_bind(item, "<Button-1>"))
        self.assertTrue(script, "thumb item has no <Button-1> binding")
        command = script.split("[", 1)[1].split(" ", 1)[0]
        values = {
            "%#": "0",
            "%b": "0",
            "%f": "0",
            "%h": "100",
            "%k": "0",
            "%s": "0",
            "%t": "0",
            "%w": "100",
            "%x": "10",
            "%y": "10",
            "%A": "?",
            "%E": "0",
            "%K": "??",
            "%N": "0",
            "%W": str(self.canvas),
            "%T": "ButtonPress",
            "%X": "0",
            "%Y": "0",
            "%D": "0",
        }
        tokens = re.findall(r"%[A-Za-z#]", script)
        self.assertTrue(tokens, f"binding script has no substitutions: {script!r}")
        self.root.tk.call(command, *[values[t] for t in tokens])

    def _set_paths(self, paths: Iterable[Path]) -> None:
        self.strip.set_paths(paths)
        self.root.update_idletasks()

    # ---- set_paths / _rebuild / _photo_for / _load_thumb / _layout_thumbs --

    def test_real_jpeg_places_one_thumb_at_thumb_size(self) -> None:
        src = self._jpeg("solid.jpg", (300, 180), (200, 40, 60))

        self._set_paths([src])

        items = self._thumb_items()
        self.assertEqual(len(items), 1, "one path must place exactly one thumb")
        box = self._bbox(items[0])
        self.assertEqual(box[2] - box[0], self.THUMB[0], "thumb width is the configured size")
        self.assertEqual(box[3] - box[1], self.THUMB[1], "thumb height is the configured size")

        region = self._region()
        self.assertGreaterEqual(region[2], self.THUMB[0], "scrollregion must cover the thumb")
        self.assertGreaterEqual(region[3], self.THUMB[1], "scrollregion must cover the thumb height")

        # The displayed pixels are the file's, not the placeholder's.
        self._assert_close(self._pixel(items[0], 32, 32), (200, 40, 60), msg="solid jpeg centre")
        self.assertEqual(self._left(), 0.0, "a fresh strip starts scrolled to the left")

    def test_scrollregion_grows_with_more_thumbs(self) -> None:
        one = self._jpeg("one.jpg", (300, 180), (200, 40, 60))
        self._set_paths([one])
        single_w = self._region()[2]

        paths = [self._jpeg(f"m{i}.jpg", (300, 180), (20 * i, 90, 150)) for i in range(3)]
        self._set_paths(paths)

        self.assertEqual(len(self._thumb_items()), 3)
        wide = self._region()[2]
        self.assertGreater(wide, single_w, "three thumbs need a wider scrollregion")
        self.assertGreaterEqual(wide, 3 * self.THUMB[0], "every thumb needs room in the region")

    def test_set_paths_replaces_previous_thumbs(self) -> None:
        first = [self._jpeg(f"a{i}.jpg", (300, 180), (200, 40, 60)) for i in range(3)]
        self._set_paths(first)
        old_ids = set(self._thumb_items())
        self.assertEqual(len(old_ids), 3)
        wide_w = self._region()[2]

        replacement = self._jpeg("only.jpg", (300, 180), (40, 200, 60))
        self._set_paths([replacement])

        new_ids = set(self._thumb_items())
        self.assertEqual(len(new_ids), 1, "set_paths replaces, it does not append")
        self.assertFalse(new_ids & old_ids, "the previous items must be gone from the canvas")
        self.assertLess(self._region()[2], wide_w, "region shrinks back to the new content")

    def test_missing_file_renders_themed_placeholder(self) -> None:
        from salad_studio.theme import rgb

        self._set_paths([self.dir / "does-not-exist.jpg"])

        items = self._thumb_items()
        self.assertEqual(len(items), 1)
        placeholder = rgb("border")
        self.assertEqual(self._pixel(items[0], 0, 0), placeholder)
        self.assertEqual(self._pixel(items[0], 32, 32), placeholder)
        box = self._bbox(items[0])
        self.assertEqual(box[2] - box[0], self.THUMB[0])

    def test_unreadable_file_and_directory_render_placeholder(self) -> None:
        from salad_studio.theme import rgb

        bogus = self.dir / "bogus.jpg"
        bogus.write_text("this is not an image", encoding="utf-8")

        self._set_paths([bogus])
        items = self._thumb_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(self._pixel(items[0], 32, 32), rgb("border"))

        # A directory is not a file either -> same placeholder path.
        self._set_paths([self.dir])
        items = self._thumb_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(self._pixel(items[0], 32, 32), rgb("border"))

    def test_wide_image_is_letterboxed_on_the_well_colour(self) -> None:
        from salad_studio.theme import rgb

        wide = self._jpeg("wide.jpg", (400, 80), (10, 220, 30))

        self._set_paths([wide])

        items = self._thumb_items()
        self.assertEqual(len(items), 1)
        item = items[0]
        box = self._bbox(item)
        self.assertEqual((box[2] - box[0], box[3] - box[1]), tuple(self.THUMB))

        # Top band is the letterbox background; the middle row is the photo.
        self.assertEqual(self._pixel(item, 32, 2), rgb("well"))
        self._assert_close(self._pixel(item, 32, 32), (10, 220, 30), msg="letterboxed photo")

    def test_empty_or_none_paths_clear_the_strip(self) -> None:
        paths = [self._jpeg(f"c{i}.jpg", (300, 180), (200, 40, 60)) for i in range(2)]
        self._set_paths(paths)
        self.assertEqual(len(self._thumb_items()), 2)

        self._set_paths([])
        self.assertEqual(self._thumb_items(), ())

        self._set_paths([self.dir / "x.jpg"])
        self.assertEqual(len(self._thumb_items()), 1)
        self.strip.set_paths(None)  # shipped signature tolerates None
        self.root.update_idletasks()
        self.assertEqual(self._thumb_items(), ())

    def test_layout_handler_is_bound_and_keeps_items_placed(self) -> None:
        paths = [self._jpeg(f"l{i}.jpg", (300, 180), (200, 40, 60)) for i in range(2)]
        self._set_paths(paths)
        items = self._thumb_items()
        self.assertEqual(len(items), 2)
        self.assertTrue(str(self.canvas.bind("<Configure>")), "relayout must be bound to <Configure>")

        before = [tuple(self.canvas.coords(i)) for i in items]
        region_before = self._region()
        self.strip._on_canvas_configure()
        self.root.update_idletasks()

        self.assertEqual([tuple(self.canvas.coords(i)) for i in items], before)
        self.assertEqual(self._region(), region_before)
        for item in items:
            self.assertNotEqual(tuple(self.canvas.coords(item)), (0.0, 0.0), "thumbs must be laid out")

    # ---- scrolling --------------------------------------------------

    def test_region_is_wider_than_canvas_and_buttons_scroll(self) -> None:
        paths = [self._jpeg(f"s{i}.jpg", (300, 180), (200, 40, 60)) for i in range(5)]
        self._set_paths(paths)
        self.assertEqual(len(self._thumb_items()), 5)

        self.assertGreater(self._region()[2], int(self.canvas.winfo_width()))
        self.assertEqual(self._left(), 0.0)

        self.strip._scroll_right()
        self.root.update_idletasks()
        scrolled = self._left()
        self.assertGreater(scrolled, 0.0, "_scroll_right must advance xview")

        self.strip._scroll_left()
        self.root.update_idletasks()
        self.assertEqual(self._left(), 0.0, "_scroll_left must return to the start")

        # The shipped chevrons are wired to those same handlers.
        self.strip.right_btn.invoke()
        self.root.update_idletasks()
        self.assertGreater(self._left(), 0.0)

        self.strip.left_btn.invoke()
        self.root.update_idletasks()
        self.assertEqual(self._left(), 0.0)

        self.strip._scroll_pixels(0)
        self.root.update_idletasks()
        self.assertEqual(self._left(), 0.0, "a zero-pixel scroll must be a no-op")

    def test_mousewheel_and_linux_scroll_shift_the_view(self) -> None:
        paths = [self._jpeg(f"w{i}.jpg", (300, 180), (200, 40, 60)) for i in range(5)]
        self._set_paths(paths)
        self.assertGreater(self._region()[2], int(self.canvas.winfo_width()))

        self.strip._scroll_right()
        self.root.update_idletasks()
        mid = self._left()
        self.assertGreater(mid, 0.0)

        self.assertEqual(self.strip._on_mousewheel(_Event(delta=120)), "break")
        self.root.update_idletasks()
        notched = self._left()
        self.assertLess(notched, mid, "a positive wheel delta scrolls back toward the start")

        self.assertEqual(self.strip._on_mousewheel(_Event(delta=0)), "break")
        self.assertEqual(self._left(), notched, "a zero delta must not move the view")

        self.assertEqual(self.strip._on_mousewheel(_Event()), "break")
        self.assertEqual(self._left(), notched, "an event without delta must not move the view")

        # Small deltas take the fine-grained branch.
        self.assertEqual(self.strip._on_mousewheel(_Event(delta=-30)), "break")
        self.root.update_idletasks()
        fine = self._left()
        self.assertGreater(fine, notched, "a small negative delta scrolls forward")

        self.assertEqual(self.strip._on_linux_scroll(_Event(num=5)), "break")
        self.root.update_idletasks()
        forward = self._left()
        self.assertGreater(forward, fine, "button-5 scrolls forward")

        self.assertEqual(self.strip._on_linux_scroll(_Event(num=4)), "break")
        self.root.update_idletasks()
        self.assertLess(self._left(), forward, "button-4 scrolls back")

        back = self._left()
        self.assertEqual(self.strip._on_linux_scroll(_Event(num=0)), "break")
        self.assertEqual(self._left(), back, "an unknown button must not move the view")

    # ---- open callback ----------------------------------------------

    def test_clicking_a_thumb_opens_that_exact_path(self) -> None:
        first = self._jpeg("first.jpg", (300, 180), (200, 40, 60))
        second = self._jpeg("second.jpg", (300, 180), (40, 200, 60))
        self._set_paths([first, second])
        items = self._thumb_items()
        self.assertEqual(len(items), 2)

        for item in items:
            self._click_thumb(item)

        self.assertEqual(self.opens, [first, second], "each thumb must open its own file")

    def test_emit_open_without_callback_is_silent(self) -> None:
        strip = self.HistoryStrip(self.root, thumb_size=(32, 32))
        self.addCleanup(strip.destroy)
        self.assertIsNone(strip.on_open, "on_open defaults to None")
        path = self._jpeg("nohandler.jpg", (300, 180), (200, 40, 60))
        strip.set_paths([path])
        self.root.update_idletasks()

        strip._emit_open(path)  # must not raise
        item = strip.canvas.find_withtag("thumb")[0]
        script = str(strip.canvas.tag_bind(item, "<Button-1>"))
        self.assertTrue(script, "thumb binding must exist even without a callback")


if __name__ == "__main__":
    unittest.main()
