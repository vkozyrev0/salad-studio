"""Civitai Comfy workflow + generation-data → Salad /prompt JSON."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for p in (str(TOOLS), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from salad_studio import comfy_import as ci  # noqa: E402
from salad_studio import request_json as rj  # noqa: E402
from salad_studio.test_watercolor_import import (  # noqa: E402
    WATERCOLOR_LORAS,
    WATERCOLOR_PASTE,
    _fake_search,
)


WORKFLOW = {
    "nodes": [
        {
            "id": 84,
            "type": "KSamplerSelect",
            "inputs": [],
            "widgets_values": ["euler"],
        },
        {
            "id": 86,
            "type": "CFGGuider",
            "inputs": [
                {"name": "model", "type": "MODEL", "link": 202},
                {"name": "positive", "type": "CONDITIONING", "link": 163},
                {"name": "negative", "type": "CONDITIONING", "link": 164},
            ],
            "widgets_values": [5],
        },
        {
            "id": 87,
            "type": "SamplerCustomAdvanced",
            "inputs": [
                {"name": "noise", "type": "NOISE", "link": 165},
                {"name": "guider", "type": "GUIDER", "link": 166},
                {"name": "sampler", "type": "SAMPLER", "link": 167},
                {"name": "sigmas", "type": "SIGMAS", "link": 168},
                {"name": "latent_image", "type": "LATENT", "link": 169},
            ],
            "widgets_values": [],
        },
        {
            "id": 79,
            "type": "MarkdownNote",
            "widgets_values": ["ignore me"],
        },
        {
            "id": 96,
            "type": "VAELoader",
            "inputs": [],
            "widgets_values": ["FLUX2\\flux2-vae.safetensors"],
        },
        {
            "id": 88,
            "type": "VAEDecode",
            "inputs": [
                {"name": "samples", "type": "LATENT", "link": 170},
                {"name": "vae", "type": "VAE", "link": 171},
            ],
            "widgets_values": [],
        },
        {
            "id": 114,
            "type": "SaveImage",
            "inputs": [{"name": "images", "type": "IMAGE", "link": 199}],
            "widgets_values": ["%date:yyyy-MM-dd%/Flux2"],
        },
        {
            "id": 89,
            "type": "EmptyFlux2LatentImage",
            "inputs": [
                {"name": "width", "type": "INT", "link": 172},
                {"name": "height", "type": "INT", "link": 173},
            ],
            "widgets_values": [1024, 1024, 1],
        },
        {
            "id": 94,
            "type": "UNETLoader",
            "inputs": [],
            "widgets_values": ["Flux.2\\flux-2-klein-base-9b-fp8.safetensors", "default"],
        },
        {
            "id": 95,
            "type": "CLIPLoader",
            "inputs": [],
            "widgets_values": [
                "Flux.2\\qwen_3_8b_fp8mixed.safetensors",
                "flux2",
                "default",
            ],
        },
        {
            "id": 85,
            "type": "Flux2Scheduler",
            "inputs": [
                {"name": "width", "type": "INT", "link": 160},
                {"name": "height", "type": "INT", "link": 161},
            ],
            "widgets_values": [40, 1024, 1024],
        },
        {
            "id": 90,
            "type": "CLIPTextEncode",
            "title": "CLIP Text Encode (Negative Prompt)",
            "inputs": [{"name": "clip", "type": "CLIP", "link": 204}],
            "widgets_values": [""],
        },
        {
            "id": 93,
            "type": "RandomNoise",
            "inputs": [],
            "widgets_values": [627393635013299, "randomize"],
        },
        {
            "id": 115,
            "type": "Power Lora Loader (rgthree)",
            "inputs": [
                {"name": "model", "type": "MODEL", "link": 200},
                {"name": "clip", "type": "CLIP", "link": 201},
            ],
            "widgets_values": [
                {},
                {"type": "PowerLoraLoaderHeaderWidget"},
                {
                    "on": True,
                    "lora": "AgedArt01a_CE_FLUX2_Klein9b_AIT5k.safetensors",
                    "strength": 0.5,
                    "strengthTwo": None,
                },
                {},
                "",
            ],
        },
        {
            "id": 91,
            "type": "PrimitiveInt",
            "title": "Width",
            "widgets_values": [1024, "fixed"],
        },
        {
            "id": 92,
            "type": "PrimitiveInt",
            "title": "Height",
            "widgets_values": [1024, "fixed"],
        },
        {
            "id": 97,
            "type": "CLIPTextEncode",
            "title": "CLIP Text Encode (Positive Prompt)",
            "inputs": [{"name": "clip", "type": "CLIP", "link": 203}],
            "widgets_values": [
                "Aged art. Oil painting style.\n\nBent over, under a load."
            ],
        },
    ],
    "links": [
        [160, 91, 0, 85, 0, "INT"],
        [161, 92, 0, 85, 1, "INT"],
        [163, 97, 0, 86, 1, "CONDITIONING"],
        [164, 90, 0, 86, 2, "CONDITIONING"],
        [165, 93, 0, 87, 0, "NOISE"],
        [166, 86, 0, 87, 1, "GUIDER"],
        [167, 84, 0, 87, 2, "SAMPLER"],
        [168, 85, 0, 87, 3, "SIGMAS"],
        [169, 89, 0, 87, 4, "LATENT"],
        [170, 87, 0, 88, 0, "LATENT"],
        [171, 96, 0, 88, 1, "VAE"],
        [172, 91, 0, 89, 0, "INT"],
        [173, 92, 0, 89, 1, "INT"],
        [199, 88, 0, 114, 0, "IMAGE"],
        [200, 94, 0, 115, 0, "MODEL"],
        [201, 95, 0, 115, 1, "CLIP"],
        [202, 115, 0, 86, 0, "MODEL"],
        [203, 115, 1, 97, 0, "CLIP"],
        [204, 115, 1, 90, 0, "CLIP"],
    ],
}

META = """Aged art. Oil painting style.

Surreal art.

Atmospheric.

Bent over, under a load, carrying a landscape on her back.
Steps: 40, CFG scale: 5, Sampler: Euler, Seed: 627393635013299, Model: Flux.2\\flux-2-klein-base-9b-fp8"""


WATERCOLOR_META = WATERCOLOR_PASTE


class ParseMetadata(unittest.TestCase):
    def test_civitai_generation_data(self) -> None:
        meta = ci.parse_civitai_metadata(META)
        self.assertIn("carrying a landscape", meta["prompt"])
        self.assertNotIn("Steps:", meta["prompt"])
        self.assertEqual(meta["steps"], 40)
        self.assertEqual(meta["cfg"], 5)
        self.assertEqual(meta["sampler"], "euler")
        self.assertEqual(meta["seed"], 627393635013299)
        self.assertEqual(meta["model"], "flux-2-klein-base-9b-fp8.safetensors")

    def test_civitai_negative_loras_size_and_dpm_sampler(self) -> None:
        meta = ci.parse_civitai_metadata(WATERCOLOR_META)
        self.assertIn("watercolor:1.3", meta["prompt"])
        self.assertIn("joyfull calm gentle smile", meta["prompt"])
        self.assertNotIn("<lora:", meta["prompt"])
        self.assertNotIn("Negative prompt", meta["prompt"])
        self.assertNotIn("Steps:", meta["prompt"])
        self.assertIn("bad, ugly, blurry", meta["negative"])
        self.assertNotIn("Steps:", meta["negative"])
        self.assertEqual(meta["steps"], 35)
        self.assertEqual(meta["cfg"], 4)
        self.assertEqual(meta["sampler"], "dpmpp_2s_ancestral")
        self.assertEqual(meta["scheduler"], "simple")
        self.assertEqual(meta["seed"], 169803930162055)
        self.assertEqual(meta["model"], "flux-2-klein-9b-fp8.safetensors")
        knobs = ci.knobs_from_sources(WATERCOLOR_META, "")
        self.assertEqual(knobs["unet"], "flux-2-klein-9b-fp8.safetensors")
        self.assertEqual(meta["width"], 1080)
        self.assertEqual(meta["height"], 1536)
        tags = list(meta.get("lora_tags") or [])
        self.assertEqual(len(tags), 10)
        self.assertEqual([t["name"] for t in tags], [row[0] for row in WATERCOLOR_LORAS])
        self.assertEqual(tags[0]["strength"], 0.45)
        self.assertEqual(tags[3]["strength"], 0.4)
        self.assertEqual(
            [t["name"] for t in tags].count("transparent-watercolor_IL_MIX"), 2
        )
        self.assertEqual(
            [t["name"] for t in tags].count("Ah! My Goddess_illustriousXL"), 2
        )
        blocking, notes = ci.inspect_pastes(WATERCOLOR_META, "")
        self.assertEqual(blocking, [])
        self.assertEqual(notes, [])

    def test_long_negative_stays_on_negative_clip(self) -> None:
        pos = "short picnic sketch of a woman"
        neg = (
            "stacked torsos, totem pole, poorly drawn, bad anatomy, wrong anatomy, "
            "extra limb, missing limb, floating limbs, mutated hands and fingers, "
            "disconnected limbs, mutation, ugly, worst quality, low quality, "
            "watermark, signature, bad hands"
        )
        self.assertGreater(len(neg), len(pos))
        text = (
            f"{pos}\nNegative prompt: {neg}\n"
            "Steps: 4, Sampler: Euler a, CFG scale: 1, Seed: 1, "
            "Model: flux-2-klein-9b-fp8, width: 1024, height: 1536"
        )
        body = ci.import_to_request(metadata_text=text)
        prompt = body["prompt"]
        self.assertEqual(prompt["63"]["inputs"]["positive"], ["74", 0])
        self.assertEqual(prompt["63"]["inputs"]["negative"], ["67", 0])
        self.assertIn("picnic sketch", prompt["74"]["inputs"]["text"])
        self.assertNotIn("stacked torsos", prompt["74"]["inputs"]["text"])
        self.assertIn("stacked torsos", prompt["67"]["inputs"]["text"])
        self.assertNotIn("picnic sketch", prompt["67"]["inputs"]["text"])

    def test_metadata_only_watercolor_builds_klein_graph(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            with patch.object(ci.ls, "civitai_search_lora", side_effect=_fake_search):
                body = ci.import_to_request(
                    metadata_text=WATERCOLOR_META, extras_path=extras
                )
        prompt = body["prompt"]
        self.assertEqual(
            prompt["70"]["inputs"]["unet_name"],
            "flux-2-klein-9b-fp8.safetensors",
        )
        self.assertIn("watercolor:1.3", prompt["74"]["inputs"]["text"])
        self.assertNotIn("<lora:", prompt["74"]["inputs"]["text"])
        self.assertIn("bad, ugly, blurry", prompt["67"]["inputs"]["text"])
        self.assertEqual(prompt["62"]["inputs"]["steps"], 35)
        self.assertEqual(prompt["63"]["inputs"]["cfg"], 4)
        self.assertEqual(prompt["61"]["inputs"]["sampler_name"], "dpmpp_2s_ancestral")
        self.assertEqual(prompt["73"]["inputs"]["noise_seed"], 169803930162055)
        self.assertEqual(prompt["66"]["inputs"]["width"], 1080)
        self.assertEqual(prompt["66"]["inputs"]["height"], 1536)
        self.assertEqual(prompt["72"]["inputs"]["vae_name"], "flux2-vae.safetensors")
        loaders = [
            (int(nid), n)
            for nid, n in prompt.items()
            if isinstance(n, dict) and n.get("class_type") == "LoraLoader"
        ]
        loaders.sort()
        self.assertEqual(len(loaders), 10)
        urls = [
            str((n.get("inputs") or {}).get("lora_name") or "") for _i, n in loaders
        ]
        strengths = [
            float((n.get("inputs") or {}).get("strength_model") or 0)
            for _i, n in loaders
        ]
        for i, (_tag, strength, ver, _fn) in enumerate(WATERCOLOR_LORAS):
            self.assertIn(str(ver), urls[i], urls[i])
            self.assertAlmostEqual(strengths[i], strength)
            self.assertTrue(urls[i].startswith("http"), urls[i])
        joined = " ".join(urls)
        self.assertIn("1810929", joined)
        self.assertIn("2825584", joined)
        self.assertNotIn("3131267", joined)
        self.assertNotIn("2735459", joined)
        self.assertNotIn("2255999", joined)


class ResolvePromptLoras(unittest.TestCase):
    def test_stale_cass_extra_is_replaced_by_aruhshura_p3(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            extras.write_text(
                json.dumps(
                    [
                        {
                            "id": "civitai:1@2255999",
                            "name": "cass_aruhshuraanima_preview3_1-step00004500",
                            "kind": "lora",
                            "base": "SD 1.5",
                            "source": {
                                "host": "civitai",
                                "download": "https://civitai.com/api/download/models/2255999",
                                "filename": "Cass.safetensors",
                                "version_id": "2255999",
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )

            def fake_search(query: str):
                return {
                    "page": "https://civitai.com/models/2444547?modelVersionId=2848936",
                    "download": "https://civitai.com/api/download/models/2848936",
                    "filename": "cass_aruhshuraanima_preview3_1-step00004500.safetensors",
                    "name": "Cass/Aruhshura (Latest style) | Style",
                }

            with patch.object(ci.ls, "civitai_search_lora", side_effect=fake_search):
                specs, missing = ci.resolve_prompt_loras(
                    [
                        {
                            "name": "cass_aruhshuraanima_preview3_1-step00004500",
                            "strength": 0.65,
                        }
                    ],
                    extras_path=extras,
                    search=True,
                )
        self.assertEqual(missing, [])
        self.assertEqual(len(specs), 1)
        self.assertIn("2848936", specs[0]["lora_name"])
        self.assertNotIn("2255999", specs[0]["lora_name"])

    def test_stale_klein_anime_v1_extra_is_replaced_by_v3(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            extras.write_text(
                json.dumps(
                    [
                        {
                            "id": "civitai:2432849@2735459",
                            "name": "Flux.2 Klein 9B anime",
                            "kind": "lora",
                            "base": "Flux.2 Klein 9B",
                            "source": {
                                "host": "civitai",
                                "download": "https://civitai.com/api/download/models/2735459",
                                "filename": "Flux.2 Klein 9B anime.safetensors",
                                "model_id": 2432849,
                                "version_id": 2735459,
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )

            def fake_search(query: str):
                return {
                    "page": "https://civitai.com/models/2432849?modelVersionId=2825584",
                    "download": "https://civitai.com/api/download/models/2825584",
                    "filename": "Flux.2 Klein 9B Anime V3 Refined.safetensors",
                    "name": "Mrpopo's Flux.2 Klein 9B anime",
                    "model_id": 2432849,
                    "version_id": 2825584,
                }

            with patch.object(ci.ls, "civitai_search_lora", side_effect=fake_search):
                specs, missing = ci.resolve_prompt_loras(
                    [{"name": "Flux.2 Klein 9B anime", "strength": 0.85}],
                    extras_path=extras,
                    search=True,
                )
        self.assertEqual(missing, [])
        self.assertEqual(len(specs), 1)
        self.assertIn("2825584", specs[0]["lora_name"])
        self.assertNotIn("2735459", specs[0]["lora_name"])

    def test_stale_goddess_v3_extra_is_replaced_by_v2_filename(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            extras.write_text(
                json.dumps(
                    [
                        {
                            "id": "civitai:999695@3131267",
                            "name": "Ah! My Goddess_illustriousXL",
                            "kind": "lora",
                            "source": {
                                "host": "civitai",
                                "download": "https://civitai.com/api/download/models/3131267",
                                "filename": "Ah! My Goddess_v3_illustriousXL.safetensors",
                                "model_id": 999695,
                                "version_id": 3131267,
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )

            def fake_search(query: str):
                return {
                    "page": "https://civitai.com/models/999695?modelVersionId=1810929",
                    "download": "https://civitai.com/api/download/models/1810929",
                    "filename": "Ah! My Goddess_illustriousXL.safetensors",
                    "name": "Ah! My Goddess",
                    "model_id": 999695,
                    "version_id": 1810929,
                }

            with patch.object(ci.ls, "civitai_search_lora", side_effect=fake_search):
                specs, missing = ci.resolve_prompt_loras(
                    [{"name": "Ah! My Goddess_illustriousXL", "strength": 0.8}],
                    extras_path=extras,
                    search=True,
                )
        self.assertEqual(missing, [])
        self.assertEqual(len(specs), 1)
        self.assertIn("1810929", specs[0]["lora_name"])
        self.assertNotIn("3131267", specs[0]["lora_name"])


class CivitaiImageHints(unittest.TestCase):
    def test_hash_hint_pins_klein_v1_not_v3(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            hints = {
                "Flux.2 Klein 9B anime": {
                    "version_id": 2735459,
                    "version_name": "V1",
                    "filename": "Flux.2 Klein 9B anime.safetensors",
                }
            }
            specs, missing = ci.resolve_prompt_loras(
                [{"name": "Flux.2 Klein 9B anime", "strength": 0.85}],
                extras_path=extras,
                search=False,
                hints=hints,
            )
        self.assertEqual(missing, [])
        self.assertEqual(len(specs), 1)
        self.assertIn("2735459", specs[0]["lora_name"])
        self.assertNotIn("2825584", specs[0]["lora_name"])
        self.assertEqual(specs[0].get("version_name"), "V1")
        self.assertEqual(specs[0].get("variation"), "V1")

    def test_resource_order_matches_civitai_panel(self) -> None:
        item = {
            "modelVersionIds": [
                1730326,
                1805810,
                1810929,
                2137047,
                2658598,
                2713096,
                2735459,
                2848936,
                2905490,
            ],
            "meta": {
                "meta": {
                    "resources": [
                        {
                            "name": "transparent-watercolor_IL_MIX",
                            "type": "lora",
                            "weight": 0.45,
                        },
                        {"name": "Sakaki_Azumanga_Daioh", "type": "lora", "weight": 0.7},
                        {
                            "name": "transparent-watercolor_IL_MIX",
                            "type": "lora",
                            "weight": 0.4,
                        },
                        {"name": "Ah! My Goddess_illustriousXL", "type": "lora"},
                        {"name": "Flux.2 Klein 9B anime", "type": "lora"},
                        {"name": "CitrixCitronOC_ANIMA", "type": "lora", "weight": 0.5},
                        {
                            "name": "cass_aruhshuraanima_preview3_1-step00004500",
                            "type": "lora",
                            "weight": 0.65,
                        },
                        {
                            "name": "anima-preview-3-masterpieces-v5",
                            "type": "lora",
                            "weight": 0.8,
                        },
                        {
                            "name": "Alpha_-_YKK_-_Yokohama_Kaidashi_Kikou",
                            "type": "lora",
                            "weight": 0.75,
                        },
                    ]
                }
            },
        }
        hints = {
            "transparent-watercolor_IL_MIX": {"version_id": 1730326},
            "Sakaki_Azumanga_Daioh": {"version_id": 1805810},
            "Ah! My Goddess_illustriousXL": {"version_id": 1810929},
            "Alpha_-_YKK_-_Yokohama_Kaidashi_Kikou": {"version_id": 2137047},
            "CitrixCitronOC_ANIMA": {"version_id": 2713096},
            "Flux.2 Klein 9B anime": {"version_id": 2735459},
            "cass_aruhshuraanima_preview3_1-step00004500": {"version_id": 2848936},
            "anima-preview-3-masterpieces-v5": {"version_id": 2905490},
        }
        tags = ci.resource_order_tags(item, hints)
        assert tags is not None
        names = [t["name"] for t in tags]
        self.assertEqual(
            names,
            [
                "transparent-watercolor_IL_MIX",
                "Sakaki_Azumanga_Daioh",
                "Ah! My Goddess_illustriousXL",
                "Alpha_-_YKK_-_Yokohama_Kaidashi_Kikou",
                "CitrixCitronOC_ANIMA",
                "Flux.2 Klein 9B anime",
                "cass_aruhshuraanima_preview3_1-step00004500",
                "anima-preview-3-masterpieces-v5",
            ],
        )
        by_name = {t["name"]: t["strength"] for t in tags}
        self.assertAlmostEqual(by_name["transparent-watercolor_IL_MIX"], 0.45)
        self.assertAlmostEqual(by_name["Ah! My Goddess_illustriousXL"], 1.0)
        self.assertAlmostEqual(by_name["Flux.2 Klein 9B anime"], 1.0)
        self.assertAlmostEqual(by_name["CitrixCitronOC_ANIMA"], 0.5)


class DarkAtmospheric122279320(unittest.TestCase):
    def test_hint_binds_ce_filename_to_resource_version(self) -> None:
        hints = {
            "Dark Atmospheric Style - CE": {
                "version_id": 2720915,
                "version_name": "V01a - Flux.2 Klein 9b",
                "filename": "",
                "model_name": "Dark Atmospheric Style - CE",
            }
        }
        hit = ci._hint_for_lora_name(
            "DarkAtmospheric01a_CE_FLUX2_Klein9b_AIT4k", hints
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(int(hit["version_id"]), 2720915)

    def test_resolve_local_uses_unique_resource_hint(self) -> None:
        prompt = {
            "115": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["94", 0],
                    "clip": ["95", 0],
                    "lora_name": "DarkAtmospheric01a_CE_FLUX2_Klein9b_AIT4k.safetensors",
                    "strength_model": 0.5,
                    "strength_clip": 0.5,
                },
            }
        }
        hints = {
            "Dark Atmospheric Style - CE": {
                "version_id": 2720915,
                "filename": "",
                "model_name": "Dark Atmospheric Style - CE",
            }
        }
        spec = {
            "lora_name": "https://civitai.com/api/download/models/2720915",
            "filename": "DarkAtmospheric01a_CE_FLUX2_Klein9b_AIT4k.safetensors",
            "tag": "Dark Atmospheric Style - CE",
            "strength_model": 0.5,
            "strength_clip": 0.5,
            "verified": True,
        }
        with patch.object(ci, "resolve_prompt_loras", return_value=([spec], [])) as rp:
            missing = ci.resolve_local_lora_nodes(prompt, hints=hints)
        self.assertEqual(missing, [])
        self.assertIn(
            "2720915", prompt["115"]["inputs"]["lora_name"]
        )
        rp.assert_called()
        kwargs = rp.call_args.kwargs
        self.assertIn("DarkAtmospheric01a_CE_FLUX2_Klein9b_AIT4k", kwargs.get("hints") or {})


class NonComfyResourceOrder(unittest.TestCase):
    """Image 130704037: no Comfy nodes; Resources chips are the apply order."""

    ITEM = {
        "id": 130704037,
        "modelVersionIds": [
            269354,
            1346283,
            1710052,
            1710060,
            1810929,
            1829247,
            2631544,
            2658598,
        ],
        "meta": {
            "meta": {
                "resources": [
                    {
                        "name": "Helga_Sinclair_-_Disney_Illustrious",
                        "type": "lora",
                        "weight": 1,
                    },
                    {"name": "ILVPAlicia", "type": "lora", "weight": 1},
                    {"name": "4k4n3_rnm", "type": "lora", "weight": 1},
                    {"name": "ILVPFreya", "type": "lora", "weight": 1},
                    {"name": "Klein-Anime-v2", "type": "lora", "weight": 1},
                    {"name": "sd_xl_dpo_lora_v1-128dim", "type": "lora", "weight": 1},
                    {"name": "ABKSKXLlokr2f-000147", "type": "lora", "weight": 1},
                    {"name": "Ah! My Goddess_illustriousXL", "type": "lora"},
                    {"name": "flux-2-klein-9b-fp8", "type": "model"},
                ]
            }
        },
    }
    HINTS = {
        "sd_xl_dpo_lora_v1-128dim": {"version_id": 269354},
        "4k4n3_rnm": {"version_id": 1346283},
        "ILVPAlicia": {"version_id": 1710052},
        "ILVPFreya": {"version_id": 1710060},
        "Ah! My Goddess_illustriousXL": {"version_id": 1810929},
        "Helga_Sinclair_-_Disney_Illustrious": {"version_id": 1829247},
        "Klein-Anime-v2": {"version_id": 2631544},
    }
    SITE_ORDER = [
        "sd_xl_dpo_lora_v1-128dim",
        "4k4n3_rnm",
        "ILVPAlicia",
        "ILVPFreya",
        "Ah! My Goddess_illustriousXL",
        "Helga_Sinclair_-_Disney_Illustrious",
        "Klein-Anime-v2",
    ]

    def test_tags_follow_model_version_ids_then_prompt_extras(self) -> None:
        paste = (
            "https://civitai.com/images/130704037\n"
            "cat photography\n"
            "<lora:Helga_Sinclair_-_Disney_Illustrious:1> "
            "<lora:ILVPAlicia:1> <lora:4k4n3_rnm:1> <lora:ILVPFreya:1> "
            "<lora:Ah! My Goddess_illustriousXL:0.75> "
            "<lora:Klein-Anime-v2:1> <lora:sd_xl_dpo_lora_v1-128dim:1> "
            "<lora:ABKSKXLlokr2f-000147:1>\n"
            "Negative prompt: blurry\n"
            "Steps: 8, CFG scale: 1, Sampler: Euler simple, "
            "Seed: 1, Model: flux-2-klein-9b-fp8"
        )
        meta = ci.parse_civitai_metadata(paste)
        tags = ci.non_comfy_lora_tags(meta, self.ITEM, self.HINTS)
        names = [t["name"] for t in tags]
        self.assertEqual(names[:7], self.SITE_ORDER)
        self.assertEqual(names[-1], "ABKSKXLlokr2f-000147")
        goddess = next(t for t in tags if "Goddess" in t["name"])
        self.assertEqual(goddess["strength"], 0.75)

    def test_convert_builds_loaders_in_site_resource_order(self) -> None:
        meta = {
            "prompt": "cat",
            "negative": "blurry",
            "steps": 8,
            "cfg": 1,
            "seed": 1,
            "width": 832,
            "height": 1216,
            "model": "flux-2-klein-9b-fp8",
            "sampler": "euler",
            "scheduler": "simple",
            "lora_tags": [
                {"name": "Helga_Sinclair_-_Disney_Illustrious", "strength": 1.0},
                {"name": "Klein-Anime-v2", "strength": 1.0},
                {"name": "sd_xl_dpo_lora_v1-128dim", "strength": 1.0},
                {"name": "ABKSKXLlokr2f-000147", "strength": 1.0},
            ],
        }

        def fake_resolve(tags, **_kw):
            specs = []
            for t in tags:
                specs.append(
                    {
                        "lora_name": "https://civitai.com/api/download/models/1",
                        "filename": str(t["name"]) + ".safetensors",
                        "tag": t["name"],
                        "strength_model": t.get("strength") or 1,
                        "strength_clip": t.get("strength") or 1,
                        "verified": True,
                    }
                )
            missing = [
                t["name"] for t in tags if "ABKSK" in str(t.get("name") or "")
            ]
            return specs, missing

        with patch.object(ci, "resolve_prompt_loras", side_effect=fake_resolve):
            body = ci.convert_klein_from_metadata(
                meta, img=self.ITEM, hints=self.HINTS
            )
        loaders = [
            (nid, n)
            for nid, n in body["prompt"].items()
            if isinstance(n, dict) and n.get("class_type") == "LoraLoader"
        ]
        titles = [
            str((n.get("_meta") or {}).get("title") or n["inputs"].get("lora_name"))
            for _nid, n in loaders
        ]
        joined = " ".join(titles)
        # Chain order is attach order: site chips, then ABKSK extra.
        order_nids = [nid for nid, _n in loaders]
        self.assertEqual(order_nids[0], "80")
        tags = ci.non_comfy_lora_tags(meta, self.ITEM, self.HINTS)
        self.assertEqual([t["name"] for t in tags][:7], self.SITE_ORDER)
        self.assertIn("Klein-Anime-v2", joined)
        last_klein = None
        for nid, node in loaders:
            title = str((node.get("_meta") or {}).get("title") or "")
            if "Klein-Anime" in title:
                last_klein = nid
        self.assertEqual(last_klein, "86")
        self.assertTrue(any("ABKSK" in t for t in titles) or len(loaders) >= 8)

    def test_image_url_extract(self) -> None:
        self.assertEqual(
            ci.ls.civitai_image_id("see https://civitai.com/images/130704876 extra"),
            "130704876",
        )

    def test_generation_data_from_image_looks_like_copy_all(self) -> None:
        item = {
            "meta": {
                "meta": {
                    "prompt": "a tree <lora:Flux.2 Klein 9B anime:0.85>",
                    "negativePrompt": "blurry",
                    "steps": 35,
                    "cfgScale": 4,
                    "sampler": "DPM++ 2S a simple",
                    "seed": 169803930162055,
                    "Model": "flux-2-klein-9b-fp8",
                    "width": 1080,
                    "height": 1536,
                    "Model hash": "865ba09f5b",
                }
            }
        }
        text = ci.generation_data_from_image(item)
        self.assertIn("<lora:Flux.2 Klein 9B anime:0.85>", text)
        self.assertIn("Negative prompt: blurry", text)
        self.assertIn("Steps: 35", text)
        self.assertIn("CFG scale: 4", text)
        self.assertIn("Sampler: DPM++ 2S a simple", text)
        self.assertIn("Model hash: 865ba09f5b", text)

    def test_workflow_from_generation_reads_comfy_nodes(self) -> None:
        gen = {"comfy": {"nodes": [{"id": 1, "type": "KSampler"}], "links": []}}
        raw = ci.workflow_from_generation(gen)
        obj = json.loads(raw)
        self.assertIn("nodes", obj)
        self.assertEqual(ci.workflow_from_generation({"prompt": "no graph"}), "")

    def test_fetch_civitai_image_pastes_fills_copy_all(self) -> None:
        item = {
            "id": 130704876,
            "meta": {
                "meta": {
                    "prompt": "a tree <lora:Flux.2 Klein 9B anime:0.85>",
                    "negativePrompt": "blurry",
                    "steps": 4,
                    "cfgScale": 1,
                    "sampler": "euler",
                    "seed": 1,
                    "Model": "flux-2-klein-9b-fp8",
                    "width": 1024,
                    "height": 1024,
                    "comfy": {"nodes": [{"id": 9}], "links": []},
                }
            },
        }
        with patch.object(ci.ls, "fetch_civitai_image", return_value=item):
            pastes = ci.fetch_civitai_image_pastes("130704876")
        self.assertIn("<lora:Flux.2 Klein 9B anime:0.85>", pastes["metadata"])
        self.assertIn("nodes", pastes["workflow"])
        self.assertEqual(pastes["image_id"], "130704876")

    def test_resolve_local_lora_filename_to_civitai_url(self) -> None:
        prompt = {
            "80": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["70", 0],
                    "clip": ["71", 0],
                    "lora_name": "PencilDrawEn01_CE_FLUX2_Klein9b_AIT4k.safetensors",
                    "strength_model": 0.8,
                    "strength_clip": 0.8,
                },
            }
        }

        def fake_search(query: str):
            return {
                "page": "https://civitai.com/models/561940?modelVersionId=2760251",
                "download": "https://civitai.com/api/download/models/2760251",
                "filename": "PencilDrawEn01_CE_FLUX2_Klein9b_AIT4k.safetensors",
                "name": "Pencil Drawing Enhancer - CE",
                "version_id": 2760251,
                "version_name": "V01 - Flux.2 Klein 9b",
                "verified": True,
            }

        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            with patch.object(ci.ls, "civitai_search_lora", side_effect=fake_search):
                missing = ci.resolve_local_lora_nodes(prompt, extras_path=extras)
        self.assertEqual(missing, [])
        self.assertIn("2760251", prompt["80"]["inputs"]["lora_name"])
        self.assertEqual(
            (prompt["80"].get("_meta") or {}).get("variation"), "V01"
        )
        self.assertEqual(
            (prompt["80"].get("_meta") or {}).get("version"),
            "V01 - Flux.2 Klein 9b",
        )

    def test_inspect_resolves_pencildraw_and_does_not_block(self) -> None:
        wf = {
            "nodes": [
                {
                    "id": 115,
                    "type": "Power Lora Loader (rgthree)",
                    "inputs": [
                        {"name": "model", "link": 200},
                        {"name": "clip", "link": 201},
                    ],
                    "widgets_values": [
                        {},
                        {"type": "PowerLoraLoaderHeaderWidget"},
                        {
                            "on": True,
                            "lora": "PencilDrawEn01_CE_FLUX2_Klein9b_AIT4k.safetensors",
                            "strength": 0.8,
                            "strengthTwo": None,
                        },
                    ],
                },
                {
                    "id": 94,
                    "type": "UNETLoader",
                    "widgets_values": [
                        "flux-2-klein-base-9b-fp8.safetensors",
                        "default",
                    ],
                },
                {
                    "id": 95,
                    "type": "CLIPLoader",
                    "widgets_values": [
                        "qwen_3_8b_fp8mixed.safetensors",
                        "flux2",
                        "default",
                    ],
                },
            ],
            "links": [
                [200, 94, 0, 115, 0, "MODEL"],
                [201, 95, 0, 115, 1, "CLIP"],
            ],
        }

        def fake_search(query: str):
            return {
                "download": "https://civitai.com/api/download/models/2760251",
                "filename": "PencilDrawEn01_CE_FLUX2_Klein9b_AIT4k.safetensors",
                "name": "Pencil Drawing Enhancer - CE",
                "version_id": 2760251,
                "version_name": "V01 - Flux.2 Klein 9b",
                "verified": True,
            }

        with patch.object(ci.ls, "civitai_search_lora", side_effect=fake_search):
            blocking, notes = ci.inspect_pastes("", json.dumps(wf))
        self.assertEqual(blocking, [])
        blob = " ".join(notes)
        self.assertNotIn("local filename", blob.lower())

    def test_primitive_int_links_do_not_crash_fill_knobs(self) -> None:
        wf = {
            "nodes": [
                {
                    "id": 91,
                    "type": "PrimitiveInt",
                    "title": "Width",
                    "widgets_values": [768, "fixed"],
                },
                {
                    "id": 92,
                    "type": "PrimitiveInt",
                    "title": "Height",
                    "widgets_values": [1024, "fixed"],
                },
                {
                    "id": 89,
                    "type": "EmptyFlux2LatentImage",
                    "inputs": [
                        {"name": "width", "type": "INT", "link": 172},
                        {"name": "height", "type": "INT", "link": 173},
                    ],
                    "widgets_values": [1024, 1024, 1],
                },
                {
                    "id": 85,
                    "type": "Flux2Scheduler",
                    "inputs": [
                        {"name": "width", "type": "INT", "link": 160},
                        {"name": "height", "type": "INT", "link": 161},
                    ],
                    "widgets_values": [40, 1024, 1024],
                },
            ],
            "links": [
                [160, 91, 0, 85, 0, "INT"],
                [161, 92, 0, 85, 1, "INT"],
                [172, 91, 0, 89, 0, "INT"],
                [173, 92, 0, 89, 1, "INT"],
            ],
        }
        knobs = ci.knobs_from_sources("", json.dumps(wf))
        self.assertEqual(knobs.get("width"), 768)
        self.assertEqual(knobs.get("height"), 1024)
        self.assertEqual(knobs.get("steps"), 40)

    def test_fetch_comfy_blob_expands_power_lora_not_rgthree(self) -> None:
        blob = {
            "prompt": {
                "94": {
                    "class_type": "UNETLoader",
                    "inputs": {"unet_name": "flux-2-klein-base-9b-fp8.safetensors"},
                },
                "95": {
                    "class_type": "CLIPLoader",
                    "inputs": {
                        "clip_name": "qwen_3_8b_fp8mixed.safetensors",
                        "type": "flux2",
                    },
                },
                "115": {
                    "class_type": "Power Lora Loader (rgthree)",
                    "inputs": {
                        "model": ["94", 0],
                        "clip": ["95", 0],
                        "lora_1": {
                            "on": True,
                            "lora": "PencilDrawEn01_CE_FLUX2_Klein9b_AIT4k.safetensors",
                            "strength": 0.8,
                        },
                    },
                },
                "86": {
                    "class_type": "CFGGuider",
                    "inputs": {"model": ["115", 0], "cfg": 5},
                },
            },
            "workflow": {
                "nodes": [
                    {
                        "id": 115,
                        "type": "Power Lora Loader (rgthree)",
                        "inputs": [
                            {"name": "model", "link": 200},
                            {"name": "clip", "link": 201},
                        ],
                        "widgets_values": [
                            {},
                            {"type": "PowerLoraLoaderHeaderWidget"},
                            {
                                "on": True,
                                "lora": "PencilDrawEn01_CE_FLUX2_Klein9b_AIT4k.safetensors",
                                "strength": 0.8,
                            },
                        ],
                    },
                    {
                        "id": 94,
                        "type": "UNETLoader",
                        "widgets_values": [
                            "flux-2-klein-base-9b-fp8.safetensors",
                            "default",
                        ],
                    },
                    {
                        "id": 95,
                        "type": "CLIPLoader",
                        "widgets_values": [
                            "qwen_3_8b_fp8mixed.safetensors",
                            "flux2",
                            "default",
                        ],
                    },
                ],
                "links": [
                    [200, 94, 0, 115, 0, "MODEL"],
                    [201, 95, 0, 115, 1, "CLIP"],
                ],
            },
        }
        raw = ci.workflow_from_generation({"comfy": json.dumps(blob)})
        ui = json.loads(raw)
        self.assertIn("nodes", ui)
        self.assertNotIn("prompt", ui)
        with patch.object(ci.ls, "civitai_search_lora", return_value={
            "download": "https://civitai.com/api/download/models/2760251",
            "filename": "PencilDrawEn01_CE_FLUX2_Klein9b_AIT4k.safetensors",
            "version_id": 2760251,
            "version_name": "V01 - Flux.2 Klein 9b",
            "verified": True,
        }):
            body = ci.import_to_request(workflow_text=raw)
        types = {
            n.get("class_type")
            for n in body["prompt"].values()
            if isinstance(n, dict)
        }
        self.assertNotIn("Power Lora Loader (rgthree)", types)
        self.assertIn("LoraLoader", types)

    def test_api_prompt_without_ui_nodes_still_expands_power_lora(self) -> None:
        obj = {
            "prompt": {
                "115": {
                    "class_type": "Power Lora Loader (rgthree)",
                    "inputs": {
                        "model": ["94", 0],
                        "clip": ["95", 0],
                        "lora_1": {
                            "on": True,
                            "lora": "foo.safetensors",
                            "strength": 0.5,
                        },
                    },
                }
            }
        }
        body = ci.salad_body_from_comfy_obj(obj)
        node = body["prompt"]["115"]
        self.assertEqual(node["class_type"], "LoraLoader")
        self.assertEqual(node["inputs"]["lora_name"], "foo.safetensors")


class WorkflowConvert(unittest.TestCase):
    def test_workflow_to_salad_prompt(self) -> None:
        body = ci.import_to_request(workflow_text=json.dumps(WORKFLOW))
        prompt = body["prompt"]
        self.assertNotIn("79", prompt)
        self.assertIn("91", prompt)
        self.assertEqual(prompt["91"]["class_type"], "PrimitiveInt")
        self.assertEqual(prompt["94"]["class_type"], "UNETLoader")
        self.assertEqual(
            prompt["94"]["inputs"]["unet_name"],
            "flux-2-klein-base-9b-fp8.safetensors",
        )
        self.assertEqual(prompt["96"]["inputs"]["vae_name"], "flux2-vae.safetensors")
        self.assertEqual(prompt["84"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(prompt["86"]["inputs"]["cfg"], 5)
        self.assertEqual(prompt["93"]["inputs"]["noise_seed"], 627393635013299)
        self.assertEqual(prompt["89"]["inputs"]["width"], ["91", 0])
        self.assertEqual(prompt["89"]["inputs"]["height"], ["92", 0])
        self.assertEqual(prompt["85"]["inputs"]["steps"], 40)
        self.assertEqual(prompt["115"]["class_type"], "LoraLoader")
        self.assertIn("2795018", prompt["115"]["inputs"]["lora_name"])
        self.assertEqual(prompt["115"]["inputs"]["strength_model"], 0.5)
        self.assertEqual(prompt["86"]["inputs"]["model"], ["115", 0])
        self.assertEqual(prompt["97"]["inputs"]["clip"], ["115", 1])
        self.assertEqual(prompt["90"]["inputs"]["clip"], ["115", 1])
        self.assertEqual(prompt["95"]["class_type"], "CLIPLoader")
        self.assertIn("Bent over", prompt["97"]["inputs"]["text"])
        self.assertEqual(body["convert_output"]["format"], "jpeg")

    def test_metadata_overlays_workflow_prompt(self) -> None:
        body = ci.import_to_request(
            workflow_text=json.dumps(WORKFLOW), metadata_text=META
        )
        self.assertIn("Bent over", body["prompt"]["97"]["inputs"]["text"])
        self.assertEqual(body["prompt"]["86"]["inputs"]["cfg"], 5)
        self.assertEqual(body["prompt"]["85"]["inputs"]["steps"], 40)

    def test_metadata_only_builds_klein_graph(self) -> None:
        body = ci.import_to_request(metadata_text=META)
        prompt = body["prompt"]
        self.assertEqual(prompt["70"]["inputs"]["unet_name"], "flux-2-klein-base-9b-fp8.safetensors")
        self.assertIn("carrying a landscape", prompt["74"]["inputs"]["text"])
        self.assertEqual(prompt["62"]["inputs"]["steps"], 40)
        self.assertEqual(prompt["63"]["inputs"]["cfg"], 5)
        self.assertEqual(prompt["61"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(prompt["73"]["inputs"]["noise_seed"], 627393635013299)

    def test_stallion_workflow_keeps_cfg5_seed_flux2(self) -> None:
        wf = json.dumps(WORKFLOW)
        # Same graph as the Civitai stallion plate, with 768 height + site seed.
        data = json.loads(wf)
        for node in data["nodes"]:
            if node.get("id") == 92:
                node["widgets_values"] = [768, "fixed"]
            if node.get("id") == 93:
                node["widgets_values"] = [116941054518963, "randomize"]
        meta = (
            "Aged painting. Oil painting style.\n\n"
            "Silhouette of a stallion rearing up. On a hillside at sunset. "
            "A wizened tree on the foreground.\n"
            "Steps: 40, CFG scale: 5, Sampler: Euler, "
            "Seed: 116941054518963, Model: Flux.2\\flux-2-klein-base-9b-fp8"
        )
        knobs = ci.knobs_from_sources(meta, json.dumps(data))
        self.assertEqual(knobs["cfg"], 5)
        self.assertEqual(knobs["seed"], 116941054518963)
        self.assertEqual(knobs["scheduler"], "flux2")
        self.assertEqual(knobs["height"], 768)
        body = ci.import_to_request(
            workflow_text=json.dumps(data),
            metadata_text=meta,
            knobs=knobs,
        )
        prompt = body["prompt"]
        self.assertEqual(prompt["86"]["inputs"]["cfg"], 5)
        self.assertEqual(prompt["93"]["inputs"]["noise_seed"], 116941054518963)
        self.assertEqual(prompt["85"]["class_type"], "Flux2Scheduler")
        self.assertEqual(prompt["85"]["inputs"]["steps"], 40)
        self.assertEqual(prompt["92"]["inputs"]["value"], 768)
        self.assertEqual(prompt["89"]["inputs"]["height"], ["92", 0])
        self.assertEqual(prompt["84"]["inputs"]["sampler_name"], "euler")
        self.assertIn("2795018", prompt["115"]["inputs"]["lora_name"])
        self.assertNotEqual(prompt["86"]["inputs"]["cfg"], 1)

    def test_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            ci.import_to_request()


DISTILLED_META = (
    "Sampler: Euler, Seed: 824168918863563, Model: Flux\\flux-2-klein-9b-fp8"
)

DISTILLED = {
    "nodes": [
        {
            "id": 197,
            "type": "ReferenceLatent",
            "inputs": [
                {"name": "conditioning", "type": "CONDITIONING", "link": 261},
                {"name": "latent", "shape": 7, "type": "LATENT", "link": None},
            ],
            "widgets_values": [],
        },
        {
            "id": 191,
            "type": "ConditioningZeroOut",
            "inputs": [{"name": "conditioning", "type": "CONDITIONING", "link": 249}],
            "widgets_values": [],
        },
        {
            "id": 195,
            "type": "Flux2Scheduler",
            "inputs": [
                {"name": "width", "type": "INT", "link": 281},
                {"name": "height", "type": "INT", "link": 283},
            ],
            "widgets_values": [4, 1024, 1024],
        },
        {
            "id": 196,
            "type": "EmptyFlux2LatentImage",
            "inputs": [
                {"name": "width", "type": "INT", "link": 282},
                {"name": "height", "type": "INT", "link": 284},
            ],
            "widgets_values": [1024, 1024, 1],
        },
        {
            "id": 190,
            "type": "CFGGuider",
            "inputs": [
                {"name": "model", "type": "MODEL", "link": 274},
                {"name": "positive", "type": "CONDITIONING", "link": 259},
                {"name": "negative", "type": "CONDITIONING", "link": 262},
            ],
            "widgets_values": [1],
        },
        {
            "id": 180,
            "type": "KSamplerSelect",
            "inputs": [],
            "widgets_values": ["euler"],
        },
        {
            "id": 184,
            "type": "VAELoader",
            "inputs": [],
            "widgets_values": ["FLUX2\\full_encoder_small_decoder.safetensors"],
        },
        {
            "id": 183,
            "type": "CLIPLoader",
            "inputs": [],
            "widgets_values": [
                "Qwen\\qwen_3_8b_fp8mixed.safetensors",
                "flux2",
                "default",
            ],
        },
        {
            "id": 187,
            "type": "SamplerCustomAdvanced",
            "inputs": [
                {"name": "noise", "type": "NOISE", "link": 240},
                {"name": "guider", "type": "GUIDER", "link": 241},
                {"name": "sampler", "type": "SAMPLER", "link": 242},
                {"name": "sigmas", "type": "SIGMAS", "link": 243},
                {"name": "latent_image", "type": "LATENT", "link": 244},
            ],
            "widgets_values": [],
        },
        {
            "id": 182,
            "type": "UNETLoader",
            "inputs": [],
            "widgets_values": ["Flux\\flux-2-klein-9b-fp8.safetensors", "default"],
        },
        {
            "id": 188,
            "type": "VAEDecode",
            "inputs": [
                {"name": "samples", "type": "LATENT", "link": 245},
                {"name": "vae", "type": "VAE", "link": 270},
            ],
            "widgets_values": [],
        },
        {
            "id": 181,
            "type": "RandomNoise",
            "inputs": [],
            "widgets_values": [824168918863563, "randomize"],
        },
        {
            "id": 200,
            "type": "Power Lora Loader (rgthree)",
            "inputs": [
                {"name": "model", "type": "MODEL", "link": 271},
                {"name": "clip", "type": "CLIP", "link": 272},
            ],
            "widgets_values": [
                {},
                {"type": "PowerLoraLoaderHeaderWidget"},
                {
                    "on": True,
                    "lora": "Flux2klein\\HighResolution9B.safetensors",
                    "strength": 0.6,
                    "strengthTwo": None,
                },
                {},
                "",
            ],
        },
        {
            "id": 205,
            "type": "PrimitiveInt",
            "title": "WIDTH",
            "widgets_values": [1280, "fixed"],
        },
        {
            "id": 204,
            "type": "PrimitiveInt",
            "title": "HEIGHT",
            "widgets_values": [1920, "fixed"],
        },
        {
            "id": 192,
            "type": "CLIPTextEncode",
            "inputs": [{"name": "clip", "type": "CLIP", "link": 273}],
            "widgets_values": ["A woman with tan skin sitting down, facing camera"],
        },
        {
            "id": 9,
            "type": "SaveImage",
            "inputs": [{"name": "images", "type": "IMAGE", "link": 347}],
            "widgets_values": ["BB"],
        },
        {"id": 154, "type": "Note", "widgets_values": ["ignore"]},
    ],
    "links": [
        [240, 181, 0, 187, 0, "NOISE"],
        [241, 190, 0, 187, 1, "GUIDER"],
        [242, 180, 0, 187, 2, "SAMPLER"],
        [243, 195, 0, 187, 3, "SIGMAS"],
        [244, 196, 0, 187, 4, "LATENT"],
        [245, 187, 0, 188, 0, "LATENT"],
        [249, 192, 0, 191, 0, "CONDITIONING"],
        [259, 197, 0, 190, 1, "CONDITIONING"],
        [261, 192, 0, 197, 0, "CONDITIONING"],
        [262, 191, 0, 190, 2, "CONDITIONING"],
        [270, 184, 0, 188, 1, "VAE"],
        [271, 182, 0, 200, 0, "MODEL"],
        [272, 183, 0, 200, 1, "CLIP"],
        [273, 200, 1, 192, 0, "CLIP"],
        [274, 200, 0, 190, 0, "MODEL"],
        [281, 205, 0, 195, 0, "INT"],
        [282, 205, 0, 196, 0, "INT"],
        [283, 204, 0, 195, 1, "INT"],
        [284, 204, 0, 196, 1, "INT"],
        [347, 188, 0, 9, 0, "IMAGE"],
    ],
}


class DistilledKleinImport(unittest.TestCase):
    def test_sampler_only_metadata_is_not_a_prompt(self) -> None:
        meta = ci.parse_civitai_metadata(DISTILLED_META)
        self.assertNotIn("prompt", meta)
        self.assertEqual(meta["sampler"], "euler")
        self.assertEqual(meta["seed"], 824168918863563)
        self.assertEqual(meta["model"], "flux-2-klein-9b-fp8.safetensors")
        self.assertNotIn("steps", meta)

    def test_extra_data_after_workflow_json(self) -> None:
        blob = json.dumps(WORKFLOW) + '{"id":"trailing","revision":0} junk'
        with self.assertRaises(json.JSONDecodeError) as ctx:
            json.loads(blob)
        self.assertIn("Extra data", str(ctx.exception))
        body = ci.import_to_request(workflow_text=blob)
        self.assertEqual(body["prompt"]["86"]["inputs"]["cfg"], 5)

    def test_sampler_prefix_plus_trailing_json_in_one_box(self) -> None:
        mixed = DISTILLED_META + "\n" + json.dumps(DISTILLED) + '{"extra":true}'
        meta_text, wf_text = ci.split_pastes(mixed, "")
        self.assertIn("Sampler:", meta_text)
        self.assertNotIn('"nodes"', meta_text)
        self.assertTrue(wf_text)
        body = ci.import_to_request(metadata_text=mixed)
        prompt = body["prompt"]
        self.assertEqual(prompt["190"]["inputs"]["cfg"], 1)
        self.assertIn("tan skin", prompt["192"]["inputs"]["text"])
        self.assertNotIn("Sampler:", prompt["192"]["inputs"]["text"])

    def test_distilled_klein_keeps_cfg1_steps4_and_reference_latent(self) -> None:
        extra = json.dumps(DISTILLED) + '{"id":"trailing"}'
        knobs = ci.knobs_from_sources(DISTILLED_META, extra)
        self.assertEqual(knobs["cfg"], 1)
        self.assertEqual(knobs["steps"], 4)
        self.assertEqual(knobs["width"], 1280)
        self.assertEqual(knobs["height"], 1920)
        self.assertEqual(knobs["seed"], 824168918863563)
        self.assertNotIn("Sampler:", str(knobs.get("prompt") or ""))
        body = ci.import_to_request(
            workflow_text=extra,
            metadata_text=DISTILLED_META,
            knobs=knobs,
        )
        prompt = body["prompt"]
        self.assertEqual(prompt["190"]["inputs"]["cfg"], 1)
        self.assertEqual(prompt["195"]["inputs"]["steps"], 4)
        def _prim(val):
            if isinstance(val, list) and val:
                node = prompt.get(str(val[0]))
                if isinstance(node, dict):
                    return node.get("inputs", {}).get("value")
            return val

        self.assertEqual(_prim(prompt["196"]["inputs"]["width"]), 1280)
        self.assertEqual(_prim(prompt["196"]["inputs"]["height"]), 1920)
        self.assertEqual(prompt["181"]["inputs"]["noise_seed"], 824168918863563)
        self.assertEqual(
            prompt["182"]["inputs"]["unet_name"],
            "flux-2-klein-9b-fp8.safetensors",
        )
        self.assertEqual(prompt["184"]["inputs"]["vae_name"], "flux2-vae.safetensors")
        self.assertIn("197", prompt)
        self.assertEqual(prompt["197"]["class_type"], "ReferenceLatent")
        self.assertEqual(prompt["191"]["class_type"], "ConditioningZeroOut")
        blob = "\n".join(ci.issues_from_pastes(DISTILLED_META, extra))
        self.assertIn("Warning:", blob)
        self.assertIn("ReferenceLatent", blob)
        self.assertNotIn("full_encoder_small_decoder", blob)
        self.assertIn("18 on site, 17 after import", blob)
        self.assertIn("dropped Note", blob)

    def test_fetch_sampler_only_copy_all_uses_comfy_prompt(self) -> None:
        comfy = {
            "prompt": {
                "192": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {
                        "text": "A woman with blonde hair and a sign",
                        "clip": ["183", 0],
                    },
                }
            },
            "workflow": {
                "nodes": [
                    {
                        "id": 192,
                        "type": "CLIPTextEncode",
                        "widgets_values": ["A woman with blonde hair and a sign"],
                    }
                ],
                "links": [],
            },
        }
        item = {
            "id": 135940058,
            "width": 1280,
            "height": 1920,
            "modelVersionIds": [],
            "meta": {
                "meta": {
                    "seed": 997353507675929,
                    "Model": "Flux\\flux-2-klein-9b-fp8",
                    "sampler": "Euler",
                    "comfy": json.dumps(comfy),
                }
            },
        }
        text = ci.generation_data_from_image(item)
        self.assertIn("Sampler: Euler", text)
        self.assertIn("997353507675929", text)
        self.assertIn("A woman with blonde hair", text)
        self.assertIn("https://civitai.com/images/135940058", text)
        with patch.object(ci.ls, "fetch_civitai_image", return_value=item):
            pastes = ci.fetch_civitai_image_pastes("135940058")
        self.assertTrue(pastes["workflow"])
        self.assertIn("CLIPTextEncode", pastes["workflow"])

    def test_stallion_paste_has_no_replica_issues(self) -> None:
        issues = ci.issues_from_pastes("", json.dumps(WORKFLOW))
        self.assertFalse(any(i.startswith("Warning:") for i in issues))
        self.assertTrue(
            any("dropped MarkdownNote" in i for i in issues) or issues == []
        )

    def test_workflow_to_prompt_keeps_distilled_names_before_compat(self) -> None:
        prompt = ci.workflow_to_prompt(DISTILLED)
        self.assertEqual(
            prompt["182"]["inputs"]["unet_name"], "flux-2-klein-9b-fp8.safetensors"
        )
        self.assertEqual(prompt["197"]["class_type"], "ReferenceLatent")
        lora = str(prompt["200"]["inputs"]["lora_name"])
        self.assertTrue(
            "HighResolution" in lora or "2760799" in lora or lora.endswith(".safetensors"),
            lora,
        )

    def test_ksampler_widgets_skip_seed_control(self) -> None:
        wf = {
            "nodes": [
                {
                    "id": 163,
                    "type": "KSampler",
                    "widgets_values": [
                        123456,
                        "randomize",
                        4,
                        1,
                        "euler",
                        "simple",
                        1,
                    ],
                    "inputs": [],
                }
            ],
            "links": [],
        }
        ins = ci.workflow_to_prompt(wf)["163"]["inputs"]
        self.assertEqual(ins["seed"], 123456)
        self.assertEqual(ins["steps"], 4)
        self.assertEqual(ins["cfg"], 1)
        self.assertEqual(ins["sampler_name"], "euler")
        self.assertEqual(ins["scheduler"], "simple")
        self.assertEqual(ins["denoise"], 1)

    def test_fp8mixed_unet_maps_to_replica_fp8(self) -> None:
        wf = {
            "nodes": [
                {
                    "id": 194,
                    "type": "UNETLoader",
                    "widgets_values": [
                        "Flux.2\\flux-2-klein-9b-fp8mixed.safetensors",
                        "default",
                    ],
                    "inputs": [],
                },
                {
                    "id": 94,
                    "type": "UNETLoader",
                    "widgets_values": [
                        "Flux.2\\flux-2-klein-base-9b-fp8.safetensors",
                        "default",
                    ],
                    "inputs": [],
                },
            ],
            "links": [],
        }
        body = ci.import_to_request(workflow_text=json.dumps(wf))
        self.assertEqual(
            body["prompt"]["194"]["inputs"]["unet_name"],
            "flux-2-klein-9b-fp8.safetensors",
        )
        self.assertEqual(
            body["prompt"]["94"]["inputs"]["unet_name"],
            "flux-2-klein-base-9b-fp8.safetensors",
        )

    def test_generate_copy_repairs_mixed_unet_and_packed_ksampler(self) -> None:
        prompt = {
            "194": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "flux-2-klein-9b-fp8mixed.safetensors"},
            },
            "163": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 1,
                    "steps": "randomize",
                    "cfg": 4,
                    "sampler_name": 1,
                    "scheduler": "euler",
                    "denoise": "simple",
                },
            },
            "9": {"class_type": "SaveImage", "inputs": {}},
        }
        posted = ci.prompt_for_salad_replica(prompt)
        self.assertEqual(
            posted["194"]["inputs"]["unet_name"],
            "flux-2-klein-9b-fp8.safetensors",
        )
        ins = posted["163"]["inputs"]
        self.assertEqual(ins["steps"], 4)
        self.assertEqual(ins["cfg"], 1)
        self.assertEqual(ins["sampler_name"], "euler")
        self.assertEqual(ins["scheduler"], "simple")
        self.assertEqual(ins["denoise"], 1)
        self.assertEqual(
            prompt["194"]["inputs"]["unet_name"],
            "flux-2-klein-9b-fp8mixed.safetensors",
        )
        self.assertEqual(prompt["163"]["inputs"]["steps"], "randomize")

    def test_salad_post_adds_saveimage_when_only_preview(self) -> None:
        prompt = {
            "101": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["171", 0], "vae": ["105", 0]},
            },
            "211": {
                "class_type": "PreviewImage",
                "inputs": {"images": ["101", 0]},
            },
            "105": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": "flux2-vae.safetensors"},
            },
        }
        posted = ci.prompt_for_salad_replica(prompt)
        self.assertNotIn("211", posted)
        savers = [
            n
            for n in posted.values()
            if isinstance(n, dict) and n.get("class_type") == "SaveImage"
        ]
        self.assertEqual(len(savers), 1)
        self.assertEqual(savers[0]["inputs"]["filename_prefix"], "klein")
        self.assertEqual(savers[0]["inputs"]["images"], ["101", 0])
        self.assertNotIn("SaveImage", [n.get("class_type") for n in prompt.values() if isinstance(n, dict)])


class ComfySubgraphUuid(unittest.TestCase):
    def test_flatten_inlines_uuid_subgraph_into_real_types(self) -> None:
        wf = {
            "nodes": [
                {
                    "id": 75,
                    "type": "aaaaaaaa-1111-2222-3333-444444444444",
                    "inputs": [
                        {"name": "image", "type": "IMAGE", "link": 1},
                    ],
                    "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [2]}],
                    "widgets_values": ["edit the photo", "flux-2-klein-9b-fp8.safetensors"],
                    "properties": {
                        "proxyWidgets": [["-1", "text"], ["-1", "unet_name"]],
                    },
                },
                {
                    "id": 9,
                    "type": "SaveImage",
                    "inputs": [{"name": "images", "type": "IMAGE", "link": 2}],
                    "widgets_values": ["klein"],
                },
                {
                    "id": 1,
                    "type": "LoadImage",
                    "inputs": [],
                    "widgets_values": ["cat.png"],
                },
            ],
            "links": [
                [1, 1, 0, 75, 0, "IMAGE"],
                [2, 75, 0, 9, 0, "IMAGE"],
            ],
            "definitions": {
                "subgraphs": [
                    {
                        "id": "aaaaaaaa-1111-2222-3333-444444444444",
                        "name": "Image Edit",
                        "inputs": [
                            {"name": "text", "type": "STRING", "linkIds": [10]},
                            {"name": "unet_name", "type": "COMBO", "linkIds": [11]},
                            {"name": "image", "type": "IMAGE", "linkIds": [12]},
                        ],
                        "outputs": [{"name": "IMAGE", "type": "IMAGE", "linkIds": [13]}],
                        "nodes": [
                            {
                                "id": 70,
                                "type": "UNETLoader",
                                "widgets_values": ["other.safetensors", "default"],
                                "inputs": [],
                            },
                            {
                                "id": 74,
                                "type": "CLIPTextEncode",
                                "widgets_values": ["inner"],
                                "inputs": [
                                    {"name": "clip", "type": "CLIP", "link": None},
                                    {"name": "text", "type": "STRING", "link": 10},
                                ],
                            },
                            {
                                "id": 65,
                                "type": "VAEDecode",
                                "inputs": [
                                    {"name": "samples", "type": "LATENT", "link": None},
                                    {"name": "pixels", "type": "IMAGE", "link": 12},
                                ],
                            },
                        ],
                        "links": [
                            {
                                "id": 10,
                                "origin_id": -10,
                                "origin_slot": 0,
                                "target_id": 74,
                                "target_slot": 1,
                                "type": "STRING",
                            },
                            {
                                "id": 11,
                                "origin_id": -10,
                                "origin_slot": 1,
                                "target_id": 70,
                                "target_slot": 0,
                                "type": "COMBO",
                            },
                            {
                                "id": 12,
                                "origin_id": -10,
                                "origin_slot": 2,
                                "target_id": 65,
                                "target_slot": 1,
                                "type": "IMAGE",
                            },
                            {
                                "id": 13,
                                "origin_id": 65,
                                "origin_slot": 0,
                                "target_id": -20,
                                "target_slot": 0,
                                "type": "IMAGE",
                            },
                        ],
                    }
                ]
            },
        }
        flat = ci.flatten_comfy_subgraphs(json.loads(json.dumps(wf)))
        inner_types = {str(n.get("type") or "") for n in (flat.get("nodes") or [])}
        self.assertIn("UNETLoader", inner_types)
        self.assertIn("CLIPTextEncode", inner_types)
        self.assertFalse(any(ci._is_uuid_type(t) for t in inner_types))
        body = ci.import_to_request(workflow_text=json.dumps(wf))
        prompt = body["prompt"]
        types = {
            n.get("class_type")
            for n in prompt.values()
            if isinstance(n, dict)
        }
        self.assertIn("VAEDecode", types)
        self.assertIn("SaveImage", types)
        self.assertIn("LoadImage", types)
        self.assertNotIn("75", prompt)
        self.assertFalse(any(ci._is_uuid_type(str(t)) for t in types))
        # UNET/CLIP are inlined then dropped: this fixture never wires them
        # into VAEDecode, so they are not on the SaveImage path.

    def test_links_by_id_indexes_dict_rows(self) -> None:
        got = ci._links_by_id(
            {
                "links": [
                    [7, 1, 0, 2, 0, "MODEL"],
                    {
                        "id": 8,
                        "origin_id": 3,
                        "origin_slot": 0,
                        "target_id": 4,
                        "target_slot": 1,
                        "type": "CLIP",
                    },
                ]
            }
        )
        self.assertEqual(got[7][1], 1)
        self.assertEqual(got[8][3], 4)
        self.assertEqual(got[8][4], 1)

    def test_drop_orphan_nodes_keeps_saveimage_path_only(self) -> None:
        prompt = {
            "70": {"class_type": "UNETLoader", "inputs": {"unet_name": "u.safetensors"}},
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "klein", "images": ["65", 0]},
            },
            "65": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["64", 0], "vae": ["72", 0]},
            },
            "64": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["73", 0]}},
            "73": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1}},
            "72": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
            "97": {"class_type": "MarkdownNote", "inputs": {}},
            "102": {"class_type": "Fast Groups Bypasser (rgthree)", "inputs": {}},
            "200": {"class_type": "UNETLoader", "inputs": {"unet_name": "unused.safetensors"}},
        }
        notes = ci.drop_orphan_nodes(prompt)
        self.assertIn("9", prompt)
        self.assertIn("65", prompt)
        self.assertIn("73", prompt)
        self.assertNotIn("97", prompt)
        self.assertNotIn("102", prompt)
        self.assertNotIn("200", prompt)
        self.assertNotIn("70", prompt)
        self.assertTrue(any("MarkdownNote #97" in n for n in notes))

    def test_muted_subgraph_is_not_inlined_as_orphans(self) -> None:
        wf = {
            "last_node_id": 10,
            "nodes": [
                {
                    "id": 1,
                    "type": "LoadImage",
                    "inputs": [],
                    "widgets_values": ["a.png"],
                    "mode": 0,
                },
                {
                    "id": 2,
                    "type": "aaaaaaaa-1111-2222-3333-444444444444",
                    "inputs": [{"name": "image", "type": "IMAGE", "link": 1}],
                    "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [2]}],
                    "mode": 0,
                },
                {
                    "id": 3,
                    "type": "aaaaaaaa-1111-2222-3333-444444444444",
                    "inputs": [{"name": "image", "type": "IMAGE", "link": 3}],
                    "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [4]}],
                    "mode": 4,
                },
                {
                    "id": 9,
                    "type": "SaveImage",
                    "inputs": [{"name": "images", "type": "IMAGE", "link": 2}],
                    "widgets_values": ["klein"],
                    "mode": 0,
                },
                {
                    "id": 94,
                    "type": "SaveImage",
                    "inputs": [{"name": "images", "type": "IMAGE", "link": 4}],
                    "widgets_values": ["klein"],
                    "mode": 4,
                },
            ],
            "links": [
                [1, 1, 0, 2, 0, "IMAGE"],
                [2, 2, 0, 9, 0, "IMAGE"],
                [3, 1, 0, 3, 0, "IMAGE"],
                [4, 3, 0, 94, 0, "IMAGE"],
            ],
            "definitions": {
                "subgraphs": [
                    {
                        "id": "aaaaaaaa-1111-2222-3333-444444444444",
                        "inputs": [{"name": "image", "type": "IMAGE"}],
                        "outputs": [{"name": "IMAGE", "type": "IMAGE"}],
                        "nodes": [
                            {
                                "id": 65,
                                "type": "VAEDecode",
                                "inputs": [
                                    {"name": "samples", "type": "LATENT", "link": None},
                                    {"name": "pixels", "type": "IMAGE", "link": 12},
                                ],
                            },
                        ],
                        "links": [
                            {
                                "id": 12,
                                "origin_id": -10,
                                "origin_slot": 0,
                                "target_id": 65,
                                "target_slot": 1,
                                "type": "IMAGE",
                            },
                            {
                                "id": 13,
                                "origin_id": 65,
                                "origin_slot": 0,
                                "target_id": -20,
                                "target_slot": 0,
                                "type": "IMAGE",
                            },
                        ],
                    }
                ]
            },
        }
        body = ci.import_to_request(workflow_text=json.dumps(wf))
        prompt = body["prompt"]
        decodes = [
            nid
            for nid, n in prompt.items()
            if isinstance(n, dict) and n.get("class_type") == "VAEDecode"
        ]
        self.assertEqual(len(decodes), 1)
        self.assertNotIn("94", prompt)
        self.assertIn("9", prompt)
        self.assertEqual(prompt["9"]["inputs"]["images"][0], decodes[0])

    def test_nested_uuid_inside_subgraph_stays_on_saveimage_path(self) -> None:
        inner = "bbbbbbbb-1111-2222-3333-444444444444"
        outer = "aaaaaaaa-1111-2222-3333-444444444444"
        wf = {
            "nodes": [
                {
                    "id": 1,
                    "type": "LoadImage",
                    "inputs": [],
                    "widgets_values": ["a.png"],
                },
                {
                    "id": 2,
                    "type": outer,
                    "inputs": [{"name": "image", "type": "IMAGE", "link": 1}],
                    "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [2]}],
                },
                {
                    "id": 9,
                    "type": "SaveImage",
                    "inputs": [{"name": "images", "type": "IMAGE", "link": 2}],
                    "widgets_values": ["klein"],
                },
            ],
            "links": [
                [1, 1, 0, 2, 0, "IMAGE"],
                [2, 2, 0, 9, 0, "IMAGE"],
            ],
            "definitions": {
                "subgraphs": [
                    {
                        "id": outer,
                        "inputs": [{"name": "image", "type": "IMAGE"}],
                        "outputs": [{"name": "IMAGE", "type": "IMAGE"}],
                        "nodes": [
                            {
                                "id": 65,
                                "type": "VAEDecode",
                                "inputs": [
                                    {"name": "samples", "type": "LATENT", "link": 20},
                                    {"name": "vae", "type": "VAE", "link": None},
                                ],
                            },
                            {
                                "id": 79,
                                "type": inner,
                                "inputs": [
                                    {"name": "image", "type": "IMAGE", "link": 12},
                                ],
                                "outputs": [
                                    {"name": "LATENT", "type": "LATENT", "links": [20]},
                                ],
                            },
                        ],
                        "links": [
                            {
                                "id": 12,
                                "origin_id": -10,
                                "origin_slot": 0,
                                "target_id": 79,
                                "target_slot": 0,
                                "type": "IMAGE",
                            },
                            {
                                "id": 20,
                                "origin_id": 79,
                                "origin_slot": 0,
                                "target_id": 65,
                                "target_slot": 0,
                                "type": "LATENT",
                            },
                            {
                                "id": 13,
                                "origin_id": 65,
                                "origin_slot": 0,
                                "target_id": -20,
                                "target_slot": 0,
                                "type": "IMAGE",
                            },
                        ],
                    },
                    {
                        "id": inner,
                        "inputs": [{"name": "image", "type": "IMAGE"}],
                        "outputs": [{"name": "LATENT", "type": "LATENT"}],
                        "nodes": [
                            {
                                "id": 78,
                                "type": "VAEEncode",
                                "inputs": [
                                    {"name": "pixels", "type": "IMAGE", "link": 1},
                                ],
                            },
                        ],
                        "links": [
                            {
                                "id": 1,
                                "origin_id": -10,
                                "origin_slot": 0,
                                "target_id": 78,
                                "target_slot": 0,
                                "type": "IMAGE",
                            },
                            {
                                "id": 2,
                                "origin_id": 78,
                                "origin_slot": 0,
                                "target_id": -20,
                                "target_slot": 0,
                                "type": "LATENT",
                            },
                        ],
                    },
                ]
            },
        }
        prompt = ci.import_to_request(workflow_text=json.dumps(wf))["prompt"]
        types = {
            n.get("class_type")
            for n in prompt.values()
            if isinstance(n, dict)
        }
        self.assertIn("VAEEncode", types)
        self.assertIn("VAEDecode", types)
        self.assertIn("SaveImage", types)
        self.assertFalse(any(ci._is_uuid_type(str(t)) for t in types))

    def test_generate_omits_leftover_uuid_class_types(self) -> None:
        prompt = {
            "75": {
                "class_type": "7b34ab90-36f9-45ba-a665-71d418f0df18",
                "inputs": {"image": ["76", 0]},
            },
            "76": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "klein", "images": ["75", 0]},
            },
        }
        posted = ci.prompt_for_salad_replica(prompt)
        self.assertNotIn("75", posted)
        self.assertEqual(posted["9"]["inputs"]["images"], ["76", 0])

    def test_generate_drops_local_img2img_size_chain(self) -> None:
        prompt = {
            "76": {
                "class_type": "LoadImage",
                "inputs": {"image": "TiledMultiDiff__00979.png"},
            },
            "123": {
                "class_type": "ImageScaleToTotalPixels",
                "inputs": {"image": ["76", 0]},
            },
            "114": {
                "class_type": "GetImageSize",
                "inputs": {"image": ["123", 0]},
            },
            "113": {
                "class_type": "EmptyFlux2LatentImage",
                "inputs": {
                    "width": ["114", 0],
                    "height": ["114", 1],
                    "batch_size": 1,
                },
            },
            "110": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["109", 0], "vae": ["112", 0]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "klein", "images": ["110", 0]},
            },
        }
        posted = ci.prompt_for_salad_replica(prompt)
        self.assertNotIn("76", posted)
        self.assertNotIn("123", posted)
        self.assertNotIn("114", posted)
        self.assertEqual(posted["113"]["inputs"]["width"], 1024)
        self.assertEqual(posted["113"]["inputs"]["height"], 1024)
        self.assertIn("9", posted)

    def test_text_multiline_widget_becomes_inputs_text(self) -> None:
        node = {
            "id": 106,
            "type": "Text Multiline",
            "widgets_values": [
                "Change the style of the image to be a realistic photography."
            ],
        }
        inputs = ci._widget_inputs(node)
        self.assertEqual(
            inputs.get("text"),
            "Change the style of the image to be a realistic photography.",
        )

    def test_lora_widget_keeps_a_civitai_url_but_basenames_a_local_path(self) -> None:
        """salad_filename must not reduce a download URL to its trailing id.

        Studio writes LoraLoader.lora_name as a Civitai download URL. Passing that
        through salad_filename leaves "2625692", which is not a URL: the LoRA then
        never resolves and Generate has nothing to attach a token to.
        """
        url = "https://civitai.com/api/download/models/2625692?fileId=2513322"
        node = {"id": 3, "type": "LoraLoader", "widgets_values": [url, -1.5, -1.5]}
        self.assertEqual(ci._widget_inputs(node).get("lora_name"), url)

        tokenised = f"https://civitai.com/api/download/models/2625692?token={'a' * 32}"
        node = {"id": 3, "type": "LoraLoader", "widgets_values": [tokenised, -1.5, -1.5]}
        self.assertEqual(ci._widget_inputs(node).get("lora_name"), tokenised)

        node = {
            "id": 3,
            "type": "LoraLoader",
            "widgets_values": [r"C:\ComfyUI\models\loras\klein_slider_detail.safetensors", -1.5, -1.5],
        }
        self.assertEqual(
            ci._widget_inputs(node).get("lora_name"), "klein_slider_detail.safetensors"
        )

    def test_generate_drops_empty_lora_loader_model_only(self) -> None:
        prompt = {
            "132": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["129", 0]},
            },
            "129": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "flux-2-klein-9b-fp8.safetensors"},
            },
            "140": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["132", 0],
                    "clip": ["130", 0],
                    "lora_name": "https://civitai.com/api/download/models/2723121",
                    "strength_model": 1,
                    "strength_clip": 1,
                },
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "klein", "images": ["8", 0]},
            },
        }
        posted = ci.prompt_for_salad_replica(prompt)
        self.assertNotIn("132", posted)
        self.assertIn("140", posted)
        self.assertEqual(posted["140"]["inputs"]["model"], ["129", 0])

    def test_convert_keeps_model_only_lora_url_and_node(self) -> None:
        """A LoraLoaderModelOnly LoRA must reach the POST copy.

        WIDGET_ORDER had no entry for the class, so _widget_inputs returned {}
        and the node left Convert with no lora_name, the ModelOnly pass in
        prompt_for_salad_replica then dropped it, silently losing the LoRA.
        The class has two widgets (no strength_clip), so a LoraLoader tuple
        would misalign strength_model.
        """
        url = "https://civitai.com/api/download/models/2760799"
        wf = {
            "nodes": [
                {
                    "id": 194,
                    "type": "UNETLoader",
                    "widgets_values": ["flux-2-klein-9b-fp8.safetensors", "default"],
                    "inputs": [],
                    "outputs": [{"name": "MODEL", "links": [1]}],
                },
                {
                    "id": 132,
                    "type": "LoraLoaderModelOnly",
                    "widgets_values": [url, 1.0],
                    "inputs": [{"name": "model", "type": "MODEL", "link": 1}],
                    "outputs": [{"name": "MODEL", "links": [2]}],
                },
                {
                    "id": 163,
                    "type": "KSampler",
                    "widgets_values": [7, "randomize", 4, 1, "euler", "simple", 1],
                    "inputs": [
                        {"name": "model", "type": "MODEL", "link": 2},
                        {"name": "positive", "type": "CONDITIONING", "link": 3},
                        {"name": "negative", "type": "CONDITIONING", "link": 4},
                        {"name": "latent_image", "type": "LATENT", "link": 5},
                    ],
                    "outputs": [{"name": "LATENT", "links": [6]}],
                },
                {
                    "id": 6,
                    "type": "CLIPTextEncode",
                    "widgets_values": ["a woman on a stool"],
                    "inputs": [{"name": "clip", "type": "CLIP", "link": 7}],
                },
                {
                    "id": 7,
                    "type": "CLIPTextEncode",
                    "widgets_values": ["blurry"],
                    "inputs": [{"name": "clip", "type": "CLIP", "link": 8}],
                },
                {
                    "id": 195,
                    "type": "CLIPLoader",
                    "widgets_values": ["qwen_3_8b_fp8mixed.safetensors", "flux2", "default"],
                    "inputs": [],
                    "outputs": [{"name": "CLIP", "links": [7, 8]}],
                },
                {
                    "id": 213,
                    "type": "EmptyFlux2LatentImage",
                    "widgets_values": [1024, 1024, 1],
                    "inputs": [],
                    "outputs": [{"name": "LATENT", "links": [5]}],
                },
                {
                    "id": 196,
                    "type": "VAELoader",
                    "widgets_values": ["flux2-vae.safetensors"],
                    "inputs": [],
                    "outputs": [{"name": "VAE", "links": [9]}],
                },
                {
                    "id": 164,
                    "type": "VAEDecode",
                    "inputs": [
                        {"name": "samples", "type": "LATENT", "link": 6},
                        {"name": "vae", "type": "VAE", "link": 9},
                    ],
                    "outputs": [{"name": "IMAGE", "links": [10]}],
                },
                {
                    "id": 203,
                    "type": "SaveImage",
                    "widgets_values": ["klein"],
                    "inputs": [{"name": "images", "type": "IMAGE", "link": 10}],
                    "outputs": [],
                },
            ],
            "links": [
                [1, 194, 0, 132, 0, "MODEL"],
                [2, 132, 0, 163, 0, "MODEL"],
                [3, 6, 0, 163, 1, "CONDITIONING"],
                [4, 7, 0, 163, 2, "CONDITIONING"],
                [5, 213, 0, 163, 3, "LATENT"],
                [6, 163, 0, 164, 0, "LATENT"],
                [7, 195, 0, 6, 0, "CLIP"],
                [8, 195, 0, 7, 0, "CLIP"],
                [9, 196, 0, 164, 1, "VAE"],
                [10, 164, 0, 203, 0, "IMAGE"],
            ],
        }
        prompt = ci.import_to_request(workflow_text=json.dumps(wf))["prompt"]
        self.assertEqual(prompt["132"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(prompt["132"]["inputs"]["lora_name"], url)
        self.assertEqual(prompt["132"]["inputs"]["strength_model"], 1.0)
        self.assertEqual(prompt["163"]["inputs"]["model"], ["132", 0])

        posted = ci.prompt_for_salad_replica(prompt)
        self.assertIn("132", posted)
        self.assertEqual(posted["132"]["inputs"]["lora_name"], url)
        self.assertEqual(posted["163"]["inputs"]["model"], ["132", 0])
        self.assertEqual(rj.civitai_lora_urls(posted), [url])

    def test_generate_omits_text_multiline(self) -> None:
        prompt = {
            "106": {
                "class_type": "Text Multiline",
                "inputs": {"text": "hello"},
            },
            "122": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": ["106", 0], "clip": ["120", 0]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "klein", "images": ["8", 0]},
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["7", 0], "vae": ["6", 0]},
            },
        }
        posted = ci.prompt_for_salad_replica(prompt)
        self.assertNotIn("106", posted)
        self.assertIn("9", posted)
        self.assertEqual(posted["122"]["inputs"]["text"], "hello")

    def test_generate_omits_uuid_self_loops_and_easy_clean_gpu(self) -> None:
        prompt = {
            "75": {
                "class_type": "7b34ab90-36f9-45ba-a665-71d418f0df18",
                "inputs": {
                    "image": ["76", 0],
                    "model": ["75", 1],
                    "clip": ["75", 2],
                },
            },
            "76": {
                "class_type": "LoadImage",
                "inputs": {"image": "https://example.com/a.png"},
            },
            "104": {
                "class_type": "easy cleanGpuUsed",
                "inputs": {"anything": ["75", 0]},
            },
            "102": {"class_type": "Fast Groups Bypasser (rgthree)", "inputs": {}},
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "klein", "images": ["104", 0]},
            },
        }
        posted = ci.prompt_for_salad_replica(prompt)
        self.assertNotIn("75", posted)
        self.assertNotIn("104", posted)
        self.assertNotIn("102", posted)
        self.assertEqual(posted["9"]["inputs"]["images"], ["76", 0])


class ReplicaMissingCustom(unittest.TestCase):
    def test_nvfp4_unet_maps_to_replica_fp8(self) -> None:
        self.assertEqual(
            ci.replica_unet_name("flux-2-klein-9b-nvfp4.safetensors"),
            "flux-2-klein-9b-fp8.safetensors",
        )

    def test_snofs_distilled_fp8_is_not_rewritten_to_official_klein(self) -> None:
        name = "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors"
        self.assertEqual(ci.replica_unet_name(name), name)

    def test_civitai_klein_fp8_alias_maps_to_replica(self) -> None:
        self.assertEqual(
            ci.replica_unet_name("flux2Klein9bFp8_fp8.safetensors"),
            "flux-2-klein-9b-fp8.safetensors",
        )

    def test_post_replaces_resolution_orientation_and_drops_color_noise(self) -> None:
        prompt = {
            "100": {
                "class_type": "ResolutionOrientationNodeComfy",
                "inputs": {
                    "resolution": "1920x1080",
                    "percent": 100,
                    "orientation": "off",
                },
            },
            "89": {
                "class_type": "EmptyFlux2LatentImage",
                "inputs": {
                    "width": ["100", 0],
                    "height": ["100", 1],
                    "batch_size": 1,
                },
            },
            "109": {
                "class_type": "ColorNoiseComfy",
                "inputs": {"image": ["88", 0]},
            },
            "88": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["87", 0], "vae": ["96", 0]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "klein", "images": ["109", 0]},
            },
            "94": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "flux-2-klein-9b-nvfp4.safetensors"},
            },
        }
        posted = ci.prompt_for_salad_replica(prompt)
        self.assertNotIn("100", posted)
        self.assertNotIn("109", posted)
        self.assertEqual(
            posted["94"]["inputs"]["unet_name"],
            "flux-2-klein-9b-fp8.safetensors",
        )
        wref = posted["89"]["inputs"]["width"]
        href = posted["89"]["inputs"]["height"]
        self.assertIsInstance(wref, list)
        self.assertEqual(posted[str(wref[0])]["inputs"]["value"], 1920)
        self.assertEqual(posted[str(href[0])]["inputs"]["value"], 1080)
        self.assertEqual(posted["9"]["inputs"]["images"], ["88", 0])


# Civitai image 134347427: Resources list MJ Style Distilled 206, but the
# saved 14-node Comfy graph is an img2img edit with no LoraLoader.
MJ_STYLE_META = (
    "https://civitai.com/images/134347427\n"
    "make her skirt bigger\n"
    "<lora:MJ Style Distilled 206:1>\n"
    "Steps: 4, CFG scale: 1, Sampler: Euler, Seed: 238202688585053, "
    "Model: flux-2-klein-9b-fp8mixed, width: 1280, height: 720, Tools: ComfyUI"
)

MJ_STYLE_WF = {
    "nodes": [
        {
            "id": 195,
            "type": "CLIPLoader",
            "widgets_values": ["qwen_3_8b_fp8mixed.safetensors", "flux2", "default"],
            "inputs": [],
        },
        {
            "id": 196,
            "type": "VAELoader",
            "widgets_values": ["flux2-vae.safetensors"],
            "inputs": [],
        },
        {
            "id": 190,
            "type": "ConditioningZeroOut",
            "inputs": [{"name": "conditioning", "type": "CONDITIONING", "link": 219}],
            "widgets_values": [],
        },
        {
            "id": 205,
            "type": "ReferenceLatent",
            "inputs": [
                {"name": "conditioning", "type": "CONDITIONING", "link": 252},
                {"name": "latent", "type": "LATENT", "link": 247},
            ],
            "widgets_values": [],
        },
        {
            "id": 204,
            "type": "ReferenceLatent",
            "inputs": [
                {"name": "conditioning", "type": "CONDITIONING", "link": 250},
                {"name": "latent", "type": "LATENT", "link": 248},
            ],
            "widgets_values": [],
        },
        {
            "id": 194,
            "type": "UNETLoader",
            "widgets_values": ["flux-2-klein-9b-fp8mixed.safetensors", "default"],
            "inputs": [],
        },
        {
            "id": 202,
            "type": "Image Comparer (rgthree)",
            "inputs": [
                {"name": "image_a", "type": "IMAGE", "link": 269},
                {"name": "image_b", "type": "IMAGE", "link": 260},
            ],
            "widgets_values": [],
        },
        {
            "id": 203,
            "type": "SaveImage",
            "widgets_values": ["img"],
            "inputs": [{"name": "images", "type": "IMAGE", "link": 270}],
        },
        {
            "id": 164,
            "type": "VAEDecode",
            "inputs": [
                {"name": "samples", "type": "LATENT", "link": 187},
                {"name": "vae", "type": "VAE", "link": 236},
            ],
            "widgets_values": [],
        },
        {
            "id": 206,
            "type": "VAEEncode",
            "inputs": [
                {"name": "pixels", "type": "IMAGE", "link": 265},
                {"name": "vae", "type": "VAE", "link": 249},
            ],
            "widgets_values": [],
        },
        {
            "id": 163,
            "type": "KSampler",
            "widgets_values": [238202688585053, "randomize", 4, 1, "euler", "simple", 1],
            "inputs": [
                {"name": "model", "type": "MODEL", "link": 256},
                {"name": "positive", "type": "CONDITIONING", "link": 251},
                {"name": "negative", "type": "CONDITIONING", "link": 253},
                {"name": "latent_image", "type": "LATENT", "link": 271},
            ],
        },
        {
            "id": 213,
            "type": "EmptyLatentImage",
            "widgets_values": [1280, 720, 1],
            "inputs": [],
        },
        {
            "id": 198,
            "type": "LoadImage",
            "widgets_values": ["img_00069_.png", "image"],
            "inputs": [],
        },
        {
            "id": 6,
            "type": "CLIPTextEncode",
            "widgets_values": ["make her skirt bigger"],
            "inputs": [{"name": "clip", "type": "CLIP", "link": 235}],
        },
    ],
    "links": [
        [187, 163, 0, 164, 0, "LATENT"],
        [219, 6, 0, 190, 0, "CONDITIONING"],
        [235, 195, 0, 6, 0, "CLIP"],
        [236, 196, 0, 164, 1, "VAE"],
        [247, 206, 0, 205, 1, "LATENT"],
        [248, 206, 0, 204, 1, "LATENT"],
        [249, 196, 0, 206, 1, "VAE"],
        [250, 6, 0, 204, 0, "CONDITIONING"],
        [251, 204, 0, 163, 1, "CONDITIONING"],
        [252, 190, 0, 205, 0, "CONDITIONING"],
        [253, 205, 0, 163, 2, "CONDITIONING"],
        [256, 194, 0, 163, 0, "MODEL"],
        [260, 198, 0, 202, 1, "IMAGE"],
        [265, 198, 0, 206, 0, "IMAGE"],
        [269, 164, 0, 202, 0, "IMAGE"],
        [270, 164, 0, 203, 0, "IMAGE"],
        [271, 213, 0, 163, 3, "LATENT"],
    ],
}

_MJ_SPEC = {
    "lora_name": "https://civitai.com/api/download/models/2912075",
    "filename": "MJ Style Distilled 206.safetensors",
    "tag": "MJ Style Distilled 206",
    "strength_model": 1.0,
    "strength_clip": 1.0,
    "verified": True,
    "version_name": "v1.0",
}


class Image134347427(unittest.TestCase):
    def test_parse_lists_mj_style_lora_tag(self) -> None:
        meta = ci.parse_civitai_metadata(MJ_STYLE_META)
        self.assertEqual(meta["prompt"], "make her skirt bigger")
        self.assertEqual(
            meta["lora_tags"],
            [{"name": "MJ Style Distilled 206", "strength": 1.0}],
        )

    def test_convert_injects_mj_style_lora_and_keeps_loadimage_name(self) -> None:
        with patch.object(ci.ls, "fetch_civitai_image", return_value=None), patch.object(
            ci, "resolve_prompt_loras", return_value=([_MJ_SPEC], [])
        ) as rp:
            body = ci.import_to_request(
                workflow_text=json.dumps(MJ_STYLE_WF),
                metadata_text=MJ_STYLE_META,
            )
        rp.assert_called()
        prompt = body["prompt"]
        loaders = [
            (nid, n)
            for nid, n in prompt.items()
            if isinstance(n, dict) and n.get("class_type") == "LoraLoader"
        ]
        self.assertEqual(len(loaders), 1)
        nid, node = loaders[0]
        self.assertIn("2912075", node["inputs"]["lora_name"])
        self.assertEqual(prompt["163"]["inputs"]["model"], [nid, 0])
        clip = prompt["6"]["inputs"]["clip"]
        self.assertTrue(isinstance(clip, list) and str(clip[0]) in prompt)
        self.assertEqual(prompt["6"]["inputs"]["text"], "make her skirt bigger")
        self.assertEqual(prompt["198"]["inputs"]["image"], "img_00069_.png")
        self.assertEqual(
            prompt["194"]["inputs"]["unet_name"],
            "flux-2-klein-9b-fp8.safetensors",
        )
        self.assertEqual(prompt["163"]["inputs"]["steps"], 4)
        self.assertEqual(prompt["163"]["inputs"]["cfg"], 1)
        self.assertEqual(prompt["163"]["inputs"]["sampler_name"], "euler")
        posted = ci.prompt_for_salad_replica(prompt)
        self.assertNotIn("198", posted)
        self.assertNotIn("206", posted)
        self.assertNotIn("204", posted)
        self.assertNotIn("205", posted)
        self.assertNotIn("202", posted)
        self.assertIn(nid, posted)
        self.assertIn("163", posted)
        self.assertEqual(posted["163"]["inputs"]["model"], [nid, 0])

    def test_graph_with_lora_loader_is_not_given_a_second_resource_lora(self) -> None:
        with patch.object(ci.ls, "fetch_civitai_image", return_value=None), patch.object(
            ci.ls, "civitai_search_lora", return_value={
                "download": "https://civitai.com/api/download/models/2795018",
                "filename": "AgedArt01a_CE_FLUX2_Klein9b_AIT5k.safetensors",
                "version_id": 2795018,
                "verified": True,
            }
        ):
            body = ci.import_to_request(
                workflow_text=json.dumps(WORKFLOW),
                metadata_text=MJ_STYLE_META,
            )
        loaders = [
            n
            for n in body["prompt"].values()
            if isinstance(n, dict) and n.get("class_type") == "LoraLoader"
        ]
        self.assertEqual(len(loaders), 1)
        self.assertNotIn("2912075", loaders[0]["inputs"]["lora_name"])


ARTIFICEAL_PROMPT = (
    "Artificeal style artwork. Graphite sketch layer and abstract color layer. "
    "The artwork presents a rear-view, slightly elevated perspective of a woman "
    "seated on a wooden stool, facing a canvas with her bare feet resting on "
    "the lower rungs of the stool."
)

ARTIFICEAL_V1 = {
    "id": 135440425,
    "width": 1344,
    "height": 1792,
    "baseModel": "Flux.2 Klein 9B",
    "modelVersionIds": [],
    "meta": {
        "id": 135440425,
        "meta": {
            "steps": 5,
            "prompt": ARTIFICEAL_PROMPT,
            "sampler": "DPM++ SDE",
            "cfgScale": 1,
        },
    },
}

ARTIFICEAL_TRPC = [
    {
        "imageId": 135440425,
        "modelVersionId": 2658598,
        "strength": None,
        "modelId": 2363950,
        "modelName": "FLUX.2-klein-9b-fp8",
        "modelType": "Checkpoint",
        "versionName": "fp8",
    },
    {
        "imageId": 135440425,
        "modelVersionId": 3088444,
        "strength": None,
        "modelId": 2745770,
        "modelName": "Artificeal",
        "modelType": "LORA",
        "versionName": "v1.0",
        "baseModel": "Flux.2 Klein 9B",
    },
]


class ArtificealFetch(unittest.TestCase):
    """Civitai image 135440425: Draw Things, empty modelVersionIds, Artificeal LoRA."""

    def test_v1_api_without_resources_is_graphite_only(self) -> None:
        text = ci.generation_data_from_image(ARTIFICEAL_V1)
        self.assertIn("Graphite sketch layer", text)
        self.assertNotIn("<lora:", text)
        self.assertIn("width: 1344", text)
        self.assertIn("height: 1792", text)

    def test_merge_resources_injects_artificeal_and_distilled_unet(self) -> None:
        item = json.loads(json.dumps(ARTIFICEAL_V1))
        ci.ls.merge_image_resources(item, ARTIFICEAL_TRPC)
        self.assertEqual(item["modelVersionIds"], [2658598, 3088444])
        text = ci.generation_data_from_image(item)
        self.assertIn("<lora:Artificeal:1>", text)
        self.assertIn("Model: FLUX.2-klein-9b-fp8", text)
        self.assertIn("width: 1344", text)
        self.assertIn("height: 1792", text)
        self.assertIn("https://civitai.com/images/135440425", text)
        self.assertIn("Sampler: DPM++ SDE", text)
        self.assertIn("CFG scale: 1", text)
        self.assertIn("Steps: 5", text)
        meta = ci.parse_civitai_metadata(text)
        self.assertEqual(meta["sampler"], "dpmpp_sde")
        self.assertEqual(meta["cfg"], 1)
        self.assertEqual(meta["steps"], 5)
        self.assertEqual(meta["width"], 1344)
        self.assertEqual(meta["height"], 1792)
        self.assertIn("klein-9b-fp8", str(meta.get("model") or "").lower())
        self.assertEqual(meta["lora_tags"][0]["name"], "Artificeal")
        self.assertNotIn("civitai.com", meta["prompt"])
        self.assertIn("overalls", meta["prompt"])
        self.assertIn("ARTIFICEAL lettering", meta["prompt"])
        self.assertNotIn("The artwork presents a rear-view", meta["prompt"])

    def test_resource_tags_without_hashes(self) -> None:
        item = json.loads(json.dumps(ARTIFICEAL_V1))
        ci.ls.merge_image_resources(item, ARTIFICEAL_TRPC)
        hints = ci.ls.lora_hints_from_generation(ci.ls.unwrap_image_generation(item))
        self.assertEqual(hints["Artificeal"]["version_id"], 3088444)
        tags = ci.resource_order_tags(item, hints)
        assert tags is not None
        self.assertEqual([t["name"] for t in tags], ["Artificeal"])

    def test_fetch_pastes_include_lora_when_trpc_fills_resources(self) -> None:
        item = json.loads(json.dumps(ARTIFICEAL_V1))
        ci.ls.merge_image_resources(item, ARTIFICEAL_TRPC)
        with patch.object(ci.ls, "fetch_civitai_image", return_value=item):
            pastes = ci.fetch_civitai_image_pastes("135440425")
        self.assertIn("<lora:Artificeal:1>", pastes["metadata"])
        self.assertEqual(pastes["workflow"], "")

    def test_generation_data_records_draw_things_tool(self) -> None:
        item = json.loads(json.dumps(ARTIFICEAL_V1))
        ci.ls.merge_image_resources(item, ARTIFICEAL_TRPC)
        ci.ls.merge_generation_payload(
            item, {"tools": [{"name": "Draw Things"}], "onSite": False}
        )
        text = ci.generation_data_from_image(item)
        self.assertIn("Tools: Draw Things", text)
        with patch.object(ci.ls, "fetch_civitai_image", return_value=item):
            pastes = ci.fetch_civitai_image_pastes("135440425")
        self.assertEqual(pastes["tool"], "Draw Things")

    def test_draw_things_model_and_size_without_prompt_converts(self) -> None:
        text = (
            "https://civitai.com/images/125352789\n"
            "Model: FLUX.2-klein-9b-fp8, width: 3584, height: 2688, Tools: Draw Things"
        )
        meta = ci.parse_civitai_metadata(text)
        self.assertNotIn("prompt", meta)
        self.assertEqual(meta.get("tools"), "Draw Things")
        self.assertEqual(ci.detect_import_tool(metadata_text=text), ci.TOOL_DRAW_THINGS)
        body = ci.import_to_request(metadata_text=text)
        prompt = body["prompt"]
        self.assertEqual(
            prompt["70"]["inputs"]["unet_name"],
            "flux-2-klein-9b-fp8.safetensors",
        )
        self.assertEqual(prompt["66"]["inputs"]["width"], 3584)
        self.assertEqual(prompt["66"]["inputs"]["height"], 2688)
        self.assertEqual(prompt["61"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(prompt["62"]["inputs"]["steps"], 4)
        self.assertEqual(prompt["63"]["inputs"]["cfg"], 1)
        self.assertEqual(prompt["74"]["inputs"]["text"], "")

    def test_detect_import_tool_draw_things_vs_comfy(self) -> None:
        self.assertEqual(
            ci.detect_import_tool(metadata_text="x\nSteps: 5, Tools: Draw Things"),
            ci.TOOL_DRAW_THINGS,
        )
        self.assertEqual(
            ci.detect_import_tool(
                workflow_text='{"1": {"class_type": "UNETLoader", "inputs": {}}}'
            ),
            ci.TOOL_COMFY,
        )
        self.assertEqual(
            ci.detect_import_tool(metadata_text="a cat\nSteps: 20, Sampler: Euler"),
            ci.TOOL_METADATA,
        )
        self.assertEqual(
            ci.detect_import_tool(
                metadata_text="x\nSteps: 5, Tools: Draw Things",
                workflow_text='{"1": {"class_type": "UNETLoader", "inputs": {}}}',
            ),
            ci.TOOL_COMFY,
        )

    def test_empty_comfy_nodes_uses_metadata_path(self) -> None:
        self.assertFalse(
            ci.has_comfy_nodes(workflow_text='{"nodes": [], "links": []}')
        )
        self.assertEqual(
            ci.detect_import_tool(
                metadata_text=(
                    "a lighthouse cat\nSteps: 20, CFG scale: 1, "
                    "Sampler: Euler, Tools: ComfyUI"
                ),
                workflow_text='{"nodes": [], "links": []}',
            ),
            ci.TOOL_METADATA,
        )
        blob = (
            '{"prompt": {"10": {"class_type": "UNETLoader", '
            '"inputs": {"unet_name": "flux-2-klein-9b-fp8.safetensors"}}}, '
            '"workflow": undefined}'
        )
        self.assertTrue(ci.has_comfy_nodes(workflow_text=blob))
        obj = ci._parse_json_blob(blob)
        self.assertEqual(ci.comfy_node_count(obj), 1)
        empty = ci.import_to_request(
            workflow_text='{"nodes": []}',
            metadata_text=(
                "a lighthouse cat\nNegative prompt: blurry\n"
                "Steps: 20, CFG scale: 1, Sampler: Euler, Seed: 1, "
                "Model: flux-2-klein-9b-fp8, width: 1024, height: 1408, "
                "Tools: ComfyUI"
            ),
        )
        self.assertIn("70", empty["prompt"])
        self.assertEqual(
            empty["prompt"]["70"]["class_type"], "UNETLoader"
        )

    def test_comfy_census_counts_site_vs_import(self) -> None:
        wf = {
            "nodes": [
                {"id": 6, "type": "CLIPTextEncode", "widgets_values": ["hi"], "inputs": [], "outputs": [{"name": "CONDITIONING", "links": [1]}]},
                {"id": 204, "type": "ReferenceLatent", "widgets_values": [], "inputs": [{"name": "conditioning", "type": "CONDITIONING", "link": 1}], "outputs": [{"name": "CONDITIONING", "links": []}]},
                {"id": 79, "type": "MarkdownNote", "widgets_values": ["x"], "inputs": [], "outputs": []},
            ],
            "links": [[1, 6, 0, 204, 0, "CONDITIONING"]],
        }
        text = json.dumps(wf)
        body = ci.import_to_request(workflow_text=text)
        note = ci.comfy_convert_census_note(text, body)
        self.assertIn("3 on site", note)
        self.assertIn("3 after import", note)
        self.assertNotIn("dropped", note)
        self.assertEqual(body["prompt"]["204"]["class_type"], "ReferenceLatent")
        self.assertEqual(body["prompt"]["79"]["class_type"], "MarkdownNote")
        posted = ci.prompt_for_salad_replica(body["prompt"])
        self.assertNotIn("204", posted)
        self.assertNotIn("79", posted)
        self.assertIn("6", posted)

    def test_comfy_fetch_keeps_base_unet_not_distilled_knobs(self) -> None:
        wf = {
            "nodes": [
                {
                    "id": 94,
                    "type": "UNETLoader",
                    "widgets_values": [
                        "Flux.2\\flux-2-klein-base-9b-fp8.safetensors",
                        "default",
                    ],
                    "inputs": [],
                    "outputs": [{"name": "MODEL", "links": [1]}],
                },
                {
                    "id": 91,
                    "type": "PrimitiveInt",
                    "title": "Width",
                    "widgets_values": [768, "fixed"],
                    "inputs": [],
                    "outputs": [{"name": "INT", "links": [2]}],
                },
                {
                    "id": 89,
                    "type": "EmptyFlux2LatentImage",
                    "widgets_values": [1024, 1024, 1],
                    "inputs": [
                        {"name": "width", "type": "INT", "link": 2},
                    ],
                    "outputs": [{"name": "LATENT", "links": []}],
                },
                {
                    "id": 79,
                    "type": "MarkdownNote",
                    "widgets_values": ["ignore"],
                    "inputs": [],
                    "outputs": [],
                },
            ],
            "links": [
                [1, 94, 0, 86, 0, "MODEL"],
                [2, 91, 0, 89, 0, "INT"],
            ],
        }
        body = ci.import_to_request(
            workflow_text=json.dumps(wf),
            knobs={"unet": "flux-2-klein-9b-fp8.safetensors", "width": 1024},
        )
        prompt = body["prompt"]
        self.assertEqual(
            prompt["94"]["inputs"]["unet_name"],
            "flux-2-klein-base-9b-fp8.safetensors",
        )
        self.assertIn("91", prompt)
        self.assertEqual(prompt["91"]["class_type"], "PrimitiveInt")
        self.assertEqual(prompt["91"]["inputs"]["value"], 768)
        self.assertEqual(prompt["89"]["inputs"]["width"], ["91", 0])
        self.assertIn("79", prompt)
        self.assertEqual(prompt["79"]["class_type"], "MarkdownNote")

    def test_unresolved_lora_is_kept_convert_still_succeeds(self) -> None:
        prompt = {
            "80": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["70", 0],
                    "clip": ["71", 0],
                    "lora_name": "DefinitelyMissingLoRA_xyz.safetensors",
                    "strength_model": 1,
                    "strength_clip": 1,
                },
            },
            "63": {
                "class_type": "CFGGuider",
                "inputs": {"model": ["80", 0], "positive": ["74", 0]},
            },
        }
        with patch.object(ci.ls, "civitai_search_lora", return_value=None), patch.object(
            ci.ls, "find_by_loader_name", return_value=None
        ):
            missing = ci.resolve_local_lora_nodes(prompt)
        self.assertTrue(missing)
        self.assertIn("80", prompt)
        self.assertEqual(prompt["63"]["inputs"]["model"], ["80", 0])

    def test_comfy_path_does_not_remap_sde(self) -> None:
        wf = {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {
                    "unet_name": "flux-2-klein-9b-fp8.safetensors",
                    "weight_dtype": "default",
                },
            },
            "2": {
                "class_type": "KSamplerSelect",
                "inputs": {"sampler_name": "dpmpp_sde"},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "hi", "clip": ["1", 0]},
            },
        }
        body = ci.import_to_request(workflow_text=json.dumps({"prompt": wf}))
        self.assertEqual(body["prompt"]["2"]["inputs"]["sampler_name"], "dpmpp_sde")

    def test_convert_loads_artificeal_on_distilled_klein(self) -> None:
        item = json.loads(json.dumps(ARTIFICEAL_V1))
        ci.ls.merge_image_resources(item, ARTIFICEAL_TRPC)
        ci.ls.merge_generation_payload(
            item, {"tools": [{"name": "Draw Things"}], "onSite": False}
        )
        text = ci.generation_data_from_image(item)

        def fake_add(*_a, **kw):
            return {
                "id": "civitai:2745770@3088444",
                "name": kw.get("name") or "Artificeal",
                "kind": "lora",
                "verified": True,
                "source": {
                    "host": "civitai",
                    "download": "https://civitai.com/api/download/models/3088444",
                    "filename": "Artificeal.safetensors",
                    "version_id": 3088444,
                    "version_name": "v1.0",
                },
            }

        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            with patch.object(ci.ls, "fetch_civitai_image", return_value=item), patch.object(
                ci.ls, "add_lora", side_effect=fake_add
            ):
                body = ci.import_to_request(
                    metadata_text=text, extras_path=extras
                )
        prompt = body["prompt"]
        self.assertEqual(
            prompt["70"]["inputs"]["unet_name"],
            "flux-2-klein-9b-fp8.safetensors",
        )
        self.assertEqual(prompt["66"]["inputs"]["width"], 1344)
        self.assertEqual(prompt["66"]["inputs"]["height"], 1792)
        self.assertEqual(prompt["63"]["inputs"]["cfg"], 1)
        self.assertEqual(prompt["62"]["inputs"]["steps"], 5)
        self.assertEqual(prompt["61"]["inputs"]["sampler_name"], "euler")
        self.assertIn("overalls", prompt["74"]["inputs"]["text"])
        self.assertIn("ARTIFICEAL lettering", prompt["74"]["inputs"]["text"])
        self.assertNotIn("<lora:", prompt["74"]["inputs"]["text"])
        self.assertEqual(prompt["74"]["inputs"]["clip"], ["80", 1])
        self.assertEqual(prompt["67"]["inputs"]["clip"], ["80", 1])
        loaders = [
            n
            for n in prompt.values()
            if isinstance(n, dict) and n.get("class_type") == "LoraLoader"
        ]
        self.assertEqual(len(loaders), 1)
        self.assertIn("3088444", loaders[0]["inputs"]["lora_name"])
        self.assertEqual(prompt["63"]["inputs"]["model"][0], "80")

    def test_seeds_3_trailing_underscore_maps_to_seeds_3(self) -> None:
        name, sched = ci._parse_sampler_field("seeds_3_")
        self.assertEqual(name, "seeds_3")
        self.assertIsNone(sched)
        self.assertEqual(ci._parse_sampler_field("not_a_real_sampler")[0], "euler")
        posted = ci.prompt_for_salad_replica(
            {
                "61": {
                    "class_type": "KSamplerSelect",
                    "inputs": {"sampler_name": "seeds_3_"},
                },
                "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x"}},
            }
        )
        self.assertEqual(posted["61"]["inputs"]["sampler_name"], "seeds_3")

    def test_civitai_resources_loras_and_seeds_sampler(self) -> None:
        item = {
            "id": 134012521,
            "width": 1424,
            "height": 2096,
            "modelVersionIds": [2625849, 2658598, 2661123],
            "meta": {
                "meta": {
                    "prompt": "A vibrant pop-art coastal city at dusk.",
                    "sampler": "seeds_3_",
                    "steps": 8,
                    "cfgScale": 1,
                    "seed": 347051366341964,
                    "Model": "flux-2-klein-9b-fp8",
                    "width": 1424,
                    "height": 2096,
                    "resources": [],
                    "civitaiResources": [
                        {"type": "checkpoint", "modelVersionId": 2658598},
                        {
                            "type": "lora",
                            "weight": 1.25,
                            "modelVersionId": 2661123,
                        },
                        {"type": "lora", "weight": 1, "modelVersionId": 2625849},
                    ],
                }
            },
        }
        text = ci.generation_data_from_image(item)
        self.assertIn("<lora:2661123:1.25>", text)
        self.assertIn("<lora:2625849:1>", text)
        self.assertIn("Sampler: seeds_3_", text)

        def fake_add(url, *_a, **kw):
            vid = str(url).rstrip("/").rsplit("/", 1)[-1]
            return {
                "id": f"civitai:{vid}@{vid}",
                "name": kw.get("name") or vid,
                "kind": "lora",
                "verified": True,
                "source": {
                    "host": "civitai",
                    "download": f"https://civitai.com/api/download/models/{vid}",
                    "filename": f"{vid}.safetensors",
                    "version_id": int(vid),
                },
            }

        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            with patch.object(ci.ls, "fetch_civitai_image", return_value=item), patch.object(
                ci.ls, "add_lora", side_effect=fake_add
            ):
                body = ci.import_to_request(
                    metadata_text=text, extras_path=extras
                )
        prompt = body["prompt"]
        self.assertEqual(prompt["61"]["inputs"]["sampler_name"], "seeds_3")
        loaders = [
            n
            for n in prompt.values()
            if isinstance(n, dict) and n.get("class_type") == "LoraLoader"
        ]
        by_vid = {}
        for node in loaders:
            url = str(node["inputs"]["lora_name"])
            for vid in ("2661123", "2625849"):
                if vid in url:
                    by_vid[vid] = node
        self.assertEqual(len(loaders), 2)
        self.assertEqual(by_vid["2661123"]["inputs"]["strength_model"], 1.25)
        self.assertEqual(by_vid["2625849"]["inputs"]["strength_model"], 1)


class CompatAndLoadImage(unittest.TestCase):
    def test_weight_family_krea_and_klein(self) -> None:
        self.assertEqual(ci.weight_family("krea2_turbo_fp8.safetensors"), "Krea 2")
        self.assertEqual(
            ci.weight_family("flux-2-klein-9b-kv-fp8.safetensors"), "Flux.2 Klein"
        )
        self.assertEqual(ci.weight_family("Krea 2"), "Krea 2")
        self.assertEqual(ci.weight_family("qwen_image_vae.safetensors"), "Krea 2")

    def test_load_image_author_missing_and_found(self) -> None:
        miss = ci.resolve_load_image(
            "Krea2_2026-08-01-222500_859820278897127.png"
        )
        self.assertEqual(miss["status"], "author_missing")
        http = ci.resolve_load_image("https://example.com/a.png")
        self.assertEqual(http["status"], "http")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "input.png").write_bytes(b"x")
            found = ci.resolve_load_image(str(root / "input.png"))
            self.assertEqual(found["status"], "local_found")
            os.environ["COMFYUI_INPUT"] = str(root)
            try:
                via_env = ci.resolve_load_image("input.png")
            finally:
                os.environ.pop("COMFYUI_INPUT", None)
            self.assertEqual(via_env["status"], "local_found")

    def test_replica_issues_flags_krea_checkpoint_lora_and_author_png(self) -> None:
        body = {
            "prompt": {
                "165": {
                    "class_type": "UNETLoader",
                    "inputs": {"unet_name": "flux-2-klein-9b-kv-fp8.safetensors"},
                },
                "80": {
                    "class_type": "LoraLoader",
                    "inputs": {
                        "lora_name": "https://civitai.com/api/download/models/3160394",
                        "strength_model": 1.0,
                    },
                },
                "91": {
                    "class_type": "LoadImage",
                    "inputs": {
                        "image": "Krea2_2026-08-01-222500_859820278897127.png"
                    },
                },
                "9": {
                    "class_type": "SaveImage",
                    "inputs": {"filename_prefix": "x"},
                },
            }
        }
        meta = (
            "Civitai resources: "
            "checkpoint|FLUX.2-klein-9b-fp8|Flux.2 Klein; "
            "checkpoint|Krea 2 Turbo Official Comfy-Org Checkpoints (Krea2)|Krea 2; "
            "lora|Krea2 Zass-style Animation|Krea 2"
        )
        issues = ci.replica_issues(body, metadata_text=meta)
        blob = "\n".join(issues)
        self.assertIn("2 checkpoints", blob)
        self.assertIn("Krea 2 Turbo", blob)
        self.assertIn("family Krea 2 is not loaded as UNET", blob)
        self.assertIn("Krea2 Zass-style Animation", blob)
        self.assertIn("author's Comfy input", blob)
        self.assertIn("Krea2_2026-08-01-222500_859820278897127.png", blob)
        self.assertIn("Generate omits it", blob)

    def test_replica_issues_flags_krea_unet_on_klein_replica(self) -> None:
        body = {
            "prompt": {
                "1": {
                    "class_type": "UNETLoader",
                    "inputs": {
                        "unet_name": "krea2_turbo_fp8_scaled.safetensors"
                    },
                }
            }
        }
        blob = "\n".join(ci.replica_issues(body))
        self.assertIn("family Krea 2", blob)
        self.assertIn("incompatible", blob)

    def test_generation_data_lists_civitai_resources(self) -> None:
        item = {
            "id": 138615853,
            "meta": {
                "meta": {
                    "prompt": "",
                    "Model": "flux-2-klein-9b-kv-fp8",
                    "resources": [
                        {
                            "name": "FLUX.2-klein-9b-fp8",
                            "type": "checkpoint",
                            "baseModel": "Flux.2 Klein 9B",
                        },
                        {
                            "name": "Krea 2 Turbo Official Comfy-Org Checkpoints (Krea2)",
                            "type": "checkpoint",
                            "baseModel": "Krea 2",
                        },
                        {
                            "name": "Krea2 Zass-style Animation",
                            "type": "lora",
                            "baseModel": "Krea 2",
                            "modelVersionId": 3160394,
                        },
                    ],
                }
            },
        }
        text = ci.generation_data_from_image(item)
        self.assertIn("Civitai resources:", text)
        self.assertIn("Krea 2 Turbo", text)
        parsed = ci.parse_civitai_metadata(text)
        types = {r["type"] for r in parsed.get("resources") or []}
        self.assertIn("checkpoint", types)
        self.assertIn("lora", types)


class SaladMissingTypesSingleSource(unittest.TestCase):
    """SALAD_MISSING_TYPES alone decides what Generate omits from the POST copy."""

    @staticmethod
    def _prompt_with(cls: str) -> dict:
        """Klein chain with ``cls`` wired between real nodes on the SaveImage path."""
        return {
            "70": {
                "class_type": "UNETLoader",
                "inputs": {
                    "unet_name": "flux-2-klein-9b-fp8.safetensors",
                    "weight_dtype": "default",
                },
            },
            "71": {
                "class_type": "CLIPLoader",
                "inputs": {
                    "clip_name": "qwen_3_8b_fp8mixed.safetensors",
                    "type": "flux2",
                },
            },
            "72": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": "flux2-vae.safetensors"},
            },
            "74": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "a cat", "clip": ["71", 0]},
            },
            "110": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["109", 0], "vae": ["72", 0]},
            },
            "900": {
                "class_type": cls,
                "inputs": {"conditioning": ["74", 0], "image": ["110", 0]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "klein", "images": ["900", 0]},
            },
        }

    @staticmethod
    def _types(prompt: dict) -> list[str]:
        return [
            str(n.get("class_type") or "")
            for n in prompt.values()
            if isinstance(n, dict)
        ]

    def test_every_shipped_missing_type_leaves_the_post_copy(self) -> None:
        for cls in sorted(ci.SALAD_MISSING_TYPES):
            with self.subTest(class_type=cls):
                posted = ci.prompt_for_salad_replica(self._prompt_with(cls))
                types = self._types(posted)
                self.assertNotIn(cls, types)
                self.assertIn("SaveImage", types)

    def test_omit_step_reads_the_shipped_set(self) -> None:
        cls = "ZzRuntimeMissingNode"
        with patch.object(ci, "SALAD_MISSING_TYPES", ci.SALAD_MISSING_TYPES | {cls}):
            posted = ci.prompt_for_salad_replica(self._prompt_with(cls))
        types = self._types(posted)
        self.assertNotIn(cls, types)
        self.assertIn("SaveImage", types)


if __name__ == "__main__":
    unittest.main()
