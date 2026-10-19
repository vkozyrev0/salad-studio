"""The hosting adapters are the single source for the targets Generate dispatches to.

Adding a hosting is a class in ``hostings.ADAPTERS``. This module fails loudly
until the adapter satisfies the interface and the press dispatches through it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "salad_studio"
for _p in (PKG, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hostings  # noqa: E402


class _App:
    """The three app members the adapters call, so the interface can be checked
    without building a Tk window."""

    def _generate_salad(self, payload, profile) -> None:
        return None

    def _on_generate_vast(self, payload, profile) -> None:
        return None

    def _vast_active(self):
        return None


class HostingsTable(unittest.TestCase):
    def test_every_adapter_has_a_unique_key(self) -> None:
        keys = [cls.key for cls in hostings.ADAPTERS]
        self.assertTrue(keys, "ADAPTERS is empty")
        self.assertEqual(len(keys), len(set(keys)), "ADAPTERS keys must be unique")
        self.assertEqual(
            hostings.BY_KEY, {cls.key: cls for cls in hostings.ADAPTERS}
        )

    def test_default_is_in_by_key(self) -> None:
        self.assertIn(hostings.DEFAULT, hostings.BY_KEY)

    def test_every_adapter_satisfies_the_interface(self) -> None:
        for cls in hostings.ADAPTERS:
            adapter = cls(_App())
            self.assertIsInstance(adapter, hostings.Hosting, cls.__name__)
            self.assertTrue(adapter.label, f"{cls.__name__} needs a radio label")
            self.assertTrue(adapter.url_label, f"{cls.__name__} needs a URL label")
            url, reason = adapter.pick_url()
            self.assertIsInstance(url, str)
            self.assertIsInstance(reason, str)
            self.assertTrue(callable(adapter.generate))

    def test_the_generate_press_dispatches_through_the_adapter(self) -> None:
        """The window reads the profile's hosting from the adapter table."""
        from salad_studio import flet_app

        source = (PKG / "flet_app.py").read_text(encoding="utf-8")
        self.assertIn("p.mode if p.mode in hostings.BY_KEY else hostings.DEFAULT", source)
        self.assertIs(flet_app.hostings, __import__("hostings"))

    def test_a_vast_adapter_refuses_when_no_row_is_selected(self) -> None:
        url, reason = hostings.BY_KEY["vast"](_App()).pick_url()
        self.assertEqual(url, "")
        self.assertIn("No vast.ai instance", reason)


if __name__ == "__main__":
    unittest.main()
