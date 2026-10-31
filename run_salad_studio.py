"""Start the studio, and the one function that binds its store names.

``python -m salad_studio`` and ``python run_salad_studio.py`` both arrive here.
The stores live only in ``salad_studio/``, but the web layer, the tests and the
package itself import each of them by both spellings, ``import profiles`` and
``salad_studio.profiles``. A module cannot alias the package it belongs to on
its own imports without being loaded first, and ``unittest`` loads a test
module before the package. Binding the names keeps every spelling one object
with one path, and it has to happen in one place: ``tests/__init__.py`` once
ran a second copy of this loop, and a test module that loaded the package
first left it two copies of ``tokens``, one of them on the real store.
"""
from __future__ import annotations

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


def bind_stores() -> None:
    """Make ``import tokens`` and ``salad_studio.tokens`` one object, with one path."""
    for name in _STORES:
        module = sys.modules.get(name)
        if module is None:
            __import__(f"salad_studio.{name}")
            module = sys.modules[f"salad_studio.{name}"]
        sys.modules[name] = module
        sys.modules[f"salad_studio.{name}"] = module
        setattr(sys.modules["salad_studio"], name, module)


bind_stores()


def main(argv: list[str] | None = None) -> None:
    from salad_studio.__main__ import main as run

    run(argv)


if __name__ == "__main__":
    main()
