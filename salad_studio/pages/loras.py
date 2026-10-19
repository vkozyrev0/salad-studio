"""LoRAs: the library as a grid, the find box narrowing it, the add/edit form.

The grid columns, their order and the form's labels are the Tk page's
(``app.py`` ``_build_loras_tab``). A row's colour rides the Verified cell and the
row's name; the selection fills the form, and Add, Save edits, Verify, Verify
unverified and Remove extra act on the form or on the selection.
"""
from __future__ import annotations

from typing import Any

import flet as ft

from salad_studio import flet_theme, flet_widgets as w, lora_store
from salad_studio.flet_pump import refresh
from salad_studio.flet_shell import Page

COLUMNS = ("Verified", "Id", "Name", "Version", "Model", "Source", "Comfy name")
# A row's Verified cell is drawn in the verified or unverified colour, as the
# Tk tree coloured the whole row.
VERIFIED_COLOR = "valid"
UNVERIFIED_COLOR = "invalid"


class LorasPage(Page):
    def __init__(self, host: Any) -> None:
        super().__init__("LoRAs", "The catalog plus the extras you add.", host.colors)
        self.host = host
        self.win = host
        self.rows: list[dict[str, Any]] = []
        self.shown: list[dict[str, Any]] = []
        self.selected: str | None = None
        self.sort_by = ""
        self.reverse = False
        self.find = w.field("", label_text="Find by name", width=300, on_change=lambda _e: self.refresh())
        self.clear_btn = w.button("Clear", lambda _e: self.clear_find())
        self.ref = w.field("", label_text="Civitai / HF URL / civitai:id@version / local path", width=520)
        self.name = w.field("", label_text="Name (optional)", width=320)
        self.filename = w.field("", label_text="Filename (optional)", width=320)
        self.family = w.combo(list(lora_store.FAMILY_CHOICES), value="Flux.2 Klein", label_text="Works with",
                              width=200)
        self.strength_model = w.field("1.0", label_text="Strength model", width=120)
        self.strength_clip = w.field("1.0", label_text="Strength clip", width=120)
        self.table_box = ft.Container(expand=True)
        self.add_btn = w.button("Add", self.add_lora)
        self.verify_btn = w.button("Verify", self.verify_selected)
        self.verify_all_btn = w.button("Verify unverified", self.verify_unverified)
        self.body.content = ft.Column(
            [
                ft.Row([self.find, self.clear_btn,
                        ft.Text("a part of the name is enough", size=11, color=self.colors["muted"])],
                       spacing=flet_theme.GAP["sm"]),
                self.table_box,
                w.heading("Add / edit LoRA", self.colors),
                self.ref, self.name, self.filename,
                ft.Row([self.family, self.strength_model, self.strength_clip],
                       spacing=flet_theme.GAP["sm"]),
                ft.Row([self.add_btn, self.verify_btn, self.verify_all_btn], spacing=flet_theme.GAP["sm"]),
            ],
            spacing=flet_theme.GAP["sm"],
            expand=True,
            scroll=ft.ScrollMode.ALWAYS,
        )
        self.refresh()

    def _cells(self, item: dict[str, Any]) -> list[str]:
        src = item.get("source") or {}
        verified = bool(item.get("verified"))
        return [
            "● yes" if verified else "● no",
            str(item.get("id") or ""),
            str(item.get("name") or ""),
            lora_store.version_label(item),
            str(item.get("base") or ""),
            str(src.get("page") or src.get("download") or ""),
            lora_store.comfy_lora_name(item),
        ]

    def refresh(self, rows: list[dict[str, Any]] | None = None) -> None:
        items = lora_store.list_loras() if rows is None else rows
        text = str(self.find.value or "").strip().lower()
        shown = [item for item in items if not text or text in str(item.get("name") or "").lower()]
        if self.sort_by:
            column = COLUMNS.index(self.sort_by)
            shown = sorted(shown, key=lambda item: self._cells(item)[column].lower(),
                           reverse=self.reverse)
        self.rows = items
        self.shown = shown
        index = next((i for i, item in enumerate(shown) if str(item.get("id")) == self.selected), None)
        cells = [self._cells(item) for item in shown]
        table = w.table(COLUMNS, cells, on_row=self.select_row, selected=index)
        for row, item in zip(table.rows, shown):
            row.cells[0].content = ft.Text(row.cells[0].content.value, size=12,
                                           color=self.colors[VERIFIED_COLOR if item.get("verified")
                                                              else UNVERIFIED_COLOR])
        for column_index, column in enumerate(table.columns):
            column.on_sort = lambda _e, i=column_index: self.sort(i)
        self.table_box.content = ft.Column([table] if cells else [], scroll=ft.ScrollMode.ALWAYS,
                                           expand=True)
        refresh(self.table_box)

    def sort(self, index: int) -> None:
        name = COLUMNS[index]
        self.reverse = not self.reverse if self.sort_by == name else False
        self.sort_by = name
        self.refresh(self.rows)

    def clear_find(self) -> None:
        self.find.value = ""
        self.refresh()

    def select_row(self, index: int) -> None:
        if not (0 <= index < len(self.shown)):
            return
        item = self.shown[index]
        self.selected = str(item.get("id") or "")
        src = item.get("source") or {}
        self.ref.value = str(src.get("page") or src.get("download") or item.get("id") or "")
        self.name.value = str(item.get("name") or "")
        self.filename.value = str(src.get("filename") or "") or lora_store.comfy_lora_name(item)
        self.family.value = lora_store.family_label(item)
        strength_model, strength_clip = lora_store.strengths_for(item)
        self.strength_model.value = str(strength_model)
        self.strength_clip.value = str(strength_clip)
        self.refresh()
        refresh(self.ref, self.name, self.filename, self.family, self.strength_model, self.strength_clip)

    def _form(self) -> dict[str, Any]:
        def number(raw: str, default: float) -> float:
            try:
                return float(str(raw or "").strip() or default)
            except ValueError:
                return default

        return {
            "name": str(self.name.value or "").strip() or None,
            "filename": str(self.filename.value or "").strip() or None,
            "base": str(self.family.value or "").strip() or None,
            "strength_model": number(self.strength_model.value, 1.0),
            "strength_clip": number(self.strength_clip.value, 1.0),
        }

    def _selected_item(self) -> dict[str, Any] | None:
        return next((item for item in self.rows if str(item.get("id")) == self.selected), None)

    def add_lora(self, _e: Any = None) -> None:
        ref = str(self.ref.value or "").strip()
        if not ref:
            self.host.dialog("Salad Studio", "Type a Civitai page, a civitai:id@version, a Hugging Face URL, "
                                            "a local .safetensors path, or a download URL.", level="error")
            return
        form = self._form()
        if not self.win.guard("lora_add", self.add_btn):
            return

        def work() -> Any:
            return lora_store.add_lora(ref, verify=True, **form)

        def done(result: Any) -> None:
            self.win.release("lora_add", self.add_btn)
            if isinstance(result, Exception):
                self.host.note(f"Could not add the LoRA: {result}", level="error")
                return
            self.ref.value = ""
            self.refresh()
            self.host.note(f"Added {(result or {}).get('name') or ref}", level="ok")

        self.win.services.background(work, done)

    def save_edits(self, _e: Any = None) -> None:
        item = self._selected_item()
        if item is None:
            self.host.dialog("Salad Studio", "Select a LoRA first.", level="error")
            return
        try:
            lora_store.edit_lora(str(item.get("id")), **self._form())
        except ValueError as exc:
            self.host.dialog("Salad Studio", f"Could not edit the LoRA: {exc}", level="error")
            return
        self.refresh()
        self.host.note(f"Saved the edits to {self.name.value}", level="ok")

    def verify_selected(self, _e: Any = None) -> None:
        item = self._selected_item()
        if item is None:
            self.host.dialog("Salad Studio", "Select a LoRA first.", level="error")
            return
        if not self.win.guard("lora_verify", self.verify_btn):
            return
        lid = str(item.get("id") or "")

        def done(result: Any) -> None:
            self.win.release("lora_verify", self.verify_btn)
            if isinstance(result, Exception):
                self.host.note(f"Could not verify the LoRA: {result}", level="error")
                return
            self.refresh()
            ok = bool(result.get("verified"))
            self.host.note("Verified" if ok else "Verification failed", level="ok" if ok else "warn")

        self.win.services.background(lambda: lora_store.verify_lora(lid), done)

    def verify_unverified(self, _e: Any = None) -> None:
        if not self.win.guard("lora_verify", self.verify_all_btn):
            return

        def done(result: Any) -> None:
            self.win.release("lora_verify", self.verify_all_btn)
            if isinstance(result, Exception):
                self.host.note(f"Could not verify the unverified LoRAs: {result}", level="error")
                return
            ok, fail, _failed = result
            self.refresh()
            self.host.note(f"Verified {ok}; {fail} failed" if fail else f"Verified {ok}",
                           level="warn" if fail else "ok")

        self.win.services.background(lora_store.verify_unverified_loras, done)

    def remove_selected(self, _e: Any = None) -> None:
        item = self._selected_item()
        if item is None:
            self.host.note("Refused: select a LoRA first", level="warn")
            return
        removed = lora_store.remove_lora(str(item.get("id")))
        self.refresh()
        if removed:
            self.host.note(f"Removed {item.get('name')}", level="ok")
        else:
            self.host.note("Refused: Known catalog LoRAs stay in the list; only extras added here can "
                           "be removed.", level="warn")
