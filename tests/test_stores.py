"""A discover run must never read the user's own ``studio-queue.json``.

A window builds a ``SaladQueue``, and the queue persists its container ledger to
``salad_queue.LEDGER_PATH``. Four modules construct a window and redirect their
own stores; the ledger was left alone, and only ``tests/test_app_layout.py``
moved it - whose ``tearDownModule`` puts the shipped path back, so every module
after it ran against the user's own file.
"""
from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for _p in (str(TOOLS), str(TOOLS / "salad_studio")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import salad_queue as top_queue  # noqa: E402

from salad_studio import salad_queue as pkg_queue  # noqa: E402

# The modules that build a real window without going through `_TempPaths`.
WINDOW_MODULES = (
    "tests.test_json_editor",
    "tests.test_profiles",
    "tests.test_prompt_history",
    "tests.test_theme",
    "tests.test_tokens",
)


class EveryWindowModuleRedirectsTheLedger(unittest.TestCase):
    def _ledger_paths(self) -> tuple[Path, Path]:
        return (Path(top_queue.LEDGER_PATH), Path(pkg_queue.LEDGER_PATH))

    def test_each_module_moves_the_ledger_off_the_users_store(self) -> None:
        temp = Path(tempfile.gettempdir())
        for name in WINDOW_MODULES:
            with self.subTest(module=name):
                module = importlib.import_module(name)
                before = self._ledger_paths()
                self.assertTrue(
                    callable(getattr(module, "setUpModule", None)),
                    f"{name} builds a window and must move the queue ledger",
                )
                module.setUpModule()
                try:
                    moved = self._ledger_paths()
                    self.assertNotEqual(
                        moved,
                        before,
                        f"{name}'s setup left the ledger where it found it",
                    )
                    for path in moved:
                        self.assertIn(
                            temp,
                            path.parents,
                            f"{name} moved the ledger to {path}, not a temp file",
                        )
                finally:
                    module.tearDownModule()
                self.assertEqual(
                    self._ledger_paths(),
                    before,
                    f"{name} must put the shipped ledger path back when it ends",
                )
