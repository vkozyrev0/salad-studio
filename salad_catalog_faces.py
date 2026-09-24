#!/usr/bin/env python3
"""Resumable SaladCloud Flux face-catalog rebuild.

Mass --generate is FROZEN while art/catalog/face/salad_PAUSE.txt exists
(docs/workflow/14-salad-comfy-live-findings.md). Do not resume until
faces, bodies, events, and sex each have an explicit chosen model.

  python salad_catalog_faces.py --status
  python salad_catalog_faces.py --generate
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
# Eldermark art output tree (outside this tool); ELDERMARK_ART overrides it.
ART = Path(os.environ.get("ELDERMARK_ART", r"C:\Users\vkozy\repos\lifesim-design\art"))

import salad_gen  # noqa: E402
from paperdoll_mask import install_knockout_plate  # noqa: E402
from regen_faces import (  # noqa: E402
    cell_key,
    load_index,
    load_policy,
    catalog_dir,
    stage_rank,
)

def ISO():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
PROGRESS = ART / "catalog" / "face" / "salad_progress.json"
LOG = ART / "catalog" / "face" / "salad_regen.log"
PIDFILE = ART / "catalog" / "face" / "salad_runner.pid"
PAUSE = ART / "catalog" / "face" / "salad_PAUSE.txt"
_LOCK = threading.Lock()

CHILD = {"infants", "infant", "children", "child", "minors", "teen"}
NEGATIVE = (
    "anime, manga, moe, pixar, cartoon, doll, oversized eyes, huge irises, "
    "saucer eyes, chibi, wall-eye, crossed eyes, frown, scowl"
)
HOUSE = (
    "DSLR 85mm photograph of a real living human, photoreal skin pores, "
    "not 3d render, not cgi, not pixar, not disney, not anime, not cartoon, "
    "not doll, not clay. Frontal head-and-shoulders, looking straight at the "
    "camera, both eyes aligned on the lens. Normal human eye size, not "
    "enlarged. Soft even studio light. Solid MAGENTA chroma-key background "
    "#FF00FF. Cream ruffled linen collar."
)
AGE = {
    "infants": (
        "TRUE INFANT 0 to 3 months, newborn baby, not a toddler, not a child. "
        "Large infant cranium, tiny nose, round apple cheeks, sparse baby hair. "
        "Slight happy open-mouth smile, no teeth."
    ),
    "children": (
        "school portrait photograph of a real eight-year-old child, DSLR 85mm, "
        "photoreal. Pre-pubescent, not a teen, not a baby. Round child cheeks, "
        "small nose. Slight closed-mouth smile."
    ),
    "minors": (
        "TRUE TEENAGER 15 to 16 years old, mid-teens, not a child under 12, "
        "not a 30-year-old. Slight closed-mouth smile."
    ),
    "young_adult": (
        "TRUE young adult 25 years old, fully grown, not a teen, not middle-aged. "
        "Slight closed-mouth smile."
    ),
    "twenties": (
        "TRUE mid-twenties 25 years old, fully grown, not a teen. "
        "Slight closed-mouth smile."
    ),
    "adults": (
        "TRUE thirties adult about 35 years old, NOT early twenties. "
        "Light expression lines. Slight closed-mouth smile."
    ),
    "thirties": (
        "TRUE thirties adult about 35 years old, mid-thirties, NOT early twenties. "
        "Light expression lines. Slight closed-mouth smile."
    ),
    "forties": (
        "TRUE mid-forties about 45, visible early aging, crow's feet starting. "
        "Slight closed-mouth smile."
    ),
    "fifties": (
        "TRUE mid-fifties about 55, greying at temples, defined nasolabial folds. "
        "Slight closed-mouth smile."
    ),
    "sixties": (
        "TRUE mid-sixties about 65, advanced aging, substantial grey hair. "
        "Slight closed-mouth smile."
    ),
    "elderly": (
        "TRUE elderly mid-to-late seventies, MUST look old, deep wrinkles, "
        "silver-white hair dominating, wrinkled neck. Slight closed-mouth smile."
    ),
    "seventies": (
        "TRUE seventies about 76, deep aging, silver-white hair, age spots. "
        "Slight closed-mouth smile."
    ),
    "eighties": (
        "TRUE eighties about 85, very old, papery skin, white hair, frailty. "
        "Slight closed-mouth smile."
    ),
}
HAIR = {
    "blonde": "natural blonde hair",
    "red": "natural copper-red hair",
    "auburn": "natural auburn hair",
    "brown": "natural brown hair",
    "black": "natural black hair",
}
EYE = {
    "blue": "blue human eyes",
    "green": "green human eyes",
    "hazel": "hazel human eyes",
    "brown": "brown human eyes",
}
SKIN = {
    "fair": "fair skin",
    "olive": "olive-tan Mediterranean skin, not green",
    "brown": "brown skin",
    "dark": "dark brown skin",
}


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{ISO()} {msg}"
    print(line, flush=True)
    with _LOCK:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_progress() -> dict:
    if PROGRESS.is_file():
        return json.loads(PROGRESS.read_text(encoding="utf-8"))
    return {
        "version": 1,
        "created_at": ISO(),
        "updated_at": ISO(),
        "backend": "salad-flux-dev",
        "totals": {"done": 0, "failed": 0},
        "cells": {},
    }


def save_progress(prog: dict) -> None:
    prog["updated_at"] = ISO()
    cells = prog.get("cells") or {}
    prog["totals"] = {
        "done": sum(1 for r in cells.values() if r.get("status") == "done"),
        "failed": sum(1 for r in cells.values() if r.get("status") == "failed"),
    }
    PROGRESS.write_text(json.dumps(prog, indent=2) + "\n", encoding="utf-8")


def noun(sex: str, stage: str) -> str:
    child = stage in CHILD
    if sex == "male":
        return "boy" if child else "man"
    return "girl" if child else "woman"


def negatives(sex: str) -> str:
    if sex == "male":
        return NEGATIVE + ", woman, female, girl, makeup, lipstick"
    return NEGATIVE


def compose(params: dict) -> str:
    stage = params.get("ageStage") or "adults"
    sex = params.get("sex") or "female"
    age = AGE.get(stage, AGE["adults"])
    hair = HAIR.get(params.get("hairColor") or "", "natural hair")
    if stage in {"elderly", "seventies", "eighties"}:
        hair = hair + ", desaturated toward grey/white"
    if sex == "male":
        hair = hair + (
            ", short boy haircut" if stage in CHILD else ", short masculine haircut"
        )
    eyes = EYE.get(params.get("eyeColor") or "", "human eyes")
    skin = SKIN.get(params.get("skinTone") or "", "natural skin")
    who = f"a {noun(sex, stage)}"
    # Sex immediately after HOUSE. AGE must stay sex-neutral: "woman/man"
    # in thirties made Flux emit women for male cells (CLIP sees woman first).
    return f"{HOUSE} Portrait of {who}. {age} {hair}. {eyes}. {skin}."


def wait_ready(key: str, base: str, ping_s: int) -> None:
    n = 0
    while True:
        n += 1
        code, _ = salad_gen._req(base + "/ready", key, timeout=20)
        if code == 200:
            log(f"[ready] try {n} status=200")
            return
        log(f"[ready] try {n} status={code} — sleep {ping_s}s")
        time.sleep(ping_s)


def queue(entries: list[dict], policy: dict, prog: dict) -> list[dict]:
    q = []
    for e in entries:
        fname = cell_key(e)
        if (prog.get("cells") or {}).get(fname, {}).get("status") == "done":
            continue
        q.append(e)
    q.sort(
        key=lambda e: (
            stage_rank(policy, (e.get("params") or {}).get("ageStage") or ""),
            cell_key(e),
        )
    )
    return q


def gen_one(entry: dict, cat: Path, key: str, base: str) -> str:
    """Return done | retry | failed. 502/503 = retry (dead replica), not a long wait."""
    params = entry.get("params") or {}
    prompt = compose(params)
    seed = salad_gen.random.randint(1, 2**48)
    payload = salad_gen.json.dumps(
        salad_gen.flux_payload(
            prompt, seed, 1024, 1024, 24, negatives(params.get("sex") or "female")
        )
    ).encode()
    try:
        code, body = salad_gen._req(base + "/prompt", key, data=payload, timeout=180)
    except Exception as e:
        log(f"[http] {cell_key(entry)} {type(e).__name__}: {e}")
        return "retry"
    if code in (401, 403):
        raise SystemExit(f"auth HTTP {code}")
    if code in (502, 503, 504, 429) or code >= 500:
        log(f"[retry] {cell_key(entry)} HTTP {code}")
        time.sleep(2)
        return "retry"
    if code != 200:
        log(f"[http] {cell_key(entry)} HTTP {code} {body[:200]!r}")
        return "failed"
    try:
        data = salad_gen.json.loads(body.decode("utf-8", "replace"))
        raw = (data.get("images") or [None])[0]
        if not raw:
            return "retry"
        if isinstance(raw, str) and raw.startswith("data:"):
            raw = raw.split(",", 1)[-1]
        dest = cat / cell_key(entry)
        tmp = dest.with_name(dest.stem + "._salad_tmp.jpg")
        tmp.write_bytes(salad_gen.base64.b64decode(raw))
        try:
            install_knockout_plate(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
    except Exception:
        log(f"[err] {cell_key(entry)}\n{traceback.format_exc()}")
        return "failed"
    return "done"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument(
        "--ignore-pause",
        action="store_true",
        help="run --generate even if salad_PAUSE.txt exists (user must say so)",
    )
    ap.add_argument("--ping-s", type=int, default=180, help="seconds between /ready polls")
    ap.add_argument(
        "--queue-depth",
        type=int,
        default=7,
        help="max in-flight /prompt calls (retries rejoin this window)",
    )
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    policy = load_policy()
    cat = catalog_dir(policy)
    entries = load_index(cat)
    prog = load_progress()
    q = queue(entries, policy, prog)
    log(
        f"[status] catalog={len(entries)} remaining={len(q)} "
        f"done={prog['totals'].get('done', 0)} failed={prog['totals'].get('failed', 0)}"
    )
    if args.status or not args.generate:
        return 0
    if PAUSE.is_file() and not args.ignore_pause:
        log(f"[paused] {PAUSE} — not generating until the user says to resume")
        return 2

    key = salad_gen._read(salad_gen.CONFIG / "key")
    base = salad_gen._read(salad_gen.CONFIG / "gateway").rstrip("/")
    PIDFILE.write_text(str(os.getpid()), encoding="utf-8")
    wait_ready(key, base, args.ping_s)
    if args.limit:
        q = q[: args.limit]
    depth = max(1, args.queue_depth)
    log(f"[run] queue-depth={depth} remaining={len(q)}")
    pending = list(q)
    retries: dict[str, int] = {}
    n_done = 0
    n_fail = 0

    def record(e: dict, st: str) -> None:
        fname = cell_key(e)
        rec = {
            "status": st,
            "backend": "salad",
            "model": "flux1-dev-fp8",
            "at": ISO(),
            "ageStage": (e.get("params") or {}).get("ageStage"),
        }
        with _LOCK:
            prog.setdefault("cells", {})[fname] = rec
            save_progress(prog)

    def work(e: dict) -> tuple[dict, str]:
        return e, gen_one(e, cat, key, base)

    with ThreadPoolExecutor(max_workers=depth) as pool:
        in_flight = set()

        def fill() -> None:
            while pending and len(in_flight) < depth:
                e = pending.pop(0)
                in_flight.add(pool.submit(work, e))

        fill()
        while in_flight:
            done, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
            for fut in done:
                e, st = fut.result()
                fname = cell_key(e)
                if st == "retry":
                    n = retries.get(fname, 0) + 1
                    retries[fname] = n
                    if n >= 24:
                        record(e, "failed")
                        n_fail += 1
                        log(f"[fail] {fname} retries exhausted")
                    else:
                        pending.append(e)
                    continue
                record(e, st)
                if st == "done":
                    n_done += 1
                    if n_done % 10 == 0:
                        log(f"[cell] {n_done} done {fname}")
                else:
                    n_fail += 1
                    log(f"[cell] fail {fname}")
            fill()
    remaining = len(queue(load_index(cat), policy, load_progress()))
    log(f"[done] processed_ok={n_done} failed={n_fail} remaining={remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
