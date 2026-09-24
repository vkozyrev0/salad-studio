"""Persisted Prompt Editor request JSON so you can reuse earlier jobs.

Stored under ``~/.config/salad/studio-prompt-history.json`` (not git).
Table UI shows prompt text + a stats column; reuse restores the full request.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

HISTORY_PATH = Path.home() / ".config" / "salad" / "studio-prompt-history.json"
THUMBS_DIR = Path.home() / ".config" / "salad" / "studio-prompt-thumbs"
MAX_ENTRIES = 100
THUMB_SIZE = (48, 48)


def _load() -> list[dict[str, Any]]:
    if not HISTORY_PATH.is_file():
        return []
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        req = row.get("request")
        if not isinstance(req, dict):
            req = None
        if not text and req is not None:
            text = prompt_text_of(req)
        if not text and req is None:
            continue
        entry: dict[str, Any] = {"text": text, "ts": int(row.get("ts") or 0)}
        if req is not None:
            entry["request"] = req
        if row.get("profile"):
            entry["profile"] = str(row.get("profile"))
        if row.get("gateway"):
            entry["gateway"] = str(row.get("gateway"))
        if row.get("image"):
            entry["image"] = str(row.get("image"))
        out.append(entry)
    return out


def _save(rows: list[dict[str, Any]]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def list_prompts() -> list[dict[str, Any]]:
    return _load()


def _canon(req: dict[str, Any] | None) -> str:
    if not isinstance(req, dict):
        return ""
    return json.dumps(req, sort_keys=True, separators=(",", ":"))


def prompt_text_of(body: dict[str, Any] | None) -> str:
    prompt = body.get("prompt") if isinstance(body, dict) else None
    if not isinstance(prompt, dict):
        return ""
    best = ""
    for node in prompt.values():
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
            continue
        text = str((node.get("inputs") or {}).get("text") or "")
        if len(text.strip()) > len(best.strip()):
            best = text
    return best


def _redact_request(body: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(body)
    prompt = out.get("prompt")
    if not isinstance(prompt, dict):
        return out
    try:
        from lora_store import strip_civitai_token
    except ImportError:
        strip_civitai_token = None  # type: ignore[assignment]
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        name = inputs.get("lora_name")
        if isinstance(name, str) and strip_civitai_token is not None:
            inputs["lora_name"] = strip_civitai_token(name)
    return out


def redact_request(body: dict[str, Any]) -> dict[str, Any]:
    """Copy of a request body with Civitai tokens stripped from LoRA URLs.

    Public so every store that persists a request (history, prompt catalog)
    strips tokens the same way.
    """
    return _redact_request(body)


def _lora_label(name: str, strength: Any) -> str:
    raw = (name or "").strip()
    if "civitai.com" in raw.lower() and "/download/models/" in raw.lower():
        vid = raw.split("/download/models/", 1)[-1].split("?", 1)[0].strip("/")
        label = f"civitai:{vid}" if vid else "civitai"
    else:
        path = urlparse(raw).path if "://" in raw else raw.replace("\\", "/")
        label = path.rsplit("/", 1)[-1] or raw
        if label.lower().endswith(".safetensors"):
            label = label[: -len(".safetensors")]
    try:
        st = float(strength)
    except (TypeError, ValueError):
        st = 1.0
    if st != 1.0:
        return f"{label}@{st:g}"
    return label


def request_stats(body: dict[str, Any] | None) -> str:
    """Compact graph fingerprint for the history table."""
    if not isinstance(body, dict):
        return ""
    prompt = body.get("prompt")
    if not isinstance(prompt, dict):
        return ""
    n = len(prompt)
    loras: list[str] = []
    width = height = steps = cfg = None
    sampler = sched = None
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "")
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        if cls == "LoraLoader":
            loras.append(
                _lora_label(
                    str(inputs.get("lora_name") or ""),
                    inputs.get("strength_model"),
                )
            )
        elif cls in (
            "EmptyFlux2LatentImage",
            "EmptyLatentImage",
            "EmptySD3LatentImage",
        ):
            width = inputs.get("width", width)
            height = inputs.get("height", height)
        elif cls == "Flux2Scheduler":
            steps = inputs.get("steps", steps)
            width = inputs.get("width", width)
            height = inputs.get("height", height)
            sched = "flux2"
        elif cls == "BasicScheduler":
            steps = inputs.get("steps", steps)
            sched = str(inputs.get("scheduler") or "simple")
        elif cls == "KSampler":
            steps = inputs.get("steps", steps)
            sampler = inputs.get("sampler_name") or sampler
        elif cls == "CFGGuider":
            cfg = inputs.get("cfg")
        elif cls == "KSamplerSelect":
            sampler = inputs.get("sampler_name") or sampler
    bits = [f"{n} nodes"]
    if loras:
        shown = ", ".join(loras[:3])
        extra = f"+{len(loras) - 3}" if len(loras) > 3 else ""
        noun = "LoRA" if len(loras) == 1 else "LoRAs"
        bits.append(f"{len(loras)} {noun} ({shown}{extra})")
    else:
        bits.append("no LoRA")
    if width not in (None, "") and height not in (None, ""):
        bits.append(f"{width}×{height}")
    if steps not in (None, ""):
        bits.append(f"{steps} steps")
    if cfg not in (None, ""):
        bits.append(f"cfg {cfg}")
    if sampler:
        bits.append(str(sampler))
    if sched:
        bits.append(str(sched))
    return " · ".join(bits)


def add_prompt(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    rows = _load()
    if rows and rows[0].get("text") == raw and "request" not in rows[0]:
        return rows[0]
    entry = {"text": raw, "ts": int(time.time())}
    rows.insert(0, entry)
    _save(rows[:MAX_ENTRIES])
    return entry


def add_request(
    body: dict[str, Any],
    *,
    profile: str = "",
    gateway: str = "",
) -> dict[str, Any] | None:
    """Newest-first. Consecutive identical request JSON is not duplicated."""
    if not isinstance(body, dict) or "prompt" not in body:
        return None
    req = _redact_request(body)
    text = prompt_text_of(req).strip()
    if not text:
        return None
    rows = _load()
    if rows and _canon(rows[0].get("request") if isinstance(rows[0].get("request"), dict) else None) == _canon(req):
        return rows[0]
    entry: dict[str, Any] = {"text": text, "request": req, "ts": int(time.time())}
    if profile:
        entry["profile"] = profile
    if gateway:
        entry["gateway"] = gateway
    rows.insert(0, entry)
    _save(rows[:MAX_ENTRIES])
    return entry


def remove_at(index: int) -> None:
    rows = _load()
    if 0 <= index < len(rows):
        _unlink_thumb(rows[index].get("image"))
        rows.pop(index)
        _save(rows)


def clear_thumbs() -> int:
    """Delete Prompt History thumbnail JPEGs and drop ``image`` fields. Keep rows."""
    n = 0
    if THUMBS_DIR.is_dir():
        for path in THUMBS_DIR.glob("*.jpg"):
            try:
                path.unlink()
                n += 1
            except OSError:
                continue
    rows = _load()
    changed = False
    for row in rows:
        if row.get("image"):
            row["image"] = ""
            changed = True
    if changed:
        _save(rows)
    return n


def _unlink_thumb(path: Any) -> None:
    raw = str(path or "").strip()
    if not raw:
        return
    p = Path(raw)
    try:
        if p.is_file() and THUMBS_DIR.resolve() in p.resolve().parents:
            p.unlink()
    except OSError:
        return


def write_thumb(src: Path, *, ts: int) -> Path | None:
    """Save a 48×48 JPEG under THUMBS_DIR. None if the source cannot be read."""
    path = Path(src)
    if not path.is_file():
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        im = Image.open(path)
        im = im.convert("RGB")
        im.thumbnail(THUMB_SIZE)
        canvas = Image.new("RGB", THUMB_SIZE, (20, 30, 40))
        x = (THUMB_SIZE[0] - im.size[0]) // 2
        y = (THUMB_SIZE[1] - im.size[1]) // 2
        canvas.paste(im, (x, y))
        THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        dest = THUMBS_DIR / f"{int(ts)}.jpg"
        canvas.save(dest, "JPEG", quality=80)
        return dest
    except OSError:
        return None


def attach_image(src: Path, *, ts: int | None = None) -> Path | None:
    """Attach a generated plate to the newest matching history row."""
    rows = _load()
    if not rows:
        return None
    idx = 0
    if ts:
        for i, row in enumerate(rows):
            if int(row.get("ts") or 0) == int(ts):
                idx = i
                break
    stamp = int(rows[idx].get("ts") or time.time())
    thumb = write_thumb(Path(src), ts=stamp)
    if thumb is None:
        return None
    old = rows[idx].get("image")
    if str(old) != str(thumb):
        _unlink_thumb(old)
    rows[idx]["image"] = str(thumb)
    _save(rows)
    return thumb


def preview(text: str, n: int = 90) -> str:
    one = " ".join((text or "").split())
    if len(one) <= n:
        return one
    return one[: n - 1] + "…"

