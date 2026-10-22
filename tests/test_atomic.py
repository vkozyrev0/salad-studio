"""The file replace that keeps a reader from seeing a half-written store."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import atomic  # noqa: E402


class AtomicWriteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "store.json"

    def test_the_new_document_is_what_a_reader_gets(self) -> None:
        atomic.write_text(self.path, '{"a": 1}\n')
        atomic.write_text(self.path, '{"a": 2}\n')
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"a": 2}\n')
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [], "no temp file is left")

    def test_a_failed_replace_keeps_the_old_document(self) -> None:
        self.path.write_text('{"a": 1}\n', encoding="utf-8")
        with mock.patch.object(atomic.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                atomic.write_text(self.path, '{"a": 2}\n')
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"a": 1}\n')
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [], "the temp file is cleaned up")


if __name__ == "__main__":
    unittest.main()
