#!/usr/bin/env python3
"""Probe faces / bodies / pregnancies / events on the Flux.2 Klein Salad group.

Uses ~/.config/salad/gateway-klein (not loganberry). Face prompts come from
face_prompt.py. Body prompts are Klein full-figure (painted face, cream
paper) — not catalog compose_body_prompt, which is headless. Mass catalog
freeze is unchanged.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import face_prompt  # noqa: E402
import salad_gen  # noqa: E402

# Eldermark art output tree (outside this tool); ELDERMARK_ART overrides it.
ART = Path(os.environ.get("ELDERMARK_ART", r"C:\Users\vkozy\repos\lifesim-design\art"))
STYLE = "ArsMJStyle, Impressionism"
PAPER = (
    "cream paper ground, warm off-white, NOT magenta, NOT chroma-key, "
    "NOT hot pink background"
)
NO_MARK = "no artist signature, no initials, no date, no watermark, no text"
FULL_FIG = (
    "entire person in frame from crown of head to soles of both feet, "
    "small figure with margin above the head and below the feet, "
    "do not crop legs, do not crop the skull"
)
INFANT = (
    "NEWBORN 0 to 3 months only, tiny infant, large cranium, cannot sit "
    "unsupported, not a toddler, not a two-year-old, not a preschooler"
)
THIRTIES = (
    "about 35 years old, mid-thirties adult, not grey or white hair, "
    "not elderly, not a child"
)
FACE_LOCK = (
    "exactly two adult figures close to camera, faces large in the frame, "
    "each face has two eyes one nose one mouth, readable features, "
    "not melted, not smeared, not extra limbs, not a crowd of tiny heads"
)
# Catalog compose_body_prompt is HEADLESS (face composited later). Klein
# full-figure probes need a painted face; stacking the pack's "headless"
# line with FULL_FIG blanked male faces and cropped skulls.
FACE_ON_BODY = (
    "painted human face with two eyes one nose one mouth, readable "
    "features, not blank, not a white oval, not headless, not a mannequin"
)
WARDROBE = (
    "simple medieval villager tunic, muted brown russet cream or grey "
    "linen, belt, boots, never green olive or sage clothing"
)
_MAGENTA = re.compile(
    r"(?i)(chroma-?key|#FF00FF|\bmagenta\b|hot pink|pink background)"
)


def _no_magenta(text: str) -> str:
    """Drop pack chroma so Klein probes use cream paper, not catalog knockout."""
    t = _MAGENTA.sub(" ", text)
    t = re.sub(r"\s+", " ", t).strip(" .,")
    return f"{t}. {PAPER}. {NO_MARK}."


def _face_stages() -> tuple[str, ...]:
    return tuple(face_prompt.load_pack()["age_stages"].keys())


def _klein_body_prompt(
    *,
    sex: str,
    stage: str,
    ang: str,
    pregnancy: str = "none",
) -> str:
    """Full-figure Klein body — painted face, cream paper, not catalog-headless."""
    pack = face_prompt.load_pack()
    key, entry = face_prompt._stage_entry(pack, stage)
    noun = face_prompt._noun(pack, key, entry, sex)
    years = entry.get("years") or stage
    age_lock = entry.get("age_lock") or ""
    markers = (pack.get("body_age_markers") or {}).get(key) or "age-accurate body"
    angle_line = {
        "front": "front view facing the camera",
        "45": "three-quarter view, 45 degrees to camera",
        "side": "strict side profile, full body from the side",
    }[ang]
    if key == "infants":
        figure = f"full-length figure of a real living baby, {noun}, {years}"
    else:
        figure = f"full-length standing figure of a real living human, {noun}, {years}"
    bits = [
        STYLE,
        figure,
        "not a doll, not a rag doll, not a mannequin, not a toy, not a reborn doll",
        age_lock,
        markers,
        angle_line,
        FACE_ON_BODY,
        FULL_FIG,
        WARDROBE,
        "fair skin, blonde hair",
        PAPER,
        NO_MARK,
    ]
    if key == "infants":
        bits.append(
            f"{INFANT}. real living baby lying on cream paper, short limbs, "
            "cannot stand, not a standing toddler, not a doll"
        )
    elif key in {"adults", "thirties", "twenties", "young_adult"}:
        bits.append(THIRTIES)
    preg_key = (pregnancy or "none").strip().lower()
    if preg_key in ("early", "mid", "late"):
        preg_line = (pack.get("body_pregnancy") or {}).get(preg_key) or preg_key
        bits.append(
            f"{preg_line}. the rounded belly is under a loose linen gown; "
            "fabric covers the bump; not a painted sphere on top of the dress, "
            "not nude, not a balloon"
        )
    return re.sub(r"\s+", " ", ". ".join(b for b in bits if b)).strip(" .,") + "."
BODY_ANGLES = ("front", "45", "side")
EVENTS = (
    (
        "wedding",
        "oil painting of a village wedding outdoors, bride and groom adults, "
        "townsfolk watching, cream dresses, daylight, cream paper, "
        + NO_MARK,
    ),
    (
        "funeral",
        "oil painting of a village funeral, adults in dark clothes around a "
        "plain coffin, grey sky, cream paper, " + NO_MARK,
    ),
    (
        "harvest",
        "oil painting of a late-summer grain harvest, adults working the "
        "field, sheaves, warm light, cream paper, " + NO_MARK,
    ),
    (
        "tavern",
        "oil painting of a crowded tavern, adult townsfolk eating and talking, "
        "lamplight, wooden tables, cream paper, " + NO_MARK,
    ),
    (
        "storm",
        "oil painting of a hard storm over a coastal village, adults on the "
        "shore, crashing waves, cream paper, " + NO_MARK,
    ),
    (
        "birth",
        "oil painting of a midwife and adult mother after a birth, newborn "
        "swaddled, candlelit cottage, non-sexual, cream paper, " + NO_MARK,
    ),
    (
        "market",
        "oil painting of a busy village market square, adult stallholders "
        "and shoppers, baskets of bread and cloth, daylight, cream paper, "
        + NO_MARK,
    ),
    (
        "church",
        "oil painting of a small village church interior, adults at prayer, "
        "wooden pews, candlelight, cream paper, " + NO_MARK,
    ),
    (
        "feast",
        f"{FACE_LOCK}. oil painting of two adults seated at a feast table, "
        f"heads and torsos visible not floating heads, roast and bread, "
        f"firelight, faces clearly painted, cream paper, " + NO_MARK,
    ),
    (
        "sickbed",
        f"{FACE_LOCK}. oil painting of one adult at a bedside and one adult "
        f"lying ill, bowl and cloth, dim cottage, both faces clearly painted, "
        f"cream paper, " + NO_MARK,
    ),
)


def klein_payload(
    text: str,
    *,
    seed: int,
    width: int,
    height: int,
    steps: int = 20,
    use_loras: bool = True,
    unet_name: str = "flux-2-klein-base-9b-fp8.safetensors",
) -> dict:
    prompt: dict = {
        "70": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": unet_name or "flux-2-klein-base-9b-fp8.safetensors",
                "weight_dtype": "default",
            },
        },
        "71": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen_3_8b_fp8mixed.safetensors",
                "type": "flux2",
                "device": "default",
            },
        },
        "72": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "flux2-vae.safetensors"},
        },
        "66": {
            "class_type": "EmptyFlux2LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "62": {
            "class_type": "Flux2Scheduler",
            "inputs": {"steps": steps, "width": width, "height": height},
        },
        "61": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "euler"},
        },
        "73": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": seed},
        },
        "67": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "", "clip": ["71", 0]},
        },
        "74": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": text, "clip": ["71", 0]},
        },
        "63": {
            "class_type": "CFGGuider",
            "inputs": {
                "model": ["70", 0],
                "positive": ["74", 0],
                "negative": ["67", 0],
                "cfg": 1,
            },
        },
        "64": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["73", 0],
                "guider": ["63", 0],
                "sampler": ["61", 0],
                "sigmas": ["62", 0],
                "latent_image": ["66", 0],
            },
        },
        "65": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["64", 0], "vae": ["72", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "klein", "images": ["65", 0]},
        },
    }
    if use_loras:
        prompt["80"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["70", 0],
                "clip": ["71", 0],
                "lora_name": "https://civitai.com/api/download/models/2625692",
                "strength_model": 1,
                "strength_clip": 1,
            },
        }
        prompt["81"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["80", 0],
                "clip": ["80", 1],
                "lora_name": "https://civitai.com/api/download/models/2763568",
                "strength_model": 0.8,
                "strength_clip": 0.8,
            },
        }
        prompt["63"]["inputs"]["model"] = ["81", 0]
        prompt["63"]["inputs"]["positive"] = ["74", 0]
        prompt["63"]["inputs"]["negative"] = ["67", 0]
    return {
        "prompt": prompt,
        "convert_output": {
            "format": "jpeg",
            "options": {"quality": 90, "progressive": True},
        },
    }


def _gateway() -> str:
    p = salad_gen.CONFIG / "gateway-klein"
    return salad_gen._read(p).rstrip("/")


def one(
    base: str,
    key: str,
    text: str,
    out: Path,
    *,
    width: int,
    height: int,
    use_loras: bool,
) -> str:
    seed = salad_gen.random.randint(1, 2**48)
    payload = salad_gen.json.dumps(
        klein_payload(text, seed=seed, width=width, height=height, use_loras=use_loras)
    ).encode()
    for _ in range(6):
        code, body = salad_gen._req(base + "/prompt", key, data=payload, timeout=180)
        if code == 200:
            break
        if code in (502, 503, 504, 524):
            salad_gen.time.sleep(8)
            continue
        return f"fail {out.name} HTTP {code} {body[:180]!r}"
    else:
        return f"fail {out.name} retries"
    data = salad_gen.json.loads(body.decode("utf-8", "replace"))
    raw = (data.get("images") or [None])[0]
    if not raw:
        return f"fail {out.name} empty keys={list(data)[:8]}"
    if isinstance(raw, str) and raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    out.write_bytes(salad_gen.base64.b64decode(raw))
    return f"ok {out.name} {out.stat().st_size}"


def jobs() -> list[tuple[str, str, int, int, bool]]:
    """(prompt, filename, width, height, use_loras). Bodies skip Impressionism LoRA."""
    out: list[tuple[str, str, int, int, bool]] = []
    for sex in ("female", "male"):
        for stage in _face_stages():
            extra = f"{INFANT}. " if stage == "infants" else ""
            prompt = _no_magenta(
                f"{STYLE}. {extra}"
                + face_prompt.compose_face_prompt(
                    sex=sex,
                    age_stage=stage,
                    skin_tone="fair",
                    hair_color="blonde",
                    eye_color="blue",
                )
            )
            name = f"salad_probe_klein_face_{sex}_{stage}.jpg"
            out.append((prompt, name, 1024, 1024, True))
    preg_ok = {
        "young_adult",
        "adults",
        "middle_age",
        "twenties",
        "thirties",
        "forties",
        "fifties",
    }
    for sex in ("female", "male"):
        for stage in _face_stages():
            for ang in BODY_ANGLES:
                prompt = _klein_body_prompt(
                    sex=sex, stage=stage, ang=ang, pregnancy="none"
                )
                name = f"salad_probe_klein_body_{sex}_{stage}_{ang}.jpg"
                out.append((prompt, name, 832, 1408, False))
    for stage in _face_stages():
        if stage not in preg_ok:
            continue
        for preg in ("early", "mid", "late"):
            for ang in BODY_ANGLES:
                prompt = _klein_body_prompt(
                    sex="female", stage=stage, ang=ang, pregnancy=preg
                )
                name = (
                    f"salad_probe_klein_body_female_{stage}_pregnant_{preg}_{ang}.jpg"
                )
                out.append((prompt, name, 832, 1408, False))
    for key, scene in EVENTS:
        prompt = f"{STYLE}. {scene}"
        name = f"salad_probe_klein_event_{key}.jpg"
        out.append((prompt, name, 1216, 832, True))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-lora", action="store_true", help="skip LoRAs on faces/events too")
    ap.add_argument(
        "--bodies-lora",
        action="store_true",
        help="Impressionism LoRA on bodies (default off — melts full figures)",
    )
    ap.add_argument("--only", default="", help="substring filter on output filename")
    ap.add_argument("--force", action="store_true", help="overwrite existing plates")
    args = ap.parse_args()
    key = salad_gen._read(salad_gen.CONFIG / "key")
    base = _gateway()
    salad_gen.wait_ready(base, key, 120)
    ART.mkdir(parents=True, exist_ok=True)
    todo = jobs()
    if args.only:
        todo = [j for j in todo if args.only in j[1]]
    print(f"[klein-probe] {len(todo)} plates gateway={base}", flush=True)
    fails = 0
    for text, name, w, h, job_lora in todo:
        out = ART / name
        if not args.force and out.is_file() and out.stat().st_size > 8000:
            print(f"skip {name}", flush=True)
            continue
        use_loras = False if args.no_lora else (True if args.bodies_lora else job_lora)
        line = one(base, key, text, out, width=w, height=h, use_loras=use_loras)
        print(line, flush=True)
        if line.startswith("fail"):
            fails += 1
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
