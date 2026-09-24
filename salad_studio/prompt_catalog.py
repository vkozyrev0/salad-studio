"""Salad Studio prompt catalog: named, described request JSONs you keep.

Stored under ``~/.config/salad/studio-prompt-catalog.json`` (not git). An
entry is ``{"id", "name", "description", "ts", "request"}``, where ``request``
is the same ``/prompt`` body the Prompt Editor holds, so an entry can be
loaded straight back into the editor. Civitai tokens are stripped before an
entry is written.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

try:
    from salad_studio.prompt_history import redact_request, request_stats
except ImportError:  # sibling import when run from salad_studio
    from prompt_history import redact_request, request_stats

CATALOG_PATH = Path.home() / ".config" / "salad" / "studio-prompt-catalog.json"
MAX_ENTRIES = 200
_SLUG = re.compile(r"[^a-z0-9]+")


def _resolve(path: Path | None) -> Path:
    return path if path is not None else CATALOG_PATH


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        req = row.get("request")
        name = str(row.get("name") or "").strip()
        if not isinstance(req, dict) or not name:
            continue
        out.append(
            {
                "id": str(row.get("id") or ""),
                "name": name,
                "description": str(row.get("description") or "").strip(),
                "ts": int(row.get("ts") or 0),
                "request": req,
            }
        )
    return out


def _save(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def _slug(name: str) -> str:
    return _SLUG.sub("-", (name or "").lower()).strip("-") or "prompt"


def _new_id(rows: list[dict[str, Any]], name: str, ts: int) -> str:
    base = f"{int(ts)}-{_slug(name)}"
    taken = {str(row.get("id") or "") for row in rows}
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def list_entries(path: Path | None = None) -> list[dict[str, Any]]:
    """Every catalog entry, newest first."""
    rows = _load(_resolve(path))
    rows.sort(key=lambda row: int(row.get("ts") or 0), reverse=True)
    return rows


def get_entry(entry_id: str, path: Path | None = None) -> dict[str, Any] | None:
    want = str(entry_id or "")
    for row in list_entries(path):
        if row.get("id") == want:
            return row
    return None


def find_by_name(name: str, path: Path | None = None) -> dict[str, Any] | None:
    want = (name or "").strip().casefold()
    for row in list_entries(path):
        if str(row.get("name") or "").casefold() == want:
            return row
    return None


def _clean_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or not isinstance(request.get("prompt"), dict):
        raise ValueError("a catalog entry needs a request JSON with a 'prompt' object")
    return redact_request(request)


def _clean_name(name: str) -> str:
    out = (name or "").strip()
    if not out:
        raise ValueError("give the prompt a short name")
    return out


def add_entry(
    name: str,
    description: str,
    request: dict[str, Any],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Store a named request. Raises ValueError on a blank or duplicate name."""
    clean = _clean_name(name)
    body = _clean_request(request)
    dest = _resolve(path)
    rows = _load(dest)
    if find_by_name(clean, dest) is not None:
        raise ValueError(f"'{clean}' is already in the catalog. Rename it or update that entry")
    ts = int(time.time())
    entry = {
        "id": _new_id(rows, clean, ts),
        "name": clean,
        "description": (description or "").strip(),
        "ts": ts,
        "request": body,
    }
    # Newest first. The new entry goes to the front explicitly, so two entries
    # added inside the same second still order by recency rather than by id.
    rows.sort(key=lambda row: int(row.get("ts") or 0), reverse=True)
    rows.insert(0, entry)
    _save(dest, rows[:MAX_ENTRIES])
    return entry


def update_entry(
    entry_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    request: dict[str, Any] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Change an entry's name/description and/or its request JSON."""
    dest = _resolve(path)
    rows = _load(dest)
    want = str(entry_id or "")
    for row in rows:
        if row.get("id") != want:
            continue
        if name is not None:
            clean = _clean_name(name)
            other = find_by_name(clean, dest)
            if other is not None and other.get("id") != want:
                raise ValueError(f"'{clean}' is already in the catalog")
            row["name"] = clean
        if description is not None:
            row["description"] = (description or "").strip()
        if request is not None:
            row["request"] = _clean_request(request)
        _save(dest, rows)
        return dict(row)
    raise ValueError(f"unknown catalog entry {want}")


def remove_entry(entry_id: str, path: Path | None = None) -> bool:
    dest = _resolve(path)
    rows = _load(dest)
    want = str(entry_id or "")
    kept = [row for row in rows if row.get("id") != want]
    if len(kept) == len(rows):
        return False
    _save(dest, kept)
    return True


def entry_stats(entry: dict[str, Any] | None) -> str:
    """Graph fingerprint of an entry, for the catalog table."""
    req = (entry or {}).get("request")
    return request_stats(req if isinstance(req, dict) else None)
