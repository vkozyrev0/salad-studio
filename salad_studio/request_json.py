"""Build the Salad POST /prompt JSON from Config + selected LoRAs + prompt text."""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

_TOOLS = Path(__file__).resolve().parent.parent
_HERE = Path(__file__).resolve().parent
for p in (_HERE, _TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import salad_gen  # noqa: E402
from salad_probe_klein import klein_payload  # noqa: E402

import lora_store as ls  # noqa: E402

UNET_BASE = "flux-2-klein-base-9b-fp8.safetensors"
UNET_DISTILLED = "flux-2-klein-9b-fp8.safetensors"
# The SNOFS merged cut. Its filename contains BOTH "snofs" and "distilled", so the
# "snofs" test must come first in normalize_unet, otherwise it lands on the plain
# distilled cut and the request goes to the wrong container group.
UNET_SNOFS = "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors"
UNET_LABELS = ("Base 9B", "Distilled 9B", "SNOFS 9B")


# Prefetched next to the official Klein files. "distilled" in the name must
# not map this onto flux-2-klein-9b-fp8.
_UNET_KEEP = {
    "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors",
}


def normalize_unet(raw: str | None) -> str:
    """Map a Civitai Model line or combo label to a replica filename."""
    name = str(raw or "").replace("\\", "/").split("/")[-1].strip()
    if name in _UNET_KEEP:
        return name
    low = name.lower()
    # Before "distill": a SNOFS cut is named "..._distilledV12..." and would
    # otherwise normalise to the plain distilled checkpoint.
    if "snofs" in low:
        return UNET_SNOFS
    if "distill" in low:
        return UNET_DISTILLED
    if low.endswith(".safetensors"):
        if "klein" in low and "9b-fp8" in low and "base" not in low:
            return UNET_DISTILLED
        if "base-9b" in low or name == UNET_BASE:
            return UNET_BASE
        return name
    if "base" in low:
        return UNET_BASE
    if "klein" in low and "9b" in low:
        return UNET_DISTILLED
    return UNET_BASE


def unet_label(raw: str | None) -> str:
    """The combo label for a replica filename, one of ``UNET_LABELS``.

    Round-trips through :func:`normalize_unet`: label -> filename -> label.
    """
    name = normalize_unet(raw)
    if name == UNET_DISTILLED:
        return "Distilled 9B"
    if name == UNET_SNOFS:
        return "SNOFS 9B"
    return "Base 9B"


def _filename_of(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        return Path(unquote(urlparse(text).path)).name
    return Path(text.replace("\\", "/")).name


def weight_meta(
    spec: dict[str, Any] | None = None,
    *,
    title: str = "",
    verified: bool | None = None,
    tag: str = "",
) -> dict[str, Any]:
    """Original filename (and optional prompt tag) kept next to the load URL."""
    src = spec or {}
    name = (
        str(src.get("filename") or "").strip()
        or str(title or "").strip()
        or _filename_of(str(src.get("lora_name") or ""))
    )
    meta: dict[str, Any] = {}
    if name:
        meta["title"] = name
    tag_s = str(src.get("tag") or tag or "").strip()
    if tag_s and tag_s != name and tag_s != Path(name).stem:
        meta["tag"] = tag_s
    flag = src.get("verified") if spec is not None else verified
    if flag is None:
        flag = verified
    if flag is not None:
        meta["verified"] = bool(flag)
    ver = str(src.get("version_name") or "").strip()
    if ver:
        meta["version"] = ver
    var = str(src.get("variation") or "").strip() or ls.variation_label(
        version_name=ver, filename=name
    )
    if var:
        meta["variation"] = var
    base = str(src.get("base") or "").strip()
    if base:
        meta["base"] = base
    if str(meta.get("title") or "").isdigit() and tag_s:
        meta["title"] = (
            tag_s if tag_s.lower().endswith(".safetensors") else f"{tag_s}.safetensors"
        )
    return meta


def _edge(val: Any) -> tuple[str, int] | None:
    if isinstance(val, list) and len(val) >= 2:
        try:
            return str(val[0]), int(val[1])
        except (TypeError, ValueError):
            return None
    return None


def base_clip_ref(prompt: dict[str, Any], start: Any = None) -> list[Any] | None:
    """Walk a CLIP wire back to CLIPLoader / checkpoint CLIP (skip LoRA patches)."""
    cur = start
    seen: set[str] = set()
    while True:
        edge = _edge(cur)
        if edge is None:
            break
        nid, slot = edge
        if nid in seen:
            break
        seen.add(nid)
        node = prompt.get(nid)
        if not isinstance(node, dict):
            break
        cls = str(node.get("class_type") or "")
        if cls in ("CLIPLoader", "DualCLIPLoader"):
            return [nid, 0]
        if cls == "CheckpointLoaderSimple":
            return [nid, 1]
        if cls == "LoraLoader":
            inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
            cur = inputs.get("clip")
            continue
        return [nid, slot]
    for nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "")
        if cls in ("CLIPLoader", "DualCLIPLoader"):
            return [str(nid), 0]
        if cls == "CheckpointLoaderSimple":
            return [str(nid), 1]
    return None


def encode_prompts_before_loras(prompt: dict[str, Any]) -> dict[str, Any]:
    """CLIPTextEncode on the CLIP loader; LoRA chain still patches the UNET.

    Illustrious/Anima CLIP tensors on Qwen corrupt prompt encodings. Encode
    positive and negative on the base CLIP, then apply LoRAs to the model.
    """
    if not isinstance(prompt, dict):
        return prompt
    for node in prompt.values():
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        clip = inputs.get("clip")
        src = None
        edge = _edge(clip)
        if edge is not None:
            src = prompt.get(edge[0])
        if not (isinstance(src, dict) and src.get("class_type") == "LoraLoader"):
            continue
        base = base_clip_ref(prompt, clip)
        if base:
            inputs["clip"] = list(base)
    return prompt


_FOREIGN_CLIP = (
    "illustrious",
    "_il_",
    "il_mix",
    "ilvp",
    "anima",
    "pony",
    "sdxl",
    "sd_xl",
    "sd-xl",
)
_KLEIN_CLIP = (
    "klein",
    "flux2",
    "flux.2",
    "artificeal",
    "agedart",
)
_DISTILLED_SDE = frozenset(
    {
        "dpmpp_sde",
        "dpmpp_sde_gpu",
        "dpmpp_2m_sde",
        "dpmpp_2m_sde_gpu",
        "dpmpp_3m_sde",
        "dpmpp_3m_sde_gpu",
    }
)


def _lora_clip_blob(node: dict[str, Any]) -> str:
    meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    return " ".join(
        [
            str(meta.get("title") or ""),
            str(meta.get("tag") or ""),
            str(meta.get("base") or ""),
            str(inputs.get("lora_name") or ""),
        ]
    ).lower()


def lora_is_klein_clip(node: dict[str, Any]) -> bool:
    """True when this LoRA's CLIP should patch Qwen (Klein-native / Artificeal)."""
    blob = _lora_clip_blob(node)
    return any(tok in blob for tok in _KLEIN_CLIP)


def lora_is_foreign_clip(node: dict[str, Any]) -> bool:
    """True when this LoRA's CLIP tensors should not patch Qwen."""
    if lora_is_klein_clip(node):
        return False
    return any(tok in _lora_clip_blob(node) for tok in _FOREIGN_CLIP)


def last_lora_clip_ref(prompt: dict[str, Any]) -> list[Any] | None:
    for node in prompt.values():
        if not isinstance(node, dict) or node.get("class_type") != "CFGGuider":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        edge = _edge(inputs.get("model"))
        if edge is None:
            continue
        src = prompt.get(edge[0])
        if isinstance(src, dict) and src.get("class_type") == "LoraLoader":
            return [edge[0], 1]
    last = None
    for nid, node in prompt.items():
        if isinstance(node, dict) and node.get("class_type") == "LoraLoader":
            last = [str(nid), 1]
    return last


def last_klein_clip_ref(prompt: dict[str, Any]) -> list[Any] | None:
    """Walk UNET chain backward; first Klein-native LoRA is last in apply order."""
    edge = None
    for node in prompt.values():
        if not isinstance(node, dict) or node.get("class_type") != "CFGGuider":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        edge = _edge(inputs.get("model"))
        break
    seen: set[str] = set()
    while edge is not None:
        nid, _slot = edge
        if nid in seen:
            break
        seen.add(nid)
        node = prompt.get(nid)
        if not isinstance(node, dict) or node.get("class_type") != "LoraLoader":
            break
        if lora_is_klein_clip(node):
            return [nid, 1]
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        edge = _edge(inputs.get("model"))
    return last_lora_clip_ref(prompt)


def wire_clip_encodes(prompt: dict[str, Any]) -> dict[str, Any]:
    """Klein-native LoRAs encode after the last LoRA; IL/Anima encode on CLIPLoader.

    Artificeal (Klein) needs its CLIP on the trigger. Illustrious CLIP on Qwen
    corrupts the prompt, so IL-only stacks stay on the base CLIPLoader.

    Mixed stacks (image 130704037: IL characters + Klein-Anime): keep IL on
    UNET, set ``strength_clip`` 0 on non-Klein loaders, encode on the last
    Klein-native LoRA (not SDXL DPO sitting after it). SDXL/Pony UNET
    strength is also zeroed so it cannot sit on top of Klein-Anime.
    """
    if not isinstance(prompt, dict):
        return prompt
    loaders = [
        n
        for n in prompt.values()
        if isinstance(n, dict) and n.get("class_type") == "LoraLoader"
    ]
    if not loaders:
        return prompt
    klein = [n for n in loaders if lora_is_klein_clip(n)]
    klein_ids = {id(n) for n in klein}
    others = [n for n in loaders if id(n) not in klein_ids]
    if klein and others:
        for node in others:
            inputs = node.setdefault("inputs", {})
            if not isinstance(inputs, dict):
                continue
            inputs["strength_clip"] = 0.0
            blob = _lora_clip_blob(node)
            if any(tok in blob for tok in ("sdxl", "sd_xl", "sd-xl", "pony")):
                inputs["strength_model"] = 0.0
    if klein:
        last = last_klein_clip_ref(prompt) or last_lora_clip_ref(prompt)
        if not last:
            return prompt
        for node in prompt.values():
            if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
                continue
            inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
            inputs["clip"] = list(last)
        return prompt
    if others:
        return encode_prompts_before_loras(prompt)
    last = last_lora_clip_ref(prompt)
    if not last:
        return prompt
    for node in prompt.values():
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        inputs["clip"] = list(last)
    return prompt


def passthrough_lora_node(prompt: dict[str, Any], nid: str) -> None:
    """Rewire consumers through this LoraLoader, then delete it."""
    node = prompt.get(nid)
    if not isinstance(node, dict):
        return
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    model_src = inputs.get("model")
    clip_src = inputs.get("clip")
    for other in prompt.values():
        if not isinstance(other, dict):
            continue
        ins = other.get("inputs")
        if not isinstance(ins, dict):
            continue
        for key, val in list(ins.items()):
            edge = _edge(val)
            if not edge or edge[0] != str(nid):
                continue
            if edge[1] == 1 and clip_src is not None:
                ins[key] = list(clip_src) if isinstance(clip_src, list) else clip_src
            elif model_src is not None:
                ins[key] = list(model_src) if isinstance(model_src, list) else model_src
    prompt.pop(nid, None)


def strip_non_klein_loras(prompt: dict[str, Any]) -> dict[str, Any]:
    """Drop IL/SDXL/Pony LoraLoaders when a Klein-native LoRA is also in the stack.

    Stock Comfy cannot apply Illustrious tensors onto Flux.2 Klein. Mixed
    stacks (130704037) otherwise sample distilled Klein + photography CLIP.
    IL-only graphs are left as-is.
    """
    if not isinstance(prompt, dict):
        return prompt
    loaders = [
        (str(nid), node)
        for nid, node in prompt.items()
        if isinstance(node, dict) and node.get("class_type") == "LoraLoader"
    ]
    if not any(lora_is_klein_clip(node) for _nid, node in loaders):
        return prompt
    drop = [nid for nid, node in loaders if not lora_is_klein_clip(node)]
    for nid in sorted(drop, key=lambda s: int(s) if str(s).isdigit() else 0, reverse=True):
        passthrough_lora_node(prompt, nid)
    return prompt


def prompt_has_distilled_unet(prompt: dict[str, Any]) -> bool:
    for node in prompt.values() if isinstance(prompt, dict) else []:
        if not isinstance(node, dict) or node.get("class_type") != "UNETLoader":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        return normalize_unet(str(inputs.get("unet_name") or "")) == UNET_DISTILLED
    return False


def boost_klein_anime_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    """Klein-Anime has no trigger; 'photography'/'realistic' at CFG 1 wins.

    Do not prepend a generic anime line (that overshot into cel-shading).
    Soften only those two words so Flux2 + Klein-Anime can show.
    """
    if not isinstance(prompt, dict):
        return prompt
    if not any(
        isinstance(n, dict)
        and n.get("class_type") == "LoraLoader"
        and lora_is_klein_clip(n)
        and "anime" in _lora_clip_blob(n)
        for n in prompt.values()
    ):
        return prompt
    pos_nid = None
    for node in prompt.values():
        if not isinstance(node, dict) or node.get("class_type") != "CFGGuider":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        edge = _edge(inputs.get("positive"))
        if edge:
            pos_nid = edge[0]
        break
    if not pos_nid:
        return prompt
    enc = prompt.get(pos_nid)
    if not isinstance(enc, dict) or enc.get("class_type") != "CLIPTextEncode":
        return prompt
    inputs = enc.setdefault("inputs", {})
    text = str(inputs.get("text") or "")
    if not text:
        return prompt
    nxt = re.sub(r"\bphotography\b", "illustration", text, flags=re.I)
    nxt = re.sub(r"\brealistic\b", "illustrated", nxt, flags=re.I)
    inputs["text"] = nxt
    return prompt


def remap_distilled_sampler(sampler: str, unet: str | None) -> str:
    """Draw Things ``DPM++ SDE`` is not Comfy ``dpmpp_sde`` on distilled Klein."""
    s = str(sampler or "").strip()
    if not s:
        return s
    if normalize_unet(unet) == UNET_DISTILLED and s.lower() in _DISTILLED_SDE:
        return "euler"
    return s


def attach_lora_chain(
    prompt: dict[str, Any],
    *,
    model_ref: list[Any],
    clip_ref: list[Any],
    loras: list[dict[str, Any]],
    start_id: int = 80,
) -> tuple[list[Any], list[Any]]:
    """Insert chained LoraLoader nodes. Returns (model_ref, clip_ref) of the last."""
    model = list(model_ref)
    clip = list(clip_ref)
    node_id = start_id
    for spec in loras:
        name = str(spec.get("lora_name") or "")
        if not name:
            continue
        key = str(node_id)
        node: dict[str, Any] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": model,
                "clip": clip,
                "lora_name": name,
                "strength_model": float(spec.get("strength_model", 1)),
                "strength_clip": float(spec.get("strength_clip", 1)),
            },
        }
        meta = weight_meta(spec)
        if meta:
            node["_meta"] = meta
        prompt[key] = node
        model = [key, 0]
        clip = [key, 1]
        node_id += 1
    return model, clip


_WEIGHT_INPUT = {
    "UNETLoader": ("unet", "unet_name"),
    "CLIPLoader": ("clip", "clip_name"),
    "VAELoader": ("vae", "vae_name"),
    "CheckpointLoaderSimple": ("checkpoint", "ckpt_name"),
    "LoraLoader": ("lora", "lora_name"),
}


def stamp_weight_refs(body: dict[str, Any]) -> dict[str, Any]:
    """Keep original .safetensors / LoRA filenames on nodes and in ``refs``.

    ``lora_name`` stays the Salad load URL. ``_meta.title`` is the original file
    or prompt tag so Import JSON can be checked without decoding Civitai ids.
    """
    prompt = body.get("prompt")
    if not isinstance(prompt, dict):
        return body
    refs: list[dict[str, Any]] = []

    def _sort_key(item: tuple[Any, Any]) -> tuple[int, str]:
        nid = str(item[0])
        try:
            return (0, f"{int(nid):08d}")
        except ValueError:
            return (1, nid)

    for nid, node in sorted(prompt.items(), key=_sort_key):
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "")
        pair = _WEIGHT_INPUT.get(cls)
        if not pair:
            continue
        kind, field = pair
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        raw = str(inputs.get(field) or "").strip()
        meta = dict(node.get("_meta") or {}) if isinstance(node.get("_meta"), dict) else {}
        title = str(meta.get("title") or "").strip()
        raw_name = _filename_of(raw)
        if raw_name.lower().endswith(".safetensors"):
            title = raw_name
        elif not title:
            title = raw_name
        if title:
            meta["title"] = title
        if "verified" not in meta and raw and not raw.startswith("http"):
            meta["verified"] = Path(raw.replace("\\", "/")).name in ls.replica_weight_names()
        if meta:
            node["_meta"] = meta
        if not raw and not title:
            continue
        row: dict[str, Any] = {
            "node": str(nid),
            "kind": kind,
            "name": title or _filename_of(raw) or raw,
            "ref": ls.strip_civitai_token(raw) if raw else raw,
        }
        if "verified" in meta:
            row["verified"] = bool(meta["verified"])
        tag = str(meta.get("tag") or "").strip()
        if tag:
            row["tag"] = tag
        ver = str(meta.get("version") or "").strip()
        if ver:
            row["version"] = ver
        var = str(meta.get("variation") or "").strip()
        if var:
            row["variation"] = var
        refs.append(row)
    body["refs"] = refs
    return body


def build_request(
    *,
    prompt_text: str,
    negative_text: str = "",
    graph: str,
    width: int,
    height: int,
    steps: int,
    seed: int,
    cfg: float | int | None = None,
    unet: str | None = None,
    loras: list[dict[str, Any]] | None = None,
    selected_ids: list[str] | None = None,
    extras_path: Path | None = None,
) -> dict[str, Any]:
    """Return the JSON object POSTed to Salad ``/prompt``."""
    specs = list(loras) if loras is not None else ls.specs_for_ids(
        selected_ids or [], extras_path, graph=graph
    )
    if graph == "klein":
        body = klein_payload(
            prompt_text,
            seed=seed,
            width=width,
            height=height,
            steps=steps,
            use_loras=False,
            unet_name=normalize_unet(unet) if unet else UNET_BASE,
        )
        graph_nodes = body["prompt"]
        model, _clip = attach_lora_chain(
            graph_nodes,
            model_ref=["70", 0],
            clip_ref=["71", 0],
            loras=specs,
        )
        if specs:
            graph_nodes["63"]["inputs"]["model"] = model
            graph_nodes["63"]["inputs"]["positive"] = ["74", 0]
            graph_nodes["63"]["inputs"]["negative"] = ["67", 0]
        wire_clip_encodes(graph_nodes)
        if cfg is not None:
            for node in graph_nodes.values():
                if isinstance(node, dict) and node.get("class_type") == "CFGGuider":
                    inputs = node.setdefault("inputs", {})
                    inputs["cfg"] = cfg
        graph_nodes["67"]["inputs"]["text"] = str(negative_text or "")
        apply_scheduler(body, "flux2")
        return stamp_weight_refs(body)
    if graph == "flux1":
        strength = float(specs[0]["strength_model"]) if specs else 0.7
        body = salad_gen.flux_payload(
            prompt_text,
            seed,
            width,
            height,
            steps,
            lora_name=None,
            lora_strength=strength,
        )
        graph_nodes = body["prompt"]
        model, clip = attach_lora_chain(
            graph_nodes,
            model_ref=["30", 0],
            clip_ref=["30", 1],
            loras=specs,
            start_id=40,
        )
        if specs:
            graph_nodes["6"]["inputs"]["clip"] = clip
            graph_nodes["33"]["inputs"]["clip"] = clip
            graph_nodes["31"]["inputs"]["model"] = model
        return stamp_weight_refs(body)
    raise ValueError(f"unknown graph {graph!r}")


def apply_scheduler(body: dict[str, Any], kind: str) -> dict[str, Any]:
    """``flux2`` keeps Flux2Scheduler; ``simple`` is Civitai's BasicScheduler."""
    prompt = body.get("prompt")
    if not isinstance(prompt, dict):
        return body
    want = "simple" if str(kind).lower() in ("simple", "basic", "civitai") else "flux2"
    model_ref = ["70", 0]
    cfg = prompt.get("63")
    if isinstance(cfg, dict) and isinstance(cfg.get("inputs"), dict):
        m = cfg["inputs"].get("model")
        if isinstance(m, list) and m:
            model_ref = m
    for _nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        cls = node.get("class_type")
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        if want == "simple" and cls == "Flux2Scheduler":
            steps = inputs.get("steps", 20)
            node["class_type"] = "BasicScheduler"
            node["inputs"] = {
                "model": model_ref,
                "scheduler": "simple",
                "steps": steps,
                "denoise": 1,
            }
        elif want == "flux2" and cls == "BasicScheduler":
            steps = inputs.get("steps", 20)
            width = inputs.get("width", 1024)
            height = inputs.get("height", 1024)
            node["class_type"] = "Flux2Scheduler"
            node["inputs"] = {"steps": steps, "width": width, "height": height}
    return body


def with_civitai_token(url: str, token: str) -> str:
    """Add ``?token=`` so Salad's LoraLoader can download gated Civitai files."""
    if not token or "civitai.com" not in url.lower():
        return url
    parts = urlparse(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    if q.get("token"):
        return url
    q["token"] = token
    return urlunparse(parts._replace(query=urlencode(q)))


def lora_name_inputs(prompt: dict[str, Any] | None) -> list[tuple[dict[str, Any], str]]:
    """Every ``(node, lora_name)`` in the graph whose input names a LoRA file or URL.

    Keyed on the *input*, not the node class. ``LoraLoaderModelOnly`` carries
    ``lora_name`` too, and a ``class_type == "LoraLoader"`` filter silently
    skipped it, so a gated Civitai file reached the replica unauthenticated and
    the LoRA never loaded. (2026-09-22)
    """
    out: list[tuple[dict[str, Any], str]] = []
    for node in (prompt or {}).values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        name = inputs.get("lora_name")
        if isinstance(name, str) and name.strip():
            out.append((node, name))
    return out


def payload_has_civitai_download(body: dict[str, Any]) -> bool:
    for _node, name in lora_name_inputs(body.get("prompt")):
        if "civitai.com" in name.lower() and "/download/" in name.lower():
            q = dict(parse_qsl(urlparse(name).query))
            if not q.get("token"):
                return True
    return False


def civitai_lora_urls(prompt: dict[str, Any]) -> list[str]:
    """Civitai download URLs the graph's LoRA nodes reference, deduped in order.

    Used by ``generator.check_lora_urls`` to confirm each one resolves *before*
    the render is POSTed. A wrong or expired URL is otherwise reported as an
    opaque HTTP 524 from the gateway. Nothing is downloaded.
    """
    urls: list[str] = []
    for _node, name in lora_name_inputs(prompt):
        if name.startswith("http") and "civitai.com" in name.lower() and name not in urls:
            urls.append(name)
    return urls


def lora_url_label(url: str) -> str:
    """A log-safe name for a LoRA URL, never the URL, which carries ``?token=``."""
    m = re.search(r"/download/models/(\d+)", url or "")
    if m:
        return f"civitai:{m.group(1)}"
    return urlparse(url or "").netloc or "lora"


def authorize_civitai_urls(body: dict[str, Any], token: str) -> dict[str, Any]:
    """Return a copy with Civitai download URLs authenticated. Does not mutate ``body``.

    The token lands only on the copy that is POSTed; the editor JSON and the
    prompt history keep the bare URL, so a saved or shared graph carries no
    secret. Re-tokenising an already-tokenised URL is a no-op.
    """
    out = copy.deepcopy(body)
    prompt = out.get("prompt")
    if not isinstance(prompt, dict) or not token:
        return out
    for node, name in lora_name_inputs(prompt):
        node["inputs"]["lora_name"] = with_civitai_token(name, token)
    return out


def _node_input(node: dict[str, Any], key: str, default: Any = None) -> Any:
    inputs = node.get("inputs") if isinstance(node, dict) else None
    if not isinstance(inputs, dict):
        return default
    return inputs.get(key, default)


def coerce_int(val: Any, default: Any = None) -> int | None:
    """Int from a node widget. Comfy links ``[node_id, slot]`` are not sizes."""
    if val is None or val is False or val == "":
        return default
    if isinstance(val, bool):
        return default
    if isinstance(val, list):
        if len(val) >= 2 and isinstance(val[1], int) and val[1] <= 8:
            return default
        return coerce_int(val[0], default) if val else default
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def apply_prompt_texts(body: dict[str, Any], positive: str, negative: str) -> bool:
    """Write Prompt-page text into the CLIP nodes the current graph already uses.

    Returns False when the document has no CFGGuider wiring, so the caller can
    fall back to building a fresh request. Does not replace the graph.
    """
    prompt = body.get("prompt") if isinstance(body, dict) else None
    if not isinstance(prompt, dict):
        return False
    pos_ids: set[str] = set()
    neg_ids: set[str] = set()
    for node in prompt.values():
        if not isinstance(node, dict) or node.get("class_type") != "CFGGuider":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        pos = inputs.get("positive")
        neg = inputs.get("negative")
        if isinstance(pos, list) and pos:
            pos_ids.add(str(pos[0]))
        if isinstance(neg, list) and neg:
            neg_ids.add(str(neg[0]))
    if not pos_ids and not neg_ids:
        return False
    for nid, node in prompt.items():
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        key = str(nid)
        if key in pos_ids:
            inputs["text"] = positive
        elif key in neg_ids:
            inputs["text"] = negative
    return True


def config_from_payload(
    body: dict[str, Any], extras_path: Path | None = None
) -> dict[str, Any]:
    """Parse Prompt Editor JSON into Config fields + selected LoRA ids."""
    prompt = body.get("prompt") if isinstance(body, dict) else None
    if not isinstance(prompt, dict):
        raise ValueError("request JSON missing 'prompt'")
    graph = "flux1"
    width, height, steps = 1024, 1024, 20
    prompt_text = ""
    negative_text = ""
    scheduler = "flux2"
    cfg_scale = 1
    pos_ids: set[str] = set()
    neg_ids: set[str] = set()
    for _nid, node in prompt.items():
        if not isinstance(node, dict) or node.get("class_type") != "CFGGuider":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        pos = inputs.get("positive")
        neg = inputs.get("negative")
        if isinstance(pos, list) and pos:
            pos_ids.add(str(pos[0]))
        if isinstance(neg, list) and neg:
            neg_ids.add(str(neg[0]))
    for nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        cls = node.get("class_type")
        if cls == "UNETLoader":
            unet = str(_node_input(node, "unet_name") or "")
            if "klein" in unet.lower():
                graph = "klein"
        elif cls == "EmptyFlux2LatentImage":
            graph = "klein"
            width = coerce_int(_node_input(node, "width"), width)
            height = coerce_int(_node_input(node, "height"), height)
        elif cls in ("EmptyLatentImage", "EmptySD3LatentImage"):
            width = coerce_int(_node_input(node, "width"), width)
            height = coerce_int(_node_input(node, "height"), height)
        elif cls == "Flux2Scheduler":
            scheduler = "flux2"
            steps = coerce_int(_node_input(node, "steps"), steps)
            width = coerce_int(_node_input(node, "width"), width)
            height = coerce_int(_node_input(node, "height"), height)
        elif cls == "BasicScheduler":
            scheduler = "simple"
            steps = coerce_int(_node_input(node, "steps"), steps)
        elif cls == "KSampler":
            steps = coerce_int(_node_input(node, "steps"), steps)
        elif cls == "CFGGuider":
            c = coerce_int(_node_input(node, "cfg"))
            if c is not None:
                cfg_scale = c
        elif cls == "CLIPTextEncode":
            text = str(_node_input(node, "text") or "")
            key = str(nid)
            if key in neg_ids:
                negative_text = text
            elif key in pos_ids:
                prompt_text = text
            elif len(text.strip()) > len(prompt_text.strip()):
                prompt_text = text
    selected_ids: list[str] = []
    unmatched: list[dict[str, Any]] = []
    for _key, node in sorted(prompt.items(), key=lambda kv: str(kv[0])):
        if not isinstance(node, dict) or node.get("class_type") != "LoraLoader":
            continue
        name = str(_node_input(node, "lora_name") or "")
        title = str((node.get("_meta") or {}).get("title") or "")
        item = ls.find_by_loader_name(name, extras_path)
        if item is None and title:
            item = ls.find_by_loader_name(title, extras_path)
        if item and item.get("id"):
            selected_ids.append(str(item["id"]))
        else:
            unmatched.append(
                {
                    "lora_name": ls.strip_civitai_token(name) if name else name,
                    "strength_model": float(_node_input(node, "strength_model") or 1),
                    "strength_clip": float(_node_input(node, "strength_clip") or 1),
                }
            )
    unet_name = UNET_BASE
    for node in prompt.values():
        if isinstance(node, dict) and node.get("class_type") == "UNETLoader":
            unet_name = normalize_unet(str(_node_input(node, "unet_name") or ""))
            break
    return {
        "graph": graph,
        "width": width,
        "height": height,
        "steps": steps,
        "scheduler": scheduler,
        "cfg": cfg_scale,
        "unet": unet_name,
        "prompt_text": prompt_text,
        "negative_text": negative_text,
        "selected_ids": selected_ids,
        "unmatched_loras": unmatched,
    }
