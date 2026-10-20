"""The window shell, exercised without a running client: pages, rail marks, status, shortcuts."""
from __future__ import annotations

import unittest

import flet as ft

from salad_studio import flet_shell
from salad_studio.flet_shell import PageSpec, Shell


class Key:
    """The fields ``flet_shell.shortcut`` reads."""

    def __init__(self, name: str, *, ctrl: bool = True, shift: bool = False) -> None:
        self.key, self.ctrl, self.shift = name, ctrl, shift


def key(name: str, *, ctrl: bool = True, shift: bool = False) -> Key:
    return Key(name, ctrl=ctrl, shift=shift)


def shell_with(names: list[str]) -> Shell:
    return Shell([PageSpec(name, lambda host, n=name: flet_shell.Page(n, "", host.colors)) for name in names])


class Opening(unittest.TestCase):
    def test_a_page_is_built_once_and_reopened_from_memory(self) -> None:
        builds: list[str] = []

        def build(host):
            builds.append("x")
            return ft.Text("page")

        shell = Shell([PageSpec("A", build), PageSpec("B", build)])
        shell.open("A")
        shell.open("B")
        shell.open("A")
        self.assertEqual(builds, ["x", "x"])
        self.assertIs(shell.body.content.controls[-1], shell.pages["A"])
        self.assertEqual(shell.current, "A")

    def test_the_open_page_is_marked_on_the_rail(self) -> None:
        shell = shell_with(["A", "B"])
        shell.open("B")
        self.assertEqual(shell.buttons["B"].bgcolor, shell.colors["primary_container"])
        self.assertIsNone(shell.buttons["A"].bgcolor)
        self.assertEqual(shell.buttons["B"].name_label.weight, ft.FontWeight.W_600)
        self.assertEqual(shell.buttons["A"].name_label.weight, ft.FontWeight.NORMAL)


class Status(unittest.TestCase):
    def test_a_note_lands_on_the_open_page_and_the_window_line(self) -> None:
        shell = shell_with(["A", "B"])
        shell.open("A")
        shell.note("Saved the profile")
        self.assertEqual(shell.pages["A"].note_text.value, "Saved the profile")
        self.assertEqual(shell.status.value, "Saved the profile")
        self.assertEqual(shell.status.color, shell.colors["muted"])

    def test_an_error_is_coloured_as_an_error(self) -> None:
        shell = shell_with(["A"])
        shell.open("A")
        shell.note("Refused", level="error")
        self.assertEqual(shell.pages["A"].note_text.color, shell.colors["error"])

    def test_a_note_before_any_page_is_open_still_reaches_the_window_line(self) -> None:
        shell = shell_with(["A"])
        shell.note("Ready")
        self.assertEqual(shell.status.value, "Ready")


class Moving(unittest.TestCase):
    def test_ctrl_tab_wraps_forward_and_shift_ctrl_tab_back(self) -> None:
        shell = shell_with(["A", "B", "C"])
        shell.open("C")
        self.assertTrue(flet_shell.apply_shortcut(shell, key("Tab")))
        self.assertEqual(shell.current, "A")
        self.assertTrue(flet_shell.apply_shortcut(shell, key("Tab", shift=True)))
        self.assertEqual(shell.current, "C")

    def test_ctrl_page_down_and_up_move_one_page(self) -> None:
        shell = shell_with(["A", "B", "C"])
        shell.open("A")
        flet_shell.apply_shortcut(shell, key("PageDown"))
        self.assertEqual(shell.current, "B")
        flet_shell.apply_shortcut(shell, key("PageUp"))
        self.assertEqual(shell.current, "A")

    def test_ctrl_digits_pick_a_page_and_zero_returns_to_the_first(self) -> None:
        shell = shell_with(["A", "B", "C", "D"])
        shell.open("B")
        flet_shell.apply_shortcut(shell, key("3"))
        self.assertEqual(shell.current, "C")
        flet_shell.apply_shortcut(shell, key("0"))
        self.assertEqual(shell.current, "A")

    def test_a_digit_past_the_last_page_stays_on_the_last_page(self) -> None:
        shell = shell_with(["A", "B"])
        flet_shell.apply_shortcut(shell, key("9"))
        self.assertEqual(shell.current, "B")

    def test_a_key_without_ctrl_is_not_a_shortcut(self) -> None:
        shell = shell_with(["A", "B"])
        shell.open("A")
        self.assertIsNone(flet_shell.shortcut(key("Tab", ctrl=False)))
        self.assertFalse(flet_shell.apply_shortcut(shell, key("Tab", ctrl=False)))
        self.assertEqual(shell.current, "A")


if __name__ == "__main__":
    unittest.main()


class PagesAndTheirControls(unittest.TestCase):
    """A page keeps its controls under names that are not the page column's own fields.

    ``SettingsPage`` stored its Width and Height knobs as ``self.width`` and
    ``self.height``. Those are ``ft.Column``'s own layout fields, so the page
    took them and the pane painted as an empty grey block on every render.
    """

    def test_no_page_sets_a_control_on_a_field_of_its_own_column(self) -> None:
        import dataclasses
        import inspect
        import sys
        from pathlib import Path

        # Pages import the repo's top-level modules (studio_meta, hostings) the
        # way the app does; the package directory alone is not enough.
        package, parent = (str(Path(__file__).resolve().parent.parent / part)
                           for part in ("salad_studio", ""))
        for path in (parent, package):
            if path not in sys.path:
                sys.path.insert(0, path)

        from salad_studio.pages import (
            assist, catalog, config, editor, history, import_page, logs_page, loras,
            prompt_settings, queue_page, tokens_page,
        )

        reserved = {f.name for f in dataclasses.fields(ft.Column)} | {
            f.name for f in dataclasses.fields(ft.Container)}
        offenders: list[str] = []
        for module in (assist, catalog, config, editor, history, import_page, logs_page, loras,
                       prompt_settings, queue_page, tokens_page):
            for name, cls in vars(module).items():
                if not (inspect.isclass(cls) and cls.__module__ == module.__name__
                        and issubclass(cls, ft.Column)):
                    continue
                source = inspect.getsource(cls)
                hits = sorted(f for f in reserved if f"self.{f} =" in source)
                offenders.extend(f"{name}.{f}" for f in hits)
        self.assertEqual(offenders, [], "a page field would take the column's layout slot")

    def test_the_window_opens_with_a_line_that_says_where_to_start(self) -> None:
        from salad_studio.flet_shell import REST_TEXT

        self.assertEqual(shell_with(["A"]).status.value, REST_TEXT)
        self.assertIn("Ctrl+Tab", REST_TEXT)


class Repainting(unittest.TestCase):
    """A page is mounted before anything repaints it, or the client loses the window."""

    def test_opening_a_page_repaints_a_control_the_client_already_has(self) -> None:
        from unittest.mock import patch

        shell = shell_with(["A", "B"])
        seen: list[str] = []

        def record(control) -> None:
            seen.append(type(control).__name__)

        with patch.object(ft.Container, "update", record):
            shell.open("A")
            shell.open("B")
        self.assertEqual(seen, ["Container", "Container"],
                         "the open page is repainted through the body, never the page")
        self.assertIs(shell.body_column.controls[-1], shell.pages["B"])


class Keyboard(unittest.TestCase):
    """Ctrl moves pages from anywhere; without Ctrl the keys move what has the focus."""

    def setUp(self) -> None:
        self.shell = shell_with(["A", "B", "C"])
        self.shell.open("A")

    def press(self, key: str, *, ctrl: bool = False, shift: bool = False) -> bool:
        return self.shell._on_key(ft.KeyboardEvent("key_down", None, key, shift, ctrl, False, False))

    def test_ctrl_tab_steps_pages_whatever_the_strip_holds(self) -> None:
        self.shell.focus = "strip"
        self.assertTrue(self.press("Tab", ctrl=True))
        self.assertEqual(self.shell.current, "B")
        self.assertTrue(self.press("Tab", ctrl=True, shift=True))
        self.assertEqual(self.shell.current, "A")

    def test_the_first_arrow_puts_the_ring_on_the_first_thumb(self) -> None:
        self.shell.focus = "strip"
        self.shell.strip.show([("a", b"a"), ("b", b"b")], lambda _i: None)
        self.assertTrue(self.press("Arrow Right"))
        self.assertEqual(self.shell.strip.ring, 0)

    def test_the_arrows_walk_the_ring_and_enter_opens_it(self) -> None:
        opened: list[int] = []
        self.shell.strip.show([("a", b"a"), ("b", b"b"), ("c", b"c")], opened.append)
        self.shell.focus = "strip"
        self.press("Right")
        self.press("Arrow Left")   # the arrow names arrive in more than one spelling
        self.press("right")
        self.assertEqual(self.shell.strip.ring, 1)
        self.assertTrue(self.press("Enter"))
        self.assertEqual(opened, [1])

    def test_home_and_end_move_the_ring_to_its_ends(self) -> None:
        self.shell.strip.show([("a", b"a"), ("b", b"b"), ("c", b"c")], lambda _i: None)
        self.shell.focus = "strip"
        self.press("End")
        self.assertEqual(self.shell.strip.ring, 2)
        self.press("Home")
        self.assertEqual(self.shell.strip.ring, 0)

    def test_the_arrows_move_the_open_pages_table_instead(self) -> None:
        class Grid:
            def __init__(self) -> None:
                self.moves: list[str] = []

            def move_selection(self, action: str) -> None:
                self.moves.append(action)

        grid = Grid()
        self.shell.pages["A"] = grid
        self.assertTrue(self.press("Arrow Down"))
        self.assertTrue(self.press("down"))
        self.assertIn("next", grid.moves)
        self.assertEqual(grid.moves[0], "next")
        self.shell.focus = "strip"
        self.shell.open("B")
        self.assertEqual(self.shell.focus, "page", "opening a page hands the keys back to it")
