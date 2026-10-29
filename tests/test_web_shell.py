"""The shell: which page is open, the status line, and the two notes that report.

The shell state lives in ``Shell``, on the core thread. These tests drive it
directly, with the stores pointed at a temporary directory, so the suite never
reads or writes the user's profiles.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import profiles  # noqa: E402
from salad_studio.web import shell as shell_mod  # noqa: E402
from salad_studio.web.core import Core  # noqa: E402
from salad_studio.web.events import Hub  # noqa: E402


class ShellTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.saved_path = profiles.PROFILES_PATH
        profiles.PROFILES_PATH = Path(self.tmp.name) / "studio-profiles.json"
        self.core = Core(workers=1).start()
        self.hub = Hub()
        self.shell = shell_mod.Shell(self.core, self.hub)

    def tearDown(self) -> None:
        self.core.stop()
        profiles.PROFILES_PATH = self.saved_path
        self.tmp.cleanup()

    def test_the_default_page_is_the_first_rail_entry(self) -> None:
        self.assertEqual(self.shell.current, "config")

    def test_opening_a_page_records_it(self) -> None:
        self.shell.open_page("queue")
        self.assertEqual(self.shell.state_dict()["current"], "queue")

    def test_a_note_writes_the_status_line_and_the_page_note(self) -> None:
        self.shell.note("Saved the keys", level="ok")
        state = self.shell.state_dict()
        self.assertEqual(state["status"], {"text": "Saved the keys", "level": "ok"})
        self.assertEqual(state["note"], {"text": "Saved the keys", "level": "ok"})

    def test_an_unknown_level_is_reported_as_info(self) -> None:
        self.shell.note("odd", level="purple")
        self.assertEqual(self.shell.state_dict()["status"]["level"], "info")

    def test_the_status_line_starts_with_the_rest_text(self) -> None:
        self.assertEqual(self.shell.state_dict()["status"]["text"], shell_mod.REST_TEXT)

    def test_a_message_logs_a_line_as_well(self) -> None:
        seen: list[tuple[str, str]] = []
        self.shell.services.log = lambda level, text: seen.append((level, text))
        self.shell.message("Kept the profile", level="info")
        self.assertEqual(seen, [("info", "Kept the profile")])

    def test_confirms_are_capped_and_the_oldest_goes_first(self) -> None:
        tokens = [self.shell.issue_confirm("shell", "clean_gallery", {"n": n})
                  for n in range(shell_mod.CONFIRM_CAP + 5)]
        self.assertEqual(len(self.shell.confirms), shell_mod.CONFIRM_CAP)
        self.assertIsNone(self.shell.take_confirm(tokens[0]), "the oldest was evicted")
        self.assertIsNone(self.shell.take_confirm(tokens[4]), "the oldest was evicted")
        self.assertEqual(self.shell.take_confirm(tokens[5]), ("shell", "clean_gallery", {"n": 5}))
        self.assertIsNone(self.shell.take_confirm(tokens[5]), "still single use")

    def test_state_serializes_to_the_shape_the_page_reads(self) -> None:
        row = self.shell.state_dict()
        for key in ("current", "status", "note", "gen", "saladWord", "counts", "plates", "busy"):
            self.assertIn(key, row)
        self.assertEqual(len(row["counts"]), 3)
        self.assertIsInstance(row["plates"], list)


if __name__ == "__main__":
    unittest.main()
