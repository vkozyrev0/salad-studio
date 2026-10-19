"""The Flet window. Entry point is ``main(page)``.

The shell owns the rail and the lines that report what happened. Each page
module builds its own controls and calls the existing service modules; the
window holds no domain state of its own beyond which page is open.
"""
from __future__ import annotations

from typing import Any

import flet as ft

from salad_studio import flet_theme
from salad_studio.flet_pump import Pump
from salad_studio.flet_shell import PageSpec, Shell, apply_shortcut
from salad_studio.pages.editor import EditorPage

PAGES: tuple[tuple[str, str], ...] = (
    ("Config", ""),
    ("Prompt Settings", ""),
    ("Tokens", ""),
    ("LoRAs", ""),
    ("Prompt Editor", "JSON and graph"),
    ("Prompt Assist", ""),
    ("Prompt Catalog", ""),
    ("Import", ""),
    ("Prompt History", ""),
    ("Queue", ""),
    ("Logs", ""),
)


def _page(name: str, host: Any) -> ft.Control:
    if name == "Prompt Editor":
        return EditorPage(host)
    from salad_studio.flet_shell import Page

    page = Page(name, "", _colors())
    page.note("Not ported yet.")
    return page


def _colors() -> dict[str, str]:
    return flet_theme.canvas_colors(True)


def build(page: ft.Page) -> Shell:
    """The window's shell, wired to the page. ``main`` adds it and opens the editor."""
    flet_theme.apply(page)
    page.title = "Salad Studio"
    page.window.min_width = 900
    page.window.min_height = 560
    pump = Pump()
    shell = Shell([PageSpec(name, lambda host, n=name: _page(n, host)) for name, _ in PAGES])
    page.on_keyboard_event = lambda e: apply_shortcut(shell, e)
    page.add(shell)
    page.run_task(pump.run)
    shell.say("Ready")
    return shell


def main(page: ft.Page) -> None:
    shell = build(page)
    shell.open("Prompt Editor")
