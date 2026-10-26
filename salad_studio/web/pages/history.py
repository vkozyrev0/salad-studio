"""Prompt History: every request, its prompt, its graph and its rating.

A row's request JSON is about 6.7 KB and the list holds up to 100, so the
state carries only what the table draws. Reuse hands the one row it opens to
the editor through the action table.

A row is addressed by its ``ts``, not by its position: the store keeps its rows
newest first, and a new render during a delete would move every index under the
page's selection.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import prompt_history

COLUMNS = ("When", "Prompt", "Graph", "Rating", "Plate")
EMPTY_TEXT = "No prompts yet. Every Generate stores its request here."
THUMB = 48


def _ts_index(entries: list[dict[str, Any]]) -> dict[Any, list[int]]:
    """The positions of each timestamp, so one page load parses the store once."""
    out: dict[Any, list[int]] = {}
    for index, entry in enumerate(entries):
        ts = entry.get("ts")
        if ts not in (None, ""):
            out.setdefault(ts, []).append(index)
    return out


def _index_of(row_id: str) -> int | None:
    """The store position a row's id names. One place, because a write must hit
    the same row the page drew."""
    entries = prompt_history.list_prompts()
    ts_index = _ts_index(entries)
    for index, entry in enumerate(entries):
        if _row_id(index, entry, ts_index) == row_id:
            return index
    return None


def _row_id(index: int, entry: dict[str, Any], ts_index: dict[Any, list[int]] | None = None) -> str:
    """A row's stable id: its timestamp, and the store position only when it has none.

    Two entries saved in one second share a timestamp, and the older one is
    ``<ts>#<index>`` so each row still names exactly one entry.
    """
    ts = entry.get("ts")
    if ts in (None, ""):
        return f"#{index}"
    same = (ts_index or {}).get(ts, [index])
    return str(ts) if len(same) <= 1 or index == min(same) else f"{ts}#{index}"


def _row(index: int, entry: dict[str, Any], studio: Any,
         ts_index: dict[Any, list[int]] | None = None) -> dict[str, Any]:
    req = entry.get("request") if isinstance(entry.get("request"), dict) else None
    image = str(entry.get("image") or "")
    return {
        "id": _row_id(index, entry, ts_index),
        "ts": int(entry.get("ts") or 0),
        "prompt": prompt_history.preview(prompt_history.prompt_text_of(req) or str(entry.get("text") or "")),
        "graph": prompt_history.request_stats(req),
        "rating": prompt_history.rating_of(entry),
        "image": f"/api/thumbs/{Path(image).name}" if image and Path(image).is_file() else "",
        "profile": str(entry.get("profile") or ""),
    }


class HistoryController:
    page = "history"

    def __init__(self, studio: Any) -> None:
        self.studio = studio
        self.selected: str | None = None

    def register(self, table: Any) -> None:
        table.action("history.view")(self.view)
        table.action("history.select", need={"id": str})(self.select)
        table.action("history.rate", need={"stars": int})(self.rate)
        table.action("history.reuse")(self.reuse)
        table.action("history.delete")(self.delete)

    def view(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        return self.state()

    def state(self) -> dict[str, Any]:
        entries = prompt_history.list_prompts()
        ts_index = _ts_index(entries)
        rows = [_row(index, entry, self.studio, ts_index) for index, entry in enumerate(entries)]
        selected = self.selected if any(row["id"] == self.selected for row in rows) else None
        return {
            "columns": list(COLUMNS),
            "rows": rows,
            "count": len(rows),
            "empty_text": "" if rows else EMPTY_TEXT,
            "selected": selected,
            "can_act": selected is not None,
            "stars": [1, 2, 3, 4, 5],
        }

    def _index_of(self, row_id: str) -> int | None:
        return _index_of(row_id)

    # -- actions

    def select(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        if self._index_of(payload["id"]) is None:
            ctx.note("History: that entry is gone; refresh the list", level="warn")
            self.selected = None
            return self.state()
        self.selected = payload["id"]
        return self.state()

    def rate(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        stars = max(0, min(int(payload["stars"]), 5))
        index = self._index_of(self.selected or "")
        if index is None:
            ctx.note("Rate: select a render first, then pick 1 to 5 stars (0 clears)", level="warn")
            return self.state()
        prompt_history.rate(index, stars)
        ctx.note(f"Render #{index} {'rated ' + str(stars) + ' star' + ('s' if stars != 1 else '') if stars else 'rating cleared'}")
        return self.state()

    def reuse(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        index = self._index_of(self.selected or "")
        if index is None:
            ctx.dialog("Reuse", "Select a prompt to reuse.")
            return self.state()
        entry = prompt_history.list_prompts()[index]
        req = entry.get("request") if isinstance(entry.get("request"), dict) else None
        self._recall(ctx, entry, "Reused request JSON from history" if req is not None
                     else "Reused prompt from history")
        ctx.navigate("editor")
        return self.state()

    def _recall(self, ctx: Any, entry: dict[str, Any], note: str) -> None:
        """Put one history entry into the editor, which owns the JSON.

        The editor is another page's controller, so it is reached through the
        table the way any page asks another for work, and never by calling into
        its fields.
        """
        body = {"request": entry.get("request"), "text": str(entry.get("text") or "")}
        result = self.studio.controllers.table.call("editor.recall", body)
        if result.error is not None:
            ctx.note(f"Could not load the request: {result.error.message}", level="error")
            return
        ctx.note(note, level="ok")

    def delete(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        index = self._index_of(self.selected or "")
        if index is None:
            ctx.note("Delete: select an entry first", level="warn")
            return self.state()
        if not ctx.confirmed:
            ctx.effects.append({
                "kind": "confirm",
                "token": self.studio.issue_confirm(self.page, "delete", {}),
                "title": "Delete this entry",
                "body": "Delete this prompt history entry? Its thumbnail goes with it. This cannot be undone.",
            })
            return self.state()
        prompt_history.remove_at(index)
        self.selected = None
        ctx.note("Deleted the history entry", level="ok")
        return self.state()
