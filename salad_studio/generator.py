"""Salad Studio image generator wrapping salad_gen / klein_payload."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent
for p in (_HERE, _TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import salad_gen  # noqa: E402
from request_json import (  # noqa: E402
    authorize_civitai_urls,
    build_request,
    civitai_lora_urls,
    lora_url_label,
    payload_has_civitai_download,
)
from studio_log import (  # noqa: E402
    explain_http,
    prompt_url,
    ready_url,
    summarize_payload,
)

_RETRY_CODES = (502, 503, 504, 521, 522, 523, 524)
# One attempt: no client-side retry loop. A 524 means Cloudflare gave up at 100 s
# but the container is still running the job, so a retry submits a *duplicate*
# rather than resuming. Each attempt costs up to _PROMPT_TIMEOUT_S and piles more
# onto the replica's queue. Clicking Generate again is faster and clearer. (2026-09-22)
_RETRY_TRIES = 1
_RETRY_SLEEP_S = 8
_PROMPT_TIMEOUT_S = 180
_READY_TRIES = 8
_READY_SLEEP_S = 8
_READY_TIMEOUT_S = 20
# LoRA URL pre-flight: one quick HEAD per URL, before the render is POSTed.
_LORA_CHECK_TIMEOUT_S = 20
# Definitive "this URL is not usable" answers. Anything else (timeout, 5xx) is
# reported and the render proceeds. The replica may reach a host we cannot.
_LORA_GONE_CODES = (401, 403, 404, 410)
# A reachability probe's success codes. 206 is the normal answer to the ranged
# GET below when the CDN honours `Range`. Civitai's does, so a plain 200 test
# called every live LoRA "unconfirmed". (2026-09-22)
_LORA_OK_CODES = (200, 206)


def read_key(key_path: str) -> str:
    return Path(key_path).read_text(encoding="utf-8").strip()


def _body_snippet(body: bytes | str, n: int = 200) -> str:
    if isinstance(body, (bytes, bytearray)):
        return body[:n].decode("utf-8", "replace")
    return str(body)[:n]


def wait_gateway_ready(
    gateway: str,
    key: str,
    *,
    on_log: Any | None = None,
) -> None:
    """GET /ready until 200. 404 means no probe endpoint. Continue to /prompt."""
    def _log(level: str, message: str) -> None:
        if on_log is not None:
            on_log(level, message)

    url = ready_url(gateway)
    last_code = 0
    last_body: bytes | str = b""
    for attempt in range(_READY_TRIES):
        _log("http", f"GET {url}  probe {attempt + 1}/{_READY_TRIES}")
        last_code, last_body = salad_gen._req(url, key, timeout=_READY_TIMEOUT_S)
        if last_code == 200:
            _log("ok", f"GET {url} HTTP 200, replica ready")
            return
        msg = explain_http(int(last_code), last_body, url, method="GET")
        if last_code == 404:
            _log("warn", "GET /ready HTTP 404, no probe endpoint; will POST /prompt")
            return
        if last_code in _RETRY_CODES and attempt + 1 < _READY_TRIES:
            _log("warn", msg + f"  retry in {_READY_SLEEP_S}s")
            salad_gen.time.sleep(_READY_SLEEP_S)
            continue
        if last_code not in _RETRY_CODES:
            _log("warn", msg + "  will POST /prompt anyway")
            return
        _log("error", msg)
        raise RuntimeError(msg + "  (pre-probe /ready failed)")
    msg = explain_http(int(last_code), last_body, url, method="GET")
    _log("error", msg)
    raise RuntimeError(msg + "  (pre-probe /ready failed)")


def first_image_b64(data: Any) -> str | None:
    """Salad wrapper uses ``images[]``; native Comfy uses history outputs."""
    if not isinstance(data, dict):
        return None
    imgs = data.get("images")
    if isinstance(imgs, list) and imgs:
        raw = imgs[0]
        if isinstance(raw, str) and raw:
            return raw
        if isinstance(raw, dict) and raw.get("filename"):
            return None
    outputs = data.get("outputs")
    if isinstance(outputs, dict):
        for node in outputs.values():
            if not isinstance(node, dict):
                continue
            for img in node.get("images") or []:
                if isinstance(img, str) and img:
                    return img
    return None


def wait_history_image(
    gateway: str,
    key: str,
    prompt_id: str,
    *,
    on_log: Any | None = None,
    tries: int = 24,
    sleep_s: int = 8,
) -> str | None:
    """Poll Comfy ``/history/{id}`` when POST /prompt only returned a prompt_id."""
    def _log(level: str, message: str) -> None:
        if on_log is not None:
            on_log(level, message)

    base = (gateway or "").rstrip("/")
    url = f"{base}/history/{prompt_id}"
    for attempt in range(tries):
        _log("http", f"GET {url}  {attempt + 1}/{tries}")
        code, body = salad_gen._req(url, key, timeout=30)
        if code != 200:
            _log("warn", f"GET {url} HTTP {code}")
            salad_gen.time.sleep(sleep_s)
            continue
        try:
            data = json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            salad_gen.time.sleep(sleep_s)
            continue
        entry = data.get(prompt_id) if isinstance(data, dict) else None
        blob = entry if isinstance(entry, dict) else data
        raw = first_image_b64(blob if isinstance(blob, dict) else {})
        if raw:
            return raw
        if isinstance(blob, dict):
            st = blob.get("status") if isinstance(blob.get("status"), dict) else {}
            if st.get("status_str") == "error" or st.get("completed") is False and st.get("status_str"):
                _log("error", f"history status {st}")
                return None
        salad_gen.time.sleep(sleep_s)
    return None


def parse_request_json(text: str) -> dict[str, Any]:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("request JSON must be an object")
    if "prompt" not in data:
        raise ValueError("request JSON missing 'prompt'")
    return data


def _probe_url(url: str, opener: Any | None = None) -> tuple[int, str]:
    """HEAD a LoRA URL, falling back to a one-byte ranged GET. 0 = inconclusive.

    Never leaks the URL: callers log ``lora_url_label`` instead, because the URL
    carries ``?token=``.
    """
    send = opener or urllib.request.urlopen
    for method, extra in (("HEAD", {}), ("GET", {"Range": "bytes=0-0"})):
        headers = {"User-Agent": salad_gen.UA, "accept": "*/*", **extra}
        try:
            req = urllib.request.Request(url, headers=headers, method=method)
            with send(req, timeout=_LORA_CHECK_TIMEOUT_S) as resp:
                return int(resp.status), method
        except urllib.error.HTTPError as exc:
            code = int(exc.code)
            exc.close()  # release the response; we only wanted the status
            # Some CDNs refuse HEAD outright. Civitai's does, with a Cloudflare
            # 403 (error 1010), while a GET of the same URL returns 200. 403 is
            # therefore only definitive *after* a GET has also said so, otherwise
            # a live LoRA would be reported dead and the render refused.
            if method == "HEAD" and code in (400, 403, 405, 501):
                continue
            return code, method
        except Exception as exc:  # noqa: BLE001, any transport failure is inconclusive
            return 0, type(exc).__name__
    return 0, "no probe worked"



def check_lora_urls(
    prompt: dict[str, Any],
    *,
    on_log: Any | None = None,
    opener: Any | None = None,
) -> list[str]:
    """Confirm the graph's Civitai LoRA URLs resolve, before the render is POSTed.

    Nothing is downloaded. The replica loads each LoRA from its URL when the
    Comfy graph runs. The point is only to catch a wrong or expired URL while it
    is still cheap: otherwise a dead URL surfaces as an opaque HTTP 524 after the
    GPU has been asked to do the work.

    Raises on a **definitive** answer (gone or denied), so the failure names the
    LoRA. A timeout, a 5xx or any transport error is reported and the render
    proceeds. Returns the URLs that could not be confirmed.
    """
    def _log(level: str, message: str) -> None:
        if on_log is not None:
            on_log(level, message)

    urls = civitai_lora_urls(prompt)
    if not urls:
        return []

    _log("info", f"checking {len(urls)} LoRA URL(s)")
    unconfirmed: list[str] = []
    dead: list[str] = []
    for url in urls:
        label = lora_url_label(url)
        code, note = _probe_url(url, opener)
        if code in _LORA_OK_CODES:
            _log("ok", f"LoRA {label} OK")
            continue
        if code in _LORA_GONE_CODES:
            _log("error", f"LoRA {label} HTTP {code}. The URL is wrong or expired")
            dead.append(label)
            continue
        _log("warn", f"LoRA {label} unconfirmed ({note or code}), rendering anyway")
        unconfirmed.append(url)
    if dead:
        raise RuntimeError(
            "Civitai LoRA URL does not resolve: "
            + ", ".join(dead)
            + "  (fix the LoRA reference, or drop the node)"
        )
    return unconfirmed


def generate_from_payload(
    *,
    gateway: str,
    key: str,
    payload: dict[str, Any] | str,
    out_dir: Path,
    on_log: Any | None = None,
) -> Path:
    """POST the Prompt Editor JSON to Salad ``/prompt`` and write a JPEG."""
    def _log(level: str, message: str) -> None:
        if on_log is not None:
            on_log(level, message)

    if isinstance(payload, str):
        body_obj = parse_request_json(payload)
    else:
        body_obj = payload
    if payload_has_civitai_download(body_obj):
        try:
            from salad_studio import tokens as tok
        except ImportError:
            import tokens as tok  # type: ignore[no-redef]
        civ = tok.read_token("civitai")
        if not civ:
            raise RuntimeError(
                "Civitai LoRA download needs a token (HTTP 401). "
                "Save the Civitai token on the Tokens tab, then Generate again."
            )
        body_obj = authorize_civitai_urls(body_obj, civ)
        _log("info", "Attached Civitai token to LoRA download URL(s) (redacted in logs).")
    if isinstance(body_obj.get("prompt"), dict):
        from salad_studio import comfy_import as ci

        safe = ci.prompt_for_salad_replica(body_obj["prompt"])
        if safe != body_obj["prompt"]:
            body_obj = dict(body_obj)
            body_obj["prompt"] = safe
            _log(
                "info",
                "Salad POST omits replica-missing node types "
                "(editor graph unchanged).",
            )
    wait_gateway_ready(gateway, key, on_log=_log)
    if isinstance(body_obj.get("prompt"), dict):
        # Check the URLs on the compat-stripped prompt: never probe a LoRA the
        # replica will not be asked for. Nothing is downloaded here. The replica
        # fetches each LoRA itself when the Comfy graph runs, using the ?token=
        # that authorize_civitai_urls put on the node's lora_name.
        check_lora_urls(body_obj["prompt"], on_log=_log)
    blob = salad_gen.json.dumps(body_obj).encode()
    url = prompt_url(gateway)
    _log("http", f"POST {url}  {len(blob)} bytes  {summarize_payload(body_obj)}")
    code = 0
    body: bytes | str = b""
    for attempt in range(_RETRY_TRIES):
        _log("http", f"attempt {attempt + 1}/{_RETRY_TRIES}  timeout={_PROMPT_TIMEOUT_S}s")
        code, body = salad_gen._req(url, key, data=blob, timeout=_PROMPT_TIMEOUT_S)
        if code == 200:
            _log("ok", f"HTTP 200 from {url}")
            break
        msg = explain_http(int(code), body, url)
        if code in _RETRY_CODES:
            # Do not advertise (or take) a backoff sleep there is no room for.
            if attempt + 1 < _RETRY_TRIES:
                _log("warn", msg + f"  retry in {_RETRY_SLEEP_S}s")
                salad_gen.time.sleep(_RETRY_SLEEP_S)
            continue
        _log("error", msg)
        raise RuntimeError(msg)
    else:
        msg = explain_http(int(code), body, url)
        _log("error", msg)
        raise RuntimeError(msg)

    try:
        data = salad_gen.json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        msg = explain_http(int(code), body, url) + "  (response is not JSON)"
        _log("error", msg)
        raise RuntimeError(msg) from None
    _log("debug", f"/prompt keys={list(data)[:16] if isinstance(data, dict) else type(data)}")
    raw = first_image_b64(data)
    if not raw and isinstance(data, dict) and data.get("prompt_id"):
        pid = str(data.get("prompt_id"))
        errs = data.get("node_errors") or {}
        if errs:
            msg = f"Comfy node_errors for {pid}: {json.dumps(errs)[:800]}"
            _log("error", msg)
            raise RuntimeError(msg)
        _log("info", f"Comfy queued prompt_id={pid}; polling /history (wrapper returned no images[])")
        raw = wait_history_image(gateway, key, pid, on_log=_log)
    if not raw:
        keys = list(data)[:16] if isinstance(data, dict) else type(data)
        msg = (
            explain_http(int(code), body, url)
            + f"  (no images in response; keys={keys})"
        )
        _log("error", msg)
        raise RuntimeError(msg)
    if isinstance(raw, str) and raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    unixms = int(time.time() * 1000)
    out = out_dir / f"studio_{unixms}.jpg"
    out.write_bytes(salad_gen.base64.b64decode(raw))
    _log("ok", f"wrote {out}  {out.stat().st_size} bytes")
    return out


def generate(
    *,
    gateway: str,
    key: str,
    prompt_text: str,
    graph: str,
    width: int,
    height: int,
    steps: int,
    use_loras: bool,
    out_dir: Path,
    seed: int | None = None,
    selected_loras: list[str] | None = None,
    extras_path: Path | None = None,
    payload: dict[str, Any] | str | None = None,
) -> Path:
    if payload is not None:
        return generate_from_payload(
            gateway=gateway, key=key, payload=payload, out_dir=out_dir
        )
    if seed is None:
        seed = salad_gen.random.randint(1, 2**48)
    if selected_loras is None:
        from lora_store import DEFAULT_KLEIN_LORA_IDS

        selected = list(DEFAULT_KLEIN_LORA_IDS) if use_loras else []
    else:
        selected = list(selected_loras)
    body_obj = build_request(
        prompt_text=prompt_text,
        graph=graph,
        width=width,
        height=height,
        steps=steps,
        seed=seed,
        selected_ids=selected,
        extras_path=extras_path,
    )
    return generate_from_payload(
        gateway=gateway, key=key, payload=body_obj, out_dir=out_dir
    )


def list_history(out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    files = list(out_dir.glob("studio_*.jpg"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def clear_history(out_dir: Path) -> int:
    """Delete ``studio_*.jpg`` plates in ``out_dir``. Returns how many files went."""
    n = 0
    for path in list_history(out_dir):
        try:
            path.unlink()
            n += 1
        except OSError:
            continue
    return n
