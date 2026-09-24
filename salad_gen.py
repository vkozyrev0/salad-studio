#!/usr/bin/env python3
"""One-shot SaladCloud ComfyUI Flux generate.

Reads secrets from ~/.config/salad/key and ~/.config/salad/gateway (not git).
Polls /ready, POSTs a Flux.1-dev Comfy graph, writes JPEG under art/.

Usage:
    python salad_gen.py
    python salad_gen.py --prompt "watercolor portrait of an adult woman, front face"
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import random
import sys
import time
import urllib.error
import urllib.request

# Eldermark art output tree (outside this tool); ELDERMARK_ART overrides it.
ART = pathlib.Path(
    os.environ.get("ELDERMARK_ART", r"C:\Users\vkozy\repos\lifesim-design\art")
)
CONFIG = pathlib.Path.home() / ".config" / "salad"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
DEFAULT_PROMPT = (
    "leafy green spaceship descending from orbit into a lush bio-organic "
    "cityscape. the sky is pale purple, and red storm clouds form in the "
    "distance, crackling with lightning."
)


def _read(path: pathlib.Path) -> str:
    if not path.is_file():
        raise SystemExit(f"missing {path}")
    return path.read_text(encoding="utf-8").strip()


def _req(url: str, key: str, data: bytes | None = None, timeout: int = 30):
    headers = {
        "Salad-Api-Key": key,
        "accept": "application/json",
        "User-Agent": UA,
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def flux_payload(
    text: str,
    seed: int,
    width: int,
    height: int,
    steps: int,
    negative: str = "",
    ckpt_name: str = "flux1-dev-fp8.safetensors",
    lora_name: str | None = None,
    lora_strength: float = 0.7,
) -> dict:
    # Graph matches Salad's Flux.1-dev recipe. No webhook — that would hang on example.com.
    prompt = {
            "6": {
                "inputs": {"text": text, "clip": ["30", 1]},
                "class_type": "CLIPTextEncode",
                "_meta": {"title": "CLIP Text Encode (Positive Prompt)"},
            },
            "8": {
                "inputs": {"samples": ["31", 0], "vae": ["30", 2]},
                "class_type": "VAEDecode",
                "_meta": {"title": "VAE Decode"},
            },
            "9": {
                "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]},
                "class_type": "SaveImage",
                "_meta": {"title": "Save Image"},
            },
            "27": {
                "inputs": {"width": width, "height": height, "batch_size": 1},
                "class_type": "EmptySD3LatentImage",
                "_meta": {"title": "EmptySD3LatentImage"},
            },
            "30": {
                "inputs": {"ckpt_name": ckpt_name},
                "class_type": "CheckpointLoaderSimple",
                "_meta": {"title": "Load Checkpoint"},
            },
            "31": {
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": 1,
                    "sampler_name": "euler",
                    "scheduler": "simple",
                    "denoise": 1,
                    "model": ["30", 0],
                    "positive": ["35", 0],
                    "negative": ["33", 0],
                    "latent_image": ["27", 0],
                },
                "class_type": "KSampler",
                "_meta": {"title": "KSampler"},
            },
            "33": {
                "inputs": {"text": negative, "clip": ["30", 1]},
                "class_type": "CLIPTextEncode",
                "_meta": {"title": "CLIP Text Encode (Negative Prompt)"},
            },
            "35": {
                "inputs": {"guidance": 3.5, "conditioning": ["6", 0]},
                "class_type": "FluxGuidance",
                "_meta": {"title": "FluxGuidance"},
            },
        }
    if lora_name:
        prompt["40"] = {
            "inputs": {
                "lora_name": lora_name,
                "strength_model": lora_strength,
                "strength_clip": lora_strength,
                "model": ["30", 0],
                "clip": ["30", 1],
            },
            "class_type": "LoraLoader",
            "_meta": {"title": "Load LoRA"},
        }
        prompt["6"]["inputs"]["clip"] = ["40", 1]
        prompt["33"]["inputs"]["clip"] = ["40", 1]
        prompt["31"]["inputs"]["model"] = ["40", 0]
    return {
        "prompt": prompt,
        "convert_output": {"format": "jpeg", "options": {"quality": 90, "progressive": True}},
    }


def wait_ready(base: str, key: str, timeout_s: int) -> None:
    deadline = time.time() + timeout_s
    n = 0
    while time.time() < deadline:
        n += 1
        code, body = _req(base + "/ready", key, timeout=20)
        print(f"[ready] try {n} status={code}", flush=True)
        if code == 200:
            return
        time.sleep(15)
    raise SystemExit(f"gateway not ready after {timeout_s}s (last HTTP {code})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument(
        "--negative",
        default="",
        help="Comfy node 33; Flux.1-dev often ignores this",
    )
    ap.add_argument("--out", default=str(ART / "salad_smoke.jpg"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=1024)
    ap.add_argument("--wait-ready", type=int, default=900, help="seconds to poll /ready")
    ap.add_argument("--timeout", type=int, default=180, help="POST /prompt timeout")
    args = ap.parse_args()

    key = _read(CONFIG / "key")
    base = _read(CONFIG / "gateway").rstrip("/")
    seed = args.seed or random.randint(1, 2**48)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    wait_ready(base, key, args.wait_ready)
    payload = json.dumps(
        flux_payload(
            args.prompt, seed, args.width, args.height, args.steps, args.negative
        )
    ).encode()
    print(f"[prompt] seed={seed} steps={args.steps} {args.width}x{args.height}", flush=True)
    code, body = _req(base + "/prompt", key, data=payload, timeout=args.timeout)
    if code != 200:
        sys.stderr.write(f"POST /prompt HTTP {code}: {body[:800]!r}\n")
        return 2
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        sys.stderr.write(f"not JSON: {body[:400]!r}\n")
        return 2
    images = data.get("images") or []
    if not images:
        sys.stderr.write(f"no images in response keys={list(data)[:12]}\n")
        return 2
    raw = images[0]
    if isinstance(raw, str) and raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    out.write_bytes(base64.b64decode(raw))
    print(f"[ok] {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
