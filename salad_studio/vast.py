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
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

VAST_API = "https://console.vast.ai/api/v1"
BUNDLES_URL = "https://console.vast.ai/api/v0/bundles/"
CREATE_URL = "https://console.vast.ai/api/v0/asks/{offer}/"
INSTANCES_URL = f"{VAST_API}/instances/"
# The v0 path answers 410 "deprecated_endpoint" (measured 2026-10-13), so this is
# the only list endpoint this client may use; test_vast pins the version.
# A page holds 25 instances, the API's own cap, so four pages cover a hundred.
# Past that the listing stops and sets ``truncated``: a short list that looks
# complete is worse than one that says it was cut off.
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

# The replacement search: a cheap 24 GB host that can run the klein image and
# pull its weights. The user edits the GPU list, the price, reliability and the
# two link floors; CUDA 13 is the image's hard floor (docs/workflow/23 section 5).
INSTANCE_DISK_GB = 100
SEARCH_DISK_GB = 140
SEARCH_GPU_RAM_MB = 24000
# An empty GPU list must not mean "any GPU": the measured unfiltered search's
# cheapest 24 GB offer is a Tesla P40 at $0.108/hr. The order is the preference
# order, so a 5090 wins a tie against a 4090.
DEFAULT_GPU_NAMES: tuple[str, ...] = ("RTX 5090", "RTX 4090")
GPU_CHOICES: tuple[str, ...] = ("RTX 5090", "RTX 4090", "RTX A6000", "A100 PCIE")
OFFER_QUERY_LIMIT = 100
REPLACE_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "max_price": 0.50,
    "min_down_mbps": 200,
    "min_up_mbps": 100,
    "cuda_min": 13.0,
    "min_reliability": 0.95,
    "gpu_names": DEFAULT_GPU_NAMES,
}
REPLACE_WAIT_TRIES = 20
REPLACE_WAIT_S = 15.0

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

    Text with no scheme must look like a host — a dot or a port — before a
    scheme is added, so a word ("not") or a typed phrase is refused here instead
    of becoming ``http://not``: an address no render could reach, and one that a
    page splitting the box on spaces would store five times. Text that carries a
    scheme is taken as typed, so ``http://comfy-local`` keeps working.
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    if "//" not in raw:
        bare = raw.split("/", 1)[0].strip()
        if "." not in bare and ":" not in bare:
            return ""
        raw = "http://" + raw
    scheme, rest = raw.split("//", 1)
    host = rest.split("/", 1)[0].strip()
    if not host:
        return ""
    return f"{scheme}//{host}"


def prompt_url(endpoint: str) -> str:
    """The ComfyUI ``/prompt`` URL of a stored instance endpoint."""
    return f"{normalize_endpoint(endpoint)}/prompt"


def view_url(endpoint: str, info: dict[str, Any]) -> str:
    """The ComfyUI ``/view`` URL of one image record a history answer carried.

    A plain ComfyUI answers ``/prompt`` with a ``prompt_id`` and ``/history``
    with file records, so the plate itself is fetched from ``/view`` with the
    filename, subfolder and type that record names.
    """
    query = urlencode(
        {
            "filename": str((info or {}).get("filename") or ""),
            "subfolder": str((info or {}).get("subfolder") or ""),
            "type": str((info or {}).get("type") or "output"),
        }
    )
    return f"{normalize_endpoint(endpoint)}/view?{query}"


def instance_row(instance: dict[str, Any]) -> dict[str, Any] | None:
    """One API record as a stored row, including one that maps no endpoint.

    A record that exists but has not mapped its ComfyUI port is a real instance:
    the page shows it as loading rather than hiding it. ``endpoint`` is empty
    until the port maps, and the API's own state says why.
    """
    if not isinstance(instance, dict):
        return None
    return clean_row(
        {
            "id": instance.get("id"),
            "endpoint": instance_endpoint(instance),
            "label": instance.get("label") or instance.get("instance_name") or "",
            "gpu": instance.get("gpu_name") or instance.get("gpu") or "",
            "state": instance.get("actual_status")
            or instance.get("status")
            or instance.get("cur_state")
            or "",
        }
    )


def parse_instances(payload: Any) -> list[dict[str, Any]]:
    """The account's instances that have an endpoint, in the API's order.

    Accepts the API's ``{"instances": [...]}`` and a bare list, so a caller that
    already unwrapped the body works too. Instances that map no ComfyUI port
    (stopped, loading, or a different image) are dropped here and kept by
    :func:`fetch_records`; a waiter for a new instance has no use for either.
    """
    rows = payload.get("instances") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for it in rows:
        row = instance_row(it)
        if row is not None and row["endpoint"]:
            out.append(row)
    return out


def fetch_instances(
    key: str, *, sender: Any | None = None, timeout: int = TIMEOUT_S
) -> dict[str, Any]:
    """List this account's instances. Never raises.

    ``status`` is the HTTP status of the first page, or 0 when the call never
    ran; ``error`` says what went wrong in words the page can show. A rejected
    key is reported as rejected rather than shown as "no instances". Pages are
    followed up to :data:`MAX_PAGES`, and when the API still offers a next page
    after the last one, ``truncated`` is True: the caller can say that the list
    it got is not the whole account, which is better than dropping instances with
    no sign that it happened.
    """
    out: dict[str, Any] = {"status": 0, "instances": [], "error": "", "truncated": False}
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
    else:
        # The loop ran out of pages with the API still offering more: say so
        # rather than returning a short list that looks complete.
        out["truncated"] = bool(after)
    out["instances"] = rows
    return out


def fetch_records(
    key: str, *, sender: Any | None = None, timeout: int = TIMEOUT_S
) -> dict[str, Any]:
    """Every instance record, including a stopped one with no endpoint.

    ``fetch_instances`` drops a row with no Comfy endpoint because the page
    cannot render on it. A replacement check has to tell a stopped instance from
    a destroyed one, so it reads the unfiltered list and refuses to rent a
    duplicate when the record still exists.
    """
    out: dict[str, Any] = {
        "status": 0,
        "instances": [],
        "error": "",
        "truncated": False,
    }
    secret = str(key or "").strip()
    if not secret:
        out["error"] = "no Vast.ai key saved"
        return out
    send = sender or _send
    rows: list[dict[str, Any]] = []
    after = ""
    for page in range(MAX_PAGES):
        try:
            status, body = send(
                list_instances_request(secret, after_token=after), timeout
            )
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
        items = payload.get("instances") if isinstance(payload, dict) else payload
        if isinstance(items, list):
            rows.extend(item for item in items if isinstance(item, dict))
        after = str(payload.get("next_token") or "") if isinstance(payload, dict) else ""
        if not after:
            break
    else:
        out["truncated"] = bool(after)
    out["instances"] = rows
    return out


def find_record(
    rows: list[dict[str, Any]], *, endpoint: str = "", instance_id: Any = None
) -> dict[str, Any] | None:
    """The raw record for a stored instance, by id first and endpoint second."""
    want = normalize_endpoint(endpoint)
    for row in rows:
        if instance_id is not None and str(row.get("id") or "") == str(instance_id):
            return row
        if want and normalize_endpoint(instance_endpoint(row)) == want:
            return row
    return None


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


def _row_id(value: Any) -> int | None:
    """A positive instance id, or None when the value is not one."""
    try:
        ident = int(value)
    except (TypeError, ValueError):
        return None
    return ident if ident > 0 else None


def row_key(row: dict[str, Any]) -> str:
    """The identity one row is stored and shown under: its id, else endpoint."""
    clean = row if isinstance(row, dict) else {}
    ident = _row_id(clean.get("id"))
    if ident is not None:
        return str(ident)
    return normalize_endpoint(clean.get("endpoint"))


def clean_row(row: Any) -> dict[str, Any] | None:
    """A stored row as this app uses it, or None when it names no instance.

    A row is an instance identity. ``id`` is that identity when the account
    assigned one; a hand-typed row has only its endpoint. The endpoint itself is
    optional user state, because a created instance exists before its ComfyUI
    port maps. A destroyed row keeps its id and loses its address, so nothing
    can POST to it again.

    ``image`` is a reference, not a fact this client checks: it records which
    container image the instance runs, so the row points at the entry the
    Config page's Container images section describes.
    """
    if not isinstance(row, dict):
        return None
    ident = _row_id(row.get("id"))
    endpoint = normalize_endpoint(row.get("endpoint"))
    state = str(row.get("state") or "").strip().lower()
    if state == "destroyed":
        endpoint = ""
    if ident is None and not endpoint:
        return None
    return {
        "id": ident,
        "endpoint": endpoint,
        "label": str(row.get("label") or "").strip(),
        "gpu": str(row.get("gpu") or "").strip(),
        "state": state,
        "image": str(row.get("image") or "").strip(),
    }


def empty_doc() -> dict[str, Any]:
    """The document a fresh install reads: no instances, Generate on Salad."""
    return {
        "version": DOC_VERSION,
        "mode": MODE_SALAD,
        "active": "",
        "instances": [],
        "replace": clean_replace({}),
        "pending": {},
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
    # The old build kept a created contract in one `pending` slot until a
    # listing showed it. Fold that legacy record into the row model once, so
    # the same instance is not both a row and a shadow of itself.
    pending = clean_pending(data.get("pending"))
    if pending and not any(row["id"] == pending["contract"] for row in rows):
        row = clean_row(
            {
                "id": pending["contract"],
                "endpoint": "",
                "state": "creating",
                "label": pending["label"],
                "image": pending["image"],
            }
        )
        if row is not None:
            rows.append(row)
    doc["instances"] = rows
    doc["replace"] = clean_replace(data.get("replace"))
    doc["pending"] = {}
    active = normalize_endpoint(data.get("active"))
    if active and active in {row["endpoint"] for row in rows if row["endpoint"]}:
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
        "replace": clean_replace(doc.get("replace")),
        # Written empty for forward compatibility only. The creating row is the
        # durable record; nothing reads this field any more.
        "pending": {},
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


def _key_text(key: Any) -> str:
    """A tree iid or store key as one spelling: an id, or a normalized endpoint."""
    raw = str(key or "").strip()
    return normalize_endpoint(raw) or raw


def _clean_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in (clean_row(r) for r in doc.get("instances") or []) if row]


def upsert_instance(
    doc: dict[str, Any], row: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    """Insert or update one row, matched by id first and endpoint second.

    The incoming endpoint, state and gpu win, because they come from the
    account. The stored image survives when the incoming row names none, and a
    stored non-empty label survives an empty incoming one, because both are user
    state. Returns ``(doc, "added" | "updated" | "unchanged")``.
    """
    incoming = clean_row(row)
    out = dict(doc)
    rows = _clean_rows(doc)
    out["instances"] = rows
    if incoming is None:
        return out, "unchanged"
    index: int | None = None
    if incoming["id"] is not None:
        for i, stored in enumerate(rows):
            if stored["id"] == incoming["id"]:
                index = i
                break
    if index is None and incoming["endpoint"]:
        for i, stored in enumerate(rows):
            if stored["endpoint"] == incoming["endpoint"]:
                index = i
                break
    if index is None:
        rows.append(incoming)
        return out, "added"
    stored = rows[index]
    merged = {
        "id": incoming["id"] if incoming["id"] is not None else stored["id"],
        "endpoint": incoming["endpoint"],
        "label": incoming["label"] or stored["label"],
        "gpu": incoming["gpu"],
        "state": incoming["state"],
        "image": incoming["image"] or stored["image"],
    }
    rows[index] = merged
    return out, ("unchanged" if merged == stored else "updated")


def reconcile(
    doc: dict[str, Any], records: list[dict[str, Any]], *, complete: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fold one unfiltered listing into the store. Returns ``(doc, summary)``.

    A complete listing is the account's whole truth: every id-bearing row it
    does not mention is destroyed, and destruction keeps the row as history.
    A truncated listing proves nothing is missing, so it destroys nothing. A row
    with no id is the user's own and is never modified, marked or removed.

    ``active`` stays only while it names a row that still maps an endpoint. When
    a row that had no endpoint is reached for the first time, its endpoint
    becomes active, because that instance is the one the create was for. A row
    that arrives already mapped is not promoted. The summary carries the ids
    that were added, updated and destroyed, the endpoints that went away, and
    the promoted id.
    """
    rows = _clean_rows(doc)
    before = {row["endpoint"] for row in rows if row["endpoint"]}
    original_rows = [dict(row) for row in rows]
    original_active = normalize_endpoint(doc.get("active"))
    manual_endpoints = {
        row["endpoint"] for row in rows if row["id"] is None and row["endpoint"]
    }
    # The rows a create owns: they existed without an endpoint before this
    # listing. The first one that maps is the instance this Fetch promoted, so
    # it becomes active once nothing else is. A row that arrives already mapped
    # was not created by this app and is never promoted on its own.
    awaiting = {
        str(row["id"]) for row in rows if row["id"] is not None and not row["endpoint"]
    }
    added: list[str] = []
    updated: list[str] = []
    live_ids: set[str] = set()
    out = dict(doc)
    out["instances"] = rows
    for record in records if isinstance(records, list) else []:
        incoming = instance_row(record)
        if incoming is None or incoming["id"] is None:
            # Without an id a record cannot be reconciled against a managed row.
            continue
        ident = str(incoming["id"])
        live_ids.add(ident)
        if incoming["endpoint"] and incoming["endpoint"] in manual_endpoints:
            # A hand-typed row owns that address. Reconciliation never touches
            # it, and two rows must not share one endpoint.
            continue
        out, status = upsert_instance(out, incoming)
        if status == "added":
            added.append(ident)
        elif status == "updated":
            updated.append(ident)

    rows = out["instances"]
    destroyed: list[str] = []
    if complete:
        for row in rows:
            ident = row["id"]
            if ident is None or str(ident) in live_ids:
                continue
            if row["state"] != "destroyed" or row["endpoint"]:
                row["state"] = "destroyed"
                row["endpoint"] = ""
                destroyed.append(str(ident))

    endpoints = {row["endpoint"] for row in rows if row["endpoint"]}
    active = original_active if original_active in endpoints else ""
    promoted = ""
    if not active:
        for row in rows:
            if str(row["id"]) in awaiting and row["endpoint"]:
                active = row["endpoint"]
                promoted = str(row["id"])
                break

    out["instances"] = rows
    out["active"] = active
    out["pending"] = {}
    after = {row["endpoint"] for row in rows if row["endpoint"]}
    summary = {
        "added": added,
        "updated": updated,
        "destroyed": destroyed,
        "gone_endpoints": sorted(before - after),
        "promoted": promoted,
    }
    summary["changed"] = bool(
        rows != original_rows or active != original_active or doc.get("pending")
    )
    return out, summary


def remove_instance(doc: dict[str, Any], key: Any) -> tuple[dict[str, Any], bool]:
    """Drop the row named by ``key`` (an id or an endpoint). Returns ``(doc, removed)``.

    Removing the active instance makes the next row that has an endpoint
    active, so the selection keeps pointing at a row the page can POST to;
    removing the last one leaves nothing active and Generate has to refuse
    until one is added.
    """
    want = _key_text(key)
    rows = _clean_rows(doc)
    removed_row = next((row for row in rows if row_key(row) == want), None)
    kept = [row for row in rows if row_key(row) != want]
    out = dict(doc)
    out["instances"] = kept
    active = normalize_endpoint(doc.get("active"))
    if removed_row is not None and active and removed_row["endpoint"] == active:
        out["active"] = next(
            (row["endpoint"] for row in kept if row["endpoint"]), ""
        )
    return out, removed_row is not None


def set_active(doc: dict[str, Any], key: Any) -> dict[str, Any]:
    """Point Generate at one listed row; a row with no endpoint is refused."""
    want = _key_text(key)
    rows = _clean_rows(doc)
    target = next((row for row in rows if row_key(row) == want), None)
    out = dict(doc)
    out["instances"] = rows
    if target is not None and target["endpoint"]:
        out["active"] = target["endpoint"]
    return out


def set_mode(doc: dict[str, Any], mode: str) -> dict[str, Any]:
    """Choose the engine Generate uses. An unknown mode keeps Salad."""
    wanted = str(mode or "").strip().lower()
    out = dict(doc)
    out["mode"] = wanted if wanted in MODES else MODE_SALAD
    return out


def active_row(doc: dict[str, Any]) -> dict[str, Any] | None:
    """The instance Generate will POST to, or None when none can be reached."""
    endpoint = normalize_endpoint(doc.get("active"))
    if not endpoint:
        return None
    for row in doc.get("instances") or []:
        clean = clean_row(row)
        if (
            clean
            and clean["endpoint"] == endpoint
            and clean["state"] != "destroyed"
        ):
            return clean
    return None


def row_label(row: dict[str, Any]) -> str:
    """What the page calls one instance: its label, else address, else ``#id``."""
    label = str((row or {}).get("label") or "").strip()
    if label:
        return label
    endpoint = str((row or {}).get("endpoint") or "").strip()
    if endpoint:
        return endpoint
    ident = (row or {}).get("id")
    return f"#{ident}" if ident is not None else ""


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _gpu_names(raw: Any) -> list[str]:
    """The GPU models a search accepts, in preference order.

    A list, tuple, set or comma string is accepted, so the stored record and the
    page's entry box speak the same shape. A known name is canonicalized
    case-insensitively, blanks and duplicates are dropped, and an empty list
    restores :data:`DEFAULT_GPU_NAMES` rather than meaning "any GPU".
    """
    if isinstance(raw, str):
        items: list[Any] = raw.split(",")
    elif isinstance(raw, (list, tuple, set)):
        items = list(raw)
    else:
        items = []
    canonical = {name.casefold(): name for name in GPU_CHOICES}
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        name = canonical.get(text.casefold(), text)
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out or list(DEFAULT_GPU_NAMES)


def clean_replace(raw: Any) -> dict[str, Any]:
    """The replacement policy, clamped to values the search can use.

    ``enabled`` is off unless the stored document says otherwise: creating an
    instance spends money, so the option is opt-in. A hand-edited or missing
    field falls back to the defaults instead of turning the search unusable.
    ``gpu_names`` always comes back as a fresh, non-empty list, because the
    search that ran with an empty list rents a Tesla P40.
    """
    out = {**REPLACE_DEFAULTS, "gpu_names": list(DEFAULT_GPU_NAMES)}
    if not isinstance(raw, dict):
        return out
    out["enabled"] = bool(raw.get("enabled"))
    for key in ("max_price", "min_down_mbps", "min_up_mbps", "cuda_min"):
        value = _num(raw.get(key), -1.0)
        if value >= 0:
            out[key] = value
    reliability = _num(raw.get("min_reliability"), -1.0)
    if 0.0 <= reliability <= 1.0:
        out["min_reliability"] = reliability
    out["gpu_names"] = _gpu_names(raw.get("gpu_names"))
    return out


def clean_pending(raw: Any) -> dict[str, Any]:
    """A created contract whose endpoint has not mapped yet, or ``{}``.

    Without this the next Generate would see the old endpoint as destroyed and
    rent a second instance while the first is still booting.
    """
    if not isinstance(raw, dict):
        return {}
    try:
        contract = int(raw.get("contract"))
    except (TypeError, ValueError):
        return {}
    if contract <= 0:
        return {}
    return {
        "contract": contract,
        "label": str(raw.get("label") or "").strip(),
        "image": str(raw.get("image") or "").strip(),
    }


def offer_value(offer: Any) -> float:
    """Images per dollar: vast.ai's perf index divided by the hourly price.

    ``dlperf_per_dphtotal`` is the API's own answer when it carries one; the
    division is the fallback for an older or partial record. A missing or zero
    input yields 0.0 rather than a division by zero.
    """
    if not isinstance(offer, dict):
        return 0.0
    stated = _num(offer.get("dlperf_per_dphtotal"))
    if stated > 0:
        return stated
    price = _num(offer.get("dph_total"))
    perf = _num(offer.get("dlperf"))
    if price > 0 and perf > 0:
        return perf / price
    return 0.0


def offer_query(replace: Any) -> dict[str, Any]:
    """The vast.ai offer search, highest images per dollar first.

    The server's order avoids the price-window starvation of a 100-offer limit:
    a cheap-but-slow page can hide every card that actually buys more images.
    The client re-sorts with the full key as a safety net.
    """
    policy = clean_replace(replace)
    return {
        "num_gpus": {"eq": 1},
        "gpu_ram": {"gte": SEARCH_GPU_RAM_MB},
        "disk_space": {"gte": SEARCH_DISK_GB},
        "cuda_max_good": {"gte": policy["cuda_min"]},
        "inet_down": {"gte": policy["min_down_mbps"]},
        "inet_up": {"gte": policy["min_up_mbps"]},
        "dph_total": {"lte": policy["max_price"]},
        "gpu_name": {"in": policy["gpu_names"]},
        "reliability2": {"gte": policy["min_reliability"]},
        "rentable": {"eq": True},
        "verified": {"eq": True},
        "rented": {"eq": False},
        "type": "on-demand",
        "order": [["dlperf_per_dphtotal", "desc"]],
        "limit": OFFER_QUERY_LIMIT,
    }


def _json_request(
    url: str, key: str, payload: dict[str, Any], *, method: str
) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**auth_headers(key), "Content-Type": "application/json"},
        method=method,
    )


def _error_text(body: bytes | str) -> str:
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except (AttributeError, ValueError):
        return _body_text(body, 160)
    if isinstance(data, dict):
        return str(data.get("msg") or data.get("error") or _body_text(body, 160))
    return _body_text(body, 160)


def search_offers(
    key: str,
    replace: Any,
    *,
    sender: Any | None = None,
    timeout: int = TIMEOUT_S,
) -> dict[str, Any]:
    """Search offers that meet the policy. Never raises."""
    out: dict[str, Any] = {"status": 0, "offers": [], "error": ""}
    secret = str(key or "").strip()
    if not secret:
        out["error"] = "no Vast.ai key saved"
        return out
    request = _json_request(BUNDLES_URL, secret, offer_query(replace), method="POST")
    try:
        status, body = (sender or _send)(request, timeout)
    except Exception as e:  # noqa: BLE001 - a search must never break the page
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    out["status"] = int(status)
    if int(status) != 200:
        out["error"] = f"HTTP {status}: {_error_text(body)}"
        return out
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except (AttributeError, ValueError):
        out["error"] = "the offer response is not JSON"
        return out
    offers = data.get("offers") if isinstance(data, dict) else None
    if not isinstance(offers, list):
        out["error"] = "the offer response holds no list"
        return out
    out["offers"] = [offer for offer in offers if isinstance(offer, dict)]
    return out


def offer_meets(offer: Any, replace: Any) -> bool:
    """Whether one offer clears every floor the policy names.

    ``reliability2`` fails closed when the record omits it: a host that cannot
    state its reliability is not the host the floor was meant to allow.
    """
    if not isinstance(offer, dict) or offer.get("id") is None:
        return False
    policy = clean_replace(replace)
    return (
        _num(offer.get("gpu_ram")) >= SEARCH_GPU_RAM_MB
        and _num(offer.get("disk_space")) >= SEARCH_DISK_GB
        and int(_num(offer.get("num_gpus"), 1)) == 1
        and _num(offer.get("cuda_max_good")) >= policy["cuda_min"]
        and _num(offer.get("inet_down")) >= policy["min_down_mbps"]
        and _num(offer.get("inet_up")) >= policy["min_up_mbps"]
        and _num(offer.get("dph_total"), 1e9) <= policy["max_price"]
        and str(offer.get("gpu_name") or "").strip() in set(policy["gpu_names"])
        and _num(offer.get("reliability2"), 0.0) >= policy["min_reliability"]
        and offer.get("rentable") is not False
    )


def matching_offers(offers: list[dict[str, Any]], replace: Any) -> list[dict[str, Any]]:
    """Every offer that clears the floors, best value first.

    The order is the contract's ranking: images per dollar descending, then the
    GPU preference list, then price, then the faster links. No cap: this is the
    list the results table shows, and the user picks from all of it.
    """
    policy = clean_replace(replace)
    rank = {name: index for index, name in enumerate(policy["gpu_names"])}
    good = [offer for offer in offers if offer_meets(offer, policy)]
    good.sort(
        key=lambda offer: (
            -offer_value(offer),
            rank.get(str(offer.get("gpu_name") or "").strip(), len(rank)),
            _num(offer.get("dph_total"), 1e9),
            -_num(offer.get("inet_down")),
            -_num(offer.get("inet_up")),
        )
    )
    return good


def pick_offers(
    offers: list[dict[str, Any]], replace: Any, *, limit: int = 3
) -> list[dict[str, Any]]:
    """The best-value offers that clear the floors, up to ``limit``.

    The create endpoint can refuse an offer that the search still lists (another
    renter took it, or the host cannot start the container), so the caller keeps
    a short queue of alternatives instead of giving up on the first refusal.
    """
    return matching_offers(offers, replace)[: max(0, int(limit))]


def pick_offer(offers: list[dict[str, Any]], replace: Any) -> dict[str, Any] | None:
    """The highest-value offer that clears the floors, or None."""
    options = pick_offers(offers, replace, limit=1)
    return options[0] if options else None


def offer_cells(offer: Any) -> dict[str, str]:
    """One offer as the results table's cell text, keyed by the page's columns."""
    data = offer if isinstance(offer, dict) else {}

    def shown(key: str) -> bool:
        return data.get(key) is not None

    value = ""
    if _num(data.get("dlperf_per_dphtotal")) > 0 or (
        _num(data.get("dlperf")) > 0 and _num(data.get("dph_total")) > 0
    ):
        value = f"{offer_value(data):.0f}"
    return {
        "gpu": str(data.get("gpu_name") or "").strip(),
        "price": f"${_num(data.get('dph_total')):.3f}" if shown("dph_total") else "",
        "perf": f"{_num(data.get('dlperf')):.0f}" if shown("dlperf") else "",
        "value": value,
        "vram": (
            str(round(_num(data.get("gpu_ram")) / 1024))
            if shown("gpu_ram")
            else ""
        ),
        "disk": f"{_num(data.get('disk_space')):g}" if shown("disk_space") else "",
        "cuda": str(_num(data.get("cuda_max_good"))) if shown("cuda_max_good") else "",
        "down": f"{_num(data.get('inet_down')):g}" if shown("inet_down") else "",
        "up": f"{_num(data.get('inet_up')):g}" if shown("inet_up") else "",
        "reliability": (
            f"{_num(data.get('reliability2')):.3f}"
            if shown("reliability2")
            else ""
        ),
        "location": str(data.get("geolocation") or "").strip() or "unknown",
        "offer": str(data.get("id")) if shown("id") else "",
    }


def offer_label(offer: Any) -> str:
    """One log-safe line for an offer: GPU, price and both link speeds."""
    if not isinstance(offer, dict):
        return "an offer"
    return (
        f"{offer.get('gpu_name') or 'GPU'} "
        f"${_num(offer.get('dph_total')):.3f}/hr, "
        f"{_num(offer.get('inet_down')):.0f}/{_num(offer.get('inet_up')):.0f} Mbps"
    )


def replacement_env(*, hf_token: str = "", civitai_token: str = "") -> str:
    """The Docker flags a replacement needs, including the two render tokens.

    The vast key is deliberately absent: it authenticates the control API and
    must never reach a rented machine. Empty token slots are omitted rather than
    sent as ``-e NAME=``, which the container would read as an empty credential.
    """
    parts = [
        "-p 3000:3000",
        "-p 8188:8188",
        "-e STARTUP_CHECK_MAX_TRIES=120",
        "-e HF_HUB_DOWNLOAD_TIMEOUT=120",
        "-e HF_HUB_ETAG_TIMEOUT=60",
    ]
    if str(hf_token or "").strip():
        parts.append(f"-e HF_TOKEN={str(hf_token).strip()}")
    if str(civitai_token or "").strip():
        parts.append(f"-e CIVITAI_API_TOKEN={str(civitai_token).strip()}")
    return " ".join(parts)


def create_instance(
    key: str,
    offer_id: int,
    *,
    image: str,
    env: str = "",
    label: str = "",
    sender: Any | None = None,
    timeout: int = TIMEOUT_S,
) -> dict[str, Any]:
    """Accept one offer. Returns the new contract id or why it failed."""
    out: dict[str, Any] = {"status": 0, "contract": None, "error": ""}
    secret = str(key or "").strip()
    image = str(image or "").strip()
    if not secret:
        out["error"] = "no Vast.ai key saved"
        return out
    if not image:
        out["error"] = "no container image is set for this instance"
        return out
    body = {
        "image": image,
        "disk": INSTANCE_DISK_GB,
        "runtype": "args",
        "target_state": "running",
        "cancel_unavail": True,
        "env": str(env or ""),
    }
    if str(label or "").strip():
        body["label"] = str(label).strip()
    request = _json_request(
        CREATE_URL.format(offer=int(offer_id)), secret, body, method="PUT"
    )
    try:
        status, raw = (sender or _send)(request, timeout)
    except Exception as e:  # noqa: BLE001 - a create must report, not raise
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    out["status"] = int(status)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except (AttributeError, ValueError):
        data = None
    if int(status) != 200 or not isinstance(data, dict) or data.get("success") is False:
        out["error"] = f"HTTP {status}: {_error_text(raw)}"
        return out
    contract = data.get("new_contract")
    if contract is None:
        out["error"] = "the create response carried no contract id"
        return out
    out["contract"] = int(contract)
    return out


def find_instance(
    rows: list[dict[str, Any]], *, endpoint: str = "", instance_id: Any = None
) -> dict[str, Any] | None:
    """The live row for a stored instance, by id first and endpoint second."""
    want = normalize_endpoint(endpoint)
    for row in rows:
        if instance_id is not None and str(row.get("id") or "") == str(instance_id):
            return row
        if want and normalize_endpoint(row.get("endpoint")) == want:
            return row
    return None


def wait_for_instance(
    key: str,
    contract: int,
    *,
    sender: Any | None = None,
    sleep: Any = time.sleep,
    tries: int = REPLACE_WAIT_TRIES,
    interval: float = REPLACE_WAIT_S,
) -> dict[str, Any] | None:
    """Poll the account until the new contract maps a Comfy endpoint."""
    for attempt in range(tries):
        listing = fetch_instances(key, sender=sender)
        if listing.get("status") == 200:
            row = find_instance(listing["instances"], instance_id=contract)
            if row is not None:
                return row
        if attempt + 1 < tries:
            sleep(interval)
    return None


def _create_and_wait(
    key: str,
    offers: list[dict[str, Any]],
    *,
    image: str,
    label: str = "",
    env: str = "",
    sender: Any | None = None,
    sleep: Any = time.sleep,
    tries: int = REPLACE_WAIT_TRIES,
    interval: float = REPLACE_WAIT_S,
) -> dict[str, Any]:
    """Create the first offer that accepts, then wait for its endpoint.

    The offers are tried in order, so an automatic replacement keeps its short
    fallback queue. A manual rent passes one offer and therefore issues exactly
    one PUT. ``row`` is None when the contract exists but has not mapped an
    endpoint yet, and the message says so.
    """
    created: dict[str, Any] = {}
    offer: dict[str, Any] = {}
    refused: list[str] = []
    for candidate in offers:
        attempt = create_instance(
            key,
            int(candidate["id"]),
            image=image,
            env=env,
            label=label,
            sender=sender,
        )
        if attempt.get("contract") is not None:
            created = attempt
            offer = candidate
            break
        refused.append(str(attempt.get("error") or "the create failed"))
    if created.get("contract") is None:
        return {
            "action": "error",
            "message": "could not create the instance: " + "; ".join(refused),
        }
    contract = int(created["contract"])
    row = wait_for_instance(
        key,
        contract,
        sender=sender,
        sleep=sleep,
        tries=tries,
        interval=interval,
    )
    message = f"created instance {contract} on {offer_label(offer)}"
    clean_label = str(label or "").strip()
    clean_image = str(image or "").strip()
    if row is None:
        return {
            "action": "created",
            "contract": contract,
            "row": None,
            "offer": offer,
            "label": clean_label,
            "image": clean_image,
            "message": message + "; it has not mapped an endpoint yet",
        }
    row = {**row, "label": clean_label, "image": clean_image}
    return {
        "action": "created",
        "contract": contract,
        "row": row,
        "offer": offer,
        "label": clean_label,
        "image": clean_image,
        "message": message + f" at {row['endpoint']}",
    }


def rent_offer(
    key: str,
    offer: dict[str, Any],
    *,
    image: str,
    label: str = "",
    env: str = "",
    sender: Any | None = None,
    sleep: Any = time.sleep,
    tries: int = REPLACE_WAIT_TRIES,
    interval: float = REPLACE_WAIT_S,
) -> dict[str, Any]:
    """Rent the offer the user selected, and never another one.

    Exactly one PUT: a refusal is reported, not answered with a second offer.
    That is what makes the button's row the machine the user chose.
    """
    if not isinstance(offer, dict) or offer.get("id") is None:
        return {"action": "error", "message": "the selected offer has no id"}
    return _create_and_wait(
        key,
        [offer],
        image=image,
        label=label,
        env=env,
        sender=sender,
        sleep=sleep,
        tries=tries,
        interval=interval,
    )


def replace_destroyed(
    *,
    key: str,
    endpoint: str = "",
    instance_id: Any = None,
    image: str,
    settings: Any,
    label: str = "",
    env: str = "",
    sender: Any | None = None,
    sleep: Any = time.sleep,
    tries: int = REPLACE_WAIT_TRIES,
    interval: float = REPLACE_WAIT_S,
) -> dict[str, Any]:
    """Keep the instance, or rent the best value offer that meets the policy.

    ``action`` is ``alive`` (nothing to do), ``created`` (a contract exists; the
    row is present once the endpoint maps), ``missing`` (gone, replacement off),
    ``no_offer`` (the floors matched nothing), or ``error``. The caller decides
    whether to POST; this function never renders.
    """
    listing = fetch_records(key, sender=sender)
    if listing.get("status") != 200:
        return {
            "action": "error",
            "message": f"could not list the account's instances: {listing.get('error')}",
        }
    if listing.get("truncated"):
        return {
            "action": "error",
            "message": (
                "the account's instance list was truncated, so a destroyed "
                "instance could be hidden; Fetch instances and try again"
            ),
        }
    live = find_record(
        listing["instances"], endpoint=endpoint, instance_id=instance_id
    )
    if live is not None:
        mapped = instance_endpoint(live)
        if not mapped:
            state = str(
                live.get("actual_status")
                or live.get("status")
                or live.get("cur_state")
                or "not running"
            ).strip()
            return {
                "action": "not_ready",
                "message": (
                    f"instance {live.get('id')} is {state}, not destroyed; "
                    "start it in the vast.ai console, then Generate again"
                ),
            }
        return {
            "action": "alive",
            "row": instance_row(live) or {},
            "message": "the instance is alive",
        }
    policy = clean_replace(settings)
    if not policy["enabled"]:
        return {
            "action": "missing",
            "message": "the instance is gone and automatic replacement is off",
        }
    found = search_offers(key, policy, sender=sender)
    if found.get("status") != 200:
        return {
            "action": "error",
            "message": f"could not search offers: {found.get('error')}",
        }
    offers = pick_offers(found["offers"], policy)
    if not offers:
        return {
            "action": "no_offer",
            "message": (
                "no offer meets the GPU, price, reliability, CUDA and link "
                "limits; widen them and press Replace again"
            ),
        }
    return _create_and_wait(
        key,
        offers,
        image=image,
        label=label,
        env=env,
        sender=sender,
        sleep=sleep,
        tries=tries,
        interval=interval,
    )
