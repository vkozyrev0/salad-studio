"""Entry point: ``python -m salad_studio`` must start the studio's server.

Importing the package's ``__main__`` only binds the name; ``main()`` runs under
the ``__name__ == "__main__"`` guard, so nothing is served here.
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
    def test_main_module_runs_the_server(self) -> None:
        import salad_studio.__main__ as m
        from salad_studio.web import app

        self.assertTrue(callable(m.main))
        self.assertIs(m.app, app)
        self.assertTrue(callable(app.run))

    def test_the_entry_point_annotations_resolve(self) -> None:
        from salad_studio.web import app

        for name in ("build", "run", "Studio"):
            with self.subTest(name=name):
                target = getattr(app, name)
                if isinstance(target, type):
                    target = target.__init__
                self.assertIsInstance(typing.get_type_hints(target), dict)


if __name__ == "__main__":
    unittest.main()
