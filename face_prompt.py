#!/usr/bin/env python3
"""Compose age-locked, DNA-aware face prompts from face_prompt_pack.json.

SINGLE prompt path for both /fal and /xai-image. Catalog scripts and skills
must call compose_face_prompt / compose_negative so Flux and Grok Imagine
receive the same full string (no per-backend rewriting).

  python face_prompt.py --stage children --sex female \\
      --skin fair --hair blonde --eye blue --negative
  python face_prompt.py --age-edit --stage elderly
"""
from __future__ import annotations

import argparse
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PACK_PATH = Path(__file__).resolve().parent / "face_prompt_pack.json"

# Style keys always interpolated into face_t2i (house lock for cross-backend parity).
_STYLE_KEYS = (
    "frame",
    "expression",
    "lighting",
    "background",
    "medium",
    "palette",
    "wardrobe",
    "composition_lock",
    "global_must",
    "global_negative",
)


@lru_cache(maxsize=4)
def load_pack(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else PACK_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    if "age_stages" not in data:
        raise SystemExit(f"[face_prompt] pack missing age_stages: {p}")
    return data


def _stage_entry(pack: dict[str, Any], stage: str) -> tuple[str, dict[str, Any]]:
    """Resolve catalog or engine stage label → (canonical_key, entry)."""
    stages: dict[str, Any] = pack["age_stages"]
    if stage in stages:
        return stage, stages[stage]
    for key, entry in stages.items():
        aliases = entry.get("aliases") or []
        if stage in aliases:
            return key, entry
    if "adults" in stages:
        return "adults", stages["adults"]
    if "adult" in stages:
        return "adult", stages["adult"]
    raise KeyError(f"unknown age stage {stage!r} and no adult fallback in pack")


def _noun(pack: dict[str, Any], stage_key: str, entry: dict[str, Any], sex: str) -> str:
    sex = (sex or "").lower()
    if sex == "male":
        return entry.get("noun_male") or entry.get("noun_neutral") or "person"
    if sex == "female":
        return entry.get("noun_female") or entry.get("noun_neutral") or "person"
    return entry.get("noun_neutral") or "person"


def _trait(pack: dict[str, Any], axis: str, value: str | None) -> str:
    if not value:
        return ""
    table = (pack.get("traits") or {}).get(axis) or {}
    return table.get(value) or f"{value} {axis}"


def _looks(pack: dict[str, Any], tier: str | None) -> str:
    if not tier:
        return "naturalistic everyday appearance"
    table = pack.get("looks_tier") or {}
    return table.get(tier) or f"{tier} appearance"


def _clean(text: str) -> str:
    text = text.replace(" . ", " ").replace("  ", " ")
    return " ".join(text.split())


def compose_face_prompt(
    *,
    sex: str,
    age_stage: str,
    skin_tone: str | None = None,
    hair_color: str | None = None,
    eye_color: str | None = None,
    looks_tier: str | None = None,
    pack: dict[str, Any] | None = None,
) -> str:
    """Text-to-image prompt — identical string for fal and xai backends."""
    pack = pack or load_pack()
    style = pack.get("style") or {}
    key, entry = _stage_entry(pack, age_stage)
    tpl = (pack.get("templates") or {}).get("face_t2i") or (
        "Portrait of {noun}, {years}. {skin}. {hair}. {eyes}. {frame}."
    )
    parts: dict[str, str] = {
        "noun": _noun(pack, key, entry, sex),
        "years": entry.get("years") or age_stage,
        "age_lock": entry.get("age_lock") or "",
        "proportions": entry.get("proportions") or "",
        "markers": entry.get("markers") or "",
        "skin": _trait(pack, "skinTone", skin_tone) or "natural skin tone",
        "hair": _trait(pack, "hairColor", hair_color) or "natural hair",
        "eyes": _trait(pack, "eyeColor", eye_color) or "natural eyes",
        "looks": _looks(pack, looks_tier),
        "must_not": entry.get("must_not") or "",
    }
    for sk in _STYLE_KEYS:
        parts[sk] = style.get(sk) or ""
    return _clean(tpl.format(**parts))


def compose_face_system_prompt(pack: dict[str, Any] | None = None) -> str:
    """Optional system instruction for models that accept it (nano-banana-pro)."""
    pack = pack or load_pack()
    tpls = pack.get("templates") or {}
    tpl = tpls.get("face_system") or ""
    return _clean(tpl)


def compose_age_edit_prompt(
    *,
    age_stage: str,
    pack: dict[str, Any] | None = None,
) -> str:
    """Image-edit prompt: age the anchor into another stage, keep identity."""
    pack = pack or load_pack()
    style = pack.get("style") or {}
    key, entry = _stage_entry(pack, age_stage)
    tpls = pack.get("templates") or {}
    if key == "elderly" and tpls.get("age_edit_elderly"):
        tpl = tpls["age_edit_elderly"]
    elif key == "adults" and tpls.get("age_edit_adults"):
        tpl = tpls["age_edit_adults"]
    else:
        tpl = tpls.get("age_edit") or (
            "Transform this exact person into {years}. Keep the same identity."
        )
    parts = {
        "years": entry.get("years") or age_stage,
        "age_lock": entry.get("age_lock") or "",
        "proportions": entry.get("proportions") or "",
        "markers": entry.get("markers") or "",
        "must_not": entry.get("must_not") or "",
        "global_negative": style.get("global_negative") or "",
    }
    return _clean(tpl.format(**parts))


def compose_negative(
    age_stage: str | None = None, pack: dict[str, Any] | None = None
) -> str:
    """Combined negative / Avoid string — same content for fal --negative and xai."""
    pack = pack or load_pack()
    style = pack.get("style") or {}
    bits = [style.get("global_negative") or ""]
    if age_stage:
        _k, entry = _stage_entry(pack, age_stage)
        bits.append(entry.get("must_not") or "")
    return ", ".join(b for b in bits if b)


def compose_body_prompt(
    *,
    sex: str,
    age_stage: str,
    build: str | None = None,
    hair_color: str | None = None,
    skin_tone: str | None = None,
    pregnancy_stage: str | None = None,
    pack: dict[str, Any] | None = None,
) -> str:
    """Body catalog prompt — same age_stages + house style as faces (no face).

    `pregnancy_stage`: none|early|mid|late — when early/mid/late, injects
    visible belly progression for female body plates.
    """
    pack = pack or load_pack()
    key, entry = _stage_entry(pack, age_stage)
    bs = pack.get("body_style") or {}
    builds = pack.get("body_build") or {}
    body_age = pack.get("body_age_markers") or {}
    preg_map = pack.get("body_pregnancy") or {}
    preg_key = (pregnancy_stage or "none").strip().lower() or "none"
    preg_line = preg_map.get(preg_key) or preg_map.get("none") or ""
    tpl = (pack.get("templates") or {}).get("body_t2i") or (
        "Body of {noun}, {years}. Build: {build}. {frame}."
    )
    # Prefer DNA-aware body template when present.
    if (pack.get("templates") or {}).get("body_t2i_dna"):
        tpl = pack["templates"]["body_t2i_dna"]
    if preg_key in ("early", "mid", "late") and (pack.get("templates") or {}).get(
        "body_t2i_pregnant"
    ):
        tpl = pack["templates"]["body_t2i_pregnant"]
    build_key = str(build) if build is not None else "50"
    hair = _trait(pack, "hairColor", hair_color)
    skin = _trait(pack, "skinTone", skin_tone)
    # Visible hair on shoulders must match face DNA (head still out of frame).
    if hair_color and key == "elderly":
        hair = (
            f"{hair}; elderly: greying/white-dominant hair of this color family "
            f"visible on shoulders and nape if any hair falls into frame"
        )
    elif hair_color:
        hair = (
            f"{hair}; any hair visible at the nape or shoulders MUST be this color"
        )
    parts = {
        "noun": _noun(pack, key, entry, sex),
        "years": entry.get("years") or age_stage,
        "age_lock": entry.get("age_lock") or "",
        "body_markers": body_age.get(key) or body_age.get(age_stage) or "age-accurate body",
        "build": builds.get(build_key) or builds.get("50") or "average build",
        "pregnancy": preg_line,
        "hair": hair or "natural hair color if any hair is visible at shoulders",
        "skin": skin or "natural skin tone on arms and neckline",
        "frame": bs.get("frame") or "",
        "pose": bs.get("pose") or "",
        "wardrobe": bs.get("wardrobe") or "",
        "background": bs.get("background") or "",
        "medium": bs.get("medium") or "",
        "global_must": bs.get("global_must") or "",
        "must_not": entry.get("must_not") or "",
        "body_global_negative": bs.get("global_negative") or "",
    }
    try:
        return _clean(tpl.format(**parts))
    except KeyError:
        # Older templates without {pregnancy} still work.
        parts.pop("pregnancy", None)
        return _clean(tpl.format(**parts))


def compose_young_deanime_edit_prompt(
    *,
    age_stage: str,
    pack: dict[str, Any] | None = None,
) -> str:
    """Image-edit: keep identity, shrink cartoon eyes to human scale."""
    pack = pack or load_pack()
    key, entry = _stage_entry(pack, age_stage)
    tpls = pack.get("templates") or {}
    tpl = tpls.get("young_deanime_edit") or (
        "Keep identity. Human-sized eyes. Semi-realistic villager portrait."
    )
    parts = {
        "years": entry.get("years") or age_stage,
        "age_lock": entry.get("age_lock") or "",
        "must_not": entry.get("must_not") or "",
    }
    try:
        return _clean(tpl.format(**parts))
    except KeyError:
        return _clean(tpl)


def compose_face_cleanup_edit_prompt(
    *,
    age_stage: str | None = None,
    hair_color: str | None = None,
    eye_color: str | None = None,
    pack: dict[str, Any] | None = None,
) -> str:
    """Image-edit: lock age/hair/eyes, magenta chroma, unsigned corners.

    Flux T2I has no negative channel, so these are corrected here
    (fal-ai/flux-pro/kontext), not by a longer face_t2i string.
    """
    pack = pack or load_pack()
    tpls = pack.get("templates") or {}
    tpl = tpls.get("face_cleanup_edit") or (
        "Keep identity. Human-sized eyes. Unsigned portrait, clean blank corners."
    )
    key, entry = _stage_entry(pack, age_stage or "adults")
    parts = {
        "years": entry.get("years") or (age_stage or "adult"),
        "age_lock": entry.get("age_lock") or "",
        "hair": _trait(pack, "hairColor", hair_color) or "the source hair-color family",
        "eyes": _trait(pack, "eyeColor", eye_color) or "the source eye color",
    }
    try:
        return _clean(tpl.format(**parts))
    except KeyError:
        return _clean(tpl)


def compose_body_age_edit_prompt(
    *,
    age_stage: str,
    pregnancy_stage: str | None = None,
    pack: dict[str, Any] | None = None,
) -> str:
    """Image-edit prompt: age a body-catalog anchor into another stage."""
    pack = pack or load_pack()
    key, entry = _stage_entry(pack, age_stage)
    bs = pack.get("body_style") or {}
    body_age = pack.get("body_age_markers") or {}
    preg_map = pack.get("body_pregnancy") or {}
    preg_key = (pregnancy_stage or "none").strip().lower() or "none"
    tpls = pack.get("templates") or {}
    if preg_key in ("early", "mid", "late") and tpls.get("body_age_edit_pregnant"):
        tpl = tpls["body_age_edit_pregnant"]
    else:
        tpl = tpls.get("body_age_edit") or (
            "Age this exact body into {years}. Keep identity. Head out of frame."
        )
    parts = {
        "years": entry.get("years") or age_stage,
        "age_lock": entry.get("age_lock") or "",
        "body_markers": body_age.get(key) or body_age.get(age_stage) or "age-accurate body",
        "pregnancy": preg_map.get(preg_key) or preg_map.get("none") or "",
        "frame": bs.get("frame") or "",
        "pose": bs.get("pose") or "",
        "background": bs.get("background") or "",
        "must_not": entry.get("must_not") or "",
        "body_global_negative": bs.get("global_negative") or "",
    }
    return _clean(tpl.format(**parts))


def compose_body_negative(
    age_stage: str | None = None, pack: dict[str, Any] | None = None
) -> str:
    pack = pack or load_pack()
    bs = pack.get("body_style") or {}
    bits = [bs.get("global_negative") or ""]
    if age_stage:
        _k, entry = _stage_entry(pack, age_stage)
        bits.append(entry.get("must_not") or "")
    return ", ".join(b for b in bits if b)


def resolve_stage_key(age_stage: str, pack: dict[str, Any] | None = None) -> str:
    pack = pack or load_pack()
    key, _ = _stage_entry(pack, age_stage)
    return key


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compose face prompts from the prompt pack.")
    ap.add_argument("--pack", default=str(PACK_PATH), help="path to face_prompt_pack.json")
    ap.add_argument("--stage", default="adults", help="age stage (catalog or engine label)")
    ap.add_argument("--sex", default="female")
    ap.add_argument("--skin", default="fair", dest="skin_tone")
    ap.add_argument("--hair", default="brown", dest="hair_color")
    ap.add_argument("--eye", default="brown", dest="eye_color")
    ap.add_argument("--looks", default="", dest="looks_tier")
    ap.add_argument("--age-edit", action="store_true", help="print age-from-anchor edit prompt")
    ap.add_argument("--negative", action="store_true", help="also print negative line")
    ap.add_argument("--json", action="store_true", help="emit {prompt, negative, stage_key}")
    args = ap.parse_args(argv)

    # Bust cache if a custom pack path is used in the same process.
    load_pack.cache_clear()
    pack = load_pack(args.pack)
    if args.age_edit:
        prompt = compose_age_edit_prompt(age_stage=args.stage, pack=pack)
    else:
        prompt = compose_face_prompt(
            sex=args.sex,
            age_stage=args.stage,
            skin_tone=args.skin_tone or None,
            hair_color=args.hair_color or None,
            eye_color=args.eye_color or None,
            looks_tier=args.looks_tier or None,
            pack=pack,
        )
    neg = compose_negative(args.stage, pack)
    if args.json:
        print(json.dumps({
            "stage_key": resolve_stage_key(args.stage, pack),
            "prompt": prompt,
            "negative": neg,
            "prompt_chars": len(prompt),
        }, indent=2))
    else:
        print(prompt)
        if args.negative:
            print("--- negative ---")
            print(neg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
