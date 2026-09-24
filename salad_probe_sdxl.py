#!/usr/bin/env python3
"""Probe the Salad ComfyUI API *SDXL* group (not Flux).

Gateway: ~/.config/salad/gateway-sdxl
Uses Salad's base+refiner graph (no webhook) for a smoke, then Lustify V7
for face/body house probes. Mass catalog stays paused.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import salad_catalog_faces as cat  # noqa: E402
import salad_gen  # noqa: E402

GW = pathlib.Path.home() / ".config" / "salad" / "gateway-sdxl"
TOKEN = pathlib.Path.home() / ".config" / "civitai" / "token"
# Eldermark art output tree (outside this tool); ELDERMARK_ART overrides it.
ART = pathlib.Path(
    os.environ.get("ELDERMARK_ART", r"C:\Users\vkozy\repos\lifesim-design\art")
)
LUSTIFY = "https://civitai.com/api/download/models/2155386"


def _token() -> str:
    return TOKEN.read_text(encoding="utf-8").strip() if TOKEN.is_file() else ""


def wait_ready(base: str, key: str, timeout_s: int = 2400) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        code, raw = salad_gen._req(base + "/ready", key, timeout=20)
        txt = raw.decode("utf-8", "replace")[:120]
        print(time.strftime("%H:%M:%S"), "ready", code, txt, flush=True)
        if code == 200:
            return
        time.sleep(20)
    raise SystemExit("SDXL group still allocating")


def salad_sdxl_base_refiner(pos: str, neg: str, seed: int, w: int, h: int) -> dict:
    """Official Salad SDXL recipe graph (baked base + refiner). No webhook."""
    return {
        "4": {
            "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
            "class_type": "CheckpointLoaderSimple",
        },
        "5": {
            "inputs": {"width": w, "height": h, "batch_size": 1},
            "class_type": "EmptyLatentImage",
        },
        "6": {
            "inputs": {"text": pos, "clip": ["4", 1]},
            "class_type": "CLIPTextEncode",
        },
        "7": {
            "inputs": {"text": neg, "clip": ["4", 1]},
            "class_type": "CLIPTextEncode",
        },
        "10": {
            "inputs": {
                "add_noise": "enable",
                "noise_seed": seed,
                "steps": 25,
                "cfg": 8,
                "sampler_name": "euler",
                "scheduler": "normal",
                "start_at_step": 0,
                "end_at_step": 20,
                "return_with_leftover_noise": "enable",
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
            "class_type": "KSamplerAdvanced",
        },
        "12": {
            "inputs": {"ckpt_name": "sd_xl_refiner_1.0.safetensors"},
            "class_type": "CheckpointLoaderSimple",
        },
        "15": {
            "inputs": {"text": pos, "clip": ["12", 1]},
            "class_type": "CLIPTextEncode",
        },
        "16": {
            "inputs": {"text": neg, "clip": ["12", 1]},
            "class_type": "CLIPTextEncode",
        },
        "11": {
            "inputs": {
                "add_noise": "disable",
                "noise_seed": 0,
                "steps": 25,
                "cfg": 8,
                "sampler_name": "euler",
                "scheduler": "normal",
                "start_at_step": 20,
                "end_at_step": 10000,
                "return_with_leftover_noise": "disable",
                "model": ["12", 0],
                "positive": ["15", 0],
                "negative": ["16", 0],
                "latent_image": ["10", 0],
            },
            "class_type": "KSamplerAdvanced",
        },
        "17": {
            "inputs": {"samples": ["11", 0], "vae": ["12", 2]},
            "class_type": "VAEDecode",
        },
        "19": {
            "inputs": {"filename_prefix": "sdxl", "images": ["17", 0]},
            "class_type": "SaveImage",
        },
    }


def lustify_graph(pos: str, neg: str, seed: int, w: int, h: int, ckpt: str) -> dict:
    """Lustify is a full SDXL ckpt, no Stability refiner."""
    return {
        "4": {"inputs": {"ckpt_name": ckpt}, "class_type": "CheckpointLoaderSimple"},
        "6": {"inputs": {"text": pos, "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
        "7": {"inputs": {"text": neg, "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
        "5": {
            "inputs": {"width": w, "height": h, "batch_size": 1},
            "class_type": "EmptyLatentImage",
        },
        "3": {
            "inputs": {
                "seed": seed,
                "steps": 28,
                "cfg": 5,
                "sampler_name": "dpmpp_2m_sde",
                "scheduler": "karras",
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
            "class_type": "KSampler",
        },
        "8": {"inputs": {"samples": ["3", 0], "vae": ["4", 2]}, "class_type": "VAEDecode"},
        "9": {
            "inputs": {"filename_prefix": "lustify", "images": ["8", 0]},
            "class_type": "SaveImage",
        },
    }


def post(base: str, key: str, prompt: dict, token: str, name: str) -> int:
    body: dict = {
        "prompt": prompt,
        "convert_output": {"format": "jpeg", "options": {"quality": 90, "progressive": True}},
    }
    if token:
        body["credentials"] = {
            "https://civitai.com": {
                "header": {"key": "Authorization", "value": f"Bearer {token}"}
            }
        }
    raw_body = json.dumps(body).encode()
    out = ART / name
    for i in range(1, 10):
        print(f"[try {i}] {name}", flush=True)
        t0 = time.time()
        code, raw = salad_gen._req(base + "/prompt", key, data=raw_body, timeout=180)
        dt = round(time.time() - t0, 1)
        txt = raw.decode("utf-8", "replace")
        if token:
            txt = txt.replace(token, "[token]")
        print(f"  HTTP {code} {dt}s {txt[:200]!r}", flush=True)
        if code == 200:
            b = json.loads(raw)["images"][0]
            if isinstance(b, str) and b.startswith("data:"):
                b = b.split(",", 1)[-1]
            out.write_bytes(salad_gen.base64.b64decode(b))
            print("saved", out, out.stat().st_size, flush=True)
            return 0
        time.sleep(20)
    return 3


def main() -> int:
    key = salad_gen._read(salad_gen.CONFIG / "key")
    base = salad_gen._read(GW).rstrip("/")
    token = _token()
    ckpt = LUSTIFY
    if token:
        ckpt = f"{LUSTIFY}?token={token}"
    wait_ready(base, key)
    ident_f = cat.compose(
        {
            "ageStage": "adults",
            "sex": "female",
            "hairColor": "blonde",
            "eyeColor": "blue",
            "skinTone": "fair",
        }
    )
    ident_m = cat.compose(
        {
            "ageStage": "adults",
            "sex": "male",
            "hairColor": "blonde",
            "eyeColor": "blue",
            "skinTone": "fair",
        }
    )
    full = (
        "FULL BODY standing photograph, entire person from crown of head to soles "
        "of both feet, both complete legs and both feet fully inside the frame. "
        "FRONT VIEW facing the camera. "
    )
    jobs = [
        (
            salad_sdxl_base_refiner(ident_f, "text, watermark", 11, 1024, 1024),
            "salad_probe_sdxl_baked_female_adults.jpg",
        ),
        (
            lustify_graph(ident_f, cat.negatives("female"), 21, 1024, 1024, ckpt),
            "salad_probe_sdxl_lustify_female_adults.jpg",
        ),
        (
            lustify_graph(ident_m, cat.negatives("male"), 22, 1024, 1024, ckpt),
            "salad_probe_sdxl_lustify_male_adults.jpg",
        ),
        (
            lustify_graph(
                full + "a woman. " + ident_f + " Cream linen tunic, belt. MAGENTA #FF00FF.",
                cat.negatives("female") + ", cropped legs, cut-off feet, back view",
                23,
                768,
                1408,
                ckpt,
            ),
            "salad_probe_sdxl_lustify_fullbody_female_adults.jpg",
        ),
        (
            lustify_graph(
                full
                + "a MAN, male body, not a woman. "
                + ident_m
                + " Cream linen tunic, belt. MAGENTA #FF00FF.",
                cat.negatives("male") + ", cropped legs, woman, female, dress",
                24,
                768,
                1408,
                ckpt,
            ),
            "salad_probe_sdxl_lustify_fullbody_male_adults.jpg",
        ),
        (
            lustify_graph(
                full
                + "heavily pregnant woman, large third-trimester belly. "
                + ident_f
                + " Cream linen tunic over the bump. MAGENTA #FF00FF.",
                cat.negatives("female") + ", cropped legs, flat stomach",
                25,
                768,
                1408,
                ckpt,
            ),
            "salad_probe_sdxl_lustify_fullbody_female_pregnant_late.jpg",
        ),
    ]
    rc = 0
    for prompt, name in jobs:
        rc = post(base, key, prompt, token, name) or rc
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
