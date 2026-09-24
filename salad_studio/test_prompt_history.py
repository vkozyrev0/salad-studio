"""Prompt History persistence and reuse."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for p in (str(TOOLS), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from salad_studio import prompt_history as ph  # noqa: E402


class PromptHistoryStore(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self._old = ph.HISTORY_PATH
        self._old_thumbs = ph.THUMBS_DIR
        ph.HISTORY_PATH = Path(self._td.name) / "studio-prompt-history.json"
        ph.THUMBS_DIR = Path(self._td.name) / "thumbs"
        self.addCleanup(lambda: setattr(ph, "HISTORY_PATH", self._old))
        self.addCleanup(lambda: setattr(ph, "THUMBS_DIR", self._old_thumbs))

    def test_add_list_skip_duplicate_remove(self) -> None:
        self.assertEqual(ph.list_prompts(), [])
        self.assertIsNone(ph.add_prompt("  "))
        a = ph.add_prompt("first prompt")
        assert a is not None
        self.assertEqual(ph.add_prompt("first prompt"), a)
        ph.add_prompt("second prompt")
        rows = ph.list_prompts()
        self.assertEqual([r["text"] for r in rows], ["second prompt", "first prompt"])
        ph.remove_at(0)
        self.assertEqual([r["text"] for r in ph.list_prompts()], ["first prompt"])
        self.assertTrue(ph.HISTORY_PATH.is_file())

    def test_preview(self) -> None:
        self.assertEqual(ph.preview("a\nb  c"), "a b c")

    def test_add_request_stores_json_and_skips_duplicate(self) -> None:
        body = {
            "prompt": {
                "74": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "stallion on a hillside", "clip": ["71", 0]},
                },
                "115": {
                    "class_type": "LoraLoader",
                    "inputs": {
                        "lora_name": "https://civitai.com/api/download/models/2795018?token=SECRET",
                        "strength_model": 0.5,
                        "strength_clip": 0.5,
                    },
                },
                "89": {
                    "class_type": "EmptyFlux2LatentImage",
                    "inputs": {"width": 1024, "height": 768, "batch_size": 1},
                },
                "85": {
                    "class_type": "BasicScheduler",
                    "inputs": {
                        "scheduler": "simple",
                        "steps": 40,
                        "denoise": 1,
                    },
                },
                "86": {
                    "class_type": "CFGGuider",
                    "inputs": {"cfg": 5},
                },
                "84": {
                    "class_type": "KSamplerSelect",
                    "inputs": {"sampler_name": "euler"},
                },
            }
        }
        a = ph.add_request(body)
        assert a is not None
        self.assertEqual(a["text"], "stallion on a hillside")
        lora = a["request"]["prompt"]["115"]["inputs"]["lora_name"]
        self.assertNotIn("SECRET", lora)
        self.assertIn("2795018", lora)
        again = ph.add_request(body)
        assert again is not None
        self.assertEqual(again["ts"], a["ts"])
        self.assertEqual(again["request"], a["request"])
        self.assertEqual(len(ph.list_prompts()), 1)
        stats = ph.request_stats(a["request"])
        self.assertIn("6 nodes", stats)
        self.assertIn("1 LoRA", stats)
        self.assertIn("civitai:2795018@0.5", stats)
        self.assertIn("1024×768", stats)
        self.assertIn("40 steps", stats)
        self.assertIn("cfg 5", stats)
        self.assertIn("euler", stats)
        self.assertIn("simple", stats)
        # Same prompt, different graph → new row
        body2 = json.loads(json.dumps(body))
        body2["prompt"]["86"]["inputs"]["cfg"] = 1
        b = ph.add_request(body2)
        assert b is not None
        self.assertIsNot(b, a)
        self.assertEqual([r["text"] for r in ph.list_prompts()], [
            "stallion on a hillside",
            "stallion on a hillside",
        ])

    def test_legacy_text_only_still_loads(self) -> None:
        ph.HISTORY_PATH.write_text(
            json.dumps([{"text": "old prompt", "ts": 1}]) + "\n",
            encoding="utf-8",
        )
        rows = ph.list_prompts()
        self.assertEqual(rows[0]["text"], "old prompt")
        self.assertNotIn("request", rows[0])
        self.assertEqual(ph.request_stats(None), "")

    def test_attach_image_writes_thumb_on_newest_row(self) -> None:
        from PIL import Image

        body = {
            "prompt": {
                "74": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "a tree at dusk", "clip": ["71", 0]},
                }
            }
        }
        entry = ph.add_request(body)
        assert entry is not None
        src = Path(self._td.name) / "plate.jpg"
        Image.new("RGB", (200, 120), (200, 80, 40)).save(src, "JPEG")
        thumb = ph.attach_image(src)
        assert thumb is not None
        self.assertTrue(thumb.is_file())
        self.assertEqual(thumb.parent, ph.THUMBS_DIR)
        with Image.open(thumb) as im:
            self.assertEqual(im.size, ph.THUMB_SIZE)
        rows = ph.list_prompts()
        self.assertEqual(rows[0]["image"], str(thumb))
        n = ph.clear_thumbs()
        self.assertGreaterEqual(n, 1)
        self.assertFalse(thumb.is_file())
        self.assertEqual(ph.list_prompts()[0].get("image") or "", "")
        ph.remove_at(0)
        self.assertFalse(thumb.is_file())


try:
    import tkinter as tk
except ImportError as _tk_err:
    tk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = _tk_err
else:
    _TK_IMPORT_ERROR = None


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class LivePromptHistory(unittest.TestCase):
    def test_reuse_fills_prompt_tab(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            raise unittest.SkipTest(f"Tk cannot initialize: {e}") from e
        from salad_studio.app import SaladStudio
        from salad_studio import lora_store, profiles, tokens as tok

        old_h = ph.HISTORY_PATH
        old_local = tok.LOCAL_PATH
        old_cfg = tok.CONFIG_HOME
        old_prof = profiles.PROFILES_PATH
        old_extras = lora_store.EXTRAS_PATH
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ph.HISTORY_PATH = tmp / "hist.json"
            tok.LOCAL_PATH = tmp / "studio-tokens.json"
            tok.CONFIG_HOME = tmp / "defaults"
            profiles.PROFILES_PATH = tmp / "studio-profiles.json"
            lora_store.EXTRAS_PATH = tmp / "studio-loras.json"
            try:
                ph.add_prompt("Aged art. Oil painting style.")
                app = SaladStudio(show=False)
                app.withdraw()
                try:
                    app.update_idletasks()
                    tabs = [app.nb.tab(t, "text") for t in app.nb.tabs()]
                    from salad_studio import app as app_mod

                    self.assertEqual(tabs, list(app_mod.TAB_ORDER))
                    self.assertLess(
                        tabs.index("Prompt Editor"), tabs.index("Prompt Catalog")
                    )
                    self.assertLess(
                        tabs.index("Prompt Catalog"), tabs.index("Prompt History")
                    )
                    kids = app.prompt_hist_tree.get_children()
                    self.assertTrue(kids)
                    # The row is text-only: no "request" key, so reuse takes the
                    # plain-text branch.
                    rows = ph.list_prompts()
                    self.assertEqual(rows[0]["text"], "Aged art. Oil painting style.")
                    self.assertNotIn("request", rows[0])
                    app.prompt_hist_tree.selection_set(kids[0])
                    app._reuse_prompt_history()
                    self.assertIn(
                        "Aged art. Oil painting style.",
                        app.prompt_text.get("1.0", "end"),
                    )
                    # ... and lands on the Prompt Editor tab, where the prompt
                    # boxes live (there is no separate "Prompt" tab).
                    self.assertEqual(
                        app.nb.tab(app.nb.select(), "text"), "Prompt Editor"
                    )
                finally:
                    app.destroy()
            finally:
                ph.HISTORY_PATH = old_h
                tok.LOCAL_PATH = old_local
                tok.CONFIG_HOME = old_cfg
                profiles.PROFILES_PATH = old_prof
                lora_store.EXTRAS_PATH = old_extras

    def test_reuse_restores_request_json(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            raise unittest.SkipTest(f"Tk cannot initialize: {e}") from e
        from salad_studio.app import SaladStudio
        from salad_studio import lora_store, profiles, tokens as tok

        old_h = ph.HISTORY_PATH
        old_local = tok.LOCAL_PATH
        old_cfg = tok.CONFIG_HOME
        old_prof = profiles.PROFILES_PATH
        old_extras = lora_store.EXTRAS_PATH
        body = {
            "prompt": {
                "74": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "history oil stallion", "clip": ["71", 0]},
                },
                "70": {
                    "class_type": "UNETLoader",
                    "inputs": {
                        "unet_name": "flux-2-klein-base-9b-fp8.safetensors",
                        "weight_dtype": "default",
                    },
                },
            },
            "convert_output": {"format": "jpeg"},
        }
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ph.HISTORY_PATH = tmp / "hist.json"
            tok.LOCAL_PATH = tmp / "studio-tokens.json"
            tok.CONFIG_HOME = tmp / "defaults"
            profiles.PROFILES_PATH = tmp / "studio-profiles.json"
            lora_store.EXTRAS_PATH = tmp / "studio-loras.json"
            try:
                ph.add_request(body)
                app = SaladStudio(show=False)
                app.withdraw()
                try:
                    app.update_idletasks()
                    kids = app.prompt_hist_tree.get_children()
                    self.assertTrue(kids)
                    vals = app.prompt_hist_tree.item(kids[0], "values")
                    # Column order is ("when", "profile", "preview", "stats")
                    # (app._build_prompt_history_tab / _refresh_prompt_history),
                    # so values[1] is the profile and values[2] the prompt preview.
                    self.assertEqual(vals[1], "")
                    self.assertIn("history oil stallion", vals[2])
                    app.prompt_hist_tree.selection_set(kids[0])
                    app._reuse_prompt_history()
                    editor = app.editor_text.get("1.0", "end")
                    self.assertIn("history oil stallion", editor)
                    self.assertIn("CLIPTextEncode", editor)
                    self.assertIn(
                        "history oil stallion",
                        app.prompt_text.get("1.0", "end"),
                    )
                finally:
                    app.destroy()
            finally:
                ph.HISTORY_PATH = old_h
                tok.LOCAL_PATH = old_local
                tok.CONFIG_HOME = old_cfg
                profiles.PROFILES_PATH = old_prof
                lora_store.EXTRAS_PATH = old_extras


if __name__ == "__main__":
    unittest.main()
