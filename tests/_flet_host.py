"""A window stand-in for a page test: the window's fields, its dialogs, and a service layer.

A page reads ``host.form``, ``host.profile`` and ``host.services`` and writes
through ``note``/``log``/``dialog``/``ask``. This object keeps all of that and
never repaints, so a test types into a page's fields, calls one of the page's
button handlers, then reads the page's fields and the stores back.

``FakeServices.background`` runs ``work`` on the calling thread and hands the
result to ``done`` at once; an exception is the result, as the real
``AppServices.background`` reports it. ``hold`` keeps the next call in flight
until ``release`` runs it.
"""
from __future__ import annotations

from typing import Any, Callable

from salad_studio import flet_theme, profiles, tokens
from salad_studio.flet_pages import Form, page as build_page
from salad_studio.flet_shell import Page


class FakeServices:
    def __init__(self) -> None:
        self.offers: dict[str, dict[str, Any]] = {}
        self.busy_flags: dict[str, bool] = {}
        self.snaps: dict[str, Any] = {}
        self.salad_word = ""
        self.gen_jobs = 0
        self.busy = False
        self.on_generated: Callable[[Any], None] | None = None
        self.on_timer: Callable[[str], None] | None = None
        self.log_lines: list[tuple[str, str]] = []
        self.salad_logs = ""
        self.gen_started = 0.0
        self.salad_key_error = ""
        self.held: list[tuple[Callable[[], Any], Callable[[Any], None]]] = []
        self.work: list[Callable[[], Any]] = []
        self.hold = False
        self.closed = False

    def salad_key(self) -> str:
        return self.token("salad")

    def token(self, kind: str) -> str:
        return tokens.read_token(kind)

    def log(self, level: str, text: str) -> None:
        self.log_lines.append((level, text))

    def set_salad_logs(self, text: str) -> None:
        self.salad_logs = text

    def background(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        self.work.append(work)
        if self.hold:
            self.held.append((work, done))
            return
        self.run(work, done)

    def run(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        try:
            result: Any = work()
        except Exception as exc:  # noqa: BLE001 - a page shows its worker's failure
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
    """The flet Page a page is handed: the overlay, the clipboard, what has been sent."""

    def __init__(self) -> None:
        self.overlay: list[Any] = []
        self.clipboard = ""

    def set_clipboard(self, text: str) -> None:
        self.clipboard = text

    def clipboard_get(self) -> str:
        return self.clipboard


class Screen:
    """The shell's page area: the open page and the window's status line."""

    def __init__(self, pages: dict[str, Page]) -> None:
        self.pages = pages
        self.current = ""
        self.colors = flet_theme.canvas_colors(True)
        self.status = type("Status", (), {"value": "", "color": ""})()

    def open(self, name: str, **_kwargs: Any) -> None:
        if name in self.pages:
            self.current = name


class Host:
    """What a page sees of the window. Every note, log line, dialog and question is kept."""

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
        self.screen = Screen(self.pages)
        self.pump = _ImmediatePump()
        self.colors = flet_theme.canvas_colors(True)

    # -- PageHost

    def note(self, text: str, *, level: str = "info") -> None:
        self.notes.append((level, text))

    def log(self, level: str, text: str) -> None:
        self.logs.append((level, text))
        self.services.log(level, text)

    def dialog(self, title: str, body: str, *, level: str = "info") -> None:
        self.dialogs.append((level, title, body))

    def guard(self, flag: str, *buttons: Any) -> bool:
        if self.services.busy_flags.get(flag):
            self.notes.append(("warn", f"{flag} already running"))
            return False
        self.services.busy_flags[flag] = True
        for button in buttons:
            button.disabled = True
        return True

    def release(self, flag: str, *buttons: Any) -> None:
        self.services.busy_flags[flag] = False
        for button in buttons:
            button.disabled = False

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

    def build_page(self, name: str) -> Page:
        """Build a page the way the window does, with repaints recorded rather than sent."""
        import flet as ft
        from unittest import mock

        with mock.patch.object(ft.Page, "update", _record_repaint):
            return build_page(self, name)

    def open_page(self, name: str) -> Any:
        """Open a page, building it once, as the window's ``open_page`` does."""
        if name not in self.pages:
            self.pages[name] = self.build_page(name)
        self.screen.open(name)
        return self.pages[name]

    def store_page(self, name: str, page: Any) -> None:
        """Put a page where ``open_page`` finds it, as a window's shell would."""
        self.pages[name] = page

    # -- assertions in a test's words

    def last_note(self) -> tuple[str, str]:
        return self.notes[-1]

    def answer_yes(self, pick: Callable[[str], bool] | None = None) -> list[str]:
        """Answer each question as ``pick(body)`` says; the default answers Yes to all."""
        answers: list[str] = []
        pending, self.asks = self.asks, []
        for _title, body, on_yes in pending:
            answers.append(body)
            if pick is None or pick(body):
                on_yes()
        return answers


def _record_repaint(page: Any, *controls: Any) -> None:
    """A repaint lands once the page is mounted, which is what the window does at startup."""


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
