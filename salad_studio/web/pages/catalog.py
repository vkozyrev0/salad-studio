"""Prompt Catalog: kept requests, listed in the page and acted on by id.

The page sends the row it selected with every action, so a Yes on Delete acts
on the row the dialog named, not on whatever is selected when it lands. Each
action reads the boxes the user is editing from its own payload.
"""
from __future__ import annotations

import time
from typing import Any

import generator
import prompt_catalog
import prompt_history

PAGE = "catalog"
COLUMNS = ("Added", "Short name", "Description", "Prompt", "Graph")
EMPTY_TEXT = "No kept prompts yet. Give one a short name and copy it from the Prompt Editor."
STATS_SEPARATOR = "·"
PREVIEW_CHARS = 90


def _graph_stats(stats: str) -> str:
    """An entry's stats up to its shape: nodes, LoRAs and the size."""
    parts = [part.strip() for part in str(stats or "").split(STATS_SEPARATOR)]
    return f" {STATS_SEPARATOR} ".join(parts[:3])


def _row(entry: dict[str, Any]) -> dict[str, Any]:
    request = entry.get("request") if isinstance(entry.get("request"), dict) else None
    return {
        "id": entry.get("id") or "",
        "name": str(entry.get("name") or ""),
        "description": str(entry.get("description") or ""),
        "cells": [
            time.strftime("%Y-%m-%d %H:%M", time.localtime(int(entry.get("ts") or 0))),
            str(entry.get("name") or ""),
            str(entry.get("description") or ""),
            prompt_history.preview(prompt_history.prompt_text_of(request), PREVIEW_CHARS),
            _graph_stats(prompt_catalog.entry_stats(entry)),
        ],
    }


def _editor(studio: Any) -> Any:
    return studio.controllers.get("editor") if studio.controllers is not None else None


def _editor_payload(studio: Any, ctx: Any) -> dict[str, Any] | None:
    """The Prompt Editor's request JSON, or None once the page has been told why not."""
    editor = _editor(studio)
    if editor is None:
        ctx.dialog("Salad Studio", "Open the Prompt Editor first.", level="error")
        return None
    try:
        return generator.parse_request_json(editor.text())
    except (ValueError, TypeError) as exc:
        ctx.dialog("Salad Studio", f"Prompt Editor JSON is invalid: {exc}", level="error")
        return None


def _field(payload: dict[str, Any], key: str, default: str = "") -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be str")
    return value.strip() or default


def _selected(payload: dict[str, Any], ctx: Any) -> dict[str, Any] | None:
    if "id" not in payload:
        raise ValueError("id is required")
    entry = prompt_catalog.get_entry(_field(payload, "id"))
    if entry is None:
        ctx.dialog("Salad Studio", "Select a catalog entry first.", level="error")
    return entry


class CatalogController:
    page = PAGE

    def __init__(self, studio: Any) -> None:
        self.studio = studio
        self.status = ""

    def register(self, table: Any) -> None:
        table.action("catalog.view")(self.view)
        # A handler with ``need`` receives only those fields, and every action here
        # reads a box beside its id, so each one takes the whole payload and
        # checks its own fields.
        table.action("catalog.add")(self.add)
        table.action("catalog.update_json")(self.update_json)
        table.action("catalog.save_meta")(self.save_meta)
        table.action("catalog.load")(self.load)
        table.action("catalog.delete")(self.delete)

    def view(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        return self.state()

    def state(self) -> dict[str, Any]:
        rows = [_row(entry) for entry in prompt_catalog.list_entries()]
        return {
            "columns": list(COLUMNS),
            "rows": rows,
            "empty": "" if rows else EMPTY_TEXT,
            "status": self.status,
        }

    # -- actions

    def add(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        name = _field(payload, "name")
        if not name:
            ctx.dialog("Salad Studio", "Give the prompt a short name first.")
            return self.state()
        body = _editor_payload(self.studio, ctx)
        if body is None:
            return self.state()
        try:
            entry = prompt_catalog.add_entry(name, _field(payload, "description"), body)
        except ValueError as exc:
            ctx.dialog("Salad Studio", str(exc), level="error")
            return self.state()
        self.status = f"Copied '{entry['name']}' from the Prompt Editor"
        ctx.note(f"Catalog: added {entry['name']}", level="ok")
        return self.state()

    def update_json(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        entry = _selected(payload, ctx)
        if entry is None:
            return self.state()
        body = _editor_payload(self.studio, ctx)
        if body is None:
            return self.state()
        try:
            entry = prompt_catalog.update_entry(entry["id"], request=body)
        except (ValueError, KeyError) as exc:
            ctx.dialog("Salad Studio", str(exc), level="error")
            return self.state()
        self.status = f"Updated the JSON of '{entry.get('name')}'"
        ctx.note(self.status, level="ok")
        return self.state()

    def save_meta(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        entry = _selected(payload, ctx)
        if entry is None:
            return self.state()
        wanted = _field(payload, "name")
        clash = prompt_catalog.find_by_name(wanted) if wanted else None
        if clash is not None and str(clash.get("id")) != entry["id"]:
            # Renaming onto another entry's name would replace that entry: ask.
            ctx.dialog(
                "Salad Studio",
                f"'{wanted}' is already a catalog entry under short name {clash.get('name')!r}. "
                "Pick another name.",
                level="error",
            )
            return self.state()
        try:
            entry = prompt_catalog.update_entry(entry["id"], name=wanted,
                                                description=_field(payload, "description"))
        except (ValueError, KeyError) as exc:
            ctx.note(str(exc), level="error")
            return self.state()
        self.status = f"Saved '{entry.get('name')}'"
        ctx.note(self.status, level="ok")
        return self.state()

    def load(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        entry = _selected(payload, ctx)
        if entry is None:
            return self.state()
        editor = _editor(self.studio)
        if editor is None:
            ctx.dialog("Salad Studio", "Open the Prompt Editor first.", level="error")
            return self.state()
        request = entry.get("request") if isinstance(entry.get("request"), dict) else {}
        editor.set_payload(request)
        ctx.navigate("editor")
        self.status = f"Loaded '{entry.get('name')}' into the Prompt Editor"
        ctx.note(self.status, level="ok")
        return self.state()

    def delete(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        entry = _selected(payload, ctx)
        if entry is None:
            return self.state()
        if not ctx.confirmed:
            ctx.effects.append({
                "kind": "confirm",
                "token": self.studio.issue_confirm(PAGE, "delete", {"id": entry["id"]}),
                "title": "Delete catalog entry",
                "body": f"Delete catalog entry '{entry.get('name')}'? This cannot be undone.",
            })
            return self.state()
        prompt_catalog.remove_entry(str(entry["id"]))
        ctx.note(f"Deleted '{entry.get('name')}'", level="ok")
        return self.state()
