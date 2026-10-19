"""Prompt Editor rules that the Flet page calls, with no widget in sight.

The editor shows the request JSON as text and the graph beside it. Both need
the same answers to a few questions: what is the prompt object inside this
text, which nodes are the positive and negative text encodes, and what happens
to the text when a Swap moves a card. Those answers live here so the page only
wires them to controls.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import salad_studio.comfy_import as comfy_import
import salad_studio.graph_view as graph_view
import salad_studio.generator as generator
import salad_studio.request_json as request_json

DEFAULT_POSITIVE = "ArsMJStyle, Impressionism, cream paper, no signature, no watermark\n"


@dataclass(frozen=True)
class EditorJson:
    """The editor text read once: the payload, the prompt inside it, and why it failed."""

    text: str
    payload: dict[str, Any] | None
    prompt: dict[str, Any]
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.payload is not None and not self.error


def parse(text: str) -> EditorJson:
    raw = (text or "").strip()
    if not raw:
        return EditorJson(text, None, {}, "the editor is empty")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return EditorJson(text, None, {}, f"JSON invalid at line {exc.lineno}: {exc.msg}")
    if not isinstance(payload, dict):
        return EditorJson(text, payload, {}, "the JSON is not an object")
    prompt = payload.get("prompt")
    if not isinstance(prompt, dict):
        return EditorJson(text, payload, {}, "the JSON has no prompt object")
    return EditorJson(text, payload, prompt)


def empty_payload() -> dict[str, Any]:
    return {"prompt": {}, "convert_output": dict(comfy_import.CONVERT_OUTPUT)}


def with_prompt(payload: dict[str, Any] | None, prompt: dict[str, Any]) -> dict[str, Any]:
    """The payload with a new prompt, weight refs stamped. Invalid text keeps its shapes."""
    base = dict(payload) if isinstance(payload, dict) else empty_payload()
    base["prompt"] = prompt
    request_json.stamp_weight_refs(base)
    return base


def dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def text_encodes(prompt: dict[str, Any]) -> tuple[str, str]:
    """(positive id, negative id). The roles are the graph's, not the key order's."""
    positive = negative = ""
    for nid, node in prompt.items():
        if not isinstance(node, dict) or str(node.get("class_type")) != "CLIPTextEncode":
            continue
        role = graph_view._clip_role(str(nid), prompt)
        if role == 0 and not positive:
            positive = str(nid)
        elif role == 1 and not negative:
            negative = str(nid)
    return positive, negative


def prompt_texts(prompt: dict[str, Any]) -> tuple[str, str]:
    positive, negative = text_encodes(prompt)
    def read(nid: str) -> str:
        node = prompt.get(nid) if nid else None
        return str((node or {}).get("inputs", {}).get("text", "")) if isinstance(node, dict) else ""
    return read(positive), read(negative)


def patch_text(prompt: dict[str, Any], which: str, text: str) -> dict[str, Any]:
    """A copy of the prompt with one CLIP text encode's text replaced. ``which`` is pos or neg."""
    nid = text_encodes(prompt)[0 if which == "pos" else 1]
    if not nid:
        return prompt
    out = json.loads(json.dumps(prompt))
    inputs = out[nid].setdefault("inputs", {})
    inputs["text"] = text
    return out


def swap_text(prompt: dict[str, Any], a: str, b: str) -> dict[str, Any]:
    """Swap two same-class nodes' inputs and meta. Raises ValueError with the reason."""
    return graph_view.swap_payloads(prompt, a, b)


def validate(text: str) -> tuple[bool, str]:
    """The same gate Generate uses, plus the graph checks. (ok, message)."""
    try:
        generator.parse_request_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        return False, str(exc)
    return True, "JSON valid"
