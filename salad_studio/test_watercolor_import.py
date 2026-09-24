"""Regression tests for the Civitai watercolor Klein generation-data paste.

Each field and each ``<lora:…>`` tag that already misfired (Cass SD 1.5,
Klein-anime V1, duplicate tags, distilled unet, DPM++ 2S a simple) is
asserted on its own, plus one Convert of the whole paste.
"""
from __future__ import annotations

import json
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
import lora_store as ls  # noqa: E402

# Exact Civitai generation data that failed Import (Cass + Klein-anime V1).
WATERCOLOR_PASTE = """(watercolor:1.3),comic,flat vector, Niji_oil_anime, (masterpiece), (best quality), (ultra-detailed), dappled shadows,  sunlight, dappled sunlight, ,,joyfull calm gentle smile
(artist:hamunezuko \\(nezukonezu32\\))), (artist:kantoku:0.8), artist:rebecca \\(keinelove\\),
(artist:yukiu con), artist:hashimoto kokai, artist:ogipote),,
op-left scene, a solitary figure stands amidst a landscape illuminated by a warm, golden light, possibly during sunset or sunrise. The central part of the image features a towering tree with bare branches reaching out into the sky, its silhouette stark against the soft glow of the setting sun. This scene is rich in detail and evokes a sense of mystery and tranquility., a captivating digital artwork by Yu 65026, known for their distinctive style and intricate compositions. It is part of the original series and features three panels that depict a surreal landscape filled with vibrant colors and dynamic forms. The scene is set in an autumnal forest, where trees and foliage are bathed in warm hues of orange, yellow, and red. The middle panel shows a close-up of the same tree, its branches reaching out into the sky. The light from the sun casts long shadows on the ground, adding depth to the scene. A figure stands nearby, their presence adding a sense of scale and human connection to this fantastical environment.,
a captivating digital artwork by Yu 65026, known for their distinctive style and intricate compositions. The scene is set in an autumnal landscape, where the trees are bathed in warm hues of orange and yellow, with falling leaves adding to the seasonal ambiance. In the background, a towering tree stands tall, its branches reaching out into the sky, creating a sense of depth and scale. The overall composition is rich in detail, capturing the beauty and complexity of nature's cycles while also highlighting the artist's skillful use of color and form to convey emotion and narrative. This artwork seems to be part of an original series or project by Yu 65026, showcasing their unique style and storytelling prowess in a visually striking manner.
<lora:transparent-watercolor_IL_MIX:0.45> <lora:Ah! My Goddess_illustriousXL:0.8> <lora:Sakaki_Azumanga_Daioh:0.7> <lora:transparent-watercolor_IL_MIX:0.4> <lora:Ah! My Goddess_illustriousXL:0.8> <lora:Alpha_-_YKK_-_Yokohama_Kaidashi_Kikou:0.75> <lora:cass_aruhshuraanima_preview3_1-step00004500:0.65> <lora:anima-preview-3-masterpieces-v5:0.8> <lora:CitrixCitronOC_ANIMA:0.5> <lora:Flux.2 Klein 9B anime:0.85>
Negative prompt: bad, ugly, blurry,
monochrome, grayscale,
text,
worst quality, bad quality, low quality,  watermark, monochrome, signature,logo,artist name,
Steps: 35, CFG scale: 4, Sampler: DPM++ 2S a simple, Seed: 169803930162055, Model: flux-2-klein-9b-fp8, width: 1080, height: 1536, Model hash: 865ba09f5b
"""

# Paste order, including duplicate watercolor / Goddess occurrences.
WATERCOLOR_LORAS: tuple[tuple[str, float, int, str], ...] = (
    (
        "transparent-watercolor_IL_MIX",
        0.45,
        1730326,
        "transparent-watercolor_IL_MIX.safetensors",
    ),
    (
        "Ah! My Goddess_illustriousXL",
        0.8,
        1810929,
        "Ah! My Goddess_illustriousXL.safetensors",
    ),
    (
        "Sakaki_Azumanga_Daioh",
        0.7,
        1805810,
        "Sakaki_Azumanga_Daioh.safetensors",
    ),
    (
        "transparent-watercolor_IL_MIX",
        0.4,
        1730326,
        "transparent-watercolor_IL_MIX.safetensors",
    ),
    (
        "Ah! My Goddess_illustriousXL",
        0.8,
        1810929,
        "Ah! My Goddess_illustriousXL.safetensors",
    ),
    (
        "Alpha_-_YKK_-_Yokohama_Kaidashi_Kikou",
        0.75,
        2137047,
        "Alpha_-_YKK_-_Yokohama_Kaidashi_Kikou.safetensors",
    ),
    (
        "cass_aruhshuraanima_preview3_1-step00004500",
        0.65,
        2848936,
        "cass_aruhshuraanima_preview3_1-step00004500.safetensors",
    ),
    (
        "anima-preview-3-masterpieces-v5",
        0.8,
        2905490,
        "anima-preview-3-masterpieces-v5.safetensors",
    ),
    (
        "CitrixCitronOC_ANIMA",
        0.5,
        2713096,
        "CitrixCitronOC_ANIMA.safetensors",
    ),
    (
        "Flux.2 Klein 9B anime",
        0.85,
        2825584,
        "Flux.2 Klein 9B Anime V3 Refined.safetensors",
    ),
)

# Civitai search shape: correct files plus the distractors that already won.
WATERCOLOR_CIVITAI_ITEMS: list[dict] = [
    {
        "id": 338702,
        "name": "transparent-watercolor(medium lora)",
        "modelVersions": [
            {"id": 1, "files": [{"name": "watercolor.safetensors"}]},
            {
                "id": 1730326,
                "name": "IL MIX",
                "files": [{"name": "transparent-watercolor_IL_MIX.safetensors"}],
            },
        ],
    },
    {
        "id": 999695,
        "name": "[illustrious XL] Ah! My Goddess",
        "modelVersions": [
            {
                "id": 3131267,
                "files": [{"name": "Ah! My Goddess_v3_illustriousXL.safetensors"}],
            },
            {
                "id": 1810929,
                "name": "v2.0",
                "files": [{"name": "Ah! My Goddess_illustriousXL.safetensors"}],
            },
        ],
    },
    {
        "id": 1595759,
        "name": "Sakaki (Azumanga Daioh)",
        "modelVersions": [
            {
                "id": 1805810,
                "files": [{"name": "Sakaki_Azumanga_Daioh.safetensors"}],
            },
        ],
    },
    {
        "id": 1888031,
        "name": "Alpha - YKK - Yokohama Kaidashi Kikou",
        "modelVersions": [
            {
                "id": 2137047,
                "files": [
                    {"name": "Alpha_-_YKK_-_Yokohama_Kaidashi_Kikou.safetensors"}
                ],
            },
        ],
    },
    {
        "id": 99,
        "name": "Cass",
        "modelVersions": [
            {"id": 2255999, "files": [{"name": "Cass.safetensors"}]},
        ],
    },
    {
        "id": 2444547,
        "name": "Cass/Aruhshura (Latest style) | Style",
        "modelVersions": [
            {
                "id": 2949873,
                "files": [
                    {"name": "cass_aruhshuraanima_v1_1-step00004500.safetensors"}
                ],
            },
            {
                "id": 2848936,
                "name": "preview 3",
                "files": [
                    {
                        "name": "cass_aruhshuraanima_preview3_1-step00004500.safetensors"
                    }
                ],
            },
        ],
    },
    {
        "id": 111,
        "name": "Koihime anima-preview-3",
        "modelVersions": [
            {
                "id": 1111111,
                "files": [{"name": "koihime_anima_preview3.safetensors"}],
            },
        ],
    },
    {
        "id": 929497,
        "name": "Aesthetic Quality Modifiers - Masterpiece",
        "modelVersions": [
            {
                "id": 2905490,
                "files": [{"name": "anima-preview-3-masterpieces-v5.safetensors"}],
            },
        ],
    },
    {
        "id": 1736187,
        "name": "Citrix CitronOC ANIMA & IL",
        "modelVersions": [
            {
                "id": 2600000,
                "files": [{"name": "CitrixCitronOC_IL.safetensors"}],
            },
            {
                "id": 2713096,
                "files": [{"name": "CitrixCitronOC_ANIMA.safetensors"}],
            },
        ],
    },
    {
        "id": 2432849,
        "name": "Mrpopo's Flux.2 Klein 9B anime",
        "modelVersions": [
            {
                "id": 2735459,
                "files": [{"name": "Flux.2 Klein 9B anime.safetensors"}],
            },
            {
                "id": 2825584,
                "name": "Anime V3 Refined",
                "files": [
                    {"name": "Flux.2 Klein 9B Anime V3 Refined.safetensors"}
                ],
            },
        ],
    },
]

PROMPT_SNIPPETS = (
    "(watercolor:1.3)",
    "comic,flat vector, Niji_oil_anime",
    "joyfull calm gentle smile",
    "hamunezuko \\(nezukonezu32\\)",
    "kantoku:0.8",
    "rebecca \\(keinelove\\)",
    "yukiu con",
    "hashimoto kokai",
    "ogipote",
    "Yu 65026",
    "autumnal forest",
    "op-left scene",
    "solitary figure",
)

NEGATIVE_SNIPPETS = (
    "bad, ugly, blurry",
    "monochrome, grayscale",
    "watermark",
    "artist name",
)

KNOBS = (
    ("steps", 35),
    ("cfg", 4),
    ("sampler", "dpmpp_2s_ancestral"),
    ("scheduler", "simple"),
    ("seed", 169803930162055),
    ("model", "flux-2-klein-9b-fp8.safetensors"),
    ("width", 1080),
    ("height", 1536),
)


def _fake_search(query: str) -> dict | None:
    """Run the real filename matcher on the watercolor Civitai catalog."""
    hit = ls.best_civitai_hit(query, WATERCOLOR_CIVITAI_ITEMS)
    if hit is None:
        raise AssertionError(f"unexpected Civitai search query: {query!r}")
    return hit


def _lora_nodes(prompt: dict) -> list[dict]:
    nodes: list[tuple[int, dict]] = []
    for nid, node in prompt.items():
        if not isinstance(node, dict) or node.get("class_type") != "LoraLoader":
            continue
        try:
            num = int(nid)
        except (TypeError, ValueError):
            num = 0
        nodes.append((num, node))
    nodes.sort()
    return [n for _i, n in nodes]


class ParseWatercolorPaste(unittest.TestCase):
    def setUp(self) -> None:
        self.meta = ci.parse_civitai_metadata(WATERCOLOR_PASTE)

    def test_each_knob(self) -> None:
        for key, want in KNOBS:
            with self.subTest(key=key):
                self.assertEqual(self.meta.get(key), want)

    def test_knobs_from_sources_matches_parse(self) -> None:
        knobs = ci.knobs_from_sources(WATERCOLOR_PASTE, "")
        self.assertEqual(knobs["steps"], 35)
        self.assertEqual(knobs["cfg"], 4)
        self.assertEqual(knobs["sampler"], "dpmpp_2s_ancestral")
        self.assertEqual(knobs["scheduler"], "simple")
        self.assertEqual(knobs["seed"], 169803930162055)
        self.assertEqual(knobs["unet"], "flux-2-klein-9b-fp8.safetensors")
        self.assertEqual(knobs["width"], 1080)
        self.assertEqual(knobs["height"], 1536)

    def test_model_hash_is_not_the_unet(self) -> None:
        self.assertNotIn("865ba09f5b", str(self.meta.get("model") or ""))
        self.assertNotIn("hash", str(self.meta.get("model") or "").lower())

    def test_prompt_keeps_each_scene_fragment(self) -> None:
        prompt = str(self.meta.get("prompt") or "")
        for snippet in PROMPT_SNIPPETS:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, prompt)

    def test_prompt_strips_lora_tags_and_trailer(self) -> None:
        prompt = str(self.meta.get("prompt") or "")
        self.assertNotIn("<lora:", prompt)
        self.assertNotIn("Negative prompt", prompt)
        self.assertNotIn("Steps:", prompt)
        self.assertNotIn("Model hash", prompt)

    def test_negative_keeps_each_line(self) -> None:
        negative = str(self.meta.get("negative") or "")
        for snippet in NEGATIVE_SNIPPETS:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, negative)
        self.assertNotIn("Steps:", negative)
        self.assertNotIn("<lora:", negative)

    def test_lora_tags_keep_paste_order_including_duplicates(self) -> None:
        tags = list(self.meta.get("lora_tags") or [])
        self.assertEqual([t["name"] for t in tags], [row[0] for row in WATERCOLOR_LORAS])
        for i, (tag, strength, _ver, _fn) in enumerate(WATERCOLOR_LORAS):
            with self.subTest(i=i, tag=tag):
                self.assertEqual(tags[i]["name"], tag)
                self.assertAlmostEqual(float(tags[i]["strength"]), strength)

    def test_duplicate_watercolor_and_goddess_are_kept(self) -> None:
        names = [t["name"] for t in (self.meta.get("lora_tags") or [])]
        self.assertEqual(names.count("transparent-watercolor_IL_MIX"), 2)
        self.assertEqual(names.count("Ah! My Goddess_illustriousXL"), 2)

    def test_inspect_is_not_blocking(self) -> None:
        blocking, notes = ci.inspect_pastes(WATERCOLOR_PASTE, "")
        self.assertEqual(blocking, [])
        self.assertEqual(notes, [])


class WatercolorLoraMatching(unittest.TestCase):
    def test_each_tag_picks_the_filename_version(self) -> None:
        for tag, _w, ver, fname in WATERCOLOR_LORAS:
            with self.subTest(tag=tag):
                hit = ls.best_civitai_hit(tag, WATERCOLOR_CIVITAI_ITEMS)
                self.assertIsNotNone(hit, tag)
                assert hit is not None
                self.assertEqual(hit["version_id"], ver, tag)
                self.assertEqual(hit["filename"], fname, tag)
                self.assertIn(str(ver), hit["download"])

    def test_cass_does_not_pick_sd15(self) -> None:
        hit = ls.best_civitai_hit(
            "cass_aruhshuraanima_preview3_1-step00004500",
            WATERCOLOR_CIVITAI_ITEMS,
        )
        assert hit is not None
        self.assertEqual(hit["version_id"], 2848936)
        self.assertNotEqual(hit["version_id"], 2255999)

    def test_klein_anime_does_not_pick_v1(self) -> None:
        hit = ls.best_civitai_hit("Flux.2 Klein 9B anime", WATERCOLOR_CIVITAI_ITEMS)
        assert hit is not None
        self.assertEqual(hit["version_id"], 2825584)
        self.assertNotEqual(hit["version_id"], 2735459)

    def test_goddess_tag_picks_v2_filename_not_mid_name_v3(self) -> None:
        hit = ls.best_civitai_hit(
            "Ah! My Goddess_illustriousXL", WATERCOLOR_CIVITAI_ITEMS
        )
        assert hit is not None
        self.assertEqual(hit["version_id"], 1810929)
        self.assertNotEqual(hit["version_id"], 3131267)
        self.assertFalse(
            ls.is_tag_or_suffix(
                "Ah! My Goddess_illustriousXL",
                {
                    "filename": "Ah! My Goddess_v3_illustriousXL.safetensors",
                },
            )
        )

    def test_each_tag_scores_exact_file_100_and_wrong_file_below_60(self) -> None:
        wrong = {
            "transparent-watercolor_IL_MIX": ["watercolor.safetensors"],
            "cass_aruhshuraanima_preview3_1-step00004500": ["Cass.safetensors"],
            "anima-preview-3-masterpieces-v5": ["koihime_anima_preview3.safetensors"],
            "CitrixCitronOC_ANIMA": ["CitrixCitronOC_IL.safetensors"],
        }
        for tag, _w, _ver, fname in WATERCOLOR_LORAS:
            with self.subTest(tag=tag, kind="file"):
                score = ls.score_civitai_hit(tag, "", [fname])
                # V3 Klein is the tag plus a suffix (90); others are exact (100).
                self.assertGreaterEqual(score, 90, fname)
            if tag in wrong:
                with self.subTest(tag=tag, kind="wrong"):
                    self.assertLess(
                        ls.score_civitai_hit(tag, "", wrong[tag]),
                        60,
                    )

    def test_klein_v3_filename_is_strong_match(self) -> None:
        self.assertGreaterEqual(
            ls.score_civitai_hit(
                "Flux.2 Klein 9B anime",
                "Mrpopo's Flux.2 Klein 9B anime",
                ["Flux.2 Klein 9B Anime V3 Refined.safetensors"],
            ),
            90,
        )


class WatercolorConvert(unittest.TestCase):
    def _convert(self, extras: Path) -> dict:
        with patch.object(ci.ls, "civitai_search_lora", side_effect=_fake_search):
            return ci.import_to_request(
                metadata_text=WATERCOLOR_PASTE, extras_path=extras
            )

    def test_whole_graph(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            body = self._convert(extras)
        prompt = body["prompt"]
        self.assertEqual(
            prompt["70"]["inputs"]["unet_name"],
            "flux-2-klein-9b-fp8.safetensors",
        )
        self.assertEqual(
            prompt["71"]["inputs"]["clip_name"],
            "qwen_3_8b_fp8mixed.safetensors",
        )
        self.assertEqual(prompt["72"]["inputs"]["vae_name"], "flux2-vae.safetensors")
        self.assertEqual(prompt["66"]["inputs"]["width"], 1080)
        self.assertEqual(prompt["66"]["inputs"]["height"], 1536)
        self.assertEqual(prompt["62"]["class_type"], "BasicScheduler")
        self.assertEqual(prompt["62"]["inputs"]["scheduler"], "simple")
        self.assertEqual(prompt["62"]["inputs"]["steps"], 35)
        self.assertEqual(prompt["61"]["inputs"]["sampler_name"], "dpmpp_2s_ancestral")
        self.assertEqual(prompt["63"]["inputs"]["cfg"], 4)
        self.assertEqual(prompt["73"]["inputs"]["noise_seed"], 169803930162055)
        self.assertEqual(body["convert_output"]["format"], "jpeg")

        positive = prompt["74"]["inputs"]["text"]
        negative = prompt["67"]["inputs"]["text"]
        for snippet in PROMPT_SNIPPETS:
            with self.subTest(clip="positive", snippet=snippet):
                self.assertIn(snippet, positive)
        self.assertNotIn("<lora:", positive)
        for snippet in NEGATIVE_SNIPPETS:
            with self.subTest(clip="negative", snippet=snippet):
                self.assertIn(snippet, negative)

        loaders = _lora_nodes(prompt)
        self.assertEqual(len(loaders), len(WATERCOLOR_LORAS))
        urls = [str((n.get("inputs") or {}).get("lora_name") or "") for n in loaders]
        strengths = [
            float((n.get("inputs") or {}).get("strength_model") or 0) for n in loaders
        ]
        for i, (tag, strength, ver, _fn) in enumerate(WATERCOLOR_LORAS):
            with self.subTest(tag=tag):
                self.assertIn(str(ver), urls[i], urls[i])
                self.assertTrue(urls[i].startswith("https://"), urls[i])
                self.assertAlmostEqual(strengths[i], strength)
        self.assertTrue(all("2255999" not in u for u in urls), urls)
        self.assertTrue(all("2735459" not in u for u in urls), urls)
        self.assertTrue(all("3131267" not in u for u in urls), urls)

        last = loaders[-1]
        last_id = 80 + len(WATERCOLOR_LORAS) - 1
        self.assertEqual(prompt["63"]["inputs"]["model"], [str(last_id), 0])
        self.assertEqual(last["inputs"]["model"], [str(last_id - 1), 0])
        # Klein-native stack: request_json.wire_clip_encodes puts both CLIP
        # encodes on the LAST Klein-native LoraLoader (the "encode after the
        # last LoRA" half of the rule), not on the CLIPLoader. Basis: the live
        # Import -> Convert -> Generate run in the audit report §5 reproduced
        # the Civitai Draw Things image this way.
        self.assertEqual(prompt["74"]["inputs"]["clip"], [str(last_id), 1])
        self.assertEqual(prompt["67"]["inputs"]["clip"], [str(last_id), 1])
        self.assertEqual(prompt["71"]["class_type"], "CLIPLoader")
        self.assertEqual(
            (prompt["70"].get("_meta") or {}).get("title"),
            "flux-2-klein-9b-fp8.safetensors",
        )
        refs = {str(r.get("node")): r for r in (body.get("refs") or [])}
        self.assertEqual(refs["70"]["name"], "flux-2-klein-9b-fp8.safetensors")
        self.assertEqual(refs["71"]["name"], "qwen_3_8b_fp8mixed.safetensors")
        self.assertEqual(refs["72"]["name"], "flux2-vae.safetensors")
        for i, (tag, _strength, ver, fname) in enumerate(WATERCOLOR_LORAS):
            nid = str(80 + i)
            with self.subTest(ref=nid, tag=tag):
                meta = prompt[nid].get("_meta") or {}
                self.assertEqual(meta.get("title"), fname)
                self.assertTrue(meta.get("verified"))
                self.assertIn(str(ver), prompt[nid]["inputs"]["lora_name"])
                self.assertEqual(refs[nid]["name"], fname)
                self.assertIn(str(ver), str(refs[nid].get("ref") or ""))
        klein_meta = prompt[str(80 + len(WATERCOLOR_LORAS) - 1)].get("_meta") or {}
        self.assertEqual(klein_meta.get("version"), "Anime V3 Refined")
        self.assertEqual(klein_meta.get("variation"), "V3")
        self.assertEqual(
            refs[str(80 + len(WATERCOLOR_LORAS) - 1)].get("version"),
            "Anime V3 Refined",
        )
        self.assertEqual(
            refs[str(80 + len(WATERCOLOR_LORAS) - 1)].get("variation"),
            "V3",
        )

    def test_stale_cass_and_klein_v1_extras_do_not_win(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            extras.write_text(
                json.dumps(
                    [
                        {
                            "id": "civitai:1@2255999",
                            "name": "cass_aruhshuraanima_preview3_1-step00004500",
                            "kind": "lora",
                            "source": {
                                "download": "https://civitai.com/api/download/models/2255999",
                                "filename": "Cass.safetensors",
                                "version_id": 2255999,
                            },
                        },
                        {
                            "id": "civitai:2432849@2735459",
                            "name": "Flux.2 Klein 9B anime",
                            "kind": "lora",
                            "source": {
                                "download": "https://civitai.com/api/download/models/2735459",
                                "filename": "Flux.2 Klein 9B anime.safetensors",
                                "model_id": 2432849,
                                "version_id": 2735459,
                            },
                        },
                        {
                            "id": "civitai:999695@3131267",
                            "name": "Ah! My Goddess_illustriousXL",
                            "kind": "lora",
                            "source": {
                                "download": "https://civitai.com/api/download/models/3131267",
                                "filename": "Ah! My Goddess_v3_illustriousXL.safetensors",
                                "model_id": 999695,
                                "version_id": 3131267,
                            },
                        },
                    ]
                ),
                encoding="utf-8",
            )
            body = self._convert(extras)
        urls = [
            str((n.get("inputs") or {}).get("lora_name") or "")
            for n in _lora_nodes(body["prompt"])
        ]
        joined = " ".join(urls)
        self.assertIn("2848936", joined)
        self.assertIn("2825584", joined)
        self.assertIn("1810929", joined)
        self.assertNotIn("2255999", joined)
        self.assertNotIn("2735459", joined)
        self.assertNotIn("3131267", joined)


class ForeignStackClipEncode(unittest.TestCase):
    """The other half of the split rule: a foreign-only stack encodes on the CLIPLoader."""

    def test_foreign_only_stack_keeps_both_clip_encodes_on_the_clip_loader(self) -> None:
        lora = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["70", 0],
                "clip": ["71", 0],
                "lora_name": "https://civitai.com/api/download/models/1730326",
                "strength_model": 1.0,
                "strength_clip": 1.0,
            },
            "_meta": {"title": "transparent-watercolor_IL_MIX.safetensors"},
        }
        self.assertTrue(ci.rj.lora_is_foreign_clip(lora))
        self.assertFalse(ci.rj.lora_is_klein_clip(lora))
        prompt = {
            "70": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "flux-2-klein-9b-fp8.safetensors"},
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
            "80": lora,
            "74": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "positive", "clip": ["80", 1]},
            },
            "67": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "negative", "clip": ["80", 1]},
            },
            "110": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["109", 0], "vae": ["72", 0]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "klein", "images": ["110", 0]},
            },
        }
        posted = ci.prompt_for_salad_replica(prompt)
        self.assertIn("80", posted)
        self.assertEqual(posted["74"]["inputs"]["clip"], ["71", 0])
        self.assertEqual(posted["67"]["inputs"]["clip"], ["71", 0])
