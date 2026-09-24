"""Tests for the Salad Studio request JSON builder (no network)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TOOLS))

import request_json as rj  # noqa: E402
import lora_store as ls  # noqa: E402

KLEIN_DETAIL = "civitai:2334190@2625692"
KLEIN_IMPRESSIONISM = "civitai:545264@2763568"
# Same versions with an explicit Civitai file id, as a real studio-loras.json
# override carries them.
KLEIN_DETAIL_FILEID_URL = (
    "https://civitai.com/api/download/models/2625692?fileId=2513322"
)
KLEIN_IMPRESSIONISM_FILEID_URL = (
    "https://civitai.com/api/download/models/2763568?fileId=2649742"
)
FLUX1_ULTRA = "civitai:796382@1026423"
PONY_WATERCOLOR = "civitai:264290@720004"
MIXED_IDS = [KLEIN_DETAIL, KLEIN_IMPRESSIONISM, FLUX1_ULTRA, PONY_WATERCOLOR]


def _lora_names(body: dict) -> list[str]:
    names = []
    for node in (body.get("prompt") or {}).values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") != "LoraLoader":
            continue
        names.append(node["inputs"]["lora_name"])
    return names


class Scheduler(unittest.TestCase):
    def test_simple_replaces_flux2_scheduler(self) -> None:
        body = rj.build_request(
            prompt_text="x",
            graph="klein",
            width=1024,
            height=768,
            steps=40,
            seed=1,
            selected_ids=[],
        )
        self.assertEqual(body["prompt"]["62"]["class_type"], "Flux2Scheduler")
        rj.apply_scheduler(body, "simple")
        self.assertEqual(body["prompt"]["62"]["class_type"], "BasicScheduler")
        self.assertEqual(body["prompt"]["62"]["inputs"]["scheduler"], "simple")
        self.assertEqual(body["prompt"]["62"]["inputs"]["steps"], 40)
        cfg = rj.config_from_payload(body)
        self.assertEqual(cfg["scheduler"], "simple")


class KleinUnet(unittest.TestCase):
    def test_normalize_base_and_distilled(self) -> None:
        self.assertEqual(
            rj.normalize_unet("Flux\\flux-2-klein-base-9b-fp8"),
            rj.UNET_BASE,
        )
        self.assertEqual(
            rj.normalize_unet("flux-2-klein-9b-fp8"),
            rj.UNET_DISTILLED,
        )
        self.assertEqual(rj.unet_label(rj.UNET_DISTILLED), "Distilled 9B")
        self.assertEqual(rj.unet_label("Base 9B"), "Base 9B")

    def test_build_request_distilled_unet(self) -> None:
        body = rj.build_request(
            prompt_text="x",
            graph="klein",
            width=1024,
            height=1024,
            steps=4,
            seed=1,
            cfg=1,
            unet=rj.UNET_DISTILLED,
            selected_ids=[],
        )
        self.assertEqual(
            body["prompt"]["70"]["inputs"]["unet_name"], rj.UNET_DISTILLED
        )
        cfg = rj.config_from_payload(body)
        self.assertEqual(cfg["unet"], rj.UNET_DISTILLED)


class BuildRequest(unittest.TestCase):
    def test_klein_selected_loras_appear_in_json(self) -> None:
        # Hermetic: the temp extras file is deliberately never created, so the
        # developer's real ~/.config/salad/studio-loras.json cannot reach this
        # build and the catalog rows are what resolve.
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            body = rj.build_request(
                prompt_text="cream paper portrait",
                graph="klein",
                width=832,
                height=1216,
                steps=20,
                seed=7,
                selected_ids=[
                    "civitai:2334190@2625692",
                    "civitai:545264@2763568",
                ],
                extras_path=extras,
            )
        self.assertIn("prompt", body)
        names = _lora_names(body)
        self.assertEqual(
            names,
            [
                "https://civitai.com/api/download/models/2625692",
                "https://civitai.com/api/download/models/2763568",
            ],
        )
        text_nodes = [
            n["inputs"]["text"]
            for n in body["prompt"].values()
            if n.get("class_type") == "CLIPTextEncode" and n["inputs"].get("text")
        ]
        self.assertIn("cream paper portrait", text_nodes)
        self.assertEqual(body["prompt"]["66"]["inputs"]["width"], 832)
        self.assertEqual(
            (body["prompt"]["80"].get("_meta") or {}).get("title"),
            "klein_slider_detail.safetensors",
        )
        self.assertEqual(
            (body["prompt"]["81"].get("_meta") or {}).get("title"),
            "impressionism_klein9b.safetensors",
        )
        refs = {str(r.get("node")): r for r in (body.get("refs") or [])}
        self.assertEqual(refs["70"]["name"], "flux-2-klein-base-9b-fp8.safetensors")
        self.assertEqual(refs["80"]["name"], "klein_slider_detail.safetensors")
        self.assertIn("2625692", str(refs["80"].get("ref") or ""))
        last = names[-1]
        self.assertEqual(last, "https://civitai.com/api/download/models/2763568")
        # Klein-native LoRAs: CLIP encodes on the last LoRA CLIP.
        self.assertEqual(body["prompt"]["74"]["inputs"]["clip"], ["81", 1])
        self.assertEqual(body["prompt"]["67"]["inputs"]["clip"], ["81", 1])
        self.assertEqual(body["prompt"]["81"]["class_type"], "LoraLoader")
        model_ref = body["prompt"]["63"]["inputs"]["model"]
        self.assertEqual(body["prompt"][model_ref[0]]["class_type"], "LoraLoader")

    def test_klein_extras_fileid_url_overrides_catalog(self) -> None:
        """An extras row for a catalog id replaces the catalog download URL."""
        overrides = {
            KLEIN_DETAIL: KLEIN_DETAIL_FILEID_URL,
            KLEIN_IMPRESSIONISM: KLEIN_IMPRESSIONISM_FILEID_URL,
        }
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            absent = tmp / "no-extras.json"
            items = []
            for lora_id, url in overrides.items():
                row = ls.find_lora(lora_id, absent)
                assert row is not None
                src = dict(row["source"])
                src["download"] = url
                items.append(
                    {
                        "id": lora_id,
                        "name": row["name"],
                        "kind": "lora",
                        "base": row["base"],
                        "source": src,
                        "verified": True,
                    }
                )
            extras = tmp / "studio-loras.json"
            extras.write_text(json.dumps({"items": items}), encoding="utf-8")
            body = rj.build_request(
                prompt_text="cream paper portrait",
                graph="klein",
                width=832,
                height=1216,
                steps=20,
                seed=7,
                selected_ids=list(overrides),
                extras_path=extras,
            )
        names = _lora_names(body)
        self.assertEqual(
            names, [KLEIN_DETAIL_FILEID_URL, KLEIN_IMPRESSIONISM_FILEID_URL]
        )
        for name in names:
            self.assertIn("?fileId=", name)

    def test_no_loras_has_no_lora_loader(self) -> None:
        body = rj.build_request(
            prompt_text="plain",
            graph="klein",
            width=64,
            height=64,
            steps=4,
            seed=1,
            selected_ids=[],
        )
        self.assertEqual(_lora_names(body), [])

    def test_classic_oil_uses_civitai_url(self) -> None:
        body = rj.build_request(
            prompt_text="oil face",
            graph="klein",
            width=768,
            height=1024,
            steps=40,
            seed=1,
            selected_ids=["civitai:637213@2760271"],
        )
        names = _lora_names(body)
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith("https://"))
        self.assertIn("2760271", names[0])
        node = next(
            n
            for n in body["prompt"].values()
            if n.get("class_type") == "LoraLoader"
        )
        self.assertEqual(node["inputs"]["strength_model"], 0.2)

    def test_flux1_chain(self) -> None:
        body = rj.build_request(
            prompt_text="flux face",
            graph="flux1",
            width=64,
            height=64,
            steps=4,
            seed=2,
            loras=[
                {
                    "lora_name": "https://civitai.com/api/download/models/1026423",
                    "strength_model": 0.65,
                    "strength_clip": 0.65,
                }
            ],
        )
        names = _lora_names(body)
        self.assertEqual(names, ["https://civitai.com/api/download/models/1026423"])
        self.assertEqual(body["prompt"]["31"]["inputs"]["model"][0], "40")

    def test_encode_prompts_before_loras_rewires_clip_encodes(self) -> None:
        prompt = {
            "71": {"class_type": "CLIPLoader", "inputs": {}},
            "80": {
                "class_type": "LoraLoader",
                "inputs": {"model": ["70", 0], "clip": ["71", 0]},
            },
            "81": {
                "class_type": "LoraLoader",
                "inputs": {"model": ["80", 0], "clip": ["80", 1]},
            },
            "74": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "pos", "clip": ["81", 1]},
            },
            "67": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "neg", "clip": ["81", 1]},
            },
            "63": {
                "class_type": "CFGGuider",
                "inputs": {"model": ["81", 0], "positive": ["74", 0], "negative": ["67", 0]},
            },
        }
        rj.encode_prompts_before_loras(prompt)
        self.assertEqual(prompt["74"]["inputs"]["clip"], ["71", 0])
        self.assertEqual(prompt["67"]["inputs"]["clip"], ["71", 0])
        self.assertEqual(prompt["63"]["inputs"]["model"], ["81", 0])
        self.assertEqual(prompt["81"]["inputs"]["clip"], ["80", 1])

    def test_wire_clip_encodes_klein_lora_keeps_last_lora_clip(self) -> None:
        prompt = {
            "71": {"class_type": "CLIPLoader", "inputs": {}},
            "80": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["70", 0],
                    "clip": ["71", 0],
                    "lora_name": "https://civitai.com/api/download/models/3088444",
                },
                "_meta": {"title": "Artificeal.safetensors", "tag": "Artificeal"},
            },
            "74": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "pos", "clip": ["71", 0]},
            },
            "67": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "", "clip": ["71", 0]},
            },
            "63": {
                "class_type": "CFGGuider",
                "inputs": {"model": ["80", 0], "positive": ["74", 0], "negative": ["67", 0]},
            },
        }
        rj.wire_clip_encodes(prompt)
        self.assertEqual(prompt["74"]["inputs"]["clip"], ["80", 1])
        self.assertEqual(prompt["67"]["inputs"]["clip"], ["80", 1])

    def test_wire_clip_encodes_illustrious_uses_clip_loader(self) -> None:
        prompt = {
            "71": {"class_type": "CLIPLoader", "inputs": {}},
            "80": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["70", 0],
                    "clip": ["71", 0],
                    "lora_name": "https://civitai.com/api/download/models/1730326",
                },
                "_meta": {"title": "transparent-watercolor_IL_MIX.safetensors"},
            },
            "74": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "pos", "clip": ["80", 1]},
            },
            "63": {
                "class_type": "CFGGuider",
                "inputs": {"model": ["80", 0], "positive": ["74", 0]},
            },
        }
        rj.wire_clip_encodes(prompt)
        self.assertEqual(prompt["74"]["inputs"]["clip"], ["71", 0])

    def test_wire_clip_encodes_mixed_il_and_klein_uses_klein_clip(self) -> None:
        """Civitai 130704037: IL characters + Klein-Anime. Encode after last LoRA."""
        prompt = {
            "71": {"class_type": "CLIPLoader", "inputs": {}},
            "80": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["70", 0],
                    "clip": ["71", 0],
                    "lora_name": "https://civitai.com/api/download/models/1829247",
                    "strength_model": 1.0,
                    "strength_clip": 1.0,
                },
                "_meta": {"title": "Helga_Sinclair_-_Disney_Illustrious.safetensors"},
            },
            "85": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["80", 0],
                    "clip": ["80", 1],
                    "lora_name": "https://civitai.com/api/download/models/2631544",
                    "strength_model": 1.0,
                    "strength_clip": 1.0,
                },
                "_meta": {"title": "Klein-Anime-v2.safetensors"},
            },
            "86": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["85", 0],
                    "clip": ["85", 1],
                    "lora_name": "https://civitai.com/api/download/models/269354",
                    "strength_model": 1.0,
                    "strength_clip": 1.0,
                },
                "_meta": {"title": "sd_xl_dpo_lora_v1-128dim.safetensors"},
            },
            "74": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "pos", "clip": ["71", 0]},
            },
            "67": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "blurry", "clip": ["71", 0]},
            },
            "63": {
                "class_type": "CFGGuider",
                "inputs": {
                    "model": ["86", 0],
                    "positive": ["74", 0],
                    "negative": ["67", 0],
                },
            },
        }
        rj.wire_clip_encodes(prompt)
        self.assertEqual(prompt["74"]["inputs"]["clip"], ["85", 1])
        self.assertEqual(prompt["67"]["inputs"]["clip"], ["85", 1])
        self.assertEqual(prompt["80"]["inputs"]["strength_clip"], 0.0)
        self.assertEqual(prompt["86"]["inputs"]["strength_clip"], 0.0)
        self.assertEqual(prompt["86"]["inputs"]["strength_model"], 0.0)
        self.assertEqual(prompt["85"]["inputs"]["strength_clip"], 1.0)
        self.assertEqual(prompt["80"]["inputs"]["strength_model"], 1.0)
        self.assertEqual(prompt["63"]["inputs"]["model"], ["86", 0])

    def test_salad_post_strips_il_keeps_klein_anime_and_site_clip(self) -> None:
        prompt = {
            "70": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "flux-2-klein-9b-fp8.safetensors"},
            },
            "71": {"class_type": "CLIPLoader", "inputs": {}},
            "80": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["70", 0],
                    "clip": ["71", 0],
                    "lora_name": "https://civitai.com/api/download/models/1829247",
                    "strength_model": 1.0,
                    "strength_clip": 1.0,
                },
                "_meta": {"title": "Helga_Sinclair_-_Disney_Illustrious.safetensors"},
            },
            "85": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["80", 0],
                    "clip": ["80", 1],
                    "lora_name": "https://civitai.com/api/download/models/2631544",
                    "strength_model": 1.0,
                    "strength_clip": 1.0,
                },
                "_meta": {"title": "Klein-Anime-v2.safetensors"},
            },
            "86": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["85", 0],
                    "clip": ["85", 1],
                    "lora_name": "https://civitai.com/api/download/models/269354",
                    "strength_model": 1.0,
                    "strength_clip": 1.0,
                },
                "_meta": {"title": "sd_xl_dpo_lora_v1-128dim.safetensors"},
            },
            "74": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": ",,\nVertical close-up photography of a cat",
                    "clip": ["71", 0],
                },
            },
            "67": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "blurry", "clip": ["71", 0]},
            },
            "63": {
                "class_type": "CFGGuider",
                "inputs": {
                    "model": ["86", 0],
                    "positive": ["74", 0],
                    "negative": ["67", 0],
                    "cfg": 1,
                },
            },
            "62": {
                "class_type": "BasicScheduler",
                "inputs": {
                    "model": ["86", 0],
                    "scheduler": "simple",
                    "steps": 8,
                    "width": 832,
                    "height": 1216,
                },
            },
            "66": {
                "class_type": "EmptyFlux2LatentImage",
                "inputs": {"width": 832, "height": 1216, "batch_size": 1},
            },
            "9": {"class_type": "SaveImage", "inputs": {}},
        }
        from salad_studio import comfy_import as ci

        posted = ci.prompt_for_salad_replica(prompt)
        self.assertNotIn("80", posted)
        self.assertNotIn("86", posted)
        self.assertIn("85", posted)
        self.assertEqual(posted["85"]["inputs"]["model"], ["70", 0])
        self.assertEqual(posted["63"]["inputs"]["model"], ["85", 0])
        self.assertEqual(posted["74"]["inputs"]["clip"], ["85", 1])
        clip = str(posted["74"]["inputs"]["text"])
        self.assertIn("illustration", clip)
        self.assertNotIn("photography", clip.lower())
        self.assertFalse(clip.startswith("anime illustration"))
        self.assertEqual(posted["62"]["class_type"], "Flux2Scheduler")
        self.assertEqual(prompt["80"]["class_type"], "LoraLoader")
        self.assertEqual(posted["62"]["inputs"]["steps"], 8)

    def test_remap_distilled_sde_to_euler(self) -> None:
        self.assertEqual(
            rj.remap_distilled_sampler("dpmpp_sde", "flux-2-klein-9b-fp8.safetensors"),
            "euler",
        )
        self.assertEqual(
            rj.remap_distilled_sampler(
                "dpmpp_sde", "flux-2-klein-base-9b-fp8.safetensors"
            ),
            "dpmpp_sde",
        )

    def test_unknown_graph(self) -> None:
        with self.assertRaises(ValueError):
            rj.build_request(
                prompt_text="x",
                graph="sdxl",
                width=8,
                height=8,
                steps=1,
                seed=1,
                selected_ids=[],
            )

    def test_klein_graph_drops_flux1_and_pony(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            klein_a = ls.comfy_lora_name(ls.find_lora(KLEIN_DETAIL, extras))
            klein_b = ls.comfy_lora_name(ls.find_lora(KLEIN_IMPRESSIONISM, extras))
            ultra = ls.comfy_lora_name(ls.find_lora(FLUX1_ULTRA, extras))
            pony = ls.comfy_lora_name(ls.find_lora(PONY_WATERCOLOR, extras))
            body = rj.build_request(
                prompt_text="mixed",
                graph="klein",
                width=64,
                height=64,
                steps=4,
                seed=1,
                selected_ids=list(MIXED_IDS),
                extras_path=extras,
            )
        names = _lora_names(body)
        self.assertEqual(names, [klein_a, klein_b])
        self.assertNotIn(ultra, names)
        self.assertNotIn(pony, names)
        dumped = json.dumps(body)
        self.assertNotIn("UltraRealPhoto", dumped)
        self.assertNotIn("1026423", dumped)
        self.assertNotIn("Watercolor", dumped)

    def test_flux1_graph_drops_klein_and_pony(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            klein_a = ls.comfy_lora_name(ls.find_lora(KLEIN_DETAIL, extras))
            klein_b = ls.comfy_lora_name(ls.find_lora(KLEIN_IMPRESSIONISM, extras))
            ultra = ls.comfy_lora_name(ls.find_lora(FLUX1_ULTRA, extras))
            pony = ls.comfy_lora_name(ls.find_lora(PONY_WATERCOLOR, extras))
            body = rj.build_request(
                prompt_text="mixed",
                graph="flux1",
                width=64,
                height=64,
                steps=4,
                seed=1,
                selected_ids=list(MIXED_IDS),
                extras_path=extras,
            )
        names = _lora_names(body)
        self.assertEqual(names, [ultra])
        self.assertNotIn(klein_a, names)
        self.assertNotIn(klein_b, names)
        self.assertNotIn(pony, names)
        dumped = json.dumps(body)
        self.assertNotIn("klein_slider_detail", dumped)
        self.assertNotIn("impressionism_klein9b", dumped)
        self.assertNotIn("Watercolor", dumped)

    def test_civitai_url_gets_token_query(self) -> None:
        url = "https://civitai.com/api/download/models/2795018"
        out = rj.with_civitai_token(url, "secret-token")
        self.assertIn("token=secret-token", out)
        self.assertIn("/models/2795018", out)
        again = rj.with_civitai_token(out, "other")
        self.assertEqual(again, out)

    def test_authorize_does_not_mutate_input(self) -> None:
        body = {
            "prompt": {
                "80": {
                    "class_type": "LoraLoader",
                    "inputs": {
                        "lora_name": "https://civitai.com/api/download/models/2795018"
                    },
                }
            }
        }
        out = rj.authorize_civitai_urls(body, "abc")
        self.assertNotIn("token=", body["prompt"]["80"]["inputs"]["lora_name"])
        self.assertIn("token=abc", out["prompt"]["80"]["inputs"]["lora_name"])
        self.assertTrue(rj.payload_has_civitai_download(body))
        self.assertFalse(rj.payload_has_civitai_download(out))

    def test_a_model_only_lora_node_is_authenticated_too(self) -> None:
        """The check keys on the lora_name input, not the node class.

        A ``class_type == "LoraLoader"`` filter skipped LoraLoaderModelOnly, so a
        gated Civitai file reached the replica with no token and never loaded.
        """
        body = {
            "prompt": {
                "80": {
                    "class_type": "LoraLoaderModelOnly",
                    "inputs": {
                        "model": ["70", 0],
                        "lora_name": "https://civitai.com/api/download/models/2809256",
                        "strength_model": 1.0,
                    },
                }
            }
        }
        self.assertTrue(rj.payload_has_civitai_download(body))
        self.assertEqual(
            rj.civitai_lora_urls(body["prompt"]),
            ["https://civitai.com/api/download/models/2809256"],
        )
        out = rj.authorize_civitai_urls(body, "abc")
        self.assertIn(
            "token=abc", out["prompt"]["80"]["inputs"]["lora_name"]
        )
        self.assertNotIn("token=", body["prompt"]["80"]["inputs"]["lora_name"])
        self.assertFalse(rj.payload_has_civitai_download(out))

    def test_a_url_that_already_has_a_file_id_keeps_it(self) -> None:
        body = {
            "prompt": {
                "80": {
                    "class_type": "LoraLoaderModelOnly",
                    "inputs": {
                        "lora_name": "https://civitai.com/api/download/models/2625692?fileId=2513322"
                    },
                }
            }
        }
        out = rj.authorize_civitai_urls(body, "abc")
        url = out["prompt"]["80"]["inputs"]["lora_name"]
        self.assertIn("fileId=2513322", url)
        self.assertIn("token=abc", url)

    def test_config_from_payload_roundtrip_klein(self) -> None:
        text = "Aged art. Oil painting style.\n\nSurreal art."
        body = rj.build_request(
            prompt_text=text,
            graph="klein",
            width=1024,
            height=1024,
            steps=40,
            seed=1,
            selected_ids=["civitai:1449678@2795018"],
        )
        cfg = rj.config_from_payload(body)
        self.assertEqual(cfg["graph"], "klein")
        self.assertEqual(cfg["width"], 1024)
        self.assertEqual(cfg["height"], 1024)
        self.assertEqual(cfg["steps"], 40)
        self.assertEqual(cfg["prompt_text"], text)
        self.assertIn("civitai:1449678@2795018", cfg["selected_ids"])
        self.assertEqual(cfg["unmatched_loras"], [])



class UnetVocabulary(unittest.TestCase):
    """Three unet families. The SNOFS cut must NOT be read as the plain distilled
    one, its filename contains both "snofs" and "distilled", and mistaking it
    sends the request to the wrong container group."""

    def test_the_three_labels_round_trip(self) -> None:
        for fname, label in (
            (rj.UNET_BASE, "Base 9B"),
            (rj.UNET_DISTILLED, "Distilled 9B"),
            (rj.UNET_SNOFS, "SNOFS 9B"),
        ):
            self.assertEqual(rj.unet_label(fname), label, fname)
            self.assertEqual(rj.normalize_unet(label), fname, label)

    def test_the_label_tuple_covers_every_family(self) -> None:
        self.assertEqual(set(rj.UNET_LABELS), {"Base 9B", "Distilled 9B", "SNOFS 9B"})

    def test_a_snofs_build_not_in_the_keep_list_is_still_snofs(self) -> None:
        # a future SNOFS release is not in _UNET_KEEP and says "Distilled" in its name
        v14 = "snofsSexNudesAndOther_v14Klein9bDistilled_full_fp8.safetensors"
        self.assertEqual(rj.normalize_unet(v14), rj.UNET_SNOFS)

    def test_the_plain_cuts_are_unchanged(self) -> None:
        self.assertEqual(rj.normalize_unet("Flux\flux-2-klein-base-9b-fp8"), rj.UNET_BASE)
        self.assertEqual(rj.normalize_unet("flux-2-klein-9b-fp8"), rj.UNET_DISTILLED)


if __name__ == "__main__":
    unittest.main()
