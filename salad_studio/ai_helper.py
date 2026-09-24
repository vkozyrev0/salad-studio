"""DeepSeek-backed prompt help for the Prompt Assist page.

Window-free. Three pieces, each testable on its own:

- :func:`build_payload`, the request body sent to DeepSeek, carrying the five
  context inputs (editor positive/negative, adjusted positive/negative, the
  request JSON) plus the resolved weight findings.
- :func:`parse_reply`, a tolerant parser for the reply's adjusted prompts,
  raising :class:`ReplyError` when the reply has no usable prompts so the
  caller can surface the raw text instead of blanking the boxes.
- :func:`ask_deepseek`, the transport, with the HTTP send injectable at the
  boundary so tests assert the real request the app builds.

Three rules keep a *piece* of a reply from being taken for the whole reply.
They exist because a reasoning model (LM Studio's Ministral, DeepSeek's
reasoning ids) writes a trace before its answer, and the trace quotes things
that parse as JSON, this system prompt's own schema, a first draft:

1. **The transport waits for the whole body.** :func:`_http_send` reads to EOF
   and refuses a body shorter than the ``Content-Length`` the server promised;
   a body that streams despite ``stream: false`` is assembled from its frames.
2. **A reply cut off at the token limit is continued, not accepted.**
   ``finish_reason == "length"`` makes :func:`_collect` ask the model for the
   remainder (up to :data:`CONTINUE_ATTEMPTS` times) and stitch it on; only
   then is the text parsed. An exhausted budget raises :class:`AiError`.
3. **The last complete object wins.** :func:`parse_reply_full` scores every
   complete ``{...}`` in the reply and prefers one that carries the prompts
   explicitly over a quoted draft, and treats the schema's ``"..."``
   placeholders as no answer at all.
"""
from __future__ import annotations

import base64
import io
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

ENDPOINT = "https://api.deepseek.com/chat/completions"
# /models on this key lists deepseek-flash and deepseek-v4-pro; the retired
# deepseek-chat alias is gone, so keep the id here where it is easy to change.
MODEL = "deepseek-flash"
MAX_TOKENS = 4000
# A reasoning model spends this budget on its trace before it writes the JSON,
# so the answer regularly hits the cap. The reply is then continued rather than
# accepted half-written; see _collect.
CONTINUE_ATTEMPTS = 2
CONTINUE_PROMPT = (
    "Your previous answer was cut off by the output-token limit in the middle "
    "of a JSON object. Resume that same object exactly where it stopped: do NOT "
    "write `{` again, do not start a new object, do not repeat what you already "
    "wrote, and add no commentary. Output only the remaining characters."
)
# A reasoning model can spend the whole budget on its trace and write no answer
# at all; there is nothing to continue in that case, only an answer to demand.
ANSWER_NOW_PROMPT = (
    "Your reasoning used the entire output-token budget and no answer was "
    "written. Answer now, briefly, with ONLY the JSON object asked for, no "
    "further reasoning."
)
# Long context + a reasoning trace takes minutes, and a continued reply is sent
# more than once, so the whole call needs more than the old two minutes.
TIMEOUT_S = 300
USER_AGENT = "SaladStudio/1.0"

# LM Studio's local server is OpenAI-compatible. Its default base is
# http://localhost:1234/v1; the model id is whatever is loaded there, so it is
# discovered from /models instead of being hardcoded.
LOCAL_BASE_URL = "http://localhost:1234/v1"
LOCAL_MODEL_URL_TIMEOUT_S = 15
LOCAL_TIMEOUT_S = 600

SYSTEM_PROMPT = (
    "You are a prompt engineer for Flux.2 Klein image generation inside Salad "
    "Studio. You receive the current positive and negative prompt, a pair of "
    "adjusted prompts the artist has started editing, the raw ComfyUI request "
    "JSON, a resolved inventory of the checkpoints, LoRAs, CLIP and VAE that "
    "the request actually loads, an issue the artist reports with the last "
    "image, and sometimes that image itself.\n"
    "Rewrite the two adjusted prompts so the image matches the artist's intent "
    "while staying faithful to the loaded models:\n"
    "- THE REPORTED ISSUE IS THE HIGHEST PRIORITY. The rewritten prompts must "
    "directly fix it: describe what should be there, and add the failure to the "
    "negative prompt. Never write a prompt that could reproduce the reported "
    "defect.\n"
    "- If an image is attached, look at it first: name the visible defect you "
    "actually see, then target that defect (not a guess).\n"
    "- Keep the trigger words and style tokens the LoRAs need; if a LoRA's "
    "trigger is unknown, do not invent one.\n"
    "- Use only LoRAs and checkpoints listed as resolved and compatible with "
    "the replica. If an entry is unresolved or flagged incompatible, say so in "
    "the negative prompt's spirit rather than relying on it.\n"
    "- Keep the artist's own wording where it already works; improve, do not "
    "replace wholesale.\n"
    "- The negative prompt lists what to avoid; keep it short and specific.\n"
    'Reply with ONLY a JSON object of the form {"issue": "what is wrong with '
    'the image, or an empty string when none was given", "positive": "...", '
    '"negative": "..."} and no other text.'
)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
# The prompt keys, best match first. A bare "prompt" is the last resort: the
# context the model is shown is full of request JSON whose nodes carry prompts,
# so a quoted draft with a plain "prompt" key must never outrank an answer that
# names the two prompts outright.
_PRIMARY_ALIASES = {
    "positive": ("positive", "positive_prompt", "positive prompt"),
    "negative": ("negative", "negative_prompt", "negative prompt"),
    "issue": ("issue", "problem", "image_issue", "image issue", "defect", "findings"),
}
_LOOSE_ALIASES = {"positive": ("prompt",)}

# A model that reasons first often quotes this module's own system prompt back,
# including its ellipsis placeholders, before it writes its answer. Those
# must read as "no answer", not as the prompts "...".
_PLACEHOLDER_WORDS = frozenset(
    {
        "n/a", "na", "none", "null", "nil", "string", "text", "prompt",
        "positive prompt", "negative prompt", "your prompt", "example",
        "placeholder", "what is wrong", "what is wrong with the image",
    }
)
_SCHEMA_ISSUE_MARKERS = ("empty string when none", "when none was given")

# How many opening braces the restart recovery scans, counted from the end of
# the reply: the answer is near the end, and a reply that echoes a whole graph
# would otherwise cost a scan per brace.
_RECOVERY_STARTS = 400

# A data URL this size is roughly a 1024px JPEG; bigger plates are downscaled.
IMAGE_MAX_SIDE = 1024
IMAGE_QUALITY = 85
IMAGE_MIME = "image/jpeg"
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class AiError(RuntimeError):
    """The DeepSeek call itself failed (key, transport or HTTP status)."""


class ReplyError(ValueError):
    """The reply arrived but carried no usable adjusted prompts."""

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


def context_block(
    *,
    editor_positive: str = "",
    editor_negative: str = "",
    adjusted_positive: str = "",
    adjusted_negative: str = "",
    request_json: str = "",
    findings: str = "",
    issue: str = "",
    image_note: str = "",
) -> str:
    """The user message: the reported issue first, then all five inputs."""
    return (
        "=== IMAGE ISSUE REPORTED BY THE ARTIST (HIGHEST PRIORITY, fix this "
        "first, and never reproduce it) ===\n"
        f"{issue.strip() or '(none reported)'}\n\n"
        f"=== ATTACHED IMAGE ===\n{image_note.strip() or '(none attached)'}\n\n"
        "=== POSITIVE PROMPT (current, in the Prompt Editor) ===\n"
        f"{editor_positive}\n\n"
        "=== NEGATIVE PROMPT (current, in the Prompt Editor) ===\n"
        f"{editor_negative}\n\n"
        "=== ADJUSTED POSITIVE PROMPT (artist's draft) ===\n"
        f"{adjusted_positive}\n\n"
        "=== ADJUSTED NEGATIVE PROMPT (artist's draft) ===\n"
        f"{adjusted_negative}\n\n"
        "=== REQUEST JSON (the /prompt body that will be sent) ===\n"
        f"{request_json}\n\n"
        "=== RESOLVED CHECKPOINTS / LoRAs / CLIP / VAE ===\n"
        f"{findings}\n"
    )


def build_payload(
    *,
    editor_positive: str = "",
    editor_negative: str = "",
    adjusted_positive: str = "",
    adjusted_negative: str = "",
    request_json: str = "",
    findings: str = "",
    issue: str = "",
    image_data_url: str = "",
    model: str = MODEL,
    max_tokens: int = MAX_TOKENS,
) -> dict[str, Any]:
    """The DeepSeek chat-completions body for one Help press.

    Without an image the user message stays a plain string; with one it becomes
    the OpenAI-style content list the DeepSeek API accepts.
    """
    note = (
        "The last generated image is attached below, inspect it and name the "
        "defect you actually see."
        if image_data_url
        else ""
    )
    text = context_block(
        editor_positive=editor_positive,
        editor_negative=editor_negative,
        adjusted_positive=adjusted_positive,
        adjusted_negative=adjusted_negative,
        request_json=request_json,
        findings=findings,
        issue=issue,
        image_note=note,
    )
    content: Any = text
    if image_data_url:
        content = [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "max_tokens": max_tokens,
        "stream": False,
    }


def image_data_url(
    path: Any, *, max_side: int = IMAGE_MAX_SIDE, quality: int = IMAGE_QUALITY
) -> str:
    """A JPEG data URL for an image file, downscaled when it is large.

    Pillow is optional: without it the file's own bytes are sent, which the
    provider accepts for JPEG/PNG but costs more tokens.
    """
    target = Path(path)
    if not target.is_file():
        raise AiError(f"image not found: {target}")
    try:
        from PIL import Image
    except ImportError:
        raw = target.read_bytes()
        if len(raw) > MAX_IMAGE_BYTES:
            raise AiError(
                f"image is {len(raw) // 1024} KB and Pillow is not installed to "
                "downscale it"
            ) from None
        mime = "image/png" if target.suffix.lower() == ".png" else IMAGE_MIME
        return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    try:
        with Image.open(target) as im:
            im = im.convert("RGB")
            if max(im.size) > max_side:
                im.thumbnail((max_side, max_side))
            buffer = io.BytesIO()
            im.save(buffer, "JPEG", quality=quality)
    except OSError as e:
        raise AiError(f"image could not be read: {e}") from e
    return f"data:{IMAGE_MIME};base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def _is_placeholder(value: str) -> bool:
    """True for the schema's ``"..."`` and the other non-answers models echo."""
    text = (value or "").strip().strip("\"'`").strip()
    if not text:
        return True
    if not any(ch.isalnum() for ch in text):
        return True
    return text.lower() in _PLACEHOLDER_WORDS


def _clean(value: str, key: str = "") -> str:
    """A prompt value, with a placeholder or an echoed schema line emptied out."""
    text = (value or "").strip()
    if _is_placeholder(text):
        return ""
    if key == "issue" and any(mark in text.lower() for mark in _SCHEMA_ISSUE_MARKERS):
        return ""
    return text


def _pick(data: dict[str, Any], key: str) -> tuple[str, bool]:
    """The value for ``key``, and whether an explicit prompt key carried it."""
    groups = ((_PRIMARY_ALIASES[key], True), (_LOOSE_ALIASES.get(key, ()), False))
    for aliases, explicit in groups:
        for alias in aliases:
            for candidate in (alias, alias.replace("_", " "), alias.upper()):
                if candidate in data:
                    value = data[candidate]
                    if isinstance(value, (str, int, float)):
                        return str(value).strip(), explicit
    return "", True


def _from_json(text: str) -> dict[str, Any] | None:
    """The prompts in a complete JSON object, or None when there is no answer.

    ``explicit`` is False when the prompts were read from a loose alias, which
    is what lets :func:`parse_reply_full` prefer a real answer over a quoted
    draft that happens to carry a ``prompt`` key.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    # The wrapper is not a hint about which part is the answer when the loose
    # alias matched outside it, so keep the unwrapped object for the score.
    for wrapper in ("prompts", "result", "data"):
        inner = data.get(wrapper)
        if isinstance(inner, dict):
            data = inner
            break
    positive_raw, positive_explicit = _pick(data, "positive")
    negative_raw, negative_explicit = _pick(data, "negative")
    positive, negative = _clean(positive_raw), _clean(negative_raw)
    if not positive and not negative:
        return None
    return {
        "positive": positive,
        "negative": negative,
        "issue": _clean(_pick(data, "issue")[0], "issue"),
        "explicit": positive_explicit and negative_explicit,
    }


def _closing_span(text: str, start: int) -> str:
    """``text[start:i+1]`` up to the brace that closes the object, or "".

    The scan carries its own string state, so calling it at a later ``{``
    recovers an object that a cut-off string in front of it would otherwise
    swallow.
    """
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


def _json_objects(text: str) -> list[str]:
    """Every complete ``{...}`` that opens at the top level, in the order it closes.

    Braces inside strings do not count, so a prompt that contains one cannot
    split an object in half.
    """
    out: list[str] = []
    start = -1
    depth = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                out.append(text[start : i + 1])
                start = -1
    return out


def _recovered_objects(text: str, limit: int = _RECOVERY_STARTS) -> list[str]:
    """Objects found by restarting the scan at each ``{``, nearest the end first.

    A model asked to continue a cut reply often re-writes the object from the
    top instead of resuming it, which leaves an unterminated head in front of a
    complete answer. This is that recovery, bounded to the tail where the answer
    is, and only consulted when the ordinary scan found nothing to parse.
    """
    starts = [i for i, ch in enumerate(text) if ch == "{"]
    out: list[str] = []
    for start in reversed(starts[-limit:]):
        span = _closing_span(text, start)
        if span:
            out.append(span)
    out.reverse()
    return out


def _candidates(text: str) -> list[str]:
    """Every place the answer could be, most likely first.

    The whole reply wins when it *is* the object. After that the *last* fenced
    block and the *last* complete object come first: a reasoning model puts its
    answer after the trace, so anything it quoted earlier is a draft.
    """
    fences = [fence.strip() for fence in _FENCE.findall(text) if fence.strip()]
    return [text, *reversed(fences), *reversed(_json_objects(text))]


def _from_labels(text: str) -> tuple[str, str] | None:
    """Fall back to labelled sections, e.g. ``Positive prompt:`` / ``Negative:``."""
    pattern = re.compile(
        r"^[\s>*#-]*(positive|negative)\s*(?:prompt)?\s*[:\-]\s*(.*?)$",
        re.I | re.M,
    )
    hits = list(pattern.finditer(text))
    if not hits:
        return None
    found: dict[str, str] = {}
    for i, hit in enumerate(hits):
        key = hit.group(1).lower()
        if key in found:
            continue
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        body = text[hit.end(2) : end]
        found[key] = _clean((hit.group(2) + "\n" + body).strip())
    positive, negative = found.get("positive", ""), found.get("negative", "")
    if not positive and not negative:
        return None
    return {"positive": positive, "negative": negative, "issue": found.get("issue", "")}


def _best_json(candidates: Iterable[str]) -> dict[str, Any] | None:
    """The best-scoring object among the candidates, or None if none carries
    prompts. Iteration order breaks ties, so the caller passes them most-likely
    first and the scores are what actually ranks them."""
    best: dict[str, Any] | None = None
    best_score: tuple[int, int] | None = None
    for candidate in candidates:
        parsed = _from_json(candidate)
        if parsed is None:
            continue
        score = (
            int(bool(parsed["positive"])) + int(bool(parsed["negative"])),
            int(bool(parsed["explicit"])),
        )
        if best_score is None or score > best_score:
            best, best_score = parsed, score
    return best


def parse_reply_full(reply: str) -> dict[str, str]:
    """Pull (positive, negative, issue) out of a DeepSeek reply.

    A reasoning model writes a trace before its answer, and the trace quotes
    JSON, this module's own schema, a first draft. So every complete object in
    the reply is scored and the best one wins: the object that fills the most
    prompts, and that names them outright rather than through a bare ``prompt``
    key. Ties go to the candidate that appears later, because the answer comes
    after the trace.

    Raises :class:`ReplyError` when nothing usable is there, so the caller can
    surface the raw reply instead of silently emptying the boxes. ``issue`` is
    what the model saw wrong with the image, and may be empty.
    """
    text = (reply or "").strip()
    if not text:
        raise ReplyError("DeepSeek returned an empty reply", reply or "")
    best = _best_json(_candidates(text))
    if best is None:
        # Nothing at the top level parsed: look again for an object the model
        # restarted after a cut-off one, which the ordinary scan cannot see.
        best = _best_json(reversed(_recovered_objects(text)))
    if best is not None:
        return {
            "positive": best["positive"],
            "negative": best["negative"],
            "issue": best["issue"],
        }
    labelled = _from_labels(text)
    if labelled is not None:
        return labelled
    raise ReplyError("the reply carried no positive/negative prompts", text)


def parse_reply(reply: str) -> tuple[str, str]:
    """The adjusted (positive, negative) pair from a reply."""
    out = parse_reply_full(reply)
    return out["positive"], out["negative"]


def _http_send(
    request: urllib.request.Request, timeout: int
) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return int(resp.status), _read_body(resp)
    except urllib.error.HTTPError as e:
        try:
            return int(e.code), e.read()
        except OSError:
            return int(e.code), b""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        # Shared by the DeepSeek and local transports, so keep it neutral.
        raise AiError(f"model call failed: {type(e).__name__}: {e}") from e


def _read_body(resp: Any) -> bytes:
    """The response body, whole.

    Read to EOF and then check it against the ``Content-Length`` the server
    promised: a body that stops early is a piece of a reply, and a piece must
    never reach the parser as if it were the answer.
    """
    expected: int | None = None
    header = ""
    try:
        header = str(resp.headers.get("Content-Length") or "")
    except (AttributeError, TypeError, ValueError):
        header = ""
    if header.strip().isdigit():
        expected = int(header.strip())
    chunks: list[bytes] = []
    while True:
        chunk = resp.read(65536)
        if not chunk:
            break
        chunks.append(chunk)
    body = b"".join(chunks)
    if expected is not None and len(body) < expected:
        raise AiError(
            f"the reply was cut off in transit: {len(body)} of {expected} bytes "
            "arrived, so the answer would have been incomplete, press Help "
            "again"
        )
    return body


def request_for(api_key: str, payload: dict[str, Any]) -> urllib.request.Request:
    """The real HTTP request the Help button sends."""
    return urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )


def _sse_reply(text: str) -> dict[str, Any] | None:
    """Assemble a reply that arrived as stream frames despite ``stream: false``.

    Some servers (and proxies in front of them) stream anyway. Every ``data:``
    frame carries one delta; concatenating them is what "the whole reply" means
    there. ``None`` when the body holds no frames at all.
    """
    frames = [
        line[len("data:") :].strip()
        for line in text.splitlines()
        if line.startswith("data:")
    ]
    payloads = [f for f in frames if f and f != "[DONE]"]
    if not payloads:
        return None
    content: list[str] = []
    reasoning: list[str] = []
    finish = ""
    for payload in payloads:
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        choices = data.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            delta = delta if isinstance(delta, dict) else {}
            if delta.get("content"):
                content.append(str(delta["content"]))
            if delta.get("reasoning_content"):
                reasoning.append(str(delta["reasoning_content"]))
            if choice.get("finish_reason"):
                finish = str(choice["finish_reason"])
    if not content and not reasoning:
        return None
    return {
        "content": "".join(content),
        "reasoning": "".join(reasoning),
        "finish_reason": finish or "stop",
        # A stream that never sent its sentinel was closed mid-answer.
        "truncated": finish == "length" or not any(f == "[DONE]" for f in frames),
        "streamed": True,
        "parsed": True,
    }


def reply_info(body: bytes | str) -> dict[str, Any]:
    """What the transport actually received, in one shape for both backends.

    ``content`` is the assistant text, ``reasoning`` the trace a reasoning model
    emits before it, ``finish_reason`` the API's stop reason, and ``truncated``
    True when the answer was cut off by the token limit, the difference between
    a complete reply and its first chunk, which is what the caller must not
    confuse.
    """
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body or "")
    out: dict[str, Any] = {
        "content": "",
        "reasoning": "",
        "finish_reason": "",
        "truncated": False,
        "streamed": False,
        "parsed": False,
    }
    data: Any = None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        data = None
    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first.get("message"), dict) else {}
            out["content"] = str(message.get("content") or "")
            out["reasoning"] = str(message.get("reasoning_content") or "")
            out["finish_reason"] = str(first.get("finish_reason") or "")
            out["truncated"] = out["finish_reason"] == "length"
            out["parsed"] = True
            return out
        # A well-formed body with no choices is not a reply.
        return out
    if data is not None:
        return out
    streamed = _sse_reply(text)
    return streamed if streamed is not None else out


def content_of(body: bytes | str) -> str:
    """``choices[0].message.content`` from a chat-completions body."""
    return str(reply_info(body)["content"] or "").strip()


def _error_detail(body: bytes | str) -> str:
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return str(body).strip()[:300]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)[:300]
        if error:
            return str(error)[:300]
    return str(body).strip()[:300]


def _continuation_payload(payload: dict[str, Any], partial: str) -> dict[str, Any]:
    """The follow-up body that asks the model to finish what it was saying.

    With nothing written yet, a reasoning trace that ate the whole budget,
    there is no half-answer to continue, so the follow-up demands the answer
    instead of appending an empty assistant turn.
    """
    out = dict(payload)
    messages = [m for m in (payload.get("messages") or []) if isinstance(m, dict)]
    if partial.strip():
        messages.append({"role": "assistant", "content": partial})
        messages.append({"role": "user", "content": CONTINUE_PROMPT})
    else:
        messages.append({"role": "user", "content": ANSWER_NOW_PROMPT})
    out["messages"] = messages
    out["stream"] = False
    return out


def _collect(
    payload: dict[str, Any],
    *,
    sender: Callable[[urllib.request.Request, int], tuple[int, bytes]],
    make_request: Callable[[dict[str, Any]], urllib.request.Request],
    timeout: int,
    who: str,
    status_error: Callable[[int, bytes], str],
    transport_error: Callable[[AiError], AiError] = lambda e: e,
    attempts: int = CONTINUE_ATTEMPTS,
) -> tuple[str, int, dict[str, Any]]:
    """Send, and keep asking for the rest while the API reports a cut reply.

    ``finish_reason == "length"`` means the model was stopped by the token
    limit, so what came back is the *front* of an answer. Continuing it is what
    "wait for the whole reply" means here: the pieces are stitched and only the
    stitched text is parsed. Returns ``(text, continuations, last_reply_info)``;
    an exhausted budget raises rather than handing a fragment to the parser.
    """
    text = ""
    info: dict[str, Any] = {}
    for round_no in range(attempts + 1):
        try:
            status, body = sender(make_request(payload), timeout)
        except AiError as e:
            raise transport_error(e) from e
        if status != 200:
            raise AiError(status_error(status, body))
        info = reply_info(body)
        info["raw_body"] = body
        if not info["parsed"]:
            raise AiError(
                f"{who} did not answer with a chat-completions reply: "
                f"{_error_detail(body) or 'empty body'}"
            )
        text += str(info["content"] or "")
        if not info["truncated"]:
            return text, round_no, info
        if round_no == attempts:
            raise AiError(
                f"{who} kept hitting the output-token limit after "
                f"{round_no} continuation(s), so the reply never finished. "
                "Shorten the context (the request JSON and the prompts) or raise "
                "max_tokens, then press Help again."
            )
        payload = _continuation_payload(payload, text)
    return text, attempts, info


def _empty_content_error(who: str, body: bytes, info: dict[str, Any]) -> AiError:
    """Why a 200 carried no answer, a reasoning trace that ate the budget, or
    a body that is not a reply at all."""
    if info.get("reasoning"):
        return AiError(
            f"{who} finished its reasoning without writing an answer: the whole "
            "output-token budget went to the trace ("
            f"{len(str(info['reasoning']))} characters of reasoning, no "
            "content). Shorten the context or raise max_tokens, then press Help "
            "again."
        )
    return AiError(
        f"{who} returned no message content (the reply may have been cut off "
        f"before the answer): {_error_detail(body) or 'empty body'}"
    )


def _ask_deepseek_full(
    api_key: str,
    payload: dict[str, Any],
    *,
    send: Callable[[urllib.request.Request, int], tuple[int, bytes]] | None = None,
    timeout: int = TIMEOUT_S,
) -> tuple[str, int, dict[str, Any]]:
    """One DeepSeek call, continued to completion: (text, continuations, info)."""
    key = (api_key or "").strip()
    if not key:
        raise AiError("DeepSeek key is empty, save it on the Tokens tab.")
    sender = send or _http_send
    text, continuations, info = _collect(
        payload,
        sender=sender,
        make_request=lambda body: request_for(key, body),
        timeout=timeout,
        who="DeepSeek",
        status_error=lambda status, body: f"DeepSeek HTTP {status}: {_error_detail(body)}",
    )
    if not text.strip():
        raise _empty_content_error("DeepSeek", info.get("raw_body") or b"", info)
    return text, continuations, info


def ask_deepseek(
    api_key: str,
    payload: dict[str, Any],
    *,
    send: Callable[[urllib.request.Request, int], tuple[int, bytes]] | None = None,
    timeout: int = TIMEOUT_S,
) -> str:
    """POST one payload and return the assistant message text, whole."""
    return _ask_deepseek_full(api_key, payload, send=send, timeout=timeout)[0]


def help_with_prompts(
    api_key: str,
    *,
    editor_positive: str = "",
    editor_negative: str = "",
    adjusted_positive: str = "",
    adjusted_negative: str = "",
    request_json: str = "",
    findings: str = "",
    issue: str = "",
    image_path: Any | None = None,
    send: Callable[[urllib.request.Request, int], tuple[int, bytes]] | None = None,
    timeout: int = TIMEOUT_S,
) -> dict[str, Any]:
    """One Help round trip against DeepSeek: build, ask, parse."""
    image = image_data_url(image_path) if image_path else ""
    payload = build_payload(
        editor_positive=editor_positive,
        editor_negative=editor_negative,
        adjusted_positive=adjusted_positive,
        adjusted_negative=adjusted_negative,
        request_json=request_json,
        findings=findings,
        issue=issue,
        image_data_url=image,
    )
    raw, continuations, _info = _ask_deepseek_full(
        api_key, payload, send=send, timeout=timeout
    )
    out = parse_reply_full(raw)
    return {
        "positive": out["positive"],
        "negative": out["negative"],
        "issue": out.get("issue", ""),
        "raw": raw,
        "payload": payload,
        "image": str(image_path) if image_path else "",
        "continued": continuations,
    }


def local_base(url: str) -> str:
    """Normalise a user-entered local URL to the OpenAI-compatible base.

    LM Studio serves two APIs on one server: the native REST API at
    ``/api/v1/*`` (``/api/v1/models``, ``/api/v1/chat``) and the
    OpenAI-compatible one at ``/v1/*`` (``/v1/models``,
    ``/v1/chat/completions``). This client speaks the OpenAI-compatible
    API, so a pasted native base is mapped onto it and a pasted inference
    URL is reduced to its base.
    """
    raw = (url or "").strip().rstrip("/")
    if not raw:
        return LOCAL_BASE_URL
    if not raw.lower().startswith(("http://", "https://")):
        raw = f"http://{raw}"
    low = raw.lower()
    for suffix in ("/chat/completions", "/models", "/responses", "/messages", "/chat"):
        if low.endswith(suffix):
            raw = raw[: -len(suffix)]
            low = raw.lower()
            break
    if low.endswith("/api/v1"):
        raw = raw[: -len("/api/v1")] + "/v1"
        low = raw.lower()
    if low.endswith("/v1"):
        return raw
    return f"{raw}/v1"


def local_models_url(base: str) -> str:
    return f"{base}/models"


def local_chat_url(base: str) -> str:
    return f"{base}/chat/completions"


def native_models_url(base: str) -> str:
    """LM Studio's native list endpoint (richer metadata than the OpenAI one)."""
    root = base[: -len("/v1")] if base.lower().endswith("/v1") else base
    return f"{root}/api/v1/models"


def model_ids(body: bytes | str) -> list[str]:
    """Model ids from an OpenAI-style ``/models`` body."""
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            out.append(str(item["id"]))
        elif isinstance(item, str) and item:
            out.append(item)
    return out


def request_for_local(base: str, payload: dict[str, Any]) -> urllib.request.Request:
    """The local chat-completions POST. No Authorization: it is a local server."""
    return urllib.request.Request(
        local_chat_url(base),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )


def _offline_hint(message: str, base: str) -> str:
    return (
        f"{message}, is the local model server running? In LM Studio open "
        f"Developer → Start Server (or enable the local server), then check the "
        f"URL ({base})."
    )


def native_model_rows(body: bytes | str) -> list[dict[str, Any]]:
    """Rows from LM Studio's native ``/api/v1/models`` payload."""
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    items = data.get("models") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("key") or item.get("id") or "").strip()
        if not mid:
            continue
        caps = item.get("capabilities")
        caps = caps if isinstance(caps, dict) else {}
        rows.append(
            {
                "id": mid,
                "type": str(item.get("type") or "").lower(),
                "loaded": bool(item.get("loaded_instances")),
                "vision": bool(caps.get("vision")) if "vision" in caps else None,
            }
        )
    return rows


def _is_chat_model(row: dict[str, Any]) -> bool:
    return "embed" not in str(row.get("type") or "")


def choose_local_model(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the model to talk to: loaded and chat-capable first.

    A local server often lists embedding models and unloaded models alongside
    the one the user is actually chatting with, so the first id is not a safe
    choice.
    """
    for row in rows:
        if row.get("loaded") and _is_chat_model(row):
            return row
    for row in rows:
        if _is_chat_model(row):
            return row
    return rows[0] if rows else {}


def local_models(
    base: str,
    *,
    send: Callable[[urllib.request.Request, int], tuple[int, bytes]] | None = None,
    timeout: int = LOCAL_MODEL_URL_TIMEOUT_S,
) -> list[dict[str, Any]]:
    """Models the local server offers, with type/loaded/vision when known.

    Asks the native endpoint first (it carries the metadata), then the
    OpenAI-compatible one. [] when the server cannot answer.
    """
    sender = send or _http_send
    headers = {"accept": "application/json", "User-Agent": USER_AGENT}
    try:
        status, body = sender(urllib.request.Request(native_models_url(base), headers=headers), timeout)
        if status == 200:
            rows = native_model_rows(body)
            if rows:
                return rows
    except Exception:  # noqa: BLE001 - fall back to the OpenAI list
        pass
    try:
        status, body = sender(urllib.request.Request(local_models_url(base), headers=headers), timeout)
    except Exception:  # noqa: BLE001 - discovery is best-effort
        return []
    if status != 200:
        return []
    return [
        {"id": mid, "type": "", "loaded": None, "vision": None}
        for mid in model_ids(body)
    ]


def fetch_local_models(
    base: str,
    *,
    send: Callable[[urllib.request.Request, int], tuple[int, bytes]] | None = None,
    timeout: int = LOCAL_MODEL_URL_TIMEOUT_S,
) -> list[str]:
    """Just the ids the local server offers."""
    return [str(row.get("id") or "") for row in local_models(base, send=send, timeout=timeout)]


def _ask_local_full(
    payload: dict[str, Any],
    *,
    base: str = LOCAL_BASE_URL,
    send: Callable[[urllib.request.Request, int], tuple[int, bytes]] | None = None,
    timeout: int = LOCAL_TIMEOUT_S,
) -> tuple[str, int, dict[str, Any]]:
    """One local call, continued to completion: (text, continuations, info)."""
    sender = send or _http_send
    text, continuations, info = _collect(
        payload,
        sender=sender,
        make_request=lambda body: request_for_local(base, body),
        timeout=timeout,
        who="the local model",
        status_error=lambda status, body: (
            f"local server HTTP {status}: {_error_detail(body)}"
            + ("" if status != 404 else f" (is a model loaded at {base}?)")
        ),
        # The "is the server running?" hint is for a transport failure only,
        # not for a reply that hit the token limit.
        transport_error=lambda e: AiError(_offline_hint(str(e), base)),
    )
    if not text.strip():
        raise AiError(
            "the local model returned no message content "
            f"({_error_detail(info.get('raw_body') or b'') or 'empty body'})"
        )
    return text, continuations, info


def ask_local(
    payload: dict[str, Any],
    *,
    base: str = LOCAL_BASE_URL,
    send: Callable[[urllib.request.Request, int], tuple[int, bytes]] | None = None,
    timeout: int = LOCAL_TIMEOUT_S,
) -> str:
    """POST one payload to the local OpenAI-compatible server."""
    return _ask_local_full(payload, base=base, send=send, timeout=timeout)[0]


def help_with_prompts_local(
    *,
    url: str = LOCAL_BASE_URL,
    model: str = "",
    editor_positive: str = "",
    editor_negative: str = "",
    adjusted_positive: str = "",
    adjusted_negative: str = "",
    request_json: str = "",
    findings: str = "",
    issue: str = "",
    image_path: Any | None = None,
    send: Callable[[urllib.request.Request, int], tuple[int, bytes]] | None = None,
    timeout: int = LOCAL_TIMEOUT_S,
) -> dict[str, Any]:
    """One Help round trip against the local LM Studio server.

    The same context and reply contract as the DeepSeek call; only the transport
    and the model id (discovered from ``/models``) differ.
    """
    base = local_base(url)
    chosen = (model or "").strip()
    vision: bool | None = None
    if not chosen:
        rows = local_models(base, send=send, timeout=LOCAL_MODEL_URL_TIMEOUT_S)
        picked = choose_local_model(rows)
        if not picked:
            raise AiError(_offline_hint(f"no model answered at {base}", base))
        chosen = str(picked.get("id") or "")
        vision = picked.get("vision")
    image = image_data_url(image_path) if image_path else ""
    payload = build_payload(
        editor_positive=editor_positive,
        editor_negative=editor_negative,
        adjusted_positive=adjusted_positive,
        adjusted_negative=adjusted_negative,
        request_json=request_json,
        findings=findings,
        issue=issue,
        image_data_url=image,
        model=chosen,
    )
    raw, continuations, _info = _ask_local_full(
        payload, base=base, send=send, timeout=timeout
    )
    out = parse_reply_full(raw)
    return {
        "positive": out["positive"],
        "negative": out["negative"],
        "issue": out.get("issue", ""),
        "raw": raw,
        "payload": payload,
        "image": str(image_path) if image_path else "",
        "base": base,
        "model": chosen,
        "vision": vision,
        "continued": continuations,
    }
