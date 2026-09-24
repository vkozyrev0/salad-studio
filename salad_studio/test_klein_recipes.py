"""The two-body Klein plate recipe, anchored to the ledger's human-verified entry.

**What this module asserts changed on 2026-09-23.** It used to pin a 4-LoRA,
6/12-step, 5,049-char sectioned-prompt stack and to state that "the prompt
architecture is the quality lever". Both were superseded: the only recipe a human
has judged is the one ``prompt_ledger.json`` records under ``verdicts``, and the
measured finding is the opposite of that claim — the **seed** dominates (2 of 7
seeds acceptable), and the winning prompt is 779 chars, not 5,049.

So the operating point is no longer written down here. It is read from the
ledger, and the ledger's ``verdicts[0].provenance.recipe`` names the file under
test. Editing the recipe without re-judging it fails these tests, which is the
point: a prompt is only "good" because a human said so.

The tests still drive both files through the same gates Generate uses —
``json_highlight.verify_request_json`` (editor) and
``comfy_import.prompt_for_salad_replica`` (the POST copy).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for p in (str(TOOLS), str(HERE)):
    if str(p) not in sys.path:
        sys.path.insert(0, p)

from salad_studio import comfy_import as ci  # noqa: E402
from salad_studio import json_highlight  # noqa: E402

KLEIN_DIR = TOOLS / "salad_klein"
LEDGER_PATH = KLEIN_DIR / "prompt_ledger.json"

# Superseded: the research-era 4-LoRA stack. Kept on disk as the record of what
# was tried; no human verdict covers either file (see the ledger's `verdicts`).
SUPERSEDED = (
    KLEIN_DIR / "prompt_snofs_distilled_anatomy.json",
    KLEIN_DIR / "prompt_snofs_distilled_anatomy_resms.json",
)

# A left-in placeholder is worse than no line at all: it renders as an unknown
# all-caps token mid-sentence and adherence collapses (measured).
FORBIDDEN = ("REPLACE_THIS", "REPLACE THIS", "TODO", "TBD", "XXX", "FIXME")

# The SNOFS LoKr. The verified unet already IS SNOFS, so loading it double-applies.
SNOFS_LOKR_ID = "2960556"


def _ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _verified() -> dict:
    """The ledger entry a human judged good. Fails loudly if there is none."""
    good = [v for v in _ledger().get("verdicts", []) if v.get("status") == "good"]
    if not good:
        raise AssertionError("prompt_ledger.json records no human-verified entry")
    return good[0]


def RECIPE() -> Path:
    """The recipe the verified entry names. The ledger decides, not this file."""
    return TOOLS / _verified()["provenance"]["recipe"]


def _editor(path: Path | None = None) -> dict:
    return json.loads((path or RECIPE()).read_text(encoding="utf-8"))


def _payload(path: Path | None = None) -> dict:
    return ci.prompt_for_salad_replica(_editor(path)["prompt"])


def _node(prompt: dict, class_type: str) -> dict:
    found = [n for n in prompt.values() if isinstance(n, dict) and n.get("class_type") == class_type]
    if len(found) != 1:
        raise AssertionError(f"expected exactly one {class_type}, found {len(found)}")
    return found[0]


class LedgerAnchor(unittest.TestCase):
    """The recipe under test is the one the ledger verified — not a copy of it."""

    def test_the_ledger_names_a_recipe_that_exists(self) -> None:
        self.assertTrue(LEDGER_PATH.is_file(), f"missing {LEDGER_PATH}")
        path = RECIPE()
        self.assertTrue(path.is_file(), f"the ledger names a missing recipe: {path}")

    def test_the_verified_entry_has_the_users_own_verdict_words(self) -> None:
        entry = _verified()
        self.assertEqual(entry["status"], "good")
        self.assertTrue((entry.get("user_verdict") or "").strip())
        self.assertTrue(entry.get("good_seeds"), "no seed judged good")
        self.assertTrue(entry.get("bad_seeds"), "no seed judged bad")

    def test_a_superseded_recipe_is_not_claimed_as_verified(self) -> None:
        """The 4-LoRA stack stays on disk, but no verdict may cover it."""
        claimed = {v["provenance"]["recipe"] for v in _ledger().get("verdicts", [])}
        for path in SUPERSEDED:
            with self.subTest(recipe=path.name):
                rel = path.relative_to(TOOLS.parent.parent).as_posix()
                self.assertNotIn(rel, claimed, "a superseded recipe carries a verdict")


class OperatingPoint(unittest.TestCase):
    """Every knob here is compared to the ledger's ``graph`` block, not retyped."""

    def setUp(self) -> None:
        self.graph = _ledger()["graph"]
        self.prompt = _editor()["prompt"]

    def test_unet_clip_and_vae(self) -> None:
        self.assertEqual(_node(self.prompt, "UNETLoader")["inputs"]["unet_name"], self.graph["unet"])
        self.assertEqual(_node(self.prompt, "CLIPLoader")["inputs"]["clip_name"], self.graph["clip"])
        self.assertEqual(_node(self.prompt, "CLIPLoader")["inputs"]["type"], "flux2")
        self.assertEqual(_node(self.prompt, "VAELoader")["inputs"]["vae_name"], self.graph["vae"])

    def test_sampler_steps_and_cfg(self) -> None:
        self.assertEqual(
            _node(self.prompt, "KSamplerSelect")["inputs"]["sampler_name"], self.graph["sampler"]
        )
        self.assertEqual(_node(self.prompt, "Flux2Scheduler")["inputs"]["steps"], self.graph["steps"])
        self.assertEqual(_node(self.prompt, "CFGGuider")["inputs"]["cfg"], self.graph["cfg"])

    def test_size_and_scheduler_agree(self) -> None:
        latent = _node(self.prompt, "EmptyFlux2LatentImage")["inputs"]
        sched = _node(self.prompt, "Flux2Scheduler")["inputs"]
        self.assertEqual((latent["width"], latent["height"]), (self.graph["width"], self.graph["height"]))
        self.assertEqual((sched["width"], sched["height"]), (latent["width"], latent["height"]))

    def test_the_lora_set_is_exactly_what_the_ledger_records(self) -> None:
        found = sorted(
            (nid for nid, n in self.prompt.items()
             if isinstance(n, dict) and str(n.get("class_type", "")).startswith("LoraLoader")),
            key=int,
        )
        self.assertEqual(
            [row["node"] for row in self.graph["loras"]],
            found,
            "the recipe's LoRA chain no longer matches prompt_ledger.json's graph.loras",
        )

    def test_the_snofs_lokr_is_not_stacked_on_the_snofs_unet(self) -> None:
        """The unet already is SNOFS; the LoKr would double-apply it."""
        self.assertNotIn(SNOFS_LOKR_ID, RECIPE().read_text(encoding="utf-8"))


class PromptText(unittest.TestCase):
    """The text under test is the text the human judged."""

    def test_the_positive_prompt_is_the_verified_text(self) -> None:
        entry = _verified()
        node = _ledger()["replacements"][0]["node"]
        self.assertEqual(_editor()["prompt"][node]["inputs"]["text"], entry["prompt"])

    def test_the_negative_prompt_is_the_verified_text(self) -> None:
        entry = _verified()
        node = _ledger()["replacements"][0]["negative_node"]
        self.assertEqual(_editor()["prompt"][node]["inputs"]["text"], entry["negative"])

    def test_no_placeholder_token_survives(self) -> None:
        for node in _payload():
            if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
                text = str(node["inputs"].get("text") or "")
                for bad in FORBIDDEN:
                    self.assertNotIn(bad, text, bad)

    def test_the_negative_stays_short(self) -> None:
        """At CFG 1 the negative is inert; a long defect list only forbids poses."""
        entry = _verified()
        self.assertLess(len(entry["negative"]), 400, "the negative grew past the style-only rule")


class PayloadGates(unittest.TestCase):
    """Both gates Generate uses, on the verified recipe."""

    def test_the_editor_gate_accepts_it(self) -> None:
        ok, msg = json_highlight.verify_request_json(RECIPE().read_text(encoding="utf-8"))
        self.assertTrue(ok, msg)

    def test_convert_output_is_jpeg(self) -> None:
        conv = _editor()["convert_output"]
        self.assertEqual(conv["format"], "jpeg")
        self.assertEqual(conv["options"]["quality"], 90)

    def test_the_post_copy_keeps_every_node(self) -> None:
        raw = _editor()["prompt"]
        posted = _payload()
        self.assertEqual(set(raw), set(posted))

    def test_every_edge_resolves(self) -> None:
        prompt = _editor()["prompt"]
        ids = set(prompt)
        for nid, node in prompt.items():
            if not isinstance(node, dict):
                continue
            for name, value in (node.get("inputs") or {}).items():
                if (
                    isinstance(value, list)
                    and len(value) == 2
                    and isinstance(value[0], str)
                    and value[1] in (0, 1)
                ):
                    self.assertIn(value[0], ids, f"{nid}.{name} -> {value[0]}")

    def test_the_post_copy_keeps_the_prompt_text(self) -> None:
        posted = _payload()
        entry = _verified()
        node = _ledger()["replacements"][0]["node"]
        self.assertEqual(posted[node]["inputs"]["text"], entry["prompt"])


if __name__ == "__main__":
    unittest.main()
