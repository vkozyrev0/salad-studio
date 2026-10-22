"""Replace a small JSON file without leaving a half-written one.

The stores here are read by other threads while a save runs: the 15 s probe
reads the token file, a page reads the history, the queue reads the ledger. A
``write_text`` truncates first, so a reader can see an empty file and treat it
as "no records". Writing a sibling temp file and replacing the target makes the
read either the old document or the new one.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


def write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically, creating the parent directory."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        # Windows refuses the replace while a reader holds the target open.
        # A few short retries cover the probe or a page load reading it now.
        for attempt in range(5):
            try:
                os.replace(tmp_name, target)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
