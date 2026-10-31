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
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for _p in (str(TOOLS), str(TOOLS / "salad_studio")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import image_deploy  # noqa: E402
import model_catalog  # noqa: E402
import profiles  # noqa: E402
import prompt_catalog  # noqa: E402
import prompt_history  # noqa: E402
import salad_queue  # noqa: E402
import tokens  # noqa: E402
import vast  # noqa: E402
import run_salad_studio  # noqa: E402
from salad_studio.web.pages import config as config_page  # noqa: E402
from tests._paths import _TempPaths  # noqa: E402

server_package = run_salad_studio.PACKAGE

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


class ReadingAKeyLeavesTheUserStoreAlone(unittest.TestCase):
    """Reading a key seeds the store, and seeding writes.

    Several modules read ``salad_studio.tokens``: ``model_catalog`` fetching a
    model, the Tokens page, the Logs page redacting a line. A seed through any
    of them must land in a test's temp store, never the operator's. That one
    gap let a doc test at the front of the suite and a fetch test further down
    repoint a path together and write the real ``studio-tokens.json``.
    """

    def test_a_seed_from_any_module_does_not_write_the_shipped_store(self) -> None:
        # The path the store ships with, not whichever module a test holds now.
        real = server_package / "studio-tokens.json"
        before = real.read_bytes() if real.is_file() else None
        with tempfile.TemporaryDirectory() as td, _TempPaths(Path(td)):
            # Every module that can read a key: a fetch, a page state, a history
            # prompt, a connection test.
            model_catalog.civitai_token()
            config_page._token_map(None)
            prompt_history.prompt_text_of({"prompt": {"1": {"class_inputs": {}}}})
            vast.fetch_instances("", sender=lambda request, timeout: (0, b""))
            for kind, _label, _rel in tokens.TOKEN_SPECS:
                tokens.read_token(kind)
            self.assertNotEqual(tokens.LOCAL_PATH, real, "the fixture moved no token store")
        after = real.read_bytes() if real.is_file() else None
        self.assertEqual(after, before, "reading a key wrote the shipped token store")


if __name__ == "__main__":
    unittest.main()
