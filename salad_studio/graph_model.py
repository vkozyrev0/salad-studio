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
from typing import Any, Iterable

from salad_studio import graph_view

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

# The class each column holds, from the Tk pane. Unknown classes share a last
# column so they never land in a sampler column.
_COLUMN: dict[str, int] = graph_view._COLUMN


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
        for r in graph_view.node_rows(node, lookup)
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
        loras = graph_view.lora_lookup()
    ids = {str(k) for k, v in prompt.items() if isinstance(v, dict)}
    cards: dict[str, dict[str, Any]] = {}
    for nid, node in prompt.items():
        nid = str(nid)
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "Node")
        title = f"#{nid}  {graph_view.node_title(node, prompt, nid)}"
        ins = [k for k, v in (node.get("inputs") or {}).items() if graph_view.is_link(v)]
        outs = [name for name, _typ in graph_view._lg_outputs(cls)]
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
                Port(name=k, key=k, kind="in", color=graph_view.slot_color(k, card["cls"]),
                     y=HEADER_H + BODY_PAD + i * ROW_H + ROW_H / 2)
                for i, k in enumerate(card["ins"])
            )
            base = len(ins)
            outs = tuple(
                Port(name=name, key=f"out_{i}", kind="out",
                     color=graph_view.slot_color(name.lower(), card["cls"]),
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
    for src, dst, key in graph_view.graph_edges(prompt):
        if src not in ids or dst not in ids or src not in by_id or dst not in by_id:
            continue
        slot = graph_view._lg_origin_slot(prompt[src] if isinstance(prompt[src], dict) else {}, key)
        edges.append(
            Edge(
                source=src,
                source_key=f"out_{slot}",
                target=dst,
                target_key=key,
                color=graph_view.slot_color(key, str((prompt[src] or {}).get("class_type") or "")),
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
    return tuple(graph_view.toggle_live_selection(list(selected), nid))


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
