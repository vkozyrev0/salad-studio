"""The suite. Run it from the repo root:

    python -m unittest discover -s tests -p "test_*.py"

Importing this package guards the run against a real dialog: see
``tests/_nomodal.py``. A modal would block the run until someone clicked it, so
the guard is installed before any test module is imported. The same import sets
``SALAD_STUDIO_HIDDEN`` and quiets ``deiconify`` (``tests/_hidden.py``), so no
test run maps a window onto the desktop.
"""
from __future__ import annotations

from tests import _hidden, _nomodal

_nomodal.install()
_hidden.install()
