"""The Flet window. Entry point is ``app_main``.

The shell owns the rail and the lines that report what happened. Each page
module builds its own controls and calls the existing service modules; the
window holds what the Tk window held: the open profile, the knob values the
form shows, the selected LoRA ids, and the runtime services every page shares.

Build order matters. A control must not be ``update()``-ed before the client
has received it: Flet reads that as a control the client lacks and clears the
window. Pages built inside ``main`` therefore build without repainting and the
first repaint happens after ``page.add``.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import flet as ft

import hostings  # noqa: E402  top-level, as profiles.py and app.py import it

from salad_studio import desktop, flet_theme, flet_widgets as w, image_deploy, lora_store, profiles, request_json, vast
from salad_studio.flet_pump import Pump, refresh
from salad_studio.flet_pages import Form, page as build_page
from salad_studio.flet_services import STRIP_COLORS, AppServices
from salad_studio.flet_shell import PageSpec, Shell, TAB_ORDER, apply_shortcut

DEFAULT_WIDTH = 1180
DEFAULT_HEIGHT = 720

SUBTITLES: dict[str, str] = {
    "Config": "Profiles, images and the two hostings.",
    "Prompt Settings": "The graph, the knobs and the LoRAs the request carries.",
    "Tokens": "Provider keys, and what each one last answered.",
    "LoRAs": "The catalog plus the extras you add.",
    "Prompt Editor": "The JSON body POSTed to the target's /prompt.",
    "Prompt Assist": "Ask for a prompt fix, then commit it.",
    "Prompt Catalog": "Kept prompts, by short name.",
    "Import": "Paste a Comfy workflow or Civitai data, then convert.",
    "Prompt History": "Every request, with its prompt and graph.",
    "Queue": "One row per request; the container is stopped when it sits idle.",
    "Logs": "Studio and HTTP lines, secrets masked.",
}


class Window:
    """Everything a page can reach: the shell, the form, the last probe and the dialogs."""

    def __init__(self, page: ft.Page, pump: Pump, shell: Shell, *, show: bool = True) -> None:
        self.page = page
        self.show = show
        self.pump = pump
        self.shell = shell
        self.services = AppServices(pump)
        self.form = Form()
        self.profile = profiles.SaladProfile(name="klein")
        self.dialogs: list[ft.AlertDialog] = []
        # The action bar's state word. A window built without a bar can still be
        # pressed; these hold its two words until ``build_action_bar`` replaces them.
        self.gen_state = ft.Text("Idle")
        self.salad_label = ft.Text("…")
        self.services.on_log = self._repaint_logs
        self.services.on_timer = self._timer

    # -- PageHost

    @property
    def colors(self) -> dict[str, str]:
        """The palette every page draws with, read by role name."""
        return self.shell.colors

    def note(self, text: str, *, level: str = "info") -> None:
        self.shell.note(text, level=level)
        self.services.log(level if level in ("info", "ok", "warn", "error") else "info", text)

    def log(self, level: str, text: str) -> None:
        self.services.log(level, text)

    def dialog(self, title: str, body: str, *, level: str = "info") -> None:
        """D1 and D2: one message and an OK. The Tk title was always "Salad Studio"."""
        icon = ft.Icon(ft.Icons.ERROR_OUTLINE if level == "error" else ft.Icons.INFO_OUTLINE,
                       color=self.shell.colors["error"] if level == "error" else self.shell.colors["accent"])
        box = ft.AlertDialog(
            modal=True,
            title=ft.Row([icon, ft.Text(title)], spacing=8),
            content=ft.Text(body, selectable=True),
            actions=[ft.TextButton("OK", on_click=lambda _e: self._close(box))],
        )
        self._show(box)

    def ask(self, title: str, body: str, on_yes: Callable[[], None]) -> None:
        """D3: a destructive confirm. "No" only closes the box."""
        box = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(body, selectable=True),
            actions=[
                ft.TextButton("No", on_click=lambda _e: self._close(box)),
                ft.TextButton("Yes", on_click=lambda _e: (self._close(box), on_yes())),
            ],
        )
        self._show(box)

    def _show(self, box: ft.AlertDialog) -> None:
        self.dialogs.append(box)
        self.page.overlay.append(box)
        box.open = True
        refresh(box)

    def _close(self, box: ft.AlertDialog) -> None:
        box.open = False
        if box in self.dialogs:
            self.dialogs.remove(box)
        if box in self.page.overlay:
            self.page.overlay.remove(box)
        refresh(box)

    # -- repaint hooks

    def _repaint_logs(self, level: str, text: str) -> None:
        self.pump.schedule(self._repaint_logs_now)

    def _repaint_logs_now(self) -> None:
        page = self.shell.pages.get("Logs")
        if page is not None and hasattr(page, "refresh_lines"):
            try:
                page.refresh_lines()
            except RuntimeError:
                return

    def _timer(self, what: str) -> None:
        """The service's tick reached a control: the strip, the queue page, the state word."""
        if what in ("salad", "gen"):
            self.refresh_strip()
            self.salad_label.value = self.services.salad_word or "…"
        if what == "queue":
            queue_page = self.shell.pages.get("Queue")
            if queue_page is not None and hasattr(queue_page, "refresh"):
                queue_page.refresh()
        if what == "logs":
            logs_page = self.shell.pages.get("Logs")
            if logs_page is not None and hasattr(logs_page, "refresh_lines"):
                logs_page.refresh_lines()

    def open_page(self, name: str) -> Any:
        """Open a page and return it, for a page that hands its result to another."""
        self.ensure_page(name)
        self.shell.open(name)
        return self.shell.pages.get(name)

    def add_action(self, control: ft.Control) -> None:
        """Put a control in the action bar. Safe before the window has painted."""
        self.shell.action_bar.controls.append(control)
        refresh(self.shell.action_bar)

    # -- the action bar: Generate, the live state word, the replica counts

    def build_action_bar(self) -> None:
        shell = self.shell
        self.gen_button = w.button("Generate", lambda _e: self.generate(), primary=True)
        self.gen_state = ft.Text("Idle", size=12, color=shell.colors["on_surface"])
        self.strip_dots: list[ft.Text] = []
        self.strip_counts: list[ft.Text] = []
        segments: list[ft.Control] = []
        for index, color in enumerate(STRIP_COLORS):
            if index:
                segments.append(ft.Text("|", size=12, color=shell.colors["muted"]))
            dot = ft.Text("\u25cf", size=12, color=color)
            count = ft.Text("0", size=14, color=shell.colors["on_surface"])
            self.strip_dots.append(dot)
            self.strip_counts.append(count)
            segments.extend([dot, count])
        self.salad_label = ft.Text("…", size=12, color=shell.colors["muted"])
        self.check_button = w.button("Check Salad status", lambda _e: self.services.check_salad())
        shell.action_bar.controls = [
            self.gen_button,
            w.button("Clean gallery", self.clean_gallery),
            self.gen_state,
            ft.Container(expand=True),
            self.salad_label,
            *segments,
            self.check_button,
        ]
        self.refresh_strip()

    def refresh_strip(self) -> None:
        from salad_studio import salad_status

        counts = salad_status.strip_counts(self.services.snaps)
        for label, count in zip(self.strip_counts, counts):
            label.value = str(count)
        refresh(*self.strip_counts)

    def clean_gallery(self, _e: Any = None) -> None:
        paths = self.services.plates(limit=1000)
        if not paths:
            self.dialog("Salad Studio", "Gallery is already empty.")
            return

        def go() -> None:
            deleted = 0
            for path in paths:
                try:
                    path.unlink()
                    deleted += 1
                except OSError as exc:
                    self.services.log("warn", f"could not delete {path}: {exc}")
            from salad_studio import prompt_history

            thumbs = prompt_history.clear_thumbs()
            self.note(f"Deleted {deleted} gallery image(s)", level="ok")
            self.services.log("ok", f"cleaned gallery ({deleted} plates, {thumbs} thumbs)")

        self.ask("Salad Studio",
                 f"Delete {len(paths)} image(s) from disk and clear the gallery? This cannot be undone.",
                 go)

    def generate(self) -> None:
        """Generate: parse the editor JSON, read the form, then queue the render."""
        from salad_studio import generator, salad_queue

        engine = self.shell.pages.get("Prompt Editor")
        raw = engine.text() if engine is not None else ""
        try:
            payload = generator.parse_request_json(raw)
        except (ValueError, TypeError) as exc:
            self.say_refusal(f"Prompt Editor JSON is invalid: {exc}", "the Prompt Editor JSON is invalid")
            return
        try:
            p = self.form.profile(self.stored_profile())
        except ValueError as exc:
            self.say_refusal(str(exc), str(exc))
            return
        refusal = self._dispatch_refusal(payload, p)
        if refusal:
            self.say_refusal(refusal, refusal)
            return
        self.services.gen_jobs += 1
        first = self.services.gen_jobs == 1
        self._say_gen("Starting…" if first else "Queued…")
        self.shell.say("Generating…")
        self.services.log("info", f"Generate  {p.mode}  {p.gateway}  graph={p.graph}")
        self.services.remember_request(payload, p)
        self.services.on_generated = self._generated
        self.services.generate(payload, p, self.services.salad_key(),
                               salad_queue.request_checksum(payload))

    def _vast_endpoints(self) -> set[str]:
        return {str(row.get("endpoint") or "").strip()
                for row in (vast.load_doc().get("instances") or [])
                if str(row.get("endpoint") or "").strip()}

    def _dispatch_refusal(self, payload: dict[str, Any], p: profiles.SaladProfile) -> str:
        """Why this press cannot be queued at all, in the Tk app's words; "" when it can."""
        if p.mode == "vast":
            return "" if p.gateway.strip() else "No vast.ai instance is selected."
        route, refusal = profiles.plan_route(payload, p, profiles.load_all())
        if refusal:
            self.services.log("error", f"Generate blocked: {refusal}")
            return refusal
        if route is not None:
            self.services.log("info", f"Routed to profile {route.name!r} (gateway {route.profile.gateway})")
            p.gateway, p.name, p.mode = route.profile.gateway, route.profile.name, route.profile.mode
        if (p.gateway or "").strip() in self._vast_endpoints():
            return ("the Salad target holds a vast.ai instance URL, so the Salad key would be "
                    "sent to that machine. Pick the Salad gateway on the Config page, then "
                    "Generate again.")
        if not p.gateway:
            return "the gateway URL is empty"
        if not self.services.salad_key():
            return "no Salad API key is saved"
        return ""

    def say_refusal(self, dialog: str, status: str) -> None:
        """A refusal writes both surfaces: the dialog is dismissed, the status line stays."""
        self.note(f"Refused: {status}", level="error")
        self.dialog("Salad Studio", dialog, level="error")

    def _say_gen(self, text: str) -> None:
        self.gen_state.value = text
        refresh(self.gen_state)

    def _generated(self, outcome: Any) -> None:
        """A finished render: the state word, the status line, the dialog and the thumb."""
        from pathlib import Path

        from salad_studio import prompt_history
        from salad_studio.flet_services import GenOutcome

        if isinstance(outcome, Exception):
            outcome = GenOutcome("failed", message=str(outcome))
        if outcome.kind == "refused":
            self._say_gen("Refused")
            self.say_refusal(outcome.message, outcome.message)
        elif outcome.kind == "failed":
            self.services.log("error", outcome.message)
            self._say_gen(f"Failed after {outcome.elapsed_s}s")
            self.shell.say("Failed. See Logs", level="error")
            self.dialog("Salad Studio", outcome.message, level="error")
        else:
            self._say_gen(f"Done in {outcome.elapsed_s}s")
            self.note(f"Wrote {outcome.out}", level="ok")
            if outcome.out is not None:
                try:
                    prompt_history.attach_image(Path(outcome.out))
                except (OSError, ValueError, TypeError) as exc:
                    self.services.log("warn", f"history thumb skipped: {exc}")
        if self.services.gen_jobs > 0:
            self._say_gen(f"{self.services.gen_jobs} render(s) still queued")

    # -- the form and the profile

    def load_profiles(self) -> None:
        allp = profiles.ensure_builtin_profiles()
        if not allp:
            p = profiles.default_profile("klein")
            profiles.upsert(p)
            profiles.set_active(p.name)
            allp = {p.name: p}
        active = profiles.get_active() or sorted(allp)[0]
        self.apply_profile(allp.get(active) or profiles.default_profile("klein"))

    def ensure_page(self, name: str) -> Any:
        """Build a page without showing it. It lands on the client with the
        shell's next update; repaint it only after that."""
        if name not in self.shell.pages:
            self.shell.pages[name] = build_page(self, name)
        return self.shell.pages[name]

    def apply_profile(self, p: profiles.SaladProfile) -> None:
        # A profile whose target is a vast.ai instance reads as the vast hosting:
        # the Tk page derived the radio from the URL, and the stored mode can be
        # stale after the instance list changed.
        mode = p.mode if p.mode in hostings.BY_KEY else hostings.DEFAULT
        self.profile = p
        self.form = Form().from_profile(p if mode == p.mode else replace(p, mode=mode))
        settings = self.shell.pages.get("Prompt Settings")
        if settings is not None and hasattr(settings, "show_form"):
            settings.show_form()
        engine = getattr(self, "engine", None)
        if engine is None and "Prompt Editor" in self.shell.pages:
            engine = self.shell.pages["Prompt Editor"]
        if engine is not None:
            engine.rebuild_from_config()

    def stored_profile(self) -> profiles.SaladProfile | None:
        return profiles.load_all().get(self.form.name)

    def refresh_pages(self) -> None:
        """Draw every open page from the window's form, after a profile is loaded."""
        config_page = self.shell.pages.get("Config")
        if config_page is not None:
            config_page.show_profile()
            config_page.show_policy(self.profile.policy)


def build(page: ft.Page, *, dark: bool = True, show: bool = True,
          first: str | None = None) -> Window:
    """The window, its shell on the page, and its first page open.

    The shell is added before any page is built. Flet mounts a control only
    when the client receives it, and an ``update()`` on a control the client
    has never seen clears the window, so a page is built while the shell it
    goes into is already mounted.
    """
    flet_theme.apply(page)
    page.title = "Salad Studio"
    page.window.min_width = 900
    page.window.min_height = 560
    pump = Pump()
    specs = [PageSpec(name, lambda host, n=name: build_page(host, n)) for name in TAB_ORDER]
    shell = Shell(specs, dark=dark)
    window = Window(page, pump, shell, show=show)
    shell.window = window
    page.on_keyboard_event = lambda e: apply_shortcut(shell, e)
    window.build_action_bar()
    window.load_profiles()
    page.add(shell)
    page.update()
    shell.open(first if first in TAB_ORDER else default_page())
    return window


def default_page() -> str:
    """The page the window opens on.

    Always Config. The saved tab is not restored: flet 1.0.4 leaves its first
    frame blank whenever the startup page is a form page, and Config is the one
    page that has painted from the first frame in every measurement.
    """
    return "Config"


def placement(win: Window, radius: float = 0.0) -> None:
    """Put the window on the secondary display, centred in its work area."""
    left, top, width, height = desktop.placement((DEFAULT_WIDTH, DEFAULT_HEIGHT))
    page = win.page
    page.window.left = left
    page.window.top = top
    page.window.width = width
    page.window.height = height
    if radius:
        page.window.window_radius = radius
    refresh(page.window)


def app_main(page: ft.Page) -> None:
    """The entry point ``flet run salad_studio.flet_app`` calls."""
    desktop.make_dpi_aware()
    page.window.width = DEFAULT_WIDTH
    page.window.height = DEFAULT_HEIGHT
    win = build(page)
    win.services.start_timers()
    if not win.show:
        return
    win.services.log("info", "Salad Studio started")
    placement(win)
    page.window.on_event = lambda e: _on_window_event(win, e)
    try:
        page.update()
    except RuntimeError:
        pass
    return win


def _on_window_event(win: Window, e: Any) -> None:
    """Close: stop the timers, remember the open page, then let the window go."""
    from salad_studio import ui_state

    if str(getattr(e, "type", "") or "").lower().endswith("close"):
        win.services.stop()
        try:
            ui_state.save_state({"tab": win.shell.current})
        except (OSError, AttributeError, ValueError):
            pass


def main(page: ft.Page) -> None:
    app_main(page)


def build_hidden(page: ft.Page) -> Window:
    """A window built and never mapped: what a test drives. ``SALAD_STUDIO_HIDDEN`` always hides."""
    return build(page, show=not bool(os.environ.get("SALAD_STUDIO_HIDDEN")))
