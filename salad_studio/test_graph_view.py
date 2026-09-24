"""Node-graph parse, layout, and payload swap (no window required)."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tkinter as tk
import unittest
from unittest import mock

import lora_store as ls

from salad_studio import graph_view as gv


class SwapPayloads(unittest.TestCase):
    def test_lora_swap_keeps_chain_links(self) -> None:
        prompt = {
            "70": {"class_type": "UNETLoader", "inputs": {"unet_name": "u.safetensors"}},
            "80": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["70", 0],
                    "clip": ["71", 0],
                    "lora_name": "https://civitai.com/api/download/models/1",
                    "strength_model": 0.45,
                    "strength_clip": 0.45,
                },
                "_meta": {"title": "watercolor.safetensors", "variation": "Illustrious"},
            },
            "81": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["80", 0],
                    "clip": ["80", 1],
                    "lora_name": "https://civitai.com/api/download/models/2",
                    "strength_model": 0.7,
                    "strength_clip": 0.7,
                },
                "_meta": {"title": "sakaki.safetensors", "variation": "V1"},
            },
        }
        out = gv.swap_payloads(prompt, "80", "81")
        self.assertEqual(out["80"]["inputs"]["model"], ["70", 0])
        self.assertEqual(out["81"]["inputs"]["model"], ["80", 0])
        self.assertEqual(
            out["80"]["inputs"]["lora_name"],
            "https://civitai.com/api/download/models/2",
        )
        self.assertEqual(
            out["81"]["inputs"]["lora_name"],
            "https://civitai.com/api/download/models/1",
        )
        self.assertAlmostEqual(out["80"]["inputs"]["strength_model"], 0.7)
        self.assertAlmostEqual(out["81"]["inputs"]["strength_model"], 0.45)
        self.assertEqual(out["80"]["_meta"]["title"], "sakaki.safetensors")
        self.assertEqual(out["81"]["_meta"]["title"], "watercolor.safetensors")
        self.assertEqual(prompt["80"]["inputs"]["lora_name"].endswith("/1"), True)

    def test_rejects_different_types(self) -> None:
        prompt = {
            "70": {"class_type": "UNETLoader", "inputs": {"unet_name": "u"}},
            "80": {"class_type": "LoraLoader", "inputs": {"lora_name": "a"}},
        }
        with self.assertRaises(ValueError):
            gv.swap_payloads(prompt, "70", "80")


class Layout(unittest.TestCase):
    def test_lora_sits_right_of_unet(self) -> None:
        prompt = {
            "70": {"class_type": "UNETLoader", "inputs": {}},
            "80": {"class_type": "LoraLoader", "inputs": {"model": ["70", 0]}},
        }
        pos = gv.layout_columns(prompt)
        self.assertLess(pos["70"][0], pos["80"][0])
        edges = gv.graph_edges(prompt)
        self.assertEqual(edges, [("70", "80", "model")])
        xy = gv.layout_xy(prompt)
        self.assertIn("70", xy)
        self.assertIn("80", xy)
        self.assertLess(xy["70"][0], xy["80"][0])


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


class LiteGraphExport(unittest.TestCase):
    def test_prompt_to_litegraph_has_comfy_nodes_and_links(self) -> None:
        data = gv.prompt_to_litegraph(KLEIN_GRAPHVIZ_PROMPT)
        types = {n["type"] for n in data["nodes"]}
        self.assertIn("comfy/UNETLoader", types)
        self.assertIn("comfy/LoraLoader", types)
        ids = {n["id"] for n in data["nodes"]}
        self.assertIn(70, ids)
        self.assertIn(80, ids)
        self.assertTrue(data["links"])
        src_ids = {L[1] for L in data["links"]}
        self.assertIn(70, src_ids)
        lora = next(n for n in data["nodes"] if n["id"] == 80)
        self.assertEqual(lora["outputs"][0][0] if False else lora["outputs"][0]["name"], "MODEL")
        self.assertIn("Klein-Anime", json.dumps(lora["properties"]))

    def test_write_litegraph_page_embeds_graph(self) -> None:
        page = gv.write_litegraph_page(KLEIN_GRAPHVIZ_PROMPT)
        html = page.read_text(encoding="utf-8")
        self.assertIn("LiteGraph", html)
        self.assertIn("comfy/UNETLoader", html)
        self.assertIn("litegraph.min.js", html)


class WebViewUserDir(unittest.TestCase):
    def test_webview_user_dir_is_writable_and_not_beside_python(self) -> None:
        path = gv.webview_user_dir()
        self.assertTrue(path.is_dir())
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        self.assertNotIn("python.exe", str(path).lower())


class JointGraphExport(unittest.TestCase):
    def test_prompt_to_joint_has_ports_and_links(self) -> None:
        data = gv.prompt_to_joint(KLEIN_GRAPHVIZ_PROMPT)
        ids = {n["id"] for n in data["nodes"]}
        self.assertIn("70", ids)
        self.assertIn("80", ids)
        lora = next(n for n in data["nodes"] if n["id"] == "80")
        self.assertTrue(any(p["id"] == "in_model" for p in lora["inPorts"]))
        self.assertEqual(lora["outPorts"][0]["id"], "out_0")
        keys = [f["key"] for f in lora["fields"]]
        self.assertIn("name", keys)
        self.assertIn("lora_name", keys)
        self.assertTrue(any("Klein-Anime" in str(f["value"]) for f in lora["fields"]))
        self.assertTrue(
            any(
                L["source"] == "70"
                and L["target"] == "80"
                and L["sourcePort"] == "out_0"
                for L in data["links"]
            )
        )

    def test_write_graph_page_embeds_joint(self) -> None:
        page = gv.write_graph_page(KLEIN_GRAPHVIZ_PROMPT)
        html = page.read_text(encoding="utf-8")
        self.assertIn("joint.min.js", html)
        self.assertIn("manhattan", html)
        self.assertIn('"id": "70"', html)
        self.assertNotIn("__STUDIO_GRAPH__", html)
        self.assertIn('class="box', html)
        self.assertIn("foreignObject", html)

    def test_joint_card_is_taller_than_field_stack(self) -> None:
        data = gv.prompt_to_joint(KLEIN_GRAPHVIZ_PROMPT)
        lora = next(n for n in data["nodes"] if n["id"] == "80")
        rows = len(lora["inPorts"]) + len(lora["fields"])
        self.assertGreaterEqual(lora["h"], 30 + rows * 24)
        clip = next(n for n in data["nodes"] if n["id"] == "74")
        text = next(f for f in clip["fields"] if f["key"] == "text")
        self.assertGreaterEqual(text["lines"], 2)
        self.assertGreaterEqual(clip["w"], 320)


class WireRouting(unittest.TestCase):
    def test_same_column_lora_uses_gap_between_boxes(self) -> None:
        boxes = {
            "80": (40.0, 40.0, 320.0, 180.0),
            "81": (40.0, 208.0, 320.0, 348.0),
        }
        sx, sy = 320.0, 54.0
        dx, dy = 40.0, 226.0
        pts = gv.route_wire(sx, sy, dx, dy, boxes, "80", "81")
        self.assertGreaterEqual(len(pts), 4)
        self.assertFalse(gv.path_hits_boxes(pts, boxes, {"80", "81"}))
        ys = [p[1] for p in pts]
        self.assertTrue(any(180.0 <= y <= 208.0 for y in ys), pts)

    def test_skip_column_vae_does_not_cross_lora_stack(self) -> None:
        boxes = {
            "72": (40.0, 200.0, 320.0, 280.0),
            "80": (392.0, 40.0, 672.0, 180.0),
            "81": (392.0, 208.0, 672.0, 348.0),
            "65": (1500.0, 40.0, 1780.0, 140.0),
        }
        pts = gv.route_wire(320.0, 214.0, 1500.0, 54.0, boxes, "72", "65")
        self.assertFalse(gv.path_hits_boxes(pts, boxes, {"72", "65"}))
        self.assertGreaterEqual(len(pts), 4)

    def test_chamfer_polyline_cuts_corner_without_arc_center(self) -> None:
        pts = [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0)]
        cut = gv.chamfer_polyline(pts, cut=12)
        self.assertGreaterEqual(len(cut), 4)
        self.assertAlmostEqual(cut[0][0], 0.0, places=1)
        self.assertAlmostEqual(cut[-1][1], 40.0, places=1)
        self.assertFalse(
            any(abs(p[0] - 40.0) < 0.2 and abs(p[1] - 0.0) < 0.2 for p in cut)
        )

    def test_separate_parallel_splits_stacked_verticals(self) -> None:
        a = [(10.0, 0.0), (10.0, 100.0)]
        b = [(10.0, 20.0), (10.0, 80.0)]
        split = gv.separate_parallel_wires([a, b])
        xs = {round(p[0], 1) for p in split[0] + split[1]}
        self.assertGreaterEqual(len(xs), 2)


class ComfyChrome(unittest.TestCase):
    def test_slot_colors_match_comfy_types(self) -> None:
        self.assertEqual(gv.slot_color("model"), "#B39DDB")
        self.assertEqual(gv.slot_color("clip"), "#F5D76E")
        self.assertEqual(gv.slot_color("positive"), "#FFA726")
        self.assertEqual(gv.slot_color("vae"), "#EF5350")
        self.assertEqual(gv.slot_color("images"), "#4FC3F7")

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
        rows = gv.widget_rows(node)
        values = dict(rows)
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
        values = dict(gv.widget_rows(node))
        self.assertEqual(values.get("name"), "Klein-Anime")
        self.assertIn("Klein-Anime-v2", values.get("lora_name", ""))

    def test_lora_card_widens_for_long_filename(self) -> None:
        node = {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": "Ah! My Goddess_illustriousXL.safetensors",
                "strength_model": 0.8,
            },
            "_meta": {"title": "Ah! My Goddess_illustriousXL.safetensors", "tag": "Ah! My Goddess"},
        }
        w, _h = gv.node_metrics(node)
        self.assertGreater(w, gv._NODE_W)
        values = dict(gv.widget_rows(node))
        self.assertIn("Goddess_illustriousXL.safetensors", values.get("lora_name", ""))

    def test_human_titles(self) -> None:
        self.assertEqual(
            gv.node_title({"class_type": "UNETLoader"}),
            "Load Diffusion Model",
        )
        self.assertEqual(
            gv.node_title({"class_type": "CLIPTextEncode"}),
            "CLIP Text Encode (Prompt)",
        )
        self.assertEqual(
            gv.node_title({"class_type": "VAEDecode"}),
            "VAE Decode",
        )
        line1, _line2 = gv.node_caption(
            "84", {"class_type": "KSamplerSelect", "inputs": {}}
        )
        self.assertIn("84", line1)


def _painted_boxes(data: dict) -> list[tuple[str, float, float, float, float]]:
    boxes = []
    for node in data["nodes"]:
        x0 = float(node["x"])
        y0 = float(node["y"])
        boxes.append((str(node["id"]), x0, y0, x0 + float(node["w"]), y0 + float(node["h"])))
    return boxes


def _overlapping_ids(data: dict) -> list[tuple[str, str]]:
    boxes = _painted_boxes(data)
    hits = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]:
                hits.append((a[0], b[0]))
    return hits


class LivePaneExport(unittest.TestCase):
    LONG_NAME = "ClassicOilPaintingVeryLongSymbolicLoaderNameForKlein"

    def _long_lora_prompt(self) -> dict:
        return {
            "70": {"class_type": "UNETLoader", "inputs": {"unet_name": "u.safetensors"}},
            "80": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["70", 0],
                    "clip": ["71", 0],
                    "lora_name": "short.safetensors",
                    "strength_model": 0.2,
                    "strength_clip": 0.2,
                },
                "_meta": {"title": "short.safetensors", "tag": self.LONG_NAME},
            },
        }

    def test_input_ports_sit_on_socket_rows_and_outputs_are_named(self) -> None:
        data = gv.prompt_to_joint(KLEIN_GRAPHVIZ_PROMPT)
        lora = next(n for n in data["nodes"] if n["id"] == "80")
        ports = {p["id"]: p for p in lora["inPorts"]}
        self.assertAlmostEqual(ports["in_model"]["y"], gv.joint_row_center(0))
        self.assertAlmostEqual(ports["in_clip"]["y"], gv.joint_row_center(1))
        self.assertEqual([p["name"] for p in lora["outPorts"]], ["MODEL", "CLIP"])
        self.assertAlmostEqual(lora["outPorts"][0]["y"], gv.joint_row_center(2))
        self.assertAlmostEqual(lora["outPorts"][1]["y"], gv.joint_row_center(3))
        self.assertNotEqual(lora["outPorts"][0]["y"], lora["outPorts"][1]["y"])

    def test_long_loader_name_that_fits_is_not_cut_at_46(self) -> None:
        data = gv.prompt_to_joint(self._long_lora_prompt())
        lora = next(n for n in data["nodes"] if n["id"] == "80")
        self.assertGreater(len(lora["title"]), 46)
        self.assertNotIn("…", lora["title"])
        self.assertIn(self.LONG_NAME, lora["title"])
        name = next(f["value"] for f in lora["fields"] if f["key"] == "name")
        self.assertEqual(name, self.LONG_NAME)
        self.assertLessEqual(24 + len(lora["title"]) * gv._J_CHAR, lora["w"] + 0.1)

    def test_joint_boxes_do_not_overlap_and_unknown_class_leaves_sampler_column(self) -> None:
        klein = gv.prompt_to_joint(KLEIN_GRAPHVIZ_PROMPT)
        self.assertEqual(_overlapping_ids(klein), [])
        prompt = dict(KLEIN_GRAPHVIZ_PROMPT)
        prompt["99"] = {"class_type": "PrimitiveInt", "inputs": {"value": 768}}
        data = gv.prompt_to_joint(prompt)
        self.assertEqual(_overlapping_ids(data), [])
        unknown = next(n for n in data["nodes"] if n["id"] == "99")
        sampler_cols = {
            n["column"]
            for n in data["nodes"]
            if n["classType"] in ("SamplerCustomAdvanced", "KSampler", "KSamplerSelect")
        }
        self.assertTrue(sampler_cols)
        self.assertNotIn(unknown["column"], sampler_cols)
        sampler_class = next(
            n["classType"]
            for n in data["nodes"]
            if n["classType"] in ("SamplerCustomAdvanced", "KSampler", "KSamplerSelect")
        )
        sampler_live = next(
            n["column"] for n in data["nodes"] if n["classType"] == sampler_class
        )
        self.assertEqual(gv.live_column(sampler_class), sampler_live)
        self.assertEqual(gv.live_column("PrimitiveInt"), unknown["column"])
        self.assertNotIn(gv.live_column("PrimitiveInt"), sampler_cols)
        self.assertEqual(gv.live_column("PrimitiveInt"), gv.live_column("NoSuchClass"))
        sampler_x = {n["x"] for n in data["nodes"] if n["column"] in sampler_cols}
        self.assertNotIn(unknown["x"], sampler_x)

    def test_live_selection_swaps_widgets_and_position_leaves_prompt(self) -> None:
        prompt = {
            "70": {"class_type": "UNETLoader", "inputs": {"unet_name": "u.safetensors"}},
            "80": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["70", 0],
                    "clip": ["71", 0],
                    "lora_name": "https://civitai.com/api/download/models/1",
                    "strength_model": 0.45,
                },
                "_meta": {"title": "watercolor.safetensors"},
            },
            "81": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["80", 0],
                    "clip": ["80", 1],
                    "lora_name": "https://civitai.com/api/download/models/2",
                    "strength_model": 0.7,
                },
                "_meta": {"title": "sakaki.safetensors"},
            },
        }
        selected: list[str] = []
        prompt, selected = gv.apply_live_pane_message(
            prompt, selected, {"op": "select", "id": "80"}
        )
        prompt, selected = gv.apply_live_pane_message(
            prompt, selected, {"op": "select", "id": "81"}
        )
        self.assertEqual(selected, ["80", "81"])
        swapped = gv.swap_payloads(prompt, selected[0], selected[1])
        self.assertEqual(swapped["80"]["inputs"]["model"], ["70", 0])
        self.assertEqual(swapped["81"]["inputs"]["model"], ["80", 0])
        self.assertEqual(
            swapped["80"]["inputs"]["lora_name"],
            "https://civitai.com/api/download/models/2",
        )
        self.assertEqual(
            swapped["81"]["inputs"]["lora_name"],
            "https://civitai.com/api/download/models/1",
        )
        same, still = gv.apply_live_pane_message(
            swapped, selected, {"op": "position", "id": "80", "x": 400, "y": 12}
        )
        self.assertIs(same, swapped)
        self.assertEqual(still, selected)
        self.assertEqual(same["80"]["inputs"]["lora_name"], swapped["80"]["inputs"]["lora_name"])
        self.assertEqual(same["80"]["inputs"]["model"], ["70", 0])

    def test_embedded_refresh_replaces_in_place_and_page_zooms_at_pointer(self) -> None:
        page = gv.write_graph_page(KLEIN_GRAPHVIZ_PROMPT)
        html = page.read_text(encoding="utf-8")
        plan = gv.graph_host_refresh(KLEIN_GRAPHVIZ_PROMPT, embedded_ready=True)
        cold = gv.graph_host_refresh(KLEIN_GRAPHVIZ_PROMPT, embedded_ready=False)
        redraw = inspect.getsource(gv.GraphPane._redraw)
        observations = [
            "loads joint.min.js: " + str("joint.min.js" in html),
            "manhattan router: " + str("manhattan" in html),
            "rounded connector: " + str('name: "rounded"' in html),
            "input port y from payload: " + str("y: p.y" in html),
            "output port names rendered: " + str('class="row out"' in html and "esc(p.name)" in html),
            "in-place replace: " + str("window.studioReplaceGraph" in html),
            "wheel zoom uses scaleUniformAtPoint at clientToLocalPoint: "
            + str(
                "scaleUniformAtPoint" in html
                and "paper.clientToLocalPoint(evt.clientX, evt.clientY)" in html
                and "paper.scale(next, next, local.x, local.y)" not in html
            ),
            "click posts select: " + str('op: "select"' in html and "element:pointerclick" in html and "window.ipc.postMessage" in html),
            "drag posts position: " + str('op: "position"' in html),
            "host refresh action: " + plan["action"],
            "host refresh calls studioReplaceGraph: " + str("studioReplaceGraph" in plan["script"]),
            "host refresh script is not a document load: " + str("load_url" not in plan["script"]),
            "cold host action: " + cold["action"],
            "redraw eval_js returns before load_url: "
            + str(
                "eval_js" in redraw
                and "load_url" in redraw
                and redraw.index("return") < redraw.index("load_url")
                and redraw.index("eval_js") < redraw.index("load_url")
            ),
            "LIMIT: a headless click on the embedded WebView2 pane cannot be driven here; "
            "criterion 3 is the selection intake test plus the page script that posts op=select to that intake.",
        ]
        for line in observations:
            if line.startswith("LIMIT"):
                continue
            self.assertFalse(line.endswith(": False"), line)
            self.assertNotIn("script is not a document load: False", line)
        self.assertEqual(plan["action"], "eval_js")
        self.assertIn("studioReplaceGraph", plan["script"])
        self.assertNotIn("load_url", plan["script"])
        self.assertEqual(cold["action"], "load_url")
        self.assertIn("eval_js", redraw)
        self.assertLess(redraw.index("eval_js"), redraw.index("load_url"))
        self.assertLess(redraw.index("return"), redraw.index("load_url"))
        text = "\n".join(observations) + "\n"
        print(text)
        dest = os.environ.get("GRAPH_PAGE_CHECK")
        if dest:
            from pathlib import Path

            Path(dest).write_text(text, encoding="utf-8")


def _two_lora_prompt() -> dict:
    """Two LoraLoader nodes in one prompt (the L13/L14 read-count fixtures)."""
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


class LoraStoreReads(unittest.TestCase):
    """L13: one LoRA store read per prompt, not one per rendered card."""

    def _counting(self, calls: list) -> object:
        real = ls.list_loras

        def counting(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        return counting

    def test_prompt_to_joint_reads_the_lora_store_at_most_once(self) -> None:
        prompt = _two_lora_prompt()
        loras = sum(
            1 for n in prompt.values() if n.get("class_type") == "LoraLoader"
        )
        self.assertGreaterEqual(loras, 2)
        calls: list = []
        with mock.patch.object(ls, "list_loras", self._counting(calls)):
            gv.prompt_to_joint(prompt)
        self.assertLessEqual(
            len(calls), 1, f"lora store read {len(calls)} times for {loras} LoRA cards"
        )

    def test_prebuilt_lookup_reads_the_store_zero_times(self) -> None:
        # No _meta tag here, so the catalog name is the only source for the label.
        prompt = {
            "70": {"class_type": "UNETLoader", "inputs": {"unet_name": "u.safetensors"}},
            "80": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["70", 0],
                    "lora_name": "custom-key.safetensors",
                    "strength_model": 0.8,
                },
            },
        }
        lookup = gv.lora_lookup(
            [{"name": "Catalog Only Name", "source": {"filename": "custom-key.safetensors"}}]
        )
        self.assertEqual(lookup.get("custom-key"), "Catalog Only Name")
        calls: list = []
        with mock.patch.object(ls, "list_loras", self._counting(calls)):
            data = gv.prompt_to_joint(prompt, loras=lookup)
        self.assertEqual(len(calls), 0, "a pre-built lookup must not read the store")
        lora = next(n for n in data["nodes"] if n["id"] == "80")
        self.assertEqual(lora["title"], "#80  Catalog Only Name")
        self.assertTrue(any("Catalog Only Name" in str(f["value"]) for f in lora["fields"]))


class _FakeWeb:
    """Stand-in for the tkwry WebView: records eval_js / load_url calls.

    Models the readiness contract that caused the reported breakage: tkwry
    refuses ``eval_js`` until the native view exists with laid-out geometry,
    and only then fires the ``when_ready`` callback.
    """

    def __init__(self, *, ready: bool = False, eval_raises: bool = False) -> None:
        self.js: list[str] = []
        self.urls: list[str] = []
        self.ready = ready
        self._ready_cbs: list = []
        self._eval_raises = eval_raises
        self.on_error = None

    def when_ready(self, callback) -> None:
        self._ready_cbs.append(callback)
        if self.ready:
            callback()

    def become_ready(self) -> None:
        self.ready = True
        for callback in list(self._ready_cbs):
            callback()

    def eval_js(self, script: str, *, on_error=None) -> None:
        if not self.ready or self._eval_raises:
            raise RuntimeError(
                "WebView is not ready; call wait_until_ready() or bind to "
                "<<WebViewReady>> before calling eval_js()"
            )
        self.on_error = on_error
        self.js.append(script)

    def load_url(self, url: str) -> None:
        self.urls.append(url)

    def focus_parent(self) -> None:
        return None

    def bind(self, *_a, **_kw) -> str:
        return ""


class _PaneCase(unittest.TestCase):
    """Base for pane tests: a real ttk frame with a fake or absent WebView2."""

    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover - headless host
            self.skipTest(f"Tk unavailable: {exc}")
        self.root.withdraw()

    def tearDown(self) -> None:
        self.root.destroy()

    def _pane(self, on_swap=None) -> gv.GraphPane:
        with mock.patch.dict(sys.modules, {"tkwry": None}):
            return gv.GraphPane(self.root, on_swap=on_swap)

    def _embedded_pane(
        self, on_swap=None, *, ready: bool = True, eval_raises: bool = False
    ) -> gv.GraphPane:
        web = _FakeWeb(ready=ready, eval_raises=eval_raises)
        fake_tkwry = mock.Mock()
        fake_tkwry.WebView = lambda *args, **kwargs: web
        with mock.patch.dict(sys.modules, {"tkwry": fake_tkwry}):
            return gv.GraphPane(self.root, on_swap=on_swap)


class EmbedReadiness(_PaneCase):
    """The reported breakage: eval_js before the WebView was laid out.

    tkwry raises ``WebView is not ready; call wait_until_ready() or bind to
    <<WebViewReady>>`` for an early ``eval_js``. The pane must keep the graph
    visible in that state instead of going blank behind an error hint.
    """

    def test_construction_does_not_claim_the_embed_is_usable(self) -> None:
        pane = self._embedded_pane(ready=False)
        self.assertTrue(pane._web_ok, "the WebView object exists")
        self.assertFalse(pane._embedded_ready, "but the page is not laid out yet")
        self.assertFalse(pane._embed_live())

    def test_a_not_ready_webview_falls_back_to_a_page_load(self) -> None:
        pane = self._embedded_pane(ready=False)
        pane.set_prompt(KLEIN_GRAPHVIZ_PROMPT)
        self.assertEqual(pane._web.js, [], "eval_js must not be attempted yet")
        self.assertTrue(pane._web.urls, "the graph must still reach the page")
        hint = str(pane._hint.cget("text"))
        self.assertNotIn("Graph refresh failed", hint)

    def test_ready_event_enables_the_in_place_refresh(self) -> None:
        pane = self._embedded_pane(ready=False)
        pane.set_prompt(KLEIN_GRAPHVIZ_PROMPT)
        self.assertEqual(pane._web.js, [])
        pane._web.become_ready()
        self.root.update()
        self.assertTrue(pane._embedded_ready)
        self.assertTrue(pane._web.js, "the ready event must push the graph in place")
        self.assertIn("studioReplaceGraph", pane._web.js[-1])
        self.assertEqual(str(pane._hint.cget("text")), "")

    def test_a_ready_webview_uses_the_in_place_refresh(self) -> None:
        pane = self._embedded_pane(ready=True)
        pane.set_prompt(KLEIN_GRAPHVIZ_PROMPT)
        self.assertTrue(pane._web.js)
        self.assertIn("studioReplaceGraph", pane._web.js[-1])
        self.assertEqual(pane._web.urls, [])

    def test_eval_failure_never_leaves_the_stale_graph(self) -> None:
        """A ready view that still refuses eval_js must reload the page."""
        pane = self._embedded_pane(ready=True, eval_raises=True)
        pane.set_prompt(KLEIN_GRAPHVIZ_PROMPT)
        self.assertEqual(pane._web.js, [])
        self.assertTrue(pane._web.urls, "the reload is the fallback")
        self.assertIn("deferred", str(pane._hint.cget("text")).lower())

    def test_async_eval_error_schedules_a_reload(self) -> None:
        pane = self._embedded_pane(ready=True)
        pane.set_prompt(KLEIN_GRAPHVIZ_PROMPT)
        self.assertIsNotNone(pane._web.on_error, "on_error must be wired")
        before = len(pane._web.urls)
        pane._web.on_error(RuntimeError("native error"))
        self.root.update()
        self.assertGreater(len(pane._web.urls), before, "the page is reloaded")
        self.assertIn("reloading", str(pane._hint.cget("text")).lower())


class PaneFallback(_PaneCase):
    """M8: with no embed there is no way to select two cards, so Swap refuses."""

    def test_embed_failure_disables_swap_and_reports_why(self) -> None:
        swapped: list = []
        pane = self._pane(on_swap=swapped.append)
        self.assertFalse(pane._web_ok)
        self.assertTrue(pane._swap_btn.instate(["disabled"]))
        hint = pane._hint.cget("text")
        self.assertIn("embed", hint.lower())
        self.assertIn("Open in browser", hint)
        self.assertFalse(hasattr(pane, "_boxes"))
        self.assertEqual(pane.canvas.bind("<Button-1>"), "")

    def test_embed_up_keeps_swap_enabled(self) -> None:
        pane = self._embedded_pane()
        self.assertTrue(pane._web_ok)
        self.assertFalse(pane._swap_btn.instate(["disabled"]))

    def test_do_swap_refuses_without_embed_and_does_not_raise(self) -> None:
        swapped: list = []
        pane = self._pane(on_swap=swapped.append)
        pane.set_prompt(_two_lora_prompt())
        pane._selected = ["80", "81"]
        pane._do_swap()
        self.assertEqual(swapped, [], "swap must not run without the embed")
        hint = pane._hint.cget("text")
        self.assertIn("embed", hint.lower())
        self.assertIn("Open in browser", hint)


class PaneRedrawWrites(_PaneCase):
    """L14: the HTML page is written only on the branch that loads it."""

    def _embedded_pane(self) -> gv.GraphPane:
        pane = super()._embedded_pane()
        pane.set_prompt(KLEIN_GRAPHVIZ_PROMPT)
        pane._web.js.clear()
        return pane

    def test_in_place_refresh_does_not_rewrite_the_page(self) -> None:
        pane = self._embedded_pane()
        plan = gv.graph_host_refresh(KLEIN_GRAPHVIZ_PROMPT, embedded_ready=True)
        self.assertEqual(plan["action"], "eval_js")
        with mock.patch.object(gv, "write_graph_page") as write:
            pane._redraw()
        self.assertEqual(write.call_count, 0, "in-place refresh rewrote the page")
        self.assertEqual(len(pane._web.js), 1)
        self.assertIn("studioReplaceGraph", pane._web.js[0])
        self.assertEqual(pane._web.urls, [])

    def test_load_url_refresh_writes_the_page_once(self) -> None:
        pane = self._embedded_pane()
        pane._embedded_ready = False
        plan = gv.graph_host_refresh(KLEIN_GRAPHVIZ_PROMPT, embedded_ready=False)
        self.assertEqual(plan["action"], "load_url")
        page = gv.write_graph_page(KLEIN_GRAPHVIZ_PROMPT)
        fake_app = mock.Mock()
        fake_app.app_url = lambda name: f"https://studio.invalid/{name}"
        with mock.patch.object(gv, "write_graph_page", return_value=page) as write:
            with mock.patch.dict(sys.modules, {"tkwry._app": fake_app}):
                pane._redraw()
        self.assertEqual(write.call_count, 1)
        self.assertEqual(pane._web.urls, [fake_app.app_url(page.name)])
        self.assertEqual(pane._web.js, [])
        # Loading the page does NOT make the view ready for eval_js: tkwry only
        # allows that once the native view is laid out and has fired
        # <<WebViewReady>>. Treating a load as readiness is what broke the pane
        # (the in-place refresh then threw "WebView is not ready").
        self.assertFalse(pane._embedded_ready)
        self.assertFalse(pane._embed_live())
