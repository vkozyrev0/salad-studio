"""Vast.ai picture generation: the control call, the instance store, the POST.

Picture generation can run on Salad container groups or on vast.ai instances the
user rents. This module is the vast half: it lists the account's instances with
the Bearer token (``tokens.read_token("vast")``), derives the HTTP endpoint
ComfyUI on an instance answers on, keeps the instances the user selected in
``~/.config/salad/studio-vast.json``, and POSTs a Comfy prompt to one of them.

Nothing here writes a token anywhere: the key stays in the gitignored token
store, and the instance list holds addresses, which are not secrets. The HTTP
transport is injected the way ``salad_status`` and ``salad_queue`` do it, so a
test drives a real request through a recorded sender instead of the network.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

VAST_API = "https://console.vast.ai/api/v1"
INSTANCES_URL = f"{VAST_API}/instances/"
# The v0 path answers 410 "deprecated_endpoint" (measured 2026-10-13), so this is
# the only list endpoint this client may use; test_vast pins the version.
# A page holds 25 instances, the API's own cap, so a bigger account is read in
# a few requests rather than truncated.
MAX_PAGES = 4
# The container ports a ComfyUI template publishes, most likely first: the
# vast.ai ComfyUI template serves 8188 (some images 18188), and the Salad images
# run Comfy on 3000. A request has to reach the host port the instance maps to
# one of these, which is why the endpoint is derived from the instance record
# rather than typed in.
COMFY_PORTS: tuple[int, ...] = (8188, 18188, 3000)
# Never a ComfyUI port: ssh is mapped by every template, so it cannot be the one
# a render should reach.
SSH_PORTS: tuple[int, ...] = (22, 2222)
INSTANCES_PATH = Path.home() / ".config" / "salad" / "studio-vast.json"
DOC_VERSION = 1
TIMEOUT_S = 45
UA = "SaladStudio/1.0"

MODE_SALAD = "salad"
MODE_VAST = "vast"
MODES: tuple[str, str] = (MODE_SALAD, MODE_VAST)


def auth_headers(key: str) -> dict[str, str]:
    """The vast.ai control-API headers: the key as a Bearer token."""
    return {
        "Authorization": f"Bearer {str(key or '').strip()}",
        "accept": "application/json",
        "User-Agent": UA,
    }


def list_instances_request(key: str, *, after_token: str = "") -> urllib.request.Request:
    """The real vast.ai call that lists this account's instances."""
    url = INSTANCES_URL
    token = str(after_token or "").strip()
    if token:
        url = f"{url}?after_token={quote(token, safe='')}"
    return urllib.request.Request(url, headers=auth_headers(key))


def _send(request: urllib.request.Request, timeout: int) -> tuple[int, bytes]:
    """One HTTP call. Returns ``(status, body)``; status 0 means it never ran."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as e:
        try:
            return int(e.code), e.read()
        except OSError:
            return int(e.code), b""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 0, b""


def _body_text(body: bytes | str, n: int = 200) -> str:
    """The first ``n`` characters of a response body, for a message."""
    raw = body[:n] if isinstance(body, (bytes, bytearray)) else str(body)[:n]
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)


def _port_map(ports: Any) -> list[tuple[int, int]]:
    """Every mapped (container port, host port) pair an instance reports."""
    out: list[tuple[int, int]] = []
    if not isinstance(ports, dict):
        return out
    for key, value in ports.items():
        head = str(key).split("/", 1)[0].strip()
        try:
            container = int(head.split("-", 1)[0])
        except ValueError:
            continue
        for entry in value if isinstance(value, list) else [value]:
            raw = entry.get("HostPort") if isinstance(entry, dict) else entry
            try:
                out.append((container, int(raw)))
            except (TypeError, ValueError):
                continue
    return out


def _host_port(ports: Any, port: int) -> int | None:
    """The host port a vast instance maps to container ``port``, or None."""
    for container, host in _port_map(ports):
        if container == int(port):
            return host
    return None


def instance_endpoint(
    instance: dict[str, Any], ports: tuple[int, ...] = COMFY_PORTS
) -> str:
    """The URL ComfyUI on this instance answers on, or "" when it maps none.

    The ComfyUI template's own port is preferred, in order. A template that
    publishes ComfyUI somewhere else is still usable when it maps exactly one
    other non-ssh port, because that is the only thing a render could reach; a
    stopped instance maps nothing at all, which is the honest "".
    """
    if not isinstance(instance, dict):
        return ""
    host = str(instance.get("public_ipaddr") or instance.get("ip") or "").strip()
    if not host:
        return ""
    mapped = _port_map(instance.get("ports"))
    for wanted in ports:
        host_port = _host_port(instance.get("ports"), wanted)
        if host_port is not None:
            return f"http://{host}:{host_port}"
    others = sorted({p for p, _h in mapped if p not in SSH_PORTS})
    if len(others) == 1:
        host_port = _host_port(instance.get("ports"), others[0])
        if host_port is not None:
            return f"http://{host}:{host_port}"
    return ""


def normalize_endpoint(text: str) -> str:
    """A typed instance address as the URL this app will POST to.

    ``1.2.3.4:31234``, ``http://1.2.3.4:31234/`` and ``https://host`` all come
    back as a scheme-carrying URL with no trailing slash, so one instance cannot
    be stored twice under two spellings. "" means the text names no host.
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    if "//" not in raw:
        raw = "http://" + raw
    scheme, rest = raw.split("//", 1)
    host = rest.split("/", 1)[0].strip()
    if not host:
        return ""
    return f"{scheme}//{host}"


def prompt_url(endpoint: str) -> str:
    """The ComfyUI ``/prompt`` URL of a stored instance endpoint."""
    return f"{normalize_endpoint(endpoint)}/prompt"


def instance_row(instance: dict[str, Any]) -> dict[str, Any] | None:
    """One API instance as a stored row, or None when it has no endpoint."""
    if not isinstance(instance, dict):
        return None
    endpoint = instance_endpoint(instance)
    if not endpoint:
        return None
    label = str(instance.get("label") or instance.get("instance_name") or "").strip()
    return {
        "endpoint": endpoint,
        "label": label,
        "id": instance.get("id"),
        "gpu": str(instance.get("gpu_name") or instance.get("gpu") or "").strip(),
        "state": str(
            instance.get("actual_status")
            or instance.get("status")
            or instance.get("cur_state")
            or ""
        ).strip(),
    }


def parse_instances(payload: Any) -> list[dict[str, Any]]:
    """The account's instances as rows this app can use, in the API's order.

    Accepts the API's ``{"instances": [...]}`` and a bare list, so a caller that
    already unwrapped the body works too. Instances that map no ComfyUI port
    (stopped, or a different image) are dropped: there is no endpoint to render
    on, and a row with no endpoint could only fail later.
    """
    rows = payload.get("instances") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for it in rows:
        row = instance_row(it)
        if row is not None:
            out.append(row)
    return out


def fetch_instances(
    key: str, *, sender: Any | None = None, timeout: int = TIMEOUT_S
) -> dict[str, Any]:
    """List this account's instances. Never raises.

    ``status`` is the HTTP status of the first page, or 0 when the call never
    ran; ``error`` says what went wrong in words the page can show. A rejected
    key is reported as rejected rather than shown as "no instances", and pages
    are followed (bounded by :data:`MAX_PAGES`) so a bigger account is not
    silently truncated.
    """
    out: dict[str, Any] = {"status": 0, "instances": [], "error": ""}
    secret = str(key or "").strip()
    if not secret:
        out["error"] = "no Vast.ai key saved"
        return out
    send = sender or _send
    rows: list[dict[str, Any]] = []
    after = ""
    for page in range(MAX_PAGES):
        try:
            status, body = send(list_instances_request(secret, after_token=after), timeout)
        except Exception as e:  # noqa: BLE001 - a listing must never break the page
            out["error"] = f"{type(e).__name__}: {e}"
            return out
        status = int(status)
        if page == 0:
            out["status"] = status
        if status != 200:
            detail = _body_text(body, 120)
            out["error"] = f"HTTP {status}" + (f": {detail}" if detail else "")
            return out
        try:
            payload = json.loads(body.decode("utf-8", "replace"))
        except (AttributeError, ValueError):
            out["error"] = "the response is not JSON"
            return out
        rows.extend(parse_instances(payload))
        after = str(payload.get("next_token") or "") if isinstance(payload, dict) else ""
        if not after:
            break
    out["instances"] = rows
    return out


def post_prompt(
    endpoint: str,
    blob: bytes,
    *,
    sender: Any | None = None,
    timeout: int = TIMEOUT_S,
) -> tuple[int, bytes]:
    """POST a Comfy prompt body to a vast instance. Returns ``(status, body)``.

    No authorization header: this is the instance's own ComfyUI, not the vast.ai
    control API, and the vast token must never leave for a rented machine.
    """
    request = urllib.request.Request(
        prompt_url(endpoint),
        data=blob,
        headers={
            "Content-Type": "application/json",
            "accept": "application/json",
            "User-Agent": UA,
        },
        method="POST",
    )
    return (sender or _send)(request, timeout)


def get_url(
    url: str, *, sender: Any | None = None, timeout: int = TIMEOUT_S
) -> tuple[int, bytes]:
    """A keyless GET of a vast instance's own URL, for ``/history/{id}``."""
    request = urllib.request.Request(
        url, headers={"accept": "application/json", "User-Agent": UA}
    )
    return (sender or _send)(request, timeout)


def clean_row(row: Any) -> dict[str, Any] | None:
    """A stored row as this app uses it, or None when it names no endpoint."""
    if not isinstance(row, dict):
        return None
    endpoint = normalize_endpoint(row.get("endpoint"))
    if not endpoint:
        return None
    return {
        "endpoint": endpoint,
        "label": str(row.get("label") or "").strip(),
        "id": row.get("id"),
        "gpu": str(row.get("gpu") or "").strip(),
        "state": str(row.get("state") or "").strip(),
    }


def empty_doc() -> dict[str, Any]:
    """The document a fresh install reads: no instances, Generate on Salad."""
    return {
        "version": DOC_VERSION,
        "mode": MODE_SALAD,
        "active": "",
        "instances": [],
    }


def load_doc(path: Path | None = None) -> dict[str, Any]:
    """The saved selection: which engine Generate uses, and the instances.

    A missing, unreadable or hand-broken file reads as "nothing selected, Salad",
    so a bad file leaves the app usable instead of aborting startup. An
    ``active`` endpoint that no longer names a listed instance is cleared, so
    the page can never point Generate at a row it does not show.
    """
    target = Path(path) if path is not None else INSTANCES_PATH
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return empty_doc()
    try:
        data = json.loads(raw)
    except ValueError:
        return empty_doc()
    if not isinstance(data, dict):
        return empty_doc()
    doc = empty_doc()
    mode = str(data.get("mode") or MODE_SALAD).strip().lower()
    doc["mode"] = mode if mode in MODES else MODE_SALAD
    rows = [row for row in (clean_row(r) for r in data.get("instances") or []) if row]
    doc["instances"] = rows
    active = normalize_endpoint(data.get("active"))
    if active and active in {row["endpoint"] for row in rows}:
        doc["active"] = active
    return doc


def save_doc(doc: dict[str, Any], path: Path | None = None) -> Path:
    """Write the selection. Returns the path it wrote."""
    target = Path(path) if path is not None else INSTANCES_PATH
    payload = {
        "version": DOC_VERSION,
        "mode": str(doc.get("mode") or MODE_SALAD),
        "active": str(doc.get("active") or ""),
        "instances": [
            row for row in (clean_row(r) for r in doc.get("instances") or []) if row
        ],
    }
    if payload["mode"] not in MODES:
        payload["mode"] = MODE_SALAD
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def add_instance(
    doc: dict[str, Any], endpoint: str, *, label: str = "", **fields: Any
) -> tuple[dict[str, Any], str]:
    """Add one instance to the selection. Returns ``(doc, refusal)``.

    The document is copied, so a refusal leaves the caller's own document
    untouched and a caller that stores the result can never half-apply an edit.
    The first instance added also becomes the active one, so a fresh selection
    is immediately usable.
    """
    url = normalize_endpoint(endpoint)
    if not url:
        return doc, "Type an instance address like http://1.2.3.4:31234."
    rows = [row for row in (clean_row(r) for r in doc.get("instances") or []) if row]
    if any(row["endpoint"] == url for row in rows):
        return doc, f"{url} is already in the list."
    rows.append(
        clean_row({"endpoint": url, "label": label, **fields}) or {"endpoint": url}
    )
    out = dict(doc)
    out["instances"] = rows
    if not out.get("active"):
        out["active"] = url
    return out, ""


def remove_instance(doc: dict[str, Any], endpoint: str) -> tuple[dict[str, Any], bool]:
    """Drop one instance. Returns ``(doc, removed)``.

    Removing the active instance makes the next listed one active, so the
    selection keeps pointing at a row the page shows; removing the last one
    leaves nothing active and Generate has to refuse until one is added.
    """
    url = normalize_endpoint(endpoint)
    rows = [row for row in (clean_row(r) for r in doc.get("instances") or []) if row]
    kept = [row for row in rows if row["endpoint"] != url]
    removed = len(kept) != len(rows)
    out = dict(doc)
    out["instances"] = kept
    if out.get("active") == url:
        out["active"] = kept[0]["endpoint"] if kept else ""
    return out, removed


def set_active(doc: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """Point Generate at one listed instance; an unknown one is ignored."""
    url = normalize_endpoint(endpoint)
    rows = [row for row in (clean_row(r) for r in doc.get("instances") or []) if row]
    out = dict(doc)
    out["instances"] = rows
    if any(row["endpoint"] == url for row in rows):
        out["active"] = url
    return out


def set_mode(doc: dict[str, Any], mode: str) -> dict[str, Any]:
    """Choose the engine Generate uses. An unknown mode keeps Salad."""
    wanted = str(mode or "").strip().lower()
    out = dict(doc)
    out["mode"] = wanted if wanted in MODES else MODE_SALAD
    return out


def active_row(doc: dict[str, Any]) -> dict[str, Any] | None:
    """The instance Generate will POST to, or None when none is selected."""
    endpoint = normalize_endpoint(doc.get("active"))
    if not endpoint:
        return None
    for row in doc.get("instances") or []:
        clean = clean_row(row)
        if clean and clean["endpoint"] == endpoint:
            return clean
    return None


def row_label(row: dict[str, Any]) -> str:
    """What the page calls one instance: its label, else its address."""
    label = str((row or {}).get("label") or "").strip()
    return label or str((row or {}).get("endpoint") or "")
