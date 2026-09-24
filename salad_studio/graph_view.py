"""Prompt-editor graph: JointJS HTML (manhattan wires) in a WebView.

Live view is ``graph_html/viewer.html`` + vendored ``joint.min.js``, embedded
with tkwry (WebView2). Python only emits node/link JSON (``prompt_to_joint``)
and pushes it in place with ``graph_host_refresh``; the same JSON feeds the
LiteGraph page ("Open as Comfy"). No Graphviz / grandalf path exists — the
JointJS page owns the routing. Without the WebView2 embed the pane is a text
hint pointing at "Open in browser" (selection needs the embed's IPC).
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

import tkinter as tk
from tkinter import ttk

from salad_studio.theme import style_canvas

Prompt = dict[str, Any]
SwapFn = Callable[[Prompt], None]

CLASS_TITLE: dict[str, str] = {
    "UNETLoader": "Load Diffusion Model",
    "CLIPLoader": "Load CLIP",
    "VAELoader": "Load VAE",
    "LoraLoader": "Load LoRA",
    "CLIPTextEncode": "CLIP Text Encode (Prompt)",
    "EmptyFlux2LatentImage": "Empty Flux2 Latent",
    "EmptyLatentImage": "Empty Latent",
    "EmptySD3LatentImage": "Empty SD3 Latent",
    "RandomNoise": "Random Noise",
    "KSamplerSelect": "KSampler Select",
    "KSampler": "KSampler",
    "BasicScheduler": "Scheduler",
    "Flux2Scheduler": "Flux2 Scheduler",
    "CFGGuider": "CFG Guider",
    "SamplerCustomAdvanced": "Sampler Custom",
    "VAEDecode": "VAE Decode",
    "SaveImage": "Save Image",
}

# ComfyUI slot colors (approx. Lite Graph defaults).
SLOT_COLOR: dict[str, str] = {
    "model": "#B39DDB",
    "clip": "#F5D76E",
    "positive": "#FFA726",
    "negative": "#FFA726",
    "text": "#FFA726",
    "latent_image": "#EC407A",
    "samples": "#EC407A",
    "latent": "#EC407A",
    "vae": "#EF5350",
    "images": "#4FC3F7",
    "image": "#4FC3F7",
    "noise": "#CE93D8",
    "guider": "#AED581",
    "sampler": "#80CBC4",
    "sigmas": "#90CAF9",
    "width": "#B0BEC5",
    "height": "#B0BEC5",
}

OUTPUT_COLOR: dict[str, str] = {
    "UNETLoader": SLOT_COLOR["model"],
    "CLIPLoader": SLOT_COLOR["clip"],
    "VAELoader": SLOT_COLOR["vae"],
    "LoraLoader": SLOT_COLOR["model"],
    "CLIPTextEncode": SLOT_COLOR["positive"],
    "EmptyFlux2LatentImage": SLOT_COLOR["latent"],
    "EmptyLatentImage": SLOT_COLOR["latent"],
    "EmptySD3LatentImage": SLOT_COLOR["latent"],
    "RandomNoise": SLOT_COLOR["noise"],
    "KSamplerSelect": SLOT_COLOR["sampler"],
    "BasicScheduler": SLOT_COLOR["sigmas"],
    "Flux2Scheduler": SLOT_COLOR["sigmas"],
    "CFGGuider": SLOT_COLOR["guider"],
    "SamplerCustomAdvanced": SLOT_COLOR["latent"],
    "VAEDecode": SLOT_COLOR["image"],
}

_BG = "#1A1A1A"
_GRID = "#262626"
_CARD = "#2B2B2B"
_HEADER = "#323232"
_FIELD = "#1F1F1F"
_INK = "#E6E6E6"
_MUTED = "#9A9A9A"
_SELECT = "#D9772A"

_NODE_W = 280.0
_NODE_W_MAX = 560.0
_LABEL_COL = 96.0
_CHAR_PX = 7.4
_GAP_X = 96.0
_GAP_Y = 36.0
_PAD = 40.0
_HEADER_H = 28.0
_ROW_H = 22.0
_CORNER = 10
_PORT = 5.5
_WIRE_STUB = 20.0
_WIRE_PAD = 6.0
_WIRE_GAP = 16.0
_WIRE_CORNER = 14.0
_WIRE_LANE = 7.0


def is_link(val: Any) -> bool:
    return (
        isinstance(val, list)
        and len(val) == 2
        and isinstance(val[0], (str, int))
        and isinstance(val[1], int)
    )


def graph_edges(prompt: Prompt) -> list[tuple[str, str, str]]:
    """(src_id, dst_id, input_name) for every node-ref input."""
    ids = {str(k) for k in prompt}
    edges: list[tuple[str, str, str]] = []
    for nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        for key, val in inputs.items():
            if is_link(val) and str(val[0]) in ids:
                edges.append((str(val[0]), str(nid), str(key)))
    return edges


_LG_OUTPUTS: dict[str, list[tuple[str, str]]] = {
    "UNETLoader": [("MODEL", "MODEL")],
    "CLIPLoader": [("CLIP", "CLIP")],
    "VAELoader": [("VAE", "VAE")],
    "LoraLoader": [("MODEL", "MODEL"), ("CLIP", "CLIP")],
    "CLIPTextEncode": [("CONDITIONING", "CONDITIONING")],
    "EmptyFlux2LatentImage": [("LATENT", "LATENT")],
    "EmptyLatentImage": [("LATENT", "LATENT")],
    "VAEDecode": [("IMAGE", "IMAGE")],
    "VAEEncode": [("LATENT", "LATENT")],
    "SamplerCustomAdvanced": [("LATENT", "LATENT")],
    "KSampler": [("LATENT", "LATENT")],
    "CFGGuider": [("GUIDER", "GUIDER")],
    "RandomNoise": [("NOISE", "NOISE")],
    "KSamplerSelect": [("SAMPLER", "SAMPLER")],
    "Flux2Scheduler": [("SIGMAS", "SIGMAS")],
    "BasicScheduler": [("SIGMAS", "SIGMAS")],
    "SaveImage": [],
    "LoadImage": [("IMAGE", "IMAGE")],
}

_LG_KEY_TYPE = {
    "model": "MODEL",
    "clip": "CLIP",
    "vae": "VAE",
    "positive": "CONDITIONING",
    "negative": "CONDITIONING",
    "conditioning": "CONDITIONING",
    "samples": "LATENT",
    "latent_image": "LATENT",
    "images": "IMAGE",
    "image": "IMAGE",
    "pixels": "IMAGE",
    "noise": "NOISE",
    "guider": "GUIDER",
    "sampler": "SAMPLER",
    "sigmas": "SIGMAS",
}


def _lg_outputs(cls: str) -> list[tuple[str, str]]:
    return list(_LG_OUTPUTS.get(cls) or [("OUT", "*")])


def _lg_origin_slot(src: dict[str, Any], dest_key: str) -> int:
    want = _LG_KEY_TYPE.get(dest_key.lower(), dest_key.upper())
    outs = _lg_outputs(str(src.get("class_type") or ""))
    for i, (_name, typ) in enumerate(outs):
        if typ == want:
            return i
    return 0


def prompt_to_litegraph(prompt: Prompt) -> dict[str, Any]:
    """Comfy /prompt dict → LiteGraph serialize JSON (ComfyUI's editor engine)."""
    loras = lora_lookup()
    xy = layout_xy(prompt, loras=loras)
    nodes_out: list[dict[str, Any]] = []
    max_id = 0
    for nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        try:
            max_id = max(max_id, int(nid))
        except (TypeError, ValueError):
            continue
        cls = str(node.get("class_type") or "Node")
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        in_slots = []
        props: dict[str, str] = {}
        for key, val in inputs.items():
            if is_link(val):
                in_slots.append(
                    {"name": str(key), "type": _LG_KEY_TYPE.get(str(key).lower(), "*")}
                )
            else:
                props[str(key)] = str(val)
        if cls == "LoraLoader":
            label = lora_symbolic_name(node, loras)
            if label:
                props = {"name": label, **props}
        x0, y0 = xy.get(str(nid), (_PAD, _PAD))
        w, h = node_metrics(node, loras)
        nodes_out.append(
            {
                "id": int(nid) if str(nid).isdigit() else nid,
                "type": "comfy/" + cls,
                "title": f"#{nid}  {node_title(node, prompt, str(nid))}",
                "pos": [x0, y0],
                "size": [max(220.0, w * 0.7), max(80.0, h * 0.55)],
                "inputs": in_slots,
                "outputs": [
                    {"name": n, "type": t} for n, t in _lg_outputs(cls)
                ],
                "properties": props,
            }
        )
    links: list[list[Any]] = []
    lid = 1
    ids = {str(k) for k in prompt}
    for src, dst, key in graph_edges(prompt):
        if src not in ids or dst not in ids:
            continue
        sn = prompt.get(src) if isinstance(prompt.get(src), dict) else {}
        dn = prompt.get(dst) if isinstance(prompt.get(dst), dict) else {}
        d_inputs = (dn or {}).get("inputs") if isinstance((dn or {}).get("inputs"), dict) else {}
        in_keys = [k for k, v in d_inputs.items() if is_link(v)]
        try:
            in_slot = in_keys.index(key)
        except ValueError:
            in_slot = 0
        out_slot = _lg_origin_slot(sn or {}, key)
        sid = int(src) if str(src).isdigit() else src
        did = int(dst) if str(dst).isdigit() else dst
        links.append(
            [lid, sid, out_slot, did, in_slot, _LG_KEY_TYPE.get(key.lower(), "*")]
        )
        lid += 1
    return {
        "last_node_id": max_id,
        "last_link_id": lid,
        "nodes": nodes_out,
        "links": links,
        "groups": [],
        "config": {},
        "extra": {},
        "version": 0.4,
    }


def write_litegraph_page(prompt: Prompt, dest: Path | None = None) -> Path:
    """Write a LiteGraph HTML page (Comfy engine; wires may cross cards)."""
    here = Path(__file__).resolve().parent / "graph_html"
    template = (here / "litegraph.html").read_text(encoding="utf-8")
    payload = json.dumps(prompt_to_litegraph(prompt), ensure_ascii=False)
    html = template.replace(
        'window.STUDIO_GRAPH || {"nodes":[], "links":[]}',
        payload,
    )
    out = dest or (here / "_litegraph.html")
    out.write_text(html, encoding="utf-8")
    return out


_J_HEADER = 30.0
_J_ROW = 26.0
_J_TEXT_ROW = 16.0
_J_LABEL = 96.0
_J_PAD = 10.0
_J_CHAR = 7.0
_J_W_MIN = 320.0
_J_W_MAX = 720.0
# Column for a class type that is not in _COLUMN (never a sampler column).
_UNKNOWN_COLUMN = 6


def joint_row_center(index: int) -> float:
    """Y of a socket-row center. Matches the live page header, body pad, and row height."""
    return _J_HEADER + _J_PAD + index * _J_ROW + _J_ROW / 2.0


def joint_title_capacity() -> int:
    """Characters that fit the card header at the maximum card width."""
    return max(12, int((_J_W_MAX - 24) / _J_CHAR))


def joint_value_capacity() -> int:
    """Characters that fit a widget value beside its label at the maximum card width."""
    return max(8, int((_J_W_MAX - _J_LABEL - 36) / _J_CHAR))


def joint_card_title(
    nid: str, node: dict[str, Any], prompt: Prompt, lookup: dict[str, str] | None = None
) -> str:
    """Header text. A loader name that fits the card is kept whole."""
    cls = str(node.get("class_type") or "")
    base = node_title(node, prompt, str(nid))
    if cls == "LoraLoader":
        label = lora_symbolic_name(node, lookup)
        if label:
            base = label
    title = f"#{nid}  {base}"
    cap = joint_title_capacity()
    if len(title) > cap:
        title = title[: cap - 1] + "…"
    return title


def joint_fields(
    node: dict[str, Any], lookup: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Widget rows as {key, value, lines} for label + text-box cards."""
    out: list[dict[str, Any]] = []
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    cls = str(node.get("class_type") or "")
    for row in node_rows(node, lookup):
        if row["kind"] != "widget":
            continue
        key = row["key"]
        raw = row["value"]
        lines = 1
        if key == "name" and cls == "LoraLoader":
            full = lora_symbolic_name(node, lookup)
            if full:
                cap = joint_value_capacity()
                raw = full if len(full) <= cap else full[: cap - 1] + "…"
        if key == "text":
            src = str(inputs.get("text") or raw).replace("\n", " ").strip()
            lines = max(2, min(5, 1 + max(0, len(src) // 42)))
            cap = 42 * lines
            raw = src if len(src) <= cap else src[: cap - 1] + "…"
        out.append({"key": key, "value": raw, "lines": lines})
        if len(out) >= 8:
            break
    return out


def joint_card_metrics(
    fields: list[dict[str, Any]],
    n_in: int,
    n_out: int = 0,
    title: str = "",
) -> tuple[float, float]:
    longest = 0
    extra = 0.0
    for f in fields:
        lines = max(1, int(f.get("lines") or 1))
        val = str(f.get("value") or "")
        if lines <= 1:
            longest = max(longest, len(val), len(str(f.get("key") or "")))
        else:
            extra += (lines - 1) * _J_TEXT_ROW + 8
    w = _J_LABEL + 18 + longest * _J_CHAR + 18
    if title:
        w = max(w, 24 + len(title) * _J_CHAR)
    w = min(_J_W_MAX, max(_J_W_MIN, w))
    rows = max(1, n_in + n_out + len(fields))
    h = _J_HEADER + _J_PAD + rows * _J_ROW + extra + _J_PAD
    return w, h


def live_column(class_type: str) -> int:
    """Comfy column for a class. Unknown classes stay out of the sampler columns."""
    cls = str(class_type or "")
    if cls in _COLUMN:
        return _COLUMN[cls]
    return _UNKNOWN_COLUMN


def _joint_prepare(
    nid: str,
    node: dict[str, Any],
    prompt: Prompt,
    lookup: dict[str, str] | None = None,
) -> dict[str, Any]:
    cls = str(node.get("class_type") or "Node")
    in_ports: list[dict[str, Any]] = []
    for row in node_rows(node, lookup):
        if row["kind"] != "link":
            continue
        key = row["key"]
        in_ports.append(
            {
                "id": "in_" + key,
                "name": key,
                "color": slot_color(key, cls),
                "y": joint_row_center(len(in_ports)),
            }
        )
    fields = joint_fields(node, lookup)
    out_ports: list[dict[str, Any]] = []
    for i, (name, _typ) in enumerate(_lg_outputs(cls)):
        out_ports.append(
            {
                "id": f"out_{i}",
                "name": name,
                "color": slot_color(name.lower(), cls),
                "y": joint_row_center(len(in_ports) + i),
            }
        )
    title = joint_card_title(nid, node, prompt, lookup)
    w, h = joint_card_metrics(fields, len(in_ports), len(out_ports), title)
    return {
        "id": str(nid),
        "classType": cls,
        "column": live_column(cls),
        "w": w,
        "h": h,
        "title": title,
        "fields": fields,
        "inPorts": in_ports,
        "outPorts": out_ports,
    }


def _place_joint_columns(
    prompt: Prompt, prepared: list[dict[str, Any]]
) -> dict[str, tuple[float, float]]:
    """Left-to-right columns packed with the width and height JointJS will draw."""
    gap_x = 160.0
    gap_y = 56.0
    buckets: dict[int, list[str]] = {}
    size: dict[str, tuple[float, float]] = {}
    for node in prepared:
        nid = str(node["id"])
        buckets.setdefault(int(node["column"]), []).append(nid)
        size[nid] = (float(node["w"]), float(node["h"]))

    def _sort_key(nid: str) -> tuple[int, int, int]:
        node = prompt.get(nid) or {}
        cls = str(node.get("class_type") or "") if isinstance(node, dict) else ""
        role = _clip_role(nid, prompt) if cls == "CLIPTextEncode" else 0
        order = {
            "UNETLoader": 0,
            "CLIPLoader": 1,
            "VAELoader": 2,
            "EmptyFlux2LatentImage": 3,
            "RandomNoise": 0,
            "KSamplerSelect": 1,
            "Flux2Scheduler": 2,
            "BasicScheduler": 2,
            "CFGGuider": 3,
            "VAEDecode": 0,
            "SaveImage": 1,
        }.get(cls, 5)
        num = int(nid) if str(nid).isdigit() else 0
        return (order, role, num)

    col_w = {
        col: max(size[nid][0] for nid in nids) if nids else _J_W_MIN
        for col, nids in buckets.items()
    }
    x = _PAD
    col_x: dict[int, float] = {}
    for col in sorted(buckets):
        col_x[col] = x
        x += col_w[col] + gap_x
    placed: dict[str, tuple[float, float]] = {}
    for col, nids in sorted(buckets.items()):
        nids.sort(key=_sort_key)
        y = _PAD
        for nid in nids:
            _w, h = size[nid]
            placed[nid] = (col_x[col], y)
            y += h + gap_y
    return placed


def prompt_to_joint(
    prompt: Prompt, loras: dict[str, str] | None = None
) -> dict[str, Any]:
    """Comfy /prompt dict → JointJS cards + ports, packed to the drawn card size.

    ``loras`` is a pre-built ``lora_lookup()`` map; built here (one store read)
    when omitted so N LoRA cards do not each re-read the store.
    """
    if loras is None:
        loras = lora_lookup()
    prepared = [
        _joint_prepare(str(nid), node, prompt, loras)
        for nid, node in prompt.items()
        if isinstance(node, dict)
    ]
    xy = _place_joint_columns(prompt, prepared)
    nodes_out: list[dict[str, Any]] = []
    for node in prepared:
        x0, y0 = xy.get(node["id"], (_PAD, _PAD))
        nodes_out.append({**node, "x": x0, "y": y0})
    links: list[dict[str, str]] = []
    ids = {str(k) for k in prompt}
    for src, dst, key in graph_edges(prompt):
        if src not in ids or dst not in ids:
            continue
        sn = prompt.get(src) if isinstance(prompt.get(src), dict) else {}
        out_slot = _lg_origin_slot(sn or {}, key)
        links.append(
            {
                "source": str(src),
                "sourcePort": f"out_{out_slot}",
                "target": str(dst),
                "targetPort": f"in_{key}",
                "color": slot_color(key, str((sn or {}).get("class_type") or "")),
            }
        )
    return {"nodes": nodes_out, "links": links}


def write_graph_page(prompt: Prompt, dest: Path | None = None) -> Path:
    """Write the live JointJS HTML page for this prompt."""
    here = Path(__file__).resolve().parent / "graph_html"
    template = (here / "viewer.html").read_text(encoding="utf-8")
    payload = json.dumps(prompt_to_joint(prompt), ensure_ascii=False)
    html = template.replace("__STUDIO_GRAPH__", payload)
    out = dest or (here / "_current.html")
    out.write_text(html, encoding="utf-8")
    return out


def webview_user_dir() -> Path:
    """Writable WebView2 user-data folder (never next to python.exe)."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        path = base / "SaladStudio" / "WebView2"
    else:
        path = Path.home() / ".local" / "share" / "salad-studio" / "webview"
    path.mkdir(parents=True, exist_ok=True)
    return path


def slot_color(name: str, class_type: str = "") -> str:
    key = (name or "").lower()
    if key in SLOT_COLOR:
        return SLOT_COLOR[key]
    return OUTPUT_COLOR.get(class_type, "#9E9E9E")


def lora_query_keys(name: str) -> list[str]:
    """Lookup keys for one loader name: token-free URL, basename, filename stem."""
    raw = str(name or "").strip()
    if not raw:
        return []
    clean = raw.split("?")[0].strip()
    path = urlparse(clean).path if "://" in clean else clean
    base = Path(path).name.lower()
    keys = [clean.lower(), base]
    if base.endswith(".safetensors"):
        keys.append(base[: -len(".safetensors")])
    return [k for k in keys if k]


def lora_lookup(items: list[dict[str, Any]] | None = None) -> dict[str, str]:
    """``{loader-name key: catalog name}`` built from ONE LoRA store read.

    ``prompt_to_joint`` builds this once and threads it through the card
    helpers, so a graph with N LoRA nodes reads the store once, not 2N times.
    Pass ``items`` (raw store rows) to drive it without touching the store.
    """
    if items is None:
        try:
            import lora_store as ls

            items = ls.list_loras()
        except Exception:
            return {}
    out: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("name") or "").strip()
        if not label:
            continue
        src = item.get("source") if isinstance(item.get("source"), dict) else {}
        for cand in (src.get("filename"), src.get("download"), item.get("id")):
            for key in lora_query_keys(str(cand or "")):
                out.setdefault(key, label)
    return out


def lora_symbolic_name(
    node: dict[str, Any], lookup: dict[str, str] | None = None
) -> str:
    """Human LoRA name (catalog / Civitai tag), not the loader filename."""
    meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    lora_name = str(inputs.get("lora_name") or "")
    title = str(meta.get("title") or "")
    tag = str(meta.get("tag") or "")
    if lookup is None:
        lookup = lora_lookup()
    catalog = ""
    for key in (*lora_query_keys(lora_name), *lora_query_keys(title)):
        catalog = lookup.get(key) or ""
        if catalog:
            break
    internal = Path(unquote(urlparse(lora_name).path) if "://" in lora_name else lora_name).name
    for cand in (tag, catalog, Path(title).stem):
        text = str(cand or "").strip()
        if not text or text.isdigit() or text.startswith("http"):
            continue
        if text.lower() == internal.lower():
            continue
        if text.lower().endswith(".safetensors"):
            text = text[:-12]
        return text
    stem = Path(title or internal).stem
    if stem and stem.lower() != Path(internal).stem.lower():
        return stem
    return ""


def node_rows(
    node: dict[str, Any], lookup: dict[str, str] | None = None
) -> list[dict[str, str]]:
    """Display rows: linked sockets first, then widgets. No link payloads as text."""
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    rows: list[dict[str, str]] = []
    for key, val in inputs.items():
        if is_link(val):
            rows.append({"kind": "link", "key": str(key), "value": ""})
    cls = str(node.get("class_type") or "")
    if cls == "LoraLoader":
        label = lora_symbolic_name(node, lookup)
        if label:
            rows.append({"kind": "widget", "key": "name", "value": label})
    for key, val in inputs.items():
        if is_link(val):
            continue
        rows.append(
            {"kind": "widget", "key": str(key), "value": _fmt_value(key, val, node)}
        )
    return rows


def widget_rows(
    node: dict[str, Any], lookup: dict[str, str] | None = None
) -> list[tuple[str, str]]:
    return [
        (r["key"], r["value"])
        for r in node_rows(node, lookup)
        if r["kind"] == "widget"
    ]


def node_metrics(
    node: dict[str, Any], lookup: dict[str, str] | None = None
) -> tuple[float, float]:
    cls = str(node.get("class_type") or "")
    rows = node_rows(node, lookup)
    extra = 0.0
    if cls == "CLIPTextEncode":
        text = str((node.get("inputs") or {}).get("text") or "")
        lines = max(2, min(5, 1 + text.count("\n") + max(0, len(text) // 50)))
        extra = 8 + 14 * lines
        rows = [r for r in rows if r["key"] != "text"]
    longest = 0
    for row in rows:
        if row.get("kind") == "widget":
            longest = max(longest, len(row.get("value") or ""))
    need = _LABEL_COL + 12 + longest * _CHAR_PX + 18
    w = max(_NODE_W, 320.0 if cls == "CLIPTextEncode" else 0.0, need)
    w = min(_NODE_W_MAX, w)
    body = max(1, len(rows)) * _ROW_H + extra + 16
    return w, _HEADER_H + body


def layout_columns(prompt: Prompt) -> dict[str, tuple[int, int]]:
    """Left-to-right columns from sources; rows by numeric id inside a column."""
    ids = [str(k) for k, n in prompt.items() if isinstance(n, dict)]
    incoming: dict[str, set[str]] = {i: set() for i in ids}
    for src, dst, _k in graph_edges(prompt):
        if dst in incoming:
            incoming[dst].add(src)
    col = {i: 0 for i in ids}
    changed = True
    guard = 0
    while changed and guard < 64:
        changed = False
        guard += 1
        for i in ids:
            if not incoming[i]:
                continue
            c = 1 + max(col.get(p, 0) for p in incoming[i])
            if c > col[i]:
                col[i] = c
                changed = True
    by_col: dict[int, list[str]] = {}
    for i, c in col.items():
        by_col.setdefault(c, []).append(i)
    pos: dict[str, tuple[int, int]] = {}
    for c, nids in by_col.items():
        nids.sort(key=lambda x: int(x) if str(x).isdigit() else 0)
        for r, nid in enumerate(nids):
            pos[nid] = (c, r)
    return pos


_COLUMN: dict[str, int] = {
    "UNETLoader": 0,
    "CLIPLoader": 0,
    "VAELoader": 0,
    "LoraLoader": 1,
    "CLIPTextEncode": 2,
    "EmptyFlux2LatentImage": 2,
    "EmptyLatentImage": 2,
    "EmptySD3LatentImage": 2,
    "RandomNoise": 3,
    "KSamplerSelect": 3,
    "BasicScheduler": 3,
    "Flux2Scheduler": 3,
    "CFGGuider": 3,
    "SamplerCustomAdvanced": 4,
    "KSampler": 4,
    "VAEDecode": 5,
    "SaveImage": 5,
}


def _clip_role(nid: str, prompt: Prompt) -> int:
    """0 = positive, 1 = negative, 2 = other."""
    for node in prompt.values():
        if not isinstance(node, dict) or node.get("class_type") != "CFGGuider":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        pos, neg = inputs.get("positive"), inputs.get("negative")
        if is_link(pos) and str(pos[0]) == nid:
            return 0
        if is_link(neg) and str(neg[0]) == nid:
            return 1
    return 2


def layout_xy(
    prompt: Prompt,
    *,
    gap_x: float | None = None,
    gap_y: float | None = None,
    loras: dict[str, str] | None = None,
) -> dict[str, tuple[float, float]]:
    """Comfy-style columns: loaders → LoRA → CLIP/latent → sampler → decode."""
    gx = _GAP_X if gap_x is None else gap_x
    gy = _GAP_Y if gap_y is None else gap_y
    buckets: dict[int, list[str]] = {}
    for nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        col = _COLUMN.get(str(node.get("class_type") or ""), 3)
        buckets.setdefault(col, []).append(str(nid))

    def _sort_key(nid: str) -> tuple[int, int, int]:
        node = prompt.get(nid) or {}
        cls = str(node.get("class_type") or "")
        role = _clip_role(nid, prompt) if cls == "CLIPTextEncode" else 0
        order = {
            "UNETLoader": 0,
            "CLIPLoader": 1,
            "VAELoader": 2,
            "EmptyFlux2LatentImage": 3,
            "RandomNoise": 0,
            "KSamplerSelect": 1,
            "Flux2Scheduler": 2,
            "BasicScheduler": 2,
            "CFGGuider": 3,
            "VAEDecode": 0,
            "SaveImage": 1,
        }.get(cls, 5)
        num = int(nid) if str(nid).isdigit() else 0
        return (order, role, num)

    placed: dict[str, tuple[float, float]] = {}
    col_w: dict[int, float] = {}
    for col, nids in buckets.items():
        widths = []
        for nid in nids:
            node = prompt.get(nid) or {}
            w, _h = node_metrics(node if isinstance(node, dict) else {}, loras)
            widths.append(w)
        col_w[col] = max(widths) if widths else _NODE_W
    x = _PAD
    col_x: dict[int, float] = {}
    for col in sorted(buckets):
        col_x[col] = x
        x += col_w[col] + gx
    for col, nids in sorted(buckets.items()):
        nids.sort(key=_sort_key)
        y = _PAD
        for nid in nids:
            node = prompt.get(nid) or {}
            _w, h = node_metrics(node if isinstance(node, dict) else {}, loras)
            placed[nid] = (col_x[col], y)
            y += h + gy
    return placed


def boxes_from_xy(
    prompt: Prompt, xy: dict[str, tuple[float, float]]
) -> dict[str, tuple[float, float, float, float]]:
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for nid, (x0, y0) in xy.items():
        node = prompt.get(nid) or {}
        w, h = node_metrics(node if isinstance(node, dict) else {})
        boxes[str(nid)] = (x0, y0, x0 + w, y0 + h)
    return boxes


def node_boxes(prompt: Prompt) -> dict[str, tuple[float, float, float, float]]:
    """Axis-aligned card rects from ``layout_xy`` + ``node_metrics``."""
    return boxes_from_xy(prompt, layout_xy(prompt))


def segment_hits_box(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    box: tuple[float, float, float, float],
    pad: float = 0.0,
) -> bool:
    """True when a segment sample lands strictly inside ``box``."""
    rx0, ry0, rx1, ry1 = box
    rx0 -= pad
    ry0 -= pad
    rx1 += pad
    ry1 += pad
    eps = 0.51
    dist = math.hypot(x1 - x0, y1 - y0)
    n = max(2, int(dist / 4.0))
    for i in range(1, n):
        t = i / n
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t
        if rx0 + eps < x < rx1 - eps and ry0 + eps < y < ry1 - eps:
            return True
    return False


def path_hits_boxes(
    pts: list[tuple[float, float]],
    boxes: dict[str, tuple[float, float, float, float]],
    skip_ids: set[str],
) -> bool:
    for i in range(len(pts) - 1):
        for nid, box in boxes.items():
            if nid in skip_ids:
                continue
            if segment_hits_box(*pts[i], *pts[i + 1], box, _WIRE_PAD):
                return True
    return False


def _merge_ranges(ranges: list[tuple[float, float]]) -> list[list[float]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    out = [[ordered[0][0], ordered[0][1]]]
    for a, b in ordered[1:]:
        if a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _blocked_y(
    x0: float,
    x1: float,
    boxes: dict[str, tuple[float, float, float, float]],
    skip_ids: set[str],
    pad: float,
) -> list[list[float]]:
    xa, xb = (x0, x1) if x0 <= x1 else (x1, x0)
    ranges: list[tuple[float, float]] = []
    for nid, (rx0, ry0, rx1, ry1) in boxes.items():
        if nid in skip_ids:
            continue
        if rx1 + pad < xa or rx0 - pad > xb:
            continue
        ranges.append((ry0 - pad, ry1 + pad))
    return _merge_ranges(ranges)


def _y_free(y: float, ranges: list[list[float]]) -> bool:
    return all(not (a <= y <= b) for a, b in ranges)


def pick_clear_y(
    prefer: list[float],
    x0: float,
    x1: float,
    boxes: dict[str, tuple[float, float, float, float]],
    skip_ids: set[str],
    y_min: float,
    y_max: float,
) -> float:
    ranges = _blocked_y(x0, x1, boxes, skip_ids, _WIRE_PAD)
    for y in prefer:
        if _y_free(y, ranges):
            return y
    cands: list[float] = []
    prev = y_min
    for a, b in ranges:
        if a - prev >= _WIRE_GAP:
            cands.append((prev + a) / 2)
        prev = max(prev, b)
    if y_max - prev >= _WIRE_GAP:
        cands.append((prev + y_max) / 2)
    target = prefer[0] if prefer else 0.0
    if cands:
        return min(cands, key=lambda y: abs(y - target))
    if ranges:
        above = ranges[0][0] - 14
        below = ranges[-1][1] + 14
        return below if abs(below - target) <= abs(above - target) else above
    return target


def _dedupe_pts(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in pts:
        if not out or abs(out[-1][0] - p[0]) > 0.5 or abs(out[-1][1] - p[1]) > 0.5:
            out.append(p)
    return out


def route_wire(
    sx: float,
    sy: float,
    dx: float,
    dy: float,
    boxes: dict[str, tuple[float, float, float, float]],
    src_id: str,
    dst_id: str,
) -> list[tuple[float, float]]:
    """Orthogonal polyline from output port to input port that misses cards.

    Same-column LoRA chains go through the gap between the two boxes.
    Skip-column wires (VAE, last LoRA → sampler) use a clear y-lane in the
    gutters, or run below the stack if no gap lines up.
    """
    skip = {str(src_id), str(dst_id)}
    stub = _WIRE_STUB
    if boxes:
        y_min = min(b[1] for b in boxes.values()) - 24
        y_max = max(b[3] for b in boxes.values()) + 40
    else:
        y_min, y_max = min(sy, dy) - 24, max(sy, dy) + 40
    src_box = boxes.get(str(src_id))
    dst_box = boxes.get(str(dst_id))
    same_col = bool(
        src_box
        and dst_box
        and not (src_box[2] < dst_box[0] or dst_box[2] < src_box[0])
    )
    if same_col and src_box and dst_box:
        if src_box[3] <= dst_box[1]:
            gap_y = (src_box[3] + dst_box[1]) / 2
        elif dst_box[3] <= src_box[1]:
            gap_y = (dst_box[3] + src_box[1]) / 2
        else:
            gap_y = pick_clear_y(
                [dy, sy], sx + stub, dx - stub, boxes, skip, y_min, y_max
            )
        x_right = max(src_box[2], dst_box[2]) + stub
        x_left = min(src_box[0], dst_box[0]) - stub
        pts = _dedupe_pts(
            [
                (sx, sy),
                (x_right, sy),
                (x_right, gap_y),
                (x_left, gap_y),
                (x_left, dy),
                (dx, dy),
            ]
        )
        if not path_hits_boxes(pts, boxes, skip):
            return pts
    x_out = sx + stub
    x_in = dx - stub
    clear_y = pick_clear_y([dy, sy], x_out, x_in, boxes, skip, y_min, y_max)
    pts = [(sx, sy), (x_out, sy)]
    if abs(clear_y - sy) > 1:
        pts.append((x_out, clear_y))
    if abs(x_in - x_out) > 1:
        pts.append((x_in, clear_y))
    if abs(clear_y - dy) > 1:
        pts.append((x_in, dy))
    pts.append((dx, dy))
    pts = _dedupe_pts(pts)
    if path_hits_boxes(pts, boxes, skip):
        pts = _dedupe_pts(
            [
                (sx, sy),
                (x_out, sy),
                (x_out, y_max),
                (x_in, y_max),
                (x_in, dy),
                (dx, dy),
            ]
        )
    return pts


def chamfer_polyline(
    pts: list[tuple[float, float]], cut: float = _WIRE_CORNER
) -> list[tuple[float, float]]:
    """Truncate 90° corners with two extra points (no circular arc)."""
    if len(pts) < 3:
        return list(pts)
    out: list[tuple[float, float]] = [pts[0]]
    for i in range(1, len(pts) - 1):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        cx, cy = pts[i + 1]
        d1x, d1y = bx - ax, by - ay
        d2x, d2y = cx - bx, cy - by
        len1 = math.hypot(d1x, d1y)
        len2 = math.hypot(d2x, d2y)
        if len1 < 1 or len2 < 1:
            out.append((bx, by))
            continue
        r = min(cut, len1 * 0.4, len2 * 0.4)
        if r < 3:
            out.append((bx, by))
            continue
        out.append((bx - d1x / len1 * r, by - d1y / len1 * r))
        out.append((bx + d2x / len2 * r, by + d2y / len2 * r))
    out.append(pts[-1])
    return _dedupe_pts(out)


def densify_polyline(
    pts: list[tuple[float, float]], step: float = 12.0
) -> list[tuple[float, float]]:
    """Insert points along each segment so the drawn polyline stays in gutters."""
    if len(pts) < 2:
        return list(pts)
    out: list[tuple[float, float]] = [pts[0]]
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        dist = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(dist / step))
        for k in range(1, n + 1):
            t = k / n
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return _dedupe_pts(out)


def round_polyline(
    pts: list[tuple[float, float]], radius: float = _WIRE_CORNER
) -> list[tuple[float, float]]:
    """Back-compat: chamfer then densify (no circular arcs)."""
    return densify_polyline(chamfer_polyline(pts, cut=radius), step=10.0)


def _overlap_clusters(
    segs: list[tuple[int, int, float, float, float]],
) -> list[list[tuple[int, int, float, float, float]]]:
    """Group segments whose ranges overlap (or nearly touch)."""
    ordered = sorted(segs, key=lambda s: (s[3], s[0], s[1]))
    clusters: list[list[tuple[int, int, float, float, float]]] = []
    cur: list[tuple[int, int, float, float, float]] = []
    hi = -1e9
    for s in ordered:
        if not cur or s[3] <= hi + 4:
            cur.append(s)
            hi = max(hi, s[4])
        else:
            clusters.append(cur)
            cur = [s]
            hi = s[4]
    if cur:
        clusters.append(cur)
    return clusters


def separate_parallel_wires(
    paths: list[list[tuple[float, float]]], lane: float = _WIRE_LANE
) -> list[list[tuple[float, float]]]:
    """Nudge collinear overlapping runs so stacked wires are readable."""
    out = [list(p) for p in paths]

    def _shift(vert: bool) -> None:
        segs: list[tuple[int, int, float, float, float]] = []
        for pi, pts in enumerate(out):
            for si in range(len(pts) - 1):
                x0, y0 = pts[si]
                x1, y1 = pts[si + 1]
                if vert:
                    if abs(x0 - x1) > 1 or abs(y0 - y1) < 10:
                        continue
                    segs.append((pi, si, (x0 + x1) / 2, min(y0, y1), max(y0, y1)))
                else:
                    if abs(y0 - y1) > 1 or abs(x0 - x1) < 10:
                        continue
                    segs.append((pi, si, (y0 + y1) / 2, min(x0, x1), max(x0, x1)))
        buckets: dict[int, list[tuple[int, int, float, float, float]]] = {}
        for s in segs:
            buckets.setdefault(int(round(s[2] / 4.0)), []).append(s)
        for group in buckets.values():
            for cluster in _overlap_clusters(group):
                if len(cluster) < 2:
                    continue
                n = len(cluster)
                for i, (pi, si, _mid, _lo, _hi) in enumerate(cluster):
                    delta = (i - (n - 1) / 2) * lane
                    x0, y0 = out[pi][si]
                    x1, y1 = out[pi][si + 1]
                    if vert:
                        out[pi][si] = (x0 + delta, y0)
                        out[pi][si + 1] = (x1 + delta, y1)
                    else:
                        out[pi][si] = (x0, y0 + delta)
                        out[pi][si + 1] = (x1, y1 + delta)

    _shift(True)
    _shift(False)
    return out


def node_title(node: dict[str, Any], prompt: Prompt | None = None, nid: str = "") -> str:
    cls = str(node.get("class_type") or "")
    if cls == "CLIPTextEncode" and prompt and nid:
        if _clip_role(nid, prompt) == 1:
            return "CLIP Text Encode (Negative Prompt)"
        if _clip_role(nid, prompt) == 0:
            return "CLIP Text Encode (Prompt)"
    return CLASS_TITLE.get(cls, cls or "Node")


def node_caption(nid: str, node: dict[str, Any]) -> tuple[str, str]:
    title = node_title(node)
    rows = widget_rows(node)
    sub = rows[0][1] if rows else ""
    return f"{nid}  {title}", sub[:48]


def swap_payloads(prompt: Prompt, id_a: str, id_b: str) -> Prompt:
    """Swap non-link inputs and ``_meta`` of two same-class nodes."""
    import copy

    out = copy.deepcopy(prompt)
    a, b = str(id_a), str(id_b)
    if a == b:
        raise ValueError("Pick two different nodes")
    na = out.get(a)
    nb = out.get(b)
    if not isinstance(na, dict) or not isinstance(nb, dict):
        raise ValueError("Unknown node")
    if str(na.get("class_type") or "") != str(nb.get("class_type") or ""):
        raise ValueError("Can only swap two nodes of the same type")
    ia = dict(na.get("inputs") or {})
    ib = dict(nb.get("inputs") or {})
    for key in set(ia) | set(ib):
        va, vb = ia.get(key), ib.get(key)
        if is_link(va) or is_link(vb):
            continue
        ia[key], ib[key] = vb, va
    na["inputs"] = ia
    nb["inputs"] = ib
    meta_a = na.get("_meta")
    meta_b = nb.get("_meta")
    if meta_b is not None:
        na["_meta"] = meta_b
    else:
        na.pop("_meta", None)
    if meta_a is not None:
        nb["_meta"] = meta_a
    else:
        nb.pop("_meta", None)
    return out


def _fmt_value(key: str, val: Any, node: dict[str, Any] | None = None) -> str:
    if key == "lora_name" and node:
        title = str(((node.get("_meta") or {}).get("title") or "")).strip()
        if title:
            return Path(title).name
    raw = str(val)
    if key in ("lora_name", "unet_name", "clip_name", "vae_name") and (
        raw.startswith("http://") or raw.startswith("https://")
    ):
        name = Path(unquote(urlparse(raw).path)).name
        raw = name if name.endswith(".safetensors") else raw
    if "\\" in raw or "/" in raw:
        raw = raw.replace("\\", "/").split("/")[-1]
    if key == "text":
        return raw.replace("\n", " ")[:72]
    if key in ("lora_name", "name", "unet_name", "clip_name", "vae_name"):
        return raw[:80]
    return raw[:48]


def toggle_live_selection(selected: list[str], nid: str) -> list[str]:
    """Toggle one card in the two-id selection the Swap button reads."""
    nid = str(nid)
    if nid in selected:
        return [s for s in selected if s != nid]
    if len(selected) >= 2:
        return [selected[1], nid]
    return [*selected, nid]


def apply_live_pane_message(
    prompt: Prompt,
    selected: list[str],
    message: dict[str, Any],
) -> tuple[Prompt, list[str]]:
    """Apply one live-pane message.

    ``select`` updates the selection only. ``position`` (a card drag) leaves
    the prompt and the selection unchanged. Neither message writes prompt JSON.
    """
    selected = list(selected)
    if not isinstance(message, dict):
        return prompt, selected
    op = str(message.get("op") or "")
    if op == "select":
        nid = str(message.get("id") or "")
        if not nid:
            return prompt, selected
        return prompt, toggle_live_selection(selected, nid)
    if op == "position":
        return prompt, selected
    return prompt, selected


def graph_host_refresh(prompt: Prompt, *, embedded_ready: bool) -> dict[str, str]:
    """How the host pushes a prompt into the live page.

    When the embedded page is already showing, return JS that replaces the
    graph in place. Otherwise the host loads the written HTML document.
    """
    if embedded_ready:
        payload = json.dumps(prompt_to_joint(prompt), ensure_ascii=False)
        return {
            "action": "eval_js",
            "script": f"window.studioReplaceGraph({payload});",
        }
    return {"action": "load_url"}


class GraphPane(ttk.Frame):
    """HTML JointJS graph (WebView2). Select two same-type cards, then Swap."""

    def __init__(self, master, *, on_swap: SwapFn | None = None) -> None:
        super().__init__(master)
        self.on_swap = on_swap
        self._prompt: Prompt = {}
        self._selected: list[str] = []
        self._web = None
        self._web_ok = False
        self._embedded_ready = False
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(
            bar,
            text="JointJS (wires route around cards). Drag empty space to pan, wheel to zoom.",
        ).pack(side="left")
        ttk.Button(bar, text="Open in browser", command=self._open_browser).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(bar, text="Open as Comfy", command=self._open_litegraph).pack(
            side="right", padx=(6, 0)
        )
        self._swap_btn = ttk.Button(bar, text="Swap selected", command=self._do_swap)
        self._swap_btn.pack(side="right", padx=(6, 0))
        ttk.Button(bar, text="Clear selection", command=self._clear_sel).pack(
            side="right"
        )
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        self._host = ttk.Frame(wrap)
        self._host.grid(row=0, column=0, sticky="nsew")
        self.canvas = tk.Canvas(wrap, highlightthickness=0, borderwidth=0)
        style_canvas(self.canvas, background=_BG)
        yscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        xscroll = ttk.Scrollbar(wrap, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set,
            background=_BG,
        )
        self._hint = ttk.Label(self, text="")
        self._hint.pack(fill="x", pady=(4, 0))
        page = write_graph_page(self._prompt)
        try:
            from tkwry import WebView

            self._web = WebView(
                self._host,
                app=str(page),
                user_data_dir=str(webview_user_dir()),
                background_color=(26, 26, 26, 255),
                on_creation_failed=self._on_web_fail,
                on_ipc=self._on_live_message,
            )
            self._web_ok = True
            self._web.when_ready(self._on_web_ready)
            self.canvas.grid_remove()
        except Exception as exc:
            self._on_web_fail(exc)

    def _embed_live(self) -> bool:
        """True only when the page is laid out and ``eval_js`` can actually run.

        tkwry refuses ``eval_js`` until the native view exists with laid-out
        host geometry, so the embed is not usable just because the object was
        constructed.
        """
        if self._web is None or not self._web_ok:
            return False
        if not self._embedded_ready:
            return False
        try:
            return bool(self._web.ready)
        except Exception:  # noqa: BLE001 - a broken webview is simply not ready
            return False

    def _eval_js(self, script: str) -> bool:
        """Run JS in the page. False means the caller must fall back to a load."""
        try:
            self._web.eval_js(script, on_error=self._on_eval_error)
            return True
        except Exception as exc:  # noqa: BLE001 - not ready, or the view is gone
            self._hint.configure(text=f"Graph refresh deferred: {exc}")
            return False

    def _on_eval_error(self, exc: object = None) -> None:
        """An async eval failure: reload the page instead of going stale."""
        self._hint.configure(text=f"Graph refresh failed ({exc}); reloading the page")
        self.after_idle(self._reload_page)

    def _on_web_ready(self) -> None:
        """The page is laid out: the graph can now be pushed in place."""
        self._embedded_ready = True
        try:
            self._hint.configure(text="")
        except tk.TclError:
            return
        self.after_idle(self._redraw)

    def _reload_page(self) -> None:
        if self._web is None or not self._web_ok:
            return
        page = write_graph_page(self._prompt)
        try:
            from tkwry._app import app_url

            self._web.load_url(app_url(page.name))
        except Exception as exc:  # noqa: BLE001
            self._hint.configure(text=f"Graph reload failed: {exc}")

    def _on_web_fail(self, exc: object = None) -> None:
        """No WebView2 embed: the canvas shows a hint and Swap is unreachable."""
        self._web_ok = False
        self._swap_btn.state(["disabled"])
        self._hint.configure(
            text=(
                f"WebView2 embed unavailable ({exc}); cards cannot be selected "
                "here. Use Open in browser."
            )
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

    def _open_browser(self) -> None:
        import webbrowser

        page = write_graph_page(self._prompt)
        webbrowser.open(page.resolve().as_uri())

    def _open_litegraph(self) -> None:
        import webbrowser

        page = write_litegraph_page(self._prompt)
        webbrowser.open(page.resolve().as_uri())

    def set_prompt(self, prompt: Prompt | None) -> None:
        self._prompt = dict(prompt or {})
        self._selected = [s for s in self._selected if s in self._prompt]
        self._redraw()

    def _clear_sel(self) -> None:
        self._selected = []
        self._redraw()

    def _on_live_message(self, message: str) -> None:
        """WebView2 host message from a card click or drag."""
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, dict):
            return
        self._prompt, self._selected = apply_live_pane_message(
            self._prompt, self._selected, msg
        )
        if msg.get("op") == "select":
            self._hint.configure(
                text=("Selected " + ", ".join(self._selected)) if self._selected else "Selection cleared"
            )

    def _do_swap(self) -> None:
        if not self._web_ok:
            # Selection arrives only over the embed's IPC; the canvas fallback
            # draws no cards, so there is nothing to swap.
            self._hint.configure(
                text="Swap needs the WebView2 embed. Use Open in browser."
            )
            return
        if len(self._selected) != 2:
            self._hint.configure(text="Select two nodes first.")
            return
        a, b = self._selected
        try:
            nxt = swap_payloads(self._prompt, a, b)
        except ValueError as e:
            self._hint.configure(text=str(e))
            return
        self._hint.configure(text=f"Swapped {a} and {b}")
        self._selected = []
        if self.on_swap:
            self.on_swap(nxt)
        else:
            self.set_prompt(nxt)

    def _draw_grid(self, width: float, height: float) -> None:
        step = 24
        for x in range(0, int(width) + step, step):
            self.canvas.create_line(x, 0, x, height, fill=_GRID, width=1)
        for y in range(0, int(height) + step, step):
            self.canvas.create_line(0, y, width, y, fill=_GRID, width=1)

    def _redraw(self) -> None:
        self.canvas.delete("all")
        prompt = self._prompt
        plan = graph_host_refresh(prompt, embedded_ready=self._embed_live())
        if plan["action"] == "eval_js" and self._web is not None:
            # An in-place replace needs a laid-out page; if it cannot run yet
            # (or ever), fall through to a full load rather than leaving the
            # pane stuck on the old graph.
            if self._eval_js(plan["script"]):
                return
        if self._web is not None and self._web_ok:
            page = write_graph_page(prompt)
            try:
                from tkwry._app import app_url

                self._web.load_url(app_url(page.name))
            except Exception as exc:
                self._hint.configure(text=f"Graph reload failed: {exc}")
            return
        if not prompt:
            self.canvas.create_text(
                16, 16, anchor="nw", fill=_MUTED, text="No prompt graph."
            )
            return
        self.canvas.create_text(
            16,
            16,
            anchor="nw",
            fill=_MUTED,
            width=520,
            text=(
                "HTML graph opens in the browser. Click Open in browser "
                "(it writes the page on demand). WebView2 embed needs tkwry."
            ),
        )


def _wrap(text: str, width: int) -> list[str]:
    words = (text or "").replace("\n", " ").split()
    lines: list[str] = []
    cur = ""
    for w in words:
        nxt = f"{cur} {w}".strip()
        if len(nxt) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = nxt
    if cur:
        lines.append(cur)
    return lines or [""]


def _rounded_rect(
    canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, **kw: Any
) -> int:
    r = _CORNER
    pts = [
        x0 + r, y0,
        x1 - r, y0,
        x1, y0,
        x1, y0 + r,
        x1, y1 - r,
        x1, y1,
        x1 - r, y1,
        x0 + r, y1,
        x0, y1,
        x0, y1 - r,
        x0, y0 + r,
        x0, y0,
        x0 + r, y0,
    ]
    return canvas.create_polygon(pts, smooth=True, splinesteps=16, **kw)
