"""Salad Studio named-profile persistence (stdlib only).

Secrets stay on disk at ``key_path``; this module stores the path, never the key.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

PROFILES_PATH = Path.home() / ".config" / "salad" / "studio-profiles.json"
DEFAULT_KEY_PATH = str(Path.home() / ".config" / "salad" / "key")
GATEWAY_KLEIN_PATH = Path.home() / ".config" / "salad" / "gateway-klein"
GATEWAY_KLEIN_5090_PATH = Path.home() / ".config" / "salad" / "gateway-klein-5090"

# Public Salad Container Gateway DNS (not secrets). Same values in docs/workflow/15.
KLEIN_GATEWAY = "https://apple-gadogado-5d0vs4l8x0j51hwy.salad.cloud"
KLEIN_5090_GATEWAY = "https://beet-ginger-cdz8ko9ehhmh4703.salad.cloud"


def _default_key_path() -> str:
    return DEFAULT_KEY_PATH


DEFAULT_KLEIN_LORA_IDS = (
    "civitai:2334190@2625692",
    "civitai:545264@2763568",
)


def _default_selected_loras() -> list[str]:
    return list(DEFAULT_KLEIN_LORA_IDS)


@dataclass
class SaladProfile:
    name: str
    gateway: str = ""
    key_path: str = field(default_factory=_default_key_path)
    graph: str = "klein"
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg: float = 5
    seed: int = 1
    scheduler: str = "flux2"
    unet: str = "flux-2-klein-base-9b-fp8.safetensors"
    use_loras: bool = True
    selected_loras: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.selected_loras:
            self.use_loras = True
        elif self.use_loras:
            self.selected_loras = list(DEFAULT_KLEIN_LORA_IDS)
        else:
            self.selected_loras = []


# ---------------------------------------------------------------------------
# Unet routing: SNOFS and non-SNOFS must never share a container.
#
# A 24 GB card (4090/3090) holds ONE ~9 GB unet plus the 8.66 GB Qwen text
# encoder, about 17.7 GB. When a second unet is needed for a different graph,
# the pair does not fit, so Comfy falls back to streaming weights from host
# memory and a render that should take seconds takes minutes:
#
#   Model Flux2 prepared for dynamic VRAM loading. 8658MB Staged. 112 patches
#   attached. Force pre-loaded 80 weights      (measured 2026-09-22)
#
# Two of our families exist, the SNOFS merged cut (two-body plates) and the
# plain Klein unets (Civitai imports, the 4-step cut). Adding unets to the
# *_disk_ costs nothing; loading two into VRAM is what breaks. So each container
# group serves exactly one family, and a graph that asks for the wrong one is
# refused here rather than silently degrading every render on that group.
SNOFS_MARKER = "snofs"
# Mirrors request_json.UNET_SNOFS, duplicated on purpose: this module is
# stdlib-only and request_json imports salad_gen + lora_store.
SNOFS_UNET = "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors"


def unet_family(unet_name: str) -> str:
    """``"snofs"``, ``"klein"``, or ``""`` for an empty name."""
    name = (unet_name or "").strip().lower()
    if not name:
        return ""
    return "snofs" if SNOFS_MARKER in name else "klein"


def payload_unets(payload: dict[str, Any] | None) -> list[str]:
    """Every unet a graph loads, in order and deduped (normally exactly one)."""
    prompt = (payload or {}).get("prompt")
    if not isinstance(prompt, dict):
        return []
    out: list[str] = []
    for node in prompt.values():
        if not isinstance(node, dict) or node.get("class_type") != "UNETLoader":
            continue
        name = str((node.get("inputs") or {}).get("unet_name") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def routing_conflict(payload: dict[str, Any] | None, profile: SaladProfile) -> str:
    """Why this graph does not belong on this profile's group, or ``""``.

    Empty when they agree, when the graph loads no unet at all, or when the
    profile names no unet to compare against.
    """
    wanted = unet_family(profile.unet)
    if not wanted:
        return ""
    bad = [u for u in payload_unets(payload) if unet_family(u) != wanted]
    if not bad:
        return ""
    return (
        f"This graph loads {bad[0]}, which is a {unet_family(bad[0])} unet, but "
        f"profile {profile.name!r} serves {profile.unet} ({wanted}).\n\n"
        "One container holds only one unet in VRAM. Rendering both families on the "
        "same group makes Comfy stream weights from host memory and turns a "
        "seconds-long render into minutes (and a gateway timeout).\n\n"
        "Switch to the profile for the other family and Generate again."
    )


def serving_family(profile: SaladProfile) -> str:
    """The unet family this profile's group serves (its own ``unet`` declares it)."""
    return unet_family(profile.unet)


def profile_for_family(
    family: str, all_profiles: dict[str, SaladProfile]
) -> tuple[str, SaladProfile] | None:
    """The profile whose group serves ``family``, or None if no group does."""
    if not family:
        return None
    for name in sorted(all_profiles):
        profile = all_profiles[name]
        if serving_family(profile) == family:
            return name, profile
    return None


def route_payload(
    payload: dict[str, Any] | None, all_profiles: dict[str, SaladProfile]
) -> tuple[str, SaladProfile] | None:
    """Which group should render this graph, by the unet it loads.

    None means "no group serves that family". The caller should refuse rather
    than send it somewhere it would thrash.
    """
    unets = payload_unets(payload)
    if not unets:
        return None
    return profile_for_family(unet_family(unets[0]), all_profiles)


def same_gateway(a: str, b: str) -> bool:
    """Two gateway URLs naming the same host. Case- and trailing-slash-insensitive.

    Two empty strings are NOT the same: an unset gateway must still be routed.
    """
    def norm(url: str) -> str:
        return (url or "").strip().rstrip("/").lower()

    left = norm(a)
    return bool(left) and left == norm(b)


def profile_for_gateway(
    gateway: str, all_profiles: dict[str, SaladProfile]
) -> SaladProfile | None:
    """The saved profile whose group is ``gateway``, or None if it is not one of ours.

    Routing asks this of the gateway the form would POST to. Comparing the
    graph's unet family to the *form's* unet cannot work: loading a JSON into the
    editor rewrites that field from the graph, so the two sides always agree.
    """
    for name in sorted(all_profiles):
        if same_gateway(all_profiles[name].gateway, gateway):
            return all_profiles[name]
    return None


def _resolve(path: Path | None) -> Path:
    return path if path is not None else PROFILES_PATH


def _read_optional_text(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def _load_doc(path: Path) -> dict:
    if not path.is_file():
        return {"profiles": {}, "active": None}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {"profiles": {}, "active": None}
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {"profiles": {}, "active": None}
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    active = data.get("active")
    if active is not None:
        active = str(active)
        if active == "":
            active = None
    return {"profiles": profiles, "active": active}


def _coerce_selected_loras(data: dict[str, Any]) -> list[str]:
    raw = data.get("selected_loras")
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if data.get("use_loras", True):
        return list(DEFAULT_KLEIN_LORA_IDS)
    return []


def _coerce(value: Any, cast: Callable[[Any], Any], default: Any) -> Any:
    """``cast(value)``, or ``default`` when the stored field is not numeric.

    A hand-edited or half-written ``studio-profiles.json`` must not abort
    ``load_all`` (and with it app startup).
    """
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def _profile_from_dict(name: str, data: object) -> SaladProfile:
    if not isinstance(data, dict):
        data = {}
    selected = _coerce_selected_loras(data)
    use_loras = bool(selected) if "selected_loras" in data else bool(
        data.get("use_loras", True)
    )
    if "selected_loras" not in data and use_loras and not selected:
        selected = list(DEFAULT_KLEIN_LORA_IDS)
    return SaladProfile(
        name=str(data.get("name") or name),
        gateway=str(data.get("gateway", "")),
        key_path=str(data.get("key_path") or DEFAULT_KEY_PATH),
        graph=str(data.get("graph") or "klein"),
        width=_coerce(data.get("width", 1024), int, 1024),
        height=_coerce(data.get("height", 1024), int, 1024),
        steps=_coerce(data.get("steps", 20), int, 20),
        cfg=_coerce(data.get("cfg", 5) or 5, float, 5),
        seed=_coerce(data.get("seed", 1) or 1, int, 1),
        scheduler=str(data.get("scheduler") or "flux2"),
        unet=str(data.get("unet") or "flux-2-klein-base-9b-fp8.safetensors"),
        use_loras=use_loras if "selected_loras" not in data else bool(selected),
        selected_loras=selected,
    )


def _profiles_from_doc(doc: dict) -> dict[str, SaladProfile]:
    out: dict[str, SaladProfile] = {}
    for key, raw in doc.get("profiles", {}).items():
        name = str(key)
        profile = _profile_from_dict(name, raw)
        profile.name = name
        out[name] = profile
    return out


def _save_doc(
    path: Path, profiles: dict[str, SaladProfile], active: str | None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "profiles": {},
        "active": active,
    }
    for key, profile in profiles.items():
        name = profile.name or key
        data = asdict(profile)
        data["name"] = name
        payload["profiles"][name] = data
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def default_profile(name: str = "klein") -> SaladProfile:
    """A built-in profile. ``klein5090`` serves the SNOFS family, so its ``unet``
    is the SNOFS cut. That field is what routing reads to pick a group."""
    key = (name or "klein").strip() or "klein"
    if key == "klein5090":
        gw = _read_optional_text(GATEWAY_KLEIN_5090_PATH) or KLEIN_5090_GATEWAY
        unet = SNOFS_UNET
    else:
        gw = _read_optional_text(GATEWAY_KLEIN_PATH) or KLEIN_GATEWAY
        unet = "flux-2-klein-base-9b-fp8.safetensors"
    return SaladProfile(
        name=key,
        gateway=gw,
        key_path=DEFAULT_KEY_PATH,
        graph="klein",
        width=1024,
        height=1024,
        steps=20,
        unet=unet,
        use_loras=True,
        selected_loras=list(DEFAULT_KLEIN_LORA_IDS),
    )


def write_gateway_file(path: Path, url: str) -> None:
    """Create ``~/.config/salad/gateway-*`` if missing. Never overwrite."""
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(url.rstrip() + "\n", encoding="utf-8")


def ensure_builtin_profiles(path: Path | None = None) -> dict[str, SaladProfile]:
    """Keep ``klein`` and ``klein5090`` on disk so the 5090 group is not lost."""
    write_gateway_file(GATEWAY_KLEIN_PATH, KLEIN_GATEWAY)
    write_gateway_file(GATEWAY_KLEIN_5090_PATH, KLEIN_5090_GATEWAY)
    path = _resolve(path)
    profiles = load_all(path)
    changed = False
    if "klein" not in profiles:
        profiles["klein"] = default_profile("klein")
        changed = True
    elif not (profiles["klein"].gateway or "").strip():
        profiles["klein"].gateway = KLEIN_GATEWAY
        changed = True
    if "klein5090" not in profiles:
        profiles["klein5090"] = default_profile("klein5090")
        changed = True
    elif not (profiles["klein5090"].gateway or "").strip():
        profiles["klein5090"].gateway = KLEIN_5090_GATEWAY
        changed = True
    if changed:
        save_all(profiles, path)
    return load_all(path)


def load_all(path: Path | None = None) -> dict[str, SaladProfile]:
    return _profiles_from_doc(_load_doc(_resolve(path)))


def save_all(
    profiles: dict[str, SaladProfile], path: Path | None = None
) -> None:
    path = _resolve(path)
    active = _load_doc(path).get("active")
    _save_doc(path, profiles, active)


def upsert(profile: SaladProfile, path: Path | None = None) -> dict[str, SaladProfile]:
    path = _resolve(path)
    profiles = load_all(path)
    profiles[profile.name] = profile
    save_all(profiles, path)
    return profiles


def delete(name: str, path: Path | None = None) -> dict[str, SaladProfile]:
    path = _resolve(path)
    profiles = load_all(path)
    profiles.pop(name, None)
    save_all(profiles, path)
    return profiles


def get_active(path: Path | None = None) -> str | None:
    return _load_doc(_resolve(path)).get("active")


def set_active(name: str, path: Path | None = None) -> None:
    path = _resolve(path)
    profiles = load_all(path)
    _save_doc(path, profiles, name)
