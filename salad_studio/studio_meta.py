"""The Studio metadata document: the routing table and the AI layer's prompt hints.

One JSON document carries the two things that used to be code literals:

- ``routing.families`` — unet family to Salad container group, keyed by the
  checkpoint the graph loads. One container holds one unet family in VRAM (a
  second ~9 GB unet beside the 8.66 GB Qwen encoder makes Comfy stream weights
  from host memory, turning a 3 s render into minutes), so this table is what
  decides which gateway a graph goes to.
- ``prompt`` — the instruction the AI layer sends: role, task, house rules and
  the reply contract.

Search order: the user's document (``~/.config/salad/studio-metadata.json``)
when it is present and usable, else the shipped default beside this module.
Editing either one changes routing and the AI instruction with no code edit.

Both consumers take the loaded document as a parameter, so a test points at a
temp file and observes the effect without monkeypatching.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_HOME = Path.home() / ".config"
USER_PATH = CONFIG_HOME / "salad" / "studio-metadata.json"
DEFAULT_PATH = Path(__file__).resolve().parent / "studio-metadata.json"

# Routing keys, in the document's own vocabulary.
GROUP = "group"
IMAGE = "image"
GATEWAY = "gateway"
UNETS = "unets"
MARKERS = "markers"


def _empty(source: str, error: str) -> dict[str, Any]:
    """A document with nothing in it, plus why it could not be read."""
    return {
        "version": 0,
        "routing": {"families": {}},
        "prompt": {"role": "", "task": "", "rules": [], "reply_contract": ""},
        "source": source,
        "error": error,
    }


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _text(item)
        if text and text not in out:
            out.append(text)
    return out


def _families(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, entry in raw.items():
        name = _text(key)
        if not name:
            continue
        data = entry if isinstance(entry, dict) else {}
        out[name] = {
            GROUP: _text(data.get(GROUP)),
            IMAGE: _text(data.get(IMAGE)),
            GATEWAY: _text(data.get(GATEWAY)),
            UNETS: _text_list(data.get(UNETS)),
            MARKERS: _text_list(data.get(MARKERS)),
        }
    return out


def normalise(data: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """A parsed document in one shape, with the fields a hand-edit can break filled in."""
    routing = data.get("routing") if isinstance(data.get("routing"), dict) else {}
    prompt = data.get("prompt") if isinstance(data.get("prompt"), dict) else {}
    version = data.get("version")
    try:
        version = int(version)
    except (TypeError, ValueError):
        version = 0
    return {
        "version": version,
        "routing": {"families": _families(routing.get("families"))},
        "prompt": {
            "role": _text(prompt.get("role")),
            "task": _text(prompt.get("task")),
            "rules": _text_list(prompt.get("rules")),
            "reply_contract": _text(prompt.get("reply_contract")),
        },
        "source": source,
        "error": "",
    }


def _read(path: Path) -> tuple[dict[str, Any] | None, str]:
    """``(document, error)`` for one file. Never raises on a bad file."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"cannot read {path}: {e}"
    if not raw.strip():
        return None, f"{path} is empty"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        return None, f"{path} is not JSON: {e}"
    if not isinstance(data, dict):
        return None, f"{path} is not a JSON object"
    return data, ""


def load(path: Path | None = None) -> dict[str, Any]:
    """The metadata document, normalised, from ``path`` or the search order.

    A broken user document falls back to the shipped default rather than
    aborting startup; the reason is carried in the ``error`` field so the app
    can log it instead of silently using different rules.
    """
    if path is not None:
        target = Path(path)
        data, error = _read(target)
        if data is None:
            return _empty(str(target), error)
        return normalise(data, source=str(target))
    if USER_PATH.is_file():
        data, error = _read(USER_PATH)
        if data is not None:
            return normalise(data, source=str(USER_PATH))
        fallback, _ = _read(DEFAULT_PATH)
        if fallback is None:
            return _empty(str(USER_PATH), error)
        doc = normalise(fallback, source=str(DEFAULT_PATH))
        doc["error"] = error
        return doc
    data, error = _read(DEFAULT_PATH)
    if data is None:
        return _empty(str(DEFAULT_PATH), error)
    return normalise(data, source=str(DEFAULT_PATH))


def families(doc: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The routing table: family name to its group, image, unets and markers."""
    routing = (doc or {}).get("routing")
    if not isinstance(routing, dict):
        return {}
    found = routing.get("families")
    return found if isinstance(found, dict) else {}


_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def default() -> dict[str, Any]:
    """The document from the search order, cached until that file changes.

    Routing asks for it once per graph node, so the file is read once and
    re-read only when its mtime moves: editing the document takes effect in a
    running app with no restart.
    """
    target = USER_PATH if USER_PATH.is_file() else DEFAULT_PATH
    try:
        stamp = target.stat().st_mtime
    except OSError:
        stamp = -1.0
    key = str(target)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    doc = load()
    _CACHE[key] = (stamp, doc)
    return doc


def reset_cache() -> None:
    """Forget the cached document (tests, and after writing one)."""
    _CACHE.clear()


def family_for_unet(unet: str, doc: dict[str, Any] | None) -> str:
    """Which family serves this checkpoint, or ``""`` when the document is silent.

    An exact name listed under a family wins. Otherwise the family whose marker
    appears **earliest** in the name wins, longest marker breaking a tie: the
    SNOFS cut is named ``snofs…_distilledV12KleinFp8`` and matches both families,
    and a marker test that ran in the wrong order would send it to the plain
    Klein group. ``""`` means "no metadata entry", which the caller refuses.
    """
    name = _text(unet)
    if not name:
        return ""
    low = name.lower()
    table = families(doc)
    for family, entry in table.items():
        if any(low == listed.lower() for listed in entry.get(UNETS, [])):
            return family
    best: tuple[int, int, int, str] | None = None
    for order, (family, entry) in enumerate(table.items()):
        for marker in entry.get(MARKERS, []):
            at = low.find(marker.lower())
            if at < 0:
                continue
            score = (at, -len(marker), order, family)
            if best is None or score < best:
                best = score
    return best[3] if best is not None else ""


def entry_for_family(family: str, doc: dict[str, Any] | None) -> dict[str, Any]:
    """The routing entry for ``family``, or an empty one."""
    return families(doc).get(
        family, {GROUP: "", IMAGE: "", GATEWAY: "", UNETS: [], MARKERS: []}
    )


def group_for_family(family: str, doc: dict[str, Any] | None) -> str:
    """The Salad container group (the saved profile) that serves ``family``."""
    return _text(entry_for_family(family, doc).get(GROUP))


def gateway_for_family(family: str, doc: dict[str, Any] | None) -> str:
    """The gateway the document names for ``family``, or ``""`` for the profile's.

    Empty is the normal case: the routed profile carries the gateway, so an
    edit to ``~/.config/salad/gateway-*`` keeps working. Naming one here is how
    the document moves a family to a different host without a code edit.
    """
    return _text(entry_for_family(family, doc).get(GATEWAY))


def image_for_family(family: str, doc: dict[str, Any] | None) -> str:
    """The container image recorded for ``family``, informational."""
    return _text(entry_for_family(family, doc).get(IMAGE))


def instruction(doc: dict[str, Any] | None) -> str:
    """The AI layer's system message, assembled from the document.

    Nothing here is a literal: the role, the task, the rules and the reply
    contract all come from the metadata, so editing the document changes the
    instruction that is actually sent.
    """
    prompt = (doc or {}).get("prompt")
    if not isinstance(prompt, dict):
        return ""
    parts = [_text(prompt.get("role")), _text(prompt.get("task"))]
    parts += [f"- {rule}" for rule in _text_list(prompt.get("rules"))]
    parts.append(_text(prompt.get("reply_contract")))
    return "\n".join(part for part in parts if part)
