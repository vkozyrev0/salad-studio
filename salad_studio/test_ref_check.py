"""Prompt Assist: resolving the request's LoRAs / checkpoints for the AI.

The online lookup is faked at the boundary, so the shipped resolver runs for
real: local catalog first, online only on a local miss, and unresolvable names
kept as ``unresolved`` instead of dropped.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for p in (str(TOOLS), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from salad_studio import lora_store as ls  # noqa: E402
from salad_studio import ref_check as rc  # noqa: E402
from salad_studio import request_json as rj  # noqa: E402

KLEIN_DETAIL = "civitai:2334190@2625692"


def _body(*, unet: str = "flux-2-klein-base-9b-fp8.safetensors", lora: str | None = None) -> dict:
    body = rj.build_request(
        prompt_text="a stallion in a winter field",
        negative_text="blurry",
        graph="klein",
        width=1024,
        height=1024,
        steps=20,
        seed=7,
        cfg=1,
        selected_ids=[KLEIN_DETAIL],
    )
    if lora is not None:
        body["prompt"]["80"]["inputs"]["lora_name"] = lora
    body["prompt"]["70"]["inputs"]["unet_name"] = unet
    return body


class CollectRefs(unittest.TestCase):
    def test_collects_every_weight_in_node_order(self) -> None:
        refs = rc.collect_refs(_body())
        kinds = [(r["node"], r["kind"]) for r in refs]
        self.assertEqual(
            kinds,
            [("70", "checkpoint"), ("71", "clip"), ("72", "vae"), ("80", "lora")],
        )
        self.assertEqual(refs[0]["field"], "unet_name")
        self.assertEqual(refs[-1]["field"], "lora_name")

    def test_collects_a_checkpoint_loader_and_skips_other_nodes(self) -> None:
        body = {
            "prompt": {
                "4": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "some_model.safetensors"},
                },
                "9": {"class_type": "SaveImage", "inputs": {"images": ["4", 0]}},
            }
        }
        refs = rc.collect_refs(body)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["kind"], "checkpoint")
        self.assertEqual(refs[0]["name"], "some_model.safetensors")

    def test_non_request_inputs_are_safe(self) -> None:
        self.assertEqual(rc.collect_refs(None), [])
        self.assertEqual(rc.collect_refs({}), [])
        self.assertEqual(rc.collect_refs({"prompt": "nope"}), [])


class LocalResolution(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self._old = ls.EXTRAS_PATH
        ls.EXTRAS_PATH = Path(self._td.name) / "studio-loras.json"
        self.addCleanup(lambda: setattr(ls, "EXTRAS_PATH", self._old))

    def test_catalog_lora_resolves_without_any_network_call(self) -> None:
        calls: list[tuple[str, str]] = []

        def lookup(name, kind):
            calls.append((name, kind))
            return None

        findings = rc.resolve_refs(_body(), lookup=lookup)
        self.assertEqual(calls, [], "a catalog LoRA must not go online")
        lora = next(f for f in findings if f["kind"] == "lora")
        self.assertEqual(lora["status"], "resolved")
        self.assertEqual(lora["source"], "catalog")
        self.assertEqual(lora["model_name"], "Klein Detail Slider")
        self.assertEqual(lora["family"], "Flux.2 Klein")
        self.assertTrue(lora["compatible"])
        self.assertFalse(lora["checked_online"])

    def test_replica_files_resolve_from_disk_knowledge(self) -> None:
        findings = rc.resolve_refs(_body(), lookup=lambda n, k: None)
        by_kind = {f["kind"]: f for f in findings}
        self.assertEqual(by_kind["checkpoint"]["status"], "resolved")
        self.assertEqual(by_kind["checkpoint"]["family"], "Flux.2 Klein")
        self.assertEqual(by_kind["clip"]["status"], "resolved")
        self.assertEqual(by_kind["vae"]["status"], "resolved")

    def test_local_miss_triggers_one_online_lookup_and_keeps_the_finding(self) -> None:
        calls: list[tuple[str, str]] = []

        def lookup(name, kind):
            calls.append((name, kind))
            return {
                "source": "civitai-model",
                "model_name": "Online Only LoRA",
                "version_name": "v3",
                "base": "Flux.2 Klein 9B",
                "filename": "online_only.safetensors",
                "url": "https://civitai.com/models/9?modelVersionId=99",
            }

        findings = rc.resolve_refs(
            _body(lora="https://civitai.com/api/download/models/9999999"), lookup=lookup
        )
        self.assertEqual(calls, [("https://civitai.com/api/download/models/9999999", "lora")])
        lora = next(f for f in findings if f["kind"] == "lora")
        self.assertEqual(lora["status"], "resolved")
        self.assertEqual(lora["source"], "civitai-model")
        self.assertEqual(lora["model_name"], "Online Only LoRA")
        self.assertEqual(lora["family"], "Flux.2 Klein")
        self.assertTrue(lora["checked_online"])

    def test_unresolvable_name_is_reported_not_dropped(self) -> None:
        body = _body(lora="totally_unknown_lora_v9.safetensors")
        findings = rc.resolve_refs(body, lookup=lambda n, k: None)
        lora = next(f for f in findings if f["kind"] == "lora")
        self.assertEqual(lora["status"], "unresolved")
        self.assertEqual(lora["name"], "totally_unknown_lora_v9.safetensors")
        self.assertTrue(lora["checked_online"])
        self.assertEqual(lora["family"], "")
        self.assertEqual([f["name"] for f in rc.unresolved(findings)], [lora["name"]])
        text = rc.format_findings(findings)
        self.assertIn("UNRESOLVED", text)
        self.assertIn("checked online", text)

    def test_family_heuristic_flags_an_incompatible_checkpoint(self) -> None:
        findings = rc.resolve_refs(
            _body(unet="krea2_ultra_bf16.safetensors"), lookup=lambda n, k: None
        )
        ckpt = next(f for f in findings if f["kind"] == "checkpoint")
        self.assertEqual(ckpt["family"], "Krea 2")
        self.assertIs(ckpt["compatible"], False)

    def test_unrecognised_filename_gets_no_family_rather_than_a_guess(self) -> None:
        """The heuristic only knows klein / krea / qwen names; it must not invent."""
        findings = rc.resolve_refs(
            _body(unet="some_obscure_model_bf16.safetensors"), lookup=lambda n, k: None
        )
        ckpt = next(f for f in findings if f["kind"] == "checkpoint")
        self.assertEqual(ckpt["family"], "")
        self.assertIsNone(ckpt["compatible"])

    def test_incompatible_catalog_lora_is_flagged(self) -> None:
        body = _body(lora="https://civitai.com/api/download/models/720004")
        findings = rc.resolve_refs(body, lookup=lambda n, k: None)
        lora = next(f for f in findings if f["kind"] == "lora")
        self.assertEqual(lora["status"], "resolved")
        self.assertEqual(lora["family"], "Pony")
        self.assertIs(lora["compatible"], False)

    def test_lookup_failure_does_not_break_resolution(self) -> None:
        def boom(name, kind):
            raise OSError("network down")

        findings = rc.resolve_refs(_body(lora="mystery.safetensors"), lookup=boom)
        lora = next(f for f in findings if f["kind"] == "lora")
        self.assertEqual(lora["status"], "unresolved")


class OnlineLookup(unittest.TestCase):
    def test_download_url_uses_the_civitai_version_api(self) -> None:
        seen: list[str] = []

        def fake_version(vid, timeout=15):
            seen.append(f"version:{vid}")
            return {
                "id": vid,
                "modelId": 42,
                "name": "Klein 9B",
                "baseModel": "Flux.2 Klein 9B",
                "files": [{"name": "klein.safetensors"}],
            }

        with mock.patch.object(ls, "fetch_civitai_version", side_effect=fake_version):
            hit = rc.online_lookup(
                "https://civitai.com/api/download/models/2625692?fileId=1", "lora"
            )
        self.assertEqual(seen, ["version:2625692"])
        assert hit is not None
        self.assertEqual(hit["source"], "civitai-version")
        self.assertEqual(hit["version_name"], "Klein 9B")
        self.assertEqual(hit["base"], "Flux.2 Klein 9B")
        self.assertEqual(hit["filename"], "klein.safetensors")

    def test_bare_name_searches_civitai_by_stem(self) -> None:
        urls: list[str] = []

        def fake_get(url, timeout):
            urls.append(url)
            return {
                "items": [
                    {
                        "id": 7,
                        "name": "Some Style",
                        "modelVersions": [
                            {
                                "id": 70,
                                "name": "v2",
                                "baseModel": "Flux.2 Klein 9B",
                                "files": [{"name": "some_style_v2.safetensors"}],
                            }
                        ],
                    }
                ]
            }

        with mock.patch.object(rc, "_civitai_get", side_effect=fake_get):
            hit = rc.online_lookup("some_style_v2.safetensors", "lora")
        self.assertEqual(len(urls), 1)
        self.assertIn("civitai.com/api/v1/models", urls[0])
        self.assertIn("query=some_style_v2", urls[0])
        self.assertIn("types=LORA", urls[0])
        assert hit is not None
        self.assertEqual(hit["model_name"], "Some Style")
        self.assertEqual(hit["version_name"], "v2")

    def test_checkpoint_search_asks_for_checkpoint_types(self) -> None:
        urls: list[str] = []

        def fake_get(url, timeout):
            urls.append(url)
            return {"items": []}

        with mock.patch.object(rc, "_civitai_get", side_effect=fake_get):
            hit = rc.online_lookup("mystery_model.safetensors", "checkpoint")
        self.assertIsNone(hit)
        self.assertIn("types=Checkpoint", urls[0])

    def test_transport_failure_reads_as_a_miss(self) -> None:
        with mock.patch.object(rc, "_civitai_get", return_value=None):
            self.assertIsNone(rc.online_lookup("whatever.safetensors", "lora"))
        self.assertIsNone(rc.online_lookup("", "lora"))


class FindingFormat(unittest.TestCase):
    def test_format_reports_every_entry(self) -> None:
        body = _body(lora="mystery.safetensors")
        findings = rc.resolve_refs(body, lookup=lambda n, k: None)
        text = rc.format_findings(findings)
        for f in findings:
            self.assertIn(str(f["node"]), text)
        self.assertIn("flux-2-klein-base-9b-fp8.safetensors", text)
        self.assertIn("family=Flux.2 Klein", text)
        self.assertIn("mystery.safetensors", text)
        self.assertIn("UNRESOLVED", text)

    def test_format_names_the_catalog_row_for_a_resolved_lora(self) -> None:
        findings = rc.resolve_refs(_body(), lookup=lambda n, k: None)
        text = rc.format_findings(findings)
        self.assertIn("Klein Detail Slider", text)
        self.assertIn("compatible with the replica", text)
        self.assertIn("source=catalog", text)

    def test_empty_request_says_so(self) -> None:
        self.assertIn("no LoRA", rc.format_findings([]))

    def test_json_round_trips_through_the_report(self) -> None:
        body = _body()
        findings = rc.resolve_refs(body, lookup=lambda n, k: None)
        self.assertEqual(json.loads(json.dumps(findings)), findings)


if __name__ == "__main__":
    unittest.main()
