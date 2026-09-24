"""Resolve the weights a request JSON references, for the Prompt Assist.

Local knowledge first, the LoRA catalog / user extras, the replica's own
prefetched files, then the filename family heuristic. A name the local sources
miss gets one online Civitai lookup. A name that resolves nowhere is reported
as ``unresolved`` rather than dropped, so the AI is told what is missing.

Window-free: the Tk page only renders what this returns. The online lookup is
injectable so tests fake the network at the boundary.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

try:
    from salad_studio import comfy_import as ci
    from salad_studio import lora_store as ls
    from salad_studio import request_json as rj
except ImportError:  # sibling imports when run from salad_studio
    import comfy_import as ci
    import lora_store as ls
    import request_json as rj

USER_AGENT = "SaladStudio/1.0"
CIVITAI_MODELS = "https://civitai.com/api/v1/models"
CIVITAI_VERSION = "https://civitai.com/api/v1/model-versions/{vid}"
_DOWNLOAD_VID = re.compile(r"/download/models/(\d+)", re.I)

# Node class -> (kind, input field) for every weight a request can load.
REF_FIELDS: dict[str, tuple[str, str]] = {
    "LoraLoader": ("lora", "lora_name"),
    "LoraLoaderModelOnly": ("lora", "lora_name"),
    "UNETLoader": ("checkpoint", "unet_name"),
    "CheckpointLoaderSimple": ("checkpoint", "ckpt_name"),
    "CLIPLoader": ("clip", "clip_name"),
    "VAELoader": ("vae", "vae_name"),
}

Lookup = Callable[[str, str], "dict[str, Any] | None"]


def _node_sort_key(item: tuple[Any, Any]) -> tuple[int, str]:
    nid = str(item[0])
    try:
        return (0, f"{int(nid):08d}")
    except ValueError:
        return (1, nid)


def collect_refs(request: dict[str, Any] | None) -> list[dict[str, str]]:
    """Every weight reference in a request body, in node order."""
    prompt = request.get("prompt") if isinstance(request, dict) else None
    if not isinstance(prompt, dict):
        return []
    out: list[dict[str, str]] = []
    for nid, node in sorted(prompt.items(), key=_node_sort_key):
        if not isinstance(node, dict):
            continue
        pair = REF_FIELDS.get(str(node.get("class_type") or ""))
        if pair is None:
            continue
        kind, field = pair
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        out.append(
            {
                "node": str(nid),
                "kind": kind,
                "field": field,
                "name": str(inputs.get(field) or "").strip(),
            }
        )
    return out


def download_version_id(url: str) -> str:
    m = _DOWNLOAD_VID.search(url or "")
    return m.group(1) if m else ""


def _civitai_get(url: str, timeout: int) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ):
        return None


def _file_stem(name: str) -> str:
    return Path(ci.salad_filename(name)).stem.lower()


def _version_finding(data: dict[str, Any], raw: str) -> dict[str, Any]:
    files = data.get("files") if isinstance(data.get("files"), list) else []
    first = next((f for f in files if isinstance(f, dict)), {})
    return {
        "source": "civitai-version",
        "model_name": str(data.get("modelName") or data.get("model", {}).get("name") or ""),
        "version_name": str(data.get("name") or ""),
        "base": str(data.get("baseModel") or ""),
        "filename": str(first.get("name") or "") or ci.salad_filename(raw),
        "url": f"https://civitai.com/models/{data.get('modelId')}"
        f"?modelVersionId={data.get('id')}"
        if data.get("modelId")
        else "",
    }


def _model_finding(item: dict[str, Any], version: dict[str, Any], raw: str) -> dict[str, Any]:
    files = version.get("files") if isinstance(version.get("files"), list) else []
    first = next((f for f in files if isinstance(f, dict)), {})
    return {
        "source": "civitai-model",
        "model_name": str(item.get("name") or ""),
        "version_name": str(version.get("name") or ""),
        "base": str(version.get("baseModel") or item.get("baseModel") or ""),
        "filename": str(first.get("name") or "") or ci.salad_filename(raw),
        "url": f"https://civitai.com/models/{item.get('id')}"
        f"?modelVersionId={version.get('id')}"
        if item.get("id")
        else "",
    }


def online_lookup(name: str, kind: str, *, timeout: int = 15) -> dict[str, Any] | None:
    """One Civitai lookup for a LoRA/checkpoint/clip/vae name or download URL."""
    raw = (name or "").strip()
    if not raw:
        return None
    vid = download_version_id(raw)
    if vid:
        data = ls.fetch_civitai_version(int(vid), timeout=timeout)
        if isinstance(data, dict) and data:
            return _version_finding(data, raw)
        return None
    stem = _file_stem(raw) or raw
    types = "LORA" if kind == "lora" else "Checkpoint"
    params = urllib.parse.urlencode({"limit": 10, "query": stem, "types": types})
    data = _civitai_get(f"{CIVITAI_MODELS}?{params}", timeout)
    items = [
        it
        for it in ((data or {}).get("items") or [])
        if isinstance(it, dict)
    ]
    if not items:
        return None
    for item in items:
        for version in item.get("modelVersions") or []:
            if not isinstance(version, dict):
                continue
            for f in version.get("files") or []:
                if isinstance(f, dict) and Path(str(f.get("name") or "")).stem.lower() == stem:
                    return _model_finding(item, version, raw)
    first = items[0]
    versions = [v for v in (first.get("modelVersions") or []) if isinstance(v, dict)]
    return _model_finding(first, versions[0] if versions else {}, raw)


def local_lookup(
    name: str, *, extras_path: Path | None = None
) -> dict[str, Any] | None:
    """Catalog / extras / replica knowledge for a weight name. None on a miss."""
    raw = (name or "").strip()
    if not raw:
        return None
    item = ls.find_by_loader_name(raw, extras_path)
    if item is not None:
        return {
            "source": "catalog",
            "model_name": str(item.get("name") or ""),
            "version_name": ls.version_label(item),
            "base": str(item.get("base") or ""),
            "family": ls.family_label(item),
            "filename": str((item.get("source") or {}).get("filename") or ""),
            "url": str((item.get("source") or {}).get("page") or ""),
            "item": item,
        }
    base = ci.salad_filename(raw)
    if base and base in ls.replica_weight_names():
        return {
            "source": "replica",
            "model_name": base,
            "version_name": "",
            "base": "",
            "family": ci.weight_family(base),
            "filename": base,
            "url": "",
        }
    mapped = ci.replica_unet_name(base) if base else ""
    if mapped and mapped != base:
        return {
            "source": "replica-map",
            "model_name": mapped,
            "version_name": "",
            "base": "",
            "family": ci.weight_family(mapped),
            "filename": mapped,
            "url": "",
        }
    family = ci.weight_family(raw)
    if family:
        return {
            "source": "filename",
            "model_name": base or raw,
            "version_name": "",
            "base": "",
            "family": family,
            "filename": base or raw,
            "url": "",
        }
    return None


def _compatible(family: str, graph: str, item: dict[str, Any] | None) -> bool | None:
    """Compatibility with the replica running ``graph``. None when unknown."""
    if item is not None:
        return ls.compatible_with_graph(item, graph)
    if not family:
        return None
    if graph == "klein":
        return family == ci.REPLICA_FAMILY
    return None


def resolve_refs(
    request: dict[str, Any] | None,
    *,
    extras_path: Path | None = None,
    graph: str | None = None,
    lookup: Lookup | None = None,
    timeout: int = 15,
) -> list[dict[str, Any]]:
    """Resolve every weight a request loads. Unresolvable names are kept."""
    body = request if isinstance(request, dict) else {}
    if graph is None:
        try:
            graph = str(rj.config_from_payload(body).get("graph") or "klein")
        except (ValueError, TypeError):
            graph = "klein"
    online = lookup if lookup is not None else (
        lambda name, kind: online_lookup(name, kind, timeout=timeout)
    )
    findings: list[dict[str, Any]] = []
    for ref in collect_refs(body):
        found = local_lookup(ref["name"], extras_path=extras_path)
        checked_online = False
        if found is None and ref["name"]:
            checked_online = True
            try:
                hit = online(ref["name"], ref["kind"])
            except Exception:  # noqa: BLE001 - a lookup miss must not stop the page
                hit = None
            if isinstance(hit, dict) and hit:
                found = dict(hit)
        finding: dict[str, Any] = {
            "node": ref["node"],
            "kind": ref["kind"],
            "name": ref["name"],
            "checked_online": checked_online,
        }
        if found is None:
            finding.update(
                {
                    "status": "unresolved",
                    "source": "",
                    "model_name": "",
                    "version_name": "",
                    "base": "",
                    "family": ci.weight_family(ref["name"]),
                    "filename": ci.salad_filename(ref["name"]),
                    "url": "",
                    "compatible": None,
                }
            )
        else:
            family = str(found.get("family") or "") or ci.weight_family(
                str(found.get("base") or "") or str(found.get("filename") or "")
            )
            finding.update(
                {
                    "status": "resolved",
                    "source": str(found.get("source") or ""),
                    "model_name": str(found.get("model_name") or ""),
                    "version_name": str(found.get("version_name") or ""),
                    "base": str(found.get("base") or ""),
                    "family": family,
                    "filename": str(found.get("filename") or ""),
                    "url": str(found.get("url") or ""),
                    "compatible": _compatible(family, str(graph), found.get("item")),
                }
            )
        findings.append(finding)
    return findings


def unresolved(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in findings if f.get("status") != "resolved"]


def format_findings(findings: list[dict[str, Any]]) -> str:
    """One line per weight, for the AI context and the log."""
    if not findings:
        return "(the request references no LoRA, checkpoint, CLIP or VAE)"
    lines: list[str] = []
    for f in findings:
        bits = [f"{f.get('kind')} #{f.get('node')} {f.get('name') or '(empty)'}"]
        if f.get("status") == "resolved":
            who = str(f.get("model_name") or "")
            ver = str(f.get("version_name") or "")
            fam = str(f.get("family") or f.get("base") or "")
            src = str(f.get("source") or "")
            bits.append(f"-> {who or 'known'}" + (f" / {ver}" if ver else ""))
            if fam:
                bits.append(f"family={fam}")
            bits.append(f"source={src}")
            compat = f.get("compatible")
            if compat is True:
                bits.append("compatible with the replica")
            elif compat is False:
                bits.append("NOT compatible with the replica")
            if f.get("url"):
                bits.append(str(f["url"]))
        else:
            checked = "checked online" if f.get("checked_online") else "not checked online"
            bits.append(f"-> UNRESOLVED ({checked})")
            if f.get("family"):
                bits.append(f"family={f['family']}")
        lines.append(" ".join(str(b) for b in bits if b))
    return "\n".join(lines)
