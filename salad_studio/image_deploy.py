"""Image deployment: where each container image lives, and what a host needs.

Two images run the two unet families, and two hosts run them: a Salad container
group (the Config page's policy points at a tag) and a vast.ai instance (the
Config page's Vast.ai instances section renders on one). Both hosts need the same
handful of things - the tag, the ports the container answers on, and the
(the gated-unet token, the Civitai token, the boot budget).

What an image *is* comes from the metadata document
(``routing.families.<family>.deployment``); what the user adds on top — extra
environment entries, and images of their own — is kept in
``~/.config/salad/studio-images.json``, beside the profiles and the token store,
so nothing about a deployment lands in the repo.

No UI here, and token values are passed in rather than read: every command
builder is a pure function a test drives with a literal map.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Top-level, the way this package's leaf modules are imported (studio_log,
# studio_meta): one module object per process, shared with the app and tests.
import studio_meta  # noqa: E402

SETTINGS_PATH = Path.home() / ".config" / "salad" / "studio-images.json"
DOC_VERSION = 1
# Where a user's own image is built from when they do not say otherwise.
DEFAULT_CONTEXT = "salad_klein"
# The vast.ai offer a create line needs; the user picks a real one from
# ``vastai search offers``, so the command ships with a placeholder.
OFFER_PLACEHOLDER = "OFFER_ID"
SOURCE_DOCUMENT = "document"
SOURCE_SETTINGS = "settings"


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ports(value: Any) -> dict[str, int]:
    """The published ports a stored row names, keyed by role.

    A row that names no port, or a non-numeric one, keeps no key: the entry then
    reports 0 and its commands publish nothing, which is what "no port" means.
    Reading a stored row stays this lenient - a hand-edited file must not stop
    the page - so a port a user *typed* into the form is checked before it is
    stored instead (see ``port_refusal``).
    """
    raw = value if isinstance(value, dict) else {}
    out: dict[str, int] = {}
    for key in (studio_meta.PORT_API, studio_meta.PORT_COMFY):
        port = _int(raw.get(key))
        if port:
            out[key] = port
    return out


# The port knobs a user types into, each with the name the Config page labels it.
PORT_FIELDS: tuple[tuple[str, str], ...] = (
    (studio_meta.PORT_API, "API port"),
    (studio_meta.PORT_COMFY, "ComfyUI port"),
)


def port_refusal(ports: dict[str, Any] | None) -> str:
    """The sentence for the first typed port that names no port, or "".

    A port that is not a positive whole number is not a port: nothing of it
    would be stored, so the entry would report 0 and its commands would publish
    nothing while the page reported the image as added. An empty knob means "no
    port" and is left alone; only a non-empty one that cannot be read is
    refused, and the sentence names the field the page shows.
    """
    raw = ports if isinstance(ports, dict) else {}
    for key, label in PORT_FIELDS:
        text = _text(raw.get(key))
        if not text:
            continue
        try:
            port = int(text)
        except ValueError:
            return f"{label} must be a whole number (got {text!r})."
        if port <= 0:
            return f"{label} must be a positive whole number (got {text!r})."
    return ""


def mask(value: str) -> str:
    """A secret shown the way the Tokens page shows one: never in full."""
    raw = _text(value)
    if not raw:
        return "(missing)"
    if len(raw) <= 4:
        return "set (****)"
    return f"set (…{raw[-4:]})"


def placeholder(name: str) -> str:
    """The shell placeholder a command uses instead of a secret's value."""
    return "${" + _text(name) + "}"


# ---------------------------------------------------------------------------
# The entries: the document's two images, then any the user added.
# ---------------------------------------------------------------------------
def entries(doc: dict[str, Any] | None, settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every image this app can deploy, the document's first.

    Each entry is one image: ``key`` (what its extra environment is filed
    under), ``name``, ``tag``, the family it serves (``""`` for a user's own
    image), and the facts a host needs. A documented family whose entry names no
    image is left out: there is nothing to deploy.
    """
    out: list[dict[str, Any]] = []
    for family, entry in sorted(studio_meta.families(doc).items()):
        tag = _text(entry.get(studio_meta.IMAGE))
        if not tag:
            continue
        deploy = studio_meta.deployment_for_family(family, doc)
        out.append(
            {
                "key": family,
                "name": family,
                "tag": tag,
                "family": family,
                "unets": list(entry.get(studio_meta.UNETS) or []),
                "source": SOURCE_DOCUMENT,
                "context": _text(deploy.get(studio_meta.CONTEXT)) or DEFAULT_CONTEXT,
                "base_image": _text(deploy.get(studio_meta.BASE_IMAGE)),
                "build_arg": _text(deploy.get(studio_meta.BUILD_ARG)),
                "ports": dict(deploy.get(studio_meta.PORTS) or {}),
                "env": list(deploy.get(studio_meta.ENV) or []),
                "gpu": _text(deploy.get(studio_meta.GPU)),
                "disk_gb": _int(deploy.get(studio_meta.DISK_GB)),
                "vcpu": _int(deploy.get(studio_meta.VCPU)),
                "memory_gb": _int(deploy.get(studio_meta.MEMORY_GB)),
            }
        )
    for row in (settings or {}).get("images") or []:
        if not isinstance(row, dict):
            continue
        tag = _text(row.get("tag"))
        name = _text(row.get("name"))
        if not tag or not name:
            continue
        out.append(
            {
                "key": name,
                "name": name,
                "tag": tag,
                "family": "",
                "unets": [],
                "source": SOURCE_SETTINGS,
                "context": _text(row.get("context")) or DEFAULT_CONTEXT,
                "base_image": "",
                "build_arg": _text(row.get("build_arg")),
                "ports": {
                    studio_meta.PORT_API: _int((row.get("ports") or {}).get(studio_meta.PORT_API)),
                    studio_meta.PORT_COMFY: _int((row.get("ports") or {}).get(studio_meta.PORT_COMFY)),
                },
                "env": [],
                "gpu": "",
                "disk_gb": 0,
                "vcpu": 0,
                "memory_gb": 0,
            }
        )
    return out


def entry_by_ref(all_entries: list[dict[str, Any]], ref: str) -> dict[str, Any] | None:
    """The entry a Config page or a vast.ai row refers to, or None.

    A reference is the entry's key, its family or its tag, matched exactly
    first and case-insensitively after that, so a tag pasted from a registry
    finds its entry.
    """
    wanted = _text(ref)
    if not wanted:
        return None
    for entry in all_entries:
        if wanted in (entry["key"], entry["family"], entry["tag"]):
            return entry
    low = wanted.lower()
    for entry in all_entries:
        if low in (str(entry["key"]).lower(), str(entry["family"]).lower(), str(entry["tag"]).lower()):
            return entry
    return None


def tag_options(doc: dict[str, Any] | None, settings: dict[str, Any] | None = None) -> list[str]:
    """The tags a page may offer as a reference, document's first, deduped."""
    out: list[str] = []
    for entry in entries(doc, settings):
        tag = str(entry["tag"])
        if tag not in out:
            out.append(tag)
    return out


# ---------------------------------------------------------------------------
# The environment: what the document documents, plus what the user added.
# ---------------------------------------------------------------------------
def extra_env(settings: dict[str, Any] | None, key: str) -> list[dict[str, str]]:
    """The user's own environment rows for one entry, in the order added."""
    rows = (settings or {}).get("env") or {}
    found = rows.get(_text(key)) if isinstance(rows, dict) else None
    out: list[dict[str, str]] = []
    for row in found or []:
        if not isinstance(row, dict):
            continue
        name = _text(row.get(studio_meta.ENV_NAME))
        if name:
            out.append(
                {
                    studio_meta.ENV_NAME: name,
                    studio_meta.ENV_VALUE: _text(row.get(studio_meta.ENV_VALUE)),
                }
            )
    return out


def env_rows(
    entry: dict[str, Any],
    extra: list[dict[str, str]] | None = None,
    tokens: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Every environment row an entry deploys with, documented rows first.

    Each row carries ``value`` (the real one, resolved from the token map when
    the document names a token slot), ``source`` ("token", "document" or
    "yours"), ``note`` and ``secret``. A user's row for a name the document
    already documents replaces that row's value rather than repeating the name.
    """
    supplied = tokens or {}
    out: list[dict[str, str]] = []
    by_name: dict[str, dict[str, str]] = {}
    for row in entry.get("env") or []:
        if not isinstance(row, dict):
            continue
        name = _text(row.get(studio_meta.ENV_NAME))
        if not name:
            continue
        slot = _text(row.get(studio_meta.ENV_TOKEN))
        value = supplied.get(slot, "") if slot else _text(row.get(studio_meta.ENV_VALUE))
        built = {
            studio_meta.ENV_NAME: name,
            studio_meta.ENV_VALUE: value,
            "source": "token" if slot else "document",
            studio_meta.ENV_NOTE: _text(row.get(studio_meta.ENV_NOTE)),
            "secret": "yes" if slot else "no",
        }
        by_name[name] = built
        out.append(built)
    for row in extra or []:
        name = _text((row or {}).get(studio_meta.ENV_NAME))
        if not name:
            continue
        value = _text((row or {}).get(studio_meta.ENV_VALUE))
        existing = by_name.get(name)
        if existing is not None:
            existing[studio_meta.ENV_VALUE] = value
            existing["source"] = "yours"
            continue
        built = {
            studio_meta.ENV_NAME: name,
            studio_meta.ENV_VALUE: value,
            "source": "yours",
            studio_meta.ENV_NOTE: "",
            "secret": "no",
        }
        by_name[name] = built
        out.append(built)
    return out


def shown_value(row: dict[str, str], *, include_values: bool = False) -> str:
    """How one row's value is shown: the real one only when asked for."""
    value = _text((row or {}).get(studio_meta.ENV_VALUE))
    if include_values or str((row or {}).get("secret")) != "yes":
        return value
    return mask(value)


def env_assignments(
    rows: list[dict[str, str]], *, include_values: bool = False
) -> list[tuple[str, str]]:
    """(name, value) pairs for a command, secrets as placeholders by default."""
    out: list[tuple[str, str]] = []
    for row in rows or []:
        name = _text((row or {}).get(studio_meta.ENV_NAME))
        if not name:
            continue
        value = _text((row or {}).get(studio_meta.ENV_VALUE))
        if str((row or {}).get("secret")) == "yes" and not include_values:
            value = placeholder(name)
        out.append((name, value))
    return out


# ---------------------------------------------------------------------------
# The commands.
# ---------------------------------------------------------------------------
def build_command(entry: dict[str, Any]) -> str:
    """``docker build`` for one entry, with its build arg and context."""
    tag = _text((entry or {}).get("tag"))
    context = _text((entry or {}).get("context")) or DEFAULT_CONTEXT
    arg = _text((entry or {}).get("build_arg"))
    arg_part = f" --build-arg {arg}" if arg else ""
    return f"docker build{arg_part} -t {tag} {context}"


def push_command(entry: dict[str, Any]) -> str:
    return f"docker push {_text((entry or {}).get('tag'))}"


def port_args(entry: dict[str, Any]) -> list[str]:
    """``-p container:container`` for each port the entry publishes."""
    ports = (entry or {}).get("ports") or {}
    out: list[str] = []
    for key in (studio_meta.PORT_API, studio_meta.PORT_COMFY):
        port = _int(ports.get(key))
        if port:
            out.append(f"-p {port}:{port}")
    return out


def docker_run_command(
    entry: dict[str, Any],
    rows: list[dict[str, str]] | None = None,
    *,
    include_values: bool = False,
) -> str:
    """``docker run`` for a host of the user's own, with ports and env."""
    parts = ["docker run --gpus all", *port_args(entry)]
    for name, value in env_assignments(rows or [], include_values=include_values):
        parts.append(f"-e {name}={value}")
    parts.append(_text((entry or {}).get("tag")))
    return " ".join(parts)


def vast_create_command(
    entry: dict[str, Any],
    rows: list[dict[str, str]] | None = None,
    *,
    include_values: bool = False,
    offer: str = OFFER_PLACEHOLDER,
) -> str:
    """The vast.ai create line for one entry.

    ``--env`` carries docker-style options, which is where vast.ai takes the
    ports and the environment; the image's own ENTRYPOINT does the first-boot
    download, so no ``--onstart-cmd`` and no ssh/jupyter injection is asked for.
    The host port vast assigns is read back from the instance, so a random
    external port is fine.
    """
    disk = _int((entry or {}).get("disk_gb")) or 100
    env_parts = [*port_args(entry)]
    for name, value in env_assignments(rows or [], include_values=include_values):
        env_parts.append(f"-e {name}={value}")
    return (
        f"vastai create instance {_text(offer) or OFFER_PLACEHOLDER} "
        f"--image {_text((entry or {}).get('tag'))} --disk {disk} "
        f"--env '{' '.join(env_parts)}'"
    )


def salad_fields(
    entry: dict[str, Any],
    rows: list[dict[str, str]] | None = None,
    *,
    include_values: bool = False,
) -> list[tuple[str, str]]:
    """The Salad portal fields for one entry, as (field, value) rows.

    The values a group has to be created with: the image, the ports, the GPU
    class, the size and the environment. A secret's value is masked unless the
    caller asks for it, so the table can be shown on screen safely.
    """
    ports = (entry or {}).get("ports") or {}
    api = _int(ports.get(studio_meta.PORT_API))
    comfy = _int(ports.get(studio_meta.PORT_COMFY))
    # A portal field is typed into a web form, so a secret is shown masked (or
    # in full when the caller asks) rather than as the shell placeholder a
    # command line uses.
    env_text = ", ".join(
        f"{row.get(studio_meta.ENV_NAME)}={shown_value(row, include_values=include_values)}"
        for row in rows or []
        if _text((row or {}).get(studio_meta.ENV_NAME))
    )
    fields = [
        ("Image", _text((entry or {}).get("tag"))),
        ("Container gateway port", str(api) if api else "(none)"),
        ("Comfy port (direct)", str(comfy) if comfy else "(none)"),
        ("GPU", _text((entry or {}).get("gpu")) or "(pick one)"),
    ]
    if _int((entry or {}).get("vcpu")) or _int((entry or {}).get("memory_gb")):
        fields.append(
            (
                "vCPU / RAM",
                f"{_int((entry or {}).get('vcpu')) or 4} / "
                f"{_int((entry or {}).get('memory_gb')) or 30} GB",
            )
        )
    if _int((entry or {}).get("disk_gb")):
        fields.append(("Disk", f"{_int((entry or {}).get('disk_gb'))} GB"))
    fields.append(("Env", env_text or "(none)"))
    return fields


def deploy_script(
    entry: dict[str, Any],
    rows: list[dict[str, str]] | None = None,
    *,
    include_values: bool = False,
) -> str:
    """The whole deploy story for one entry, as the Config page's images section shows it."""
    lines = [
        "# build and push",
        build_command(entry),
        push_command(entry),
        "",
        "# a host of your own",
        docker_run_command(entry, rows, include_values=include_values),
        "",
        "# vast.ai (the image's own ENTRYPOINT does the first-boot download)",
        vast_create_command(entry, rows, include_values=include_values),
        "",
        "# Salad portal fields",
    ]
    lines += [f"{name}: {value}" for name, value in salad_fields(entry, rows, include_values=include_values)]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The store: the user's own images and extra environment rows.
# ---------------------------------------------------------------------------
def empty_settings() -> dict[str, Any]:
    return {"version": DOC_VERSION, "images": [], "env": {}}


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """The user's own images and extra environment, or an empty store.

    A missing, unreadable or hand-broken file reads as "nothing added", so a bad
    file leaves the page usable instead of aborting startup.
    """
    target = Path(path) if path is not None else SETTINGS_PATH
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return empty_settings()
    try:
        data = json.loads(raw)
    except ValueError:
        return empty_settings()
    if not isinstance(data, dict):
        return empty_settings()
    images: list[dict[str, str]] = []
    for row in data.get("images") or []:
        if not isinstance(row, dict):
            continue
        name = _text(row.get("name"))
        tag = _text(row.get("tag"))
        if not name or not tag:
            continue
        images.append(
            {
                "name": name,
                "tag": tag,
                "context": _text(row.get("context")),
                "build_arg": _text(row.get("build_arg")),
                "ports": _ports(row.get("ports")),
            }
        )
    env: dict[str, list[dict[str, str]]] = {}
    raw_env = data.get("env") if isinstance(data.get("env"), dict) else {}
    for key, rows in raw_env.items():
        cleaned = [
            {
                studio_meta.ENV_NAME: _text(r.get(studio_meta.ENV_NAME)),
                studio_meta.ENV_VALUE: _text(r.get(studio_meta.ENV_VALUE)),
            }
            for r in (rows or [])
            if isinstance(r, dict) and _text(r.get(studio_meta.ENV_NAME))
        ]
        if cleaned:
            env[_text(key)] = cleaned
    return {"version": DOC_VERSION, "images": images, "env": env}


def save_settings(settings: dict[str, Any], path: Path | None = None) -> Path:
    """Write the store. Returns the path it wrote."""
    target = Path(path) if path is not None else SETTINGS_PATH
    payload = {
        "version": DOC_VERSION,
        "images": [
            {
                "name": _text(row.get("name")),
                "tag": _text(row.get("tag")),
                "context": _text(row.get("context")),
                "build_arg": _text(row.get("build_arg")),
                "ports": _ports(row.get("ports")),
            }
            for row in (settings or {}).get("images") or []
            if isinstance(row, dict) and _text(row.get("name")) and _text(row.get("tag"))
        ],
        "env": {
            str(key): [
                {
                    studio_meta.ENV_NAME: _text(r.get(studio_meta.ENV_NAME)),
                    studio_meta.ENV_VALUE: _text(r.get(studio_meta.ENV_VALUE)),
                }
                for r in rows or []
                if isinstance(r, dict) and _text(r.get(studio_meta.ENV_NAME))
            ]
            for key, rows in ((settings or {}).get("env") or {}).items()
        },
    }
    payload["env"] = {k: v for k, v in payload["env"].items() if v}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def add_image(
    settings: dict[str, Any],
    name: str,
    tag: str,
    *,
    context: str = "",
    build_arg: str = "",
    ports: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """Add the user's own image. Returns ``(settings, refusal)``.

    ``ports`` are the ports the image publishes, keyed by role
    (``studio_meta.PORT_API`` / ``PORT_COMFY``). They are stored with the row and
    survive the round trip, so an image of your own can carry the same deploy
    facts a documented family does; with none, its commands publish no port. A
    typed port that cannot be read is refused by name rather than stored as
    "no port".
    """
    key = _text(name)
    image = _text(tag)
    if not key:
        return settings, "Type a name for the image."
    if not image:
        return settings, "Type the image tag, for example user/eldermark-klein:tag."
    bad_port = port_refusal(ports)
    if bad_port:
        return settings, bad_port
    out = dict(settings)
    rows = [row for row in (settings or {}).get("images") or [] if isinstance(row, dict)]
    if any(_text(row.get("name")).lower() == key.lower() for row in rows):
        return settings, f"{key} is already in the list."
    rows.append(
        {
            "name": key,
            "tag": image,
            "context": _text(context),
            "build_arg": _text(build_arg),
            "ports": _ports(ports),
        }
    )
    out["images"] = rows
    return out, ""


def remove_image(settings: dict[str, Any], name: str) -> tuple[dict[str, Any], bool]:
    """Drop the user's own image, with the environment rows filed under it."""
    key = _text(name)
    rows = [row for row in (settings or {}).get("images") or [] if isinstance(row, dict)]
    kept = [row for row in rows if _text(row.get("name")).lower() != key.lower()]
    removed = len(kept) != len(rows)
    out = dict(settings)
    out["images"] = kept
    if removed:
        env = dict((settings or {}).get("env") or {})
        for name_key in [k for k in env if str(k).lower() == key.lower()]:
            env.pop(name_key, None)
        out["env"] = env
    return out, removed


def add_env(
    settings: dict[str, Any], key: str, name: str, value: str
) -> tuple[dict[str, Any], str]:
    """Add one environment row for an entry. Returns ``(settings, refusal)``."""
    entry_key = _text(key)
    env_name = _text(name)
    if not entry_key:
        return settings, "Pick an image first."
    if not env_name:
        return settings, "Type the environment variable's name."
    if not env_name.replace("_", "").isalnum() or env_name[0].isdigit():
        return settings, f"{env_name} is not a usable environment variable name."
    env = {str(k): list(v) for k, v in ((settings or {}).get("env") or {}).items()}
    rows = env.get(entry_key, [])
    if any(_text(row.get(studio_meta.ENV_NAME)) == env_name for row in rows):
        return settings, f"{env_name} is already set for {entry_key}."
    rows.append({studio_meta.ENV_NAME: env_name, studio_meta.ENV_VALUE: _text(value)})
    env[entry_key] = rows
    out = dict(settings)
    out["env"] = env
    return out, ""


def remove_env(settings: dict[str, Any], key: str, name: str) -> tuple[dict[str, Any], bool]:
    """Drop one environment row. Returns ``(settings, removed)``."""
    entry_key = _text(key)
    env_name = _text(name)
    env = {str(k): list(v) for k, v in ((settings or {}).get("env") or {}).items()}
    rows = env.get(entry_key, [])
    kept = [row for row in rows if _text(row.get(studio_meta.ENV_NAME)) != env_name]
    removed = len(kept) != len(rows)
    if removed:
        if kept:
            env[entry_key] = kept
        else:
            env.pop(entry_key, None)
    out = dict(settings)
    out["env"] = env
    return out, removed
