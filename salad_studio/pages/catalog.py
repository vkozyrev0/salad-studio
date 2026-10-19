"""Prompt Catalog: kept requests under a short name and a description."""
from __future__ import annotations

import time
from typing import Any

import flet as ft

from salad_studio import flet_theme, flet_widgets as w, generator, prompt_catalog, prompt_history
from salad_studio.flet_shell import Page

COLUMNS = ("Added", "Short name", "Description", "Prompt", "Graph")
EMPTY_TEXT = "No kept prompts yet. Give one a short name and copy it from the Prompt Editor."


class CatalogPage(Page):
    def __init__(self, host: Any) -> None:
        super().__init__("Prompt Catalog", "Kept prompts, by short name.", host.colors)
        self.host = host
        self.win = host
        self.entries: list[dict[str, Any]] = []
        self.selected: str | None = None
        self.name = w.field("", label_text="Short name", width=240)
        self.description = w.field("", label_text="Description", width=460)
        self.table_holder = ft.Column(expand=True, scroll=ft.ScrollMode.ALWAYS)
        self.empty = ft.Text(EMPTY_TEXT, size=12, color=self.colors["muted"])
        self.catalog_status = ft.Text("", size=12, color=self.colors["muted"])
        self.body.content = ft.Column(
            [
                w.row([self.name, self.description]),
                self.table_holder,
                self.empty,
                w.row([w.button("Copy from Prompt Editor", self.add),
                       w.button("Update JSON", self.update_json),
                       w.button("Save name / description", self.save_meta),
                       w.button("Load into Prompt Editor", self.load),
                       w.button("Delete", self.delete)]),
                self.catalog_status,
            ],
            spacing=flet_theme.GAP["sm"],
            expand=True,
        )
        self.refresh()

    def refresh(self) -> None:
        self.entries = prompt_catalog.list_entries()
        cells = []
        for entry in self.entries:
            request = entry.get("request") if isinstance(entry.get("request"), dict) else None
            cells.append([
                time.strftime("%Y-%m-%d %H:%M", time.localtime(int(entry.get("ts") or 0))),
                str(entry.get("name") or ""),
                str(entry.get("description") or ""),
                prompt_history.preview(prompt_history.prompt_text_of(request)),
                prompt_catalog.entry_stats(entry),
            ])
        index = next((i for i, e in enumerate(self.entries) if str(e.get("id")) == self.selected), None)
        self.table_holder.controls = (
            [w.table(COLUMNS, cells, on_row=self.select_row, selected=index)] if cells
            else []
        )
        self.empty.visible = not cells
        try:
            self.table_holder.update()
            self.empty.update()
        except RuntimeError:
            return

    def select_row(self, index: int) -> None:
        if not (0 <= index < len(self.entries)):
            return
        entry = self.entries[index]
        self.selected = str(entry.get("id") or "")
        self.name.value = str(entry.get("name") or "")
        self.description.value = str(entry.get("description") or "")
        self.refresh()
        try:
            self.name.update()
            self.description.update()
        except RuntimeError:
            return

    def _editor_payload(self) -> dict[str, Any] | None:
        editor = self.win.shell.pages.get("Prompt Editor")
        if editor is None:
            self.host.dialog("Salad Studio", "Open the Prompt Editor first.", level="error")
            return None
        try:
            return generator.parse_request_json(editor.text())
        except (ValueError, TypeError) as exc:
            self.host.dialog("Salad Studio", f"Prompt Editor JSON is invalid: {exc}", level="error")
            return None

    def add(self, _e: Any = None) -> None:
        name = str(self.name.value or "").strip()
        if not name:
            self.host.dialog("Salad Studio", "Give the prompt a short name first.")
            return
        payload = self._editor_payload()
        if payload is None:
            return
        try:
            entry = prompt_catalog.add_entry(name, str(self.description.value or ""), payload)
        except ValueError as exc:
            self.host.dialog("Salad Studio", str(exc), level="error")
            return
        self.selected = str(entry["id"])
        self.refresh()
        self.catalog_status.value = f"Copied '{entry['name']}' from the Prompt Editor"
        self.host.note(f"Catalog: added {entry['name']}", level="ok")

    def update_json(self, _e: Any = None) -> None:
        if not self.selected:
            self.host.dialog("Salad Studio", "Select a catalog entry first.")
            return
        payload = self._editor_payload()
        if payload is None:
            return
        try:
            entry = prompt_catalog.update_entry(self.selected, request=payload)
        except (ValueError, KeyError) as exc:
            self.host.dialog("Salad Studio", str(exc), level="error")
            return
        self.refresh()
        self.catalog_status.value = f"Updated the JSON of '{entry.get('name')}'"
        self.host.note(self.catalog_status.value, level="ok")

    def save_meta(self, _e: Any = None) -> None:
        if not self.selected:
            self.host.dialog("Salad Studio", "Select a catalog entry first.")
            return
        wanted = str(self.name.value or "").strip()
        clash = prompt_catalog.find_by_name(wanted) if wanted else None
        if clash is not None and str(clash.get("id")) != self.selected:
            # Renaming onto another entry's name would replace that entry: ask.
            self.host.dialog(
                "Salad Studio",
                f"'{wanted}' is already a catalog entry under short name {clash.get('name')!r}. "
                "Pick another name.",
                level="error",
            )
            return
        try:
            entry = prompt_catalog.update_entry(self.selected, name=str(self.name.value or ""),
                                                description=str(self.description.value or ""))
        except (ValueError, KeyError) as exc:
            self.host.dialog("Salad Studio", str(exc), level="error")
            return
        self.refresh()
        self.catalog_status.value = f"Saved '{entry.get('name')}'"
        self.host.note(self.catalog_status.value, level="ok")

    def load(self, _e: Any = None) -> None:
        entry = prompt_catalog.get_entry(self.selected or "")
        if entry is None:
            self.host.dialog("Salad Studio", "Select a catalog entry first.")
            return
        request = entry.get("request") if isinstance(entry.get("request"), dict) else {}
        editor = self.win.open_page("Prompt Editor")
        editor.set_payload(request)
        self.catalog_status.value = f"Loaded '{entry.get('name')}' into the Prompt Editor"
        self.host.note(self.catalog_status.value, level="ok")

    def delete(self, _e: Any = None) -> None:
        entry = prompt_catalog.get_entry(self.selected or "")
        if entry is None:
            self.host.dialog("Salad Studio", "Select a catalog entry first.")
            return

        def go() -> None:
            prompt_catalog.remove_entry(str(entry["id"]))
            self.selected = None
            self.refresh()
            self.host.note(f"Deleted '{entry.get('name')}'", level="ok")

        self.host.ask("Salad Studio", f"Delete catalog entry '{entry.get('name')}'? This cannot be undone.",
                      go)
