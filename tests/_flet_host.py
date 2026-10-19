"""A window stand-in for a page test: the window's fields, its dialogs, and a service layer.

A page reads ``host.form``, ``host.profile`` and ``host.services`` and writes
through ``note``/``log``/``dialog``/``ask``. This object keeps all of that
without a client, a loop or a thread, so a test types into the page's controls,
presses the page's buttons and then reads the controls and the stores back.

``FakeServices.background`` runs ``work`` on the calling thread and hands its
result to ``done`` at once, and records an exception as the result, which is
what the real ``AppServices.background`` does. ``hold`` leaves the next call in
flight, the way a slow network call does, until ``release`` runs it.
``open_page`` builds and records the other page a page opens, the way the
window's shell does. ``screen`` stands in for the shell's page area.
"""
from __future__ import annotations

from typing import Any, Callable

from salad_studio import flet_theme, profiles, tokens
from salad_studio.flet_pages import Form, page as build_page
from salad_studio.flet_shell import Page


class FakeServices:
    def __init__(self) -> None:
        self.offers: dict[str, dict[str, Any]] = {}
        self.offers_selected: dict[str, Any] | None = None
        self.busy_flags: dict[str, bool] = {}
        self.snaps: dict[str, Any] = {}
        self.salad_word = ""
        self.gen_jobs = 0
        self.busy = False
        self.on_generated: Callable[[Any], None] | None = None
        self.on_timer: Callable[[str], None] | None = None
        self.log_lines: list[tuple[str, str]] = []
        self.held: list[tuple[Callable[[], Any], Callable[[Any], None]]] = []
        self.work: list[Callable[[], Any]] = []
        self.hold = False
        self.closed = False

    def salad_key(self) -> str:
        return self.token("salad")

    def token(self, kind: str) -> str:
        return tokens.read_token(kind)

    def background(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        self.work.append(work)
        if self.hold:
            self.held.append((work, done))
            return
        self.run(work, done)

    def run(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        try:
            result: Any = work()
        except Exception as exc:  # noqa: BLE001 - the page shows a worker's failure
            result = exc
        if not self.closed:
            done(result)

    def release(self) -> None:
        held, self.held = self.held, []
        self.hold = False
        for work, done in held:
            self.run(work, done)

    def stop(self) -> None:
        self.closed = True

    def thumbnail(self, path: Any, size: int = 140) -> bytes | None:
        return None


class FakePage:
    """The flet Page the window hands a page: the overlay, the clipboard, what is attached."""

    def __init__(self) -> None:
        self.overlay: list[Any] = []
        self.clipboard = ""
        self.attached: list[Any] = []

    def attach(self, control: Any) -> None:
        self.attached.append(control)

    def contains(self, control: Any) -> bool:
        return any(control is n for n in walk(self.attached))

    def set_clipboard(self, text: str) -> None:
        self.clipboard = text

    def clipboard_get(self) -> str:
        return self.clipboard


class Screen:
    """The shell's page area: which page is open, and the status line under it."""

    def __init__(self, pages: dict[str, Page]) -> None:
        self.pages = pages
        self.current = ""
        self.colors = flet_theme.canvas_colors(True)
        self.attached: list[Any] = []
        self.status = type("Status", (), {"value": "", "color": ""})()

    def contains(self, control: Any) -> bool:
        return any(control is n for n in walk(self.attached))

    def open(self, name: str | Any, *, refresh_now: bool = True) -> None:
        if isinstance(name, str) and name in self.pages:
            self.current = name
            return
        config = self.pages.get("Config")
        for attr in CONFIG_SECTIONS.values():
            if config is not None and name is getattr(config, attr, None):
                self.attached.append(name)

    def say(self, text: str, *, level: str = "info") -> None:
        self.status.value = text

    def note(self, text: str, *, level: str = "info") -> None:
        self.say(text, level=level)


# The Config page's four sections, and which control each one draws.
CONFIG_SECTIONS: dict[str, str] = {
    "policy": "policy_section",
    "images": "images_section",
    "vast": "vast_section",
}


class Host:
    """What a page sees of the window. Every note, line and dialog is kept.

    A page repaints a control only after Flet has been given it, so
    ``control.update()`` raises until the section that holds it has been shown:
    the section tab hands its section to Flet, as the page does. A control the
    host never hands over at all repaints freely.
    """

    def __init__(self) -> None:
        self.form = Form()
        self.profile = profiles.SaladProfile(name="klein")
        self.services = FakeServices()
        self.page = FakePage()
        self.notes: list[tuple[str, str]] = []
        self.logs: list[tuple[str, str]] = []
        self.dialogs: list[tuple[str, str, str]] = []
        self.asks: list[tuple[str, str, Callable[[], None]]] = []
        self.pages: dict[str, Page] = {}
        self.page.missing = self._missing
        self.screen = Screen(self.pages)
        self.screen.missing = self._missing
        self.pump = _ImmediatePump()
        self.colors = flet_theme.canvas_colors(True)

    # -- PageHost

    def note(self, text: str, *, level: str = "info") -> None:
        self.notes.append((level, text))

    def log(self, level: str, text: str) -> None:
        self.logs.append((level, text))
        self.services.log_lines.append((level, text))

    def dialog(self, title: str, body: str, *, level: str = "info") -> None:
        self.dialogs.append((level, title, body))

    def ask(self, title: str, body: str, on_yes: Callable[[], None]) -> None:
        self.asks.append((title, body, on_yes))

    # -- the window's own methods a page calls

    def stored_profile(self) -> profiles.SaladProfile | None:
        return profiles.load_all().get(self.form.name)

    def apply_profile(self, p: profiles.SaladProfile) -> None:
        self.profile = p
        self.form = Form().from_profile(p)
        settings = self.pages.get("Prompt Settings")
        if settings is not None and hasattr(settings, "show_form"):
            settings.show_form()

    def load_profiles(self) -> None:
        """What the window does at startup: the built-ins exist, the active one is on the form."""
        profiles.ensure_builtin_profiles()
        active = profiles.get_active() or "klein"
        self.apply_profile(profiles.load_all().get(active))

    def open_page(self, name: str) -> Any:
        """Open a page, building it once, as the window's ``open_page`` does."""
        if name not in self.pages:
            self.pages[name] = build_page(self, name)
        self.screen.open(name)
        return self.pages[name]

    def _missing(self, control: Any) -> bool:
        """True until the section that holds ``control`` has been shown."""
        config = self.pages.get("Config")
        if config is None or control is config or control is config.body:
            return False
        return not self.screen.contains(control)

    def store_page(self, name: str, page: Any) -> None:
        """Put a page where ``open_page`` finds it, as a window's shell would."""
        self.pages[name] = page

    # -- assertions in a test's words

    def messages(self) -> list[str]:
        return [text for _level, text in self.notes]

    def last_note(self) -> tuple[str, str]:
        return self.notes[-1]

    def answer_yes(self, pick: Callable[[str], bool] | None = None) -> list[str]:
        """Answer each confirm as ``pick(body)`` says; the default deletes everything."""
        answers: list[str] = []
        pending, self.asks = self.asks, []
        for _title, body, on_yes in pending:
            answers.append(body)
            if pick is None or pick(body):
                on_yes()
        return answers


class _ImmediatePump:
    """The page's pump: a delayed call runs when it is scheduled."""

    def call_later(self, ms: float, fn: Callable[..., None], *args: Any, **kwargs: Any) -> int:
        fn(*args, **kwargs)
        return 1

    def every(self, ms: float, fn: Callable[..., None], *args: Any, **kwargs: Any) -> int:
        return 1

    def cancel(self, token: int | None) -> None:
        return None

    def schedule(self, fn: Callable[..., None], *args: Any, **kwargs: Any) -> None:
        fn(*args, **kwargs)


def walk(control: Any) -> list[Any]:
    """Every control under ``control``, the control itself first."""
    out: list[Any] = []
    seen: set[int] = set()

    def visit(node: Any) -> None:
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        out.append(node)
        if isinstance(node, dict):
            for value in node.values():
                visit(value)
            return
        if isinstance(node, (list, tuple)):
            for value in node:
                visit(value)
            return
        content = getattr(node, "content", None)
        visit(content)
        for attr in ("controls", "actions", "segments", "options", "rows", "columns", "selected"):
            visit(getattr(node, attr, None))

    visit(control)
    return out


def texts(control: Any) -> list[str]:
    """Every string a page shows: a Text's value, a field's value or label, a segment's label."""
    out: list[str] = []
    for node in walk(control):
        value = getattr(node, "value", None)
        if isinstance(value, str) and value:
            out.append(value)
        text = getattr(node, "text", None)
        if isinstance(text, str) and text:
            out.append(text)
        label = getattr(node, "label", None)
        if isinstance(label, str) and label:
            out.append(label)
    return out


def button(control: Any, label: str) -> Any:
    """The button whose text is ``label``."""
    def word(node: Any) -> str:
        # w.button passes the label straight to Flet, which keeps it as ``content``.
        content = getattr(node, "content", "")
        return content if isinstance(content, str) else str(getattr(content, "value", ""))

    found = [n for n in walk(control) if hasattr(n, "on_click") and word(n) == label]
    if len(found) != 1:
        raise AssertionError(f"{label!r} names {len(found)} buttons, not one")
    return found[0]


def press(control: Any, label: str) -> Any:
    """Click the button ``label``, as the user would."""
    return button(control, label).on_click(None)


def table_rows(table: Any) -> list[list[str]]:
    """A ``w.table``'s cells as text, one list per row."""
    out: list[list[str]] = []
    for row in getattr(table, "rows", []) or []:
        cells: list[str] = []
        for cell in row.cells:
            content = cell.content
            cells.append(str(content.value) if hasattr(content, "value") else str(content))
        out.append(cells)
    return out
