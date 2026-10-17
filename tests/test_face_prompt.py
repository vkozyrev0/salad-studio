"""face_prompt's composers, driven from the shipped prompt pack.

The module is the single prompt path for the Eldermark face plates, and nothing
in the suite drove it: it was reached only through ``salad_probe_klein.py``,
which the root structural check reads rather than runs. (T5.)
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for _p in (TOOLS / "salad_studio", TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import face_prompt as fp  # noqa: E402

# M1/M4. A template no composer names cannot be filled — `str.format(**parts)`
# raises `KeyError` for every reader in the tree — and a block no shipped `.py`
# names is schema, not a prompt. A word-boundary scan for each name over every
# `.py` in the repo found only the pack's own definition line, so both were
# deleted. `body_style` is deliberately not in the list: `salad_probe_klein.py`
# names it (its headless frame is what the Klein probe must not copy) and so does
# `docs/workflow/14`, so it stays.
UNSUPPLIED_PARTS = ("build", "body_markers", "body_global_negative", "pose", "pregnancy")
UNREAD_BLOCKS = ("house_style_name", "sex_words", "child_stages", "defaults", "body_build")


def composerless_templates(pack: dict, composer_source: str) -> list[str]:
    """Template names the composer module never names: nothing can fill them."""
    return sorted(
        name
        for name in (pack.get("templates") or {})
        if not re.search(rf"\b{re.escape(name)}\b", composer_source)
    )


def templates_needing_an_unsupplied_part(pack: dict) -> list[str]:
    """``name: parts`` for every template asking for a part no composer supplies."""
    out: list[str] = []
    for name, tpl in (pack.get("templates") or {}).items():
        missing = [p for p in UNSUPPLIED_PARTS if f"{{{p}}}" in tpl]
        if missing:
            out.append(f"{name}: {', '.join(missing)}")
    return out


def unread_blocks(pack: dict) -> list[str]:
    """The unread blocks the pack still carries, as ``where.name``."""
    style = pack.get("style") or {}
    out: list[str] = []
    for name in UNREAD_BLOCKS:
        where = style if name == "house_style_name" else pack
        if name in where:
            out.append(f"style.{name}" if name == "house_style_name" else name)
    return out


class TheFacePrompt(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = fp.load_pack()
        self.assertTrue(self.pack, "the shipped prompt pack must load")

    def test_the_same_inputs_compose_the_same_prompt(self) -> None:
        """Both backends get one string, so the composer must be deterministic."""
        kwargs = dict(sex="female", age_stage="adults", skin_tone="fair")
        first = fp.compose_face_prompt(**kwargs)
        second = fp.compose_face_prompt(**kwargs)
        self.assertEqual(first, second)
        self.assertTrue(first.strip())

    def test_each_age_stage_composes_its_own_prompt(self) -> None:
        stages = sorted((self.pack.get("age_stages") or {}))
        self.assertTrue(stages, "the pack must name its age stages")
        seen = {}
        for stage in stages:
            with self.subTest(stage=stage):
                text = fp.compose_face_prompt(sex="female", age_stage=stage)
                self.assertTrue(text.strip(), f"{stage} composed nothing")
                self.assertNotIn("{", text, "no template placeholder may survive")
                seen[stage] = text
        self.assertEqual(
            len(set(seen.values())), len(seen), "two stages must not compose one prompt"
        )

    def test_a_chosen_trait_reaches_the_prompt(self) -> None:
        plain = fp.compose_face_prompt(sex="female", age_stage="adults")
        red = fp.compose_face_prompt(
            sex="female", age_stage="adults", hair_color="red"
        )
        self.assertNotEqual(plain, red, "a chosen hair colour must change the prompt")

    def test_looks_and_palette_reach_the_prompt(self) -> None:
        """`--looks` and style.palette are composed, so the template must show them."""
        plain = fp.compose_face_prompt(sex="female", age_stage="adults")
        striking = fp.compose_face_prompt(
            sex="female", age_stage="adults", looks_tier="striking"
        )
        comely = fp.compose_face_prompt(
            sex="female", age_stage="adults", looks_tier="comely"
        )
        palette = (self.pack.get("style") or {}).get("palette") or ""
        self.assertTrue(palette.strip(), "the pack must name a palette")
        self.assertIn(palette, plain, "the palette never reached the prompt")
        self.assertNotEqual(plain, striking, "--looks striking did not change the prompt")
        self.assertNotEqual(plain, comely, "--looks comely did not change the prompt")
        self.assertNotEqual(striking, comely)
        self.assertIn(self.pack["looks_tier"]["striking"], striking)

    def test_a_stage_states_its_age_once(self) -> None:
        """``year_band`` was a second age nobody read, and it disagreed with ``years``."""
        for key, entry in (self.pack.get("age_stages") or {}).items():
            with self.subTest(stage=key):
                self.assertNotIn("year_band", entry)
                self.assertTrue(str(entry.get("years") or "").strip())

    def test_the_infant_band_is_the_newborn_months(self) -> None:
        """Catalog and Klein used to say 0 to 3 months while the pack said 9 to 14."""
        years = self.pack["age_stages"]["infants"]["years"]
        self.assertIn("0 to 3 months", years)
        self.assertNotIn("9 to 14", years)
        text = fp.compose_face_prompt(sex="female", age_stage="infants")
        self.assertEqual(text.count("0 to 3 months"), 1)
        self.assertNotIn("9 to 14", text)

    def test_both_sexes_compose_a_noun_of_their_own(self) -> None:
        woman = fp.compose_face_prompt(sex="female", age_stage="adults")
        man = fp.compose_face_prompt(sex="male", age_stage="adults")
        self.assertNotEqual(woman, man)

    def test_a_stage_key_resolves_from_its_label(self) -> None:
        for stage in sorted((self.pack.get("age_stages") or {})):
            with self.subTest(stage=stage):
                self.assertEqual(fp.resolve_stage_key(stage, self.pack), stage)

    def test_an_alias_resolves_to_its_canonical_stage(self) -> None:
        """A name that is not itself a stage key resolves through the alias table."""
        stages = self.pack.get("age_stages") or {}
        aliases: dict[str, str] = {}
        for key, entry in stages.items():
            for alias in entry.get("aliases") or []:
                self.assertNotIn(alias, stages, f"{alias} is a key and an alias")
                self.assertNotIn(alias, aliases, f"{alias} is an alias of two stages")
                aliases[alias] = key
        self.assertTrue(aliases, "the pack must name at least one alias")
        for alias, key in sorted(aliases.items()):
            with self.subTest(alias=alias):
                self.assertEqual(fp.resolve_stage_key(alias, self.pack), key)


class TheYoungStagesKeepTheEyesAlive(unittest.TestCase):
    """The pack's expression is written for adults and used to compose every stage.

    "neutral closed-mouth adult expression … each iris SMALL … lots of white sclera
    on the inner AND outer corners … no sparkle stars", with "SMALL irises with
    visible sclera" in ``global_must`` and "sparkle catchlights" in
    ``global_negative``: composed unchanged into an infant's or a child's prompt it
    fights the stage's own "HUMAN infant eyes of natural scale" and the plate comes
    out with a blank, sclera-heavy, catchlight-free stare — a dead-looking newborn.
    A stage may now override a style key, and the two youngest stages do.
    """

    ADULT_SCLERA = "lots of white sclera on the inner AND outer corners"

    def setUp(self) -> None:
        self.pack = fp.load_pack()

    def _prompt_and_negative(self, stage: str) -> tuple[str, str]:
        return (
            fp.compose_face_prompt(sex="female", age_stage=stage),
            fp.compose_negative(age_stage=stage),
        )

    def test_an_infant_prompt_asks_for_live_eyes(self) -> None:
        prompt, negative = self._prompt_and_negative("infants")
        self.assertNotIn(
            self.ADULT_SCLERA,
            prompt,
            "the adult sclera clause must not reach an infant prompt",
        )
        for cue in ("natural catchlight", "not a blank stare", "not lifeless"):
            with self.subTest(cue=cue):
                self.assertIn(cue, prompt, f"an infant prompt must ask for {cue!r}")
        self.assertNotIn(
            "sparkle catchlights",
            negative,
            "a baby's eyes need a catchlight, so the negative must not ban it",
        )

    def test_a_child_prompt_asks_for_live_eyes(self) -> None:
        prompt, negative = self._prompt_and_negative("children")
        self.assertNotIn(self.ADULT_SCLERA, prompt)
        self.assertIn("natural catchlight", prompt)
        self.assertNotIn("sparkle catchlights", negative)

    def test_the_adult_prompt_is_unchanged(self) -> None:
        """The fix is age-aware: the calibrated adult wording must not move."""
        for stage in ("adults", "twenties"):
            with self.subTest(stage=stage):
                prompt, negative = self._prompt_and_negative(stage)
                self.assertIn(
                    self.ADULT_SCLERA,
                    prompt,
                    f"{stage} must keep the adult iris and sclera rule",
                )
                self.assertIn("neutral closed-mouth adult expression", prompt)
                self.assertIn(
                    "sparkle catchlights",
                    negative,
                    f"{stage} must keep the adult negative list",
                )


class ThePackCarriesNoDeadSchema(unittest.TestCase):
    """M1/M4: only templates a composer fills, and blocks shipped code reads.

    Eight of the twelve templates had no composer, and the four body ones named
    ``{build}``, ``{body_markers}``, ``{body_global_negative}``, ``{pose}`` and
    ``{pregnancy}``, which no shipped composer supplies — the live body path is
    ``salad_probe_klein._klein_body_prompt``, hand-written prose, so
    ``body_build`` had no reader either. ``style.house_style_name``,
    ``sex_words``, ``child_stages`` and ``defaults`` were named by no ``.py`` at
    all. All thirteen were deleted rather than kept as schema nothing can read.
    """

    def setUp(self) -> None:
        self.pack = fp.load_pack()
        self.composer = (TOOLS / "face_prompt.py").read_text(encoding="utf-8")

    def test_every_template_has_a_composer(self) -> None:
        self.assertEqual(
            composerless_templates(self.pack, self.composer),
            [],
            "a template no composer reads cannot be filled by any shipped code",
        )

    def test_no_template_asks_for_a_part_nobody_supplies(self) -> None:
        self.assertEqual(templates_needing_an_unsupplied_part(self.pack), [])

    def test_the_unread_blocks_are_gone(self) -> None:
        self.assertEqual(unread_blocks(self.pack), [])


if __name__ == "__main__":
    unittest.main()
