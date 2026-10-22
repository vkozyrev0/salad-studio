"""No test module may read or write the user's own stores.

Every store the studio uses lives under ``~/.config/salad``. A test that builds
a studio and forgets to move one of those paths writes into the operator's real
files, and that has happened: an images test left two probe entries in the
shipped ``studio-images.json``. This drives the real studio with every path
moved and asserts the shipped files are untouched, then restores everything and
asserts the paths came back exactly.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for _p in (str(TOOLS), str(TOOLS / "salad_studio")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import image_deploy  # noqa: E402
import profiles  # noqa: E402
import prompt_catalog  # noqa: E402
import prompt_history  # noqa: E402
import salad_queue  # noqa: E402
import tokens  # noqa: E402
import vast  # noqa: E402

STORE_PATHS = (
    (profiles, "PROFILES_PATH"),
    (image_deploy, "SETTINGS_PATH"),
    (prompt_catalog, "CATALOG_PATH"),
    (prompt_history, "HISTORY_PATH"),
    (prompt_history, "THUMBS_DIR"),
    (vast, "INSTANCES_PATH"),
    (salad_queue, "LEDGER_PATH"),
    (tokens, "LOCAL_PATH"),
)


def _shipped() -> dict[str, Path]:
    """The store paths as they ship, read before any test fixture moves them."""
    return {f"{module.__name__}.{name}": Path(getattr(module, name))
            for module, name in STORE_PATHS}


def _snapshot(paths: dict[str, Path]) -> dict[str, bytes | None]:
    """Each shipped store's bytes, or None when it does not exist."""
    return {key: (path.read_bytes() if path.is_file() else None) for key, path in paths.items()}


class TheStudioMovesEveryStore(unittest.TestCase):
    def test_building_a_studio_leaves_the_shipped_stores_untouched(self) -> None:
        from tests._studio import studio

        shipped = _shipped()
        before = _snapshot(shipped)
        with studio() as made:
            after_enter = _snapshot(shipped)
            self.assertEqual(after_enter, before, "building the studio wrote a shipped store")
            # A page's state and one write, the way a person's first minute goes.
            self.assertIn("slots", made.state("tokens"))
            made.act("config", "add_vast", {"endpoint": "203.0.113.9:31234"})
            self.assertNotEqual(_snapshot(_shipped()), before, "the write went nowhere at all")
        self.assertEqual(_snapshot(shipped), before, "a stopped studio left a shipped store changed")

    def test_stopping_a_studio_puts_every_path_back(self) -> None:
        from tests._studio import Studio

        shipped = {key: getattr(module, name) for module, name in STORE_PATHS
                   for key in [f"{module.__name__}.{name}"]}
        made = Studio()
        try:
            moved = {key: getattr(module, name) for module, name in STORE_PATHS
                     for key in [f"{module.__name__}.{name}"]}
            self.assertEqual(set(moved), set(shipped))
            for key in moved:
                self.assertNotEqual(moved[key], shipped[key], f"{key} was never moved")
        finally:
            made.stop()
        restored = {key: getattr(module, name) for module, name in STORE_PATHS
                    for key in [f"{module.__name__}.{name}"]}
        self.assertEqual(restored, shipped)


if __name__ == "__main__":
    unittest.main()
