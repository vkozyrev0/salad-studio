"""The graph model is pure data: layout, selection, drag and zoom are provable without a UI."""
from __future__ import annotations

import unittest

import salad_studio.graph_model as gm
import salad_studio.request_json as request_json


def klein_prompt() -> dict:
    body = request_json.build_request(prompt_text="a watercolour portrait", graph="klein",
                                      width=64, height=64, steps=4, seed=1, selected_ids=[])
    return body["prompt"]


class Layout(unittest.TestCase):
    def setUp(self) -> None:
        self.model = gm.layout(klein_prompt())

    def test_every_node_and_link_in_the_prompt_is_in_the_model(self) -> None:
        prompt = klein_prompt()
        self.assertEqual(len(self.model.nodes), len(prompt))
        links = sum(
            1
            for node in prompt.values()
            for value in (node.get("inputs") or {}).values()
            if isinstance(value, list) and len(value) == 2
        )
        self.assertEqual(len(self.model.edges), links)

    def test_edges_name_ports_that_exist(self) -> None:
        for edge in self.model.edges:
            src, dst = self.model.node(edge.source), self.model.node(edge.target)
            self.assertIsNotNone(src)
            self.assertIsNotNone(dst)
            self.assertIsNotNone(src.port(edge.source_key, "out"))
            self.assertIsNotNone(dst.port(edge.target_key, "in"))

    def test_columns_run_left_to_right_and_cards_do_not_overlap(self) -> None:
        nodes = self.model.nodes
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                overlap = (a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h)
                self.assertFalse(overlap, f"{a.id} overlaps {b.id}")

    def test_layout_is_deterministic(self) -> None:
        again = gm.layout(klein_prompt())
        self.assertEqual([(n.id, n.x, n.y) for n in self.model.nodes],
                         [(n.id, n.x, n.y) for n in again.nodes])


class Gestures(unittest.TestCase):
    def setUp(self) -> None:
        self.model = gm.layout(klein_prompt())

    def test_hit_test_finds_the_node_under_a_point_and_nothing_on_blank_space(self) -> None:
        node = self.model.nodes[0]
        sx, sy = self.model.view.to_screen(node.x + 4, node.y + 4)
        self.assertEqual(gm.hit_test(self.model, sx, sy).id, node.id)
        self.assertIsNone(gm.hit_test(self.model, -50, -50))

    def test_selection_keeps_two_and_drops_the_oldest(self) -> None:
        a, b, c = (n.id for n in self.model.nodes[:3])
        self.assertEqual(gm.toggle_selection((), a), (a,))
        self.assertEqual(gm.toggle_selection((a,), b), (a, b))
        self.assertEqual(gm.toggle_selection((a, b), c), (b, c))
        self.assertEqual(gm.toggle_selection((a, b), a), (b,))

    def test_dragging_moves_only_that_node_and_its_origin_record(self) -> None:
        node = self.model.nodes[0]
        moved = gm.drag_node(self.model, node.id, 12.5, -7.0)
        self.assertEqual((moved.node(node.id).x, moved.node(node.id).y), (node.x + 12.5, node.y - 7.0))
        self.assertEqual(moved.origin, ("node", node.id))
        others = [n for n in self.model.nodes if n.id != node.id]
        for other in others:
            self.assertEqual(moved.node(other.id), other)

    def test_zoom_keeps_the_point_under_the_cursor(self) -> None:
        before = self.model.view.to_world(321.0, 123.0)
        zoomed = gm.zoom_at(self.model, 1.1, 321.0, 123.0)
        after = zoomed.view.to_world(321.0, 123.0)
        self.assertAlmostEqual(before[0], after[0], places=6)
        self.assertAlmostEqual(before[1], after[1], places=6)
        self.assertAlmostEqual(zoomed.view.scale, 1.1)

    def test_zoom_is_clamped(self) -> None:
        model = self.model
        for _ in range(60):
            model = gm.zoom_at(model, 1.1, 0, 0)
        self.assertLessEqual(model.view.scale, gm.ZOOM_MAX)
        for _ in range(120):
            model = gm.zoom_at(model, 0.9, 0, 0)
        self.assertGreaterEqual(model.view.scale, gm.ZOOM_MIN)

    def test_fit_puts_the_whole_graph_inside_the_viewport(self) -> None:
        fitted = gm.fit_view(self.model, 900, 700)
        for node in fitted.nodes:
            for wx, wy in ((node.x, node.y), (node.x + node.w, node.y + node.h)):
                sx, sy = fitted.view.to_screen(wx, wy)
                self.assertTrue(0 <= sx <= 900, f"{node.id} at {sx}")
                self.assertTrue(0 <= sy <= 700, f"{node.id} at {sy}")

    def test_pan_translates_without_changing_scale(self) -> None:
        panned = gm.pan_by(self.model, 40, -15)
        self.assertEqual(panned.view.scale, self.model.view.scale)
        self.assertEqual(self.model.view.to_screen(0, 0), (self.model.view.ox, self.model.view.oy))
        self.assertEqual(panned.view.to_screen(10, 10),
                         (self.model.view.to_screen(10, 10)[0] + 40, self.model.view.to_screen(10, 10)[1] - 15))


if __name__ == "__main__":
    unittest.main()
