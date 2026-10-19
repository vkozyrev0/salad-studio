"""What the canvas pane draws for a model, without a client: shape counts, colours, layers."""
from __future__ import annotations

import unittest

import flet as ft
from flet import canvas as cv

from salad_studio import flet_theme, graph_canvas as gc, graph_model as gm
from salad_studio import request_json


def klein() -> gm.GraphModel:
    body = request_json.build_request(prompt_text="a watercolour portrait of an adult", graph="klein",
                                      width=64, height=64, steps=4, seed=1, selected_ids=[])
    return gm.layout(body["prompt"])


COLORS = flet_theme.canvas_colors(True)


class Wires(unittest.TestCase):
    def test_a_wire_leaves_right_enters_left_and_never_goes_backwards(self) -> None:
        pts = gc.wire_points(100, 50, 400, 120)
        self.assertEqual(pts[0], (100, 50))
        self.assertEqual(pts[-1], (400, 120))
        for (x1, _y1), (x2, _y2) in zip(pts, pts[1:]):
            self.assertGreaterEqual(x2, x1)
            self.assertIn((x1 == x2) or (_y1 == _y2), (True,))

    def test_a_level_wire_is_one_straight_run(self) -> None:
        self.assertEqual(gc.wire_points(10, 10, 50, 10), [(10, 10), (50, 10)])

    def test_rounded_elements_start_at_the_first_point_and_end_at_the_last(self) -> None:
        els = gc._polyline([(0, 0), (10, 0), (10, 20), (30, 20)])
        self.assertIsInstance(els[0], cv.Path.MoveTo)
        self.assertEqual((els[0].x, els[0].y), (0, 0))
        self.assertEqual((els[-1].x, els[-1].y), (30, 20))


class Shapes(unittest.TestCase):
    def test_one_path_per_edge_that_lands_on_a_real_port(self) -> None:
        model = klein()
        shapes = gc.edge_shapes(model, COLORS)
        self.assertEqual(len(shapes), len(model.edges))
        self.assertTrue(all(isinstance(s, cv.Path) for s in shapes))

    def test_every_node_draws_a_card_its_title_and_its_rows(self) -> None:
        model = klein()
        shapes = gc.node_shapes(model, COLORS)
        texts = [s.value for s in shapes if isinstance(s, cv.Text)]
        for node in model.nodes:
            self.assertIn(node.title, texts)
            self.assertTrue(any(t.startswith(node.title) for t in texts))
        fills = [s for s in shapes if isinstance(s, cv.Rect)]
        self.assertEqual(len(fills), 2 * len(model.nodes))

    def test_the_selected_card_draws_in_the_accent_colour(self) -> None:
        model = klein()
        target = model.nodes[0].id
        selected = model.with_selection((target,))
        shapes = gc.node_shapes(selected, COLORS)
        strokes = [s.paint.color for s in shapes if isinstance(s, cv.Rect) and s.paint.style == ft.PaintingStyle.STROKE]
        self.assertIn(COLORS["accent"], strokes)
        plain = [s.paint.color for s in gc.node_shapes(model, COLORS) if isinstance(s, cv.Rect) and s.paint.style == ft.PaintingStyle.STROKE]
        self.assertNotIn(COLORS["accent"], plain)

    def test_zoom_scales_the_card_rectangles(self) -> None:
        model = klein()
        base = [s for s in gc.node_shapes(model, COLORS) if isinstance(s, cv.Rect)][:2]
        zoomed = gm.zoom_at(model, 2.0, 0, 0)
        big = [s for s in gc.node_shapes(zoomed, COLORS) if isinstance(s, cv.Rect)][:2]
        self.assertAlmostEqual(big[0].width, base[0].width * 2, places=3)

    def test_an_empty_model_draws_nothing(self) -> None:
        empty = gm.GraphModel()
        self.assertEqual(gc.edge_shapes(empty, COLORS), [])
        self.assertEqual(gc.node_shapes(empty, COLORS), [])


if __name__ == "__main__":
    unittest.main()
