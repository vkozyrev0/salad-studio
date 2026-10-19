"""The prompt graph pane in Flet: a canvas painted from a ``GraphModel``.

Gestures never touch the canvas. Each one computes the next model and asks the
frame loop to repaint. Inputs are coalesced by the loop, so a drag sends at most
one frame per screen refresh while the model keeps every pointer position.

Layers. The edge layer is a separate canvas, redrawn only when a node moves or
the view changes; the node layer is redrawn when the selection or the zoom
changes. The graph itself is painted straight into screen coordinates, so a
card's pixels do not depend on the zoom level of a parent transform.
"""
from __future__ import annotations

from typing import Any, Callable

import flet as ft
from flet import canvas as cv

from salad_studio import flet_theme, graph_model as gm
from salad_studio.flet_pump import refresh

Prompt = dict[str, Any]
RepaintFn = Callable[[gm.GraphModel, bool], None]


def _paint(color: str, width: float = 1.0) -> ft.Paint:
    return ft.Paint(color=color, stroke_width=width, style=ft.PaintingStyle.STROKE)


def wire_points(ax: float, ay: float, bx: float, by: float) -> list[tuple[float, float]]:
    """A right-angled wire from an output to an input. It leaves right, turns
    in the gap between the columns, and enters left, as the JointJS pane did."""
    if abs(ay - by) < 0.5:
        return [(ax, ay), (bx, by)]
    mx = ax + max(28.0, min(90.0, (bx - ax) * 0.45))
    return [(ax, ay), (mx, ay), (mx, by), (bx, by)]


def _polyline(pts: list[tuple[float, float]], radius: float = 8.0) -> list[Any]:
    """MoveTo/LineTo/QuadraticTo through a polyline with rounded interior corners."""
    els: list[Any] = [cv.Path.MoveTo(*pts[0])]
    for i in range(1, len(pts) - 1):
        px, py = pts[i - 1]
        cx, cy = pts[i]
        nx, ny = pts[i + 1]
        d1 = (cx - px, cy - py)
        d2 = (nx - cx, ny - cy)
        l1 = max(1e-6, (d1[0] ** 2 + d1[1] ** 2) ** 0.5)
        l2 = max(1e-6, (d2[0] ** 2 + d2[1] ** 2) ** 0.5)
        r = min(radius, l1 / 2, l2 / 2)
        els.append(cv.Path.LineTo(cx - d1[0] / l1 * r, cy - d1[1] / l1 * r))
        els.append(cv.Path.QuadraticTo(cx, cy, cx + d2[0] / l2 * r, cy + d2[1] / l2 * r))
    els.append(cv.Path.LineTo(*pts[-1]))
    return els


def _text(x: float, y: float, value: str, size: float, color: str, weight=None) -> cv.Text:
    style = ft.TextStyle(size=size, color=color)
    if weight is not None:
        style.weight = weight
    return cv.Text(x, y, value=value, style=style)


def edge_shapes(model: gm.GraphModel, colors: dict[str, str]) -> list[Any]:
    view = model.view
    shapes: list[Any] = []
    for edge in model.edges:
        src, dst = model.node(edge.source), model.node(edge.target)
        if src is None or dst is None:
            continue
        out_port = src.port(edge.source_key, "out")
        in_port = dst.port(edge.target_key, "in")
        if out_port is None or in_port is None:
            continue
        ax, ay = view.to_screen(*src.port_point(out_port))
        bx, by = view.to_screen(*dst.port_point(in_port))
        shapes.append(cv.Path(elements=_polyline(wire_points(ax, ay, bx, by)), paint=_paint(edge.color, 2)))
    return shapes


def node_shapes(model: gm.GraphModel, colors: dict[str, str]) -> list[Any]:
    view, s = model.view, model.view.scale
    shapes: list[Any] = []
    for node in model.nodes:
        x, y = view.to_screen(node.x, node.y)
        w, h = node.w * s, node.h * s
        selected = node.id in model.selected
        shapes.append(cv.Rect(x, y, w, h, border_radius=max(2.0, 10 * s),
                              paint=ft.Paint(color=colors["card"], style=ft.PaintingStyle.FILL)))
        shapes.append(cv.Rect(x, y, w, h, border_radius=max(2.0, 10 * s),
                              paint=_paint(colors["accent"] if selected else colors["card_stroke"], 3 if selected else 1)))
        pad = gm.BODY_PAD * s
        shapes.append(_text(x + pad, y + 9 * s, node.title, 12 * s, colors["text"], ft.FontWeight.W_600))
        row = 0
        for port in node.ins:
            py = y + port.y * s
            shapes.append(cv.Circle(x, py, gm.PORT_R * s, paint=ft.Paint(color=port.color, style=ft.PaintingStyle.FILL)))
            shapes.append(_text(x + pad + 4, py - 7 * s, port.name, 11 * s, colors["muted"]))
            row += 1
        for port in node.outs:
            py = y + port.y * s
            shapes.append(cv.Circle(x + w, py, gm.PORT_R * s, paint=ft.Paint(color=port.color, style=ft.PaintingStyle.FILL)))
            shapes.append(_text(x + w - pad - 4 - len(port.name) * 6.2 * s, py - 7 * s, port.name, 11 * s, colors["muted"]))
            row += 1
        for key, value in node.rows:
            py = y + (gm.HEADER_H + gm.BODY_PAD + row * gm.ROW_H) * s
            shapes.append(_text(x + pad, py, f"{key}: {value}", 11 * s, colors["muted"]))
            row += 1
        if node.note:
            py = y + (gm.HEADER_H + gm.BODY_PAD + row * gm.ROW_H) * s
            shapes.append(_text(x + pad, py, node.note, 11 * s, colors["text"]))
    return shapes


class GraphView(ft.Container):
    """Canvas pane plus its gesture surface. Holds no state beyond what it paints."""

    def __init__(self, *, dark: bool = True, on_swap: Callable[[gm.GraphModel], None] | None = None) -> None:
        super().__init__(expand=True, clip_behavior=ft.ClipBehavior.HARD_EDGE)
        self.on_swap = on_swap
        self.layers = "edges"
        self.colors = flet_theme.canvas_colors(dark)
        self.model = gm.GraphModel()
        self._paint_fn: RepaintFn | None = None
        self._mode: str | None = None
        self._last: tuple[float, float] = (0.0, 0.0)
        self._drag_id: str | None = None
        self._dirty_edges = True
        self._dirty_nodes = True
        self._size = (0.0, 0.0)
        self.edge_canvas = cv.Canvas(expand=True, shapes=[])
        self.node_canvas = cv.Canvas(expand=True, shapes=[])
        self.empty = ft.Container(
            expand=True,
            alignment=ft.Alignment.CENTER,
            content=ft.Text("No prompt graph.", color=self.colors["muted"]),
        )
        self.gesture = ft.GestureDetector(
            expand=True,
            content=ft.Stack([self.edge_canvas, self.node_canvas], expand=True),
            drag_interval=1,
            mouse_cursor=ft.MouseCursor.GRAB,
            on_tap_down=self._down,
            on_tap_move=self._move,
            on_tap_up=self._up,
            on_tap_cancel=self._up,
            on_pan_start=self._down,
            on_pan_update=self._move,
            on_pan_end=self._up,
            on_pan_cancel=self._up,
            on_scroll=self._scroll,
            on_scale_start=self._scale_start,
            on_scale_update=self._scale_update,
            on_secondary_tap_up=self._secondary,
            on_size_change=self._sized,
        )
        self.content = ft.Stack([self.empty, self.gesture], expand=True)

    # -- public

    def bind(self, paint_fn: RepaintFn) -> None:
        self._paint_fn = paint_fn

    def use_layers(self, layers: str) -> None:
        """``edges`` repaints only the edge layer during a node drag (the measured winner)."""
        self.layers = layers

    def set_model(self, model: gm.GraphModel, *, edges: bool = True, nodes: bool = True) -> None:
        self.model = model
        self._dirty_edges = self._dirty_edges or edges
        self._dirty_nodes = self._dirty_nodes or nodes

    def mark_edges(self) -> None:
        self._dirty_edges = True

    def mark_nodes(self) -> None:
        self._dirty_nodes = True

    def repaint(self) -> None:
        if self._dirty_edges:
            self.edge_canvas.shapes = edge_shapes(self.model, self.colors)
            self._dirty_edges = False
        if self._dirty_nodes:
            self.node_canvas.shapes = node_shapes(self.model, self.colors)
            self._dirty_nodes = False
        self.empty.visible = not self.model.nodes
        self.gesture.visible = bool(self.model.nodes)
        refresh(self.edge_canvas, self.node_canvas, self.empty, self.gesture)

    def fit(self) -> None:
        if self.model.nodes:
            self.set_model(gm.fit_view(self.model, *self._size))
            self._emit()

    # -- gestures

    def _emit(self, drag: bool = False) -> None:
        if self._paint_fn is not None:
            self._paint_fn(self.model, drag)

    def _sized(self, e: ft.SizeChangeEvent) -> None:
        self._size = (e.width, e.height)

    def _down(self, e: ft.PointerEvent) -> None:
        x, y = e.local_position.x, e.local_position.y
        self._last = (x, y)
        node = gm.hit_test(self.model, x, y)
        self._mode = "move" if node is not None else "pan"
        self._drag_id = node.id if node is not None else None
        if node is not None:
            self.set_model(self.model.with_selection(gm.toggle_selection(self.model.selected, node.id)))
            self.mark_nodes()
            self._emit()

    def _move(self, e: ft.PointerEvent) -> None:
        if self._mode is None:
            return
        x, y = e.local_position.x, e.local_position.y
        dx, dy = x - self._last[0], y - self._last[1]
        self._last = (x, y)
        if self._mode == "move" and self._drag_id is not None:
            s = self.model.view.scale
            self.set_model(gm.drag_node(self.model, self._drag_id, dx / s, dy / s))
            self.mark_edges()
        else:
            self.set_model(gm.pan_by(self.model, dx, dy))
            self.mark_edges()
            self.mark_nodes()
        self._emit(drag=True)

    def _up(self, e: ft.PointerEvent) -> None:
        self._mode = None
        self._drag_id = None
        self._emit()

    def _scroll(self, e: Any) -> None:
        dy = getattr(e, "scroll_delta_y", None)
        if not dy:
            dy = getattr(e, "scroll_delta", 0) or 0
        factor = gm.ZOOM_STEP if dy > 0 else 1 / gm.ZOOM_STEP
        x, y = e.local_position.x, e.local_position.y
        self.set_model(gm.zoom_at(self.model, factor, x, y))
        self.mark_edges()
        self.mark_nodes()
        self._emit(drag=True)

    def _scale_start(self, e: ft.ScaleStartEvent) -> None:
        if getattr(e, "pointer_count", 0) and e.pointer_count >= 2 and e.local_focal_point:
            self._focal = (e.local_focal_point.x, e.local_focal_point.y)

    def _scale_update(self, e: ft.ScaleUpdateEvent) -> None:
        if e.scale and e.scale > 0:
            fx, fy = getattr(self, "_focal", (e.local_focal_point.x, e.local_focal_point.y))
            self.set_model(gm.zoom_at(self.model, e.scale, fx, fy))
            self.mark_edges()
            self.mark_nodes()
            self._emit(drag=True)

    def _secondary(self, e: ft.PointerEvent) -> None:
        """Right click: the same two-id selection action as a left click, without a drag."""
        self.set_model(gm.begin_drag(self.model, e.local_position.x, e.local_position.y)[0])
        self.mark_nodes()
        self._emit()
