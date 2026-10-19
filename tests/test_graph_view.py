"""The prompt graph as the Flet pane shows it: labels, card sizes, ports, wires, layers.

The JointJS WebView pane is gone. Its labeling and lookup rules moved to
``graph_model``. They are driven here. ``tests/test_graph_model.py`` and
``tests/test_graph_canvas.py`` own layout, selection, drag, zoom, fit, pan and
the painted shapes.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
for _p in (HERE.parent / "salad_studio", HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import flet as ft  # noqa: E402
from flet import canvas as cv  # noqa: E402

import lora_store as ls  # noqa: E402
from salad_studio import flet_theme, graph_canvas as gc, graph_model as gm  # noqa: E402

KLEIN_GRAPHVIZ_PROMPT = {
    "70": {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": "flux-2-klein-9b-fp8.safetensors"},
    },
    "71": {
        "class_type": "CLIPLoader",
        "inputs": {"clip_name": "qwen_3_8b_fp8mixed.safetensors"},
    },
    "80": {
        "class_type": "LoraLoader",
        "inputs": {
            "model": ["70", 0],
            "clip": ["71", 0],
            "lora_name": "Klein-Anime-v2.safetensors",
            "strength_model": 1.0,
            "strength_clip": 1.0,
        },
        "_meta": {
            "title": "Klein-Anime-v2.safetensors",
            "tag": "Klein-Anime",
        },
    },
    "74": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "a cat on a lighthouse", "clip": ["80", 1]},
    },
    "64": {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "guider": ["80", 0],
            "latent_image": ["74", 0],
        },
    },
    "65": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["64", 0]},
    },
}

COLORS = flet_theme.canvas_colors(True)


def _two_lora_prompt() -> dict:
    return {
        "70": {"class_type": "UNETLoader", "inputs": {"unet_name": "u.safetensors"}},
        "80": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["70", 0],
                "lora_name": "Klein-Anime-v2.safetensors",
                "strength_model": 0.8,
            },
            "_meta": {"title": "Klein-Anime-v2.safetensors", "tag": "Klein-Anime"},
        },
        "81": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["80", 0],
                "lora_name": "PencilDrawEn01.safetensors",
                "strength_model": 0.6,
            },
            "_meta": {"title": "PencilDrawEn01.safetensors", "tag": "PencilDraw"},
        },
    }


class ComfyChrome(unittest.TestCase):
    def test_slot_colors_match_comfy_types(self) -> None:
        self.assertEqual(gm.slot_color("model"), "#B39DDB")
        self.assertEqual(gm.slot_color("clip"), "#F5D76E")
        self.assertEqual(gm.slot_color("positive"), "#FFA726")
        self.assertEqual(gm.slot_color("vae"), "#EF5350")
        self.assertEqual(gm.slot_color("images"), "#4FC3F7")

    def test_lora_widget_uses_meta_filename_not_version_id(self) -> None:
        node = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["70", 0],
                "lora_name": "https://civitai.com/api/download/models/2760251",
                "strength_model": 0.8,
            },
            "_meta": {"title": "PencilDrawEn01_CE_FLUX2_Klein9b_AIT4k.safetensors"},
        }
        values = dict(gm.layout({"80": node}, loras={}).node("80").rows)
        self.assertIn("PencilDrawEn01", values.get("lora_name", ""))
        self.assertNotEqual(values.get("lora_name"), "2760251")

    def test_lora_card_shows_symbolic_name_and_filename(self) -> None:
        node = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["70", 0],
                "clip": ["71", 0],
                "lora_name": "https://civitai.com/api/download/models/2631544",
                "strength_model": 1.0,
                "strength_clip": 1.0,
            },
            "_meta": {
                "title": "Klein-Anime-v2.safetensors",
                "tag": "Klein-Anime",
            },
        }
        values = dict(gm.layout({"80": node}, loras={}).node("80").rows)
        self.assertEqual(values.get("name"), "Klein-Anime")
        self.assertIn("Klein-Anime-v2", values.get("lora_name", ""))

    def test_human_titles(self) -> None:
        self.assertEqual(gm.node_title({"class_type": "UNETLoader"}), "Load Diffusion Model")
        self.assertEqual(gm.node_title({"class_type": "CLIPTextEncode"}), "CLIP Text Encode (Prompt)")
        self.assertEqual(gm.node_title({"class_type": "VAEDecode"}), "VAE Decode")
        caption = gm.layout({"84": {"class_type": "KSamplerSelect", "inputs": {}}}, loras={}).node("84").title
        self.assertIn("84", caption)
        self.assertIn("KSampler Select", caption)


class Cards(unittest.TestCase):
    def test_long_symbolic_name_is_shown_whole(self) -> None:
        name = "ClassicOilPaintingVeryLongSymbolicLoaderNameForKlein"
        prompt = {
            "70": {"class_type": "UNETLoader", "inputs": {"unet_name": "u.safetensors"}},
            "80": {
                "class_type": "LoraLoader",
                "inputs": {"model": ["70", 0], "lora_name": "short.safetensors", "strength_model": 0.2},
                "_meta": {"title": "short.safetensors", "tag": name},
            },
        }
        loras = gm.lora_lookup([{"name": name, "source": {"filename": "short.safetensors"}}])
        node = gm.layout(prompt, loras=loras).node("80")
        self.assertNotIn("…", node.title, "the title is the card width's job, not a cut")
        self.assertGreater(node.w, gm.CARD_MIN_W, "the card widened to hold the name")
        self.assertIn(name, dict(node.rows)["name"])

    def test_a_long_text_prompt_shows_one_line_inside_its_card(self) -> None:
        model = gm.layout(KLEIN_GRAPHVIZ_PROMPT, loras={})
        clip = model.node("74")
        self.assertEqual(clip.note, "a cat on a lighthouse")
        texts = [s.value for s in gc.node_shapes(model, COLORS) if isinstance(s, cv.Text)]
        self.assertIn("a cat on a lighthouse", texts)

    def test_unknown_classes_keep_their_own_column(self) -> None:
        prompt = dict(KLEIN_GRAPHVIZ_PROMPT)
        prompt["99"] = {"class_type": "PrimitiveInt", "inputs": {"value": 768}}
        model = gm.layout(prompt, loras={})
        unknown = model.node("99")
        samplers = [n for n in model.nodes if n.class_type in ("SamplerCustomAdvanced", "KSampler", "KSamplerSelect")]
        self.assertTrue(samplers)
        for sampler in samplers:
            self.assertNotEqual(unknown.x, sampler.x)


class LoraStoreReads(unittest.TestCase):
    def _counting(self, calls: list):
        real = ls.list_loras

        def counting(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        return counting

    def test_laying_out_two_lora_cards_reads_the_store_once(self) -> None:
        calls: list = []
        with mock.patch.object(ls, "list_loras", self._counting(calls)):
            gm.layout(_two_lora_prompt())
        self.assertLessEqual(len(calls), 1, f"lora store read {len(calls)} times for two LoRA cards")

    def test_a_prebuilt_lookup_never_reads_the_store(self) -> None:
        prompt = {
            "70": {"class_type": "UNETLoader", "inputs": {"unet_name": "u.safetensors"}},
            "80": {
                "class_type": "LoraLoader",
                "inputs": {"model": ["70", 0], "lora_name": "custom-key.safetensors", "strength_model": 0.8},
            },
        }
        lookup = gm.lora_lookup(
            [{"name": "Catalog Only Name", "source": {"filename": "custom-key.safetensors"}}]
        )
        self.assertEqual(lookup.get("custom-key"), "Catalog Only Name")
        with mock.patch.object(ls, "list_loras") as read:
            node = gm.layout(prompt, loras=lookup).node("80")
        self.assertEqual(read.call_count, 0, "a pre-built lookup must not read the store")
        self.assertEqual(dict(node.rows)["name"], "Catalog Only Name")


class Ports(unittest.TestCase):
    def test_input_ports_sit_on_socket_rows_and_outputs_are_named(self) -> None:
        lora = gm.layout(KLEIN_GRAPHVIZ_PROMPT, loras={}).node("80")
        rows = list(lora.ins) + list(lora.outs)
        self.assertEqual([p.name for p in lora.outs], ["MODEL", "CLIP"])
        self.assertLess(lora.ins[0].y, lora.outs[0].y)
        self.assertLess(lora.outs[0].y, lora.outs[1].y)
        # Every socket lands inside the card, and each sits on its own row.
        self.assertEqual(len({round(p.y, 3) for p in rows}), len(rows))
        for port in rows:
            self.assertGreater(port.y, gm.HEADER_H)
            self.assertLess(port.y, lora.h)


class Wires(unittest.TestCase):
    def test_an_edge_leaves_its_source_port_and_enters_its_target_port(self) -> None:
        model = gm.layout(KLEIN_GRAPHVIZ_PROMPT, loras={})
        paths = gc.edge_shapes(model, COLORS)
        self.assertEqual(len(paths), len(model.edges))
        self.assertEqual(len(model.edges), len(gm.graph_edges(KLEIN_GRAPHVIZ_PROMPT)))
        for edge, path in zip(model.edges, paths):
            src, dst = model.node(edge.source), model.node(edge.target)
            start, end = path.elements[0], path.elements[-1]
            self.assertEqual((start.x, start.y), model.view.to_screen(*src.port_point(src.port(edge.source_key, "out"))))
            self.assertEqual((end.x, end.y), model.view.to_screen(*dst.port_point(dst.port(edge.target_key, "in"))))


class Layers(unittest.TestCase):
    def test_a_repaint_redraws_only_the_layers_marked_dirty(self) -> None:
        pane = gc.GraphView()
        model = gm.layout(KLEIN_GRAPHVIZ_PROMPT, loras={})
        pane.model = model
        pane.repaint()
        edges, nodes = list(pane.edge_canvas.shapes), list(pane.node_canvas.shapes)
        moved = gm.drag_node(model, model.nodes[0].id, 30, 10)
        pane.set_model(moved, nodes=False)
        pane.repaint()
        self.assertNotEqual(list(pane.edge_canvas.shapes), edges, "the wires follow the card")
        self.assertEqual(list(pane.node_canvas.shapes), nodes, "the node layer was not marked, so it is not rebuilt")

    def test_a_pan_redraws_both_layers(self) -> None:
        pane = gc.GraphView()
        pane.model = gm.layout(KLEIN_GRAPHVIZ_PROMPT, loras={})
        pane.repaint()
        edges, nodes = list(pane.edge_canvas.shapes), list(pane.node_canvas.shapes)
        pane._down(_Pointer(-200.0, -200.0))
        pane._move(_Pointer(-100.0, -100.0))
        pane.repaint()
        self.assertNotEqual(list(pane.edge_canvas.shapes), edges)
        self.assertNotEqual(list(pane.node_canvas.shapes), nodes)


class Gestures(unittest.TestCase):
    def test_a_click_selects_and_a_drag_moves_only_that_card(self) -> None:
        model = gm.layout(_two_lora_prompt(), loras={})
        pane = gc.GraphView()
        pane.model = model
        node = model.node("80")
        tx, ty = model.view.to_screen(node.x + 4, node.y + 4)
        pane._down(_Pointer(tx, ty))
        self.assertEqual(pane.model.selected, ("80",))
        pane._move(_Pointer(tx + 30, ty + 10))
        pane._up(_Pointer(tx + 30, ty + 10))
        moved = pane.model.node("80")
        self.assertEqual((moved.x, moved.y), (node.x + 30, node.y + 10))
        self.assertEqual(pane.model.node("81"), model.node("81"))

    def test_a_right_click_makes_the_same_selection_as_a_left_click(self) -> None:
        model = gm.layout(_two_lora_prompt(), loras={})
        node = model.node("81")
        sx, sy = model.view.to_screen(node.x + 4, node.y + 4)
        left = gm.begin_drag(model, sx, sy)[0].selected
        pane = gc.GraphView()
        pane.model = model
        pane._secondary(_Pointer(sx, sy))
        self.assertEqual(pane.model.selected, left)
        self.assertEqual(left, ("81",))

    def test_a_second_click_picks_the_second_card_and_a_third_drops_the_first(self) -> None:
        model = gm.layout(_two_lora_prompt(), loras={})
        pane = gc.GraphView()
        pane.model = model
        for nid in ("80", "81", "70"):
            node = model.node(nid)
            sx, sy = model.view.to_screen(node.x + 4, node.y + 4)
            pane._down(_Pointer(sx, sy))
            self.assertEqual(pane.model.selected[-1], nid)
        self.assertEqual(pane.model.selected, ("81", "70"))


class _Pointer:
    """The fields a Flet pointer event carries that the pane reads."""

    def __init__(self, x: float, y: float, scroll: float = 0.0) -> None:
        self.local_position = ft.Offset(x, y)
        self.scroll_delta_y = scroll


if __name__ == "__main__":
    unittest.main()
