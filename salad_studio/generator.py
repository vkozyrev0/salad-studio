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
from salad_studio import vast  # noqa: E402
from studio_log import (  # noqa: E402
    explain_http,
    prompt_url,
    ready_url,
    summarize_payload,
)

# Top-level, like studio_log and request_json above: the app and the tests must
# share ONE salad_queue module object, or an Attempt made in one copy of the
# module is not an Attempt to the other.
import salad_queue  # noqa: E402

class ContainerDown(RuntimeError):
    """The request's container is not running, so nothing was POSTed.

    Raised instead of a plain ``RuntimeError`` so the press can report a refusal
    rather than a failed render: no transport attempt was made, and the message
    is the one the press itself gives (``salad_queue.container_down_refusal``).
    A container that answered and then failed still raises ``RuntimeError``.
    """


_RETRY_CODES = (502, 503, 504, 521, 522, 523, 524)
# The GET /ready probe retries on every one of those, 504 and 524 included: a
# probe submits no work, so asking again cannot duplicate a render. The POST is
# different and goes through salad_queue, which treats 504/524 as terminal.
_PROMPT_TIMEOUT_S = 180
# The readiness wait covers a **cold** container start, which is the whole point
# of it: a stopped group has to be allocated a GPU, pull the image if this node
# has never run it, boot Comfy and finish the Hugging Face prefetch before
# /ready answers. That is minutes, not seconds, and the prefetch dominates it:
# measured 2026-09-26, one group's replica was still fetching flux2-vae.safetensors
# ten minutes in, the other group's replica took 25-30 minutes from its
# deployment's start_time before it served, and a spawn has been seen to run past
# an hour. So the wait covers about ninety minutes.
#
# It widens as it goes: a warm replica answers the first probe, so the early ones
# stay close together, and each later one waits longer (10 s, then 30 s, then
# 60 s). That is 118 requests for ninety minutes of coverage, where a flat 10 s
# would be 540 - and while a container has no ready replica every answer is the
# same 503 page, so asking for it ten times a minute says nothing new. The probes
# and the sleep go through the injected transport and clock, so tests drive the
# whole budget without waiting.
_READY_SLEEP_S = 10
_READY_SLEEP_AFTER = 15
_READY_SLEEP_MID_S = 30
_READY_SLEEP_MID_AFTER = 45
_READY_SLEEP_MAX_S = 60
_READY_TRIES = 118
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

def ready_sleep_s(attempt: int) -> int:
    """How long to wait before the next readiness probe.

    ``attempt`` is the 0-based index of the probe that just failed. The first
    probes are close together because a warm replica answers one of them at once;
    after that each one waits longer, because from there on the answer is the same
    "replica unavailable" page until the boot finishes.
    """
    if attempt < _READY_SLEEP_AFTER:
        return _READY_SLEEP_S
    if attempt < _READY_SLEEP_MID_AFTER:
        return _READY_SLEEP_MID_S
    return _READY_SLEEP_MAX_S


def ready_budget_s() -> int:
    """How long the whole readiness wait covers, in seconds.

    Summed from the interval table rather than written down twice, so the budget
    a failure message names is the one the loop actually spends: the loop sleeps
    before every probe but the last, so the table's last interval is never spent.
    """
    return sum(ready_sleep_s(attempt) for attempt in range(_READY_TRIES - 1))


def wait_gateway_ready(
    gateway: str,
    key: str,
    *,
    on_log: Any | None = None,
    line: str = "",
    state: Any | None = None,
) -> None:
    """GET /ready until 200. 404 means no probe endpoint. Continue to /prompt.

    ``state()`` (optional) reports the group's own state, and it is what tells
    the two kinds of 404 apart: a **booting** replica answers 404 because the
    route is not registered yet, while a running one that has no probe endpoint
    answers the same 404 and should not be waited on. Without ``state`` the 404
    keeps its old meaning ("no probe endpoint").

    Raises when the budget runs out with the container still not answering, and
    names the profile and gateway in that failure so the window can say which
    container the request was waiting for.
    """
    def _log(level: str, message: str) -> None:
        if on_log is not None:
            on_log(level, message)

    def _state() -> str:
        if state is None:
            return ""
        try:
            return str(state() or "").strip().lower()
        except Exception:  # noqa: BLE001 - an unreadable state is "", not a crash
            return ""

    url = ready_url(gateway)
    who = f"profile {line!r} ({gateway})" if line else gateway
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
            group = _state()
            if state is None or group == "running":
                _log("warn", "GET /ready HTTP 404, no probe endpoint; will POST /prompt")
                return
            # The group is not running, so this 404 is the route not being
            # registered yet: the replica is still coming up.
            if attempt + 1 < _READY_TRIES:
                _log(
                    "warn",
                    f"GET {url} HTTP 404 while the group reads {group or 'unknown'}; "
                    f"still starting, retry in {ready_sleep_s(attempt)}s",
                )
                salad_gen.time.sleep(ready_sleep_s(attempt))
                continue
            # Last attempt, replica still booting: fall out so the tail names
            # the probe count and the budget it spent.
            _log("error", msg)
            break
        if last_code in _RETRY_CODES and attempt + 1 < _READY_TRIES:
            _log("warn", msg + f"  retry in {ready_sleep_s(attempt)}s")
            salad_gen.time.sleep(ready_sleep_s(attempt))
            continue
        if last_code not in _RETRY_CODES:
            _log("warn", msg + "  will POST /prompt anyway")
            return
        # Last attempt on a retry code: fall out for the tail below.
        _log("error", msg)
        break
    msg = explain_http(int(last_code), last_body, url, method="GET")
    _log("error", msg)
    raise RuntimeError(
        f"{msg}  (pre-probe /ready failed for {who} after {_READY_TRIES} probes over "
        f"~{ready_budget_s() // 60} minutes; last status HTTP {int(last_code)})"
    )


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


def poll_history_image(
    fetch: Any,
    url: str,
    prompt_id: str,
    *,
    on_log: Any | None = None,
    tries: int = 24,
    sleep_s: int = 8,
    pick: Any | None = None,
) -> Any | None:
    """Poll a Comfy ``/history/{id}`` URL until it carries an image.

    ``fetch(url)`` performs one GET and returns ``(status, body)``, so the Salad
    path passes its keyed transport and the vast path a keyless one. ``pick``
    decides what counts as the plate in one answer: the default is the base64 a
    Salad wrapper carries, and the vast path passes one that also accepts a
    native ComfyUI file record (which the caller resolves through ``/view``). A
    non-200 answer, a body that is not JSON and an entry with no image all just
    wait for the next try: the render is still running until Comfy says
    otherwise.
    """
    finder = pick or first_image_b64

    def _log(level: str, message: str) -> None:
        if on_log is not None:
            on_log(level, message)

    for attempt in range(tries):
        _log("http", f"GET {url}  {attempt + 1}/{tries}")
        code, body = fetch(url)
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
        found = finder(blob if isinstance(blob, dict) else {})
        if found:
            return found
        if isinstance(blob, dict):
            st = blob.get("status") if isinstance(blob.get("status"), dict) else {}
            # Only "error" is terminal. An entry that is present but not
            # completed is the render still running, which is the whole reason
            # this polls; `and` binds tighter than `or`, so testing
            # `completed is False` beside a status string ended the wait on the
            # first in-flight entry it saw.
            if st.get("status_str") == "error":
                _log("error", f"history status {st}")
                return None
        salad_gen.time.sleep(sleep_s)
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
    """Poll Comfy ``/history/{id}`` on a Salad gateway for a prompt_id answer."""
    base = (gateway or "").rstrip("/")
    return poll_history_image(
        lambda url: salad_gen._req(url, key, timeout=30),
        f"{base}/history/{prompt_id}",
        prompt_id,
        on_log=on_log,
        tries=tries,
        sleep_s=sleep_s,
    )


def native_image_file(data: Any) -> dict[str, str] | None:
    """The first native ComfyUI image record in an answer, or None.

    A plain ComfyUI answers ``/history`` with **file records**
    (``{"filename", "subfolder", "type"}``) rather than base64: the image is
    saved inside the container and fetched from ``/view``. Resolving that needs
    the instance, so this returns the record and the caller does the GET.
    """
    outputs = data.get("outputs") if isinstance(data, dict) else None
    if not isinstance(outputs, dict):
        return None
    for node in outputs.values():
        if not isinstance(node, dict):
            continue
        for img in node.get("images") or []:
            if isinstance(img, dict) and img.get("filename"):
                return {
                    "filename": str(img["filename"]),
                    "subfolder": str(img.get("subfolder") or ""),
                    "type": str(img.get("type") or "output"),
                }
    return None


def fetch_view_image(
    base: str, info: dict[str, str], *, sender: Any | None = None, on_log: Any | None = None
) -> str:
    """GET a native ComfyUI ``/view`` image and return it as base64 text."""
    def _log(level: str, message: str) -> None:
        if on_log is not None:
            on_log(level, message)

    url = vast.view_url(base, info)
    _log("http", f"GET {url}")
    code, body = vast.get_url(url, sender=sender)
    if int(code) != 200 or not body:
        raise RuntimeError(f"GET {url} HTTP {code}: the plate could not be fetched")
    return salad_gen.base64.b64encode(body).decode("ascii")


# The plate files this app writes. A Salad wrapper answers with a JPEG
# (``convert_output``), while a plain ComfyUI saves what its graph says, which is
# a PNG by default; the gallery, the history strip and Clear read both.
PLATE_GLOBS: tuple[str, ...] = ("studio_*.jpg", "studio_*.png")


def plate_suffix(data: bytes) -> str:
    """The extension the plate's own bytes call for: ``.png`` or ``.jpg``."""
    return ".png" if data.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg"


def write_plate(raw: str, out_dir: Path) -> Path:
    """Decode one accepted image and write it as ``studio_<ms>.<ext>``.

    Both engines end here: the accepted response carries the plate as base64,
    sometimes behind a ``data:`` URL. The extension follows the bytes, so a file
    is never labelled as something it is not.
    """
    if isinstance(raw, str) and raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    data = salad_gen.base64.b64decode(raw)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"studio_{int(time.time() * 1000)}{plate_suffix(data)}"
    out.write_bytes(data)
    return out


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
    for method, extra, last in (("HEAD", {}, False), ("GET", {"Range": "bytes=0-0"}, True)):
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
            # A HEAD transport failure is inconclusive on its own, so the ranged
            # GET below still runs. The GET is the last method: with neither
            # answering, fall out for the summary rather than this pass's own
            # reason, which names only one of the two.
            if last:
                break
            continue
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


def _attempt_error(attempt: salad_queue.Attempt, url: str, job: salad_queue.Job) -> str:
    """Why a queued request produced no plate."""
    if attempt.error and not attempt.body:
        # A failure that never reached the container (the readiness wait, a
        # refused start) carries its own message, which names the profile and
        # the gateway; there is no transport body to explain.
        return attempt.error
    if attempt.status:
        msg = explain_http(attempt.status, attempt.body, url)
        return f"{msg}  ({attempt.error})" if attempt.error else msg
    return f"POST {url} never answered: {attempt.error or job.reason or 'no response'}"


def prepare_body(
    payload: dict[str, Any] | str,
    *,
    on_log: Any | None = None,
    label: str = "Salad",
) -> dict[str, Any]:
    """The body a Comfy replica is POSTed, built from the Prompt Editor JSON.

    Both engines POST the same graph, so the work between the editor's JSON and
    the bytes on the wire lives here once: attach the Civitai token the graph's
    LoRA downloads need, drop the node types the replica is known to lack, and
    check the LoRA URLs while that is still cheap (a dead URL otherwise surfaces
    as an opaque 524 after the GPU has done the work). ``label`` only names the
    engine in the log line.
    """
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
                f"{label} POST omits replica-missing node types "
                "(editor graph unchanged).",
            )
    if isinstance(body_obj.get("prompt"), dict):
        # Check the URLs on the compat-stripped prompt: never probe a LoRA the
        # replica will not be asked for. Nothing is downloaded here. The replica
        # fetches each LoRA itself when the Comfy graph runs, using the ?token=
        # that authorize_civitai_urls put on the node's lora_name.
        check_lora_urls(body_obj["prompt"], on_log=_log)
    return body_obj


def generate_from_payload(
    *,
    gateway: str,
    key: str,
    payload: dict[str, Any] | str,
    out_dir: Path,
    on_log: Any | None = None,
    queue: salad_queue.SaladQueue | None = None,
    line: str = "",
    checksum: str = "",
    ts: int | None = None,
    history_key: str = "",
) -> Path:
    """POST the Prompt Editor JSON to Salad ``/prompt`` and write a JPEG.

    The POST goes through ``queue`` (the process-wide one by default), on the
    line named by ``line``: the profile whose container serves this graph. Jobs
    on other lines run beside it, jobs on this line wait their turn, and one the
    container cannot serve yet is retried there. ``checksum`` is the caller's
    digest of the request, carried on the job so the press that submitted it can
    recognise a repeat of the queue's head (see ``salad_queue.request_checksum``).
    """
    def _log(level: str, message: str) -> None:
        if on_log is not None:
            on_log(level, message)

    line_queue = queue if queue is not None else salad_queue.shared()
    body_obj = prepare_body(payload, on_log=on_log, label="Salad")
    blob = salad_gen.json.dumps(body_obj).encode()
    url = prompt_url(gateway)
    _log("http", f"POST {url}  {len(blob)} bytes  {summarize_payload(body_obj)}")

    def render_once() -> salad_queue.Attempt:
        """One submission: POST /prompt, then resolve the image it accepted.

        ``accepted`` turns True the moment the container answers 200, which is
        what stops the queue from POSTing the job a second time: a re-POST of an
        accepted prompt renders a duplicate plate. Everything after that answer
        is therefore reported as an accepted failure, never as a retry.
        """
        _log("http", f"POST {url}  timeout={_PROMPT_TIMEOUT_S}s")
        try:
            code, body = salad_gen._req(url, key, data=blob, timeout=_PROMPT_TIMEOUT_S)
        except OSError as e:
            # A POST that times out may already be a render. The queue reads
            # status 0 as busy and retries it, which would submit the plate a
            # second time, so an unanswered POST is terminal like 504/524.
            return salad_queue.Attempt(
                status=524,
                error=(
                    f"POST {url} did not answer within {_PROMPT_TIMEOUT_S}s "
                    f"({type(e).__name__}); the container may still be rendering "
                    "it, so it is not re-sent"
                ),
            )
        code = int(code)
        if code != 200:
            return salad_queue.Attempt(status=code, body=body)
        _log("ok", f"HTTP 200 from {url}")
        try:
            data = salad_gen.json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return salad_queue.Attempt(
                status=code, body=body, accepted=True, error="the response is not JSON"
            )
        _log(
            "debug",
            f"/prompt keys={list(data)[:16] if isinstance(data, dict) else type(data)}",
        )
        raw = first_image_b64(data)
        if not raw and isinstance(data, dict) and data.get("prompt_id"):
            pid = str(data.get("prompt_id"))
            errs = data.get("node_errors") or {}
            if errs:
                return salad_queue.Attempt(
                    status=code,
                    body=body,
                    accepted=True,
                    error=f"Comfy node_errors for {pid}: {json.dumps(errs)[:800]}",
                )
            _log(
                "info",
                f"Comfy queued prompt_id={pid}; polling /history "
                "(wrapper returned no images[])",
            )
            raw = wait_history_image(gateway, key, pid, on_log=_log)
        if not raw:
            keys = list(data)[:16] if isinstance(data, dict) else type(data)
            return salad_queue.Attempt(
                status=code,
                body=body,
                accepted=True,
                error=f"no images in the response; keys={keys}",
            )
        return salad_queue.Attempt(status=code, body=body, accepted=True, result=raw)

    def dispatch_once(_job: salad_queue.Job) -> salad_queue.Attempt:
        """Ask for this request's container, wait for it, then submit once.

        This runs *inside* the job, after the queue has taken the request, so the
        row is in the Queue page for the whole of a cold start: the wait is
        minutes, and a request that is not in the queue looks like one that never
        happened. The queue reads the group's state every time, so a container
        that went down since the press is refused here rather than started; a
        container that is still coming up is waited for.

        A container that never answers ends the job here. 504 is terminal to the
        queue, so it does not retry a wait that already ran its whole budget, and
        the message names the profile, the gateway and the last status seen.
        """
        refusal = line_queue.ensure_container(line, gateway) if line else ""
        if refusal:
            # No log here: the queue logs this refusal on its own line, and the
            # press reports it once. Two lines with the same sentence is what
            # made one press look like four failures.
            return salad_queue.Attempt(status=504, error=refusal)
        try:
            wait_gateway_ready(
                gateway,
                key,
                on_log=_log,
                line=line,
                state=(lambda: line_queue.group_state(line, gateway)) if line else None,
            )
        except RuntimeError as e:
            _log("error", str(e))
            return salad_queue.Attempt(status=504, error=str(e))
        return render_once()

    job = line_queue.deliver(
        {"gateway": gateway, "url": url, "bytes": len(blob), "profile": line, "ts": ts,
         "history_key": history_key},
        dispatch_once,
        line=line,
        ensure=False,
        checksum=checksum,
    )
    attempt = job.result if isinstance(job.result, salad_queue.Attempt) else salad_queue.Attempt()
    if job.state != salad_queue.ACCEPTED:
        msg = _attempt_error(attempt, url, job)
        if line and msg == salad_queue.container_down_refusal(line, gateway):
            # The press refuses a group the badge says is stopped, so this is the
            # race: the group went down between the badge read and the dispatch.
            raise ContainerDown(msg)
        _log("error", msg)
        raise RuntimeError(msg)
    out = write_plate(attempt.result, out_dir)
    _log("ok", f"wrote {out}  {out.stat().st_size} bytes")
    return out


def generate_from_vast(
    *,
    endpoint: str,
    payload: dict[str, Any] | str,
    out_dir: Path,
    on_log: Any | None = None,
    sender: Any | None = None,
    timeout: int = _PROMPT_TIMEOUT_S,
    queue: salad_queue.SaladQueue | None = None,
    line: str = "",
    checksum: str = "",
    ts: int | None = None,
    history_key: str = "",
) -> Path:
    """POST the Prompt Editor JSON to a vast.ai instance's ComfyUI and write a JPEG.

    The vast half of Generate: the same body preparation and the same
    accepted-image transform the Salad path uses, with the instance's own
    ``/prompt`` as the target instead of a Salad gateway. There is no readiness
    wait and no container to start: the instance is the user's own machine. The
    POST still goes through ``queue`` on the line named by ``line``, so the
    request appears on the Queue page, waits its turn, and a busy instance is
    retried there. ``accepted`` turns True the moment the instance answers 200,
    which is what stops a retry from duplicating a render it already took.

    ``sender(request, timeout)`` replaces the transport, so a test drives a real
    POST through a recorded request. No token is sent to the instance — the
    vast.ai key only ever authenticates the control API — so ``sender`` sees a
    request that carries none.
    """
    def _log(level: str, message: str) -> None:
        if on_log is not None:
            on_log(level, message)

    base = vast.normalize_endpoint(endpoint)
    if not base:
        raise RuntimeError(
            "No vast.ai instance is selected. Add one under Vast.ai instances on "
            "the Config page and select it, then Generate again."
        )
    body_obj = prepare_body(payload, on_log=on_log, label="Vast")
    blob = salad_gen.json.dumps(body_obj).encode()
    url = vast.prompt_url(base)
    _log("http", f"POST {url}  {len(blob)} bytes  {summarize_payload(body_obj)}")
    line_queue = queue if queue is not None else salad_queue.shared()

    def render_once() -> salad_queue.Attempt:
        """One submission: POST /prompt, then resolve the image it accepted.

        ``accepted`` turns True the moment the instance answers 200, which is
        what stops the queue from POSTing the job a second time: a re-POST of an
        accepted prompt renders a duplicate plate. Everything after that answer
        is therefore reported as an accepted failure, never as a retry.
        """
        _log("http", f"POST {url}  timeout={timeout}s")
        code, body = vast.post_prompt(base, blob, sender=sender, timeout=timeout)
        code = int(code)
        if code == 0:
            # The instance did not answer the POST. The request may still have
            # reached it, so a retry could render the plate twice; terminal.
            return salad_queue.Attempt(
                status=524,
                error=(
                    f"POST {url} got no answer within {timeout}s; the instance "
                    "may still be rendering it, so it is not re-sent"
                ),
            )
        if code != 200:
            return salad_queue.Attempt(status=code, body=body)
        _log("ok", f"HTTP 200 from {url}")
        try:
            data = salad_gen.json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return salad_queue.Attempt(
                status=code,
                body=body,
                accepted=True,
                error=f"POST {url} answered 200 with a body that is not JSON",
            )
        raw: Any = first_image_b64(data) or native_image_file(data)
        if not raw and isinstance(data, dict) and data.get("prompt_id"):
            pid = str(data.get("prompt_id"))
            errs = data.get("node_errors") or {}
            if errs:
                return salad_queue.Attempt(
                    status=code,
                    body=body,
                    accepted=True,
                    error=f"Comfy node_errors for {pid}: {json.dumps(errs)[:800]}",
                )
            _log(
                "info",
                f"Comfy queued prompt_id={pid}; polling /history "
                "(wrapper returned no images[])",
            )
            raw = poll_history_image(
                lambda u: vast.get_url(u, sender=sender),
                f"{base}/history/{pid}",
                pid,
                on_log=_log,
                # A native ComfyUI keeps the plate in the container and names it in
                # /history, so accept that record as well as a wrapper's base64.
                pick=lambda hist: first_image_b64(hist) or native_image_file(hist),
            )
        if isinstance(raw, dict):
            try:
                raw = fetch_view_image(base, raw, sender=sender, on_log=_log)
            except RuntimeError as e:
                return salad_queue.Attempt(
                    status=code, body=body, accepted=True, error=str(e)
                )
        if not raw:
            keys = list(data)[:16] if isinstance(data, dict) else type(data)
            return salad_queue.Attempt(
                status=code,
                body=body,
                accepted=True,
                error=f"no images in the response from {url}; keys={keys}",
            )
        return salad_queue.Attempt(status=code, body=body, accepted=True, result=raw)

    def dispatch_once(_job: salad_queue.Job) -> salad_queue.Attempt:
        return render_once()

    job = line_queue.deliver(
        {"endpoint": base, "profile": line, "ts": ts, "history_key": history_key},
        dispatch_once,
        line=line,
        ensure=False,
        checksum=checksum,
    )
    attempt = (
        job.result if isinstance(job.result, salad_queue.Attempt) else salad_queue.Attempt()
    )
    if job.state != salad_queue.ACCEPTED:
        msg = attempt.error if attempt.error else _attempt_error(attempt, url, job)
        _log("error", msg)
        raise RuntimeError(msg)
    if attempt.result is None:
        # The instance accepted the POST (so it is not retried) but the answer
        # carried no plate. Report the attempt's own reason instead of handing
        # None to the image decoder, which would only raise a TypeError.
        msg = attempt.error if attempt.error else _attempt_error(attempt, url, job)
        _log("error", msg)
        raise RuntimeError(msg)
    out = write_plate(attempt.result, out_dir)
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
    files = [path for pattern in PLATE_GLOBS for path in out_dir.glob(pattern)]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
