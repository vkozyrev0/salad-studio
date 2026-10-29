"""Entry point: ``python -m salad_studio`` must start the studio's server.

Importing the package's ``__main__`` only binds the name; ``main()`` runs under
the ``__name__ == "__main__"`` guard, so nothing is served here.
"""
from __future__ import annotations

import sys
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

    def test_main_passes_the_port_and_the_open_flag_to_the_server(self) -> None:
        import salad_studio.__main__ as m
        from salad_studio.web import app

        calls: list[tuple[int, bool]] = []
        saved = app.run
        app.run = lambda *, port, open_browser: calls.append((port, open_browser))
        try:
            m.main(["--no-open", "8765"])
            m.main([])
        finally:
            app.run = saved
        self.assertEqual(calls, [(8765, False), (0, True)])

    def test_prefetch_cutout_downloads_the_model_and_starts_no_server(self) -> None:
        import salad_studio.__main__ as m
        from salad_studio import cutout
        from salad_studio.web import app

        import contextlib
        import io

        asked: list[str] = []
        saved_prefetch, saved_run = cutout.prefetch, app.run
        cutout.prefetch = lambda model=cutout.DEFAULT_MODEL: asked.append(model) or Path("models") / "u2net"
        app.run = lambda **_kwargs: self.fail("a prefetch starts no server")
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                m.main(["--prefetch-cutout"])
        finally:
            cutout.prefetch, app.run = saved_prefetch, saved_run
        self.assertEqual(asked, [cutout.DEFAULT_MODEL], "the pinned model, never the 977 MB default")
        self.assertIn(str(Path("models") / "u2net"), out.getvalue())


if __name__ == "__main__":
    unittest.main()
