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
from salad_studio import flet_widgets
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
RAIL_WIDTH = 196
STRIP_HEIGHT = 96
BAR_HEIGHT = 46
# The window's line while nothing has happened yet: the first step of the
# workflow the pages follow, and the way across them.
REST_TEXT = "Start on Config: pick a profile and its target.   Ctrl+Tab moves between pages."


@dataclass(frozen=True)
class PageSpec:
    name: str
    build: Callable[["PageHost"], ft.Control]


def page_number(title: str) -> str:
    """Where the page sits on the rail, as a two-digit label: "04"."""
    if title not in TAB_ORDER:
        return ""
    return f"{TAB_ORDER.index(title) + 1:02d}"


class PageHost(Protocol):
    """What a page may do with the window."""

    def note(self, text: str, *, level: str = "info") -> None: ...

    def log(self, level: str, text: str) -> None: ...

    colors: dict[str, str]

    def dialog(self, title: str, body: str, *, level: str = "info") -> None: ...

    def ask(self, title: str, body: str, on_yes: Callable[[], None]) -> None: ...


class Page(ft.Column):
    """One page: its title capsule, a note line, and the page's own content.

    The capsule is the window's one loud element: the page's two-digit number
    from the rail, a rose rule, then the title set heavy. The number is where
    the page sits, so the capsule and the rail agree.
    """

    def __init__(self, title: str, subtitle: str, colors: dict[str, str]) -> None:
        super().__init__(expand=True, spacing=flet_theme.GAP["sm"], tight=True)
        self.colors = colors
        self.heading = title
        self.note_text = ft.Text("", size=12, color=colors["muted"], max_lines=3, selectable=True)
        self.body = ft.Container(expand=True)
        self.number = ft.Text(page_number(title), style=flet_theme.plate_type(colors))
        self.pillow = ft.Row(
            [
                self.number,
                ft.Container(width=1, height=34, bgcolor=colors["accent"]),
                ft.Column(
                    [
                        ft.Text(title, style=flet_theme.title_type(colors)),
                        ft.Text(subtitle, size=12, color=colors["muted"]),
                    ],
                    spacing=2,
                    tight=True,
                ),
            ],
            spacing=flet_theme.GAP["md"],
                vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self.controls = [self.pillow, self.note_text, self.body]

    def note(self, text: str, *, level: str = "info") -> None:
        self.note_text.value = text
        self.note_text.color = self.colors[level] if level in self.colors else self.colors["muted"]


class RailButton(ft.Container):
    """One page button in the rail: its number, a hairline, its name.

    The selected page is marked by a tinted fill and by a heavier name, and its
    number turns rose, the same mark the open page's capsule carries.
    """

    def __init__(self, name: str, on_select: Callable[[str], None], colors: dict[str, str]) -> None:
        self.number = ft.Text(page_number(name), size=10, color=colors["muted"])
        self.name_label = ft.Text(name, size=13)
        super().__init__(
            padding=ft.Padding.symmetric(horizontal=flet_theme.GAP["md"],
                                         vertical=flet_theme.GAP["xs"] + 2),
            border_radius=flet_theme.CONTROL_RADIUS,
            ink=True,
            on_click=lambda _e: on_select(name),
            # The row is centred, not stretched: a Row that fills its container
            # leaves its children no height here and the number never draws.
            content=ft.Row([self.number, self.name_label], spacing=flet_theme.GAP["md"],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER, height=22),
        )
        self.name = name
        self.colors = colors
        self.mark(False)

    def mark(self, selected: bool) -> None:
        self.bgcolor = self.colors["primary_container"] if selected else None
        self.name_label.color = self.colors["on_primary_container"] if selected else self.colors["on_surface"]
        self.name_label.weight = ft.FontWeight.W_600 if selected else ft.FontWeight.NORMAL
        self.number.color = (self.colors["accent"] if selected else self.colors["muted"])


class HistoryStrip(ft.Container):
    """The bottom strip: tall ◀ | thumbnails | tall ▶. A click opens a plate.

    The keyboard ring marks the thumb Enter would open. It moves by click, and
    by Left, Right, Home and End while the strip holds the focus (see
    ``Shell._on_key``). The ring is a rose border plus a corner tick, so the
    mark does not rest on colour alone.
    """

    def __init__(self, colors: dict[str, str], on_open: Callable[[Any], None]) -> None:
        self.colors = colors
        self.on_open = on_open
        self._strip_scroll = None
        self._offset = 0.0
        self.ring: int | None = None
        # The shell, which owns which place the keyboard is on.
        self.owner: Any = None
        self.empty = ft.Text("No plates yet. A finished render appears here.",
                             size=12, color=colors["muted"])
        # A ListView asked to expand paints at zero height inside this Row (flet
        # 1.0.4), and an empty one then draws a dark block above the strip. It
        # is given its height, and it stays out of the tree until a plate exists.
        self.list = ft.ListView(horizontal=True, spacing=6, height=STRIP_HEIGHT - 32, visible=False)
        # The strip is the window's last band of chrome, like the bar at the top;
        # its contents carry the pad, so the band meets the edges.
        super().__init__(
            height=STRIP_HEIGHT,
            bgcolor=colors["chrome"],
            border=ft.Border.only(top=ft.BorderSide(1, colors["outline"])),
            padding=ft.Padding.only(left=flet_theme.GAP["lg"], right=flet_theme.GAP["lg"],
                                    top=flet_theme.GAP["xs"], bottom=flet_theme.GAP["xs"]),
            on_click=self.claim,
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
        """Move a few thumbnails. The offset is kept here: flet's ListView reports none."""
        self._offset = max(0.0, self._offset + delta * 120)
        if self._strip_scroll is not None:
            self._strip_scroll(self._offset)

    def show(self, thumbs: list[tuple[str, bytes | None]], open_index: Callable[[int], None]) -> None:
        self.list.controls.clear()
        for index, (name, png) in enumerate(thumbs):
            self.list.controls.append(
                ft.Container(
                    width=STRIP_HEIGHT - 28,
                    height=STRIP_HEIGHT - 28,
                    border_radius=6,
                    bgcolor=self.colors["surface_container"],
                    tooltip=name,
                    on_click=lambda _e, i=index: self._click(i, open_index),
                    content=ft.Image(src=png, fit=ft.BoxFit.CONTAIN, expand=True)
                    if png else ft.Text("?", color=self.colors["muted"]),
                )
            )
        if self.ring is not None and self.ring >= len(thumbs):
            self.ring = len(thumbs) - 1 if thumbs else None
        self._paint_ring()
        self.empty.visible = not thumbs
        self.list.visible = bool(thumbs)

    def _click(self, index: int, open_index: Callable[[int], None]) -> None:
        self.mark(index)
        open_index(index)

    def mark(self, index: int) -> None:
        """Put the ring on a thumb, or take it off with None."""
        self.ring = index if 0 <= index < len(self.list.controls) else None
        self._paint_ring()

    def step(self, delta: int) -> None:
        """Move the ring and stop at the ends. The first press puts it on the first thumb."""
        if self.ring is None:
            self.mark(0)
        else:
            self.mark(max(0, min(len(self.list.controls) - 1, self.ring + delta)))

    def first(self) -> None:
        self.mark(0)

    def last(self) -> None:
        self.mark(len(self.list.controls) - 1)

    def claim(self, _e: Any = None) -> None:
        """A click on the strip hands its thumbs the arrow keys and Enter."""
        self.owner.focus = "strip"

    def open_ringed(self) -> None:
        if self.ring is not None and 0 <= self.ring < len(self.list.controls):
            self.list.controls[self.ring].on_click(ft.ControlEvent("0", "tap"))

    def _paint_ring(self) -> None:
        for index, thumb in enumerate(self.list.controls):
            rung = index == self.ring
            thumb.border = ft.Border.all(2, self.colors["accent"] if rung else self.colors["outline"])
            image = thumb.content
            if isinstance(image, ft.Image):
                image.border = (ft.Border.only(left=ft.BorderSide(6, self.colors["accent"]))
                                if rung else None)


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
        # Which of the window's two selectable places the arrows move: the open
        # page's table, or the history strip. A click on either claims it.
        self.focus = "page"
        # At rest the status line says where a first run starts and how to
        # leave the page; the first note, message or error replaces it.
        self.status = ft.Text(REST_TEXT, size=12, color=self.colors["muted"], selectable=True)
        # The line is a Row, as a bar is: a Column whose only child is tight is
        # laid out as a Row anyway, and a bare Text in one wraps as narrow as
        # its first words.
        self.status_bg = ft.Container(
            content=ft.Row([self.status], spacing=0),
            bgcolor=self.colors["chrome"],
            padding=ft.Padding.symmetric(horizontal=flet_theme.GAP["lg"], vertical=flet_theme.GAP["xs"]),
        )
        self.action_bar = ft.Row(spacing=flet_theme.GAP["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.strip = HistoryStrip(self.colors, on_open=lambda _p: None)
        self.strip.owner = self
        self.strip._strip_scroll = self.scroll_strip
        # One non-tight column holds the open page for the shell's lifetime:
        # a page swapped into a tight column is laid out at zero height and the
        # pane paints blank (measured on flet 1.0.4).
        self.body_column = ft.Column([], expand=True)
        self.body = ft.Container(
            content=self.body_column, expand=True, padding=ft.Padding.only(top=flet_theme.GAP["xs"]))
        self.buttons: dict[str, RailButton] = {}
        self.rail = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO)
        self.pane = ft.Column([self.body], expand=True, tight=True, spacing=flet_theme.GAP["sm"])
        self._build()

    def _build(self) -> None:
        """The rail is a solid panel; the page area sits on the lighter ground.

        The rail is a fixed-width panel from the bar to the status line; the page
        area expands into the rest, and the two stretch to the same height.
        """
        # Not ``self.rail.width``: Column.width is the rail column's own field and
        # assigning a number to it fails. The container around the rail is sized.
        # The rail keeps the only persistent label in the window: eleven numbers
        # mean nothing until something says what they index.
        self.rail_label = ft.Container(
            content=ft.Text("PAGES", size=10, weight=ft.FontWeight.W_600,
                            color=self.colors["muted"]),
            padding=ft.Padding.only(left=flet_theme.GAP["md"] + 26, top=flet_theme.GAP["sm"],
                                    bottom=flet_theme.GAP["xs"]),
        )
        self.rail.controls.append(self.rail_label)
        for spec in self.specs:
            button = RailButton(spec.name, self.open, self.colors)
            self.buttons[spec.name] = button
            self.rail.controls.append(button)
        rail_panel = ft.Container(
            content=self.rail,
            width=RAIL_WIDTH,
            bgcolor=self.colors["chrome"],
            padding=ft.Padding.only(left=flet_theme.GAP["sm"], right=flet_theme.GAP["sm"]),
        )
        # A container, so the page area owns its own ground and pad.
        self.page_area = ft.Container(
            content=self.pane,
            expand=True,
            bgcolor=self.colors["page"],
            padding=ft.Padding.only(left=flet_theme.GAP["lg"], right=flet_theme.GAP["lg"],
                                    top=flet_theme.GAP["md"], bottom=flet_theme.GAP["sm"]),
        )
        # The bar runs the whole width over the rail; the rail fills what is
        # left above the status line; the strip is the last band.
        self.bar = ft.Container(
            content=self.action_bar,
            height=BAR_HEIGHT,
            bgcolor=self.colors["chrome"],
            border=ft.Border.only(bottom=ft.BorderSide(1, self.colors["outline"])),
            padding=ft.Padding.only(left=flet_theme.GAP["lg"], right=flet_theme.GAP["lg"],
                                    top=flet_theme.GAP["xs"], bottom=flet_theme.GAP["xs"]),
        )
        self.main_row = ft.Row(
            [rail_panel, self.page_area],
            spacing=0,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.controls = [self.bar, self.main_row, self.status_bg, self.strip]

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
        self.focus = "page"
        self.body_column.controls.clear()
        self.body_column.controls.append(self.pages[name])
        for label, button in self.buttons.items():
            button.mark(label == name)
        if refresh_now:
            refresh(self.body)
        return self.pages[name]

    def _on_key(self, e: ft.KeyboardEvent) -> bool:
        """Route one key press. True when the window used it.

        Ctrl+Tab, Ctrl+PgUp/PgDn and Ctrl+digit switch pages from anywhere.
        Without Ctrl the keys belong to the focused place: arrows move the open
        page's table selection or the strip's ring, Home and End jump, and
        Enter opens the ringed plate.
        """
        if e.ctrl:
            return apply_shortcut(self, e)
        action = action_for(key_name(e))
        if action is None:
            return False
        if self.focus == "strip":
            if action == "enter":
                self.strip.open_ringed()
            elif action == "home":
                self.strip.first()
            elif action == "end":
                self.strip.last()
            elif action in ("up", "left", "down", "right"):
                self.strip.step(-1 if action in ("up", "left") else 1)
            else:
                return False
            return True
        page = self.pages.get(self.current)
        if (action == "enter" or page is None or flet_widgets.field_has_focus()
                or not hasattr(page, "move_selection")):
            return False
        moves = {"up": "prev", "left": "prev", "down": "next", "right": "next",
                 "home": "first", "end": "last"}
        if action not in moves:
            return False
        page.move_selection(moves[action])
        return True

    def scroll_strip(self, offset: float) -> None:
        """Move the history strip to ``offset``, from the frame loop: flet's scroll is a coroutine."""
        async def move() -> None:
            try:
                await self.strip.list.scroll_to(offset=offset, duration=150)
            except (RuntimeError, AttributeError):
                return

        if getattr(self.window, "pump", None) is not None:
            self.window.pump.schedule(lambda: self.window.page.run_task(move))
        else:
            self.strip._offset = offset

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


# Keys by what the window does with them. Flutter and flet name the same key
# differently across versions ("Arrow Left", "Left", "arrowLeft"), so each key
# is matched by its letters rather than by one spelling.
KEYS = {
    "next": ("tab", "pagedown", "numpadpagedown", "numpad2"),
    "prev": ("pageup", "numpadpageup", "numpad9"),
    "up": ("arrowup", "up", "numpad8"),
    "down": ("arrowdown", "down", "numpad2"),
    "left": ("arrowleft", "left", "numpad4"),
    "right": ("arrowright", "right", "numpad6"),
    "home": ("home",),
    "end": ("end",),
    "enter": ("enter", "numpadenter"),
    "space": ("space", "numpadspace"),
}


def key_name(e: ft.KeyboardEvent) -> str:
    """The key as a compact lowercase name: "Arrow Left" and "arrowLeft" both read "arrowleft"."""
    return str(getattr(e, "key", "") or "").lower().replace(" ", "").replace("_", "")


def action_for(key: str) -> str | None:
    """What ``KEYS`` says ``key`` does, remembering a numpad spelling for the digits."""
    for action, names in KEYS.items():
        for name in names:
            if name.lower().replace(" ", "").replace("_", "") == key:
                return f"{action} numpad" if name.startswith("numpad") else action
    return None


def _text_field_focused(page: Any) -> bool:
    """True when the keyboard is in a field, which keeps the arrows and Tab for editing."""
    current = getattr(page, "window", None)
    return bool(getattr(current, "focused", False)) if current is not None else False
