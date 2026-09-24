"""Convert Civitai Comfy workflow JSON + generation-data text to Salad /prompt JSON."""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent
for p in (_HERE, _TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import lora_store as ls  # noqa: E402
import request_json as rj  # noqa: E402

# Live SaveImage graph is kept. Muted/bypassed subgraph copies, notes, and
# nodes that nothing on that path depends on are dropped (image 123566519).
SKIP_TYPES: set[str] = set()
MUTED_MODES = {2, 4}  # Comfy NEVER / BYPASS
_OUTPUT_TYPES = {"SaveImage", "PreviewImage", "SaveImageWebsocket"}
POWER_LORA = "Power Lora Loader (rgthree)"
# Classes Salad Comfy 0.35 cannot instantiate. Generate omits them from the POST
# copy: prompt_for_salad_replica drops each one, except the three repaired in
# place by _rewrite_replica_missing_nodes (ReferenceLatent, ConditioningZeroOut,
# Color Correct GPU (mtb)).
SALAD_MISSING_TYPES = {
    "ZImageLatent",
    "ReferenceLatent",
    "ConditioningZeroOut",
    "MarkdownNote",
    "Note",
    "Color Correct GPU (mtb)",
    "PreviewImage",
    "Image Comparer (rgthree)",
    "Text Multiline",
    POWER_LORA,
    "Fast Groups Bypasser (rgthree)",
    "easy cleanGpuUsed",
    "ColorNoiseComfy",
}
_UUID_TYPE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

WIDGET_ORDER: dict[str, tuple[str, ...]] = {
    "KSamplerSelect": ("sampler_name",),
    "CFGGuider": ("cfg",),
    "VAELoader": ("vae_name",),
    "UNETLoader": ("unet_name", "weight_dtype"),
    "CLIPLoader": ("clip_name", "type", "device"),
    "Flux2Scheduler": ("steps", "width", "height"),
    "BasicScheduler": ("scheduler", "steps", "denoise"),
    "CLIPTextEncode": ("text",),
    "Text Multiline": ("text",),
    "RandomNoise": ("noise_seed",),
    "EmptyFlux2LatentImage": ("width", "height", "batch_size"),
    "EmptyLatentImage": ("width", "height", "batch_size"),
    "EmptySD3LatentImage": ("width", "height", "batch_size"),
    "SaveImage": ("filename_prefix",),  # date templates confuse Salad output pickup
    "VAEDecode": (),
    "SamplerCustomAdvanced": (),
    "ReferenceLatent": (),
    "ConditioningZeroOut": (),
    "LoraLoader": ("lora_name", "strength_model", "strength_clip"),
    # Model-only: no strength_clip widget, so the tuple is one shorter.
    "LoraLoaderModelOnly": ("lora_name", "strength_model"),
    "PrimitiveInt": ("value",),
    "PrimitiveFloat": ("value",),
    "PrimitiveString": ("value",),
    "KSampler": ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"),
    "CheckpointLoaderSimple": ("ckpt_name",),
    "CLIPSetLastLayer": ("stop_at_clip_layer",),
    "LoadImage": ("image",),
    "VAEEncode": (),
    "ResolutionOrientationNodeComfy": ("resolution", "percent", "orientation"),
    "ColorNoiseComfy": (),
}

# Comfy "control_after_generate" sits in widgets_values after seed.
_SEED_CONTROL = {"randomize", "fixed", "increment", "decrement"}

# Civitai trailer may omit Steps: (Sampler / Seed / Model only).
_TRAILER = re.compile(
    r"(?is)(?:^|\n)\s*(?:Steps|CFG(?:\s*scale)?|Sampler|Seed|Model|Size|Scheduler|Tools)\s*:"
)

TOOL_COMFY = "comfy"
TOOL_DRAW_THINGS = "draw_things"
TOOL_METADATA = "metadata"
_NEG = re.compile(r"(?is)(?:^|\n)\s*Negative prompt\s*:")
_LORA_TAG = re.compile(r"<lora:([^:>]+?)(?::([-\d.]+))?>", re.I)
_SCHEDULER_WORDS = (
    "simple",
    "karras",
    "exponential",
    "sgm_uniform",
    "normal",
    "ddim_uniform",
    "beta",
)
_SAMPLER_ALIASES = {
    "euler": "euler",
    "euler a": "euler_ancestral",
    "euler_ancestral": "euler_ancestral",
    "dpm++ 2s a": "dpmpp_2s_ancestral",
    "dpmpp_2s_ancestral": "dpmpp_2s_ancestral",
    "dpm++ 2m": "dpmpp_2m",
    "dpmpp_2m": "dpmpp_2m",
    "dpm++ sde": "dpmpp_sde",
    "dpm++ 2m sde": "dpmpp_2m_sde",
    "dpm2 a": "dpm_2_ancestral",
    "dpm2": "dpm_2",
    "heun": "heun",
    "lms": "lms",
    "ddim": "ddim",
    "uni pc": "uni_pc",
    "unipc": "uni_pc",
}
# Stock Comfy KSamplerSelect names (Salad 0.35 reports 45). Civitai sometimes
# stores SEEDS as ``seeds_3_`` with a trailing underscore.
_COMFY_SAMPLER_NAMES = frozenset(
    {
        *_SAMPLER_ALIASES.values(),
        "euler_cfg_pp",
        "euler_ancestral_cfg_pp",
        "heunpp2",
        "dpm_fast",
        "dpm_adaptive",
        "dpmpp_sde_gpu",
        "dpmpp_2m_sde",
        "dpmpp_2m_sde_gpu",
        "dpmpp_3m_sde",
        "dpmpp_3m_sde_gpu",
        "ddpm",
        "lcm",
        "ipndm",
        "ipndm_v",
        "deis",
        "uni_pc_bh2",
        "er_sde",
        "res_multistep",
        "res_multistep_ancestral",
        "gradient_estimation",
        "gradient_estimation_cfg_pp",
        "seeds_2",
        "seeds_3",
    }
)

CONVERT_OUTPUT = {
    "format": "jpeg",
    "options": {"quality": 90, "progressive": True},
}

# Distilled unet is prefetched next to base-9b. The small decoder VAE is not.
# Civitai Comfy graphs often load `…9b-fp8mixed.safetensors`; the replica only
# has `flux-2-klein-9b-fp8.safetensors` and `flux-2-klein-base-9b-fp8.safetensors`.
REPLICA_VAE = {
    "full_encoder_small_decoder.safetensors": "flux2-vae.safetensors",
}
REPLICA_UNET = {
    "flux-2-klein-9b-fp8mixed.safetensors": "flux-2-klein-9b-fp8.safetensors",
    "flux-2-klein-base-9b-fp8mixed.safetensors": (
        "flux-2-klein-base-9b-fp8.safetensors"
    ),
    "flux-2-klein-9b-nvfp4.safetensors": "flux-2-klein-9b-fp8.safetensors",
    "flux-2-klein-base-9b-nvfp4.safetensors": (
        "flux-2-klein-base-9b-fp8.safetensors"
    ),
}


def salad_filename(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return raw
    return raw.replace("\\", "/").rsplit("/", 1)[-1]


def _is_seed_control(val: Any) -> bool:
    return isinstance(val, str) and val.strip().lower() in _SEED_CONTROL


# Prefetched beside the official Klein fp8 files. The klein+fp8 heuristic
# would otherwise rewrite this name onto flux-2-klein-9b-fp8.
_REPLICA_UNET_KEEP = {
    "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors",
}


def replica_unet_name(name: str) -> str:
    """Basename, then map Civitai `fp8mixed` Klein files onto replica disk."""
    base = salad_filename(name)
    if base in _REPLICA_UNET_KEEP:
        return base
    mapped = REPLICA_UNET.get(base)
    if mapped:
        return mapped
    low = base.lower()
    if "klein" in low and ("fp8" in low or "nvfp4" in low):
        if "base" in low:
            return "flux-2-klein-base-9b-fp8.safetensors"
        return "flux-2-klein-9b-fp8.safetensors"
    return base


REPLICA_FAMILY = "Flux.2 Klein"
_INCOMPATIBLE_FAMILIES = {
    "Krea 2",
    "SDXL",
    "Pony",
    "Illustrious",
    "Flux.1 Dev",
    "Flux.1 D",
}


def weight_family(name: str) -> str:
    """Family of a UNET / VAE / LoRA filename or Civitai baseModel string."""
    raw = str(name or "").strip()
    if not raw:
        return ""
    fam = ls.normalize_family(raw)
    if fam in ls.FAMILY_LABELS:
        return ls.FAMILY_LABELS[fam]
    if fam in _INCOMPATIBLE_FAMILIES or fam == "Krea 2":
        return fam
    low = salad_filename(raw).lower().replace("_", " ").replace("-", " ")
    if "krea" in low:
        return "Krea 2"
    if "klein" in low:
        return "Flux.2 Klein"
    compact = low.replace(" ", "_")
    if "qwen_image_vae" in compact:
        return "Krea 2"
    return ""


def load_image_search_roots() -> list[Path]:
    roots: list[Path] = []
    for env in ("COMFYUI_INPUT", "COMFY_INPUT"):
        val = (os.environ.get(env) or "").strip()
        if val:
            roots.append(Path(val))
    roots.extend(
        [
            Path.cwd() / "input",
            Path.home() / "ComfyUI" / "input",
            Path.home() / "Documents" / "ComfyUI" / "input",
        ]
    )
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return out


def resolve_load_image(name: str) -> dict[str, Any]:
    """HTTP, a file on this PC, or the author's local Comfy input (unavailable)."""
    raw = str(name or "").strip()
    if not raw:
        return {"status": "empty"}
    if raw.startswith("http://") or raw.startswith("https://"):
        return {"status": "http", "path": raw}
    path = Path(raw)
    try:
        if path.is_file():
            return {"status": "local_found", "path": str(path.resolve())}
    except OSError:
        pass
    fn = salad_filename(raw)
    for root in load_image_search_roots():
        try:
            cand = root / fn
            if cand.is_file():
                return {"status": "local_found", "path": str(cand.resolve())}
        except OSError:
            continue
    return {"status": "author_missing", "filename": fn}


def _parse_sampler_field(raw: str) -> tuple[str, str | None]:
    """Civitai 'DPM++ 2S a simple' → Comfy sampler + optional scheduler.

    Trailing underscores (``seeds_3_``) are Civitai spelling of ``seeds_3``.
    Names Salad Comfy will reject become euler.
    """
    s = re.sub(r"\s+", " ", (raw or "").strip().lower()).rstrip("_")
    sched = None
    for word in _SCHEDULER_WORDS:
        if s == word or s.endswith(" " + word):
            sched = word
            s = s[: -len(word)].strip() if s != word else ""
            break
    if not s:
        return "euler", sched
    name = _SAMPLER_ALIASES.get(s)
    if not name:
        name = s.replace("++", "pp").replace("+", "p").replace(" ", "_").rstrip("_")
    if name not in _COMFY_SAMPLER_NAMES:
        name = "euler"
    return name, sched


def _tool_names(
    *,
    metadata_text: str = "",
    img: dict[str, Any] | None = None,
    tool_hint: str = "",
) -> str:
    names: list[str] = []
    if tool_hint:
        names.append(tool_hint)
    meta = parse_civitai_metadata(metadata_text) if metadata_text else {}
    if meta.get("tools"):
        names.append(str(meta["tools"]))
    if img:
        gen = ls.unwrap_image_generation(img)
        for row in gen.get("tools") or []:
            if isinstance(row, str):
                names.append(row)
            elif isinstance(row, dict) and row.get("name"):
                names.append(str(row["name"]))
    return " ".join(names).lower()


def _js_to_json(text: str) -> str:
    """Civitai sometimes emits JS ``undefined`` in the workflow field."""
    return re.sub(r":\s*undefined\b", ": null", text or "")


def comfy_node_count(obj: Any) -> int:
    """How many real Comfy nodes are in a parsed workflow / prompt object."""
    if not isinstance(obj, dict):
        return 0
    nodes = obj.get("nodes")
    if isinstance(nodes, list):
        return sum(1 for n in nodes if isinstance(n, dict) and (n.get("type") or n.get("class_type")))
    nested = obj.get("workflow")
    if isinstance(nested, dict):
        n = comfy_node_count(nested)
        if n:
            return n
    prompt = obj.get("prompt")
    if isinstance(prompt, dict):
        return sum(
            1
            for n in prompt.values()
            if isinstance(n, dict) and n.get("class_type")
        )
    return sum(1 for n in obj.values() if isinstance(n, dict) and n.get("class_type"))


def has_comfy_nodes(
    workflow_text: str = "", img: dict[str, Any] | None = None
) -> bool:
    """True when a paste or Civitai blob has at least one Comfy node.

    Tools: ComfyUI with an empty ``nodes`` list (or ``workflow: undefined``
    and no parseable prompt) is not Comfy — Convert uses the metadata path.
    """
    wf = (workflow_text or "").strip()
    if wf:
        obj = _parse_json_blob(wf) if wf[:1] in "{[" or "class_type" in wf or '"nodes"' in wf else None
        try:
            if obj is None and wf.startswith("{"):
                obj = json.loads(_js_to_json(wf))
        except json.JSONDecodeError:
            obj = None
        if comfy_node_count(obj) > 0:
            return True
        if obj is not None:
            return False
    if img:
        gen = ls.unwrap_image_generation(img)
        raw = gen.get("comfy")
        parsed = raw if isinstance(raw, dict) else None
        if isinstance(raw, str):
            try:
                parsed = json.loads(_js_to_json(raw))
            except json.JSONDecodeError:
                parsed = None
        if comfy_node_count(parsed) > 0:
            return True
        got = workflow_from_generation(gen)
        if got:
            try:
                if comfy_node_count(json.loads(_js_to_json(got))) > 0:
                    return True
            except json.JSONDecodeError:
                pass
    return False


def detect_import_tool(
    *,
    metadata_text: str = "",
    workflow_text: str = "",
    img: dict[str, Any] | None = None,
    tool_hint: str = "",
) -> str:
    """Pick an isolated Convert route. Comfy nodes win over Tools: Draw Things."""
    if has_comfy_nodes(workflow_text, img):
        return TOOL_COMFY
    blob = _tool_names(metadata_text=metadata_text, img=img, tool_hint=tool_hint)
    if "draw things" in blob:
        return TOOL_DRAW_THINGS
    return TOOL_METADATA


def map_draw_things_sampler(sampler: str, unet: str | None = None) -> str:
    """Draw Things sampler names → Salad Klein KSamplerSelect.

    Draw Things DPM++ SDE / Euler A Trailing are not Comfy ``dpmpp_sde`` /
    ``euler_ancestral``. Distilled Klein on Salad uses euler + Flux2Scheduler.
    """
    raw = re.sub(r"\s+", " ", (sampler or "").strip().lower())
    for word in ("trailing", "karras", "ays"):
        if raw.endswith(" " + word):
            raw = raw[: -len(word)].strip()
    name, _sched = _parse_sampler_field(raw) if raw else ("euler", None)
    if name in (
        "dpmpp_sde",
        "dpmpp_sde_gpu",
        "dpmpp_2m_sde",
        "dpmpp_2m_sde_gpu",
        "dpmpp_3m_sde",
        "euler_ancestral",
        "ddim",
    ):
        return "euler"
    mapped = rj.remap_distilled_sampler(name, unet)
    return mapped or "euler"


def _extract_lora_tags(prompt: str) -> tuple[str, list[dict[str, Any]]]:
    found: list[tuple[str, float]] = []

    def _keep(match: re.Match[str]) -> str:
        name = (match.group(1) or "").strip()
        strength = float(match.group(2) or 1)
        if name:
            found.append((name, strength))
        return ""

    text = _LORA_TAG.sub(_keep, prompt or "")
    text = re.sub(r"(?i)https?://(?:www\.)?civitai\.com/images/\d+\s*", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # Keep paste order, including duplicates (A1111 applies each occurrence).
    tags = [{"name": n, "strength": s} for n, s in found]
    return text, tags


def _http_lora_url(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    name = ls.comfy_lora_name(item)
    if name.startswith("http://") or name.startswith("https://"):
        return name
    dl = str((item.get("source") or {}).get("download") or "")
    if dl.startswith("http://") or dl.startswith("https://"):
        if item.get("verified") is True or ls._is_known_id(item.get("id")):
            return dl
    return ""


def _spec_from_item(
    item: dict[str, Any] | None,
    strength: float,
    name: str,
    missing: list[str],
    extras_path: Path | None = None,
) -> dict[str, Any] | None:
    if item:
        item = ls.ensure_civitai_version_name(item, extras_path=extras_path)
    url = _http_lora_url(item)
    if url:
        src = (item.get("source") or {}) if item else {}
        return {
            "id": item.get("id") if item else "",
            "lora_name": url,
            "filename": str(src.get("filename") or name),
            "tag": name,
            "version_name": ls.version_label(item) if item else "",
            "variation": ls.variation_label(item) if item else "",
            "verified": bool(item.get("verified")) if item else False,
            "strength_model": strength,
            "strength_clip": strength,
        }
    missing.append(name)
    return None


def _item_from_hint(
    name: str,
    strength: float,
    hint: dict[str, Any],
    extras_path: Path | None,
) -> dict[str, Any] | None:
    vid = hint.get("version_id")
    if not vid:
        return None
    try:
        return ls.add_lora(
            f"https://civitai.com/api/download/models/{vid}",
            extras_path=extras_path,
            name=name,
            filename=str(hint.get("filename") or "") or None,
            strength_model=strength,
            strength_clip=strength,
            base=str(hint.get("base") or "Flux.2 Klein") or "Flux.2 Klein",
            verified=True,
            verify=False,
            version_name=str(hint.get("version_name") or "") or None,
        )
    except (ValueError, SystemExit):
        return None


def resolve_prompt_loras(
    tags: list[dict[str, Any]],
    *,
    extras_path: Path | None = None,
    search: bool = True,
    hints: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Catalog lookup, then Civitai search + extras add. URLs only."""
    specs: list[dict[str, Any]] = []
    missing: list[str] = []
    pending: list[tuple[dict[str, Any], float, dict[str, Any] | None]] = []
    for tag in tags or []:
        name = str(tag.get("name") or "").strip()
        if not name:
            continue
        try:
            strength = float(tag.get("strength") or 1)
        except (TypeError, ValueError):
            strength = 1.0
        hint = (hints or {}).get(name)
        if hint and hint.get("version_id"):
            item = _item_from_hint(name, strength, hint, extras_path)
            spec = _spec_from_item(
                item, strength, name, missing, extras_path=extras_path
            )
            if spec:
                if hint.get("version_name"):
                    spec["version_name"] = hint["version_name"]
                spec["variation"] = ls.variation_label(
                    version_name=str(hint.get("version_name") or ""),
                    filename=str(hint.get("filename") or spec.get("filename") or ""),
                )
                specs.append(spec)
            continue
        item = ls.find_by_loader_name(name, extras_path)
        if item is None and not name.lower().endswith(".safetensors"):
            item = ls.find_by_loader_name(name + ".safetensors", extras_path)
        if item is not None:
            extras_hit = ls.civitai_hit_from_item(item)
            if not ls.is_tag_or_suffix(name, extras_hit):
                item = None
        unversioned = bool(item is not None and ls.looks_unversioned_filename(name, item))
        # Search when missing, or when an unverified exact-filename extra may have
        # a later suffix version (Klein-anime V1 → V3). Verified extras are used
        # as-is so Fill/Convert do not re-query Civitai for every tag.
        if search and (
            item is None or (unversioned and item.get("verified") is not True)
        ):
            pending.append(({"name": name, "strength": strength}, strength, item))
            continue
        if item is not None and item.get("verified") is not True:
            item = ls.verify_item(item, live=True)
            if item.get("verified") is True:
                ls.write_extra(item, extras_path)
        spec = _spec_from_item(
            item, strength, name, missing, extras_path=extras_path
        )
        if spec:
            specs.append(spec)
    if pending:
        unique: list[str] = []
        seen: set[str] = set()
        for tag, _strength, _extras in pending:
            q = tag["name"]
            if q not in seen:
                seen.add(q)
                unique.append(q)
        with ThreadPoolExecutor(max_workers=min(8, len(unique))) as pool:
            futs = {name: pool.submit(ls.civitai_search_lora, name) for name in unique}
            hits: dict[str, dict[str, Any] | None] = {}
            for name, fut in futs.items():
                try:
                    hits[name] = fut.result()
                except Exception:
                    hits[name] = None
        for tag, strength, extras_item in pending:
            name = tag["name"]
            hit = hits.get(name)
            extras_hit = ls.civitai_hit_from_item(extras_item)
            chosen = ls.prefer_civitai_hit(name, extras_hit, hit)
            item = extras_item
            use_search = chosen is not None and chosen is not extras_hit
            if use_search and hit:
                try:
                    item = ls.add_lora(
                        str(hit.get("page") or hit.get("download") or ""),
                        extras_path=extras_path,
                        name=name,
                        filename=str(hit.get("filename") or "") or None,
                        strength_model=strength,
                        strength_clip=strength,
                        base="Flux.2 Klein",
                        verified=True,
                        verify=False,
                        version_name=str(hit.get("version_name") or "") or None,
                    )
                except (ValueError, SystemExit):
                    item = extras_item
            elif item is not None and item.get("verified") is not True:
                item = ls.verify_item(item, live=True)
                if item.get("verified") is True:
                    ls.write_extra(item, extras_path)
            spec = _spec_from_item(
                item, strength, name, missing, extras_path=extras_path
            )
            if spec:
                specs.append(spec)
    return specs, missing


def _hint_for_lora_name(
    name: str, hints: dict[str, dict[str, Any]] | None
) -> dict[str, Any] | None:
    """Match a Comfy local filename to Civitai Resources hints.

    Image 122279320 stores ``DarkAtmospheric01a_CE_…safetensors`` in the
    graph but Resources name the same LoRA ``Dark Atmospheric Style - CE``.
    """
    if not hints:
        return None
    raw = (name or "").strip()
    if raw in hints:
        return hints[raw]
    stem = Path(salad_filename(raw)).stem
    if stem in hints:
        return hints[stem]
    for key, hint in hints.items():
        if not isinstance(hint, dict):
            continue
        if _same_lora_tag(stem, key) or _same_lora_tag(stem, str(hint.get("filename") or "")):
            return hint
        if _same_lora_tag(stem, str(hint.get("model_name") or "")):
            return hint
    usable = [h for h in hints.values() if isinstance(h, dict) and h.get("version_id")]
    if len(usable) == 1:
        return usable[0]
    return None


def resolve_local_lora_nodes(
    prompt: dict[str, Any],
    extras_path: Path | None = None,
    hints: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Replace local ``lora_name`` filenames with Civitai download URLs.

    Unresolved LoRAs stay in the editor; Generate looks them up again.
    """
    missing: list[str] = []
    for node, name in rj.lora_name_inputs(prompt):
        if not name or name.startswith("http://") or name.startswith("https://"):
            continue
        inputs = node.setdefault("inputs", {})
        fname = salad_filename(name)
        stem = Path(fname).stem
        try:
            strength = float(inputs.get("strength_model") or 1)
        except (TypeError, ValueError):
            strength = 1.0
        bound = dict(hints or {})
        hit = _hint_for_lora_name(stem, hints)
        if hit and stem not in bound:
            bound[stem] = hit
        specs, miss = resolve_prompt_loras(
            [{"name": stem, "strength": strength}],
            extras_path=extras_path,
            search=True,
            hints=bound,
        )
        url = str((specs[0] if specs else {}).get("lora_name") or "")
        if url.startswith("http://") or url.startswith("https://"):
            inputs["lora_name"] = url
            meta = rj.weight_meta(specs[0])
            if meta:
                node["_meta"] = {**(node.get("_meta") or {}), **meta}
            continue
        missing.extend(miss or [fname])
    return missing


def _next_node_id(prompt: dict[str, Any]) -> int:
    n = 0
    for key in prompt:
        try:
            n = max(n, int(key))
        except (TypeError, ValueError):
            continue
    return n + 1 if n else 80


def _prompt_has_lora(prompt: dict[str, Any]) -> bool:
    return any(
        isinstance(node, dict) and node.get("class_type") == "LoraLoader"
        for node in prompt.values()
    )


def inject_resource_loras(
    prompt: dict[str, Any],
    *,
    tags: list[dict[str, Any]] | None,
    extras_path: Path | None = None,
    hints: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Insert Civitai Resources LoRAs when the saved Comfy graph has none.

    Civitai image 134347427 lists MJ Style Distilled 206 (2912075) in
    Resources-used, but the 14-node workflow is an img2img edit with no
    LoraLoader. Convert follows the graph unless we add those rows.
    """
    if not isinstance(prompt, dict) or _prompt_has_lora(prompt):
        return []
    tags = list(tags or [])
    if not tags:
        return []
    specs, missing = resolve_prompt_loras(
        tags, extras_path=extras_path, search=True, hints=hints
    )
    if not specs:
        return missing
    unet: str | None = None
    clip: str | None = None
    for nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        cls = node.get("class_type")
        if cls == "UNETLoader" and unet is None:
            unet = str(nid)
        elif cls == "CLIPLoader" and clip is None:
            clip = str(nid)
    if unet is None:
        return missing
    start = _next_node_id(prompt)
    last_model, last_clip = rj.attach_lora_chain(
        prompt,
        model_ref=[unet, 0],
        clip_ref=[clip, 0] if clip is not None else ["71", 0],
        loras=specs,
        start_id=start,
    )
    new_ids = {str(start + i) for i in range(len(specs))}
    for nid, node in prompt.items():
        if not isinstance(node, dict) or str(nid) in new_ids:
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key, val in list(inputs.items()):
            edge = _edge(val)
            if not edge:
                continue
            if edge[0] == unet and edge[1] == 0:
                inputs[key] = list(last_model)
            elif clip is not None and edge[0] == clip and edge[1] == 0:
                inputs[key] = list(last_clip)
    return missing


def resource_order_tags(
    item: dict[str, Any] | None,
    hints: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Unique LoRAs in Civitai Resources-used order (``modelVersionIds``).

    Draw Things posts often have empty ids; then use ``resources[]`` rows
    from tRPC / page scrape. Weights: first ``resources[].weight`` else 1.
    Checkpoint ids that are not LoRAs are skipped.
    """
    if not isinstance(item, dict):
        return None
    gen = ls.unwrap_image_generation(item)
    ver_to_tag: dict[int, str] = {}
    for tag, hint in (hints or {}).items():
        try:
            vid = int(hint.get("version_id"))
        except (TypeError, ValueError):
            continue
        if tag and vid:
            ver_to_tag[vid] = tag
    first_w: dict[str, float] = {}
    res_order: list[str] = []
    for row in ls.generation_resource_rows(gen):
        if not isinstance(row, dict):
            continue
        kind = str(row.get("type") or row.get("modelType") or "").lower()
        if "lora" not in kind:
            continue
        vid = row.get("modelVersionId") or row.get("versionId")
        try:
            vid_i = int(vid) if vid is not None else None
        except (TypeError, ValueError):
            vid_i = None
        name = str(row.get("name") or row.get("modelName") or "").strip()
        if not name and vid_i is not None:
            name = str(vid_i)
        if not name:
            continue
        if vid_i and name:
            ver_to_tag.setdefault(vid_i, name)
        if name not in first_w:
            res_order.append(name)
            weight = row.get("weight")
            if weight is None:
                weight = row.get("strength")
            if weight is None:
                first_w[name] = 1.0
            else:
                try:
                    first_w[name] = float(weight)
                except (TypeError, ValueError):
                    first_w[name] = 1.0
        elif row.get("weight") is not None and first_w.get(name) == 1.0:
            try:
                first_w[name] = float(row["weight"])
            except (TypeError, ValueError):
                pass
    ids = item.get("modelVersionIds")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(ids, list) and ids and ver_to_tag:
        for raw_id in ids:
            try:
                vid = int(raw_id)
            except (TypeError, ValueError):
                continue
            tag = ver_to_tag.get(vid)
            if not tag or tag in seen:
                continue
            seen.add(tag)
            out.append({"name": tag, "strength": first_w.get(tag, 1.0)})
        if out:
            return out
    for name in res_order:
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "strength": first_w.get(name, 1.0)})
    return out or None


def _lora_tag_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _same_lora_tag(a: str, b: str) -> bool:
    ka, kb = _lora_tag_key(a), _lora_tag_key(b)
    if not ka or not kb:
        return False
    return ka == kb or ka in kb or kb in ka


def non_comfy_lora_tags(
    meta: dict[str, Any] | None,
    img: dict[str, Any] | None,
    hints: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Site Resources-used order, then extra prompt LoRAs not on the chips.

    Non-Comfy Convert (image 130704037): 1) read Resources list, 2) resolve
    extras from ``<lora:…>`` / hashes, 3) build the Klein chain in that order.
    """
    paste = list((meta or {}).get("lora_tags") or [])
    site = resource_order_tags(img, hints) if img else None
    if not site:
        return paste
    out: list[dict[str, Any]] = []
    used: set[int] = set()
    for row in site:
        tag = dict(row)
        for i, extra in enumerate(paste):
            if i in used:
                continue
            if not _same_lora_tag(str(tag.get("name") or ""), str(extra.get("name") or "")):
                continue
            if extra.get("strength") is not None:
                try:
                    tag["strength"] = float(extra["strength"])
                except (TypeError, ValueError):
                    pass
            used.add(i)
            break
        out.append(tag)
    for i, extra in enumerate(paste):
        if i in used:
            continue
        name = str(extra.get("name") or "")
        if any(_same_lora_tag(name, str(t.get("name") or "")) for t in out):
            continue
        out.append(dict(extra))
    return out


def parse_civitai_metadata(text: str) -> dict[str, Any]:
    """Parse Civitai 'generation data' (prompt + Negative prompt + Steps/CFG/…).

    Trailer-only lines (``Sampler: Euler, Seed: …, Model: …`` with no
    ``Steps:``) are metadata, not a prompt. JSON blobs mixed into the
    paste are stripped so they never become CLIP text. ``<lora:name:w>``
    tags are lifted out of the prompt.
    """
    raw = _strip_json_objects((text or "").strip())
    if not raw:
        return {}
    prompt = raw
    negative = ""
    rest = ""
    n = _NEG.search(raw)
    t = _TRAILER.search(raw)
    if n and (t is None or n.start() < t.start()):
        prompt = raw[: n.start()].strip()
        after_neg = raw[n.end() :].strip()
        t2 = _TRAILER.search(after_neg)
        if t2:
            negative = after_neg[: t2.start()].strip()
            rest = after_neg[t2.start() :].strip()
        else:
            negative = after_neg
    elif t:
        prompt = raw[: t.start()].strip()
        rest = raw[t.start() :].strip()
    blob = rest or (raw if not n else rest)
    out: dict[str, Any] = {}
    prompt, lora_tags = _extract_lora_tags(prompt)
    if lora_tags:
        out["lora_tags"] = lora_tags
    if prompt and not _TRAILER.match(prompt) and not _NEG.match(prompt):
        out["prompt"] = prompt
    if negative:
        out["negative"] = negative

    def grab(pat: str) -> str | None:
        mm = re.search(pat, blob, re.I)
        return mm.group(1).strip() if mm else None

    steps = grab(r"Steps:\s*([\d.]+)")
    if steps:
        out["steps"] = int(float(steps))
    cfg = grab(r"CFG(?:\s*scale)?:\s*([\d.]+)")
    if cfg:
        out["cfg"] = float(cfg) if "." in cfg else int(cfg)
    sampler = grab(r"Sampler:\s*([^,\n]+)")
    if sampler:
        sname, sched = _parse_sampler_field(sampler)
        out["sampler"] = sname
        if sched:
            out["scheduler"] = sched
    seed = grab(r"Seed:\s*([-\d]+)")
    if seed:
        out["seed"] = int(seed)
    model = grab(r"Model:\s*([^\n,]+)")
    if model and "hash" not in model.lower():
        fn = salad_filename(model)
        if fn and not fn.lower().endswith(".safetensors"):
            fn += ".safetensors"
        out["model"] = fn
    scheduler = grab(r"Scheduler:\s*([^,\n]+)")
    if scheduler:
        out["scheduler"] = scheduler.lower().strip()
    width = grab(r"Size:\s*(\d+)\s*[x×]\s*\d+")
    height = grab(r"Size:\s*\d+\s*[x×]\s*(\d+)")
    if not width:
        width = grab(r"\bwidth:\s*(\d+)")
    if not height:
        height = grab(r"\bheight:\s*(\d+)")
    if width:
        out["width"] = int(width)
    if height:
        out["height"] = int(height)
    tools = grab(r"Tools:\s*([^,\n]+)")
    if tools:
        out["tools"] = tools.strip()
    res_line = re.search(r"^Civitai resources:\s*(.+)$", raw, re.I | re.M)
    if res_line:
        rows: list[dict[str, str]] = []
        for chunk in res_line.group(1).split(";"):
            bits = [b.strip() for b in chunk.split("|")]
            if len(bits) < 2:
                continue
            rows.append(
                {
                    "type": bits[0],
                    "name": bits[1],
                    "family": bits[2] if len(bits) > 2 else "",
                }
            )
        if rows:
            out["resources"] = rows
    if out.get("prompt"):
        draw = "draw things" in str(out.get("tools") or "").lower()
        if draw or _has_artificeal(lora_tags):
            out["prompt"] = expand_truncated_cover_prompt(
                str(out["prompt"]),
                has_artificeal=_has_artificeal(lora_tags) or draw,
            )
    return out


def _node_map(workflow: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        try:
            nid = int(node.get("id"))
        except (TypeError, ValueError):
            continue
        out[nid] = node
    return out


def _links_by_id(workflow: dict[str, Any]) -> dict[int, list[Any]]:
    """Index list-style and dict-style Comfy links (subgraphs use dicts)."""
    out: dict[int, list[Any]] = {}
    for row in workflow.get("links") or []:
        lid = _link_id(row)
        try:
            lid_i = int(lid)
        except (TypeError, ValueError):
            continue
        if isinstance(row, (list, tuple)) and len(row) >= 5:
            out[lid_i] = list(row)
        elif isinstance(row, dict):
            o, os_ = _link_src(row)
            t, ts = _link_dst(row)
            out[lid_i] = [lid_i, o, os_, t, ts, row.get("type")]
    return out


def _primitive_value(node: dict[str, Any]) -> Any:
    widgets = node.get("widgets_values") or []
    if widgets:
        return widgets[0]
    return None


def _lora_name_for_file(filename: str) -> str:
    item = ls.find_by_loader_name(filename)
    if item:
        return ls.comfy_lora_name(item)
    return salad_filename(filename)


def _power_lora_specs(node: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for item in node.get("widgets_values") or []:
        if not isinstance(item, dict) or "lora" not in item:
            continue
        if item.get("on") is False:
            continue
        name = str(item.get("lora") or "").strip()
        if not name:
            continue
        strength = float(item.get("strength") if item.get("strength") is not None else 1)
        two = item.get("strengthTwo")
        clip = float(two) if two is not None else strength
        item = ls.find_by_loader_name(name)
        specs.append(
            {
                "lora_name": _lora_name_for_file(name),
                "filename": salad_filename(name),
                "tag": Path(salad_filename(name)).stem,
                "verified": bool(item.get("verified")) if item else False,
                "strength_model": strength,
                "strength_clip": clip,
            }
        )
    return specs


def _widget_inputs(node: dict[str, Any]) -> dict[str, Any]:
    ntype = str(node.get("type") or "")
    names = WIDGET_ORDER.get(ntype, ())
    widgets = list(node.get("widgets_values") or [])
    # Skip rgthree/header objects in widget list
    flat: list[Any] = []
    for w in widgets:
        if isinstance(w, dict):
            continue
        if _is_seed_control(w):
            continue
        flat.append(w)
    out: dict[str, Any] = {}
    for i, name in enumerate(names):
        if i >= len(flat):
            break
        val = flat[i]
        if name in ("unet_name", "clip_name", "vae_name", "ckpt_name"):
            val = salad_filename(str(val))
        elif name == "lora_name":
            # A LoraLoader widget may already hold a Civitai download URL — that is
            # what Studio writes, and what a saved Comfy graph of ours contains.
            # salad_filename keeps only the text after the last "/", which reduces
            # ".../download/models/2625692" to "2625692": not a URL, so nothing
            # resolves and Generate never attaches the token. Basename local paths
            # only. (2026-09-22)
            text = str(val).strip()
            if not text.lower().startswith(("http://", "https://")):
                val = salad_filename(text)
        if name == "value" and ntype == "PrimitiveInt":
            val = rj.coerce_int(val, val)
        if name == "noise_seed":
            try:
                val = int(val)
            except (TypeError, ValueError):
                pass
        if name == "filename_prefix":
            s = str(val)
            if "%" in s or "/" in s or "\\" in s:
                val = "klein"
        out[name] = val
    return out


def _node_muted(node: dict[str, Any]) -> bool:
    """Comfy mode 2 = never, 4 = bypass — not part of the live graph."""
    try:
        return int(node.get("mode") or 0) in MUTED_MODES
    except (TypeError, ValueError):
        return False


def workflow_to_prompt(workflow: dict[str, Any]) -> dict[str, Any]:
    """Comfy editor workflow (nodes/links) → API ``prompt`` graph."""
    nodes = _node_map(workflow)
    links = _links_by_id(workflow)
    power_ids: set[int] = set()
    for nid, node in nodes.items():
        ntype = str(node.get("type") or "")
        if ntype == POWER_LORA:
            power_ids.add(nid)

    prompt: dict[str, Any] = {}
    lora_out: dict[int, tuple[list[Any], list[Any]]] = {}

    for nid, node in nodes.items():
        ntype = str(node.get("type") or "")
        if ntype == POWER_LORA or _node_muted(node):
            continue
        inputs: dict[str, Any] = _widget_inputs(node)
        dest_slots = [inp for inp in (node.get("inputs") or []) if isinstance(inp, dict)]
        for slot, inp in enumerate(dest_slots):
            link_id = inp.get("link")
            if link_id is None:
                continue
            row = links.get(int(link_id))
            if not row:
                continue
            src_id, src_slot = int(row[1]), int(row[2])
            name = str(inp.get("name") or f"input_{slot}")
            if src_id in power_ids:
                # Rewired after the LoRA chain is inserted.
                inputs[name] = ["__power__", src_slot, src_id]
                continue
            inputs[name] = [str(src_id), src_slot]
        key = str(nid)
        prompt[key] = {"class_type": ntype, "inputs": inputs}

    # Replace each Power Lora Loader with a LoraLoader chain.
    for nid, node in nodes.items():
        if str(node.get("type") or "") != POWER_LORA or _node_muted(node):
            continue
        specs = _power_lora_specs(node)
        dest_slots = [inp for inp in (node.get("inputs") or []) if isinstance(inp, dict)]
        model_ref: list[Any] | None = None
        clip_ref: list[Any] | None = None
        for inp in dest_slots:
            row = links.get(int(inp["link"])) if inp.get("link") is not None else None
            if not row:
                continue
            ref = [str(int(row[1])), int(row[2])]
            if inp.get("name") == "model":
                model_ref = ref
            elif inp.get("name") == "clip":
                clip_ref = ref
        if model_ref is None:
            model_ref = ["70", 0]
        if clip_ref is None:
            clip_ref = ["71", 0]
        if not specs:
            lora_out[nid] = (model_ref, clip_ref)
            continue
        chain_id = nid
        model, clip = list(model_ref), list(clip_ref)
        for i, spec in enumerate(specs):
            key = str(chain_id if i == 0 else f"{nid}{i}")
            node: dict[str, Any] = {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": model,
                    "clip": clip,
                    "lora_name": spec["lora_name"],
                    "strength_model": spec["strength_model"],
                    "strength_clip": spec["strength_clip"],
                },
            }
            meta = rj.weight_meta(spec)
            if meta:
                node["_meta"] = meta
            prompt[key] = node
            model = [key, 0]
            clip = [key, 1]
        lora_out[nid] = (model, clip)

    for node in prompt.values():
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for k, v in list(inputs.items()):
            if isinstance(v, list) and v and v[0] == "__power__":
                src_slot, src_id = int(v[1]), int(v[2])
                model, clip = lora_out.get(src_id, (["70", 0], ["71", 0]))
                inputs[k] = clip if src_slot == 1 else model

    if not prompt:
        raise ValueError("Comfy workflow has no convertible nodes")
    return prompt


def apply_metadata(body: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    prompt = body.get("prompt")
    if not isinstance(prompt, dict) or not meta:
        return body
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        cls = node.get("class_type")
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        if cls == "CLIPTextEncode":
            continue
        elif cls == "CFGGuider" and "cfg" in meta:
            inputs["cfg"] = meta["cfg"]
        elif cls == "KSamplerSelect" and "sampler" in meta:
            name, _ = _parse_sampler_field(str(meta["sampler"]))
            inputs["sampler_name"] = name
        elif cls == "RandomNoise" and "seed" in meta:
            inputs["noise_seed"] = meta["seed"]
        elif cls == "KSampler":
            if "seed" in meta:
                inputs["seed"] = meta["seed"]
            if "steps" in meta:
                inputs["steps"] = meta["steps"]
            if "cfg" in meta:
                inputs["cfg"] = meta["cfg"]
            if "sampler" in meta:
                name, _ = _parse_sampler_field(str(meta["sampler"]))
                inputs["sampler_name"] = name
        elif cls in ("Flux2Scheduler", "BasicScheduler"):
            if "steps" in meta:
                inputs["steps"] = meta["steps"]
            if cls == "BasicScheduler" and "scheduler" in meta:
                inputs["scheduler"] = meta["scheduler"]
            if "width" in meta:
                inputs["width"] = meta["width"]
            if "height" in meta:
                inputs["height"] = meta["height"]
        elif cls in (
            "EmptyFlux2LatentImage",
            "EmptyLatentImage",
            "EmptySD3LatentImage",
        ):
            if "width" in meta:
                inputs["width"] = meta["width"]
            if "height" in meta:
                inputs["height"] = meta["height"]
        elif cls == "UNETLoader" and "model" in meta:
            name = salad_filename(str(meta["model"]))
            if name.endswith(".safetensors") or "klein" in name.lower():
                inputs["unet_name"] = name if "base" in name.lower() else rj.normalize_unet(name)
    _assign_clip_texts(prompt, meta)
    return body


def _assign_clip_texts(prompt: dict[str, Any], meta: dict[str, Any]) -> None:
    """Write prompt/negative onto CLIP encodes using CFGGuider wires, not length.

    A long Civitai negative (anatomy dump) used to sort into the positive slot.
    """
    pos_ids: set[str] = set()
    neg_ids: set[str] = set()
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") not in ("CFGGuider", "KSampler"):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        for key, bucket in (("positive", pos_ids), ("negative", neg_ids)):
            edge = _edge(inputs.get(key))
            if edge:
                bucket.add(edge[0])
    pos_enc: list[dict[str, Any]] = []
    neg_enc: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for nid, node in prompt.items():
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        title = str((node.get("_meta") or {}).get("title") or "").lower()
        if str(nid) in pos_ids or "positive" in title:
            pos_enc.append(inputs)
        elif str(nid) in neg_ids or "negative" in title:
            neg_enc.append(inputs)
        else:
            other.append(inputs)
    if not pos_enc and not neg_enc and other:
        other.sort(key=lambda inp: len(str(inp.get("text") or "")), reverse=True)
        pos_enc = other[:1]
        neg_enc = other[1:2]
    if meta.get("prompt") and pos_enc:
        pos_enc[0]["text"] = str(meta["prompt"])
    if meta.get("negative") is not None and neg_enc:
        neg_enc[0]["text"] = str(meta.get("negative") or "")


def _is_graph_obj(obj: Any) -> bool:
    return isinstance(obj, dict) and (
        "nodes" in obj or isinstance(obj.get("prompt"), dict)
    )


def _iter_json_objects(text: str):
    """Yield ``(obj, start, end)`` for each JSON value, ignoring Extra data."""
    raw = text or ""
    decoder = json.JSONDecoder()
    i = 0
    n = len(raw)
    while i < n:
        while i < n and raw[i] not in "{[":
            i += 1
        if i >= n:
            return
        try:
            obj, end = decoder.raw_decode(raw, i)
        except json.JSONDecodeError:
            i += 1
            continue
        yield obj, i, end
        i = end


def _strip_json_objects(text: str) -> str:
    """Drop JSON values so leftover text is generation data / prompt."""
    raw = text or ""
    keep: list[str] = []
    last = 0
    for _obj, start, end in _iter_json_objects(raw):
        keep.append(raw[last:start])
        last = end
    keep.append(raw[last:])
    return "".join(keep).strip()


def _first_graph_json_text(text: str) -> str:
    raw = text or ""
    for obj, start, end in _iter_json_objects(raw):
        if _is_graph_obj(obj):
            return raw[start:end]
    return ""


def _parse_json_blob(text: str) -> Any:
    """Parse the first Comfy workflow / Salad prompt object in *text*.

    Civitai copies often have a valid ``{nodes:…}`` object followed by
    another JSON blob or trailing junk — ``json.loads`` then raises
    ``Extra data``. Prefix lines (``Sampler: Euler, Seed: …``) are skipped.
    """
    raw = _js_to_json((text or "").strip())
    if not raw:
        return None
    found: list[Any] = []
    for obj, _start, _end in _iter_json_objects(raw):
        if _is_graph_obj(obj):
            return obj
        found.append(obj)
    if found:
        return found[0]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise


# Civitai 135440425 stores only the Artificeal trigger + a stool sentence.
# Convert of that text paints abstract washes (no overalls, no landscape).
# The cover scene CLIP is what produced the closer Salad plate.
ARTIFICEAL_COVER_PROMPT = (
    "Artificeal style artwork. Graphite sketch layer and abstract color layer. "
    "The artwork presents a rear-view, slightly elevated perspective of a woman "
    "seated on a wooden stool, facing a canvas with her bare feet resting on "
    "the lower rungs of the stool."
)
ARTIFICEAL_COVER_CLIP = (
    "Artificeal style artwork. Graphite sketch layer and abstract color layer. "
    "Rear view, slightly elevated, a woman with a short bob seated on a wooden "
    "stool, wearing cream overalls with back pockets over a black camisole, "
    "bare feet on the stool rungs, holding a paintbrush, painting a watercolor "
    "landscape of hills, trees and water on a canvas on a wooden easel, "
    "ARTIFICEAL lettering at the bottom, cream paper."
)


def _norm_prompt(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _has_artificeal(gen_or_tags: Any) -> bool:
    if isinstance(gen_or_tags, dict):
        blob = json.dumps(gen_or_tags).lower()
        return "artificeal" in blob
    if isinstance(gen_or_tags, list):
        return any(
            "artificeal" in str((t or {}).get("name") or "").lower()
            for t in gen_or_tags
            if isinstance(t, dict)
        )
    return "artificeal" in str(gen_or_tags or "").lower()


def expand_truncated_cover_prompt(prompt: str, *, has_artificeal: bool) -> str:
    """Replace the 135440425 trigger-only CLIP with the cover scene."""
    if not has_artificeal:
        return prompt
    if _norm_prompt(prompt) != _norm_prompt(ARTIFICEAL_COVER_PROMPT):
        return prompt
    return ARTIFICEAL_COVER_CLIP


def _parse_comfy_field(gen: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(gen, dict):
        return None
    comfy = gen.get("comfy")
    if isinstance(comfy, str) and comfy.strip().startswith("{"):
        try:
            comfy = json.loads(comfy)
        except json.JSONDecodeError:
            return None
    return comfy if isinstance(comfy, dict) else None


def _clip_text_from_comfy(gen: dict[str, Any] | None) -> str:
    """Positive CLIP text when Copy All omits a prompt (Civitai stores it in comfy)."""
    obj = _parse_comfy_field(gen)
    if not obj:
        return ""
    texts: list[str] = []
    prompt_map = obj.get("prompt") if isinstance(obj.get("prompt"), dict) else None
    if prompt_map:
        for node in prompt_map.values():
            if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
                continue
            t = str((node.get("inputs") or {}).get("text") or "").strip()
            if t:
                texts.append(t)
    ui = _ui_workflow(obj)
    if ui:
        for node in ui.get("nodes") or []:
            if not isinstance(node, dict) or node.get("type") != "CLIPTextEncode":
                continue
            w = node.get("widgets_values") or []
            if w and str(w[0] or "").strip():
                texts.append(str(w[0]).strip())
    return max(texts, key=len) if texts else ""


def generation_data_from_image(item: dict[str, Any]) -> str:
    """Rebuild A1111 generation-data text from ``withMeta`` image JSON."""
    gen = ls.unwrap_image_generation(item)
    prompt = str(gen.get("prompt") or "").strip() or _clip_text_from_comfy(gen)
    prompt = expand_truncated_cover_prompt(
        prompt, has_artificeal=_has_artificeal(gen)
    )
    if "<lora:" not in prompt:
        bits: list[str] = []
        for row in ls.generation_resource_rows(gen):
            if not isinstance(row, dict):
                continue
            kind = str(row.get("type") or row.get("modelType") or "").lower()
            if "lora" not in kind:
                continue
            vid = row.get("modelVersionId") or row.get("versionId")
            try:
                vid_i = int(vid) if vid is not None else None
            except (TypeError, ValueError):
                vid_i = None
            name = str(row.get("name") or row.get("modelName") or "").strip()
            if not name and vid_i is not None:
                name = str(vid_i)
            if not name:
                continue
            weight = row.get("weight")
            if weight is None:
                weight = row.get("strength")
            try:
                w = float(weight) if weight is not None else 1.0
            except (TypeError, ValueError):
                w = 1.0
            bits.append(f"<lora:{name}:{w:g}>")
        if bits:
            prompt = prompt + "\n" + " ".join(bits)
    iid = item.get("id")
    neg = str(gen.get("negativePrompt") or "").strip()
    parts: list[str] = []
    if prompt:
        parts.append(
            f"https://civitai.com/images/{iid}\n{prompt}" if iid else prompt
        )
    elif iid:
        parts.append(f"https://civitai.com/images/{iid}")
    if neg:
        parts.append("Negative prompt: " + neg)
    trailer = []
    if gen.get("steps") is not None:
        trailer.append(f"Steps: {gen.get('steps')}")
    if gen.get("cfgScale") is not None:
        trailer.append(f"CFG scale: {gen.get('cfgScale')}")
    if gen.get("sampler"):
        trailer.append(f"Sampler: {gen.get('sampler')}")
    if gen.get("seed") is not None:
        trailer.append(f"Seed: {gen.get('seed')}")
    model = gen.get("Model")
    if not model:
        for row in gen.get("resources") or []:
            if not isinstance(row, dict):
                continue
            kind = str(row.get("type") or row.get("modelType") or "").lower()
            if "checkpoint" not in kind:
                continue
            model = row.get("name") or row.get("modelName")
            if model:
                break
    if model:
        trailer.append(f"Model: {model}")
    width = gen.get("width") if gen.get("width") not in (None, "") else item.get("width")
    height = gen.get("height") if gen.get("height") not in (None, "") else item.get("height")
    if width:
        trailer.append(f"width: {width}")
    if height:
        trailer.append(f"height: {height}")
    if gen.get("Model hash"):
        trailer.append(f"Model hash: {gen.get('Model hash')}")
    tools = gen.get("tools")
    labels: list[str] = []
    if isinstance(tools, list):
        for row in tools:
            if isinstance(row, str) and row.strip():
                labels.append(row.strip())
            elif isinstance(row, dict) and row.get("name"):
                labels.append(str(row["name"]).strip())
    if labels:
        trailer.append("Tools: " + ", ".join(labels))
    if trailer:
        parts.append(", ".join(str(x) for x in trailer))
    res_bits: list[str] = []
    for row in ls.generation_resource_rows(gen):
        kind = str(row.get("type") or row.get("modelType") or "").lower()
        if "lora" in kind:
            rtype = "lora"
        elif "checkpoint" in kind or "checkpoint" in str(row.get("modelType") or "").lower():
            rtype = "checkpoint"
        else:
            continue
        vid = row.get("modelVersionId") or row.get("versionId")
        try:
            vid_i = int(vid) if vid is not None else None
        except (TypeError, ValueError):
            vid_i = None
        rname = str(row.get("name") or row.get("modelName") or "").strip()
        if not rname and vid_i is not None:
            rname = str(vid_i)
        if not rname:
            continue
        rfam = weight_family(str(row.get("baseModel") or row.get("base") or rname))
        res_bits.append(f"{rtype}|{rname}|{rfam}")
    if res_bits:
        parts.append("Civitai resources: " + "; ".join(res_bits))
    return "\n".join(parts)


def _ui_workflow(obj: dict[str, Any] | None) -> dict[str, Any] | None:
    """Prefer Comfy UI ``{nodes, links}`` (Copy All) over API ``{prompt: {id: node}}``."""
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("nodes"), list) and obj.get("nodes"):
        return obj
    nested = obj.get("workflow")
    if isinstance(nested, dict) and isinstance(nested.get("nodes"), list):
        return nested
    comfy = obj.get("comfy")
    if isinstance(comfy, dict):
        return _ui_workflow(comfy)
    if isinstance(comfy, str) and comfy.strip().startswith("{"):
        try:
            return _ui_workflow(json.loads(_js_to_json(comfy)))
        except json.JSONDecodeError:
            return None
    return None


def expand_power_lora_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    """Turn API-format rgthree Power Lora nodes into Salad ``LoraLoader`` chains."""
    out = dict(prompt)
    for nid, node in list(prompt.items()):
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type") or "") != POWER_LORA:
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        model = inputs.get("model") or ["70", 0]
        clip = inputs.get("clip") or ["71", 0]
        specs: list[dict[str, Any]] = []
        for val in inputs.values():
            if not isinstance(val, dict) or not val.get("lora"):
                continue
            if val.get("on") is False:
                continue
            name = str(val.get("lora") or "").strip()
            if not name:
                continue
            strength = float(val.get("strength") if val.get("strength") is not None else 1)
            specs.append(
                {
                    "lora_name": name,
                    "filename": salad_filename(name),
                    "tag": Path(salad_filename(name)).stem,
                    "strength_model": strength,
                    "strength_clip": strength,
                }
            )
        if not specs:
            out.pop(str(nid), None)
            continue
        last_model, last_clip = list(model), list(clip)
        for i, spec in enumerate(specs):
            key = str(nid) if i == 0 else f"{nid}_{i}"
            loaded = {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": last_model,
                    "clip": last_clip,
                    "lora_name": spec["lora_name"],
                    "strength_model": spec["strength_model"],
                    "strength_clip": spec["strength_clip"],
                },
            }
            meta = rj.weight_meta(spec)
            if meta:
                loaded["_meta"] = meta
            out[key] = loaded
            last_model, last_clip = [key, 0], [key, 1]
        if len(specs) > 1:
            last = f"{nid}_{len(specs) - 1}"
            for other in out.values():
                if not isinstance(other, dict):
                    continue
                oin = other.get("inputs")
                if not isinstance(oin, dict):
                    continue
                for k, v in list(oin.items()):
                    if isinstance(v, list) and len(v) >= 2 and str(v[0]) == str(nid):
                        slot = v[1]
                        oin[k] = [last, 0 if slot == 0 else 1]
    return out


def _is_uuid_type(class_type: str) -> bool:
    return bool(_UUID_TYPE.match((class_type or "").strip()))


def _link_id(row: Any) -> Any:
    if isinstance(row, dict):
        return row.get("id")
    if isinstance(row, (list, tuple)) and row:
        return row[0]
    return None


def _set_link_id(row: Any, lid: int) -> None:
    if isinstance(row, dict):
        row["id"] = lid
    elif isinstance(row, list) and row:
        row[0] = lid


def _max_link_id(workflow: dict[str, Any]) -> int:
    m = 0
    for row in workflow.get("links") or []:
        try:
            m = max(m, int(_link_id(row)))
        except (TypeError, ValueError):
            continue
    return m


def _set_node_input_link(
    nodes: list[Any], nid: Any, slot: Any, link_id: Any
) -> None:
    node = next((n for n in nodes if str(n.get("id")) == str(nid)), None)
    if not isinstance(node, dict):
        return
    ins = node.get("inputs") if isinstance(node.get("inputs"), list) else []
    try:
        idx = int(slot)
    except (TypeError, ValueError):
        return
    if 0 <= idx < len(ins) and isinstance(ins[idx], dict):
        ins[idx]["link"] = link_id


def _link_src(row: Any) -> tuple[Any, Any]:
    if isinstance(row, dict):
        return row.get("origin_id"), row.get("origin_slot")
    if isinstance(row, (list, tuple)) and len(row) >= 5:
        return row[1], row[2]
    return None, None


def _link_dst(row: Any) -> tuple[Any, Any]:
    if isinstance(row, dict):
        return row.get("target_id"), row.get("target_slot")
    if isinstance(row, (list, tuple)) and len(row) >= 5:
        return row[3], row[4]
    return None, None


def _set_link_src(row: Any, nid: Any, slot: Any) -> None:
    if isinstance(row, dict):
        row["origin_id"] = nid
        row["origin_slot"] = slot
    elif isinstance(row, list) and len(row) >= 5:
        row[1], row[2] = nid, slot


def _set_link_dst(row: Any, nid: Any, slot: Any) -> None:
    if isinstance(row, dict):
        row["target_id"] = nid
        row["target_slot"] = slot
    elif isinstance(row, list) and len(row) >= 5:
        row[3], row[4] = nid, slot


def _set_named_widget(nodes: list[Any], nid: Any, name: str, val: Any) -> None:
    node = next((n for n in nodes if str(n.get("id")) == str(nid)), None)
    if not isinstance(node, dict):
        return
    ntype = str(node.get("type") or "")
    order = WIDGET_ORDER.get(ntype) or ()
    wv = list(node.get("widgets_values") or [])
    if ntype == "CLIPTextEncode" or name == "text":
        node["widgets_values"] = [val] + wv[1:]
        return
    idx = list(order).index(name) if name in order else 0
    while len(wv) <= idx:
        wv.append(None)
    wv[idx] = val
    node["widgets_values"] = wv


def flatten_comfy_subgraphs(
    obj: dict[str, Any], *, strip_unknown: bool = True
) -> dict[str, Any]:
    """Inline Comfy subgraph UUIDs (image 123714802) into real node types."""
    if not isinstance(obj, dict):
        return obj
    subs: dict[str, dict[str, Any]] = {}
    defs = obj.get("definitions")
    if isinstance(defs, dict):
        for sg in defs.get("subgraphs") or []:
            if isinstance(sg, dict) and sg.get("id"):
                flatten_comfy_subgraphs(sg, strip_unknown=False)
                subs[str(sg["id"])] = sg
    nodes = obj.get("nodes")
    if not isinstance(nodes, list):
        return obj
    max_id = 0
    for n in nodes:
        try:
            max_id = max(max_id, int(n.get("id")))
        except (TypeError, ValueError):
            continue
    counter = [max_id]
    guard = 0
    while guard < 32:
        guard += 1
        parent = next(
            (
                n
                for n in nodes
                if isinstance(n, dict)
                and _is_uuid_type(str(n.get("type") or ""))
                and str(n.get("type")) in subs
                and not _node_muted(n)
            ),
            None,
        )
        if parent is None:
            if strip_unknown:
                drop_ids = {
                    str(n.get("id"))
                    for n in nodes
                    if isinstance(n, dict)
                    and _is_uuid_type(str(n.get("type") or ""))
                }
                if drop_ids:
                    obj["nodes"] = [
                        n for n in nodes if str(n.get("id")) not in drop_ids
                    ]
            break
        _inline_subgraph(obj, parent, subs[str(parent.get("type"))], counter)
        nodes = obj.get("nodes") or []
    return obj


def _inline_subgraph(
    host: dict[str, Any],
    parent: dict[str, Any],
    sg: dict[str, Any],
    counter: list[int],
) -> None:
    idmap: dict[Any, int] = {}
    inner = [json.loads(json.dumps(n)) for n in (sg.get("nodes") or []) if isinstance(n, dict)]
    for n in inner:
        old = n.get("id")
        counter[0] += 1
        idmap[old] = counter[0]
        idmap[str(old)] = counter[0]
        n["id"] = counter[0]
    in_map: dict[int, list[tuple[Any, Any]]] = {}
    out_map: dict[int, tuple[Any, Any]] = {}
    new_links: list[Any] = []
    link_id_map: dict[int, int] = {}
    next_lid = [_max_link_id(host)]
    for raw in sg.get("links") or []:
        L = json.loads(json.dumps(raw))
        o, os_ = _link_src(L)
        t, ts = _link_dst(L)
        if o in (-10, "-10"):
            try:
                in_map.setdefault(int(os_), []).append((idmap.get(t, t), ts))
            except (TypeError, ValueError):
                pass
            continue
        if t in (-20, "-20"):
            try:
                out_map[int(ts)] = (idmap.get(o, o), os_)
            except (TypeError, ValueError):
                pass
            continue
        next_lid[0] += 1
        new_lid = next_lid[0]
        try:
            link_id_map[int(_link_id(L))] = new_lid
        except (TypeError, ValueError):
            pass
        _set_link_id(L, new_lid)
        _set_link_src(L, idmap.get(o, idmap.get(str(o), o)), os_)
        _set_link_dst(L, idmap.get(t, idmap.get(str(t), t)), ts)
        new_links.append(L)
    for n in inner:
        for inp in n.get("inputs") or []:
            if not isinstance(inp, dict) or inp.get("link") is None:
                continue
            try:
                mapped = link_id_map.get(int(inp["link"]))
            except (TypeError, ValueError):
                mapped = None
            if mapped is not None:
                inp["link"] = mapped
    p_inputs = parent.get("inputs") if isinstance(parent.get("inputs"), list) else []
    by_name = {
        str(p.get("name")): p
        for p in p_inputs
        if isinstance(p, dict) and p.get("name")
    }
    sg_inputs = sg.get("inputs") if isinstance(sg.get("inputs"), list) else []
    host_links = host.get("links") if isinstance(host.get("links"), list) else []
    for i, sinp in enumerate(sg_inputs):
        if not isinstance(sinp, dict):
            continue
        name = str(sinp.get("name") or "")
        pin = by_name.get(name)
        targets = in_map.get(i) or []
        if not pin or pin.get("link") is None or not targets:
            continue
        plink = pin.get("link")
        inn, its = targets[0]
        for HL in host_links:
            if _link_id(HL) == plink:
                _set_link_dst(HL, inn, its)
                break
        _set_node_input_link(inner, inn, its, plink)
    proxy = []
    props = parent.get("properties")
    if isinstance(props, dict):
        proxy = props.get("proxyWidgets") or []
    p_widgets = list(parent.get("widgets_values") or [])
    if isinstance(proxy, list) and proxy:
        for i, spec in enumerate(proxy):
            if i >= len(p_widgets) or not isinstance(spec, (list, tuple)) or len(spec) < 2:
                continue
            inner_old, wname = spec[0], str(spec[1])
            val = p_widgets[i]
            if str(inner_old) in ("-1", "-1.0"):
                for j, sinp in enumerate(sg_inputs):
                    if isinstance(sinp, dict) and str(sinp.get("name")) == wname:
                        for inn, _its in in_map.get(j) or []:
                            _set_named_widget(inner, inn, wname, val)
                        break
            else:
                nid = idmap.get(inner_old, idmap.get(str(inner_old)))
                if nid is not None:
                    _set_named_widget(inner, nid, wname, val)
    parent_id = parent.get("id")
    for HL in host_links:
        o, os_ = _link_src(HL)
        if str(o) != str(parent_id):
            continue
        try:
            mapped = out_map.get(int(os_))
        except (TypeError, ValueError):
            mapped = None
        if mapped:
            _set_link_src(HL, mapped[0], mapped[1])
    host["nodes"] = [
        n for n in (host.get("nodes") or []) if str(n.get("id")) != str(parent_id)
    ]
    host["nodes"].extend(inner)
    host.setdefault("links", [])
    if isinstance(host["links"], list):
        host["links"].extend(new_links)


def salad_body_from_comfy_obj(obj: dict[str, Any]) -> dict[str, Any]:
    """UI workflow → LoraLoader chain; API prompt → expand rgthree then use."""
    ui = _ui_workflow(obj)
    if ui is not None:
        ui = flatten_comfy_subgraphs(json.loads(json.dumps(ui)))
        prompt = workflow_to_prompt(ui)
        drop_orphan_nodes(prompt)
        return {
            "prompt": prompt,
            "convert_output": dict(CONVERT_OUTPUT),
        }
    prompt = obj.get("prompt") if isinstance(obj.get("prompt"), dict) else None
    if prompt:
        prompt = expand_power_lora_prompt(prompt)
        drop_orphan_nodes(prompt)
        return {
            "prompt": prompt,
            "convert_output": dict(CONVERT_OUTPUT),
        }
    raise ValueError(
        "Not a Comfy workflow (need 'nodes') or Salad request (need 'prompt')"
    )


def workflow_from_generation(gen: dict[str, Any] | None) -> str:
    """Comfy UI ``nodes`` JSON when present; else API ``prompt`` graph."""
    if not isinstance(gen, dict):
        return ""

    def _as_workflow(val: Any) -> str:
        obj: Any = val
        if isinstance(val, str) and val.strip().startswith("{"):
            try:
                obj = json.loads(_js_to_json(val))
            except json.JSONDecodeError:
                return ""
        if not isinstance(obj, dict):
            return ""
        ui = _ui_workflow(obj)
        if ui is not None:
            return json.dumps(ui)
        if isinstance(obj.get("prompt"), dict):
            return json.dumps({"prompt": obj["prompt"]})
        return ""

    for key in ("comfy", "workflow", "extra"):
        raw = gen.get(key)
        if key == "extra" and isinstance(raw, dict):
            for sub in ("comfy", "workflow", "pnginfo"):
                got = _as_workflow(raw.get(sub))
                if got:
                    return got
            continue
        got = _as_workflow(raw)
        if got:
            return got
    return ""


def fetch_civitai_image_pastes(image_id: str) -> dict[str, str]:
    """Generation-data text (Copy All) plus optional Comfy workflow JSON."""
    img = ls.fetch_civitai_image(image_id)
    if not img:
        raise ValueError(f"Civitai image {image_id} was not found")
    gen = ls.unwrap_image_generation(img)
    meta = generation_data_from_image(img)
    wf = workflow_from_generation(gen)
    if not meta.strip() and not wf.strip():
        raise ValueError(
            f"Civitai image {image_id} has no generation data (Copy All is empty)"
        )
    tools = gen.get("tools")
    tool = ""
    if isinstance(tools, list):
        names = []
        for row in tools:
            if isinstance(row, str) and row.strip():
                names.append(row.strip())
            elif isinstance(row, dict) and row.get("name"):
                names.append(str(row["name"]).strip())
        tool = ", ".join(names)
    return {
        "image_id": str(image_id),
        "metadata": meta,
        "workflow": wf,
        "tool": tool,
    }


def _finish_body(
    body: dict[str, Any],
    *,
    meta: dict[str, Any],
    meta_text: str,
    wf_raw: str,
    knobs: dict[str, Any] | None,
) -> dict[str, Any]:
    if "convert_output" not in body:
        body["convert_output"] = dict(CONVERT_OUTPUT)
    body = apply_metadata(body, meta)
    auto = knobs_from_sources(meta_text, wf_raw)
    if knobs:
        for k, v in knobs.items():
            if v not in (None, ""):
                auto[k] = v
    body = apply_knobs(body, auto)
    if isinstance(body.get("prompt"), dict):
        rj.wire_clip_encodes(body["prompt"])
    return rj.stamp_weight_refs(body)


def comfy_source_nodes(obj: dict[str, Any] | None) -> list[tuple[str, str]]:
    """(id, type) for every node on the Civitai/Comfy graph (UI nodes preferred)."""
    if not isinstance(obj, dict):
        return []
    ui = _ui_workflow(obj)
    if ui is not None and isinstance(ui.get("nodes"), list):
        out: list[tuple[str, str]] = []
        for node in ui["nodes"]:
            if not isinstance(node, dict):
                continue
            nid = node.get("id")
            ntype = str(node.get("type") or node.get("class_type") or "")
            if nid is None or not ntype:
                continue
            out.append((str(nid), ntype))
        return out
    prompt = obj.get("prompt") if isinstance(obj.get("prompt"), dict) else obj
    if isinstance(prompt, dict):
        rows: list[tuple[str, str]] = []
        for nid, node in prompt.items():
            if isinstance(node, dict) and node.get("class_type"):
                rows.append((str(nid), str(node["class_type"])))
        return rows
    return []


def salad_graph_nodes(prompt: dict[str, Any] | None) -> list[tuple[str, str]]:
    if not isinstance(prompt, dict):
        return []
    return [
        (str(nid), str(node.get("class_type") or ""))
        for nid, node in prompt.items()
        if isinstance(node, dict) and node.get("class_type")
    ]


def format_comfy_census(
    src: list[tuple[str, str]], dst: list[tuple[str, str]]
) -> str:
    src_ids = {i for i, _ in src}
    dst_ids = {i for i, _ in dst}
    dropped = [(i, t) for i, t in src if i not in dst_ids]
    added = [(i, t) for i, t in dst if i not in src_ids]
    line = f"Comfy nodes: {len(src)} on site, {len(dst)} after import"
    if dropped:
        line += "; dropped " + ", ".join(f"{t} #{i}" for i, t in dropped)
    if added:
        line += "; added " + ", ".join(f"{t} #{i}" for i, t in added)
    rewritten = []
    src_type = {i: t for i, t in src}
    for i, t in dst:
        if i in src_type and src_type[i] != t:
            rewritten.append(f"{src_type[i]}→{t} #{i}")
    if rewritten:
        line += "; rewrote " + ", ".join(rewritten)
    return line


def comfy_convert_census_note(workflow_text: str, body: dict[str, Any] | None) -> str:
    if not (workflow_text or "").strip():
        return ""
    try:
        obj = _parse_json_blob(workflow_text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return ""
    if not isinstance(obj, dict):
        return ""
    src = comfy_source_nodes(obj)
    dst = salad_graph_nodes(body.get("prompt") if isinstance(body, dict) else None)
    if not src:
        return ""
    return format_comfy_census(src, dst)


def convert_comfy_graph(
    obj: dict[str, Any],
    *,
    extras_path: Path | None = None,
    meta: dict[str, Any] | None = None,
    meta_text: str = "",
    wf_raw: str = "",
    knobs: dict[str, Any] | None = None,
    img: dict[str, Any] | None = None,
    hints: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Comfy nodes path: the graph is source of truth (UNET, size, CFG, CLIP).

    Do not overlay Import Checkpoint Distilled onto a base-9b loader. When
    the saved graph has no LoraLoader, insert Civitai Resources-used LoRAs
    (e.g. MJ Style Distilled 206 on image 134347427).
    """
    body = salad_body_from_comfy_obj(obj)
    prompt = body.get("prompt")
    if isinstance(prompt, dict):
        resolve_local_lora_nodes(prompt, extras_path=extras_path, hints=hints)
        meta = meta if isinstance(meta, dict) else {}
        tags = list(meta.get("lora_tags") or []) or resource_order_tags(
            img, hints
        ) or []
        inject_resource_loras(
            prompt, tags=tags, extras_path=extras_path, hints=hints
        )
        apply_salad_compat(body)
        rj.wire_clip_encodes(prompt)
    if "convert_output" not in body:
        body["convert_output"] = dict(CONVERT_OUTPUT)
    return rj.stamp_weight_refs(body)


def convert_klein_from_metadata(
    meta: dict[str, Any],
    *,
    img: dict[str, Any] | None = None,
    hints: dict[str, dict[str, Any]] | None = None,
    extras_path: Path | None = None,
    meta_text: str = "",
    knobs: dict[str, Any] | None = None,
    draw_things: bool = False,
) -> dict[str, Any]:
    """No Comfy graph: Klein /prompt from site prompt + Resources LoRA order."""
    if draw_things and meta.get("prompt"):
        meta = dict(meta)
        meta["prompt"] = expand_truncated_cover_prompt(
            str(meta["prompt"]), has_artificeal=True
        )
    seed = int(meta.get("seed") or 1)
    width = int(meta.get("width") or 1024)
    height = int(meta.get("height") or 768)
    unet_guess = str(meta.get("model") or "")
    distilled = "klein" in unet_guess.lower() and "base" not in unet_guess.lower()
    if meta.get("steps") is not None:
        steps = int(meta["steps"])
    elif draw_things and distilled:
        steps = 4
    else:
        steps = 40
    if draw_things and distilled and meta.get("cfg") is None:
        meta = dict(meta)
        meta["cfg"] = 1
    tags = non_comfy_lora_tags(meta, img, hints)
    specs, _missing = resolve_prompt_loras(
        tags,
        extras_path=extras_path,
        search=True,
        hints=hints or None,
    )
    body = rj.build_request(
        prompt_text=str(meta.get("prompt") or ""),
        graph="klein",
        width=width,
        height=height,
        steps=steps,
        seed=seed,
        cfg=meta.get("cfg"),
        loras=specs,
        selected_ids=[],
        extras_path=extras_path,
    )
    if isinstance(body.get("prompt"), dict):
        resolve_local_lora_nodes(
            body["prompt"], extras_path=extras_path, hints=hints
        )
    auto = knobs_from_sources(meta_text, "")
    if knobs:
        for k, v in knobs.items():
            if v not in (None, ""):
                auto[k] = v
    if draw_things:
        unet = auto.get("unet") or meta.get("model")
        samp = auto.get("sampler") or meta.get("sampler") or "euler"
        auto["sampler"] = map_draw_things_sampler(str(samp), unet)
        auto["scheduler"] = "flux2"
    return _finish_body(
        body, meta=meta, meta_text=meta_text, wf_raw="", knobs=auto
    )


def import_to_request(
    *,
    workflow_text: str = "",
    metadata_text: str = "",
    knobs: dict[str, Any] | None = None,
    extras_path: Path | None = None,
) -> dict[str, Any]:
    """Dispatch Convert to an isolated path (Comfy / Draw Things / metadata)."""
    meta_text, wf_raw = split_pastes(metadata_text, workflow_text)
    hints: dict[str, dict[str, Any]] = {}
    img: dict[str, Any] | None = None
    image_id = ls.civitai_image_id(meta_text) or ls.civitai_image_id(wf_raw)
    if image_id:
        img = ls.fetch_civitai_image(image_id)
        if img:
            hints = ls.lora_hints_from_generation(ls.unwrap_image_generation(img))
            rebuilt = generation_data_from_image(img)
            parsed_now = parse_civitai_metadata(meta_text) if meta_text else {}
            if rebuilt and not parsed_now.get("lora_tags"):
                meta_text = rebuilt
            live = workflow_from_generation(ls.unwrap_image_generation(img))
            if live:
                live_obj = _parse_json_blob(live)
                has_subs = (
                    isinstance(live_obj, dict)
                    and isinstance(
                        ((live_obj.get("definitions") or {}) if isinstance(live_obj.get("definitions"), dict) else {}).get("subgraphs"),
                        list,
                    )
                    and bool((live_obj.get("definitions") or {}).get("subgraphs"))
                )
                if has_subs or not wf_raw:
                    wf_raw = live
    meta = parse_civitai_metadata(meta_text) if meta_text else {}
    path = detect_import_tool(
        metadata_text=meta_text, workflow_text=wf_raw, img=img
    )
    if path == TOOL_COMFY:
        obj = _parse_json_blob(wf_raw) if wf_raw else None
        if not isinstance(obj, dict) or comfy_node_count(obj) == 0:
            path = TOOL_METADATA
        else:
            return convert_comfy_graph(
                obj,
                extras_path=extras_path,
                meta=meta,
                meta_text=meta_text,
                wf_raw=wf_raw,
                knobs=knobs,
                img=img,
                hints=hints,
            )
    if (
        path == TOOL_DRAW_THINGS
        or meta.get("prompt")
        or meta.get("negative")
        or meta.get("sampler")
        or meta.get("model")
        or meta.get("width")
        or meta.get("seed") is not None
    ):
        return convert_klein_from_metadata(
            meta,
            img=img,
            hints=hints,
            extras_path=extras_path,
            meta_text=meta_text,
            knobs=knobs,
            draw_things=path == TOOL_DRAW_THINGS,
        )
    raise ValueError(
        "Paste a Comfy workflow JSON and/or Civitai generation data "
        "(prompt + Steps/CFG, or Sampler/Seed/Model)."
    )


def drop_orphan_nodes(prompt: dict[str, Any]) -> list[str]:
    """Drop nodes the live SaveImage/Preview path does not depend on.

    Flatten of Civitai UUID subgraphs (image 123566519) used to leave a
    second muted Klein pipeline plus MarkdownNote / Fast Groups Bypasser
    with no wires. Those are import debris, not diagram bugs.
    """
    if not isinstance(prompt, dict):
        return []
    ids = {str(k) for k, n in prompt.items() if isinstance(n, dict)}
    deps: dict[str, set[str]] = {i: set() for i in ids}
    for nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        for val in inputs.values():
            edge = _edge(val)
            if edge and edge[0] in ids:
                deps[str(nid)].add(edge[0])
    sinks: list[str] = []
    for nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type") or "") not in _OUTPUT_TYPES:
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        edge = _edge(inputs.get("images") or inputs.get("image"))
        if edge is None or edge[0] in ids:
            sinks.append(str(nid))
    if not sinks:
        return []
    keep: set[str] = set()
    stack = list(sinks)
    while stack:
        cur = stack.pop()
        if cur in keep:
            continue
        keep.add(cur)
        stack.extend(deps.get(cur, ()))
    notes: list[str] = []
    for nid in list(prompt.keys()):
        sid = str(nid)
        if sid in keep:
            continue
        cls = str((prompt.get(nid) or {}).get("class_type") or "?")
        notes.append(f"Dropped orphan {cls} #{sid} (not on the SaveImage path).")
        del prompt[nid]
    return notes


def _edge(val: Any) -> tuple[str, int] | None:
    if isinstance(val, list) and len(val) >= 2:
        try:
            return str(val[0]), int(val[1])
        except (TypeError, ValueError):
            return None
    return None


def _rewire(prompt: dict[str, Any], old_id: str, slot_map: dict[int, Any]) -> None:
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key, val in list(inputs.items()):
            edge = _edge(val)
            if not edge or edge[0] != old_id:
                continue
            src = slot_map.get(edge[1])
            if src is not None:
                inputs[key] = src


def replica_issues(
    body: dict[str, Any] | None,
    metadata_text: str = "",
    extras_path: Path | None = None,
) -> list[str]:
    """Warnings for nodes/files the Klein prefetch replica may not run.

    Flags incompatible checkpoint/LoRA families (Krea 2 on a Klein group)
    and LoadImage names that are the author's local Comfy input, not a
    file on this PC or a Civitai URL.
    """
    issues: list[str] = []
    prompt = body.get("prompt") if isinstance(body, dict) else None
    if not isinstance(prompt, dict):
        return issues
    unet_fams: list[str] = []
    for nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        cls = node.get("class_type")
        if cls == "VAELoader":
            name = salad_filename(str(inputs.get("vae_name") or ""))
            if name in REPLICA_VAE:
                issues.append(
                    f"VAE {name} is not on the replica. This group has "
                    f"{REPLICA_VAE[name]}."
                )
            fam = weight_family(name)
            if fam in _INCOMPATIBLE_FAMILIES:
                issues.append(
                    f"VAE #{nid} {name} family {fam} is incompatible with "
                    f"this {REPLICA_FAMILY} replica."
                )
        elif cls == "UNETLoader":
            name = salad_filename(str(inputs.get("unet_name") or ""))
            mapped = replica_unet_name(name)
            fam = weight_family(name) or weight_family(mapped)
            if fam:
                unet_fams.append(fam)
            if name and mapped != name:
                issues.append(
                    f"UNET {name} is not on the replica. This group has "
                    f"{mapped}."
                )
            if fam in _INCOMPATIBLE_FAMILIES:
                issues.append(
                    f"UNET #{nid} family {fam} ({name}) is incompatible "
                    f"with this {REPLICA_FAMILY} replica."
                )
        elif cls == "CLIPLoader":
            clip_type = str(inputs.get("type") or "").strip().lower()
            if clip_type and clip_type not in ("flux2", "flux.2", ""):
                issues.append(
                    f"CLIPLoader #{nid} type {clip_type} is incompatible "
                    f"with this {REPLICA_FAMILY} replica (flux2)."
                )
        elif _is_uuid_type(cls):
            issues.append(
                f"Warning: #{nid} is a Comfy subgraph id ({cls}); "
                "Convert inlines the inner Klein graph."
            )
        elif cls in SALAD_MISSING_TYPES:
            issues.append(
                f"Warning: #{nid} {cls} is not on Salad Comfy 0.35 "
                "(kept in the editor; Generate omits it from the POST)."
            )
        elif cls == "LoraLoader":
            name = str(inputs.get("lora_name") or "")
            http = name.lower().startswith("http://") or name.lower().startswith(
                "https://"
            )
            item = ls.find_by_loader_name(name, extras_path) if name else None
            fam = ls.family_label(item) if item else weight_family(name)
            if fam in _INCOMPATIBLE_FAMILIES:
                issues.append(
                    f"LoRA #{nid} family {fam} is incompatible with this "
                    f"{REPLICA_FAMILY} replica ({salad_filename(name) or name})."
                )
            elif name and not http:
                issues.append(
                    f"LoRA {salad_filename(name)} is a local filename; "
                    "Convert will look it up on Civitai."
                )
        elif cls == "LoadImage":
            name = str(inputs.get("image") or "").strip()
            hit = resolve_load_image(name)
            status = str(hit.get("status") or "")
            if status == "http":
                continue
            if status == "empty":
                issues.append(
                    f"LoadImage #{nid} has no image; Generate omits it."
                )
            elif status == "local_found":
                issues.append(
                    f"LoadImage #{nid} {salad_filename(name)} is on this PC "
                    f"at {hit.get('path')}; Salad still cannot read it. "
                    "Generate omits it (no img2img source on Salad)."
                )
            else:
                issues.append(
                    f"LoadImage #{nid} {salad_filename(name)} is a local file "
                    "not on this PC (author's Comfy input, not a Civitai URL). "
                    "Generate omits it (no img2img source on Salad)."
                )
    graph_unet = next((f for f in unet_fams if f), "")
    meta = parse_civitai_metadata(metadata_text) if metadata_text else {}
    listed = meta.get("resources") if isinstance(meta.get("resources"), list) else []
    ckpt_rows = [
        r
        for r in listed
        if isinstance(r, dict) and str(r.get("type") or "").lower() == "checkpoint"
    ]
    if len(ckpt_rows) > 1:
        labels = []
        for r in ckpt_rows:
            nm = str(r.get("name") or "")
            fam = str(r.get("family") or weight_family(nm) or "unknown")
            labels.append(f"{nm} ({fam})")
        issues.append(
            "Civitai lists "
            + str(len(ckpt_rows))
            + " checkpoints: "
            + "; ".join(labels)
            + "."
        )
    for r in listed:
        if not isinstance(r, dict):
            continue
        rtype = str(r.get("type") or "").lower()
        rname = str(r.get("name") or "")
        rfam = str(r.get("family") or "") or weight_family(rname)
        if rfam not in _INCOMPATIBLE_FAMILIES:
            continue
        if rtype == "checkpoint":
            if graph_unet == REPLICA_FAMILY:
                issues.append(
                    f"Civitai resource checkpoint {rname} family {rfam} is "
                    f"not loaded as UNET (graph UNET is {graph_unet}; likely "
                    "LoadImage lineage). This Klein replica cannot run that "
                    "checkpoint."
                )
            elif not graph_unet:
                issues.append(
                    f"Civitai resource checkpoint {rname} family {rfam} is "
                    f"incompatible with this {REPLICA_FAMILY} replica."
                )
        elif rtype == "lora":
            issues.append(
                f"Civitai resource LoRA {rname} family {rfam} is incompatible "
                f"with this {REPLICA_FAMILY} replica."
            )
    return issues


def inspect_pastes(
    metadata_text: str = "", workflow_text: str = ""
) -> tuple[list[str], list[str]]:
    """Return (blocking replica issues, non-blocking notes)."""
    meta_text, wf_raw = split_pastes(metadata_text, workflow_text)
    blocking: list[str] = []
    notes: list[str] = []
    if wf_raw:
        try:
            obj = _parse_json_blob(wf_raw)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            blocking = [f"Could not parse workflow JSON: {e}"]
            obj = None
        if isinstance(obj, dict):
            try:
                body = salad_body_from_comfy_obj(obj)
            except ValueError as e:
                blocking = [str(e)]
                body = None
            if body:
                prompt = body.get("prompt")
                if isinstance(prompt, dict):
                    still = resolve_local_lora_nodes(prompt)
                    if still:
                        notes.extend(
                            f"LoRA not found on Civitai (left as local filename): {name}"
                            for name in still
                        )
                    apply_salad_compat(body)
                    census = comfy_convert_census_note(wf_raw, body)
                    if census:
                        notes.append(census)
                more = replica_issues(body, metadata_text=meta_text)
                notes.extend(
                    i
                    for i in more
                    if i not in notes and "look it up on Civitai" not in i
                )
    if meta_text:
        meta = parse_civitai_metadata(meta_text)
        notes.extend(str(n) for n in (meta.get("notes") or []))
    return blocking, notes


def issues_from_pastes(metadata_text: str = "", workflow_text: str = "") -> list[str]:
    """Parse Import pastes and list replica blockers plus notes."""
    blocking, notes = inspect_pastes(metadata_text, workflow_text)
    return blocking + notes


def apply_salad_compat(body: dict[str, Any]) -> list[str]:
    """Path-only cleanup: strip Windows folders on UNET/CLIP/VAE names.

    Maps replica-missing filenames (small decoder VAE, Civitai `fp8mixed`
    Klein UNETs) onto the files prefetch actually writes. Does not change
    node types. Missing types stay and are warned.
    """
    warnings: list[str] = []
    prompt = body.get("prompt") if isinstance(body, dict) else None
    if not isinstance(prompt, dict):
        return warnings
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        cls = str(node.get("class_type") or "")
        if cls == "VAELoader":
            name = salad_filename(str(inputs.get("vae_name") or ""))
            mapped = REPLICA_VAE.get(name)
            if mapped and mapped != name:
                inputs["vae_name"] = mapped
                warnings.append(f"VAE {name} → {mapped} (replica disk)")
            elif name:
                inputs["vae_name"] = name
        elif cls == "UNETLoader" and inputs.get("unet_name"):
            name = salad_filename(str(inputs["unet_name"]))
            mapped = replica_unet_name(name)
            if mapped != name:
                warnings.append(f"UNET {name} → {mapped} (replica disk)")
            inputs["unet_name"] = mapped
        elif cls == "CLIPLoader" and inputs.get("clip_name"):
            inputs["clip_name"] = salad_filename(str(inputs["clip_name"]))
    return warnings


def _repair_ksampler_inputs(prompt: dict[str, Any]) -> None:
    """Unshift KSampler widgets packed with control_after_generate as steps.

    Comfy UI widgets_values are ``seed, randomize|fixed|…, steps, cfg,
    sampler_name, scheduler, denoise``. Convert used to zip that list onto
    the six KSampler inputs, so Salad got ``steps='randomize'``.
    """
    for node in prompt.values():
        if not isinstance(node, dict) or node.get("class_type") != "KSampler":
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if not _is_seed_control(inputs.get("steps")):
            continue
        inputs["steps"] = inputs.get("cfg")
        inputs["cfg"] = inputs.get("sampler_name")
        inputs["sampler_name"] = inputs.get("scheduler")
        inputs["scheduler"] = inputs.get("denoise")
        inputs["denoise"] = 1


def _repair_sampler_names(prompt: dict[str, Any]) -> None:
    """Map Civitai/Draw Things sampler strings onto Comfy KSamplerSelect names."""
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") not in ("KSamplerSelect", "KSampler"):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        raw = inputs.get("sampler_name")
        if not isinstance(raw, str) or not raw.strip():
            inputs["sampler_name"] = "euler"
            continue
        name, _sched = _parse_sampler_field(raw)
        inputs["sampler_name"] = name


def prompt_for_salad_replica(prompt: dict[str, Any]) -> dict[str, Any]:
    """Copy of the editor graph with replica-missing types removed for POST.

    Import keeps every node. Salad Comfy 0.35 cannot instantiate rgthree /
    ReferenceLatent / notes, so Generate sends this stripped copy.
    """
    out = json.loads(json.dumps(prompt))
    apply_salad_compat({"prompt": out})
    _repair_ksampler_inputs(out)
    _repair_sampler_names(out)
    resolve_local_lora_nodes(out)
    rj.strip_non_klein_loras(out)
    if rj.prompt_has_distilled_unet(out):
        rj.apply_scheduler({"prompt": out}, "flux2")
    rj.wire_clip_encodes(out)
    rj.boost_klein_anime_prompt(out)
    for nid, node in list(out.items()):
        if not isinstance(node, dict):
            continue
        if node.get("class_type") == "ResolutionOrientationNodeComfy":
            _replace_resolution_orientation(out, str(nid), node)
    _rewrite_replica_missing_nodes(out)
    for nid, node in list(out.items()):
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "")
        if _is_uuid_type(cls) or cls in SALAD_MISSING_TYPES:
            _passthrough_drop_node(out, str(nid), node)
    for nid, node in list(out.items()):
        if not isinstance(node, dict) or node.get("class_type") != "LoraLoaderModelOnly":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        if str(inputs.get("lora_name") or "").strip():
            continue
        _passthrough_drop_node(out, str(nid), node)
    for nid, node in list(out.items()):
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        image = str(inputs.get("image") or "").strip()
        if image.startswith("http://") or image.startswith("https://"):
            continue
        del out[nid]
    _drop_missing_image_chain(out)
    _fill_dangling_size_links(out)
    _rewire_missing_links(out)
    ensure_save_image(out)
    return out


def _rewrite_replica_missing_nodes(prompt: dict[str, Any]) -> None:
    """Repair the replica-missing types Convert rewires instead of dropping.

    Salad Comfy 0.35 has no ReferenceLatent / ConditioningZeroOut / Color
    Correct GPU (mtb), but the graph needs their effect: consumers are rewired
    to the node's own upstream input, and ConditioningZeroOut becomes an empty
    CLIPTextEncode. Runs before the SALAD_MISSING_TYPES drop pass so those
    three never reach it.
    """
    clip = rj.base_clip_ref(prompt) or ["71", 0]
    for nid, node in list(prompt.items()):
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "")
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        if cls == "ReferenceLatent":
            _rewire(prompt, str(nid), {0: inputs.get("conditioning")})
            del prompt[nid]
        elif cls == "ConditioningZeroOut":
            zclip: Any = clip
            edge = _edge(inputs.get("conditioning"))
            if edge:
                src = prompt.get(edge[0])
                if isinstance(src, dict) and src.get("class_type") == "CLIPTextEncode":
                    zclip = (src.get("inputs") or {}).get("clip") or clip
            node["class_type"] = "CLIPTextEncode"
            node["inputs"] = {
                "text": "",
                "clip": list(zclip) if isinstance(zclip, list) else zclip,
            }
        elif cls == "Color Correct GPU (mtb)":
            _rewire(prompt, str(nid), {0: inputs.get("image")})
            del prompt[nid]


def _drop_missing_image_chain(prompt: dict[str, Any]) -> None:
    """After LoadImage is omitted, drop ImageScale/GetImageSize/VAEEncode that pointed at it."""
    changed = True
    while changed:
        changed = False
        ids = {str(k) for k, n in prompt.items() if isinstance(n, dict)}
        for nid, node in list(prompt.items()):
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
            for key in ("image", "pixels"):
                edge = _edge(inputs.get(key))
                if edge and edge[0] not in ids:
                    del prompt[nid]
                    changed = True
                    break


def _rewire_missing_links(prompt: dict[str, Any]) -> None:
    """Replace leftover [deleted-id, slot] edges after omitting replica-missing nodes."""
    ids = {str(k) for k, n in prompt.items() if isinstance(n, dict)}
    clip = None
    try:
        clip = rj.base_clip_ref(prompt)
    except Exception:
        clip = None
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key, val in list(inputs.items()):
            edge = _edge(val)
            if not edge or edge[0] in ids:
                continue
            if key in {"width", "height", "batch_size", "steps"}:
                inputs[key] = 1024
            elif key == "text":
                inputs[key] = ""
            elif key == "clip" and clip:
                inputs[key] = list(clip)


def _fill_dangling_size_links(prompt: dict[str, Any], default: int = 1024) -> None:
    ids = {str(k) for k, n in prompt.items() if isinstance(n, dict)}
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key, val in list(inputs.items()):
            edge = _edge(val)
            if not edge or edge[0] in ids:
                continue
            if key in {"width", "height", "batch_size", "steps"}:
                inputs[key] = default


def _replace_resolution_orientation(
    prompt: dict[str, Any], nid: str, node: dict[str, Any]
) -> None:
    """Swap ResolutionOrientationNodeComfy for two PrimitiveInt size nodes."""
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    raw = str(inputs.get("resolution") or inputs.get("value") or "")
    match = re.search(r"(\d+)\s*[x×]\s*(\d+)", raw, re.I)
    width = int(match.group(1)) if match else 1024
    height = int(match.group(2)) if match else 1024
    wid = str(_next_node_id(prompt))
    prompt[wid] = {"class_type": "PrimitiveInt", "inputs": {"value": width}}
    hid = str(_next_node_id(prompt))
    prompt[hid] = {"class_type": "PrimitiveInt", "inputs": {"value": height}}
    _rewire(prompt, str(nid), {0: [wid, 0], 1: [hid, 0]})
    prompt.pop(str(nid), None)


def _passthrough_drop_node(prompt: dict[str, Any], nid: str, node: dict[str, Any]) -> None:
    """Drop a replica-unrunnable node; rewire consumers to a non-self input."""
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    first = None
    for key in ("image", "images", "anything", "samples", "model", "conditioning"):
        val = inputs.get(key)
        edge = _edge(val)
        if edge and str(edge[0]) != str(nid):
            first = val
            break
    if first is None:
        text = inputs.get("text")
        first = "" if isinstance(text, list) or text is None else str(text)
    _rewire(prompt, str(nid), {0: first})
    prompt.pop(str(nid), None)


def _has_save_image(prompt: dict[str, Any]) -> bool:
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") == "SaveImage":
            return True
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        if "filename_prefix" in inputs:
            return True
    return False


def _image_ref_for_save(prompt: dict[str, Any]) -> list[Any] | None:
    """Prefer VAEDecode; else last remaining IMAGE producer."""
    decode = None
    other: list[Any] | None = None
    for nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "")
        if cls == "VAEDecode":
            decode = [str(nid), 0]
        elif cls in ("VAEDecodeTiled", "ImageScaleToTotalPixels") and other is None:
            other = [str(nid), 0]
    return decode or other


def ensure_save_image(prompt: dict[str, Any]) -> None:
    """Salad /prompt requires a node with ``filename_prefix`` (SaveImage).

    Civitai graphs (image 140934673) often end on PreviewImage only.
    """
    if not isinstance(prompt, dict) or _has_save_image(prompt):
        return
    ref = _image_ref_for_save(prompt)
    if not ref:
        return
    nid = str(_next_node_id(prompt))
    prompt[nid] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "klein", "images": list(ref)},
    }


def split_pastes(metadata_text: str, workflow_text: str) -> tuple[str, str]:
    """Split mixed pastes: JSON may sit in either box, with extra data after it."""
    meta = (metadata_text or "").strip()
    wf = (workflow_text or "").strip()
    if wf:
        return _strip_json_objects(meta), wf
    extracted = _first_graph_json_text(meta)
    if extracted:
        return _strip_json_objects(meta), extracted
    return meta, wf


def _int_from_graph(prompt: dict[str, Any], val: Any, default: Any = None) -> Any:
    n = rj.coerce_int(val)
    if n is not None:
        return n
    edge = _edge(val)
    if edge is None:
        return default
    node = prompt.get(edge[0])
    if isinstance(node, dict) and node.get("class_type") in (
        "PrimitiveInt",
        "PrimitiveFloat",
    ):
        return rj.coerce_int((node.get("inputs") or {}).get("value"), default)
    return default


def knobs_from_sources(metadata_text: str = "", workflow_text: str = "") -> dict[str, Any]:
    """CFG / seed / size / scheduler extracted from paste (workflow wins, then metadata).

    Only keys actually found are returned — do not default CFG 5 / 40 steps /
    1024² here or a distilled Klein graph (CFG 1, 4 steps, 1280×1920) gets
    clobbered on Convert.
    """
    meta_text, wf_text = split_pastes(metadata_text, workflow_text)
    knobs: dict[str, Any] = {}
    if wf_text:
        try:
            obj = _parse_json_blob(wf_text)
        except (json.JSONDecodeError, ValueError, TypeError):
            obj = None
        if isinstance(obj, dict):
            if "nodes" in obj:
                body = {"prompt": workflow_to_prompt(obj)}
            elif isinstance(obj.get("prompt"), dict):
                body = obj
            else:
                body = None
            if body:
                cfg = rj.config_from_payload(body)
                gp = body.get("prompt") if isinstance(body.get("prompt"), dict) else {}
                w = rj.coerce_int(cfg.get("width"))
                h = rj.coerce_int(cfg.get("height"))
                for node in gp.values():
                    if not isinstance(node, dict):
                        continue
                    if node.get("class_type") in (
                        "EmptyFlux2LatentImage",
                        "EmptyLatentImage",
                        "Flux2Scheduler",
                    ):
                        inp = node.get("inputs") or {}
                        gw = _int_from_graph(gp, inp.get("width"))
                        gh = _int_from_graph(gp, inp.get("height"))
                        if gw is not None:
                            w = gw
                        if gh is not None:
                            h = gh
                if w is not None:
                    knobs["width"] = w
                if h is not None:
                    knobs["height"] = h
                st = rj.coerce_int(cfg.get("steps"))
                if st is not None:
                    knobs["steps"] = st
                if cfg.get("scheduler"):
                    knobs["scheduler"] = str(cfg["scheduler"])
                if cfg.get("cfg") not in (None, ""):
                    knobs["cfg"] = cfg.get("cfg")
                if cfg.get("unet"):
                    knobs["unet"] = cfg["unet"]
                if cfg.get("prompt_text"):
                    knobs["prompt"] = cfg["prompt_text"]
                for node in (body.get("prompt") or {}).values():
                    if not isinstance(node, dict):
                        continue
                    if node.get("class_type") == "RandomNoise":
                        seed = (node.get("inputs") or {}).get("noise_seed")
                        seed_i = rj.coerce_int(seed)
                        if seed_i is not None:
                            knobs["seed"] = seed_i
                    if node.get("class_type") == "CFGGuider":
                        c = (node.get("inputs") or {}).get("cfg")
                        if c is not None:
                            knobs["cfg"] = c
    meta = parse_civitai_metadata(meta_text) if meta_text else {}
    for k in ("cfg", "steps", "width", "height", "seed", "sampler", "prompt", "negative"):
        if k in meta and k not in knobs:
            knobs[k] = meta[k]
    if meta.get("model") and "unet" not in knobs:
        knobs["unet"] = rj.normalize_unet(str(meta["model"]))
    if meta.get("scheduler") and "scheduler" not in knobs:
        knobs["scheduler"] = "simple" if meta["scheduler"] == "simple" else "flux2"
    return knobs


def apply_knobs(body: dict[str, Any], knobs: dict[str, Any] | None) -> dict[str, Any]:
    """Force CFG / seed / size / scheduler onto a Salad /prompt body."""
    if not knobs or not isinstance(body.get("prompt"), dict):
        return body
    meta = {}
    for k in ("cfg", "steps", "width", "height", "seed", "prompt", "negative", "sampler"):
        if knobs.get(k) not in (None, ""):
            meta[k] = knobs[k]
    if knobs.get("unet"):
        meta["model"] = knobs["unet"]
    body = apply_metadata(body, meta)
    if knobs.get("scheduler"):
        rj.apply_scheduler(body, knobs["scheduler"])
    # apply_scheduler may drop width/height on BasicScheduler; keep latent size.
    return apply_metadata(
        body,
        {
            k: knobs[k]
            for k in ("width", "height", "steps")
            if knobs.get(k) not in (None, "")
        },
    )
