"""The window: action bar, page rail, per-page note lines, status line.

Pages are controls with ``refresh(channel)``. The shell owns the rail, which
page is open, the keyboard shortcuts that move between pages, and the two
lines that report what happened. A page never writes to another page.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

import flet as ft

from salad_studio import flet_theme


@dataclass(frozen=True)
class PageSpec:
    name: str
    build: Callable[["PageHost"], ft.Control]


class PageHost(Protocol):
    """What a page may do with the window. Domain state lives in the page's own module."""

    def note(self, text: str, *, level: str = "info") -> None: ...


class Page(ft.Column):
    """One page: a heading, a note line, and the page's own content."""

    def __init__(self, title: str, subtitle: str, colors: dict[str, str]) -> None:
        super().__init__(expand=True, spacing=flet_theme.GAP["sm"])
        self.colors = colors
        self.title = title
        self.note_text = ft.Text("", size=12, color=colors["muted"], max_lines=3)
        self.body = ft.Container(expand=True)
        self.controls = [
            ft.Row(
                [
                    ft.Text(title, style=ft.TextStyle(size=17, weight=ft.FontWeight.W_600,
                                                      color=colors["on_surface"])),
                    ft.Text(subtitle, size=12, color=colors["muted"]),
                ],
                spacing=flet_theme.GAP["sm"],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            self.note_text,
            self.body,
        ]

    def note(self, text: str, *, level: str = "info") -> None:
        self.note_text.value = text
        self.note_text.color = {
            "info": self.colors["muted"],
            "ok": self.colors["ok"],
            "warn": self.colors["warn"],
            "error": self.colors["error"],
        }.get(level, self.colors["muted"])


class RailButton(ft.Container):
    """One page button in the rail. The selected page is marked by fill and by a bar."""

    def __init__(self, name: str, on_select: Callable[[str], None], colors: dict[str, str]) -> None:
        super().__init__(
            padding=ft.Padding.symmetric(horizontal=flet_theme.GAP["md"], vertical=flet_theme.GAP["sm"]),
            border_radius=flet_theme.CONTROL_RADIUS,
            ink=True,
            on_click=lambda _e: on_select(name),
            content=ft.Text(name, size=13),
        )
        self.name = name
        self.colors = colors

    def mark(self, selected: bool) -> None:
        self.bgcolor = self.colors["primary_container"] if selected else None
        self.content.color = self.colors["on_primary_container"] if selected else self.colors["on_surface"]
        self.content.weight = ft.FontWeight.W_600 if selected else ft.FontWeight.NORMAL


class Shell(ft.Column):
    """Rail, action bar, page area, status line and the bottom history slot."""

    def __init__(self, specs: list[PageSpec], *, dark: bool = True) -> None:
        super().__init__(expand=True, spacing=flet_theme.GAP["sm"])
        self.colors = flet_theme.canvas_colors(dark)
        self.specs = specs
        self.pages: dict[str, Page] = {}
        self.current = ""
        self.status = ft.Text("", size=12, color=self.colors["muted"])
        self.status_bg = ft.Container(content=self.status, padding=ft.Padding.symmetric(
            horizontal=flet_theme.GAP["md"], vertical=flet_theme.GAP["xs"]))
        self.action_bar = ft.Row(spacing=flet_theme.GAP["sm"])
        self.bottom = ft.Container()
        self.body = ft.Container(expand=True)
        self.buttons: dict[str, RailButton] = {}
        self.rail = ft.Container()
        self.pane = ft.Column(expand=True)
        self._build()

    def _build(self) -> None:
        self.rail.content = ft.Column([], spacing=2)
        self.rail.width = 170
        self.rail.padding = ft.Padding.only(right=flet_theme.GAP["md"])
        for spec in self.specs:
            button = RailButton(spec.name, self.open, self.colors)
            self.buttons[spec.name] = button
            self.rail.content.controls.append(button)
        self.pane.controls = [self.action_bar, self.body]
        self.pane.spacing = flet_theme.GAP["sm"]
        self.main_row = ft.Row([self.rail, self.pane], expand=True,
                               vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.main_area = ft.Container(content=self.main_row, expand=True, padding=flet_theme.GAP["md"])
        self.controls = [self.main_area, self.status_bg, self.bottom]

    def open(self, name: str) -> None:
        if name == self.current and name in self.pages:
            return
        spec = next(s for s in self.specs if s.name == name)
        if name not in self.pages:
            self.pages[name] = spec.build(self)
        self.current = name
        self.body.content = self.pages[name]
        for label, button in self.buttons.items():
            button.mark(label == name)
        self._refresh()

    def _refresh(self) -> None:
        try:
            self.update()
        except RuntimeError:
            return  # built before it is on a page: the next mount paints it

    def step(self, delta: int) -> None:
        names = [s.name for s in self.specs]
        index = names.index(self.current) if self.current in names else 0
        self.open(names[(index + delta) % len(names)])

    def goto(self, index: int) -> None:
        names = [s.name for s in self.specs]
        self.open(names[min(index, len(names) - 1)])

    def note(self, text: str, *, level: str = "info") -> None:
        page = self.pages.get(self.current)
        if page is not None:
            page.note(text, level=level)
        self.status.value = text
        self.status.color = {"error": self.colors["accent"], "ok": self.colors["ok"]}.get(level, self.colors["muted"])

    def say(self, text: str) -> None:
        """Write the window status line. Safe before the shell is on the page."""
        self.status.value = text
        try:
            self.update()
        except RuntimeError:
            return  # not mounted yet: the value is already set


def shortcut(e: ft.KeyboardEvent) -> tuple[str, int] | None:
    """Map a key press to ('next' | 'prev' | 'page', index). Pure, so it can be tested."""
    key = str(e.key).lower()
    if not e.ctrl:
        return None
    if key == "tab":
        return ("next", 0) if not e.shift else ("prev", 0)
    if key in ("pagedown", "numpad pagedown"):
        return ("next", 0)
    if key in ("pageup", "numpad pageup"):
        return ("prev", 0)
    if len(key) == 1 and key.isdigit():
        return ("page", 0 if key == "0" else int(key) - 1)
    return None


def apply_shortcut(shell: Shell, e: ft.KeyboardEvent) -> bool:
    action = shortcut(e)
    if action is None:
        return False
    kind, index = action
    if kind == "next":
        shell.step(1)
    elif kind == "prev":
        shell.step(-1)
    else:
        shell.goto(index)
    return True
