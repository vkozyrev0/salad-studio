"""Tokens: the provider keys, each with the state of its last probe.

Empty slots seed from the config files the studio already reads; DeepSeek also
reads ``DEEPSEEK_API_KEY``. A key is shown as a password until "show", and the
probe runs on a worker so the window keeps painting.
"""
from __future__ import annotations

from typing import Any

import flet as ft

from salad_studio import flet_theme, flet_widgets as w, tokens
from salad_studio.flet_shell import Page

SLOTS: tuple[tuple[str, str], ...] = (
    ("salad", "Salad"),
    ("huggingface", "Hugging Face"),
    ("civitai", "Civitai"),
    ("deepseek", "DeepSeek"),
    ("vast", "Vast.ai"),
)
# tokens.state_color maps a probe state to the palette key the dot is drawn in.
DOT = {"valid": "valid", "invalid": "invalid", "unknown": "unknown"}


class TokensPage(Page):
    def __init__(self, host: Any) -> None:
        super().__init__("Tokens", "Provider keys, and what each one last answered.", host.colors)
        self.host = host
        self.win = host
        self.fields: dict[str, ft.TextField] = {}
        self.dots: dict[str, ft.Text] = {}
        self.state: dict[str, str] = {slot: "unknown" for slot, _ in SLOTS}
        rows: list[ft.Control] = []
        for slot, label in SLOTS:
            field = w.field("", label_text=label, width=460, password=True, can_reveal=True)
            dot = ft.Text("●", size=16, color=self.colors["unknown"], tooltip="unconfirmed")
            self.fields[slot] = field
            self.dots[slot] = dot
            rows.append(w.row([dot, field]))
        self.body.content = ft.Column(
            [
                *rows,
                w.row([w.button("Check keys", self.check_keys),
                       w.button("Save key", self.save_key)]),
            ],
            spacing=flet_theme.GAP["sm"], scroll=ft.ScrollMode.ALWAYS, expand=True,
        )
        self._seed()

    def _seed(self) -> None:
        for slot, _label in SLOTS:
            try:
                value = tokens.read_token(slot)
            except (AttributeError, OSError):
                value = ""
            self.fields[slot].value = value or ""

    def refresh_states(self) -> None:
        for slot, state in self.state.items():
            self.dots[slot].color = self.colors[tokens.state_color(state)]
            self.dots[slot].tooltip = {"valid": "accepted", "invalid": "rejected"}.get(state, "unconfirmed")
        try:
            for dot in self.dots.values():
                dot.update()
        except RuntimeError:
            return

    def save_key(self, _e: Any = None) -> None:
        for slot, _label in SLOTS:
            value = str(self.fields[slot].value or "").strip()
            if not value:
                continue
            try:
                tokens.write_token(slot, value)
            except OSError as exc:
                self.host.dialog("Salad Studio", f"Could not save the {slot} key: {exc}", level="error")
                return
        self.host.note("Saved the keys", level="ok")

    def check_keys(self, _e: Any = None) -> None:
        if self.win.services.busy_flags.get("tokens"):
            return
        self.win.services.busy_flags["tokens"] = True
        values = {slot: str(self.fields[slot].value or "").strip() for slot, _ in SLOTS}

        def work() -> Any:
            out: dict[str, str] = {}
            for slot, value in values.items():
                try:
                    out[slot] = str(tokens.probe_token(slot, key=value or None).get("state") or "unknown")
                except Exception:  # noqa: BLE001 - a probe never fails the page
                    out[slot] = "unknown"
            return out

        def done(result: Any) -> None:
            self.win.services.busy_flags["tokens"] = False
            if isinstance(result, Exception):
                self.host.dialog("Salad Studio", str(result), level="error")
                return
            self.state = result
            self.refresh_states()
            bad = [slot for slot, s in result.items() if s == "invalid"]
            self.host.note("Keys checked" if not bad else f"Rejected: {', '.join(bad)}",
                           level="ok" if not bad else "warn")

        self.win.services.background(work, done)
