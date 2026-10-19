"""Prompt History: every request, its prompt, its graph and its rating."""
from __future__ import annotations

import time
from typing import Any

import flet as ft

from salad_studio import flet_theme, flet_widgets as w, prompt_history
from salad_studio.flet_shell import Page

COLUMNS = ("When", "Prompt", "Graph", "Rating", "Image")
EMPTY_TEXT = "No prompts yet. Every Generate stores its request here."
THUMB = 48


class HistoryPage(Page):
    def __init__(self, host: Any) -> None:
        super().__init__("Prompt History", "Every request, with its prompt and graph.", host.colors)
        self.host = host
        self.win = host
        self.rows: list[dict[str, Any]] = []
        self.selected: int | None = None
        self._thumbs: dict[int, bytes | None] = {}
        self.table_holder = ft.Column(expand=True, scroll=ft.ScrollMode.ALWAYS)
        self.empty = ft.Text(EMPTY_TEXT, size=12, color=self.colors["muted"])
        rating = [w.button("No stars", lambda _e: self.rate(0))]
        rating[:0] = [w.flat(str(n), lambda _e, k=n: self.rate(k)) for n in range(1, 6)]
        self.body.content = ft.Column(
            [
                self.table_holder,
                self.empty,
                w.row([w.button("Reuse", self.reuse, primary=True), w.button("Delete", self.delete),
                       w.label("Rating", self.colors), *rating]),
            ],
            spacing=flet_theme.GAP["sm"], expand=True,
        )
        self.refresh()

    def _thumb(self, index: int, raw: str) -> ft.Control | None:
        from pathlib import Path

        path = Path(raw)
        if not raw or not path.is_file():
            return None
        if index not in self._thumbs:
            self._thumbs[index] = self.win.services.thumbnail(path, THUMB)
        png = self._thumbs[index]
        return ft.Image(src=png, width=THUMB, height=THUMB, fit=ft.BoxFit.COVER, border_radius=4) if png else None

    def refresh(self) -> None:
        self.rows = prompt_history.list_prompts()
        cells: list[list[Any]] = []
        for index, row in enumerate(self.rows):
            req = row.get("request") if isinstance(row.get("request"), dict) else None
            stars = prompt_history.rating_of(row)
            thumb = self._thumb(index, str(row.get("image") or ""))
            cells.append([
                time.strftime("%Y-%m-%d %H:%M", time.localtime(int(row.get("ts") or 0))),
                prompt_history.preview(prompt_history.prompt_text_of(req) or str(row.get("text") or "")),
                prompt_history.request_stats(req) if req else "",
                "*" * stars if stars else "",
                thumb or "",
            ])
        selected = self.selected if self.selected is not None and self.selected < len(cells) else None
        self.table_holder.controls = ([w.table(COLUMNS, cells, on_row=self.select_row,
                                              selected=selected, heading_height=44)]
                                     if cells else [])
        self.empty.visible = not cells
        try:
            self.table_holder.update()
            self.empty.update()
        except RuntimeError:
            return

    def select_row(self, index: int) -> None:
        if 0 <= index < len(self.rows):
            self.selected = index
            self.refresh()

    def reuse(self, _e: Any = None) -> None:
        if self.selected is None or not (0 <= self.selected < len(self.rows)):
            self.host.dialog("Salad Studio", "Select a prompt to reuse.")
            return
        row = self.rows[self.selected]
        request = row.get("request") if isinstance(row.get("request"), dict) else None
        editor = self.win.open_page("Prompt Editor")
        if request is not None:
            editor.set_payload(request)
            self.host.note("Reused request JSON from history", level="ok")
            return
        text = str(row.get("text") or "")
        editor.set_positive_only(text)
        self.host.note("Reused prompt from history", level="ok")

    def rate(self, stars: int) -> None:
        if self.selected is None:
            self.host.note("Rate: select a render first, then press 1-5 (0 clears)", level="warn")
            return
        prompt_history.rate(self.selected, stars)
        self.refresh()
        word = f"rated {stars} star{'s' if stars != 1 else ''}" if stars else "rating cleared"
        self.host.note(f"Render #{self.selected} {word}", level="info")

    def delete(self, _e: Any = None) -> None:
        if self.selected is None or not (0 <= self.selected < len(self.rows)):
            self.host.dialog("Salad Studio", "Select a prompt to delete.")
            return
        index = self.selected

        def go() -> None:
            prompt_history.remove_at(index)
            self.selected = None
            self.refresh()
            self.host.note("Deleted the history entry", level="ok")

        self.host.ask("Salad Studio", "Delete this prompt history entry? This cannot be undone.", go)
