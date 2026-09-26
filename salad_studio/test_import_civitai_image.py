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
for _p in (HERE, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio import comfy_import, lora_store  # noqa: E402
from salad_studio.test_launch import _TempPaths  # noqa: E402

try:
    import tkinter as tk
except ImportError as _tk_err:
    tk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = _tk_err
else:
    _TK_IMPORT_ERROR = None

FIXTURE = HERE / "civitai_fixtures" / "image_125073040.json"


FIXTURES = HERE / "civitai_fixtures"


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class ImportTabLoraManagerImage(unittest.TestCase):
    """Image 123550044: Import → Convert → Generate POSTs a clean copy."""

    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.fixture = json.loads(
            (FIXTURES / "image_123550044.json").read_text(encoding="utf-8")
        )
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.app.update_idletasks()

    def _fetch_and_convert(self) -> None:
        app = self.app
        app._goto_tab("Import")
        app.var_imp_image_url.set(self.fixture["source"])
        with mock.patch.object(
            lora_store, "fetch_civitai_image", return_value=self.fixture["image"]
        ):
            app._on_fetch_civitai_image()
        app.update_idletasks()
        app._on_import_civitai()
        app.update_idletasks()

    def test_generate_posts_a_copy_with_no_pack_types_and_the_prompt(self) -> None:
        app = self.app
        errors: list[str] = []
        with mock.patch.object(
            self.app_mod.messagebox, "showerror", lambda *a, **k: errors.append(str(a))
        ):
            self._fetch_and_convert()
        self.assertEqual(errors, [], "the import must not raise a dialog")

        tokens = self.app_mod.tokens
        tokens.write_token("salad", "lora-manager-key")
        tokens.write_token("civitai", "lora-manager-civitai-token")
        captured: dict = {}
        plate = "QUJD"
        outcome: list[BaseException] = []

        def _req(url, key=None, data=None, timeout=30):
            if str(url).endswith("/ready"):
                return 200, b"ok"
            captured["url"] = str(url)
            captured["body"] = json.loads(data.decode("utf-8")) if data else {}
            return 200, json.dumps({"images": [plate]}).encode()

        with tempfile.TemporaryDirectory() as out_td, mock.patch.object(
            self.app_mod.generator.salad_gen, "_req", side_effect=_req
        ), mock.patch.object(self.app_mod, "OUT_DIR", Path(out_td)), mock.patch.object(
            self.app_mod.messagebox, "showerror", lambda *a, **k: errors.append(str(a))
        ):
            app.gen_queue = self.app_mod.salad_queue.SaladQueue(
                on_log=app._on_queue_log, sleep=lambda _s: None
            )
            app.var_gateway.set(self.app_mod.profiles.load_all()["klein"].gateway)
            app.var_salad_status.set("Ready")

            def body() -> None:
                try:
                    app._on_generate()
                    deadline = time.time() + 30
                    while time.time() < deadline and not captured:
                        app.update()
                        time.sleep(0.02)
                except BaseException as exc:  # noqa: BLE001 - re-raised below
                    outcome.append(exc)
                finally:
                    app.quit()

            app.after(0, body)
            app.mainloop()
        if outcome:
            raise outcome[0]

        self.assertEqual(errors, [], "Generate must not raise a dialog")
        self.assertTrue(captured.get("body"), "Generate never POSTed")
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


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class ImportTabCivitaiImage(unittest.TestCase):
    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.app.update_idletasks()

    def _fetch(self) -> None:
        """Press Fetch from Civitai, served from the fixture."""
        app = self.app
        app._goto_tab("Import")
        app.var_imp_image_url.set(self.fixture["source"])
        with mock.patch.object(
            lora_store, "fetch_civitai_image", return_value=self.fixture["image"]
        ):
            app._on_fetch_civitai_image()
        app.update_idletasks()

    def _convert(self) -> None:
        """Press Convert to Prompt Editor on whatever the page holds."""
        self.app._on_import_civitai()
        self.app.update_idletasks()

    def test_the_import_produces_a_runnable_klein_request(self) -> None:
        app = self.app
        errors: list[str] = []
        with mock.patch.object(
            self.app_mod.messagebox, "showerror", lambda *a, **k: errors.append(str(a))
        ):
            self._fetch()
            self._convert()

        self.assertEqual(errors, [], "the import must not raise a dialog")
        status = app.status.get()
        self.assertIn("after import", status, f"the page must report the import: {status!r}")
        self.assertIn("added UNETLoader", status)
        payload = json.loads(app.editor_text.get("1.0", "end"))
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
        self.assertIn("SamplerCustomAdvanced", classes)
        self.assertNotIn("SeedVR2VideoUpscaler", classes)
        self.assertIn("imported Civitai paste", app.log_text.get("1.0", "end"))

    def test_the_fetched_paste_is_the_upscaler_workflow(self) -> None:
        """The paste is real; it is the route that changed."""
        self._fetch()
        stash = self.app._import_workflow_text()
        obj = comfy_import._parse_json_blob(stash)
        self.assertGreater(comfy_import.comfy_node_count(obj), 0, "the paste carries nodes")
        self.assertFalse(
            comfy_import.graph_can_sample(obj),
            "this workflow has no sampler, no diffusion loader and no text encode",
        )
        self.assertIn("SeedVR2VideoUpscaler", stash)
        self.assertIn("realistic", self.app.import_meta.get("1.0", "end"))


if __name__ == "__main__":
    unittest.main()
