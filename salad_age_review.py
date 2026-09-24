#!/usr/bin/env python3
"""Generate one Salad Flux face per catalog age band for review.

Reuses salad_gen.py (key+gateway in ~/.config/salad). Infant plate is the
approved v5 file; other bands use the same house (frontal, pink studio,
normal eye size, slight happy expression, cream linen collar).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import salad_gen

# Eldermark art output tree (outside this tool); ELDERMARK_ART overrides it.
ART = Path(os.environ.get("ELDERMARK_ART", r"C:\Users\vkozy\repos\lifesim-design\art"))
NEGATIVE = (
    "anime, manga, moe, oversized eyes, huge irises, wall-eye, crossed eyes, "
    "frown, scowl, crying, pixar, cartoon, doll"
)
HOUSE = (
    "Frontal head-and-shoulders portrait, looking straight at the camera, "
    "both eyes aligned on the lens. Realistic Northern European human, "
    "not anime, not pixar, not cartoon. Normal human eye size, not enlarged, "
    "not doll eyes. Fair skin, natural blonde hair family, blue eyes. "
    "Slight happy closed-mouth smile, gentle upturned lips, no teeth, no big grin. "
    "Soft even studio light. Pink-magenta studio backdrop. "
    "Simple cream ruffled linen collar."
)

# Unique visual bands (young_adult==twenties, adults~thirties, middle_age==fifties, elderly~seventies).
BANDS: list[tuple[str, str]] = [
    (
        "children",
        "TRUE CHILD about eight years old, elementary-school girl, pre-pubescent, "
        "not a teen, not a baby. Smaller nose, soft rounded jaw, fuller cheeks. "
        + HOUSE,
    ),
    (
        "minors",
        "TRUE TEENAGER girl 15 to 16 years old, mid-teens, not a child under 12, "
        "not a 30-year-old adult. Adolescent face longer than a child's, residual "
        "cheek softness, jaw starting to define. " + HOUSE,
    ),
    (
        "twenties",
        "TRUE young woman 25 years old, fully grown adult, not a teen, not middle-aged. "
        "Adult bone structure, youthful jaw, no grey hair, no deep wrinkles. " + HOUSE,
    ),
    (
        "thirties",
        "TRUE woman 35 years old, mid-thirties, NOT early twenties, NOT elderly. "
        "Fully mature adult face, light expression lines, lived-in pores, looks 35. "
        + HOUSE,
    ),
    (
        "forties",
        "TRUE woman 45 years old, mid-forties with clear early aging, NOT thirties youth. "
        "Visible crow's feet starting, mild nasolabial folds, possible early temple grey. "
        + HOUSE,
    ),
    (
        "fifties",
        "TRUE woman 55 years old, mid-fifties, clearly older than 40, NOT young adult. "
        "Clear crow's feet, defined nasolabial folds, greying blonde at temples, mature neck. "
        + HOUSE,
    ),
    (
        "sixties",
        "TRUE woman 65 years old, mid-sixties with advanced aging, not fifties, not frail 80. "
        "Deep crow's feet, strong nasolabial folds, substantial grey-blonde hair, wrinkled neck. "
        + HOUSE,
    ),
    (
        "seventies",
        "TRUE elderly woman 76 years old, MUST look old at a glance, deep aging required. "
        "Deep forehead furrows, heavy folds, age spots, papery skin, silver-white hair dominating, "
        "wrinkled neck rings, weathered villager elder. " + HOUSE,
    ),
    (
        "eighties",
        "TRUE elderly woman 85 years old, very old, thinner papery skin, marked frailty, "
        "white hair, deep folds, sunken cheeks, long earlobes, multiple neck rings. " + HOUSE,
    ),
]


def main() -> int:
    key = salad_gen._read(salad_gen.CONFIG / "key")
    base = salad_gen._read(salad_gen.CONFIG / "gateway").rstrip("/")
    salad_gen.wait_ready(base, key, 120)

    src_infant = ART / "salad_newborn_v5.jpg"
    dst_infant = ART / "salad_age_infants.jpg"
    if not src_infant.is_file():
        raise SystemExit(f"missing approved infant {src_infant}")
    shutil.copy2(src_infant, dst_infant)
    print(f"[copy] infants <- {src_infant.name}", flush=True)

    for stage, prompt in BANDS:
        out = ART / f"salad_age_{stage}.jpg"
        seed = salad_gen.random.randint(1, 2**48)
        payload = salad_gen.json.dumps(
            salad_gen.flux_payload(prompt, seed, 1024, 1024, 24, NEGATIVE)
        ).encode()
        print(f"[prompt] {stage} seed={seed}", flush=True)
        code, body = salad_gen._req(base + "/prompt", key, data=payload, timeout=180)
        if code != 200:
            print(f"[fail] {stage} HTTP {code} {body[:400]!r}", file=sys.stderr)
            return 2
        data = salad_gen.json.loads(body.decode("utf-8", "replace"))
        images = data.get("images") or []
        if not images:
            print(f"[fail] {stage} no images keys={list(data)[:12]}", file=sys.stderr)
            return 2
        raw = images[0]
        if isinstance(raw, str) and raw.startswith("data:"):
            raw = raw.split(",", 1)[-1]
        out.write_bytes(salad_gen.base64.b64decode(raw))
        print(f"[ok] {out.name} ({out.stat().st_size} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
