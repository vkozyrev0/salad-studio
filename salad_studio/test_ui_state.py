"""ui_state tests: drive the shipped load_state/save_state on temp paths.

Covers the module the audit flagged as having no dedicated test (M18).
Both functions take an optional `path`; the default-path branch is
exercised by pointing `STATE_PATH` at a temp file so the real
`~/.config/salad/studio-ui.json` is never touched.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from salad_studio import ui_state  # noqa: E402


class UiStateOnTempPaths(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "studio-ui.json"

    # ---- load_state -------------------------------------------------

    def test_missing_file_returns_none(self) -> None:
        self.assertFalse(self.path.exists())
        self.assertIsNone(ui_state.load_state(self.path))

    def test_directory_instead_of_file_returns_none(self) -> None:
        self.assertIsNone(ui_state.load_state(self.dir))

    def test_corrupt_json_returns_none(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(ui_state.load_state(self.path))

    def test_empty_file_returns_none(self) -> None:
        self.path.write_text("", encoding="utf-8")
        self.assertIsNone(ui_state.load_state(self.path))

    def test_non_object_payload_returns_none(self) -> None:
        for payload in ("[1, 2]", '"a string"', "42", "null", "true"):
            with self.subTest(payload=payload):
                self.path.write_text(payload, encoding="utf-8")
                self.assertIsNone(ui_state.load_state(self.path))

    # ---- save_state / round trip ------------------------------------

    def test_save_load_round_trip(self) -> None:
        state = {
            "geometry": "1100x720",
            "tab": "Prompt Editor",
            "nested": {"loras": [1, 2, 3], "flag": True},
            "count": 3,
            "label": "café, ✓",
        }

        ui_state.save_state(state, self.path)

        self.assertEqual(ui_state.load_state(self.path), state)

        text = self.path.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"), "the file must end in a newline")
        self.assertEqual(json.loads(text), state, "the file must be valid JSON")
        self.assertTrue(text.strip(), "the file must not be empty")

    def test_save_state_creates_missing_parent_directories(self) -> None:
        target = self.dir / "one" / "two" / "studio-ui.json"
        self.assertFalse(target.parent.exists())

        ui_state.save_state({"tab": "Config"}, target)

        self.assertTrue(target.is_file())
        self.assertEqual(ui_state.load_state(target), {"tab": "Config"})

    def test_save_state_overwrites_existing_file(self) -> None:
        ui_state.save_state({"tab": "Config"}, self.path)
        ui_state.save_state({"tab": "Logs"}, self.path)
        self.assertEqual(ui_state.load_state(self.path), {"tab": "Logs"})

    def test_empty_state_round_trips(self) -> None:
        ui_state.save_state({}, self.path)
        self.assertEqual(ui_state.load_state(self.path), {})

    # ---- default path branch ---------------------------------------

    def test_default_path_branch_uses_state_path(self) -> None:
        self.addCleanup(setattr, ui_state, "STATE_PATH", ui_state.STATE_PATH)
        ui_state.STATE_PATH = self.path

        self.assertIsNone(ui_state.load_state())
        ui_state.save_state({"tab": "Tokens"})
        self.assertTrue(self.path.is_file())
        self.assertEqual(ui_state.load_state(), {"tab": "Tokens"})


if __name__ == "__main__":
    unittest.main()
