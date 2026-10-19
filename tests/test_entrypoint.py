"""Entry point: `python -m salad_studio` must open the Flet window.

Importing the package's `__main__` only binds the name; `main()` runs under the
`__name__ == "__main__"` guard, so no window is created here.
"""
from __future__ import annotations

import sys
import typing
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PKG = TOOLS / "salad_studio"
for _p in (PKG, TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class ModuleEntryPoint(unittest.TestCase):
    def test_main_module_runs_the_window(self) -> None:
        import salad_studio.__main__ as m
        from salad_studio import flet_app

        self.assertTrue(callable(m.main))
        self.assertIs(m.app_main, flet_app.app_main)
        self.assertIs(flet_app.main.__globals__["app_main"], flet_app.app_main)

    def test_the_windows_annotations_resolve(self) -> None:
        """Every annotation names a real object, not a missing import."""
        from salad_studio import flet_app

        for name in ("Form", "Window", "build", "app_main", "default_page"):
            with self.subTest(name=name):
                self.assertIsInstance(typing.get_type_hints(getattr(flet_app, name)), dict)


if __name__ == "__main__":
    unittest.main()
