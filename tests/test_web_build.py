"""The page's build: when the server makes one, and when it keeps the one it has.

``ui/dist`` is not committed, so a fresh clone has no page until a build writes
one. The build stamps the digest of its inputs beside ``index.html``, and that
digest, not a clock, decides whether the page on disk came from the source now.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for _p in (TOOLS, TOOLS / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio.web import app


class BuildPageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ui = Path(self.tmp.name)
        self.source = self.ui / "src"
        self.source.mkdir()
        (self.source / "main.ts").write_text("x")
        (self.ui / "angular.json").write_text("{}")
        (self.ui / "public").mkdir()
        (self.ui / "public" / "favicon.ico").write_bytes(b"ico")
        self.dist = self.ui / "dist" / "ui" / "browser"
        self.dist.mkdir(parents=True)
        self.runs: list[int] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def make(self) -> bool:
        """Stand in for ``npx ng build``: write the page and its stamp."""
        self.runs.append(1)
        (self.dist / "index.html").write_text("<app-root></app-root>")
        (self.dist / ".stamp").write_text(app._source_digest(self.source))
        return True

    def decide(self, run=None) -> bool:
        return app.build_page(self.source, self.dist, run or self.make)

    def test_a_page_with_no_build_gets_one(self) -> None:
        (self.dist / "index.html").unlink(missing_ok=True)
        self.assertTrue(self.decide())
        self.assertEqual(len(self.runs), 1)
        self.assertTrue(self.decide() is False, "a build of this source is kept")
        self.assertEqual(len(self.runs), 1)

    def test_a_changed_source_builds_again(self) -> None:
        self.decide()
        (self.source / "main.ts").write_text("changed")
        self.assertTrue(self.decide())
        self.assertEqual(len(self.runs), 2)

    def test_a_changed_public_file_builds_again(self) -> None:
        self.decide()
        (self.ui / "public" / "favicon.ico").write_bytes(b"other")
        self.assertTrue(self.decide())
        self.assertEqual(len(self.runs), 2)

    def test_a_checkout_that_restamps_files_keeps_the_build_it_shipped(self) -> None:
        self.decide()
        for path in (self.source / "main.ts", self.ui / "public" / "favicon.ico"):
            path.write_text(path.read_text())
        self.assertTrue(self.decide() is False, "a rewritten file is not a changed one")
        self.assertEqual(len(self.runs), 1)

    def test_a_page_without_a_stamp_is_not_trusted(self) -> None:
        (self.dist / "index.html").write_text("old")
        self.assertTrue(self.decide())
        self.assertEqual(len(self.runs), 1)

    def test_a_failed_build_leaves_the_page_it_had(self) -> None:
        (self.dist / "index.html").write_text("old")
        self.assertFalse(self.decide(lambda: False))
        self.assertEqual((self.dist / "index.html").read_text(), "old")


if __name__ == "__main__":
    unittest.main()
