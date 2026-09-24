"""Color-coded Salad Studio log lines. Never include raw secrets."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable
from urllib.parse import parse_qsl, urlparse, urlunparse

import request_json as rj

LogFn = Callable[[str, str], None]

# Distinct from JSON-editor token colors; same dark well.
LEVEL_COLORS: dict[str, str] = {
    "debug": "#8A9AAB",
    "info": "#E8DCC8",
    "ok": "#8FBF9A",
    "warn": "#E0A04A",
    "error": "#D48A9A",
    "http": "#7EB8D4",
}

_HTTP_HINTS: dict[int, str] = {
    401: "Unauthorized (Salad-Api-Key or Civitai token).",
    400: "Salad rejected the graph (node/model/download).",
    404: "Gateway path not found. Check Config gateway URL ends at the replica, then /prompt is appended.",
    502: "Bad gateway, replica or Cloudflare proxy glitch.",
    503: "Salad replica unavailable.",
    504: "Gateway timeout.",
    520: "Cloudflare 520: Comfy origin returned an empty or invalid response (process crash or restart mid-job, often while downloading a Civitai LoRA). Not a bad graph JSON. Wait for GET /ready 200; do not re-POST until then.",
    521: "Cloudflare 521: origin (Salad Comfy) is down or still starting, not a malformed request URL.",
    522: "Cloudflare 522: TCP to origin timed out, replica unreachable or still booting, not a bad request URL.",
    523: "Cloudflare 523: origin unreachable.",
    524: "Cloudflare 524: origin timed out (job too long or replica asleep).",
}


def redact(text: str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    out = text
    for secret in secrets:
        s = (secret or "").strip()
        if len(s) >= 4:
            out = out.replace(s, "…")
    out = re.sub(r"([?&]token=)[^&\s\"']+", r"\1…", out, flags=re.I)
    return out


def strip_url_secrets(url: str) -> str:
    parts = urlparse(url)
    q = [(k, "…" if k.lower() == "token" else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    query = "&".join(f"{k}={v}" for k, v in q)
    return urlunparse(parts._replace(query=query))


def gateway_base(gateway: str) -> str:
    return (gateway or "").strip().rstrip("/")


def prompt_url(gateway: str) -> str:
    base = gateway_base(gateway)
    if not base:
        return "(empty gateway)/prompt"
    return base + "/prompt"


def ready_url(gateway: str) -> str:
    base = gateway_base(gateway)
    if not base:
        return "(empty gateway)/ready"
    return base + "/ready"


def format_line(level: str, message: str) -> str:
    ts = datetime.now().astimezone().strftime("%H:%M:%S")
    tag = (level or "info").upper()
    return f"[{ts} {tag}] {message}"


def explain_http(
    code: int,
    body: bytes | str,
    request_url: str,
    *,
    method: str = "POST",
) -> str:
    """Human error for popups/logs. Request URL is first; Cloudflare docs URLs are not."""
    snippet = _snippet(body)
    title, detail = _problem_title_detail(snippet)
    hint = _HTTP_HINTS.get(int(code), "")
    shown = strip_url_secrets(request_url)
    parts = [f"{method} {shown}", f"HTTP {code}"]
    if hint:
        parts.append(hint)
    if title:
        parts.append(title)
    if detail and detail not in (title, hint):
        parts.append(detail)
    return ", ".join(parts)


def _snippet(body: bytes | str, n: int = 1200) -> str:
    if isinstance(body, (bytes, bytearray)):
        return body[:n].decode("utf-8", "replace")
    return str(body)[:n]


def _problem_title_detail(snippet: str) -> tuple[str, str]:
    data: Any = None
    try:
        data = json.loads(snippet)
    except (json.JSONDecodeError, TypeError):
        data = None
    title = ""
    detail = ""
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            title = str(err.get("type") or err.get("message") or "")
            detail = str(err.get("message") or err.get("details") or "")
        else:
            title = str(data.get("title") or data.get("error") or "")
            detail = str(data.get("detail") or data.get("message") or "")
        node_errors = data.get("node_errors")
        if node_errors:
            extra = json.dumps(node_errors, default=str)
            detail = f"{detail} {extra}".strip() if detail else extra
    else:
        tm = re.search(r'"title"\s*:\s*"((?:\\.|[^"\\])*)"', snippet)
        dm = re.search(r'"detail"\s*:\s*"((?:\\.|[^"\\])*)', snippet)
        title = tm.group(1) if tm else ""
        detail = dm.group(1) if dm else ""
        if not title and not detail and not snippet.lstrip().startswith("{"):
            detail = snippet.strip()
    title, detail = title.strip(), detail.strip()
    if "developers.cloudflare.com" in detail:
        detail = ""
    return title, detail


def summarize_payload(body: dict[str, Any]) -> str:
    prompt = body.get("prompt") if isinstance(body, dict) else None
    if not isinstance(prompt, dict):
        return "payload has no prompt"
    n = len(prompt)
    loras = []
    for _node, name in rj.lora_name_inputs(prompt):
        loras.append(strip_url_secrets(name) if name.startswith("http") else name)
    bits = [f"{n} nodes"]
    if loras:
        bits.append("loras: " + ", ".join(loras))
    return "; ".join(bits)
