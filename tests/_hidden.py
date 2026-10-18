"""No test may map a window onto the desktop.

``SaladStudio(show=False)`` builds the window without mapping it, but a test
that drives a button does not know which handler calls ``deiconify``, and a
test that measures a laid-out page has to map the window to get a size. The
env var is the one switch both paths honour: ``SaladStudio`` stops showing
itself when it is set, and a test's own calls to ``deiconify`` are replaced
with a no-op, so the window is built, laid out and drivable with nothing on
screen. A test that really needs a mapped window for a grab lifts the patch
deliberately, and only for its own window.
"""
from __future__ import annotations

import os
import tkinter as tk

_ENV = "SALAD_STUDIO_HIDDEN"


def install() -> None:
    """Set the env var and take deiconify off every real window."""
    os.environ[_ENV] = "1"

    def quiet(self) -> None:
        """Patched over tk.Wm: a test window is built and laid out, never shown."""

    if getattr(tk.Wm, "deiconify", None) is not quiet:
        tk.Wm.deiconify = quiet  # type: ignore[method-assign]
