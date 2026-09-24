"""Tests for salad_studio.lora_store. Never touch the real extras file."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TOOLS))

import lora_store as ls  # noqa: E402


class ListKnown(unittest.TestCase):
    def test_list_includes_klein_baked_loras(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            rows = ls.list_loras(extras)
        ids = [r["id"] for r in rows]
        self.assertIn("civitai:2334190@2625692", ids)
        self.assertIn("civitai:545264@2763568", ids)
        self.assertIn("civitai:637213@2760271", ids)
        for row in rows:
            self.assertEqual(row.get("kind"), "lora")
        self.assertNotEqual(extras.resolve(), ls.EXTRAS_PATH.resolve())

    def test_baked_klein_uses_filename_not_url(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            item = ls.find_lora("civitai:2334190@2625692", extras)
        assert item is not None
        self.assertEqual(
            ls.comfy_lora_name(item),
            "https://civitai.com/api/download/models/2625692",
        )
        imp = ls.find_lora("civitai:545264@2763568", extras)
        assert imp is not None
        self.assertEqual(
            ls.comfy_lora_name(imp),
            "https://civitai.com/api/download/models/2763568",
        )
        sm, sc = ls.strengths_for(imp)
        self.assertEqual(sm, 0.8)
        self.assertEqual(sc, 0.8)

    def test_listed_ce_lora_uses_download_url(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            item = ls.find_lora("civitai:637213@2760271", extras)
        assert item is not None
        name = ls.comfy_lora_name(item)
        self.assertTrue(name.startswith("https://"), name)
        self.assertIn("2760271", name)


class CivitaiSearchScore(unittest.TestCase):
    def test_filename_stem_beats_unrelated_title(self) -> None:
        hit = ls.score_civitai_hit(
            "transparent-watercolor_IL_MIX",
            "Some Watercolor Mix",
            ["transparent-watercolor_IL_MIX.safetensors"],
        )
        miss = ls.score_civitai_hit(
            "transparent-watercolor_IL_MIX",
            "Unrelated LoRA",
            ["other.safetensors"],
        )
        self.assertEqual(hit, 100)
        self.assertLess(miss, 60)

    def test_title_contains_query(self) -> None:
        score = ls.score_civitai_hit(
            "Flux.2 Klein 9B anime",
            "Mrpopo's Flux.2 Klein 9B anime",
            ["klein_anime_v3.safetensors"],
        )
        self.assertGreaterEqual(score, 70)

    def test_picks_older_version_with_exact_filename(self) -> None:
        items = [
            {
                "id": 338702,
                "name": "transparent-watercolor(medium lora)",
                "modelVersions": [
                    {"id": 1, "files": [{"name": "watercolor.safetensors"}]},
                    {
                        "id": 42,
                        "files": [{"name": "transparent-watercolor_IL_MIX.safetensors"}],
                    },
                ],
            }
        ]
        hit = ls.best_civitai_hit("transparent-watercolor_IL_MIX", items)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["version_id"], 42)
        self.assertEqual(hit["filename"], "transparent-watercolor_IL_MIX.safetensors")

    def test_picks_newer_version_when_filename_is_tag_plus_suffix(self) -> None:
        items = [
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
                        "files": [
                            {"name": "Flux.2 Klein 9B Anime V3 Refined.safetensors"}
                        ],
                    },
                ],
            }
        ]
        hit = ls.best_civitai_hit("Flux.2 Klein 9B anime", items)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["version_id"], 2825584)
        self.assertEqual(
            hit["filename"], "Flux.2 Klein 9B Anime V3 Refined.safetensors"
        )
        self.assertIn("2825584", hit["download"])

        v1_first = [
            {
                "id": 2432849,
                "name": "Mrpopo's Flux.2 Klein 9B anime",
                "modelVersions": list(reversed(items[0]["modelVersions"])),
            }
        ]
        hit2 = ls.best_civitai_hit("Flux.2 Klein 9B anime", v1_first)
        assert hit2 is not None
        self.assertEqual(hit2["version_id"], 2825584)

    def test_prefer_civitai_hit_upgrades_v1_tag_to_v3_suffix(self) -> None:
        v1 = {
            "filename": "Flux.2 Klein 9B anime.safetensors",
            "name": "Mrpopo's Flux.2 Klein 9B anime",
            "model_id": 2432849,
            "version_id": 2735459,
            "download": "https://civitai.com/api/download/models/2735459",
        }
        v3 = {
            "filename": "Flux.2 Klein 9B Anime V3 Refined.safetensors",
            "name": "Mrpopo's Flux.2 Klein 9B anime",
            "model_id": 2432849,
            "version_id": 2825584,
            "download": "https://civitai.com/api/download/models/2825584",
        }
        picked = ls.prefer_civitai_hit("Flux.2 Klein 9B anime", v1, v3)
        self.assertIs(picked, v3)
        # extras often stores civitai:version@version so model_ids differ
        v1_download_only = dict(v1, model_id=2735459)
        picked2 = ls.prefer_civitai_hit("Flux.2 Klein 9B anime", v1_download_only, v3)
        self.assertIs(picked2, v3)

    def test_goddess_v3_mid_name_does_not_beat_exact_v2_filename(self) -> None:
        items = [
            {
                "id": 999695,
                "name": "[illustrious XL] Ah! My Goddess",
                "modelVersions": [
                    {
                        "id": 3131267,
                        "files": [
                            {"name": "Ah! My Goddess_v3_illustriousXL.safetensors"}
                        ],
                    },
                    {
                        "id": 1810929,
                        "files": [
                            {"name": "Ah! My Goddess_illustriousXL.safetensors"}
                        ],
                    },
                ],
            }
        ]
        hit = ls.best_civitai_hit("Ah! My Goddess_illustriousXL", items)
        assert hit is not None
        self.assertEqual(hit["version_id"], 1810929)
        self.assertNotEqual(hit["version_id"], 3131267)

    def test_query_variants_include_tail(self) -> None:
        vars_ = ls._query_variants("anima-preview-3-masterpieces-v5")
        self.assertIn("masterpieces-v5", vars_)

    def test_short_cass_title_does_not_match_aruhshura_tag(self) -> None:
        self.assertEqual(
            ls.score_civitai_hit(
                "cass_aruhshuraanima_preview3_1-step00004500",
                "Cass",
                ["Cass.safetensors"],
            ),
            0,
        )
        self.assertEqual(
            ls.score_civitai_hit(
                "cass_aruhshuraanima_preview3_1-step00004500",
                "Cass/Aruhshura (Latest style) | Style",
                ["cass_aruhshuraanima_preview3_1-step00004500.safetensors"],
            ),
            100,
        )

    def test_picks_aruhshura_preview3_not_generic_cass(self) -> None:
        items = [
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
                        "files": [
                            {
                                "name": "cass_aruhshuraanima_preview3_1-step00004500.safetensors"
                            }
                        ],
                    },
                ],
            },
        ]
        hit = ls.best_civitai_hit(
            "cass_aruhshuraanima_preview3_1-step00004500", items
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["version_id"], 2848936)
        self.assertEqual(
            hit["filename"],
            "cass_aruhshuraanima_preview3_1-step00004500.safetensors",
        )
        self.assertIn("2848936", hit["download"])

    def test_query_variants_strip_step_suffix(self) -> None:
        vars_ = ls._query_variants("cass_aruhshuraanima_preview3_1-step00004500")
        self.assertTrue(
            any("aruhshuraanima_preview3" in v for v in vars_), vars_
        )


class AddFromSources(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.extras = Path(self._td.name) / "studio-loras.json"

        def fake_version(version_id, timeout=15):
            vid = int(version_id)
            return {
                "id": vid,
                "modelId": vid,
                "files": [
                    {
                        "name": f"civitai-{vid}.safetensors",
                        "primary": True,
                        "downloadUrl": f"https://civitai.com/api/download/models/{vid}",
                    }
                ],
            }

        self._p_ver = patch.object(
            ls, "fetch_civitai_version", side_effect=fake_version
        )
        self._p_http = patch.object(ls, "verify_http_url", return_value=True)
        self._p_ver.start()
        self._p_http.start()
        self.addCleanup(self._p_ver.stop)
        self.addCleanup(self._p_http.stop)

    def test_add_civitai_url(self) -> None:
        item = ls.add_lora(
            "https://civitai.com/models/957327?modelVersionId=2725918",
            extras_path=self.extras,
        )
        self.assertEqual(item["id"], "civitai:957327@2725918")
        src = item["source"]
        self.assertEqual(src["host"], "civitai")
        self.assertIn("2725918", src["download"])
        self.assertTrue(item.get("verified"))
        loaded = json.loads(self.extras.read_text(encoding="utf-8"))
        ids = [it["id"] for it in loaded["items"]]
        self.assertIn("civitai:957327@2725918", ids)

    def test_add_civitai_short_ref(self) -> None:
        item = ls.add_lora("civitai:2745770@3088444", extras_path=self.extras)
        self.assertEqual(item["id"], "civitai:2745770@3088444")
        self.assertIn("3088444", item["source"]["download"])
        self.assertTrue(item.get("verified"))

    def test_add_huggingface_url(self) -> None:
        url = (
            "https://huggingface.co/example/lora/resolve/main/"
            "MyStyle.safetensors"
        )
        item = ls.add_lora(url, extras_path=self.extras, name="My Style")
        self.assertEqual(item["id"], "hf:MyStyle.safetensors")
        self.assertEqual(item["name"], "My Style")
        self.assertEqual(item["source"]["host"], "huggingface")
        self.assertEqual(item["source"]["download"], url)
        self.assertEqual(ls.comfy_lora_name(item), url)
        self.assertTrue(item.get("verified"))

    def test_add_direct_download_url(self) -> None:
        url = "https://cdn.example.test/weights/foo.safetensors"
        item = ls.add_lora(url, extras_path=self.extras)
        self.assertEqual(item["source"]["host"], "url")
        self.assertEqual(item["source"]["download"], url)
        self.assertEqual(item["source"]["filename"], "foo.safetensors")
        self.assertTrue(item.get("verified"))

    def test_add_local_path(self) -> None:
        local = Path(self._td.name) / "on_disk.safetensors"
        local.write_bytes(b"lora")
        item = ls.add_lora(str(local), extras_path=self.extras)
        self.assertEqual(item["id"], "local:on_disk.safetensors")
        self.assertEqual(item["source"]["host"], "local")
        self.assertEqual(item["source"]["filename"], "on_disk.safetensors")
        self.assertTrue(item.get("verified"))
        found = ls.find_lora("local:on_disk.safetensors", self.extras)
        assert found is not None
        self.assertEqual(found["source"]["filename"], "on_disk.safetensors")

    def test_add_bare_safetensors_filename(self) -> None:
        item = ls.add_lora(
            "HighResolution9B.safetensors",
            extras_path=self.extras,
            strength_model=0.6,
            base="Flux.2 Klein",
        )
        self.assertEqual(item["id"], "local:HighResolution9B.safetensors")
        self.assertEqual(item["source"]["filename"], "HighResolution9B.safetensors")
        self.assertEqual(ls.comfy_lora_name(item), "HighResolution9B.safetensors")
        self.assertFalse(item.get("verified"))
        self.assertEqual(item["strength_model"], 0.6)
        found = ls.find_by_loader_name("HighResolution9B.safetensors", self.extras)
        self.assertIsNotNone(found)

    def test_add_persists_row_for_every_source_kind(self) -> None:
        """add_lora must write the extras row for local / bare-name / hf / url refs."""
        local = Path(self._td.name) / "on_disk.safetensors"
        local.write_bytes(b"lora")
        cases = [
            (
                "local path",
                str(local),
                "local:on_disk.safetensors",
                "local",
                "on_disk.safetensors",
            ),
            (
                "bare filename",
                "SomeName.safetensors",
                "local:SomeName.safetensors",
                "local",
                "SomeName.safetensors",
            ),
            (
                "huggingface url",
                "https://huggingface.co/example/lora/resolve/main/MyStyle.safetensors",
                "hf:MyStyle.safetensors",
                "huggingface",
                "MyStyle.safetensors",
            ),
            (
                "download url",
                "https://cdn.example.test/weights/foo.safetensors",
                "url:foo.safetensors",
                "url",
                "foo.safetensors",
            ),
        ]
        for label, ref, want_id, want_host, want_filename in cases:
            with self.subTest(source=label):
                extras = Path(tempfile.mkdtemp(dir=self._td.name)) / "studio-loras.json"
                item = ls.add_lora(ref, extras_path=extras)
                self.assertEqual(item["id"], want_id)
                self.assertTrue(extras.is_file(), "add_lora did not write an extras row")
                found = ls.find_lora(want_id, extras)
                self.assertIsNotNone(found, f"{want_id} missing after re-read")
                self.assertEqual(found["source"]["host"], want_host)
                self.assertEqual(found["source"]["filename"], want_filename)
                listed = {row["id"]: row for row in ls.list_loras(extras)}
                self.assertIn(want_id, listed)
                self.assertEqual(listed[want_id]["source"]["host"], want_host)
                self.assertEqual(listed[want_id]["source"]["filename"], want_filename)

    def test_add_unknown_civitai_ref_is_valueerror_not_systemexit(self) -> None:
        with self.assertRaises(ValueError):
            ls.add_lora("not-a-ref", extras_path=self.extras)

    def test_remove_only_extras(self) -> None:
        ls.add_lora("civitai:1@2", extras_path=self.extras, name="temp")
        self.assertTrue(ls.remove_lora("civitai:1@2", extras_path=self.extras))
        self.assertIsNone(ls.find_lora("civitai:1@2", self.extras))
        # Known rows stay even if we try to remove them from extras.
        self.assertFalse(ls.remove_lora("civitai:2334190@2625692", extras_path=self.extras))
        self.assertIsNotNone(ls.find_lora("civitai:2334190@2625692", self.extras))

    def test_specs_for_ids_order(self) -> None:
        specs = ls.specs_for_ids(
            ["civitai:2334190@2625692", "civitai:545264@2763568"],
            extras_path=self.extras,
        )
        self.assertEqual(len(specs), 2)
        self.assertEqual(
            specs[0]["lora_name"],
            "https://civitai.com/api/download/models/2625692",
        )
        self.assertEqual(
            specs[1]["lora_name"],
            "https://civitai.com/api/download/models/2763568",
        )
        self.assertEqual(specs[1]["strength_model"], 0.8)

    def test_never_writes_real_extras(self) -> None:
        self.assertNotEqual(self.extras.resolve(), ls.EXTRAS_PATH.resolve())
        ls.add_lora("civitai:9@9", extras_path=self.extras)
        self.assertTrue(self.extras.is_file())

    def test_catalog_family_readable_without_extras(self) -> None:
        klein = ls.find_lora("civitai:2334190@2625692", self.extras)
        imp = ls.find_lora("civitai:545264@2763568", self.extras)
        ultra = ls.find_lora("civitai:796382@1026423", self.extras)
        assert klein is not None and imp is not None and ultra is not None
        self.assertEqual(ls.family_label(klein), "Flux.2 Klein")
        self.assertEqual(ls.family_label(imp), "Flux.2 Klein")
        self.assertEqual(ls.family_label(ultra), "Flux.1 Dev")
        self.assertTrue(ls.compatible_with_graph(klein, "klein"))
        self.assertFalse(ls.compatible_with_graph(klein, "flux1"))
        self.assertTrue(ls.compatible_with_graph(ultra, "flux1"))
        self.assertFalse(ls.compatible_with_graph(ultra, "klein"))
        self.assertEqual(ls.graph_label("klein"), ls.family_label(klein))
        self.assertEqual(ls.graph_label("flux1"), ls.family_label(ultra))
        self.assertEqual(ls.graph_id("Flux.2 Klein"), "klein")
        self.assertEqual(ls.graph_id("Flux.1 Dev"), "flux1")
        self.assertTrue(ls.compatible_with_graph(klein, "Flux.2 Klein"))
        self.assertFalse(ls.compatible_with_graph(ultra, "Flux.2 Klein"))
        self.assertTrue(ls.compatible_with_graph(ultra, "Flux.1 Dev"))
        self.assertIn("Flux.2 Klein", ls.GRAPH_CHOICES)
        self.assertIn("Flux.1 Dev", ls.GRAPH_CHOICES)

    def test_find_by_loader_name_civitai_url_and_filename(self) -> None:
        aged = ls.find_by_loader_name(
            "https://civitai.com/api/download/models/2795018", self.extras
        )
        assert aged is not None
        self.assertEqual(aged["id"], "civitai:1449678@2795018")
        with_tok = ls.find_by_loader_name(
            "https://civitai.com/api/download/models/2795018?token=nope",
            self.extras,
        )
        assert with_tok is not None
        self.assertEqual(with_tok["id"], aged["id"])
        baked = ls.find_by_loader_name("klein_slider_detail.safetensors", self.extras)
        assert baked is not None
        self.assertEqual(baked["id"], "civitai:2334190@2625692")
        pony = ls.find_lora("civitai:264290@720004", self.extras)
        assert pony is not None
        self.assertEqual(ls.family_label(pony), "Pony")
        self.assertFalse(ls.compatible_with_graph(pony, "klein"))
        self.assertFalse(ls.compatible_with_graph(pony, "flux1"))

    def test_add_and_edit_family_name_filename_strength(self) -> None:
        item = ls.add_lora(
            "civitai:111@222",
            extras_path=self.extras,
            name="scratch extra",
            filename="scratch.safetensors",
            strength_model=0.4,
            strength_clip=0.5,
            base="unknown",
        )
        self.assertEqual(item["base"], "")
        self.assertFalse(ls.compatible_with_graph(item, "klein"))
        self.assertFalse(ls.compatible_with_graph(item, "flux1"))
        edited = ls.edit_lora(
            "civitai:111@222",
            extras_path=self.extras,
            name="Flux extra",
            filename="flux_extra.safetensors",
            strength_model=0.65,
            strength_clip=0.7,
            base="Flux.1 Dev",
        )
        self.assertEqual(edited["name"], "Flux extra")
        self.assertEqual(edited["source"]["filename"], "flux_extra.safetensors")
        self.assertEqual(edited["strength_model"], 0.65)
        self.assertEqual(edited["strength_clip"], 0.7)
        self.assertEqual(edited["base"], "Flux.1 D")
        loaded = ls.find_lora("civitai:111@222", self.extras)
        assert loaded is not None
        self.assertEqual(loaded["name"], "Flux extra")
        self.assertEqual(loaded["source"]["filename"], "flux_extra.safetensors")
        self.assertEqual(loaded["strength_model"], 0.65)
        self.assertEqual(loaded["strength_clip"], 0.7)
        self.assertEqual(ls.family_of(loaded), "Flux.1 D")
        self.assertEqual(ls.family_label(loaded), "Flux.1 Dev")
        self.assertTrue(ls.compatible_with_graph(loaded, "flux1"))
        self.assertFalse(ls.compatible_with_graph(loaded, "klein"))
        disk = json.loads(self.extras.read_text(encoding="utf-8"))
        row = next(it for it in disk["items"] if it["id"] == "civitai:111@222")
        self.assertEqual(row["base"], "Flux.1 D")
        self.assertEqual(row["name"], "Flux extra")

    def test_edit_overlays_catalog_row(self) -> None:
        ls.edit_lora(
            "civitai:2334190@2625692",
            extras_path=self.extras,
            name="Detail (annotated)",
            base="Flux.2 Klein",
        )
        loaded = ls.find_lora("civitai:2334190@2625692", self.extras)
        assert loaded is not None
        self.assertEqual(loaded["name"], "Detail (annotated)")
        self.assertEqual(ls.family_label(loaded), "Flux.2 Klein")


class VerifyWeightRefs(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.extras = Path(self._td.name) / "studio-loras.json"

    def test_missing_civitai_version_is_not_verified_and_not_a_url(self) -> None:
        with patch.object(ls, "fetch_civitai_version", return_value=None):
            item = ls.add_lora("civitai:1@999001", extras_path=self.extras)
        self.assertFalse(item.get("verified"))
        name = ls.comfy_lora_name(item)
        self.assertFalse(name.startswith("http"), name)

    def test_civitai_api_hit_sets_verified_and_official_download(self) -> None:
        def fake(version_id, timeout=15):
            return {
                "id": int(version_id),
                "modelId": 2444547,
                "files": [
                    {
                        "name": "cass_aruhshuraanima_preview3_1-step00004500.safetensors",
                        "primary": True,
                        "downloadUrl": "https://civitai.com/api/download/models/2848936",
                    }
                ],
            }

        with patch.object(ls, "fetch_civitai_version", side_effect=fake):
            item = ls.add_lora(
                "https://civitai.com/api/download/models/2848936",
                extras_path=self.extras,
                filename="cass_aruhshuraanima_preview3_1-step00004500.safetensors",
            )
        self.assertTrue(item.get("verified"))
        self.assertIn("2848936", item["source"]["download"])
        self.assertTrue(ls.comfy_lora_name(item).startswith("https://"))

    def test_replica_safetensor_names_are_verified(self) -> None:
        names = ls.replica_weight_names()
        self.assertIn("flux-2-klein-9b-fp8.safetensors", names)
        self.assertIn("qwen_3_8b_fp8mixed.safetensors", names)
        self.assertIn("flux2-vae.safetensors", names)
        self.assertTrue(ls.verify_safetensor_ref("flux-2-klein-9b-fp8.safetensors"))
        self.assertTrue(ls.verify_safetensor_ref("flux2-vae.safetensors"))

    def test_unverified_payload_flags_unknown_lora_url(self) -> None:
        payload = {
            "prompt": {
                "70": {
                    "class_type": "UNETLoader",
                    "inputs": {"unet_name": "flux-2-klein-9b-fp8.safetensors"},
                },
                "80": {
                    "class_type": "LoraLoader",
                    "inputs": {
                        "lora_name": "https://civitai.com/api/download/models/1",
                    },
                },
            }
        }
        with patch.object(ls, "fetch_civitai_version", return_value=None):
            with patch.object(ls, "verify_http_url", return_value=False):
                bad = ls.unverified_payload_refs(payload, extras_path=self.extras)
        self.assertTrue(any("download/models/1" in u for u in bad), bad)
        self.assertFalse(any("flux-2-klein-9b-fp8" in u for u in bad), bad)

    def test_convert_skips_unverified_extra_without_search(self) -> None:
        from salad_studio import comfy_import as ci

        extras = self.extras
        extras.write_text(
            json.dumps(
                [
                    {
                        "id": "civitai:1@1",
                        "name": "ghost",
                        "kind": "lora",
                        "verified": False,
                        "source": {
                            "download": "https://civitai.com/api/download/models/1",
                            "filename": "ghost.safetensors",
                            "version_id": 1,
                        },
                    }
                ]
            ),
            encoding="utf-8",
        )
        with patch.object(ls, "fetch_civitai_version", return_value=None):
            specs, missing = ci.resolve_prompt_loras(
                [{"name": "ghost", "strength": 1}],
                extras_path=extras,
                search=False,
            )
        self.assertEqual(specs, [])
        self.assertEqual(missing, ["ghost"])

    def test_import_verifies_unverified_extra_instead_of_rejecting(self) -> None:
        from salad_studio import comfy_import as ci

        extras = self.extras
        extras.write_text(
            json.dumps(
                [
                    {
                        "id": "civitai:338702@1730326",
                        "name": "transparent-watercolor_IL_MIX",
                        "kind": "lora",
                        "verified": False,
                        "source": {
                            "host": "civitai",
                            "download": "https://civitai.com/api/download/models/1730326",
                            "filename": "transparent-watercolor_IL_MIX.safetensors",
                            "model_id": 338702,
                            "version_id": 1730326,
                        },
                    }
                ]
            ),
            encoding="utf-8",
        )

        def fake_version(version_id, timeout=15):
            return {
                "id": 1730326,
                "modelId": 338702,
                "files": [
                    {
                        "name": "transparent-watercolor_IL_MIX.safetensors",
                        "primary": True,
                        "downloadUrl": "https://civitai.com/api/download/models/1730326",
                    }
                ],
            }

        with patch.object(ls, "fetch_civitai_version", side_effect=fake_version):
            with patch.object(ls, "civitai_search_lora") as search:
                specs, missing = ci.resolve_prompt_loras(
                    [{"name": "transparent-watercolor_IL_MIX", "strength": 0.4}],
                    extras_path=extras,
                    search=False,
                )
                search.assert_not_called()
        self.assertEqual(missing, [])
        self.assertEqual(len(specs), 1)
        self.assertIn("1730326", specs[0]["lora_name"])
        self.assertTrue(specs[0].get("verified"))
        loaded = ls.find_lora("civitai:338702@1730326", extras)
        assert loaded is not None
        self.assertTrue(loaded.get("verified"))

    def test_verify_lora_and_unverified_batch(self) -> None:
        extras = self.extras
        ls.add_lora(
            "civitai:1@999001",
            extras_path=extras,
            verify=False,
            verified=False,
        )
        with patch.object(ls, "fetch_civitai_version", return_value=None):
            item = ls.verify_lora("civitai:1@999001", extras_path=extras)
            self.assertFalse(item.get("verified"))
            ok_n, fail_n, failed = ls.verify_unverified_loras(extras_path=extras)
        self.assertGreaterEqual(fail_n, 1)
        self.assertIn("civitai:1@999001", failed)

        def fake(version_id, timeout=15):
            vid = int(version_id)
            return {
                "id": vid,
                "modelId": 1,
                "files": [
                    {
                        "name": "ok.safetensors",
                        "primary": True,
                        "downloadUrl": f"https://civitai.com/api/download/models/{vid}",
                    }
                ],
            }

        with patch.object(ls, "fetch_civitai_version", side_effect=fake):
            item = ls.verify_lora("civitai:1@999001", extras_path=extras)
        self.assertTrue(item.get("verified"))
        self.assertTrue(ls.comfy_lora_name(item).startswith("https://"))

    def test_ensure_version_name_from_civitai_when_missing(self) -> None:
        item = {
            "id": "civitai:561940@2760251",
            "name": "PencilDrawEn01_CE_FLUX2_Klein9b_AIT4k",
            "kind": "lora",
            "verified": True,
            "source": {
                "download": "https://civitai.com/api/download/models/2760251",
                "filename": "PencilDrawEn01_CE_FLUX2_Klein9b_AIT4k.safetensors",
                "version_id": 2760251,
            },
        }
        ls.write_extra(item, self.extras)

        def fake(version_id, timeout=15):
            return {
                "id": 2760251,
                "name": "V01 - Flux.2 Klein 9b",
                "files": [{"name": "x.safetensors", "primary": True}],
            }

        with patch.object(ls, "fetch_civitai_version", side_effect=fake):
            filled = ls.ensure_civitai_version_name(item, extras_path=self.extras)
        self.assertEqual(ls.version_label(filled), "V01 - Flux.2 Klein 9b")
        self.assertEqual(ls.variation_label(filled), "V01")


class VariationLabel(unittest.TestCase):
    def test_short_tokens_from_civitai_version_names(self) -> None:
        self.assertEqual(ls.variation_label(version_name="V1"), "V1")
        self.assertEqual(ls.variation_label(version_name="Anime V3 Refined"), "V3")
        self.assertEqual(ls.variation_label(version_name="illustrious XL_v2.0"), "v2.0")
        self.assertEqual(ls.variation_label(version_name="Anima P3"), "P3")
        self.assertEqual(ls.variation_label(version_name="preview 3"), "P3")
        self.assertEqual(ls.variation_label(version_name="v5.0 [anima-preview-3]"), "v5.0")
        self.assertEqual(
            ls.variation_label(filename="Flux.2 Klein 9B Anime V3 Refined.safetensors"),
            "V3",
        )
        self.assertEqual(
            ls.variation_label(filename="transparent-watercolor_IL_MIX.safetensors"),
            "",
        )
        self.assertEqual(
            ls.variation_label(version_name="V01 - Flux.2 Klein 9b"),
            "V01",
        )

    def test_query_variants_include_pencil_draw(self) -> None:
        vars_ = ls._query_variants("PencilDrawEn01_CE_FLUX2_Klein9b_AIT4k.safetensors")
        joined = " ".join(vars_).lower()
        self.assertTrue(
            any("pencil draw" in v.lower() for v in vars_),
            vars_,
        )
        self.assertIn("pencildrawen01", joined)

    def test_query_variants_ce_trainer_filename(self) -> None:
        vars_ = ls._query_variants("Geometric01_CE_FLUX2_Klein9b_AIT5k")
        joined = " ".join(vars_).lower()
        self.assertIn("geometric01", joined)
        self.assertTrue(any(v.lower() in ("geometric", "geometric ce") for v in vars_), vars_)

    def test_query_variants_dark_atmospheric_ce_spaces_words(self) -> None:
        vars_ = ls._query_variants(
            "DarkAtmospheric01a_CE_FLUX2_Klein9b_AIT4k.safetensors"
        )
        self.assertTrue(
            any(v.lower() == "dark atmospheric" for v in vars_),
            vars_,
        )

    def test_hydrate_picks_klein_file_from_full_model(self) -> None:
        query = "Geometric01_CE_FLUX2_Klein9b_AIT5k"
        search_hit = {
            "id": 801170,
            "name": "Geometric - CE",
            "modelVersions": [
                {
                    "id": 2697046,
                    "name": "V01 - Z-Image",
                    "files": [{"name": "Geometric01_CE_ZIMG_AIT3k.safetensors"}],
                }
            ],
        }
        full = {
            "id": 801170,
            "name": "Geometric - CE",
            "modelVersions": [
                {
                    "id": 2697046,
                    "files": [{"name": "Geometric01_CE_ZIMG_AIT3k.safetensors"}],
                },
                {
                    "id": 2762669,
                    "name": "V01a - Flux.2 Klein 9b",
                    "files": [
                        {
                            "name": "Geometric01_CE_FLUX2_Klein9b_AIT5k.safetensors",
                            "downloadUrl": "https://civitai.com/api/download/models/2762669",
                        }
                    ],
                },
            ],
        }
        with patch.object(ls, "fetch_civitai_model", return_value=full):
            hydrated = ls._hydrate_model_versions(query, search_hit)
        hit = ls.best_civitai_hit(query, [hydrated])
        assert hit is not None
        self.assertEqual(hit["version_id"], 2762669)
        self.assertIn("Geometric01_CE_FLUX2_Klein9b_AIT5k", hit["filename"])


class CollapseDuplicates(unittest.TestCase):
    def test_same_version_and_same_visible_name_collapse(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            extras.write_text(
                json.dumps(
                    [
                        {
                            "id": "civitai:2848936@2848936",
                            "name": "cass_aruhshuraanima_preview3_1-step00004500",
                            "kind": "lora",
                            "base": "Flux.2 Klein 9B",
                            "status": "user",
                            "verified": False,
                            "source": {
                                "filename": "cass_aruhshuraanima_preview3_1-step00004500.safetensors",
                                "version_id": 2848936,
                                "download": "https://civitai.com/api/download/models/2848936",
                            },
                        },
                        {
                            "id": "civitai:2444547@2848936",
                            "name": "cass_aruhshuraanima_preview3_1-step00004500",
                            "kind": "lora",
                            "base": "Flux.2 Klein 9B",
                            "status": "user",
                            "verified": True,
                            "source": {
                                "filename": "cass_aruhshuraanima_preview3_1-step00004500.safetensors",
                                "version_id": 2848936,
                                "version_name": "preview 3",
                                "download": "https://civitai.com/api/download/models/2848936",
                            },
                        },
                        {
                            "id": "civitai:999695@1810929",
                            "name": "Ah! My Goddess_illustriousXL",
                            "kind": "lora",
                            "base": "Flux.2 Klein 9B",
                            "status": "user",
                            "verified": True,
                            "source": {
                                "filename": "Ah! My Goddess_illustriousXL.safetensors",
                                "version_id": 1810929,
                                "version_name": "v2.0",
                            },
                        },
                        {
                            "id": "civitai:999695@3131267",
                            "name": "Ah! My Goddess_illustriousXL",
                            "kind": "lora",
                            "base": "Flux.2 Klein 9B",
                            "status": "user",
                            "verified": True,
                            "source": {
                                "filename": "Ah! My Goddess_v3_illustriousXL.safetensors",
                                "version_id": 3131267,
                                "version_name": "v3.0",
                            },
                        },
                    ]
                ),
                encoding="utf-8",
            )
            rows = [
                r
                for r in ls.list_loras(extras)
                if "cass_aruhshuraanima" in str(r.get("name") or "")
                or "Goddess" in str(r.get("name") or "")
            ]
            cass = [r for r in rows if "cass" in str(r.get("name") or "")]
            goddess = [r for r in rows if "Goddess" in str(r.get("name") or "")]
            self.assertEqual(len(cass), 1, cass)
            self.assertEqual(cass[0]["id"], "civitai:2444547@2848936")
            self.assertEqual(ls.version_label(cass[0]), "preview 3")
            self.assertEqual(len(goddess), 1, goddess)
            self.assertEqual(goddess[0]["id"], "civitai:999695@1810929")
            self.assertIn("v2.0", ls.config_label(goddess[0]))


class ImageResources(unittest.TestCase):
    def test_merge_fills_empty_model_version_ids(self) -> None:
        item = {
            "id": 1,
            "width": 1344,
            "height": 1792,
            "modelVersionIds": [],
            "meta": {"meta": {"prompt": "x", "steps": 5}},
        }
        ls.merge_image_resources(
            item,
            [
                {
                    "modelType": "Checkpoint",
                    "modelName": "FLUX.2-klein-9b-fp8",
                    "modelVersionId": 2658598,
                },
                {
                    "modelType": "LORA",
                    "modelName": "Artificeal",
                    "modelVersionId": 3088444,
                    "versionName": "v1.0",
                },
            ],
        )
        self.assertEqual(item["modelVersionIds"], [2658598, 3088444])
        gen = ls.unwrap_image_generation(item)
        self.assertEqual(gen["Model"], "FLUX.2-klein-9b-fp8")
        self.assertEqual(gen["width"], 1344)
        loras = [r for r in gen["resources"] if r["type"] == "lora"]
        self.assertEqual(loras[0]["name"], "Artificeal")
        self.assertEqual(loras[0]["modelVersionId"], 3088444)
        hints = ls.lora_hints_from_generation(gen)
        self.assertEqual(hints["Artificeal"]["version_id"], 3088444)
        self.assertEqual(hints["Artificeal"]["version_name"], "v1.0")

    def test_civitai_resources_fill_hints_without_names(self) -> None:
        gen = {
            "prompt": "x",
            "resources": [],
            "civitaiResources": [
                {"type": "checkpoint", "modelVersionId": 2658598},
                {"type": "lora", "weight": 1.25, "modelVersionId": 2661123},
            ],
        }
        rows = ls.generation_resource_rows(gen)
        self.assertEqual(len(rows), 2)
        hints = ls.lora_hints_from_generation(gen)
        self.assertEqual(hints["2661123"]["version_id"], 2661123)
        self.assertNotIn("2658598", hints)

    def test_fetch_image_uses_trpc_when_v1_has_no_resources(self) -> None:
        v1 = {
            "items": [
                {
                    "id": 135440425,
                    "width": 1344,
                    "height": 1792,
                    "modelVersionIds": [],
                    "meta": {"meta": {"prompt": "Artificeal style artwork.", "steps": 5}},
                }
            ]
        }
        trpc = [
            {
                "modelType": "LORA",
                "modelName": "Artificeal",
                "modelVersionId": 3088444,
            }
        ]
        with patch.object(ls, "_civitai_json", return_value=v1), patch.object(
            ls, "fetch_civitai_generation_data", return_value=trpc
        ), patch.object(ls, "fetch_civitai_page_resources") as page:
            item = ls.fetch_civitai_image("135440425")
        page.assert_not_called()
        assert item is not None
        self.assertEqual(item["modelVersionIds"], [3088444])
        self.assertEqual(
            ls.unwrap_image_generation(item)["resources"][0]["name"],
            "Artificeal",
        )


if __name__ == "__main__":
    unittest.main()
