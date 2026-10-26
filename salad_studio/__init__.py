"""Salad Studio, Windows helper for Salad Comfy gen/preview. Not Eldermark.

The stores live in this package, but the web layer, the tests and the package
itself import each of them by both spellings, ``import profiles`` and
``salad_studio.profiles``. ``run_salad_studio.py`` is the one loader: it binds
the two spellings to one object before anything else runs, and both entry
points reach it. This file only puts the package on the path, so a sibling's
short import resolves even when the package was loaded first.
"""
from pathlib import Path as _Path

import sys as _sys

_PACKAGE = str(_Path(__file__).resolve().parent)
if _PACKAGE not in _sys.path:
    _sys.path.insert(0, _PACKAGE)
