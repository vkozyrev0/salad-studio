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
        self.assertEqual(shell.buttons["B"].content.weight, ft.FontWeight.W_600)
        self.assertEqual(shell.buttons["A"].content.weight, ft.FontWeight.NORMAL)


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
