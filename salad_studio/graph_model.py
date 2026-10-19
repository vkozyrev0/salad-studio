"""The prompt graph as data. No Flet, no Tk, no drawing.

``GraphModel`` is the single source of truth for the graph pane: nodes with
their ports and widget rows, edges between ports, the two-id selection, and
the view transform. Every gesture is a function from one model to the next,
and ``render`` and ``hit_test`` are pure functions of a model, so a drag is a
model change and a repaint, nothing else.

The layout keeps the Tk pane's look: one column per class, cards sized to
their rows, widget rows below link rows, a title header, and wires that leave
an output port on the right edge and enter an input port on the left edge.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

Prompt = dict[str, Any]

# Card metrics, carried from the JointJS page (graph_html/viewer.html) so the
# cards keep the size they had: 30 px header, 10 px body padding, 26 px rows,
# a 96 px label column and a 7 px character estimate.
HEADER_H = 30.0
BODY_PAD = 10.0
ROW_H = 26.0
LABEL_COL = 96.0
CHAR_W = 6.6
CARD_MIN_W = 240.0
CARD_MAX_W = 560.0
COLUMN_GAP = 140.0
ROW_GAP = 48.0
PAGE_PAD = 24.0
PORT_R = 4.5

ZOOM_MIN = 0.25
ZOOM_MAX = 2.4
ZOOM_STEP = 1.1

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

_GRAPH_COLUMNS: dict[str, int] = {
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

_UNKNOWN_COLUMN = 6

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

def _lg_origin_slot(src: dict[str, Any], dest_key: str) -> int:
    want = _LG_KEY_TYPE.get(dest_key.lower(), dest_key.upper())
    outs = _lg_outputs(str(src.get("class_type") or ""))
    for i, (_name, typ) in enumerate(outs):
        if typ == want:
            return i
    return 0

def _lg_outputs(cls: str) -> list[tuple[str, str]]:
    return list(_LG_OUTPUTS.get(cls) or [("OUT", "*")])

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

def is_link(val: Any) -> bool:
    return (
        isinstance(val, list)
        and len(val) == 2
        and isinstance(val[0], (str, int))
        and isinstance(val[1], int)
    )

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

def node_title(node: dict[str, Any], prompt: Prompt | None = None, nid: str = "") -> str:
    cls = str(node.get("class_type") or "")
    if cls == "CLIPTextEncode" and prompt and nid:
        if _clip_role(nid, prompt) == 1:
            return "CLIP Text Encode (Negative Prompt)"
        if _clip_role(nid, prompt) == 0:
            return "CLIP Text Encode (Prompt)"
    return CLASS_TITLE.get(cls, cls or "Node")

def slot_color(name: str, class_type: str = "") -> str:
    key = (name or "").lower()
    if key in SLOT_COLOR:
        return SLOT_COLOR[key]
    return OUTPUT_COLOR.get(class_type, "#9E9E9E")

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

def toggle_live_selection(selected: list[str], nid: str) -> list[str]:
    """Toggle one card in the two-id selection the Swap button reads."""
    nid = str(nid)
    if nid in selected:
        return [s for s in selected if s != nid]
    if len(selected) >= 2:
        return [selected[1], nid]
    return [*selected, nid]

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

_COLUMN = _GRAPH_COLUMNS


@dataclass(frozen=True)
class Port:
    name: str
    key: str
    kind: str  # "in" or "out"
    color: str
    y: float  # relative to the card's top edge


@dataclass(frozen=True)
class Node:
    id: str
    class_type: str
    title: str
    x: float
    y: float
    w: float
    h: float
    ins: tuple[Port, ...] = ()
    outs: tuple[Port, ...] = ()
    rows: tuple[tuple[str, str], ...] = ()  # (key, value) widget rows
    note: str = ""  # the CLIP text shown inside a text-encode card

    def port(self, key: str, kind: str) -> Port | None:
        for p in (self.ins if kind == "in" else self.outs):
            if p.key == key:
                return p
        return None

    def port_point(self, port: Port) -> tuple[float, float]:
        x = self.x if port.kind == "in" else self.x + self.w
        return x, self.y + port.y

    def contains(self, wx: float, wy: float) -> bool:
        return self.x <= wx <= self.x + self.w and self.y <= wy <= self.y + self.h


@dataclass(frozen=True)
class Edge:
    source: str
    source_key: str
    target: str
    target_key: str
    color: str


@dataclass(frozen=True)
class ViewTransform:
    """World to screen is ``p * scale + offset``. Zoom keeps a chosen point fixed."""

    ox: float = 0.0
    oy: float = 0.0
    scale: float = 1.0

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale + self.ox, y * self.scale + self.oy

    def to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self.ox) / self.scale, (sy - self.oy) / self.scale

    def zoomed_at(self, factor: float, sx: float, sy: float) -> "ViewTransform":
        """Scale by ``factor`` keeping the screen point under (sx, sy) still."""
        scale = min(ZOOM_MAX, max(ZOOM_MIN, self.scale * factor))
        wx, wy = self.to_world(sx, sy)
        return ViewTransform(sx - wx * scale, sy - wy * scale, scale)

    def panned(self, dx: float, dy: float) -> "ViewTransform":
        return replace(self, ox=self.ox + dx, oy=self.oy + dy)


@dataclass(frozen=True)
class GraphModel:
    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()
    selected: tuple[str, ...] = ()
    view: ViewTransform = field(default_factory=ViewTransform)
    origin: tuple[str, str] = ("", "")  # the last edit, so a caller can skip a relayout
    hint: str = ""

    def node(self, nid: str) -> Node | None:
        for n in self.nodes:
            if n.id == nid:
                return n
        return None

    def with_node(self, node: Node) -> "GraphModel":
        return replace(self, nodes=tuple(node if n.id == node.id else n for n in self.nodes))

    def with_selection(self, ids: Iterable[str]) -> "GraphModel":
        return replace(self, selected=tuple(ids)[:2])

    def with_view(self, view: ViewTransform) -> "GraphModel":
        return replace(self, view=view)


# --------------------------------------------------------------------- layout


def _widget_rows(nid: str, node: dict[str, Any], lookup: dict[str, str]) -> list[tuple[str, str]]:
    return [
        (r["key"], r["value"])
        for r in node_rows(node, lookup)
        if r["kind"] == "widget"
    ]


def clip_note(node: dict[str, Any]) -> str:
    if str(node.get("class_type") or "") != "CLIPTextEncode":
        return ""
    text = str((node.get("inputs") or {}).get("text") or "").replace("\n", " ").strip()
    return text if len(text) <= 160 else text[:159] + "…"


def _card_size(title: str, rows: list[tuple[str, str]], n_ins: int, n_out: int, note: str) -> tuple[float, float]:
    longest = max([len(title) + 6] + [len(k) + len(v) + 4 for k, v in rows])
    w = max(CARD_MIN_W, LABEL_COL + 36 + longest * CHAR_W)
    w = min(CARD_MAX_W, w)
    body_rows = max(1, n_ins + n_out + len(rows))
    h = HEADER_H + BODY_PAD * 2 + body_rows * ROW_H + (ROW_H if note else 0)
    return w, h


def _column_of(class_type: str) -> int:
    return _COLUMN.get(class_type, 6)


def _column_order(nid: str, node: dict[str, Any]) -> tuple[int, int]:
    """Sort inside a column the way the Tk pane does: loaders first, then ids."""
    cls = str(node.get("class_type") or "")
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
    return order, int(nid) if str(nid).isdigit() else 0


def layout(prompt: Prompt, loras: dict[str, str] | None = None) -> GraphModel:
    """Prompt JSON to a fresh model. Pure; the only store read is the LoRA lookup."""
    if loras is None:
        loras = lora_lookup()
    ids = {str(k) for k, v in prompt.items() if isinstance(v, dict)}
    cards: dict[str, dict[str, Any]] = {}
    for nid, node in prompt.items():
        nid = str(nid)
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "Node")
        title = f"#{nid}  {node_title(node, prompt, nid)}"
        ins = [k for k, v in (node.get("inputs") or {}).items() if is_link(v)]
        outs = [name for name, _typ in _lg_outputs(cls)]
        rows = _widget_rows(nid, node, loras)
        note = clip_note(node)
        w, h = _card_size(title, rows, len(ins), len(outs), note)
        cards[nid] = {
            "node": node,
            "cls": cls,
            "title": title,
            "ins": ins,
            "outs": outs,
            "rows": rows,
            "note": note,
            "w": w,
            "h": h,
            "column": _column_of(cls),
        }

    buckets: dict[int, list[str]] = {}
    for nid, card in cards.items():
        buckets.setdefault(card["column"], []).append(nid)
    col_w = {c: max(cards[n]["w"] for n in nids) for c, nids in buckets.items()}
    col_x: dict[int, float] = {}
    x = PAGE_PAD
    for col in sorted(buckets):
        col_x[col] = x
        x += col_w[col] + COLUMN_GAP

    nodes: list[Node] = []
    for col, nids in sorted(buckets.items()):
        nids.sort(key=lambda n: _column_order(n, cards[n]["node"]))
        y = PAGE_PAD
        for nid in nids:
            card = cards[nid]
            ins = tuple(
                Port(name=k, key=k, kind="in", color=slot_color(k, card["cls"]),
                     y=HEADER_H + BODY_PAD + i * ROW_H + ROW_H / 2)
                for i, k in enumerate(card["ins"])
            )
            base = len(ins)
            outs = tuple(
                Port(name=name, key=f"out_{i}", kind="out",
                     color=slot_color(name.lower(), card["cls"]),
                     y=HEADER_H + BODY_PAD + (base + i) * ROW_H + ROW_H / 2)
                for i, name in enumerate(card["outs"])
            )
            nodes.append(
                Node(
                    id=nid,
                    class_type=card["cls"],
                    title=card["title"],
                    x=col_x[col],
                    y=y,
                    w=col_w[col],
                    h=card["h"],
                    ins=ins,
                    outs=outs,
                    rows=tuple(card["rows"]),
                    note=card["note"],
                )
            )
            y += card["h"] + ROW_GAP

    edges: list[Edge] = []
    by_id = {n.id: n for n in nodes}
    for src, dst, key in graph_edges(prompt):
        if src not in ids or dst not in ids or src not in by_id or dst not in by_id:
            continue
        slot = _lg_origin_slot(prompt[src] if isinstance(prompt[src], dict) else {}, key)
        edges.append(
            Edge(
                source=src,
                source_key=f"out_{slot}",
                target=dst,
                target_key=key,
                color=slot_color(key, str((prompt[src] or {}).get("class_type") or "")),
            )
        )
    return GraphModel(nodes=tuple(nodes), edges=tuple(edges), origin=("layout", ""))


def relayout(model: GraphModel, prompt: Prompt) -> GraphModel:
    """Lay a new prompt out and keep the view and the selection the user is in."""
    fresh = layout(prompt)
    keep = tuple(n for n in model.selected if fresh.node(n) is not None)
    return replace(fresh, view=model.view, selected=keep)


# ----------------------------------------------------------------- gestures


def hit_test(model: GraphModel, sx: float, sy: float) -> Node | None:
    """The topmost node under a screen point. Later nodes draw on top."""
    wx, wy = model.view.to_world(sx, sy)
    for node in reversed(model.nodes):
        if node.contains(wx, wy):
            return node
    return None


def toggle_selection(selected: tuple[str, ...], nid: str) -> tuple[str, ...]:
    """Two-id selection: a third pick drops the oldest. Pressing a picked node clears it."""
    return tuple(toggle_live_selection(list(selected), nid))


def begin_drag(model: GraphModel, sx: float, sy: float) -> tuple[GraphModel, str | None]:
    node = hit_test(model, sx, sy)
    if node is None:
        return model, None
    return model.with_selection(toggle_selection(model.selected, node.id)), node.id


def drag_node(model: GraphModel, nid: str, dx: float, dy: float) -> GraphModel:
    """Move a node by a world delta. Edges follow because they are drawn from ports."""
    node = model.node(nid)
    if node is None or (dx == 0 and dy == 0):
        return model
    moved = replace(node, x=node.x + dx, y=node.y + dy)
    return replace(model.with_node(moved), origin=("node", nid))


def zoom_at(model: GraphModel, factor: float, sx: float, sy: float) -> GraphModel:
    return model.with_view(model.view.zoomed_at(factor, sx, sy))


def pan_by(model: GraphModel, dx: float, dy: float) -> GraphModel:
    return model.with_view(model.view.panned(dx, dy))


def fit_view(model: GraphModel, width: float, height: float, *, padding: float = 48.0) -> GraphModel:
    """Scale and centre so the whole graph fits a viewport. Never enlarges past 1."""
    if not model.nodes or width <= 0 or height <= 0:
        return model
    right = max(n.x + n.w for n in model.nodes)
    bottom = max(n.y + n.h for n in model.nodes)
    scale = min(1.0, (width - padding * 2) / right, (height - padding * 2) / bottom)
    scale = max(ZOOM_MIN, scale)
    ox = (width - right * scale) / 2
    oy = (height - bottom * scale) / 2
    return model.with_view(ViewTransform(ox, oy, scale))


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
