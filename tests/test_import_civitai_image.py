"""The Import tab converts Civitai image 125073040 through the shipped path.

The Civitai fetch is served from the recorded fixture, so this drives the real
Fetch and Convert handlers with no network call.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "salad_studio"
for _p in (PKG, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio import comfy_import  # noqa: E402
from tests.test_launch import _TempPaths  # noqa: E402

FIXTURE = HERE / "civitai_fixtures" / "image_125073040.json"
FIXTURES = HERE / "civitai_fixtures"


def _redirect_convert_off_the_network(case: unittest.TestCase) -> None:
    """Serve the fixture from the lora_store Convert actually calls.

    ``comfy_import`` binds top-level ``lora_store`` as ``ls``. That object is
    not ``salad_studio.lora_store``, so a patch on the package copy never
    lands. ``ls.EXTRAS_PATH`` is also the user's file unless it moves: Convert
    writes each resolved LoRA there.
    """
    ls = comfy_import.ls
    search = mock.patch.object(ls, "civitai_search_lora", return_value=None)
    search.start()
    case.addCleanup(search.stop)
    fetch = mock.patch.object(
        ls, "fetch_civitai_image", return_value=case.fixture["image"]
    )
    fetch.start()
    case.addCleanup(fetch.stop)
    saved = ls.EXTRAS_PATH
    ls.EXTRAS_PATH = case.tmp / "studio-loras.json"
    case.addCleanup(setattr, ls, "EXTRAS_PATH", saved)


class ImportTabLoraManagerImage(unittest.TestCase):
    """Image 123550044: Import, Fetch, Convert, then Generate POSTs a clean copy."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import tokens as studio_tokens
        from salad_studio.pages.import_page import ImportPage
        from tests._flet_host import Host

        self.fixture = json.loads(
            (FIXTURES / "image_123550044.json").read_text(encoding="utf-8")
        )
        self.host = Host()
        self.host.load_profiles()
        self.page = ImportPage(self.host)
        self.host.store_page("Import", self.page)
        studio_tokens.write_token("salad", "lora-manager-key")
        studio_tokens.write_token("civitai", "lora-manager-civitai-token")
        _redirect_convert_off_the_network(self)

    def _fetch_and_convert(self) -> None:
        self.page.url.value = self.fixture["source"]
        self.page.fetch_civitai()
        self.page.convert()

    def test_generate_posts_a_copy_with_no_pack_types_and_the_prompt(self) -> None:
        from salad_studio import flet_services, generator

        self._fetch_and_convert()
        self.assertEqual(self.host.dialogs, [], "the import must not raise a dialog")
        editor = self.host.pages["Prompt Editor"]
        payload = generator.parse_request_json(editor.text())
        captured: dict = {}

        def _req(url, key=None, data=None, timeout=30):
            if str(url).endswith("/ready"):
                return 200, b"ok"
            captured["url"] = str(url)
            captured["body"] = json.loads(data.decode("utf-8")) if data else {}
            return 200, json.dumps({"images": ["QUJD"]}).encode()

        target = self.host.form.profile(self.host.stored_profile())
        with tempfile.TemporaryDirectory() as out_td, mock.patch.object(
            generator.salad_gen, "_req", side_effect=_req
        ), mock.patch.object(flet_services, "OUT_DIR", Path(out_td)):
            generator.generate_from_payload(gateway=target.gateway,
                                            key=self.host.services.salad_key(),
                                            payload=payload, out_dir=Path(out_td),
                                            line=target.name, checksum=f"checksum-{id(self)}")
        self.assertEqual(self.host.dialogs, [], "Generate must not raise a dialog")
        self.assertTrue(captured.get("body"), "Generate never POSTed")
        self.assertEqual(captured["url"], f"{target.gateway.rstrip('/')}/prompt")
        posted = captured["body"]["prompt"]
        classes = sorted(
            {str(node.get("class_type")) for node in posted.values() if isinstance(node, dict)}
        )
        self.assertEqual([c for c in classes if "LoraManager" in c], [])
        self.assertEqual([c for c in classes if c in comfy_import.SALAD_MISSING_TYPES], [])
        ids = set(posted)
        for nid, node in posted.items():
            for key, value in (node.get("inputs") or {}).items():
                edge = comfy_import._edge(value)
                if edge:
                    with self.subTest(node=nid, input=key):
                        self.assertIn(edge[0], ids, f"#{nid}.{key} -> missing #{edge[0]}")
        texts = [
            node["inputs"].get("text")
            for node in posted.values()
            if node.get("class_type") == "CLIPTextEncode"
        ]
        expected = str(
            comfy_import.parse_civitai_metadata(self.fixture["metadata"]).get("prompt") or ""
        ).strip()
        self.assertIn(expected, texts)


class ImportTabCivitaiImage(unittest.TestCase):
    """Image 125073040: Fetch from the fixture, Convert onto the Prompt Editor."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio.pages.import_page import ImportPage
        from tests._flet_host import Host

        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.host = Host()
        self.host.load_profiles()
        self.page = ImportPage(self.host)
        self.host.store_page("Import", self.page)
        _redirect_convert_off_the_network(self)

    def _fetch(self) -> None:
        """Press Fetch from Civitai, served from the fixture."""
        self.page.url.value = self.fixture["source"]
        self.page.fetch_civitai()

    def _convert(self) -> None:
        """Press Convert to Prompt Editor on whatever the page holds."""
        self.page.convert()

    def test_the_import_produces_a_runnable_klein_request(self) -> None:
        self._fetch()
        self._convert()
        self.assertEqual(self.host.dialogs, [], "the import must not raise a dialog")
        note = self.host.notes[-1][1]
        self.assertIn("after import", note, f"the page must report the import: {note!r}")
        self.assertIn("added UNETLoader", note)
        payload = json.loads(self.host.pages["Prompt Editor"].text())
        prompt = payload["prompt"]
        classes = [node.get("class_type") for node in prompt.values()]

        texts = [
            node["inputs"].get("text")
            for node in prompt.values()
            if node.get("class_type") == "CLIPTextEncode"
        ]
        self.assertIn("realistic, 将画面变为真实的照片", texts)
        loras = [
            node["inputs"].get("lora_name")
            for node in prompt.values()
            if node.get("class_type") == "LoraLoader"
        ]
        self.assertEqual(len(loras), 2, f"both LoRAs must be loaders: {loras}")
        for name in loras:
            self.assertTrue(
                str(name or "").lower().startswith(("http://", "https://")),
                f"a loader kept a local filename: {name!r}",
            )
        self.assertIn("SamplerCustomAdvanced", classes)
        self.assertNotIn("SeedVR2VideoUpscaler", classes)
        self.assertIn("imported Civitai paste",
                      " ".join(line for _level, line in self.host.services.log_lines))

    def test_the_fetched_paste_is_the_upscaler_workflow(self) -> None:
        """The paste is real; it is the route that changed."""
        self._fetch()
        stash = self.page.workflow_text()
        obj = comfy_import._parse_json_blob(stash)
        self.assertGreater(comfy_import.comfy_node_count(obj), 0, "the paste carries nodes")
        self.assertFalse(
            comfy_import.graph_can_sample(obj),
            "this workflow has no sampler, no diffusion loader and no text encode",
        )
        self.assertIn("SeedVR2VideoUpscaler", stash)
        self.assertIn("realistic", self.page.meta.value)


if __name__ == "__main__":
    unittest.main()
