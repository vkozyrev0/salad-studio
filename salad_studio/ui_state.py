"""Salad Studio window state. Saved on close, restored on open.

Secrets (API keys and token fields) are not stored here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_PATH = Path.home() / ".config" / "salad" / "studio-ui.json"


def load_state(path: Path | None = None) -> dict[str, Any] | None:
    target = path if path is not None else STATE_PATH
    try:
        if not target.is_file():
            return None
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    target = path if path is not None else STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
