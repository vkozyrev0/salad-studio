"""Salad Studio tokens: local gitignored JSON, seeded from ~/.config if empty.

Primary store: ``studio-tokens.json`` next to this package (not git).
If a slot is empty, copy from default storage:

- salad        ``~/.config/salad/key``
- huggingface  ``~/.config/huggingface/token``
- civitai      ``~/.config/civitai/token``
- deepseek     ``~/.config/deepseek/key``, else ``DEEPSEEK_API_KEY``

A kind listed in ``TOKEN_ENV_VARS`` also reads its key from that environment
variable when no file has one. The environment value is used as-is and is
never copied into ``studio-tokens.json``, so an ephemeral key stays ephemeral.

``probe_token`` does a real provider call so the Tokens page can show whether
a key actually works; see ``PROBE_SPECS``.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_HOME = Path.home() / ".config"
LOCAL_PATH = Path(__file__).resolve().parent / "studio-tokens.json"
USER_AGENT = "SaladStudio/1.0"

TOKEN_SPECS: tuple[tuple[str, str, str], ...] = (
    ("salad", "Salad API", "salad/key"),
    ("huggingface", "Hugging Face", "huggingface/token"),
    ("civitai", "Civitai", "civitai/token"),
    ("deepseek", "DeepSeek", "deepseek/key"),
)

# Kinds that also have a conventional environment variable. Only consulted
# when the local store and the default file are both empty.
TOKEN_ENV_VARS: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
}

# kind -> (url, header name). Each was checked to answer 200 for a working key
# and 401 for a rejected one. The Salad path mirrors salad_status.API / ORG /
# PROJECT (test_tokens asserts they agree); Civitai needs /me because its
# public /models answers 200 even for a bogus key.
PROBE_SPECS: dict[str, tuple[str, str]] = {
    "salad": (
        "https://api.salad.com/api/public/organizations/life-sim/projects/default/containers",
        "Salad-Api-Key",
    ),
    "huggingface": ("https://huggingface.co/api/whoami-v2", "Authorization"),
    "civitai": ("https://civitai.com/api/v1/me", "Authorization"),
    "deepseek": ("https://api.deepseek.com/models", "Authorization"),
}

VALID = "valid"
INVALID = "invalid"
UNKNOWN = "unknown"
PROBE_TIMEOUT_S = 15


def default_path(kind: str) -> Path:
    for kid, _label, rel in TOKEN_SPECS:
        if kid == kind:
            return CONFIG_HOME / rel
    raise KeyError(f"unknown token {kind}")


def env_var(kind: str) -> str:
    """Environment variable that can hold this kind, or ""."""
    return TOKEN_ENV_VARS.get(kind, "")


def default_label(kind: str) -> str:
    """Default row for the Tokens tab: file path, plus any env fallback."""
    label = str(default_path(kind))
    name = env_var(kind)
    return f"{label}   (or {name} in the environment)" if name else label


def token_path(kind: str) -> Path:
    """Local JSON is the store for every kind."""
    if kind not in {k for k, _l, _r in TOKEN_SPECS}:
        raise KeyError(f"unknown token {kind}")
    return LOCAL_PATH


def token_label(kind: str) -> str:
    for kid, label, _rel in TOKEN_SPECS:
        if kid == kind:
            return label
    raise KeyError(f"unknown token {kind}")


def _read_file(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return ""


def _load_local() -> dict[str, str]:
    if not LOCAL_PATH.is_file():
        return {}
    try:
        data = json.loads(LOCAL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) if v is not None else "" for k, v in data.items()}


def _save_local(doc: dict[str, str]) -> Path:
    LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {kind: str(doc.get(kind) or "") for kind, _l, _r in TOKEN_SPECS}
    LOCAL_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return LOCAL_PATH


def seed_from_defaults() -> list[str]:
    """Copy empty local slots from ~/.config. Returns kinds that were filled."""
    doc = _load_local()
    copied: list[str] = []
    for kind, _label, _rel in TOKEN_SPECS:
        if str(doc.get(kind) or "").strip():
            continue
        val = _read_file(default_path(kind))
        if val:
            doc[kind] = val
            copied.append(kind)
    if copied:
        _save_local(doc)
    return copied


def read_token(kind: str) -> str:
    seed_from_defaults()
    doc = _load_local()
    val = str(doc.get(kind) or "").strip()
    if val:
        return val
    val = _read_file(default_path(kind))
    if val:
        return val
    return read_env_token(kind)


def read_env_token(kind: str) -> str:
    """Key from this kind's environment variable, or "". Never persisted."""
    name = env_var(kind)
    if not name:
        return ""
    return (os.environ.get(name) or "").strip()


def write_token(kind: str, value: str) -> Path:
    if kind not in {k for k, _l, _r in TOKEN_SPECS}:
        raise KeyError(f"unknown token {kind}")
    doc = _load_local()
    doc[kind] = value.strip()
    return _save_local(doc)


def masked(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "(missing)"
    if len(raw) <= 4:
        return "set (****)"
    return f"set (…{raw[-4:]})"


def resolve_salad_key(key_path: str | None = None) -> str:
    """Key sent as Salad-Api-Key. Local JSON wins, then defaults, then ``key_path``."""
    val = read_token("salad")
    if val:
        return val
    if key_path:
        val = _read_file(Path(key_path))
        if val:
            return val
    raise FileNotFoundError(
        "Salad API key is empty. Save it on the Tokens tab "
        f"({LOCAL_PATH})."
    )


def _http_send(
    request: urllib.request.Request, timeout: int
) -> tuple[int, bytes]:
    """One HTTP GET. Returns (status, body). Status 0 means the call never ran."""
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


def probe_request(kind: str, key: str) -> urllib.request.Request:
    """The real provider request used to check one key."""
    spec = PROBE_SPECS.get(kind)
    if spec is None:
        raise KeyError(f"no key check for {kind}")
    url, header = spec
    value = key if header != "Authorization" else f"Bearer {key}"
    return urllib.request.Request(
        url,
        headers={
            header: value,
            "accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )


def probe_token(
    kind: str,
    *,
    send=None,
    timeout: int = PROBE_TIMEOUT_S,
    key: str | None = None,
) -> dict[str, str]:
    """Check one stored key against its provider.

    ``state`` is VALID only when the provider answered 200; a rejected key is
    INVALID, and anything else (no key, transport failure, an unexpected
    status) is UNKNOWN, never a false green.
    """
    secret = (read_token(kind) if key is None else key) or ""
    if not secret.strip():
        return {"kind": kind, "state": UNKNOWN, "detail": "no key saved"}
    try:
        request = probe_request(kind, secret.strip())
    except KeyError as e:
        return {"kind": kind, "state": UNKNOWN, "detail": str(e)}
    sender = send or _http_send
    try:
        status, _body = sender(request, timeout)
    except Exception as e:  # noqa: BLE001 - a probe must never break the app
        return {"kind": kind, "state": UNKNOWN, "detail": f"{type(e).__name__}: {e}"}
    if status == 200:
        return {"kind": kind, "state": VALID, "detail": "HTTP 200"}
    if status in (401, 403):
        return {"kind": kind, "state": INVALID, "detail": f"HTTP {status}"}
    if status == 0:
        return {"kind": kind, "state": UNKNOWN, "detail": "no response"}
    return {"kind": kind, "state": UNKNOWN, "detail": f"HTTP {status}"}


def probe_all(*, send=None, timeout: int = PROBE_TIMEOUT_S) -> dict[str, dict[str, str]]:
    """Check every kind that has a probe spec."""
    return {
        kind: probe_token(kind, send=send, timeout=timeout) for kind in PROBE_SPECS
    }


def state_color(state: str) -> str:
    """Palette key for an indicator dot. Kept here so the widget only renders."""
    if state == VALID:
        return "valid"
    if state == INVALID:
        return "invalid"
    return "unknown"
