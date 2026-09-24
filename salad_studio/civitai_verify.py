"""Headless Civitai image URL → Salad Studio import → replica POST, with a journal.

Used by the /civitai-verify skill. Reuses the same list/import/convert/inspect/
Generate functions Salad Studio uses; does not open the Tk GUI.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent
for p in (_HERE, _TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import comfy_import as ci  # noqa: E402
import generator  # noqa: E402
import lora_store as ls  # noqa: E402
import profiles  # noqa: E402
import salad_status  # noqa: E402
import tokens  # noqa: E402
from studio_log import prompt_url  # noqa: E402

MAX_ATTEMPTS = 5
IMPORT_SOURCE_NAMES = ("comfy_import.py", "request_json.py")
SAMPLE_URL = "https://civitai.com/images/123566519"
DEFAULT_FIXTURE_META = (
    "civitai verify fixture prompt, a standing figure in warm evening light\n"
    "Negative prompt: bad, blurry\n"
    "Steps: 4, CFG scale: 1, Sampler: Euler, Seed: 1, "
    "Model: flux-2-klein-9b-fp8, width: 64, height: 64\n"
)

_MISSING_NODE = re.compile(
    r"missing_node_type",
    re.I,
)
_NODE_NOT_FOUND = re.compile(r"Node '([^']+)' not found")
_CLASS_TYPE_FIELD = re.compile(r'"class_type"\s*:\s*"([^"]+)"')
_SKIP_TYPE_TOKENS = {
    "error",
    "type",
    "message",
    "details",
    "extra_info",
    "node_id",
    "class_type",
    "node_title",
    "node_errors",
    "missing_node_type",
}


def default_fixture_pastes() -> dict[str, str]:
    return {
        "image_id": "fixture",
        "metadata": DEFAULT_FIXTURE_META,
        "workflow": "",
        "tool": "",
    }


class Journal:
    """Append-only JSONL journal. ``path`` may be a file or a directory."""

    def __init__(self, path: str | Path) -> None:
        raw = Path(path)
        if raw.suffix.lower() in {".jsonl", ".json", ".log", ".md", ".txt"}:
            self.file = raw
            self.dir = raw.parent
        else:
            self.dir = raw
            self.file = raw / "journal.jsonl"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file.parent.mkdir(parents=True, exist_ok=True)

    def append(self, **event: Any) -> dict[str, Any]:
        event.setdefault("ts", datetime.now().astimezone().isoformat())
        line = json.dumps(event, default=str, ensure_ascii=False)
        with self.file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return event

    def events(self) -> list[dict[str, Any]]:
        if not self.file.is_file():
            return []
        out: list[dict[str, Any]] = []
        for line in self.file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out

    def fingerprints(self) -> list[str]:
        steps = {"import-code-change", "import-code-baseline"}
        return [
            str(e["fingerprint"])
            for e in self.events()
            if e.get("fingerprint") and e.get("step") in steps
        ]

    def has_loop(self) -> bool:
        return any(
            e.get("step") == "loop" or e.get("loop") is True for e in self.events()
        )


def fingerprint_sources(parts: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> str:
    """Stable sha256 of (name, text) pairs. Hashes the inputs, never a canned value."""
    h = hashlib.sha256()
    for name, text in parts:
        h.update(str(name).encode("utf-8"))
        h.update(b"\0")
        h.update(str(text).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def import_source_paths(root: Path | None = None) -> list[Path]:
    base = Path(root) if root is not None else _HERE
    return [base / name for name in IMPORT_SOURCE_NAMES]


def fingerprint_import_sources(
    root: Path | None = None,
    extra: list[tuple[str, str]] | None = None,
) -> str:
    parts: list[tuple[str, str]] = []
    for path in import_source_paths(root):
        if path.is_file():
            parts.append((path.name, path.read_text(encoding="utf-8")))
        else:
            parts.append((path.name, ""))
    if extra:
        parts.extend(extra)
    return fingerprint_sources(parts)


def consider_import_code_change(seen: list[str], fingerprint: str) -> dict[str, Any]:
    """Loop-detect helper: restoring a prior fingerprint is a ping-pong. Refuse it."""
    fp = str(fingerprint)
    prior = [str(x) for x in seen]
    if fp in prior:
        return {
            "loop": True,
            "accepted": False,
            "fingerprint": fp,
            "seen": list(prior),
        }
    return {
        "loop": False,
        "accepted": True,
        "fingerprint": fp,
        "seen": prior + [fp],
    }


def record_import_code_change(
    journal: Journal,
    fingerprint: str,
    description: str,
    *,
    step: str = "import-code-change",
) -> bool:
    """Append an import-code fingerprint. False if this restores an earlier hash."""
    decision = consider_import_code_change(journal.fingerprints(), fingerprint)
    if decision["loop"]:
        journal.append(
            step="loop",
            loop=True,
            fingerprint=fingerprint,
            description=description,
            refuse=True,
            message=(
                "Import-code fingerprint restored an earlier hash "
                "(ping-pong / infinite loop). No further import-code edits."
            ),
        )
        return False
    journal.append(
        step=step,
        fingerprint=fingerprint,
        description=description,
        loop=False,
    )
    return True


def studio_gateway_targets(
    load_all_fn: Callable[[], dict[str, Any]] | None = None,
) -> list[tuple[str, str]]:
    """(profile_id, gateway) for the same klein + klein5090 pair Studio opens."""
    load = load_all_fn or profiles.load_all
    try:
        allp = load()
    except Exception:
        allp = {}
    out: list[tuple[str, str]] = []
    for pid, fallback in (
        ("klein", profiles.KLEIN_GATEWAY),
        ("klein5090", profiles.KLEIN_5090_GATEWAY),
    ):
        gw = fallback
        prof = allp.get(pid) if isinstance(allp, dict) else None
        saved = ""
        if prof is not None:
            saved = str(getattr(prof, "gateway", "") or "").strip()
        if saved:
            gw = saved
        out.append((pid, gw))
    return out


def list_studio_groups(
    key: str | None,
    *,
    snapshot_fn: Callable[[str, str], dict[str, Any]] | None = None,
    targets: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Snapshot both Studio gateways with Ready/block words."""
    snap = snapshot_fn or salad_status.snapshot_gateway
    rows: list[dict[str, Any]] = []
    for pid, gw in targets or studio_gateway_targets():
        row: dict[str, Any] = {
            "profile_id": pid,
            "gateway": gw,
            "group_name": pid,
            "display_name": pid,
            "word": "Down",
            "block": None,
            "ready": False,
            "ok": False,
        }
        if not key:
            row["block"] = "no Salad API key"
            row["word"] = "Down"
            rows.append(row)
            continue
        try:
            info = snap(gw, key)
        except Exception as exc:
            row["block"] = str(exc)
            row["error"] = str(exc)
            rows.append(row)
            continue
        group = info.get("group") if isinstance(info, dict) else None
        group = group if isinstance(group, dict) else {}
        word = str(
            info.get("word")
            or salad_status.short_status(info)
            or "Unknown"
        )
        block = info.get("block")
        if block is None:
            block = salad_status.generate_block_reason(info)
        row.update(
            {
                "group_name": group.get("name") or pid,
                "display_name": group.get("display_name") or group.get("name") or pid,
                "word": word,
                "block": block,
                "ready": word.split()[0] == "Ready",
                "detail": info.get("detail"),
                "instances": info.get("instances") or [],
                "ok": True,
                "info": info,
            }
        )
        rows.append(row)
    return rows


def pick_studio_group(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prefer a Ready replica; otherwise the first listed group."""
    ready = [r for r in rows if r.get("ready")]
    if ready:
        return ready[0]
    return rows[0] if rows else None


def civitai_id_from_url(url: str) -> str:
    text = (url or "").strip()
    found = ls.civitai_image_id(text)
    if found:
        return found
    if text.isdigit():
        return text
    raise ValueError(f"Not a Civitai image URL or id: {url!r}")


def fetch_civitai_pastes(
    url: str,
    *,
    fetch_fn: Callable[[str], dict[str, str]] | None = None,
) -> dict[str, str]:
    fetch = fetch_fn or ci.fetch_civitai_image_pastes
    image_id = civitai_id_from_url(url)
    pastes = fetch(image_id)
    if not isinstance(pastes, dict):
        raise ValueError(f"Civitai fetch for {image_id} returned no pastes")
    pastes = dict(pastes)
    pastes.setdefault("image_id", image_id)
    return pastes


def convert_to_request(
    pastes: dict[str, str],
    *,
    extras_path: Path | None = None,
    import_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    convert = import_fn or ci.import_to_request
    return convert(
        workflow_text=str(pastes.get("workflow") or ""),
        metadata_text=str(pastes.get("metadata") or ""),
        extras_path=extras_path,
    )


def inspect_converted(
    body: dict[str, Any] | None,
    pastes: dict[str, str],
    *,
    inspect_fn: Callable[..., tuple[list[str], list[str]]] | None = None,
    replica_fn: Callable[..., list[str]] | None = None,
    extras_path: Path | None = None,
) -> dict[str, Any]:
    inspect = inspect_fn or ci.inspect_pastes
    replica = replica_fn or ci.replica_issues
    blocking, notes = inspect(
        str(pastes.get("metadata") or ""),
        str(pastes.get("workflow") or ""),
    )
    meta_text = str(pastes.get("metadata") or "")
    try:
        replica_notes = replica(
            body, metadata_text=meta_text, extras_path=extras_path
        )
    except TypeError:
        replica_notes = replica(body)
    prompt = body.get("prompt") if isinstance(body, dict) else None
    has_graph = isinstance(prompt, dict) and any(
        isinstance(node, dict) and node.get("class_type") for node in prompt.values()
    )
    runnable = bool(has_graph) and not blocking
    return {
        "blocking": list(blocking or []),
        "notes": list(notes or []),
        "replica_issues": list(replica_notes or []),
        "runnable": runnable,
        "has_graph": has_graph,
    }


_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "in",
    "on",
    "at",
    "to",
    "with",
    "from",
    "by",
    "is",
    "are",
    "was",
    "were",
    "this",
    "that",
    "these",
    "those",
    "into",
    "over",
    "under",
    "near",
    "image",
    "photo",
    "picture",
    "scene",
    "shows",
    "showing",
    "there",
    "their",
}


def content_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) >= 4 and w not in _STOPWORDS}


_MULTIPANEL = re.compile(
    r"\b("
    r"three[\s-]?panel|3[\s-]?panel|two[\s-]?panel|2[\s-]?panel|"
    r"four[\s-]?panel|4[\s-]?panel|multi[\s-]?panel|"
    r"comic[\s-]?strip|triptych|"
    r"broken into \d+|three parts|\d+ panels?"
    r")\b",
    re.I,
)
_PLURAL_PEOPLE = re.compile(
    r"\b(several|children|crowd|group|figures|two girls|two women|"
    r"three girls|many)\b",
    re.I,
)
_ONE_PERSON = re.compile(
    r"\b(solitary|single figure|one girl|one woman|one child|a girl|a woman|"
    r"the girl|the woman)\b",
    re.I,
)
_CLOSE_FRAME = re.compile(r"\b(close-?up|portrait|bust|headshot|face)\b", re.I)
_WIDE_FRAME = re.compile(
    r"\b(wide|full-?page|full-?scene|canopy|establishing|landscape view)\b",
    re.I,
)


def is_multipanel_description(text: str) -> bool:
    """True when the caption describes a comic strip / several panels, not one plate."""
    return bool(_MULTIPANEL.search(text or ""))


def composition_signature(text: str) -> tuple[str, str, str]:
    """(layout, people, frame) — unknown means that axis was not mentioned."""
    raw = text or ""
    layout = "multi" if is_multipanel_description(raw) else "single"
    if _PLURAL_PEOPLE.search(raw):
        people = "plural"
    elif _ONE_PERSON.search(raw):
        people = "one"
    else:
        people = "unknown"
    if _CLOSE_FRAME.search(raw):
        frame = "close"
    elif _WIDE_FRAME.search(raw):
        frame = "wide"
    else:
        frame = "unknown"
    return (layout, people, frame)


def descriptions_are_similar(site: str, generated: str) -> bool:
    """True when subject/scene overlap and composition matches.

    Any composition mismatch is significant: single plate vs 3-panel strip,
    one figure vs several, close-up vs wide. Shared medium words (watercolor,
    forest) are not enough. Pixel identity is not required.
    """
    sa, sb = composition_signature(site), composition_signature(generated)
    for left, right in zip(sa, sb, strict=False):
        if left != "unknown" and right != "unknown" and left != right:
            return False
    a, b = content_tokens(site), content_tokens(generated)
    if not a or not b:
        return False
    overlap = a & b
    if not overlap:
        return False
    smaller = min(len(a), len(b))
    return len(overlap) >= 2 or (len(overlap) / smaller) >= 0.4


def _http_get_bytes(url: str, timeout: int = 30) -> bytes:
    # CDN plate URLs are public; a Civitai API bearer on the GET often 401s.
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "SaladStudio-civitai-verify", "accept": "*/*"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_site_plate(
    image_id: str,
    dest: Path,
    *,
    item_fn: Callable[[str], dict[str, Any] | None] | None = None,
    get_bytes_fn: Callable[[str], bytes] | None = None,
) -> Path:
    """Download the Civitai CDN plate for ``image_id`` to ``dest``."""
    fetch_item = item_fn or ls.fetch_civitai_image
    item = fetch_item(str(image_id))
    if not isinstance(item, dict):
        raise ValueError(f"Civitai image {image_id} was not found")
    url = str(item.get("url") or "").strip()
    if not url:
        raise ValueError(f"Civitai image {image_id} has no image url")
    getter = get_bytes_fn or _http_get_bytes
    data = getter(url)
    if not data:
        raise ValueError(f"Civitai image {image_id} download was empty")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def _xai_describe_key() -> str:
    env = (os.environ.get("XAI_API_KEY") or "").strip()
    if env:
        return env
    path = Path.home() / ".config" / "xai" / "key"
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return ""


def default_describe_image(path: Path) -> str:
    """Caption ``path`` via xAI vision when a key exists. Raises if unavailable."""
    key = _xai_describe_key()
    if not key:
        raise RuntimeError("describe unavailable: no XAI_API_KEY or ~/.config/xai/key")
    raw = Path(path).read_bytes()
    if not raw:
        raise RuntimeError(f"describe unavailable: empty file {path}")
    b64 = base64.b64encode(raw).decode("ascii")
    mime = "image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    payload = {
        "model": "grok-2-vision-1212",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Describe this image in 2-4 sentences. Focus on subject, "
                            "pose, setting, and clothing. Do not name art medium or style."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
    }
    req = urllib.request.Request(
        "https://api.x.ai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"describe unavailable: {exc}") from exc
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("describe unavailable: empty vision response")
    msg = (choices[0] or {}).get("message") or {}
    text = str(msg.get("content") or "").strip()
    if not text:
        raise RuntimeError("describe unavailable: blank caption")
    return text


def backtrack_prompt_gap(
    body: dict[str, Any] | None,
    inspect: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Name /prompt causes for a visual gap, then the import conversion that produced them."""
    json_findings: list[str] = []
    import_findings: list[str] = []
    prompt = body.get("prompt") if isinstance(body, dict) else None
    prompt = prompt if isinstance(prompt, dict) else {}
    clip_texts: list[str] = []
    lora_names: list[str] = []
    load_images: list[str] = []
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "")
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        if cls == "CLIPTextEncode":
            raw = inputs.get("text")
            if isinstance(raw, str):
                clip_texts.append(raw.strip())
            elif raw in (None, ""):
                clip_texts.append("")
            else:
                clip_texts.append("")
        elif cls == "LoraLoader":
            lora_names.append(str(inputs.get("lora_name") or ""))
        elif cls == "LoadImage":
            load_images.append(str(inputs.get("image") or ""))
    if clip_texts and all(not t for t in clip_texts):
        json_findings.append("empty CLIP text on CLIPTextEncode")
        import_findings.append(
            "import/convert left CLIP empty (dropped Text Multiline or missing prompt paste)"
        )
    local_loras = [
        n
        for n in lora_names
        if n and not n.lower().startswith("http://") and not n.lower().startswith("https://")
    ]
    if local_loras:
        json_findings.append(
            f"LoRA local filename not a Civitai URL: {local_loras[0]}"
        )
        import_findings.append(
            "resolve_local_lora_nodes did not bind the LoRA to a Civitai download URL"
        )
    notes: list[str] = []
    if isinstance(inspect, dict):
        notes.extend(str(x) for x in (inspect.get("replica_issues") or []))
        notes.extend(str(x) for x in (inspect.get("notes") or []))
    if any("loadimage" in n.lower() and "local" in n.lower() for n in notes) or any(
        img and not img.lower().startswith("http") for img in load_images
    ):
        json_findings.append("LoadImage omitted from Salad POST (local file)")
        import_findings.append(
            "prompt_for_salad_replica drops local LoadImage so img2img becomes txt2img"
        )
    if not json_findings:
        json_findings.append(
            "no obvious empty-CLIP / local-LoRA / omitted-LoadImage cause in /prompt"
        )
        import_findings.append(
            "visual gap may be sampler/RNG or content the convert did not preserve"
        )
    return {"json_request": json_findings, "import_conversion": import_findings}


def _norm_clip(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def extract_clip_pair(body: dict[str, Any] | None) -> tuple[str, str]:
    """Positive and negative CLIP strings from CFGGuider/KSampler wires."""
    prompt = body.get("prompt") if isinstance(body, dict) else None
    prompt = prompt if isinstance(prompt, dict) else {}
    pos_ids: set[str] = set()
    neg_ids: set[str] = set()
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") not in ("CFGGuider", "KSampler"):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        for key, bucket in (("positive", pos_ids), ("negative", neg_ids)):
            edge = _edge_ids(inputs.get(key))
            if edge:
                bucket.add(edge)
    pos = neg = ""
    for nid, node in prompt.items():
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        raw = inputs.get("text")
        text = raw.strip() if isinstance(raw, str) else ""
        sid = str(nid)
        if sid in pos_ids:
            pos = text
        elif sid in neg_ids:
            neg = text
    return pos, neg


def apply_clip_texts(
    body: dict[str, Any],
    *,
    positive: str | None = None,
    negative: str | None = None,
) -> dict[str, Any]:
    """Write CLIPTextEncode text on CFGGuider wires. Opt-in prompt manipulation only."""
    prompt = body.get("prompt") if isinstance(body, dict) else None
    prompt = prompt if isinstance(prompt, dict) else {}
    pos_ids: set[str] = set()
    neg_ids: set[str] = set()
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") not in ("CFGGuider", "KSampler"):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        pe, ne = _edge_ids(inputs.get("positive")), _edge_ids(inputs.get("negative"))
        if pe:
            pos_ids.add(pe)
        if ne:
            neg_ids.add(ne)
    changed = {"positive": False, "negative": False}
    for nid, node in prompt.items():
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
            continue
        inputs = node.setdefault("inputs", {})
        if not isinstance(inputs, dict):
            continue
        sid = str(nid)
        if positive is not None and sid in pos_ids:
            inputs["text"] = str(positive)
            changed["positive"] = True
        if negative is not None and sid in neg_ids:
            inputs["text"] = str(negative)
            changed["negative"] = True
    return changed


def _edge_ids(val: Any) -> str:
    if isinstance(val, (list, tuple)) and val:
        return str(val[0])
    return ""


def audit_clip(body: dict[str, Any] | None, metadata_text: str = "") -> dict[str, Any]:
    """Check CLIP positive/negative against Civitai generation-data. Does not rewrite text."""
    meta = ci.parse_civitai_metadata(metadata_text) if metadata_text else {}
    pos, neg = extract_clip_pair(body)
    want_pos = str(meta.get("prompt") or "")
    want_neg = str(meta.get("negative") or "")
    issues: list[str] = []
    pos_match = True
    neg_match = True
    if want_pos:
        pos_match = _norm_clip(pos) == _norm_clip(want_pos)
        if not pos_match:
            issues.append(
                "positive CLIP does not match Civitai generation-data prompt"
            )
    elif not pos:
        issues.append("positive CLIP is empty and generation-data has no prompt")
        pos_match = False
    if want_neg:
        neg_match = _norm_clip(neg) == _norm_clip(want_neg)
        if not neg_match:
            issues.append(
                "negative CLIP does not match Civitai generation-data negative"
            )
    return {
        "ok": not issues,
        "positive_match": pos_match,
        "negative_match": neg_match,
        "positive_len": len(pos),
        "negative_len": len(neg),
        "issues": issues,
    }


_WRONG_LORA_FAMILIES = {
    "SDXL",
    "Pony",
    "Illustrious",
    "Krea 2",
    "Flux.1 Dev",
    "Flux.1 D",
}


def loras_in_prompt(body: dict[str, Any] | None) -> list[dict[str, Any]]:
    prompt = body.get("prompt") if isinstance(body, dict) else None
    prompt = prompt if isinstance(prompt, dict) else {}
    rows: list[dict[str, Any]] = []
    for nid, node in prompt.items():
        if not isinstance(node, dict) or node.get("class_type") != "LoraLoader":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        rows.append(
            {
                "nid": str(nid),
                "lora_name": str(inputs.get("lora_name") or ""),
                "strength_model": inputs.get("strength_model"),
                "strength_clip": inputs.get("strength_clip"),
            }
        )
    return rows


def audit_loras(
    body: dict[str, Any] | None,
    extras_path: Path | None = None,
) -> dict[str, Any]:
    """Check each LoraLoader against Studio extras/catalog (import expands extras)."""
    extras = ls.list_loras(extras_path)
    issues: list[str] = []
    rows: list[dict[str, Any]] = []
    for loader in loras_in_prompt(body):
        name = loader["lora_name"]
        item = ls.find_by_loader_name(name, extras_path) if name else None
        family = ls.family_label(item) if item else "unknown"
        in_extras = bool(item)
        http = name.lower().startswith("http://") or name.lower().startswith("https://")
        row = {
            **loader,
            "in_extras": in_extras,
            "family": family,
            "lora_id": str((item or {}).get("id") or ""),
            "verified": bool((item or {}).get("verified")),
        }
        if not name:
            issues.append(f"LoraLoader #{loader['nid']} has empty lora_name")
            row["issue"] = "empty name"
        elif not in_extras and not http:
            issues.append(
                f"LoraLoader #{loader['nid']} local filename not in Studio extras: {name}"
            )
            row["issue"] = "not in extras"
        elif family in _WRONG_LORA_FAMILIES:
            issues.append(
                f"LoraLoader #{loader['nid']} family {family} is not Flux.2 Klein"
            )
            row["issue"] = f"wrong family {family}"
        rows.append(row)
    return {
        "ok": not issues,
        "loras": rows,
        "extras_count": len(extras),
        "issues": issues,
    }


_ABLATE_KEEP = {
    "SaveImage",
}


def _ablate_priority(cls: str) -> int:
    if cls == "LoraLoader":
        return 0
    if cls == "CLIPTextEncode":
        return 1
    return 2


def ablate_candidates(body: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Every node except SaveImage, one-at-a-time. LoRAs first, then CLIP encodes, then the rest."""
    prompt = body.get("prompt") if isinstance(body, dict) else None
    prompt = prompt if isinstance(prompt, dict) else {}
    out: list[tuple[str, str]] = []
    for nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "")
        if not cls or cls in _ABLATE_KEEP:
            continue
        out.append((str(nid), cls))
    out.sort(key=lambda row: (_ablate_priority(row[1]), row[0]))
    return out


def run_node_ablation(
    journal: Journal,
    body: dict[str, Any],
    *,
    url: str,
    picked: dict[str, Any],
    key: str,
    out_dir: Path,
    generate_fn: Callable[..., Path] | None,
    max_ablate: int,
    inspect: dict[str, Any] | None,
    describe_fn: Callable[[Path], str] | None,
    fetch_site_fn: Callable[[str, Path], Path] | None,
) -> None:
    """Drop one optional node at a time, POST, journal the JPEG for local compare.

    Does not rewrite CLIP text. Restores the full graph between trials.
    """
    cands = ablate_candidates(body)[: max(0, int(max_ablate))]
    journal.append(
        step="ablate-plan",
        url=url,
        candidates=[{"nid": nid, "class_type": cls} for nid, cls in cands],
    )
    for nid, cls in cands:
        variant = prompt_without_node(body, nid)
        try:
            path = post_to_group(
                variant,
                picked,
                key=key,
                out_dir=out_dir,
                generate_fn=generate_fn,
            )
            journal.append(
                step="ablate",
                ok=True,
                url=url,
                dropped=nid,
                class_type=cls,
                image=str(path),
            )
            compare_generated_to_site(
                journal,
                url=url,
                generated_path=Path(path),
                body=variant,
                inspect=inspect,
                describe_fn=describe_fn,
                fetch_site_fn=fetch_site_fn,
            )
        except Exception as exc:
            journal.append(
                step="ablate",
                ok=False,
                url=url,
                dropped=nid,
                class_type=cls,
                error=str(exc),
            )


def prompt_without_node(body: dict[str, Any], nid: str) -> dict[str, Any]:
    """Deep-copy /prompt and drop one node with the same passthrough as replica POST."""
    out = copy.deepcopy(body)
    prompt = out.get("prompt")
    if not isinstance(prompt, dict):
        return out
    node = prompt.get(str(nid))
    if isinstance(node, dict):
        ci._passthrough_drop_node(prompt, str(nid), node)
        ci._rewire_missing_links(prompt)
    return out


def journal_prompt_backtrack(
    journal: Journal,
    *,
    url: str,
    body: dict[str, Any] | None,
    inspect: dict[str, Any] | None = None,
    reason: str = "",
) -> dict[str, list[str]]:
    """Inspect converted /prompt, journal JSON causes then import-conversion causes."""
    gap = backtrack_prompt_gap(body, inspect)
    journal.append(
        step="backtrack",
        url=url,
        reason=reason or None,
        json_request=gap["json_request"],
        import_conversion=gap["import_conversion"],
    )
    return gap


def visual_gap_actionable(gap: dict[str, list[str]] | None) -> bool:
    """True when JSON findings point at convert (empty CLIP, local LoRA, omitted LoadImage)."""
    blob = " ".join((gap or {}).get("json_request") or []).lower()
    if "no obvious" in blob:
        return False
    return any(
        key in blob
        for key in ("clip", "lora", "loadimage", "load image")
    )


def compare_generated_to_site(
    journal: Journal,
    *,
    url: str,
    generated_path: Path | None,
    body: dict[str, Any] | None = None,
    inspect: dict[str, Any] | None = None,
    describe_fn: Callable[[Path], str] | None = None,
    fetch_site_fn: Callable[[str, Path], Path] | None = None,
    image_id: str | None = None,
) -> dict[str, Any]:
    """Describe site vs generated JPEGs, journal similar/different, backtrack on a gap.

    A failed captioner still inspects ``/prompt`` (JSON then import) when a JPEG exists.
    """
    if generated_path is None or not Path(generated_path).is_file():
        event = journal.append(
            step="compare",
            ok=False,
            skipped="no POST JPEG",
            url=url,
        )
        return event
    iid = image_id or civitai_id_from_url(url)
    site_path = journal.dir / f"site_{iid}.jpg"
    try:
        fetch = fetch_site_fn or (
            lambda image_id, dest: fetch_site_plate(image_id, dest)
        )
        got = fetch(str(iid), site_path)
        site_path = Path(got) if isinstance(got, (str, Path)) else site_path
    except Exception as exc:
        event = journal.append(
            step="compare",
            ok=False,
            skipped="no site image",
            error=str(exc),
            url=url,
            generated=str(generated_path),
        )
        event["backtrack"] = journal_prompt_backtrack(
            journal,
            url=url,
            body=body,
            inspect=inspect,
            reason="compare skipped (no site image); JSON inspected anyway",
        )
        return event
    caption = describe_fn
    if caption is None:
        if not _xai_describe_key():
            return _pending_local_describe(
                journal,
                url=url,
                site_path=site_path,
                generated_path=generated_path,
                body=body,
                inspect=inspect,
                error="no XAI_API_KEY or ~/.config/xai/key",
            )
        caption = default_describe_image
    try:
        site_text = caption(Path(site_path))
        gen_text = caption(Path(generated_path))
    except Exception as exc:
        return _pending_local_describe(
            journal,
            url=url,
            site_path=site_path,
            generated_path=generated_path,
            body=body,
            inspect=inspect,
            error=str(exc),
        )
    similar = descriptions_are_similar(site_text, gen_text)
    event = journal.append(
        step="compare",
        ok=True,
        url=url,
        similar=similar,
        significantly_different=not similar,
        site_description=site_text,
        generated_description=gen_text,
        site_image=str(site_path),
        generated=str(generated_path),
    )
    if not similar:
        event["backtrack"] = journal_prompt_backtrack(
            journal,
            url=url,
            body=body,
            inspect=inspect,
            reason="descriptions significantly different",
        )
    return event


def _pending_local_describe(
    journal: Journal,
    *,
    url: str,
    site_path: Path,
    generated_path: Path,
    body: dict[str, Any] | None,
    inspect: dict[str, Any] | None,
    error: str,
) -> dict[str, Any]:
    """Remote vision failed; keep local JPEGs and inspect /prompt. Not a dead skip."""
    event = journal.append(
        step="compare",
        ok=False,
        skipped="pending_local_describe",
        pending_local_describe=True,
        error=error,
        url=url,
        site_image=str(site_path),
        generated=str(generated_path),
    )
    event["backtrack"] = journal_prompt_backtrack(
        journal,
        url=url,
        body=body,
        inspect=inspect,
        reason="remote vision failed; local JPEGs saved — describe those files then --record-compare",
    )
    _save_prompt_snapshot(journal, body, inspect)
    return event


def _save_prompt_snapshot(
    journal: Journal,
    body: dict[str, Any] | None,
    inspect: dict[str, Any] | None,
) -> None:
    if isinstance(body, dict):
        (journal.dir / "last_prompt.json").write_text(
            json.dumps(body, default=str), encoding="utf-8"
        )
    if isinstance(inspect, dict):
        (journal.dir / "last_inspect.json").write_text(
            json.dumps(inspect, default=str), encoding="utf-8"
        )


def complete_compare_with_texts(
    journal: Journal,
    *,
    url: str,
    site_description: str,
    generated_description: str,
    body: dict[str, Any] | None = None,
    inspect: dict[str, Any] | None = None,
    site_image: str | None = None,
    generated: str | None = None,
) -> dict[str, Any]:
    """Finish compare using descriptions of the already-downloaded local JPEGs."""
    if body is None:
        snap = journal.dir / "last_prompt.json"
        if snap.is_file():
            try:
                loaded = json.loads(snap.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                loaded = None
            if isinstance(loaded, dict):
                body = loaded
    if inspect is None:
        snap = journal.dir / "last_inspect.json"
        if snap.is_file():
            try:
                loaded = json.loads(snap.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                loaded = None
            if isinstance(loaded, dict):
                inspect = loaded
    similar = descriptions_are_similar(site_description, generated_description)
    event = journal.append(
        step="compare",
        ok=True,
        local_describe=True,
        url=url,
        similar=similar,
        significantly_different=not similar,
        site_description=site_description,
        generated_description=generated_description,
        site_image=site_image,
        generated=generated,
    )
    if not similar:
        event["backtrack"] = journal_prompt_backtrack(
            journal,
            url=url,
            body=body,
            inspect=inspect,
            reason="local file descriptions significantly different",
        )
    return event


def post_to_group(
    body: dict[str, Any],
    group: dict[str, Any],
    *,
    key: str,
    out_dir: Path,
    generate_fn: Callable[..., Path] | None = None,
    on_log: Callable[[str, str], None] | None = None,
) -> Path:
    generate = generate_fn or generator.generate_from_payload
    return generate(
        gateway=str(group.get("gateway") or ""),
        key=key,
        payload=body,
        out_dir=Path(out_dir),
        on_log=on_log,
    )


def pull_group_logs(
    group: dict[str, Any],
    key: str,
    *,
    log_fn: Callable[..., list[str]] | None = None,
) -> list[str]:
    pull = log_fn or salad_status.recent_log_lines
    name = str(group.get("group_name") or "")
    if not name or not key:
        return []
    try:
        return list(
            pull(key, group_name=name, minutes=20, limit=40) or []
        )
    except Exception as exc:
        return [f"log pull failed: {exc}"]


def diagnose_failure(
    error: str,
    logs: list[str] | None = None,
    inspect: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Turn convert/inspect/POST/log text into import-code issue records."""
    issues: list[dict[str, Any]] = []
    blob = error or ""
    for line in logs or []:
        blob += "\n" + str(line)
    if inspect and inspect.get("blocking"):
        for item in inspect["blocking"]:
            issues.append({"kind": "inspect_blocking", "message": str(item)})
    if inspect and not inspect.get("has_graph", True):
        issues.append({"kind": "empty_prompt", "message": "converted JSON has no prompt graph"})
    if _MISSING_NODE.search(blob):
        class_type = ""
        field = _CLASS_TYPE_FIELD.search(blob)
        if field and field.group(1).strip() not in _SKIP_TYPE_TOKENS:
            class_type = field.group(1).strip()
        if not class_type:
            named = _NODE_NOT_FOUND.search(blob)
            if named:
                class_type = named.group(1).strip()
        issues.append(
            {
                "kind": "missing_node_type",
                "class_type": class_type,
                "message": blob[:800],
            }
        )
    if not issues and blob.strip():
        issues.append({"kind": "runtime", "message": blob[:800]})
    return issues


def add_salad_missing_type(source: str, class_type: str) -> str:
    """Insert a Salad-missing class into SALAD_MISSING_TYPES (the only omit list)."""
    name = str(class_type or "").strip()
    if not name:
        return source
    quoted = json.dumps(name)
    marker = "SALAD_MISSING_TYPES = {"
    idx = source.find(marker)
    if idx >= 0:
        end = source.find("}", idx)
        if end > idx and quoted not in source[idx:end]:
            source = source[: idx + len(marker)] + f"\n    {quoted}," + source[idx + len(marker) :]
    return source


def apply_known_import_fix(
    issues: list[dict[str, Any]],
    *,
    source_root: Path,
    journal: Journal,
) -> bool:
    """Edit conversion sources for known Salad failures. False = stop (loop or nothing to do)."""
    missing = [
        i.get("class_type")
        for i in issues
        if i.get("kind") == "missing_node_type" and i.get("class_type")
    ]
    if not missing:
        journal.append(
            step="import-code-change",
            ok=False,
            skipped="no mechanical import-code fix for these issues",
            issues=issues,
        )
        return False
    path = source_root / "comfy_import.py"
    if not path.is_file():
        journal.append(
            step="import-code-change",
            ok=False,
            error=f"missing {path}",
        )
        return False
    original = path.read_text(encoding="utf-8")
    updated = original
    for class_type in missing:
        updated = add_salad_missing_type(updated, str(class_type))
    if updated == original:
        journal.append(
            step="import-code-change",
            ok=False,
            skipped="no mechanical import-code fix for these issues",
            unchanged=True,
            issues=issues,
        )
        return False
    description = "add Salad-missing node type(s) to conversion omit list: " + ", ".join(
        str(x) for x in missing
    )
    writes = {"comfy_import.py": updated}
    parts: list[tuple[str, str]] = []
    for src in import_source_paths(source_root):
        if src.name in writes:
            parts.append((src.name, writes[src.name]))
        elif src.is_file():
            parts.append((src.name, src.read_text(encoding="utf-8")))
        else:
            parts.append((src.name, ""))
    fp = fingerprint_sources(parts)
    if not record_import_code_change(journal, fp, description):
        return False
    path.write_text(updated, encoding="utf-8")
    reload_conversion_modules(source_root)
    return True


def reload_conversion_modules(source_root: Path | None = None) -> None:
    """Re-bind convert/POST to conversion sources on disk after an import-code edit."""
    import importlib
    import importlib.util

    global ci
    root = Path(source_root) if source_root is not None else _HERE
    path = (root / "comfy_import.py").resolve()
    live = (_HERE / "comfy_import.py").resolve()
    if path != live:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return
        if "def import_to_request" not in text or "def prompt_for_salad_replica" not in text:
            return
    if path == live:
        for name in ("comfy_import", "salad_studio.comfy_import"):
            mod = sys.modules.get(name)
            if mod is not None:
                importlib.reload(mod)
        ci = sys.modules.get("comfy_import") or sys.modules["salad_studio.comfy_import"]
        pkg = sys.modules.get("salad_studio")
        if pkg is not None and "salad_studio.comfy_import" in sys.modules:
            pkg.comfy_import = sys.modules["salad_studio.comfy_import"]
        return
    if not path.is_file():
        return
    spec = importlib.util.spec_from_file_location("salad_studio.comfy_import", path)
    if spec is None or spec.loader is None:
        return
    mod = importlib.util.module_from_spec(spec)
    sys.modules["salad_studio.comfy_import"] = mod
    sys.modules["comfy_import"] = mod
    spec.loader.exec_module(mod)
    pkg = sys.modules.get("salad_studio")
    if pkg is not None:
        pkg.comfy_import = mod
    ci = mod


def sync_source_fingerprint(journal: Journal, source_root: Path) -> bool:
    """Record baseline or an external import-code edit. False on loop."""
    fp = fingerprint_import_sources(source_root)
    seen = journal.fingerprints()
    if not seen:
        return record_import_code_change(
            journal, fp, "baseline import sources", step="import-code-baseline"
        )
    if fp == seen[-1]:
        return True
    return record_import_code_change(
        journal, fp, "import sources changed since last journaled fingerprint"
    )


def _load_fixture_file(path: Path) -> dict[str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"fixture {path} is not a JSON object")
    return {
        "image_id": str(raw.get("image_id") or "fixture"),
        "metadata": str(raw.get("metadata") or ""),
        "workflow": str(raw.get("workflow") or ""),
        "tool": str(raw.get("tool") or ""),
    }


def _node_count(body: dict[str, Any] | None) -> int:
    prompt = body.get("prompt") if isinstance(body, dict) else None
    if not isinstance(prompt, dict):
        return 0
    return sum(
        1
        for node in prompt.values()
        if isinstance(node, dict) and node.get("class_type")
    )


def run_verify(
    urls: list[str],
    journal: Journal,
    *,
    snapshot_fn: Callable[..., dict[str, Any]] | None = None,
    fetch_fn: Callable[..., dict[str, str]] | None = None,
    import_fn: Callable[..., dict[str, Any]] | None = None,
    inspect_fn: Callable[..., tuple[list[str], list[str]]] | None = None,
    replica_fn: Callable[..., list[str]] | None = None,
    generate_fn: Callable[..., Path] | None = None,
    log_fn: Callable[..., list[str]] | None = None,
    describe_fn: Callable[[Path], str] | None = None,
    fetch_site_fn: Callable[[str, Path], Path] | None = None,
    resolve_key_fn: Callable[[], str] | None = None,
    extras_path: Path | None = None,
    out_dir: Path | None = None,
    no_post: bool = False,
    edit_import: bool = False,
    fixture: dict[str, str] | None = None,
    fallback_fixture: bool = True,
    source_root: Path | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    ablate: bool = False,
    max_ablate: int = 24,
    allow_prompt_edit: bool = False,
    prompt_positive: str | None = None,
    prompt_negative: str | None = None,
    targets: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """List replicas, import each URL, optionally POST, journal every step."""
    source_root = Path(source_root) if source_root is not None else _HERE
    out_dir = Path(out_dir) if out_dir is not None else journal.dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not sync_source_fingerprint(journal, source_root):
        return {"ok": False, "loop": True, "journal": str(journal.file)}

    key = ""
    key_error = ""
    resolve = resolve_key_fn or tokens.resolve_salad_key
    try:
        key = str(resolve() or "")
    except Exception as exc:
        key_error = str(exc)
        journal.append(step="salad-key", ok=False, error=key_error)

    groups = list_studio_groups(
        key or None, snapshot_fn=snapshot_fn, targets=targets
    )
    picked = pick_studio_group(groups)
    journal.append(
        step="container-list",
        ok=bool(groups),
        groups=[
            {
                "profile_id": g.get("profile_id"),
                "gateway": g.get("gateway"),
                "group_name": g.get("group_name"),
                "display_name": g.get("display_name"),
                "word": g.get("word"),
                "block": g.get("block"),
                "ready": g.get("ready"),
            }
            for g in groups
        ],
        picked=(
            {
                "profile_id": picked.get("profile_id"),
                "gateway": picked.get("gateway"),
                "group_name": picked.get("group_name"),
                "word": picked.get("word"),
                "block": picked.get("block"),
                "ready": picked.get("ready"),
            }
            if picked
            else None
        ),
        key_error=key_error or None,
    )

    summaries: list[dict[str, Any]] = []
    for url in urls:
        summaries.append(
            _verify_one_url(
                url,
                journal,
                picked=picked,
                key=key,
                extras_path=extras_path,
                out_dir=out_dir,
                no_post=no_post,
                edit_import=edit_import,
                fixture=fixture,
                fallback_fixture=fallback_fixture,
                source_root=source_root,
                max_attempts=max_attempts,
                fetch_fn=fetch_fn,
                import_fn=import_fn,
                inspect_fn=inspect_fn,
                replica_fn=replica_fn,
                generate_fn=generate_fn,
                log_fn=log_fn,
                describe_fn=describe_fn,
                fetch_site_fn=fetch_site_fn,
                ablate=ablate,
                max_ablate=max_ablate,
                allow_prompt_edit=allow_prompt_edit,
                prompt_positive=prompt_positive,
                prompt_negative=prompt_negative,
            )
        )
    ok = all(s.get("ok") for s in summaries) if summaries else False
    journal.append(step="done", ok=ok, urls=list(urls))
    return {
        "ok": ok,
        "loop": journal.has_loop(),
        "groups": groups,
        "picked": picked,
        "urls": summaries,
        "journal": str(journal.file),
    }


def _try_fix(
    journal: Journal,
    issues: list[dict[str, Any]],
    *,
    edit_import: bool,
    source_root: Path,
) -> bool:
    journal.append(step="diagnose", issues=issues)
    if not edit_import:
        journal.append(
            step="import-code-change",
            ok=False,
            skipped="edit_import is off; conversion code was not modified",
            issues=issues,
        )
        return False
    return apply_known_import_fix(issues, source_root=source_root, journal=journal)


def _verify_one_url(
    url: str,
    journal: Journal,
    *,
    picked: dict[str, Any] | None,
    key: str,
    extras_path: Path | None,
    out_dir: Path,
    no_post: bool,
    edit_import: bool,
    fixture: dict[str, str] | None,
    fallback_fixture: bool,
    source_root: Path,
    max_attempts: int,
    fetch_fn: Callable[..., dict[str, str]] | None,
    import_fn: Callable[..., dict[str, Any]] | None,
    inspect_fn: Callable[..., tuple[list[str], list[str]]] | None,
    replica_fn: Callable[..., list[str]] | None,
    generate_fn: Callable[..., Path] | None,
    log_fn: Callable[..., list[str]] | None,
    describe_fn: Callable[[Path], str] | None,
    fetch_site_fn: Callable[[str, Path], Path] | None,
    ablate: bool,
    max_ablate: int,
    allow_prompt_edit: bool,
    prompt_positive: str | None,
    prompt_negative: str | None,
) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, max(1, max_attempts) + 1):
        if journal.has_loop():
            return {"ok": False, "url": url, "loop": True, "attempt": attempt}
        journal.append(step="attempt", url=url, attempt=attempt, max_attempts=max_attempts)

        pastes: dict[str, str] | None = None
        fetch_error = ""
        try:
            pastes = fetch_civitai_pastes(url, fetch_fn=fetch_fn)
            journal.append(
                step="fetch",
                ok=True,
                url=url,
                image_id=pastes.get("image_id"),
                attempt=attempt,
            )
        except Exception as exc:
            fetch_error = str(exc)
            journal.append(
                step="fetch",
                ok=False,
                url=url,
                error=fetch_error,
                attempt=attempt,
            )
            if fixture is not None:
                pastes = dict(fixture)
                journal.append(
                    step="fetch",
                    ok=True,
                    url=url,
                    fixture=True,
                    reason=fetch_error,
                    image_id=pastes.get("image_id"),
                )
            elif fallback_fixture:
                pastes = default_fixture_pastes()
                journal.append(
                    step="fetch",
                    ok=True,
                    url=url,
                    fixture=True,
                    reason=fetch_error,
                    image_id="fixture",
                )
            else:
                return {"ok": False, "url": url, "error": fetch_error, "attempt": attempt}

        try:
            body = convert_to_request(
                pastes, extras_path=extras_path, import_fn=import_fn
            )
        except Exception as exc:
            last_error = str(exc)
            journal.append(
                step="convert",
                ok=False,
                url=url,
                error=last_error,
                attempt=attempt,
            )
            issues = diagnose_failure(last_error)
            if not _try_fix(
                journal, issues, edit_import=edit_import, source_root=source_root
            ):
                return {"ok": False, "url": url, "error": last_error, "attempt": attempt}
            continue

        if not isinstance(body, dict):
            last_error = "convert returned a non-object"
            journal.append(step="convert", ok=False, url=url, error=last_error)
            return {"ok": False, "url": url, "error": last_error, "attempt": attempt}

        journal.append(
            step="convert",
            ok=True,
            url=url,
            node_count=_node_count(body),
            has_prompt=isinstance(body.get("prompt"), dict),
            attempt=attempt,
        )
        if allow_prompt_edit and (
            prompt_positive is not None or prompt_negative is not None
        ):
            changed = apply_clip_texts(
                body, positive=prompt_positive, negative=prompt_negative
            )
            journal.append(
                step="prompt-edit",
                ok=True,
                url=url,
                positive=bool(changed.get("positive")),
                negative=bool(changed.get("negative")),
                positive_len=len(prompt_positive or ""),
                negative_len=len(prompt_negative or ""),
            )
        elif prompt_positive or prompt_negative:
            journal.append(
                step="prompt-edit",
                ok=False,
                skipped="allow_prompt_edit is off",
                url=url,
            )

        insp = inspect_converted(
            body,
            pastes,
            inspect_fn=inspect_fn,
            replica_fn=replica_fn,
            extras_path=extras_path,
        )
        journal.append(
            step="inspect",
            ok=insp["runnable"],
            url=url,
            runnable=insp["runnable"],
            blocking=insp["blocking"],
            notes=insp["notes"][:20],
            replica_issues=insp["replica_issues"][:20],
            attempt=attempt,
        )
        _save_prompt_snapshot(journal, body, insp)
        clip_rep = audit_clip(body, str(pastes.get("metadata") or ""))
        journal.append(step="audit-clip", url=url, **clip_rep)
        lora_rep = audit_loras(body, extras_path)
        journal.append(step="audit-loras", url=url, **lora_rep)
        if not insp["runnable"]:
            last_error = "; ".join(insp["blocking"]) or "converted JSON is not runnable"
            issues = diagnose_failure(last_error, inspect=insp)
            if not _try_fix(
                journal, issues, edit_import=edit_import, source_root=source_root
            ):
                return {"ok": False, "url": url, "error": last_error, "attempt": attempt}
            continue

        skip_reason = None
        if no_post:
            skip_reason = "no-post flag"
        elif not key:
            skip_reason = "no Salad API key"
        elif not picked:
            skip_reason = "no container group listed"
        elif not picked.get("ready"):
            word = picked.get("word") or "not Ready"
            block = picked.get("block") or word
            skip_reason = f"group not Ready ({word}): {block}"

        if skip_reason:
            journal.append(
                step="post",
                ok=False,
                skipped=skip_reason,
                url=url,
                gateway=picked.get("gateway") if picked else None,
                group_name=picked.get("group_name") if picked else None,
                word=picked.get("word") if picked else None,
                attempt=attempt,
            )
            compare_generated_to_site(
                journal,
                url=url,
                generated_path=None,
                body=body,
                inspect=insp,
                describe_fn=describe_fn,
                fetch_site_fn=fetch_site_fn,
            )
            return {
                "ok": True,
                "url": url,
                "skipped": skip_reason,
                "attempt": attempt,
                "node_count": _node_count(body),
            }

        logs: list[str] = []

        def _on_log(level: str, message: str) -> None:
            if level in {"error", "warn"}:
                journal.append(
                    step="generate-log",
                    level=level,
                    message=str(message)[:1200],
                )

        try:
            image_path = post_to_group(
                body,
                picked,
                key=key,
                out_dir=out_dir,
                generate_fn=generate_fn,
                on_log=_on_log,
            )
        except Exception as exc:
            last_error = str(exc)
            logs = pull_group_logs(picked, key, log_fn=log_fn)
            journal.append(
                step="post",
                ok=False,
                url=url,
                error=last_error,
                logs=logs,
                gateway=picked.get("gateway"),
                prompt_url=prompt_url(str(picked.get("gateway") or "")),
                attempt=attempt,
            )
            issues = diagnose_failure(last_error, logs=logs)
            if not _try_fix(
                journal, issues, edit_import=edit_import, source_root=source_root
            ):
                return {
                    "ok": False,
                    "url": url,
                    "error": last_error,
                    "logs": logs,
                    "attempt": attempt,
                }
            continue

        journal.append(
            step="post",
            ok=True,
            url=url,
            image=str(image_path),
            gateway=picked.get("gateway"),
            prompt_url=prompt_url(str(picked.get("gateway") or "")),
            attempt=attempt,
        )
        compare_generated_to_site(
            journal,
            url=url,
            generated_path=Path(image_path),
            body=body,
            inspect=insp,
            describe_fn=describe_fn,
            fetch_site_fn=fetch_site_fn,
        )
        if ablate and picked and key:
            run_node_ablation(
                journal,
                body,
                url=url,
                picked=picked,
                key=key,
                out_dir=out_dir,
                generate_fn=generate_fn,
                max_ablate=max_ablate,
                inspect=insp,
                describe_fn=describe_fn,
                fetch_site_fn=fetch_site_fn,
            )
        return {
            "ok": True,
            "url": url,
            "image": str(image_path),
            "attempt": attempt,
            "node_count": _node_count(body),
        }

    journal.append(
        step="max-attempts",
        ok=False,
        url=url,
        max_attempts=max_attempts,
        error=last_error,
    )
    return {"ok": False, "url": url, "error": last_error, "max_attempts": True}


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Verify Civitai image URL(s) through Salad Studio import and an optional "
            f"replica POST. Retry loop is capped at {MAX_ATTEMPTS} plus fingerprint stop."
        )
    )
    p.add_argument(
        "urls",
        nargs="*",
        help="Civitai image URL(s), e.g. https://civitai.com/images/123566519",
    )
    p.add_argument(
        "--record-compare",
        action="store_true",
        help="Finish compare from descriptions of the local site/generated JPEGs",
    )
    p.add_argument("--site-description", default="", help="Caption of the local site plate")
    p.add_argument(
        "--generated-description",
        default="",
        help="Caption of the local Salad JPEG",
    )
    p.add_argument(
        "--journal",
        required=True,
        help="Append-only journal file or directory",
    )
    p.add_argument("--out", default="", help="Directory for Salad JPEGs")
    p.add_argument(
        "--no-post",
        action="store_true",
        help="Convert/inspect only; never POST /prompt",
    )
    p.add_argument(
        "--edit-import",
        action="store_true",
        dest="edit_import",
        help=(
            "Opt in to writing known mechanical conversion patches into "
            "comfy_import.py on disk and retrying (default: off; the failure is "
            "journaled and the run halts)"
        ),
    )
    p.add_argument(
        "--no-edit-import",
        action="store_false",
        dest="edit_import",
        help=(
            "Never edit conversion sources on inspect/POST failure "
            "(already the default; accepted for compatibility)"
        ),
    )
    p.add_argument(
        "--fixture",
        default="",
        help="JSON {metadata, workflow} used when Civitai fetch fails (or instead of fetch)",
    )
    p.add_argument(
        "--no-fallback",
        action="store_true",
        help="Do not use the bundled metadata fixture when Civitai fetch fails",
    )
    p.add_argument(
        "--max-attempts",
        type=int,
        default=MAX_ATTEMPTS,
        help=f"Retry cap after import-code edits (default {MAX_ATTEMPTS})",
    )
    p.add_argument("--extras", default="", help="LoRA extras JSON path")
    p.add_argument(
        "--ablate",
        action="store_true",
        help="After a successful POST, drop one optional node at a time and POST again",
    )
    p.add_argument(
        "--max-ablate",
        type=int,
        default=24,
        help="Max nodes to drop in --ablate (LoRAs first, then CLIP, then others)",
    )
    p.add_argument(
        "--source-root",
        default="",
        help="Directory of comfy_import.py / request_json.py (default: this package)",
    )
    p.add_argument(
        "--allow-prompt-edit",
        action="store_true",
        help="Allow CLIP text overlay (authors sometimes omit the prompt on purpose)",
    )
    p.add_argument(
        "--prompt-positive",
        default="",
        help="With --allow-prompt-edit, set positive CLIP text before POST",
    )
    p.add_argument(
        "--prompt-negative",
        default="",
        help="With --allow-prompt-edit, set negative CLIP text before POST",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.record_compare:
        if not str(args.site_description or "").strip() or not str(
            args.generated_description or ""
        ).strip():
            print(
                " --record-compare needs --site-description and --generated-description",
                file=sys.stderr,
            )
            return 1
        journal = Journal(args.journal)
        url = ""
        if args.urls:
            url = args.urls[0]
        else:
            for row in reversed(journal.events()):
                if row.get("url"):
                    url = str(row["url"])
                    break
        last_cmp = None
        for row in reversed(journal.events()):
            if row.get("step") == "compare":
                last_cmp = row
                break
        result = complete_compare_with_texts(
            journal,
            url=url,
            site_description=str(args.site_description),
            generated_description=str(args.generated_description),
            site_image=(last_cmp or {}).get("site_image"),
            generated=(last_cmp or {}).get("generated"),
        )
        print(
            json.dumps(
                {
                    "journal": str(journal.file),
                    "ok": True,
                    "similar": result.get("similar"),
                    "significantly_different": result.get("significantly_different"),
                    "loop": journal.has_loop(),
                },
                indent=2,
            )
        )
        return 0
    if not args.urls:
        print("pass at least one Civitai image URL", file=sys.stderr)
        return 1
    journal = Journal(args.journal)
    fixture = None
    if args.fixture:
        fixture_path = Path(args.fixture)
        try:
            fixture = _load_fixture_file(fixture_path)
            journal.append(step="fixture", ok=True, path=str(fixture_path))
        except Exception as exc:
            journal.append(step="fixture", ok=False, path=str(fixture_path), error=str(exc))
            print(f"fixture load failed: {exc}", file=sys.stderr)
            return 1
    extras = Path(args.extras) if args.extras else None
    source_root = Path(args.source_root) if args.source_root else _HERE
    out_dir = Path(args.out) if args.out else None
    try:
        result = run_verify(
            list(args.urls),
            journal,
            extras_path=extras,
            out_dir=out_dir,
            no_post=bool(args.no_post),
            edit_import=bool(args.edit_import),
            fixture=fixture,
            fallback_fixture=not args.no_fallback,
            source_root=source_root,
            max_attempts=int(args.max_attempts) or MAX_ATTEMPTS,
            ablate=bool(args.ablate),
            max_ablate=int(args.max_ablate) or 24,
            allow_prompt_edit=bool(args.allow_prompt_edit),
            prompt_positive=str(args.prompt_positive or "") or None,
            prompt_negative=str(args.prompt_negative or "") or None,
        )
    except Exception as exc:
        journal.append(step="fatal", ok=False, error=str(exc))
        print(f"fatal: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"journal": result.get("journal"), "ok": result.get("ok"), "loop": result.get("loop")}, indent=2))
    if result.get("loop"):
        return 3
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
