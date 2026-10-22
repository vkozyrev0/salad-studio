"""Config: the profile, its images, its Salad group policy and its vast.ai hosts.

Four sections, one per segment. Each action writes only what its own section
shows: a profile save takes the profile fields, a policy apply takes the policy
fields, and the image a vast.ai action deploys is the one it was handed, not a
dropdown on another segment.

``state()`` carries what the open section draws. The checkpoint list, the
environment rows and the instance table are short; the image catalogue is a
list of options and its environment is drawn for the one image picked.
"""
from __future__ import annotations

import copy
from typing import Any

import image_deploy
import profiles
import salad_status
import studio_meta
import vast

SECTIONS: tuple[tuple[str, str], ...] = (
    ("profile", "Profile"),
    ("images", "Images"),
    ("policy", "Salad group"),
    ("vast", "Vast.ai"),
)
MODE_SEGMENTS: tuple[tuple[str, str], ...] = (("salad", "Salad gateway"), ("vast", "Vast.ai instance"))
LABELS: dict[str, str] = {"gateway": "Gateway URL", "instance": "Instance URL"}
PROBE_KINDS: tuple[str, ...] = ("startup", "readiness")
PROBE_KEYS: tuple[str, ...] = ("path", "port", "initial_delay_seconds", "period_seconds",
                               "timeout_seconds", "success_threshold", "failure_threshold")
VAST_COLUMNS: tuple[str, ...] = ("Use", "Label", "Address", "Image", "State", "GPU", "Active")
OFFER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("gpu", "GPU"), ("price", "$/hr"), ("perf", "Perf"), ("value", "Perf/$"),
    ("vram", "VRAM GB"), ("disk", "Disk GB"),
)
OFFER_LIMIT = 40

# The field each refusal names, for a page that puts the message under a control.
FIELD_OF: dict[str, str] = {
    "width": "width", "height": "height", "steps": "steps", "cfg": "cfg", "seed": "seed",
}


def _document() -> dict[str, Any]:
    """The metadata document, as ``image_deploy`` reads it.

    That module imports ``studio_meta`` top-level, so its copy is the one that
    turns the document into entries, and the two copies must agree.
    """
    return studio_meta.default()


def _image_entries(settings: dict[str, Any]) -> list[dict[str, Any]]:
    return image_deploy.entries(_document(), settings)


def _token_map(studio: Any) -> dict[str, str]:
    """Every stored key by slot, so an environment row can show its own name in place of a literal."""
    from salad_studio import tokens

    out: dict[str, str] = {}
    for kind, _label, _rel in tokens.TOKEN_SPECS:
        try:
            value = studio.services.token(kind) if studio is not None else ""
        except (OSError, AttributeError):
            value = ""
        if value:
            out[kind] = value
    return out


def _field_named(exc: ValueError) -> str | None:
    """The control a :meth:`Form.profile` refusal names, lowercased."""
    head = str(exc).split(" ", 1)[0].strip().lower()
    return FIELD_OF.get(head)


def _checkpoint_list(studio: Any, selected: str | None) -> tuple[list[dict[str, Any]], str | None]:
    names = list(studio.profile.checkpoints or [])
    chosen = selected if selected in names else (names[0] if names else None)
    return [{"name": name, "selected": name == chosen} for name in names], chosen


class ConfigController:
    page = "config"

    def __init__(self, studio: Any) -> None:
        self.studio = studio
        self.section = "profile"
        self.checkpoint = ""
        self.env_image = ""
        self.show_tokens = False
        # The policy as last loaded or saved: ``group_name`` and ``version`` are
        # the group's own facts, and only a load or an apply knows them.
        self.policy: dict[str, Any] = {}
        self.gpu_names: dict[str, str] = {}
        self.gpu_selected: list[str] = []
        self.policy_edited = False
        self.policy_form: dict[str, Any] = self._policy_from({})
        self.vast_index: int | None = None
        self.offer_selected: dict[str, Any] | None = None
        self.offer_rows: list[dict[str, Any]] = []
        self.vast_gpus = ", ".join(vast.DEFAULT_GPU_NAMES)
        self.vast_endpoint = ""

    def register(self, table: Any) -> None:
        table.action("config.view")(self.view)
        table.action("config.select_vast", need={"index": int})(self.select_vast)
        table.action("config.select_offer", need={"index": int})(self.select_offer)
        for name, fn in (
            ("section", self.section_state),
            ("load_profile", self.load_profile), ("add_profile", self.add_profile),
            ("save_profile", self.save_profile), ("delete_profile", self.delete_profile),
            ("set_mode", self.set_mode), ("use_selected_instance", self.use_selected_instance),
            ("select_checkpoint", self.select_checkpoint), ("add_checkpoint", self.add_checkpoint),
            ("remove_checkpoint", self.remove_checkpoint),
            ("set_env_image", self.set_env_image), ("add_env", self.add_env),
            ("remove_env", self.remove_env), ("save_env", self.save_env),
            ("set_policy", self.set_policy), ("load_policy", self.load_policy),
            ("apply_policy", self.apply_policy), ("reallocate", self.reallocate),
            ("set_vast_endpoint", self.set_vast_endpoint),
            ("add_vast", self.add_vast), ("fetch_vast", self.fetch_vast),
            ("set_vast_image", self.set_vast_image), ("make_profile_for_vast", self.make_profile_for_vast),
            ("remove_vast", self.remove_vast), ("save_vast", self.save_vast),
            ("set_vast_gpus", self.set_vast_gpus), ("search_offers", self.search_offers),
            ("rent_offer", self.rent_offer), ("replace_destroyed", self.replace_destroyed),
        ):
            table.action(f"config.{name}")(fn)

    def view(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        return self.state()

    # -- state

    def state(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "sections": [{"id": key, "label": label} for key, label in SECTIONS],
            "profile": self._profile_state(),
            "images": self._images_state(),
            "policy": self._policy_state(),
            "vast": self._vast_state(),
        }

    def _images_state(self) -> dict[str, Any]:
        """The Images section: the tags on offer, the one picked, and its environment.

        A secret's value is sent masked unless the person asked to see it, so a
        reply never carries a provider key the page did not already show.
        """
        settings = image_deploy.load_settings()
        tags = image_deploy.tag_options(_document(), settings)
        picked = image_deploy.entry_by_ref(_image_entries(settings), self.env_image or "") or None
        if picked is None and self.env_image == "" and tags:
            # Nothing picked yet: the section opens on the first image, the one
            # a fresh install deploys, instead of an empty environment.
            picked = image_deploy.entry_by_ref(_image_entries(settings), tags[0])
        rows: list[dict[str, Any]] = []
        if picked is not None:
            documented = image_deploy.env_rows(picked, extra=image_deploy.extra_env(settings, picked["key"]),
                                               tokens=_token_map(self.studio))
            rows = [{"name": str(row.get(studio_meta.ENV_NAME) or ""),
                     "value": image_deploy.shown_value(row, include_values=self.show_tokens),
                     "secret": str(row.get("secret")) == "yes",
                     "note": "documented" if row.get("source") == "document" else ""}
                    for row in documented]
        return {
            "tags": tags,
            "image": (picked or {}).get("tag", ""),
            "key": (picked or {}).get("key", ""),
            "show_tokens": self.show_tokens,
            "env": rows,
            "script": image_deploy.deploy_script(picked, documented, include_values=self.show_tokens)
            if picked is not None else "",
            "own_image": [],
        }

    def _profile_state(self) -> dict[str, Any]:
        form = self.studio.form
        stored = self.studio.stored_profile()
        checkpoints, chosen = _checkpoint_list(self.studio, self.checkpoint)
        self.checkpoint = chosen or ""
        return {
            "profiles": sorted(profiles.load_all()),
            "name": form.name,
            "gateway": form.gateway,
            "label": LABELS["gateway"],
            "modes": [{"id": key, "label": label} for key, label in MODE_SEGMENTS],
            "mode": form.mode if form.mode in ("salad", "vast") else "salad",
            "checkpoints": checkpoints,
            "selected_checkpoint": chosen,
            # Only a stored profile is the one checkpoints belong to.
            "checkpoints_editable": stored is not None,
            "serves": _serving_names(self.studio, stored),
        }

    def _policy_state(self) -> dict[str, Any]:
        """The section as typed.

        A type in one of its fields stays until the group is loaded or
        applied, and a load from another page shows once the fields carry
        nothing of this page's own: the profile's policy replaces them.
        """
        policy = self.studio.profile.policy or {}
        if not self.policy_edited or self.policy == self.policy_form:
            self._show_policy(policy)
        form = self.policy_form
        selected = set(self.gpu_selected)
        header = (f"{self.policy.get('group_name')}  v{self.policy.get('version') or '?'}"
                  if self.policy.get("group_name") else "")
        return {
            "group": header,
            "image": form["image"],
            "us_only": "us" in form["country_codes"],
            "gpus": [{"id": gid, "name": label, "selected": gid in selected}
                     for gid, label in sorted(self.gpu_names.items())],
            "probes": {kind: dict(form[kind]) for kind in PROBE_KINDS},
            "probe_keys": list(PROBE_KEYS),
            "open": bool(form["image"]),
        }

    def _vast_state(self) -> dict[str, Any]:
        doc = vast.load_doc()
        rows = [r for r in (vast.clean_row(x) for x in (doc.get("instances") or [])) if r]
        active = str(doc.get("active") or "")
        chosen = rows[self.vast_index] if self.vast_index is not None and 0 <= self.vast_index < len(rows) else None
        floors = vast.REPLACE_DEFAULTS
        return {
            "instances": [
                {"index": i, "key": vast.row_key(r), "label": vast.row_label(r),
                 "endpoint": str(r.get("endpoint") or (f"#{r.get('id')}" if r.get("id") is not None else "")),
                 "image": str(r.get("image") or ""), "state": str(r.get("state") or ""),
                 "gpu": str(r.get("gpu") or ""),
                 "active": bool(r.get("endpoint")) and str(r.get("endpoint")) == active,
                 "selected": i == self.vast_index}
                for i, r in enumerate(rows)
            ],
            "instance_columns": list(VAST_COLUMNS),
            "selected_instance": vast.row_label(chosen) if chosen else None,
            "gpus": self.vast_gpus,
            "floors": (f"max ${floors['max_price']:.2f}/hr, {floors['min_down_mbps']} down / "
                       f"{floors['min_up_mbps']} up Mbps, CUDA {floors['cuda_min']}, "
                       f"reliability {floors['min_reliability']}"),
            "offer_columns": [label for _key, label in OFFER_COLUMNS],
            "offers": [[vast.offer_cells(o).get(key, "") for key, _label in OFFER_COLUMNS]
                       for o in self.offer_rows],
            "selected_offer": vast.offer_label(self.offer_selected) if self.offer_selected else None,
        }

    # -- the profile section

    def section_state(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        self.section = str(payload.get("section") or self.section)
        return self.state()

    def _refresh_profile(self, p: profiles.SaladProfile) -> None:
        self.studio.apply_profile(p)
        self.policy_edited = False
        self._show_policy(p.policy or {})
        if self.checkpoint not in (p.checkpoints or []):
            self.checkpoint = (p.checkpoints or [""])[0]

    def load_profile(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        stored = profiles.load_all().get(name)
        if stored is None:
            ctx.note(f"Refused: there is no profile named {name!r}", level="warn")
            return self.state()
        profiles.set_active(name)
        self._refresh_profile(stored)
        ctx.note(f"Loaded profile {name}", level="info")
        return self.state()

    def add_profile(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        form = self.studio.form
        if "name" in payload:
            form.name = str(payload.get("name") or "klein").strip() or "klein"
        if "gateway" in payload:
            form.gateway = str(payload.get("gateway") or "").strip()
        name = form.name
        if name in profiles.load_all():
            ctx.note(f"Refused: there is already a profile named {name!r}", level="warn")
            return self.state()
        p = profiles.default_profile(name)
        if form.gateway:
            p.gateway = form.gateway
        profiles.upsert(p)
        profiles.set_active(p.name)
        self._refresh_profile(p)
        ctx.note(f"Added profile {p.name}", level="ok")
        return self.state()

    def save_profile(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        """Write the profile section, and nothing from the Salad group section."""
        form = self.studio.form
        form.name = str(payload.get("name") if "name" in payload else form.name).strip() or "klein"
        if "gateway" in payload:
            form.gateway = str(payload.get("gateway") or "").strip()
        if "mode" in payload:
            form.mode = str(payload.get("mode") or "salad")
        try:
            p = form.profile(self.studio.stored_profile())
        except ValueError as exc:
            field = _field_named(exc)
            ctx.dialog("Salad Studio", f"Invalid size/steps: {exc}", level="error")
            ctx.note(f"Refused: {exc}", level="error")
            if field is not None:
                ctx.effects[-1]["field"] = field
            return self.state()
        profiles.upsert(p)
        profiles.set_active(p.name)
        self._refresh_profile(p)
        ctx.note(f"Saved profile {p.name}", level="ok")
        return self.state()

    def delete_profile(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        name = str(payload.get("name") or self.studio.form.name).strip()
        if not ctx.confirmed:
            if name not in profiles.load_all():
                ctx.note(f"Refused: there is no profile named {name!r}", level="warn")
                return self.state()
            ctx.effects.append({
                "kind": "confirm",
                "token": self.studio.issue_confirm("config", "delete_profile", {"name": name}),
                "title": "Salad Studio",
                "body": (f"Delete profile {name!r}? The last profile is recreated as a default. "
                         "This cannot be undone."),
            })
            return self.state()
        left = profiles.delete(name)
        if not left:
            p = profiles.default_profile("klein")
            profiles.upsert(p)
            profiles.set_active(p.name)
            self._refresh_profile(p)
            ctx.note(f"Deleted {name}; recreated the default profile", level="ok")
        else:
            active = profiles.get_active()
            active = active if active in left else sorted(left)[0]
            profiles.set_active(active)
            self._refresh_profile(left[active])
            ctx.note(f"Deleted {name}", level="ok")
        return self.state()

    def set_mode(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        mode = str(payload.get("mode") or "salad")
        self.studio.form.mode = mode if mode in ("salad", "vast") else "salad"
        # The target follows the engine. A Salad gateway left in place would be
        # POSTed with the vast key, and a vast endpoint with the Salad key.
        gateway = self.studio.form.gateway.strip()
        endpoints = {str(row.get("endpoint") or "").strip()
                     for row in (vast.load_doc().get("instances") or [])}
        salad_gateways = {p.gateway.strip() for p in profiles.load_all().values() if p.gateway.strip()}
        if self.studio.form.mode == "vast" and (
            gateway in salad_gateways or profiles.is_salad_gateway(gateway)
        ):
            self.studio.form.gateway = ""
        elif self.studio.form.mode == "salad" and gateway in endpoints:
            self.studio.form.gateway = ""
        self.studio.publish()
        return self.state()

    def use_selected_instance(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        row = vast.active_row(vast.load_doc())
        if row is None:
            ctx.note("Refused: No vast.ai instance is selected.", level="warn")
            return self.state()
        endpoint = str(row.get("endpoint") or "")
        if not endpoint:
            ctx.note("Refused: The selected vast.ai instance has no endpoint yet.", level="warn")
            return self.state()
        self.studio.form.gateway = endpoint
        self.studio.publish()
        ctx.note(f"Using {endpoint}", level="info")
        return self.state()

    def select_checkpoint(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        name = str(payload.get("name") or "")
        if name not in (self.studio.profile.checkpoints or []):
            ctx.note(f"Refused: {name!r} is not one of the checkpoints this profile serves", level="warn")
            return self.state()
        self.checkpoint = name
        ctx.note(f"Selected checkpoint {name}", level="info")
        return self.state()

    def add_checkpoint(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        text = str(payload.get("text") or "").strip()
        if not text:
            ctx.note("Type a checkpoint filename or pick a label first", level="warn")
            return self.state()
        stored = self.studio.stored_profile()
        if stored is None:
            ctx.note("Refused: Save the profile before editing its checkpoints", level="warn")
            return self.state()
        refusal = profiles.add_checkpoint(stored, text)
        if refusal:
            ctx.note(f"Refused: {refusal}", level="warn")
            return self.state()
        profiles.upsert(stored)
        self.checkpoint = text
        self._refresh_profile(stored)
        ctx.note(f"Added checkpoint {text}", level="ok")
        return self.state()

    def remove_checkpoint(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        stored = self.studio.stored_profile()
        names = list(stored.checkpoints) if stored is not None else []
        if not names:
            ctx.note("Refused: The profile lists no checkpoints", level="warn")
            return self.state()
        name = str(payload.get("name") or "")
        if name not in names:
            ctx.note("Refused: select the checkpoint to remove", level="warn")
            return self.state()
        profiles.remove_checkpoint(stored, name)
        profiles.upsert(stored)
        self.checkpoint = ""
        self._refresh_profile(stored)
        ctx.note(f"Removed checkpoint {name}", level="ok")
        return self.state()

    # -- the images section: the environment follows the image it was handed

    def _env_image(self, ref: str) -> dict[str, Any] | None:
        """The entry ``ref`` names, or the first one offered when it names none."""
        entries = _image_entries(image_deploy.load_settings())
        entry = image_deploy.entry_by_ref(entries, ref)
        if entry is None and not ref:
            entry = entries[0] if entries else None
        return entry

    def set_env_image(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        """Pick the image whose environment the section shows, or reveal its secrets.

        The reveal travels in the payload so the value is never stored on the
        controller: the next reply sends the rows masked unless asked again.
        """
        if "show_tokens" in payload:
            self.show_tokens = bool(payload.get("show_tokens"))
        if "image" in payload:
            self.env_image = str((self._env_image(str(payload.get("image") or "")) or {}).get("tag") or "")
        return self.state()

    def add_env(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        entry = self._env_image(str(payload.get("image") or ""))
        if entry is None:
            ctx.note("Refused: Pick an image first.", level="warn")
            return self.state()
        name = str(payload.get("name") or "").strip()
        if not name:
            ctx.note("Refused: Name the environment variable first", level="warn")
            return self.state()
        settings = image_deploy.load_settings()
        settings, refusal = image_deploy.add_env(settings, entry["key"], name, str(payload.get("value") or ""))
        if refusal:
            ctx.note(f"Refused: {refusal}", level="warn")
            return self.state()
        image_deploy.save_settings(settings)
        ctx.note(f"Added {name}", level="ok")
        return self.state()

    def remove_env(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        """Remove the row the page names, not the text left in a field."""
        name = str(payload.get("name") or "").strip()
        if not name:
            ctx.note("Refused: select the environment row to remove", level="warn")
            return self.state()
        entry = self._env_image(str(payload.get("image") or ""))
        if entry is None:
            ctx.note("Refused: Pick an image first.", level="warn")
            return self.state()
        settings = image_deploy.load_settings()
        settings, removed = image_deploy.remove_env(settings, entry["key"], name)
        if removed:
            image_deploy.save_settings(settings)
        ctx.note(f"Removed {name}" if removed else f"Refused: {name} is documented, not an extra",
                 level="ok" if removed else "warn")
        return self.state()

    def save_env(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        image_deploy.save_settings(image_deploy.load_settings())
        ctx.note("Saved the environment", level="ok")
        return self.state()

    # -- the Salad group section: the policy travels with these actions

    @staticmethod
    def _policy_from(policy: dict[str, Any]) -> dict[str, Any]:
        return {
            "image": str(policy.get("image") or ""),
            "country_codes": list(policy.get("country_codes") or []),
            "gpu_classes": [str(x) for x in (policy.get("gpu_classes") or [])],
            "startup": {k: str((policy.get("startup") or {}).get(k, "")) for k in PROBE_KEYS},
            "readiness": {k: str((policy.get("readiness") or {}).get(k, "")) for k in PROBE_KEYS},
        }

    def _show_policy(self, shown: dict[str, Any]) -> None:
        self.policy = copy.deepcopy(shown or {})
        self.policy_form = self._policy_from(shown or {})
        self.gpu_selected = list(self.policy_form["gpu_classes"])

    def set_policy(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        """The fields as typed, held until Apply to Salad sends them."""
        form = self.policy_form
        if "image" in payload:
            form["image"] = str(payload.get("image") or "").strip()
        if "us_only" in payload:
            form["country_codes"] = ["us"] if payload.get("us_only") else []
        if "gpu_classes" in payload:
            self.gpu_selected = [str(x) for x in (payload.get("gpu_classes") or [])]
            form["gpu_classes"] = list(self.gpu_selected)
        probes = payload.get("probes")
        if isinstance(probes, dict):
            for kind in PROBE_KINDS:
                if isinstance(probes.get(kind), dict):
                    for key, value in probes[kind].items():
                        if key in PROBE_KEYS:
                            form[kind][key] = str(value or "")
        self.policy_edited = True
        return self.state()

    def _policy_document(self) -> dict[str, Any]:
        form = self.policy_form
        return {
            "image": form["image"],
            "country_codes": list(form["country_codes"]),
            "gpu_classes": [gid for gid in self.gpu_selected],
            "startup": dict(form["startup"]),
            "readiness": dict(form["readiness"]),
            "group_name": self.policy.get("group_name", ""),
            "version": self.policy.get("version"),
        }

    def _gateway(self) -> str:
        return (self.studio.form.gateway or self.studio.profile.gateway).strip()

    def load_policy(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        gateway = self._gateway()
        if not gateway:
            ctx.dialog("Salad Studio", "Refused: the gateway URL is empty", level="error")
            ctx.note("Refused: the gateway URL is empty", level="warn")
            return self.state()
        key = self.studio.services.salad_key()
        keep = list(self.gpu_selected)

        def work() -> Any:
            classes = salad_status.list_gpu_classes(key)
            policy, error = salad_status.load_policy(gateway, key)
            return classes, policy, error

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                ctx.dialog("Salad Studio", f"Could not load the group's policy: {result}", level="error")
                ctx.note("Could not load the group's policy", level="error")
                return
            classes, policy, error = result
            if error or policy is None:
                ctx.dialog("Salad Studio", error or "No policy came back.", level="error")
                ctx.note(error or "No policy came back.", level="error")
                return
            wanted = {str(c.get("id")): str(c.get("name") or c.get("id"))
                      for c in (classes or []) if isinstance(c, dict) and c.get("id") is not None}
            for gid in keep:
                wanted.setdefault(gid, gid)
            self.gpu_names = wanted
            # ``done`` runs outside any request, so what it shows must survive
            # the next ``state()``: the open profile carries it from here.
            self.studio.profile.policy = dict(policy)
            self.policy_edited = False
            self.studio.publish()
            ctx.note("Loaded the group's policy", level="ok")

        ctx.background(work, done)
        ctx.note("Loading the group's policy…")
        return self.state()

    def apply_policy(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        gateway = self._gateway()
        if not gateway:
            ctx.dialog("Salad Studio", "Refused: the gateway URL is empty", level="error")
            ctx.note("Refused: the gateway URL is empty", level="warn")
            return self.state()
        policy = self._policy_document()
        key = self.studio.services.salad_key()

        def work() -> Any:
            return salad_status.apply_policy(gateway, key, policy)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                ctx.dialog("Salad Studio", str(result), level="error")
                return
            status, payload = result
            if int(status) != 200:
                ctx.dialog("Salad Studio", f"Salad refused the policy: {payload}", level="error")
                ctx.note(f"Salad refused the policy: {payload}", level="error")
                return
            stored = self.studio.stored_profile()
            if stored is not None:
                stored.policy = dict(policy)
                profiles.upsert(stored)
                self.studio.profile = stored
            self.policy = dict(policy)
            self.policy_edited = False
            ctx.note("Applied the policy to the Salad group", level="ok")

        ctx.background(work, done)
        ctx.note("Applying the policy…")
        return self.state()

    def reallocate(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        if not ctx.confirmed:
            ctx.effects.append({
                "kind": "confirm",
                "token": self.studio.issue_confirm("config", "reallocate", {}),
                "title": "Salad Studio",
                "body": "Reallocate the container instance now? Live renders on it are lost.",
            })
            return self.state()
        gateway = self._gateway()
        key = self.studio.services.salad_key()

        def work() -> Any:
            return salad_status.reallocate_instance(gateway, key)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                ctx.dialog("Salad Studio", str(result), level="error")
                ctx.note(f"Could not reallocate: {result}", level="error")
                return
            status, body = result
            ok = int(status) in (200, 201, 204)
            ctx.note("Reallocated the instance" if ok else f"Salad refused: {body}",
                     level="ok" if ok else "error")

        ctx.background(work, done)
        ctx.note("Reallocating the instance…")
        return self.state()

    # -- the Vast.ai section

    def _selected_row(self) -> dict[str, Any] | None:
        rows = [r for r in (vast.clean_row(x) for x in (vast.load_doc().get("instances") or [])) if r]
        index = self.vast_index
        return rows[index] if index is not None and 0 <= index < len(rows) else None

    @staticmethod
    def _image_ref(payload: dict[str, Any]) -> str:
        """The image a vast.ai action deploys: the one it was handed."""
        return str(payload.get("image") or "")

    def select_vast(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        index = payload["index"]
        doc = vast.load_doc()
        rows = [r for r in (vast.clean_row(x) for x in (doc.get("instances") or [])) if r]
        if not (0 <= index < len(rows)):
            ctx.note("Refused: select an instance first", level="warn")
            return self.state()
        row = rows[index]
        doc = vast.set_active(doc, vast.row_key(row))
        vast.save_doc(doc)
        self.vast_index = index
        ctx.note(f"Selected {vast.row_label(row)}", level="ok")
        return self.state()

    def select_offer(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        index = payload["index"]
        if not (0 <= index < len(self.offer_rows)):
            ctx.note("Refused: select an offer first", level="warn")
            return self.state()
        self.offer_selected = self.offer_rows[index]
        self.studio.services.offers = {**self._offers_map(), "selected": self.offer_selected}
        ctx.note(f"Selected {vast.offer_label(self.offer_selected)}", level="info")
        return self.state()

    def _offers_map(self) -> dict[str, Any]:
        return {str(o.get("id") or i): o for i, o in enumerate(self.offer_rows)}

    def set_vast_endpoint(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        self.vast_endpoint = str(payload.get("endpoint") or "")
        return self.state()

    def add_vast(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        text = str(payload.get("endpoint", self.vast_endpoint) or "")
        endpoint = vast.normalize_endpoint(text)
        if not endpoint:
            ctx.note("Refused: type an instance id or a host:port", level="warn")
            return self.state()
        doc, refusal = vast.add_instance(vast.load_doc(), endpoint)
        if refusal:
            ctx.note(f"Refused: {refusal}", level="warn")
            return self.state()
        vast.save_doc(doc)
        self.vast_index = None
        self.vast_endpoint = ""
        ctx.note(f"Added {endpoint}", level="ok")
        return self.state()

    def fetch_vast(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        key = self.studio.services.token("vast")

        def work() -> Any:
            return vast.fetch_records(key)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                ctx.dialog("Salad Studio", str(result), level="error")
                return
            if result.get("error"):
                ctx.dialog("Salad Studio", str(result["error"]), level="error")
                return
            doc, _summary = vast.reconcile(vast.load_doc(), result.get("instances") or [],
                                           complete=not result.get("truncated"))
            vast.save_doc(doc)
            self.vast_index = None
            ctx.note(f"Fetched {len(result.get('instances') or [])} instance(s)", level="ok")

        ctx.background(work, done)
        ctx.note("Fetching vast.ai instances…")
        return self.state()

    def set_vast_image(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        row = self._selected_row()
        if row is None:
            ctx.note("Refused: select an instance first", level="warn")
            return self.state()
        entry = image_deploy.entry_by_ref(_image_entries(image_deploy.load_settings()), self._image_ref(payload))
        if entry is None:
            ctx.note("Refused: name the image to set, as the Images section shows it", level="warn")
            return self.state()
        image = str(entry.get("tag") or "")
        key = vast.row_key(row)
        doc = vast.load_doc()
        rows = []
        for existing in doc.get("instances") or []:
            clean = vast.clean_row(existing)
            rows.append({**clean, "image": image} if clean and vast.row_key(clean) == key else existing)
        vast.save_doc({**doc, "instances": rows})
        ctx.note(f"Set the image on {vast.row_label(row)}", level="ok")
        return self.state()

    def make_profile_for_vast(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        row = self._selected_row()
        if row is None:
            ctx.note("Refused: select an instance first", level="warn")
            return self.state()
        name = f"vast-{vast.row_key(row)}"
        p = profiles.default_profile(name)
        p.mode = "vast"
        p.gateway = str(row.get("endpoint") or "")
        profiles.upsert(p)
        profiles.set_active(name)
        self._refresh_profile(p)
        ctx.note(f"Created profile {name}", level="ok")
        return self.state()

    def remove_vast(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        row = self._selected_row()
        if row is None:
            ctx.note("Refused: select an instance first", level="warn")
            return self.state()
        key = vast.row_key(row)
        if not ctx.confirmed:
            ctx.effects.append({
                "kind": "confirm",
                "token": self.studio.issue_confirm("config", "remove_vast", {"index": self.vast_index}),
                "title": "Salad Studio",
                "body": (f"Remove instance {vast.row_label(row)} from the list? The machine itself is "
                         "not destroyed."),
            })
            return self.state()
        doc, removed = vast.remove_instance(vast.load_doc(), key)
        if removed:
            vast.save_doc(doc)
        self.vast_index = None
        ctx.note("Removed the instance" if removed else "Refused: the instance is not in the list",
                 level="ok" if removed else "warn")
        return self.state()

    def save_vast(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        vast.save_doc(vast.load_doc())
        ctx.note("Saved the instance list", level="ok")
        return self.state()

    def set_vast_gpus(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        self.vast_gpus = str(payload.get("gpus") or "")
        return self.state()

    def _criteria(self, payload: dict[str, Any]) -> dict[str, Any]:
        criteria = vast.clean_replace(vast.REPLACE_DEFAULTS)
        names = [n.strip() for n in str(payload.get("gpus", self.vast_gpus) or "").split(",") if n.strip()]
        if names:
            criteria["gpu_names"] = names
        return criteria

    def search_offers(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        criteria = self._criteria(payload)
        key = self.studio.services.token("vast")

        def work() -> Any:
            return vast.search_offers(key, criteria)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                ctx.dialog("Salad Studio", str(result), level="error")
                return
            if result.get("error"):
                ctx.dialog("Salad Studio", str(result["error"]), level="error")
                return
            offers = vast.matching_offers(list(result.get("offers") or []), criteria)
            self.offer_rows = sorted(offers, key=vast.offer_value)[:OFFER_LIMIT]
            self.offer_selected = None
            self.studio.services.offers = dict(self._offers_map())
            ctx.note(f"Found {len(self.offer_rows)} offer(s)", level="ok")

        ctx.background(work, done)
        ctx.note("Finding offers…")
        return self.state()

    def rent_offer(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        offer = self.offer_selected
        if not offer:
            ctx.note("Refused: select an offer first", level="warn")
            return self.state()
        entry = image_deploy.entry_by_ref(_image_entries(image_deploy.load_settings()), self._image_ref(payload))
        if entry is None:
            ctx.note("Refused: name the image the instance runs, as the Images section shows it", level="warn")
            return self.state()
        image = str(entry.get("tag") or "")
        if not ctx.confirmed:
            ctx.effects.append({
                "kind": "confirm",
                "token": self.studio.issue_confirm("config", "rent_offer", {"image": self._image_ref(payload)}),
                "title": "Salad Studio",
                "body": f"Rent {vast.offer_label(offer)}? This spends money on your vast.ai account.",
            })
            return self.state()
        key = self.studio.services.token("vast")

        def work() -> Any:
            return vast.rent_offer(key, offer, image=image)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                ctx.dialog("Salad Studio", str(result), level="error")
                return
            if isinstance(result, dict) and isinstance(result.get("row"), dict):
                row = result["row"]
                doc, _refusal = vast.add_instance(
                    vast.load_doc(), str(row.get("endpoint") or ""),
                    label=result.get("label") or f"vast-{result.get('contract')}",
                    image=result.get("image") or "")
                row_key = vast.row_key(vast.clean_row(row) or row)
                if row_key:
                    doc = vast.set_active(doc, row_key)
                vast.save_doc(doc)
            message = str(result.get("message") or "") if isinstance(result, dict) else ""
            ctx.note(message or f"Rented the offer {vast.offer_label(offer)}", level="ok")

        ctx.background(work, done)
        ctx.note("Renting the offer…")
        return self.state()

    def replace_destroyed(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        criteria = self._criteria(payload)
        row = self._selected_row() or {}
        image = str(row.get("image") or "")
        if not image:
            entry = image_deploy.entry_by_ref(_image_entries(image_deploy.load_settings()), self._image_ref(payload))
            image = str((entry or {}).get("tag") or "")
        key = self.studio.services.token("vast")

        def work() -> Any:
            return vast.replace_destroyed(key=key, endpoint=str(row.get("endpoint") or ""),
                                          instance_id=row.get("id"), image=image, settings=criteria)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                ctx.dialog("Salad Studio", str(result), level="error")
                return
            ctx.note(f"Replace: {result.get('message') or result.get('action')}", level="ok")

        ctx.background(work, done)
        ctx.note("Replacing the instance…")
        return self.state()


def _serving_names(studio: Any, stored: profiles.SaladProfile | None) -> str:
    """A one-line warning when the profile lists checkpoints of different families."""
    if stored is None:
        return ""
    return profiles.mixed_family_reason(stored, studio_meta.default())
