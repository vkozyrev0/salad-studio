#!/usr/bin/env python3
"""One male + one female plate per AGE key, using current compose() HOUSE."""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import salad_catalog_faces as cat  # noqa: E402
import salad_gen  # noqa: E402

# Eldermark art output tree (outside this tool); ELDERMARK_ART overrides it.
ART = Path(os.environ.get("ELDERMARK_ART", r"C:\Users\vkozy\repos\lifesim-design\art"))


def _civitai_token() -> str:
    p = Path.home() / ".config" / "civitai" / "token"
    return p.read_text(encoding="utf-8").strip() if p.is_file() else ""


def _payload_bytes(
    prompt: str,
    sex: str,
    ckpt: str,
    token: str,
    lora: str,
    lora_strength: float,
) -> bytes:
    seed = salad_gen.random.randint(1, 2**48)
    body = salad_gen.flux_payload(
        prompt,
        seed,
        1024,
        1024,
        24,
        cat.negatives(sex),
        ckpt_name=ckpt,
        lora_name=lora or None,
        lora_strength=lora_strength,
    )
    if token and ("civitai.com" in ckpt or "civitai.com" in lora):
        body["credentials"] = {
            "https://civitai.com": {
                "header": {"key": "Authorization", "value": f"Bearer {token}"}
            }
        }
    return salad_gen.json.dumps(body).encode()


def one(
    key: str,
    base: str,
    sex: str,
    stage: str,
    prefix: str,
    ckpt: str,
    token: str,
    lora: str = "",
    lora_strength: float = 0.7,
) -> str:
    params = {
        "ageStage": stage,
        "sex": sex,
        "hairColor": "blonde",
        "eyeColor": "blue",
        "skinTone": "fair",
    }
    prompt = cat.compose(params)
    payload = _payload_bytes(prompt, sex, ckpt, token, lora, lora_strength)
    out = ART / f"{prefix}_{sex}_{stage}.jpg"
    for _attempt in range(8):
        code, body = salad_gen._req(base + "/prompt", key, data=payload, timeout=180)
        if code == 200:
            break
        if code in (502, 503, 504, 524):
            salad_gen.time.sleep(8)
            continue
        txt = body.decode("utf-8", "replace")
        if token:
            txt = txt.replace(token, "[token]")
        return f"fail {out.name} HTTP {code} {txt[:160]}"
    else:
        return f"fail {out.name} retries"
    data = salad_gen.json.loads(body.decode("utf-8", "replace"))
    raw = (data.get("images") or [None])[0]
    if not raw:
        return f"fail {out.name} empty"
    if isinstance(raw, str) and raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    out.write_bytes(salad_gen.base64.b64decode(raw))
    return f"ok {out.name} {out.stat().st_size}"


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--sex", choices=("female", "male"))
    ap.add_argument("--stage", choices=tuple(cat.AGE))
    ap.add_argument("--prefix", default="salad_probe")
    ap.add_argument(
        "--ckpt",
        default="flux1-dev-fp8.safetensors",
        help="CheckpointLoaderSimple name or Civitai URL",
    )
    ap.add_argument("--lora", default="", help="LoRA filename or Civitai URL")
    ap.add_argument("--lora-strength", type=float, default=0.7)
    args = ap.parse_args()
    key = salad_gen._read(salad_gen.CONFIG / "key")
    base = salad_gen._read(salad_gen.CONFIG / "gateway").rstrip("/")
    salad_gen.wait_ready(base, key, 120)
    token = _civitai_token()

    def _authed(url: str) -> str:
        if token and url.startswith("https://civitai.com/") and "token=" not in url:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}token={token}"
        return url

    ckpt = _authed(args.ckpt)
    lora = _authed(args.lora)
    sexes = (args.sex,) if args.sex else ("female", "male")
    stages = (args.stage,) if args.stage else tuple(cat.AGE)
    jobs = [(s, t) for s in sexes for t in stages]
    need_warm = ckpt.startswith("http") or lora.startswith("http")
    if need_warm:
        print("[warm] first replica download", flush=True)
        warm = one(
            key, base, jobs[0][0], jobs[0][1], args.prefix, ckpt, token, lora, args.lora_strength
        )
        print("[warm]", warm, flush=True)
        jobs = jobs[1:]
    with ThreadPoolExecutor(max_workers=7) as pool:
        futs = [
            pool.submit(
                one, key, base, s, t, args.prefix, ckpt, token, lora, args.lora_strength
            )
            for s, t in jobs
        ]
        for fut in as_completed(futs):
            print(fut.result(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
