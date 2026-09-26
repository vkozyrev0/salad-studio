"""Probe the Salad replica and matching container group for Config's gateway."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from salad_gen import UA, _req
from studio_log import explain_http, ready_url

ORG = "life-sim"
PROJECT = "default"
API = "https://api.salad.com/api/public"


def _api_request(
    method: str, url: str, key: str, data: dict[str, Any] | None = None
) -> tuple[int, Any]:
    headers = {
        "Salad-Api-Key": key,
        "accept": "application/json",
        "User-Agent": UA,
    }
    body = None
    if data is not None:
        headers["content-type"] = "application/merge-patch+json"
        body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read()
            parsed = json.loads(raw.decode() or "{}") if raw else {}
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw[:400]}
        return e.code, parsed
    except urllib.error.URLError as e:
        return 0, {"error": str(e.reason if getattr(e, "reason", None) else e)}


def _api_json_post(url: str, key: str, data: dict[str, Any]) -> tuple[int, Any]:
    headers = {
        "Salad-Api-Key": key,
        "accept": "application/json",
        "content-type": "application/json",
        "User-Agent": UA,
    }
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read()
            parsed = json.loads(raw.decode() or "{}") if raw else {}
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw[:400]}
        return e.code, parsed
    except urllib.error.URLError as e:
        return 0, {"error": str(e.reason if getattr(e, "reason", None) else e)}


def _api_get(url: str, key: str) -> tuple[int, Any]:
    return _api_request("GET", url, key)


def _strip_group(g: dict[str, Any]) -> dict[str, Any]:
    c = dict(g.get("container") or {})
    c.pop("environment_variables", None)
    net = dict(g.get("networking") or {})
    net.pop("auth", None)
    st = dict(g.get("current_state") or {})
    return {
        "name": g.get("name"),
        "display_name": g.get("display_name"),
        "version": g.get("version"),
        "replicas": g.get("replicas"),
        "pending_change": g.get("pending_change"),
        "status": st.get("status"),
        "description": st.get("description"),
        "counts": st.get("instance_status_counts"),
        "image": c.get("image"),
        "dns": net.get("dns"),
        "port": net.get("port"),
    }


def _strip_instance(it: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": it.get("id") or it.get("instance_id"),
        "machine_id": it.get("machine_id"),
        "state": it.get("state") or it.get("status"),
        "ready": it.get("ready"),
        "started": it.get("started"),
        "pulling_progress": it.get("pulling_progress"),
        "version": it.get("version"),
        "update_time": it.get("update_time"),
        "gpu": it.get("gpu") or it.get("gpu_class") or it.get("gpu_class_name"),
    }


def find_group_by_gateway(
    gateway: str,
    key: str,
    *,
    sender: Any | None = None,
    group: str = "",
) -> dict[str, Any] | None:
    """The Salad group whose DNS is this gateway, or None.

    ``group`` short-circuits the lookup when the caller already knows the name,
    and ``sender`` replaces the transport, so a test drives this with a recorded
    request instead of a live call.
    """
    send = sender or _api_request
    list_url = f"{API}/organizations/{ORG}/projects/{PROJECT}/containers"

    def get(url: str) -> tuple[int, Any]:
        # With no explicit sender this goes through _api_get, which is the seam
        # the rest of this module's callers and tests patch.
        if sender is not None:
            return send("GET", url, key, None)
        return _api_get(url, key)

    if group:
        code, data = get(f"{list_url}/{group}")
        return data if code == 200 and isinstance(data, dict) else None
    host = (urlparse((gateway or "").strip()).hostname or "").lower()
    if not host:
        return None
    code, data = get(list_url)
    if code != 200 or not isinstance(data, dict):
        return None
    for g in data.get("items") or []:
        if not isinstance(g, dict):
            continue
        dns = str((g.get("networking") or {}).get("dns") or "").lower()
        if dns == host:
            return g
    return None


def _probe_fields(probe: Any, *, path: str, port: int) -> dict[str, Any]:
    probe = probe if isinstance(probe, dict) else {}
    http = probe.get("http") if isinstance(probe.get("http"), dict) else {}
    return {
        "path": str(http.get("path") or path),
        "port": int(http.get("port") or port),
        "initial_delay_seconds": int(probe.get("initial_delay_seconds") or 0),
        "period_seconds": int(probe.get("period_seconds") or 10),
        "timeout_seconds": int(probe.get("timeout_seconds") or 5),
        "failure_threshold": int(probe.get("failure_threshold") or 3),
    }


def policy_from_group(group: dict[str, Any]) -> dict[str, Any]:
    c = group.get("container") or {}
    res = c.get("resources") or {}
    countries = group.get("country_codes") or []
    if not isinstance(countries, list):
        countries = []
    return {
        "group_name": group.get("name"),
        "version": group.get("version"),
        "image": c.get("image") or "",
        "gpu_classes": list(res.get("gpu_classes") or []),
        "country_codes": [str(x).lower() for x in countries],
        "startup": _probe_fields(
            group.get("startup_probe"), path="/health", port=3000
        ),
        "readiness": _probe_fields(
            group.get("readiness_probe"), path="/ready", port=3000
        ),
    }


STARTUP_EXPLAIN = (
    "After the container process starts, Salad waits {delay}s, then GET {path} "
    "on port {port} every {period}s (each try may last up to {timeout}s). "
    "{fail} failures in a row (~{total}s from start) interrupt the instance "
    "(Startup Probe Failure). Klein's Hugging Face download must finish and "
    "Comfy must listen before that budget runs out."
)

READINESS_EXPLAIN = (
    "Once startup has passed, Salad GET {path} on port {port} every {period}s "
    "(timeout {timeout}s). The first probe is after {delay}s. {fail} failures "
    "in a row (~{window}s) mark the replica not ready for gateway traffic. "
    "Studio's Ready badge and Generate's /ready pre-probe use this path."
)


def explain_probe(kind: str, fields: dict[str, Any]) -> str:
    """Fill the Policy-tab blurb from current probe fields."""
    def _int(key: str, default: int) -> int:
        try:
            return int(fields.get(key) if fields.get(key) not in ("", None) else default)
        except (TypeError, ValueError):
            return default

    delay = _int("initial_delay_seconds", 0)
    period = _int("period_seconds", 10)
    timeout = _int("timeout_seconds", 5)
    fail = _clamp_fail(fields.get("failure_threshold"))
    path = str(fields.get("path") or ("/health" if kind == "startup" else "/ready"))
    port = _int("port", 3000)
    total = delay + fail * period
    window = fail * period
    tmpl = STARTUP_EXPLAIN if kind == "startup" else READINESS_EXPLAIN
    return tmpl.format(
        delay=delay,
        path=path,
        port=port,
        period=period,
        timeout=timeout,
        fail=fail,
        total=total,
        window=window,
    )


def _clamp_fail(n: Any) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = 3
    return max(1, min(20, v))


def _pack_probe(fields: dict[str, Any], *, path: str) -> dict[str, Any]:
    return {
        "http": {
            "path": str(fields.get("path") or path),
            "port": int(fields.get("port") or 3000),
            "scheme": "http",
            "headers": [],
        },
        "initial_delay_seconds": int(fields.get("initial_delay_seconds") or 0),
        "period_seconds": int(fields.get("period_seconds") or 10),
        "timeout_seconds": int(fields.get("timeout_seconds") or 5),
        "success_threshold": 1,
        "failure_threshold": _clamp_fail(fields.get("failure_threshold")),
    }


def load_policy(gateway: str, key: str) -> tuple[dict[str, Any] | None, str | None]:
    """Fresh GET of the group that matches Config gateway (includes website edits)."""
    group = find_group_by_gateway(gateway, key)
    if group is None:
        return None, "No container group matches this gateway DNS."
    name = group.get("name")
    url = f"{API}/organizations/{ORG}/projects/{PROJECT}/containers/{name}"
    code, full = _api_get(url, key)
    if code == 200 and isinstance(full, dict):
        group = full
    elif code != 200:
        return None, f"Salad GET group HTTP {code}"
    return policy_from_group(group), None


def apply_policy(gateway: str, key: str, policy: dict[str, Any]) -> tuple[int, Any]:
    group = find_group_by_gateway(gateway, key)
    if group is None:
        return 404, {"error": "No container group matches this gateway DNS."}
    name = group.get("name")
    url = f"{API}/organizations/{ORG}/projects/{PROJECT}/containers/{name}"
    gcode, full = _api_get(url, key)
    if gcode == 200 and isinstance(full, dict):
        group = full
    patch: dict[str, Any] = {
        "startup_probe": _pack_probe(policy.get("startup") or {}, path="/health"),
        "readiness_probe": _pack_probe(policy.get("readiness") or {}, path="/ready"),
    }
    if "country_codes" in policy:
        codes = policy.get("country_codes") or []
        patch["country_codes"] = [str(c).lower() for c in codes]
    image = str(policy.get("image") or "").strip()
    gpus = policy.get("gpu_classes")
    if image or gpus is not None:
        container: dict[str, Any] = {}
        if image:
            container["image"] = image
        if gpus is not None:
            old = dict((group.get("container") or {}).get("resources") or {})
            container["resources"] = {
                "cpu": old.get("cpu"),
                "memory": old.get("memory"),
                "shm_size": old.get("shm_size"),
                "gpu_classes": list(gpus),
            }
            if old.get("storage_amount") is not None:
                container["resources"]["storage_amount"] = old.get("storage_amount")
        patch["container"] = container
    return _api_request("PATCH", url, key, patch)


def _instance_state(it: dict[str, Any]) -> str:
    return str(it.get("state") or it.get("status") or "").lower()


def _instance_pulling(it: dict[str, Any]) -> bool:
    st = _instance_state(it)
    if st in ("downloading", "creating", "allocating"):
        return True
    pct = pull_pct(it.get("pulling_progress"))
    return (not it.get("ready")) and pct is not None and pct < 100


def check_container(gateway: str, key: str) -> dict[str, Any]:
    """Match Config gateway DNS to a Salad group and probe /ready."""
    gw = (gateway or "").strip()
    host = (urlparse(gw).hostname or "").lower()
    out: dict[str, Any] = {
        "host": host,
        "ready_url": ready_url(gw),
        "ready_code": None,
        "ready_ok": False,
        "group": None,
        "instances": [],
        "error": None,
    }
    if not host:
        out["error"] = "Gateway URL is empty or has no host."
        return out
    list_url = f"{API}/organizations/{ORG}/projects/{PROJECT}/containers"
    code, data = _api_get(list_url, key)
    if code != 200 or not isinstance(data, dict):
        out["error"] = f"Salad API list groups HTTP {code}"
        return out
    match = None
    for g in data.get("items") or []:
        if not isinstance(g, dict):
            continue
        dns = str((g.get("networking") or {}).get("dns") or "").lower()
        if dns == host:
            match = g
            break
    if match is None:
        out["error"] = f"No container group in {ORG}/{PROJECT} has DNS {host}"
        return out
    name = match.get("name")
    gcode, gfull = _api_get(f"{list_url}/{name}", key)
    if gcode == 200 and isinstance(gfull, dict):
        match = gfull
    out["group"] = _strip_group(match)
    icode, idata = _api_get(f"{list_url}/{name}/instances", key)
    if icode == 200 and isinstance(idata, dict):
        out["instances"] = [
            _strip_instance(it)
            for it in (idata.get("instances") or [])
            if isinstance(it, dict)
        ]
    # Skip /ready while the replica is pulling, a stale 200 from the
    # previous instance (or a 20s 522 hang) must not freeze the badge.
    if not any(_instance_pulling(it) for it in out["instances"]):
        try:
            rcode, body = _req(ready_url(gw), key, timeout=5)
            out["ready_code"] = rcode
            out["ready_ok"] = rcode == 200
            out["ready_explain"] = explain_http(
                int(rcode), body, ready_url(gw), method="GET"
            )
        except Exception as e:
            out["ready_code"] = 0
            out["ready_explain"] = f"GET {ready_url(gw)} failed: {e}"
    return out


WORD_COLORS: dict[str, str] = {
    "Ready": "#8FBF9A",
    "Starting": "#E0A04A",
    "Creating": "#E0A04A",
    "Downloading": "#E0A04A",
    "Allocating": "#7EB8D4",
    "Deploying": "#E0A04A",
    "Stopped": "#8A9AAB",
    "Failed": "#D48A9A",
    "Down": "#D48A9A",
    "Unknown": "#8A9AAB",
}


def pull_pct(progress: Any) -> int | None:
    """Salad reports 0–1 or 0–100. Return 0–100 or None."""
    if progress is None:
        return None
    try:
        p = float(progress)
    except (TypeError, ValueError):
        return None
    if p <= 1.0:
        p *= 100.0
    return max(0, min(100, int(round(p))))


def color_for_status(word: str) -> str:
    key = (word or "Unknown").split()[0]
    return WORD_COLORS.get(key, WORD_COLORS["Unknown"])


def _instance_rank(it: dict[str, Any]) -> int:
    st = _instance_state(it)
    if st == "downloading":
        return 0
    if st in ("creating", "allocating") or _instance_pulling(it):
        return 1
    if not it.get("ready"):
        return 2
    return 3


def _instance_word(it: dict[str, Any]) -> str | None:
    st = _instance_state(it)
    pct = pull_pct(it.get("pulling_progress"))
    if st == "downloading":
        return f"Downloading {pct}%" if pct is not None else "Downloading"
    if st == "creating":
        if pct is not None and pct < 100:
            return f"Downloading {pct}%"
        return "Creating"
    if st == "allocating":
        return "Allocating"
    if not it.get("ready") and pct is not None and pct < 100:
        return f"Downloading {pct}%"
    if st in ("failed", "interrupted"):
        return "Failed"
    if st == "running" and it.get("ready"):
        return "Ready"
    if st == "running":
        return "Starting"
    return None


# Cloudflare edge codes meaning "the edge answered, the replica did not".
# Distinct from a replica that is merely still booting: /ready on a booting
# replica answers 404, because the route is not registered yet.
_ORIGIN_DOWN_CODES = (0, 520, 521, 522, 523, 524)


def _origin_down(info: dict[str, Any]) -> bool:
    return info.get("ready_code") in _ORIGIN_DOWN_CODES


def short_status(info: dict[str, Any]) -> str:
    """Short replica badge: Ready, Downloading 33%, Creating, …"""
    insts = list(info.get("instances") or [])
    if insts:
        insts.sort(key=_instance_rank)
        word = _instance_word(insts[0])
        if word == "Ready" and info.get("ready_ok") is False and info.get(
            "ready_code"
        ) not in (None, 404):
            # Salad still reports the instance running and ready, but Comfy did
            # not answer. An edge code means the replica is gone, not booting:
            # calling that "Starting" told the user a dead container was on its
            # way up. (measured 2026-09-22)
            return "Down" if _origin_down(info) else "Starting"
        if word:
            return word
    g = info.get("group") or {}
    gs = str(g.get("status") or "").lower()
    if gs == "stopped":
        return "Stopped"
    if gs == "failed":
        return "Failed"
    if gs in ("deploying", "pending"):
        return "Deploying"
    if info.get("ready_ok"):
        return "Ready"
    if gs == "running":
        return "Starting"
    if info.get("error"):
        return "Down"
    if _origin_down(info):
        return "Down"
    return "Unknown"


def format_status(info: dict[str, Any]) -> str:
    if info.get("error") and not info.get("group"):
        return str(info["error"])
    parts: list[str] = []
    g = info.get("group") or {}
    if g:
        parts.append(
            f"{g.get('display_name') or g.get('name')}  "
            f"{g.get('status') or '?'}  v{g.get('version')}"
        )
        if g.get("description"):
            parts.append(str(g["description"]))
        if g.get("counts"):
            parts.append(str(g["counts"]))
        if g.get("image"):
            img = str(g["image"])
            parts.append(img.rsplit("/", 1)[-1] if "/" in img else img)
    inst = info.get("instances") or []
    if inst:
        bits = []
        for it in inst:
            pull = it.get("pulling_progress")
            pull_s = f" pull={int(float(pull or 0) * 100)}%" if pull is not None else ""
            bits.append(
                f"{it.get('state')} ready={it.get('ready')} started={it.get('started')}{pull_s}"
            )
        parts.append("instance: " + "; ".join(bits))
    else:
        parts.append("no instances")
    if info.get("ready_ok"):
        parts.append("/ready 200")
    elif info.get("ready_explain"):
        parts.append(str(info["ready_explain"]))
    if info.get("error"):
        parts.append(str(info["error"]))
    return ", ".join(p for p in parts if p)


def list_gpu_classes(key: str) -> list[dict[str, Any]]:
    code, data = _api_get(f"{API}/organizations/{ORG}/gpu-classes", key)
    items = (data or {}).get("items") if isinstance(data, dict) else []
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        out.append({"id": it.get("id"), "name": it.get("name") or ""})
    return out


def recent_log_lines(
    key: str,
    *,
    group_name: str,
    instance_id: str | None = None,
    minutes: int = 20,
    limit: int = 40,
) -> list[str]:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=max(1, minutes))
    if instance_id:
        query = f'resource.labels.instance_id = "{instance_id}"'
    else:
        query = f'resource.labels.container_group_name = "{group_name}"'
    code, logs = _api_json_post(
        f"{API}/organizations/{ORG}/log-entries",
        key,
        {
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "page_size": limit,
            "sort_order": "desc",
            "query": query,
        },
    )
    if code != 200 or not isinstance(logs, dict):
        return []
    lines: list[str] = []
    for it in logs.get("items") or []:
        if not isinstance(it, dict):
            continue
        txt = it.get("text_log") or ""
        if not txt:
            jl = it.get("json_log")
            if isinstance(jl, dict):
                txt = str(jl.get("message") or jl.get("msg") or jl.get("log") or "")
            elif jl:
                txt = str(jl)
        one = " ".join(str(txt).split())
        if not one:
            continue
        t = str(it.get("time") or "")[11:19]
        lines.append(f"{t} {one[:240]}" if t else one[:240])
        if len(lines) >= limit:
            break
    return lines


def replica_detail(info: dict[str, Any]) -> str:
    """One line under the badge: GPU, pull %, last prefetch/log."""
    g = info.get("group") or {}
    insts = list(info.get("instances") or [])
    bits: list[str] = []
    if g.get("name"):
        bits.append(str(g.get("name")))
    if g.get("version") is not None:
        bits.append(f"v{g.get('version')}")
    if insts:
        it = sorted(insts, key=_instance_rank)[0]
        gpu = it.get("gpu")
        if gpu:
            bits.append(str(gpu))
        pct = pull_pct(it.get("pulling_progress"))
        st = _instance_state(it)
        if st == "downloading" and pct is not None:
            bits.append(f"image {pct}%")
        elif st == "running" and not it.get("ready"):
            bits.append("prefetch")
        log = str(info.get("last_log") or "").strip()
        if log:
            bits.append(log[:80])
    else:
        gs = str(g.get("status") or "")
        if gs:
            bits.append(gs)
        bits.append("no instance")
    if not info.get("ready_ok") and info.get("ready_explain"):
        # Say *why* the replica is not answering, a bare "Down" left the user
        # guessing between a restart, a bad gateway URL and a dead origin.
        first = str(info["ready_explain"]).split("\n")[0].strip()
        if first:
            bits.append(first[:120])
    return " · ".join(bits)


def generate_block_reason(info: dict[str, Any]) -> str | None:
    """Why Generate should not POST yet. None if Ready."""
    word = short_status(info)
    if word == "Ready" or (info.get("ready_ok") and word.split()[0] == "Ready"):
        return None
    detail = replica_detail(info)
    if word.startswith("Downloading"):
        return f"Replica is still pulling the Docker image ({word}). {detail}"
    if word in ("Allocating", "Deploying"):
        return f"No GPU yet ({word}). {detail}"
    if word in ("Creating", "Starting"):
        return (
            f"Replica is up but Comfy is not ready ({word}). "
            "Hugging Face prefetch may still be running. " + detail
        )
    if word in ("Stopped", "Failed", "Down"):
        return f"Replica is {word}. {detail}"
    return f"Replica is not Ready ({word}). {detail}"


def attach_last_log(info: dict[str, Any], key: str) -> dict[str, Any]:
    g = info.get("group") or {}
    name = str(g.get("name") or "")
    insts = info.get("instances") or []
    iid = None
    if insts:
        iid = sorted(insts, key=_instance_rank)[0].get("id")
    lines = recent_log_lines(
        key, group_name=name, instance_id=str(iid) if iid else None, minutes=20, limit=8
    )
    info["last_log"] = lines[0] if lines else ""
    info["log_lines"] = lines
    return info


def reallocate_instance(gateway: str, key: str) -> tuple[int, Any]:
    info = check_container(gateway, key)
    insts = info.get("instances") or []
    if not insts:
        return 404, {"error": "No instance to reallocate."}
    it = sorted(insts, key=_instance_rank)[0]
    iid = it.get("id")
    name = (info.get("group") or {}).get("name")
    if not iid or not name:
        return 404, {"error": "Missing instance or group name."}
    url = (
        f"{API}/organizations/{ORG}/projects/{PROJECT}/containers/"
        f"{name}/instances/{iid}/reallocate"
    )
    return _api_request("POST", url, key)


def _group_action(
    action: str,
    gateway: str,
    key: str,
    *,
    sender: Any | None = None,
    group: str = "",
) -> tuple[int, Any]:
    """``POST …/containers/{name}/{action}`` for the group behind ``gateway``.

    Salad answers a start or stop with 202 and no body; the group keeps its
    configuration and DNS, and a later start allocates new instances.
    """
    send = sender or _api_request
    name = group or str(
        (find_group_by_gateway(gateway, key, sender=sender) or {}).get("name") or ""
    )
    if not name:
        return 404, {"error": "No container group matches this gateway DNS."}
    url = f"{API}/organizations/{ORG}/projects/{PROJECT}/containers/{name}/{action}"
    return send("POST", url, key, None)


def start_container_group(
    gateway: str, key: str, *, sender: Any | None = None, group: str = ""
) -> tuple[int, Any]:
    """Start the group behind ``gateway``, so it can take a request."""
    return _group_action("start", gateway, key, sender=sender, group=group)


def stop_container_group(
    gateway: str, key: str, *, sender: Any | None = None, group: str = ""
) -> tuple[int, Any]:
    """Stop the group behind ``gateway``. Its configuration and DNS stay."""
    return _group_action("stop", gateway, key, sender=sender, group=group)


def group_is_running(
    gateway: str, key: str, *, sender: Any | None = None, group: str = ""
) -> bool | None:
    """Whether the group behind ``gateway`` has instances up.

    ``True`` running, ``False`` stopped, ``None`` when the answer is unknown (no
    group, no key, an API error, or a state in between such as pending or
    failed). The caller starts a container only on a definite ``False``, so an
    unknown answer leaves it alone rather than starting or stopping it twice.
    """
    found = find_group_by_gateway(gateway, key, sender=sender, group=group)
    if found is None:
        return None
    status = str((found.get("current_state") or {}).get("status") or "").lower()
    if status == "stopped":
        return False
    if status == "running":
        return True
    return None


class ContainerLifecycle:
    """The queue's handle on the containers it may start and stop.

    ``key_provider`` is called for every action, so the token the app stores is
    read when the action happens rather than captured at startup. ``sender``
    replaces the transport, the way the rest of this module is tested.
    """

    def __init__(self, key_provider: Any, *, sender: Any | None = None) -> None:
        self._key = key_provider
        self._sender = sender

    def _token(self) -> str:
        try:
            return str(self._key() or "")
        except Exception:  # noqa: BLE001 - no stored token is a refusal, not a crash
            return ""

    def is_running(self, profile: str, gateway: str) -> bool | None:
        key = self._token()
        if not key or not gateway:
            return None
        return group_is_running(gateway, key, sender=self._sender)

    def start(self, profile: str, gateway: str) -> tuple[int, str]:
        return self._act("start", profile, gateway)

    def stop(self, profile: str, gateway: str) -> tuple[int, str]:
        return self._act("stop", profile, gateway)

    def _act(self, action: str, profile: str, gateway: str) -> tuple[int, str]:
        key = self._token()
        if not key:
            return 401, "no Salad token is stored"
        if not gateway:
            return 404, f"profile {profile!r} has no gateway"
        # The group is resolved from the gateway's DNS: a profile name and a
        # Salad group name are not the same thing (profile "klein" is the group
        # "flux2-klein2"), so the DNS is the only reliable link between them.
        code, payload = _group_action(action, gateway, key, sender=self._sender)
        return int(code), _api_message(payload)


def _api_message(payload: Any) -> str:
    """The server's own words for a failed control-plane call."""
    if isinstance(payload, dict):
        for key in ("error", "detail", "title", "message"):
            value = payload.get(key)
            if isinstance(value, dict):
                value = value.get("message") or value.get("detail") or value.get("type")
            if isinstance(value, str) and value.strip():
                return value.strip()[:200]
        if payload.get("raw"):
            return str(payload["raw"])[:200]
    if isinstance(payload, str) and payload.strip():
        return payload.strip()[:200]
    return ""


def snapshot_gateway(gateway: str, key: str) -> dict[str, Any]:
    info = check_container(gateway, key)
    try:
        attach_last_log(info, key)
    except Exception:
        info["last_log"] = ""
    info["word"] = short_status(info)
    info["detail"] = replica_detail(info)
    info["block"] = generate_block_reason(info)
    return info

