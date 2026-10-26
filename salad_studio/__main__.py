"""``python -m salad_studio`` starts the studio's server and opens the page."""
from __future__ import annotations

import sys
from pathlib import Path

for _p in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import run_salad_studio  # noqa: E402; F401  the loader binds the stores first
from salad_studio.web import app  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    port = next((int(arg) for arg in args if arg.isdigit()), 0)
    app.run(port=port, open_browser="--no-open" not in args)


if __name__ == "__main__":
    main()
