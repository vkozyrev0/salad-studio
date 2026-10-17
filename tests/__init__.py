"""The suite. Run it from the repo root:

    python -m unittest discover -s tests -p "test_*.py"

Importing this package guards the run against a real dialog: see
``tests/_nomodal.py``. A modal would block the run until someone clicked it, so
the guard is installed before any test module is imported.
"""
from __future__ import annotations

from tests import _nomodal

_nomodal.install()
