"""Logs: the container's own stdout beside the Studio and HTTP lines, secrets masked."""
from __future__ import annotations

from typing import Any

import flet as ft

from salad_studio import flet_theme, flet_widgets as w
from salad_studio.flet_services import level_color
from salad_studio.flet_shell import Page


class LogsPage(Page):
    def __init__(self, host: Any) -> None:
        super().__init__("Logs", "Studio and HTTP lines, secrets masked.", host.colors)
        self.host = host
        self.win = host
        self.salad_lines = ft.ListView(expand=True, spacing=0, auto_scroll=True)
        self.salad_box = ft.Container(
            content=ft.Column([w.heading("Salad container logs (active gateway)", self.colors),
                               ft.Container(self.salad_lines, expand=True, padding=6)],
                              expand=True, tight=True),
            expand=True, bgcolor=self.colors["surface_container"], border_radius=flet_theme.CARD_RADIUS,
            padding=8,
        )
        self.studio_lines = ft.ListView(expand=True, spacing=0, auto_scroll=True)
        self.studio_box = ft.Container(
            content=ft.Column([w.heading("Studio / HTTP", self.colors),
                               ft.Container(self.studio_lines, expand=True, padding=6),
                               ft.Row([w.button("Clear Studio logs", lambda _e: self.clear())])],
                              expand=True, tight=True),
            expand=True, bgcolor=self.colors["surface_container"], border_radius=flet_theme.CARD_RADIUS,
            padding=8,
        )
        self.body.content = ft.Column(
            [
                self.salad_box,
                ft.Row([w.button("Refresh Salad logs", self.refresh_salad_logs),
                        w.button("Check Salad status", self.check_salad)]),
                self.studio_box,
            ],
            spacing=flet_theme.GAP["sm"],
            expand=True,
        )
        self.shown = 0
        self.refresh_lines()

    def refresh_lines(self, _e: Any = None) -> None:
        """Append the lines logged since the last call, and the container text as a whole."""
        lines = list(self.win.services.log_lines)
        for level, text in lines[self.shown:]:
            self.studio_lines.controls.append(
                ft.Text(text, size=12, font_family="Consolas", color=level_color(level), selectable=True))
        self.shown = len(lines)
        text = self.win.services.salad_logs
        version = self.win.services.salad_logs_version
        if getattr(self, "_salad_version", None) != version:
            self._salad_version = version
            self.salad_lines.controls = [
                ft.Text(line, size=12, font_family="Consolas", color=self.colors["on_surface"], selectable=True)
                for line in (text or "").splitlines()
            ] or [ft.Text("(nothing fetched yet)", size=12, color=self.colors["muted"])]
        try:
            self.studio_lines.update()
            self.salad_lines.update()
        except RuntimeError:
            return

    def clear(self) -> None:
        self.win.services.clear_logs()
        self.shown = 0
        self.studio_lines.controls.clear()
        self.refresh_lines()
        self.host.note("Logs cleared", level="info")

    def refresh_salad_logs(self, _e: Any = None) -> None:
        self.win.services.refresh_salad_logs()
        self.host.note("Refreshing the Salad logs…", level="info")

    def check_salad(self, _e: Any = None) -> None:
        self.win.services.check_salad()
        self.host.note("Checking Salad status…", level="info")
