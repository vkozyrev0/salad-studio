"""The window: action bar, page rail, per-page note lines, status line, history strip.

Pages are controls with a ``note`` line of their own and a ``PageHost`` that
lets them say something without touching another page. The shell owns the rail
(which page is open), the keyboard shortcuts that move between pages, and the
two lines that report what happened: the open page's note and the window's
status. It does not repaint itself while it builds: Flet pushes a control the
first time it lands on the page, and an ``update()`` called on a control the
client has not seen yet blanks the whole window.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

import flet as ft

from salad_studio import flet_theme
from salad_studio.flet_pump import refresh

TAB_ORDER: tuple[str, ...] = (
    "Config",
    "Prompt Settings",
    "Tokens",
    "LoRAs",
    "Prompt Editor",
    "Prompt Assist",
    "Prompt Catalog",
    "Import",
    "Prompt History",
    "Queue",
    "Logs",
)
RAIL_WIDTH = 170
STRIP_HEIGHT = 96


@dataclass(frozen=True)
class PageSpec:
    name: str
    build: Callable[["PageHost"], ft.Control]


class PageHost(Protocol):
    """What a page may do with the window."""

    def note(self, text: str, *, level: str = "info") -> None: ...

    def log(self, level: str, text: str) -> None: ...

    colors: dict[str, str]

    def dialog(self, title: str, body: str, *, level: str = "info") -> None: ...

    def ask(self, title: str, body: str, on_yes: Callable[[], None]) -> None: ...


class Page(ft.Column):
    """One page: a heading, a note line, and the page's own content."""

    def __init__(self, title: str, subtitle: str, colors: dict[str, str]) -> None:
        super().__init__(expand=True, spacing=flet_theme.GAP["sm"], tight=True)
        self.colors = colors
        self.heading = title
        self.note_text = ft.Text("", size=12, color=colors["muted"], max_lines=3, selectable=True)
        self.body = ft.Container(expand=True)
        self.controls = [
            ft.Row(
                [
                    ft.Text(title, size=17, weight=ft.FontWeight.W_600, color=colors["on_surface"]),
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
        self.note_text.color = self.colors[level] if level in self.colors else self.colors["muted"]


class RailButton(ft.Container):
    """One page button in the rail. The selected page is marked by fill and by weight."""

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
        self.mark(False)

    def mark(self, selected: bool) -> None:
        self.bgcolor = self.colors["primary_container"] if selected else None
        self.content.color = self.colors["on_primary_container"] if selected else self.colors["on_surface"]
        self.content.weight = ft.FontWeight.W_600 if selected else ft.FontWeight.NORMAL


class HistoryStrip(ft.Container):
    """The bottom strip: tall ◀ | thumbnails | tall ▶. A click opens a plate.

    A Flet control's fields can only be set after ``ft.Row.__init__`` has run,
    so the children are built first and attached through attributes afterwards.
    """

    def __init__(self, colors: dict[str, str], on_open: Callable[[Any], None]) -> None:
        self.colors = colors
        self.on_open = on_open
        self.list = ft.ListView(horizontal=True, spacing=6, expand=True, height=STRIP_HEIGHT - 12)
        self.empty = ft.Text("No plates yet. A finished render appears here.",
                             size=12, color=colors["muted"])
        super().__init__(
            height=STRIP_HEIGHT,
            content=ft.Row(
                [
                    ft.TextButton("◀", on_click=lambda _e: self.scroll(-3), tooltip="Older"),
                    ft.Stack([self.list, self.empty], expand=True),
                    ft.TextButton("▶", on_click=lambda _e: self.scroll(3), tooltip="Newer"),
                ],
                spacing=flet_theme.GAP["sm"],
            ),
        )

    def scroll(self, delta: int) -> None:
        try:
            self.list.scroll_to(offset=(self.list.scroll_offset or 0) + delta * 120, duration=150)
        except (RuntimeError, AttributeError):
            pass

    def show(self, thumbs: list[tuple[str, bytes | None]], open_index: Callable[[int], None]) -> None:
        self.list.controls.clear()
        for index, (name, png) in enumerate(thumbs):
            self.list.controls.append(
                ft.Container(
                    width=STRIP_HEIGHT - 16,
                    height=STRIP_HEIGHT - 16,
                    border_radius=6,
                    bgcolor=self.colors["surface_container"],
                    tooltip=name,
                    on_click=lambda _e, i=index: open_index(i),
                    content=ft.Image(src=png, fit=ft.BoxFit.CONTAIN, expand=True)
                    if png else ft.Text("?", color=self.colors["muted"]),
                )
            )
        self.empty.visible = not thumbs
        self.list.visible = bool(thumbs)


class Shell(ft.Column):
    """Action bar, rail, page area, status line and the bottom history strip."""

    def __init__(self, specs: list[PageSpec], *, dark: bool = True, window: Any = None) -> None:
        super().__init__(expand=True, spacing=flet_theme.GAP["sm"], tight=True)
        # The window every page reaches through its host. A page built by the
        # shell gets the window, never the shell: the shell has no services.
        self.window = window
        self.dark = dark
        self.colors = flet_theme.canvas_colors(dark)
        self.specs = specs
        # Pages are built the first time they open, then kept. Flet mounts a
        # control only once it lands on the page, so a page is built while the
        # shell is already on screen (see ``flet_app.build``).
        self.pages: dict[str, Page] = {}
        self.current = ""
        self.status = ft.Text("", size=12, color=self.colors["muted"], selectable=True)
        self.status_bg = ft.Container(
            content=self.status,
            padding=ft.Padding.symmetric(horizontal=flet_theme.GAP["md"], vertical=flet_theme.GAP["xs"]),
        )
        self.action_bar = ft.Row(spacing=flet_theme.GAP["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.strip = HistoryStrip(self.colors, on_open=lambda _p: None)
        # One non-tight column holds the open page for the shell's lifetime:
        # a page swapped into a tight column is laid out at zero height and the
        # pane paints blank (measured on flet 1.0.4).
        self.body_column = ft.Column([], expand=True)
        self.body = ft.Container(content=self.body_column, expand=True)
        self.buttons: dict[str, RailButton] = {}
        self.rail = ft.Column(spacing=2)
        self.pane = ft.Column(expand=True, tight=True, spacing=flet_theme.GAP["sm"])
        self._build()

    def _build(self) -> None:
        self.rail.width = RAIL_WIDTH
        for spec in self.specs:
            button = RailButton(spec.name, self.open, self.colors)
            self.buttons[spec.name] = button
            self.rail.controls.append(button)
        self.pane.controls = [self.action_bar, self.body]
        self.main_row = ft.Row(
            [ft.Container(self.rail, padding=ft.Padding.only(right=flet_theme.GAP["md"])), self.pane],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.main_area = ft.Container(content=self.main_row, expand=True)
        self.controls = [self.main_area, self.status_bg, self.strip]

    def open(self, name: str, *, refresh_now: bool = True) -> Page:
        """Show a page, building it the first time, and hand it back.

        Only the body is repainted: the rail's marks go out with it. Repainting
        the whole shell covers the LoRAs page's table, for a reason not found.
        """
        if name not in self.pages:
            spec = next((s for s in self.specs if s.name == name), None)
            if spec is None:
                return None
            self.pages[name] = spec.build(self.window if self.window is not None else self)
        self.current = name
        self.body_column.controls.clear()
        self.body_column.controls.append(self.pages[name])
        for label, button in self.buttons.items():
            button.mark(label == name)
        if refresh_now:
            refresh(self.body)
        return self.pages[name]

    def refresh(self) -> None:
        refresh(self)

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
        self.say(text, level=level)

    def say(self, text: str, *, level: str = "info") -> None:
        """Write the window status line, and the open page's note, when it can."""
        self.status.value = text
        self.status.color = {
            "error": self.colors["error"],
            "warn": self.colors["warn"],
            "ok": self.colors["ok"],
        }.get(level, self.colors["muted"])
        refresh(self.status)


def shortcut(e: ft.KeyboardEvent) -> tuple[str, int] | None:
    """Map a key press to ('next' | 'prev' | 'first' | 'last' | 'page', index). Pure."""
    key = str(e.key or "").lower().replace("control+", "").replace("ctrl+", "")
    if not e.ctrl:
        return None
    if key == "tab":
        return ("next", 0) if not e.shift else ("prev", 0)
    if key in ("pagedown", "numpad pagedown", "numpad2"):
        return ("next", 0)
    if key in ("pageup", "numpad pageup", "numpad9"):
        return ("prev", 0)
    if len(key) == 1 and key.isdigit():
        return ("first", 0) if key == "0" else ("page", int(key) - 1)
    return None


def page_index(key: str, count: int) -> int | None:
    """Ctrl+1..9 is page 1..9, Ctrl+0 is the last page; a digit past the end clamps."""
    if not (len(key) == 1 and key.isdigit()):
        return None
    index = count - 1 if key == "0" else int(key) - 1
    return max(0, min(index, count - 1))


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
