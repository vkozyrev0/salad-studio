"""Entry-point test: `python -m salad_studio` must resolve the app's main.

Covers the module the audit flagged as untested (M19). Importing the
package's `__main__` only binds the name, `main()` runs under the
`__name__ == "__main__"` guard, so no window is created here.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PKG = TOOLS / "salad_studio"
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


class ModuleEntryPoint(unittest.TestCase):
    def test_main_module_reexports_app_main(self) -> None:
        import salad_studio.app as app
        import salad_studio.__main__ as m

        self.assertEqual(m.__name__, "salad_studio.__main__")
        self.assertTrue(callable(m.main))
        self.assertIs(m.main, app.main)

    def test_the_apps_annotations_resolve(self) -> None:
        """Every annotation names a real object, not a missing import.

        ``Any`` was used at three sites without being imported; the deferred
        annotations hid it until ``get_type_hints`` evaluated one.
        """
        import typing

        import salad_studio.app as app

        for name in ("queue_request_label", "SaladStudio._finished_label"):
            with self.subTest(name=name):
                obj = app
                for part in name.split("."):
                    obj = getattr(obj, part)
                self.assertIsInstance(typing.get_type_hints(obj), dict)


if __name__ == "__main__":
    unittest.main()
