"""``salad_age_review``'s shipped data: the age bands and their shared wording.

The script has no helper functions; its testable surface is the module data it
renders from. These drive ``BANDS``, ``HOUSE``, ``NEGATIVE`` and ``ART`` as the
reader of the module sees them, so a band that loses its house wording, gains a
placeholder, or repeats a stage name fails here.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import salad_age_review as age_review  # noqa: E402

# A left-in placeholder renders as an unknown all-caps token mid-prompt.
PLACEHOLDERS = ("REPLACE_THIS", "REPLACE THIS")


class TheAgeBands(unittest.TestCase):
    def test_the_stage_names_are_unique(self) -> None:
        names = [name for name, _prompt in age_review.BANDS]
        self.assertTrue(names, "BANDS names no stages")
        self.assertEqual(len(names), len(set(names)), f"duplicate stage in {names}")

    def test_every_band_carries_prompt_text(self) -> None:
        for name, prompt in age_review.BANDS:
            with self.subTest(stage=name):
                self.assertTrue(prompt.strip(), f"{name} has no prompt text")

    def test_every_band_carries_the_house_wording(self) -> None:
        for name, prompt in age_review.BANDS:
            with self.subTest(stage=name):
                self.assertIn(age_review.HOUSE, prompt)

    def test_no_band_leaves_a_placeholder(self) -> None:
        for name, prompt in age_review.BANDS:
            for token in PLACEHOLDERS:
                with self.subTest(stage=name, token=token):
                    self.assertNotIn(token, prompt)


class TheSharedWording(unittest.TestCase):
    def test_the_negative_and_house_text_are_non_empty_strings(self) -> None:
        for name in ("NEGATIVE", "HOUSE"):
            text = getattr(age_review, name)
            with self.subTest(name=name):
                self.assertIsInstance(text, str)
                self.assertTrue(text.strip())

    def test_the_art_root_follows_its_environment_override(self) -> None:
        import importlib
        import os
        import tempfile
        from unittest import mock

        saved = age_review.ART
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"ELDERMARK_ART": tmp}):
                reloaded = importlib.reload(age_review)
                self.assertEqual(reloaded.ART, Path(tmp))
        importlib.reload(age_review)
        self.assertEqual(age_review.ART, saved)


if __name__ == "__main__":
    unittest.main()
