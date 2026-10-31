"""The suite. The first import of ``tests`` binds the store names before any test module loads."""
import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "salad_studio"):
    if str(_p) not in _sys.path:
        _sys.path.insert(0, str(_p))

# The binding lives in the loader, which is the one place that owns it. A
# second copy of the loop here bound a module this one had already imported,
# and a test module that loaded the package first ended up with two ``tokens``
# modules, one of them still on the person's real store.
import run_salad_studio as _loader  # noqa: E402,F401  binds the store names
