"""Prompt Editor JSON color-coding + verification (same parse Generate uses)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PKG = TOOLS / "salad_studio"
for p in (str(TOOLS), str(PKG)):
    if p not in sys.path:
        sys.path.insert(0, p)

import json_highlight as jh  # noqa: E402
from generator import parse_request_json  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
