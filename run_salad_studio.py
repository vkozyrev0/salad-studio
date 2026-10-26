"""Start the studio. The one place the store imports are bound before anything runs.

``python -m salad_studio`` and ``python run_salad_studio.py`` both arrive here.
The stores live only in ``salad_studio/``, but the web layer, the tests and the
package itself import each of them by both spellings, ``import profiles`` and
``salad_studio.profiles``. A module cannot alias the package it belongs to on
its own imports without being loaded first, and ``unittest`` loads a test
module before the package. This file is imported first by both entry points, so
binding the names here is what keeps every spelling one object with one path.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "salad_studio"
for _path in (ROOT, PACKAGE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

_STORES = ("atomic", "generator", "graph_model", "hostings", "image_deploy",
           "lora_store", "profiles", "prompt_catalog", "prompt_history",
           "ref_check", "request_json", "salad_queue", "salad_status",
           "studio_log", "studio_meta", "tokens", "vast")

for _name in _STORES:
    _module = sys.modules.get(_name)
    if _module is None:
        __import__(f"salad_studio.{_name}")
        _module = sys.modules[f"salad_studio.{_name}"]
    sys.modules[_name] = _module
    sys.modules[f"salad_studio.{_name}"] = _module
    setattr(sys.modules["salad_studio"], _name, _module)


def main(argv: list[str] | None = None) -> None:
    from salad_studio.__main__ import main as run

    run(argv)


if __name__ == "__main__":
    main()
