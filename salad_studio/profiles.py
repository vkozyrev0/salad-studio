"""Salad Studio named-profile persistence (stdlib only).

Secrets stay on disk at ``key_path``; this module stores the path, never the key.

A profile owns the **checkpoints its container serves**, and that list is the
routing table: a graph goes to the profile that lists the checkpoint it loads.
The metadata document (:mod:`studio_meta`) keeps what a family *is* (its markers)
and the seed list a new built-in profile starts from.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

# Top-level, the way this package's leaf modules are imported (studio_log,
# request_json): one module object per process, shared with the app and tests.
import studio_meta  # noqa: E402

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
    # Every checkpoint this container serves. One container holds one unet
    # family in VRAM, so this list is what routing matches a graph against; the
    # Config page adds to it and removes from it.
    checkpoints: list[str] = field(default_factory=list)
    use_loras: bool = True
    selected_loras: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.checkpoints = [c for c in (str(c).strip() for c in self.checkpoints) if c]
        if self.selected_loras:
            self.use_loras = True
        elif self.use_loras:
            self.selected_loras = list(DEFAULT_KLEIN_LORA_IDS)
        else:
            self.selected_loras = []

    @property
    def primary_checkpoint(self) -> str:
        """The first checkpoint in the list, or ``""`` when it lists none."""
        return self.checkpoints[0] if self.checkpoints else ""


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
#
# Which checkpoints a container serves is the profile's own ``checkpoints``
# list, so growing that list is a Config-page edit and no code change. The
# metadata document keeps what a family *is* (its markers) and the seed list a
# new built-in profile starts from.
SNOFS_MARKER = "snofs"
# Mirrors request_json.UNET_SNOFS, duplicated on purpose: this module is
# stdlib-only and request_json imports salad_gen + lora_store.
SNOFS_UNET = "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors"


def unet_family(unet_name: str, meta: dict[str, Any] | None = None) -> str:
    """``"snofs"``, ``"klein"``, or ``""`` when the metadata does not classify it.

    The family table lives in the metadata document. Routing does not need it
    (the profile's list decides); it is what tells two checkpoints apart when a
    profile's list is checked for mixing families.
    """
    doc = studio_meta.default() if meta is None else meta
    return studio_meta.family_for_unet(unet_name, doc)


def checkpoint_family(unet_name: str, meta: dict[str, Any] | None = None) -> str:
    """The family a checkpoint belongs to, falling back to its own name.

    A checkpoint the metadata does not classify is its own family, so a profile
    that lists only it is consistent, and a checkpoint that does not exist yet
    needs no metadata edit to be routable.
    """
    name = (unet_name or "").strip()
    if not name:
        return ""
    return unet_family(name, meta) or name.lower()


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


def profile_families(profile: SaladProfile, meta: dict[str, Any] | None = None) -> set[str]:
    """Every unet family the profile's checkpoint list spans."""
    return {checkpoint_family(name, meta) for name in profile.checkpoints if name.strip()}


def mixed_family_reason(
    profile: SaladProfile, meta: dict[str, Any] | None = None
) -> str:
    """Why this profile's list spans more than one family, or ``""``.

    One container holds one unet family in VRAM, so a list that mixes families
    cannot be served by one group: the second unet forces Comfy to stream
    weights from host memory and a seconds-long render becomes minutes.
    """
    families = sorted(f for f in profile_families(profile, meta) if f)
    if len(families) <= 1:
        return ""
    return (
        f"Profile {profile.name!r} lists checkpoints from {len(families)} unet "
        f"families ({', '.join(families)}). One container holds one unet family in "
        "VRAM, so split the list across one profile per family."
    )


def serving_family(profile: SaladProfile, meta: dict[str, Any] | None = None) -> str:
    """The unet family this profile serves (the first checkpoint it lists)."""
    return checkpoint_family(profile.primary_checkpoint, meta)


def add_checkpoint(
    profile: SaladProfile, unet: str, meta: dict[str, Any] | None = None
) -> str:
    """Append ``unet`` to the profile's list. Returns ``""`` or a refusal reason."""
    name = (unet or "").strip()
    if not name:
        return "Type a checkpoint filename or pick a label first."
    if name in profile.checkpoints:
        return f"{name} is already in {profile.name!r}."
    mine = checkpoint_family(name, meta)
    listed = sorted(f for f in profile_families(profile, meta) if f)
    if listed and mine not in listed:
        return (
            f"{name} is a {mine} checkpoint and {profile.name!r} serves "
            f"{listed[0]}. One container holds one unet family in VRAM, so add it "
            "to a profile for that family instead."
        )
    profile.checkpoints.append(name)
    return ""


def remove_checkpoint(profile: SaladProfile, unet: str) -> bool:
    """Drop ``unet`` from the profile's list. True when it was there."""
    name = (unet or "").strip()
    if not name or name not in profile.checkpoints:
        return False
    profile.checkpoints = [c for c in profile.checkpoints if c != name]
    return True


def profiles_for_checkpoint(
    unet: str, all_profiles: dict[str, SaladProfile]
) -> list[str]:
    """The names of the profiles that list this checkpoint, sorted."""
    name = (unet or "").strip()
    if not name:
        return []
    return sorted(p.name for p in all_profiles.values() if name in p.checkpoints)


def route_payload(
    payload: dict[str, Any] | None,
    all_profiles: dict[str, SaladProfile],
    meta: dict[str, Any] | None = None,
) -> tuple[str, SaladProfile] | None:
    """Which profile should render this graph, by the checkpoint it loads.

    The profile's own list decides, so adding a checkpoint to a profile on the
    Config page makes a graph loading it routable with no code edit. None means
    "no profile serves it": nothing lists the checkpoint, two profiles do and
    the choice would be a coin toss, or the one that lists it mixes families.
    """
    unets = payload_unets(payload)
    if not unets:
        return None
    names = profiles_for_checkpoint(unets[0], all_profiles)
    if len(names) != 1:
        return None
    profile = all_profiles[names[0]]
    if mixed_family_reason(profile, meta):
        return None
    return names[0], profile


@dataclass(frozen=True)
class Route:
    """Where a graph belongs: the profile that lists the checkpoint it loads."""

    family: str
    name: str
    profile: SaladProfile
    image: str = ""


def plan_route(
    payload: dict[str, Any] | None,
    form_profile: SaladProfile,
    all_profiles: dict[str, SaladProfile],
    meta: dict[str, Any] | None = None,
) -> tuple[Route | None, str]:
    """The route this graph needs, and the reason to refuse it instead.

    ``(None, "")`` means "send it where the form points": the graph loads no
    unet, the form points at a gateway that is not one of our profiles (a
    hand-typed gateway is the user's own), or the profile the form points at is
    the one that lists this checkpoint. ``(None, reason)`` means refuse and say
    why. A route means the form's profile cannot serve this graph, and carries
    the profile that can.

    The comparison is against the profile the form's GATEWAY belongs to, not
    against the form's checkpoint: loading a JSON into the editor rewrites that
    field from the graph, so comparing the graph's checkpoint to it compares the
    graph with itself and can never fire, which is how a SNOFS graph reached the
    klein group (2026-09-22).
    """
    unets = payload_unets(payload)
    if not unets:
        return None, ""
    here = profile_for_gateway(form_profile.gateway, all_profiles)
    if here is None:
        return None, ""
    doc = studio_meta.default() if meta is None else meta
    checkpoint = unets[0]
    names = profiles_for_checkpoint(checkpoint, all_profiles)
    if not names:
        return None, (
            f"No profile lists {checkpoint}, so nothing is known to serve it. Add the "
            "checkpoint to a profile's list on the Config page."
        )
    if len(names) > 1:
        return None, (
            f"{checkpoint} is listed by {len(names)} profiles ({', '.join(names)}), so "
            "which container should render it is ambiguous. Leave it on one profile."
        )
    target = all_profiles[names[0]]
    mixed = mixed_family_reason(target, doc)
    if mixed:
        return None, mixed
    if target.name == here.name:
        return None, ""
    family = checkpoint_family(checkpoint, doc)
    return (
        Route(
            family=family,
            name=target.name,
            profile=target,
            image=studio_meta.image_for_family(family, doc),
        ),
        "",
    )


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


def _coerce_checkpoints(data: dict[str, Any]) -> list[str]:
    """The profile's checkpoint list, migrating a single-checkpoint record.

    A file written before the list existed carries one ``unet``; it loads as a
    one-entry list so an existing profile keeps working.
    """
    raw = data.get("checkpoints")
    listed: list[str] = []
    if isinstance(raw, list):
        listed = [str(x).strip() for x in raw if str(x).strip()]
    if listed:
        return listed
    legacy = str(data.get("unet") or "").strip()
    return [legacy] if legacy else []


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
        checkpoints=_coerce_checkpoints(data),
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


def seed_checkpoints(name: str, meta: dict[str, Any] | None = None) -> list[str]:
    """The checkpoints a new profile starts from, seeded by the metadata document.

    ``klein5090`` serves the SNOFS family and every other name the plain Klein
    cuts, so a new profile starts able to serve what its group was built for.
    The list is the profile's own from then on; this is only the seed.
    """
    doc = studio_meta.default() if meta is None else meta
    family = "snofs" if (name or "").strip() == "klein5090" else "klein"
    entry = studio_meta.entry_for_family(family, doc)
    listed = [str(x).strip() for x in (entry.get(studio_meta.UNETS) or []) if str(x).strip()]
    return listed


def default_profile(name: str = "klein", meta: dict[str, Any] | None = None) -> SaladProfile:
    """A built-in profile: its checkpoint list is the metadata document's seed
    for the family its group serves, and that list is what routing reads."""
    key = (name or "klein").strip() or "klein"
    if key == "klein5090":
        gw = _read_optional_text(GATEWAY_KLEIN_5090_PATH) or KLEIN_5090_GATEWAY
    else:
        gw = _read_optional_text(GATEWAY_KLEIN_PATH) or KLEIN_GATEWAY
    return SaladProfile(
        name=key,
        gateway=gw,
        key_path=DEFAULT_KEY_PATH,
        graph="klein",
        width=1024,
        height=1024,
        steps=20,
        checkpoints=seed_checkpoints(key, meta),
        use_loras=True,
        selected_loras=list(DEFAULT_KLEIN_LORA_IDS),
    )


def fallback_gateway(name: str) -> str:
    """The published gateway for a built-in profile name, or ``""``.

    Used when a stored profile carries no gateway, so the badges and the status
    probe still have somewhere to point.
    """
    key = (name or "").strip()
    if key == "klein5090":
        return KLEIN_5090_GATEWAY
    if key == "klein":
        return KLEIN_GATEWAY
    return ""


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
