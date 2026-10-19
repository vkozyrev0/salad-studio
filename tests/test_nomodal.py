"""The Flet dialogs open and close without holding a modal loop.

The Tk messageboxes blocked the thread until someone clicked. ``Window.dialog``
and ``Window.ask`` add an ``AlertDialog`` to the real page's overlay with
``open=True``, return at once, and the buttons take it back out of the
overlay. The page carries a stub session and records its repaints instead of
sending them, so this runs with no client.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import flet as ft  # noqa: E402

from salad_studio import flet_theme  # noqa: E402
from salad_studio.flet_app import Window  # noqa: E402
from tests._flet_window import Session, TempStores  # noqa: E402


def _window() -> tuple[Window, ft.Page]:
    page = ft.Page(Session())
    shell = mock.Mock(colors=flet_theme.canvas_colors(dark=True))
    return Window(page, mock.Mock(), shell), page


def _repaint_probe(test: unittest.TestCase, box: ft.AlertDialog) -> list[str]:
    """Record each repaint of the box, the way Flet receives it with no client."""
    steps: list[str] = []

    def update() -> None:
        steps.append("closed" if box.open is False else "open")

    box.update = update
    test.addCleanup(setattr, box, "update", type(box).update.__get__(box))
    return steps


def _press(box: ft.AlertDialog, label: str) -> None:
    button = next(a for a in box.actions if a.content == label)
    button.on_click(mock.Mock(control=button))


class TheDialogSurface(unittest.TestCase):
    def setUp(self) -> None:
        self.stores = TempStores().__enter__()

    def tearDown(self) -> None:
        self.stores.__exit__(None, None, None)

    def test_dialog_returns_at_once_with_its_box_open_on_the_overlay(self) -> None:
        window, page = _window()
        self.assertIsNone(window.dialog("Salad Studio", "Gallery is already empty."))
        [box] = page.overlay
        self.assertIsInstance(box, ft.AlertDialog)
        self.assertTrue(box.open)
        self.assertIn("Gallery is already empty.", box.content.value)
        self.assertEqual([a.content for a in box.actions], ["OK"])

    def test_ok_removes_the_box_from_the_overlay(self) -> None:
        window, page = _window()
        window.dialog("Salad Studio", "done")
        [box] = page.overlay
        steps = _repaint_probe(self, box)
        _press(box, "OK")
        self.assertFalse(box.open)
        self.assertEqual(page.overlay, [])
        self.assertEqual(steps, ["closed"], "closing repaints the box")

    def test_a_destructive_ask_waits_for_yes_before_it_acts(self) -> None:
        window, page = _window()
        act = mock.Mock()
        self.assertIsNone(window.ask("Salad Studio", "Delete 3 image(s)?", act))
        [box] = page.overlay
        self.assertEqual([a.content for a in box.actions], ["No", "Yes"])
        self.assertTrue(box.modal)
        act.assert_not_called()

        _press(box, "No")
        act.assert_not_called()
        self.assertFalse(box.open)
        self.assertEqual(page.overlay, [], "No closes the box and leaves the gallery")

    def test_yes_closes_the_box_and_then_acts(self) -> None:
        window, page = _window()
        act = mock.Mock()
        window.ask("Salad Studio", "Delete 3 image(s)?", act)
        [box] = page.overlay
        _press(box, "Yes")
        act.assert_called_once_with()
        self.assertFalse(box.open)
        self.assertEqual(page.overlay, [])


if __name__ == "__main__":
    unittest.main()
