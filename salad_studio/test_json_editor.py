"""Prompt Editor JSON color-coding + verification (same parse Generate uses)."""
from __future__ import annotations

import ast
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

import json_highlight as jh  # noqa: E402
from generator import parse_request_json  # noqa: E402

APP = HERE / "app.py"
SAMPLE = '{"hello": "world", "n": 1, "prompt": {"w": 64}}'


def _kind_at(text: str, needle: str) -> str | None:
    pos = text.index(needle)
    for kind, start, end in jh.tokenize_json(text):
        if start <= pos < end:
            return kind
    return None


class JsonHighlight(unittest.TestCase):
    def test_token_kinds_distinct_for_key_string_number(self) -> None:
        spans = jh.tokenize_json(SAMPLE)
        kinds = {k for k, _s, _e in spans}
        self.assertIn("key", kinds)
        self.assertIn("string", kinds)
        self.assertIn("number", kinds)
        self.assertGreaterEqual(len(kinds), 2)
        self.assertEqual(_kind_at(SAMPLE, "hello"), "key")
        self.assertEqual(_kind_at(SAMPLE, "world"), "string")
        self.assertEqual(_kind_at(SAMPLE, "1"), "number")
        self.assertNotEqual(_kind_at(SAMPLE, "hello"), _kind_at(SAMPLE, "world"))
        colors = jh.TOKEN_COLORS
        self.assertNotEqual(colors["key"], colors["string"])
        self.assertNotEqual(colors["key"], colors["number"])
        self.assertNotEqual(colors["string"], colors["number"])

    def test_verify_uses_parse_request_json(self) -> None:
        ok, msg = jh.verify_request_json('{"prompt": {}}')
        self.assertTrue(ok, msg)
        self.assertEqual(msg, "JSON valid")
        parsed = parse_request_json('{"prompt": {}}')
        self.assertEqual(parsed["prompt"], {})

        ok, msg = jh.verify_request_json("not-json")
        self.assertFalse(ok)
        self.assertIn("JSON", msg)

        ok, msg = jh.verify_request_json("{}")
        self.assertFalse(ok)
        self.assertIn("prompt", msg.lower())

        with self.assertRaises(json.JSONDecodeError):
            parse_request_json("not-json")
        with self.assertRaises(ValueError):
            parse_request_json("{}")
        self.assertEqual(parse_request_json('{"prompt": {}}')["prompt"], {})

        with patch.object(jh, "parse_request_json", wraps=jh.parse_request_json) as wrapped:
            jh.verify_request_json('{"prompt": {}}')
            wrapped.assert_called()
            jh.verify_request_json("{}")
            self.assertGreaterEqual(wrapped.call_count, 2)


class SourceWiresChrome(unittest.TestCase):
    def test_editor_applies_highlight_and_parse(self) -> None:
        src = APP.read_text(encoding="utf-8")
        self.assertIn("json_highlight.apply_to_text", src)
        self.assertIn("json_highlight.verify_request_json", src)
        self.assertIn("_apply_json_chrome", src)
        self.assertIn("parse_request_json", src)
        self.assertIn("Validate", src)
        self.assertIn("_validate_editor", src)
        tree = ast.parse(src)
        apply_calls_highlight = False
        apply_calls_verify = False
        sync_calls_chrome = False
        generate_calls_parse = False
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name != "SaladStudio":
                continue
            for item in node.body:
                if not isinstance(item, ast.FunctionDef):
                    continue
                names = [
                    n.attr
                    for n in ast.walk(item)
                    if isinstance(n, ast.Attribute)
                ]
                if item.name == "_apply_json_chrome":
                    apply_calls_highlight = "apply_to_text" in names
                    apply_calls_verify = "verify_request_json" in names
                if item.name == "_sync_editor":
                    sync_calls_chrome = "_apply_json_chrome" in names
                if item.name == "_on_generate":
                    generate_calls_parse = "parse_request_json" in names
        self.assertTrue(apply_calls_highlight)
        self.assertTrue(apply_calls_verify)
        self.assertTrue(sync_calls_chrome)
        self.assertTrue(generate_calls_parse)


try:
    import tkinter as tk
except ImportError as _tk_err:
    tk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = _tk_err
else:
    _TK_IMPORT_ERROR = None


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class LiveJsonEditor(unittest.TestCase):
    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        tmp = Path(self._td.name)
        from salad_studio.app import SaladStudio
        from salad_studio import lora_store, profiles

        profiles.PROFILES_PATH = tmp / "studio-profiles.json"
        lora_store.EXTRAS_PATH = tmp / "studio-loras.json"
        self.app = SaladStudio(show=False)
        self.app.withdraw()
        self.app.update_idletasks()
        self.addCleanup(self.app.destroy)

    def test_rebuilt_editor_has_multiple_token_colors(self) -> None:
        widget = self.app.editor_text
        raw = widget.get("1.0", "end-1c")
        self.assertIn("prompt", raw)
        tags = [t for t in widget.tag_names() if str(t).startswith("json_")]
        self.assertGreaterEqual(len(tags), 2, tags)
        fgs = {str(widget.tag_cget(t, "foreground")).lower() for t in tags}
        fgs.discard("")
        self.assertGreater(len(fgs), 1, fgs)
        key_fg = str(widget.tag_cget("json_key", "foreground")).lower()
        str_fg = str(widget.tag_cget("json_string", "foreground")).lower()
        self.assertTrue(key_fg)
        self.assertTrue(str_fg)
        self.assertNotEqual(key_fg, str_fg)
        self.assertEqual(self.app.json_status.get(), "JSON valid")

    def test_live_verification_invalid_then_valid(self) -> None:
        app = self.app
        widget = app.editor_text
        widget.delete("1.0", "end")
        widget.insert("1.0", "not-json")
        app._apply_json_chrome()
        app.update_idletasks()
        self.assertNotEqual(app.json_status.get(), "JSON valid")
        self.assertIn("JSON", app.json_status.get())
        ok, _msg = jh.verify_request_json(widget.get("1.0", "end-1c").strip())
        self.assertFalse(ok)

        widget.delete("1.0", "end")
        widget.insert("1.0", '{"prompt": {}}')
        app._apply_json_chrome()
        app.update_idletasks()
        self.assertEqual(app.json_status.get(), "JSON valid")
        ok, _msg = jh.verify_request_json(widget.get("1.0", "end-1c").strip())
        self.assertTrue(ok)

        widget.delete("1.0", "end")
        widget.insert("1.0", "{}")
        app._apply_json_chrome()
        app.update_idletasks()
        self.assertNotEqual(app.json_status.get(), "JSON valid")
        self.assertIn("prompt", app.json_status.get().lower())

    def test_validate_button_accepts_valid_and_rejects_invalid(self) -> None:
        app = self.app
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", '{"prompt": {}}')
        self.assertTrue(app._validate_editor(popup=False))
        self.assertIn("JSON valid", app.json_status.get())
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", "not-json")
        self.assertFalse(app._validate_editor(popup=False))
        self.assertNotEqual(app.json_status.get(), "JSON valid")


if __name__ == "__main__":
    unittest.main()
