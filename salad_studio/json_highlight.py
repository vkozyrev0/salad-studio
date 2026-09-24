#!/usr/bin/env python3
"""Prompt Editor JSON token colors + request-JSON verification.

Color spans and the valid/invalid result are pure functions over a string so
tests can call them without a window. Verification is ``parse_request_json``
, the same gate Generate uses.
"""
from __future__ import annotations

import json
import re
from typing import Any

try:
    from salad_studio.generator import parse_request_json
except ImportError:  # sibling import when run from salad_studio
    from generator import parse_request_json

# Distinct token colors on the dark editor well. Tests compare kinds/tags,
# not copies of these hex values.
TOKEN_COLORS: dict[str, str] = {
    "key": "#7EB8D4",
    "string": "#C5D89A",
    "number": "#E0A04A",
    "literal": "#D48A9A",
    "punct": "#8A9AAB",
}

_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_LITERAL = re.compile(r"(?:true|false|null)")
_PUNCT = re.compile(r"[{}\[\]:,]")
_SPACE = re.compile(r"\s+")

Span = tuple[str, int, int]


def tokenize_json(text: str) -> list[Span]:
    """Return (kind, start, end) spans. ``key`` vs ``string`` are distinct kinds."""
    spans: list[Span] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            m = _SPACE.match(text, i)
            i = m.end() if m else i + 1
            continue
        if _PUNCT.match(text, i):
            spans.append(("punct", i, i + 1))
            i += 1
            continue
        if ch == '"':
            m = _STRING.match(text, i)
            if not m:
                spans.append(("string", i, i + 1))
                i += 1
                continue
            start, end = m.start(), m.end()
            j = end
            while j < n and text[j].isspace():
                j += 1
            kind = "key" if j < n and text[j] == ":" else "string"
            spans.append((kind, start, end))
            i = end
            continue
        if ch == "-" or ch.isdigit():
            m = _NUMBER.match(text, i)
            if m:
                spans.append(("number", m.start(), m.end()))
                i = m.end()
                continue
        lit = _LITERAL.match(text, i)
        if lit:
            spans.append(("literal", lit.start(), lit.end()))
            i = lit.end()
            continue
        i += 1
    return spans


def token_kinds(text: str) -> set[str]:
    return {kind for kind, _s, _e in tokenize_json(text)}


def verify_request_json(text: str) -> tuple[bool, str]:
    """Same parse Generate uses. ``(ok, readable reason)``."""
    try:
        parse_request_json(text)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e.msg}"
    except ValueError as e:
        return False, str(e)
    return True, "JSON valid"


def apply_to_text(widget: Any) -> list[Span]:
    """Paint token tags on a ``tk.Text``. Returns the spans that were applied."""
    text = widget.get("1.0", "end-1c")
    for kind, color in TOKEN_COLORS.items():
        tag = f"json_{kind}"
        widget.tag_configure(tag, foreground=color)
        widget.tag_remove(tag, "1.0", "end")
    spans = tokenize_json(text)
    for kind, start, end in spans:
        if end <= start:
            continue
        widget.tag_add(f"json_{kind}", f"1.0+{start}c", f"1.0+{end}c")
    try:
        widget.tag_raise("sel")
    except Exception:
        pass
    return spans
