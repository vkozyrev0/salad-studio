"""The form the server holds: what Config and Prompt Settings both edit.

``Form`` is the one place that knows how the knob fields become a profile; it
lives on the server, so Config and Prompt Settings read one form. These tests
hold that behaviour still.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio import profiles  # noqa: E402
from salad_studio.web.form import Form  # noqa: E402


def _profile(**kw) -> profiles.SaladProfile:
    base = dict(name="klein", gateway="https://x.salad.cloud", mode="salad", graph="klein",
                width=1024, height=1024, steps=20, cfg=1, seed=1, scheduler="flux2",
                checkpoints=profiles.seed_checkpoints("klein"), selected_loras=[], policy={})
    base.update(kw)
    return profiles.SaladProfile(**base)


class FormTest(unittest.TestCase):
    def test_a_default_form_describes_the_defaults(self) -> None:
        f = Form()
        self.assertEqual((f.width, f.height, f.steps, f.cfg, f.seed), ("1024", "1024", "20", "1", "1"))
        self.assertEqual(f.graph, "klein")

    def test_a_form_round_trips_a_profile(self) -> None:
        p = _profile(width=768, height=1344, steps=8, cfg=2.5, seed=42, selected_loras=["a"])
        back = Form().from_profile(p)
        self.assertEqual((back.width, back.height, back.steps, back.cfg, back.seed),
                         ("768", "1344", "8", "2.5", "42"))
        self.assertEqual(back.selected_loras, ["a"])
        out = back.profile(p)
        self.assertEqual((out.width, out.height, out.steps, out.cfg, out.seed), (768, 1344, 8, 2.5, 42))

    def test_a_word_in_a_number_field_is_refused_by_name(self) -> None:
        f = Form(width="wide")
        with self.assertRaises(ValueError) as caught:
            f.profile()
        self.assertIn("Width", str(caught.exception))

    def test_a_seed_that_is_not_a_whole_number_is_truncated_to_its_whole_part(self) -> None:
        # The old table did the same: ``int(number(...))``. Pinned so the
        # behaviour does not silently tighten.
        f = Form(seed="1.5")
        self.assertEqual(f.profile().seed, 1)

    def test_an_empty_field_takes_the_default(self) -> None:
        f = Form(steps="", cfg="")
        out = f.profile()
        self.assertEqual((out.steps, out.cfg), (20, profiles.FORM_CFG))

    def test_selected_loras_turn_loras_on(self) -> None:
        out = Form(selected_loras=["x"]).profile()
        self.assertTrue(out.use_loras)
        self.assertEqual(Form().profile().use_loras, False)

    def test_the_stored_profile_supplies_checkpoints_and_policy(self) -> None:
        stored = _profile(checkpoints=["a.safetensors"], policy={"gpu_classes": ["RTX 4090"]})
        out = Form().from_profile(stored).profile(stored)
        self.assertEqual(out.checkpoints, ["a.safetensors"])
        self.assertEqual(out.policy, {"gpu_classes": ["RTX 4090"]})

    def test_without_a_stored_profile_the_seed_checkpoints_are_used(self) -> None:
        out = Form().profile()
        self.assertEqual(out.checkpoints, profiles.seed_checkpoints("klein"))


if __name__ == "__main__":
    unittest.main()
