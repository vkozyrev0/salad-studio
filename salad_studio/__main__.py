"""``python -m salad_studio`` opens the window."""
from __future__ import annotations

import sys
from pathlib import Path

for _p in (Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import flet as ft  # noqa: E402

from salad_studio.flet_app import app_main  # noqa: E402


def main() -> None:
    ft.run(app_main)


if __name__ == "__main__":
    main()
