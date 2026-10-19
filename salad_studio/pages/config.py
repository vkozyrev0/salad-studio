"""Config: the profile, its images, its Salad group policy and its vast.ai hosts.

Four sections in the order a deployment runs them, switched by a segmented
button; each scrolls alone. The page reads the window's form for what is shown
and the stores for what is saved, which is the rule the Tk page followed: the
profile store is the authority for a saved profile.
"""
from __future__ import annotations

from typing import Any

import flet as ft

import studio_meta  # noqa: E402  top-level, as image_deploy and profiles import it
from salad_studio import flet_theme, flet_widgets as w, image_deploy
from salad_studio.flet_pump import refresh
from salad_studio.flet_shell import Page

SECTIONS: tuple[tuple[str, str], ...] = (
    ("profile", "Profile"),
    ("images", "Images"),
    ("policy", "Salad group"),
    ("vast", "Vast.ai"),
)
MODE_SEGMENTS: tuple[tuple[str, str], ...] = (("salad", "Salad gateway"), ("vast", "Vast.ai instance"))
LABELS: dict[str, str] = {"gateway": "Gateway URL", "instance": "Instance URL"}
PROBE_KEYS: tuple[str, ...] = ("path", "port", "initial_delay_seconds", "period_seconds",
                               "timeout_seconds", "success_threshold", "failure_threshold")


def _document() -> dict[str, Any]:
    """The metadata document as it is on disk now: an edited document shows without a restart."""
    return studio_meta.load()


def _image_entries(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Every image this page can deploy."""
    return image_deploy.entries(_document(), settings)


class ConfigPage(Page):
    def __init__(self, host: Any) -> None:
        super().__init__("Config", "Profiles, images and the two hostings.", host.colors)
        self.host = host
        self.win = host
        self.section = "profile"
        self.tabs = ft.SegmentedButton(
            segments=[ft.Segment(value=key, label=ft.Text(label)) for key, label in SECTIONS],
            selected=[self.section],
            allow_empty_selection=False,
            on_change=self._on_section,
        )
        self.panel = ft.Container(expand=True)
        self.body.content = ft.Column([self.tabs, self.panel], expand=True, spacing=flet_theme.GAP["sm"])
        self._build_profile()
        self._build_images()
        self._build_policy()
        self._build_vast()
        self.show_section()

    def _on_section(self, e: Any) -> None:
        self.section = next(iter(e.control.selected), self.section)
        self.show_section()

    def show_section(self) -> None:
        self.panel.content = {
            "profile": self.profile_section,
            "images": self.images_section,
            "policy": self.policy_section,
            "vast": self.vast_section,
        }[self.section]
        refresh(self.panel)

    # -- Profile

    def _build_profile(self) -> None:
        from salad_studio import profiles

        form = self.win.form
        self.name = w.field(form.name, label_text="Profile name", width=220)
        self.profile_list = w.combo(sorted(profiles.load_all()), value=form.name,
                                    label_text="Active profile", width=220,
                                    on_change=lambda e: self.load_profile(str(e.control.value or "")))
        self.target = ft.SegmentedButton(
            segments=[ft.Segment(value=key, label=ft.Text(label)) for key, label in MODE_SEGMENTS],
            selected=[form.mode if form.mode in ("salad", "vast") else "salad"],
            allow_empty_selection=False,
            on_change=self._on_mode,
        )
        self.url = w.field(form.gateway, label_text="Gateway URL", width=420)
        self.checkpoint = w.field("", label_text="Checkpoint filename or label", width=420,
                                  on_submit=lambda _e: self.add_checkpoint())
        self.checkpoint_list = ft.Column([], spacing=2, tight=True)
        self.profile_section = ft.Column(
            [
                w.heading("Profiles", self.colors), w.row([self.profile_list, self.name]),
                w.row([w.button("Add profile", self.add_profile),
                       w.button("Save profile", self.save_profile),
                       w.button("Delete profile", self.delete_profile)]),
                w.heading("Target", self.colors), self.target,
                w.row([self.url, w.button("Use the selected instance", self.use_selected_instance)]),
                w.heading("Checkpoints this profile serves", self.colors),
                w.row([self.checkpoint, w.button("Add", self.add_checkpoint),
                       w.button("Remove selected", self.remove_checkpoint)]),
                self.checkpoint_list,
            ],
            spacing=flet_theme.GAP["sm"], scroll=ft.ScrollMode.ALWAYS, expand=True,
        )
        self._fill_checkpoints()

    def _fill_checkpoints(self) -> None:
        names = list(self.win.profile.checkpoints or [])
        self.checkpoint_list.controls = [
            ft.Text(f"• {name}", size=12, selectable=True) for name in names
        ] or [ft.Text("(none)", size=12, color=self.colors["muted"])]

    def show_profile(self) -> None:
        """Draw the window's form after a profile is loaded from here or elsewhere."""
        from salad_studio import profiles

        form = self.win.form
        self.profile_list.options = [ft.DropdownOption(text=n, key=n) for n in sorted(profiles.load_all())]
        self.profile_list.value = form.name
        self.name.value = form.name
        self.url.value = form.gateway
        self.url.label = LABELS["instance" if form.mode == "vast" else "gateway"]
        self.target.selected = [form.mode if form.mode in ("salad", "vast") else "salad"]
        self._fill_checkpoints()
        refresh(self.name, self.url, self.profile_list, self.target, self.checkpoint_list)

    def _on_mode(self, e: Any) -> None:
        mode = next(iter(e.control.selected), "salad")
        self.win.form.mode = mode
        self.url.label = LABELS["instance" if mode == "vast" else "gateway"]
        refresh(self.url)

    def _read_form(self) -> None:
        self.win.form.name = str(self.name.value or "klein").strip() or "klein"
        self.win.form.gateway = str(self.url.value or "").strip()

    def load_profile(self, name: str) -> None:
        from salad_studio import profiles

        stored = profiles.load_all().get(name)
        if stored is None:
            return
        profiles.set_active(name)
        self.win.apply_profile(stored)
        self.show_profile()
        self.show_policy(stored.policy)
        self.host.note(f"Loaded profile {name}", level="info")

    def add_profile(self, _e: Any = None) -> None:
        from salad_studio import profiles

        self._read_form()
        name = self.win.form.name
        if name in profiles.load_all():
            self.host.note(f"Refused: there is already a profile named {name!r}", level="warn")
            return
        p = profiles.default_profile(name)
        if self.win.form.gateway:
            p.gateway = self.win.form.gateway
        profiles.upsert(p)
        profiles.set_active(p.name)
        self.win.apply_profile(p)
        self.show_profile()
        self.show_policy(p.policy)
        self.host.note(f"Added profile {p.name}", level="ok")

    def save_profile(self, _e: Any = None) -> None:
        from salad_studio import profiles

        self._read_form()
        try:
            p = self.win.form.profile(self.win.stored_profile())
        except ValueError as exc:
            self.host.dialog("Salad Studio", f"Invalid size/steps: {exc}", level="error")
            self.host.note(f"Refused: {exc}", level="error")
            return
        profiles.upsert(p)
        profiles.set_active(p.name)
        self.win.apply_profile(p)
        self.show_profile()
        self.show_policy(p.policy)
        self.host.note(f"Saved profile {p.name}", level="ok")

    def delete_profile(self, _e: Any = None) -> None:
        from salad_studio import profiles

        self._read_form()
        name = self.win.form.name
        if name not in profiles.load_all():
            self.host.note(f"Refused: there is no profile named {name!r}", level="warn")
            return

        def go() -> None:
            left = profiles.delete(name)
            if not left:
                p = profiles.default_profile("klein")
                profiles.upsert(p)
                profiles.set_active(p.name)
                self.host.note(f"Deleted {name}; recreated the default profile", level="ok")
                self.win.apply_profile(p)
            else:
                active = profiles.get_active()
                active = active if active in left else sorted(left)[0]
                profiles.set_active(active)
                self.win.apply_profile(left[active])
                self.host.note(f"Deleted {name}", level="ok")
            self.show_profile()
            self.show_policy(self.win.profile.policy)

        self.host.ask("Salad Studio",
                      f"Delete profile {name!r}? The last profile is recreated as a default. "
                      "This cannot be undone.", go)

    def use_selected_instance(self, _e: Any = None) -> None:
        from salad_studio import vast

        row = vast.active_row(vast.load_doc())
        if row is None:
            self.host.note("Refused: No vast.ai instance is selected.", level="warn")
            return
        endpoint = str(row.get("endpoint") or "")
        if not endpoint:
            self.host.note("Refused: The selected vast.ai instance has no endpoint yet.", level="warn")
            return
        self.url.value = endpoint
        self.win.form.gateway = endpoint
        refresh(self.url)
        self.host.note(f"Using {endpoint}", level="info")

    def add_checkpoint(self, _e: Any = None) -> None:
        from salad_studio import profiles

        text = str(self.checkpoint.value or "").strip()
        if not text:
            self.host.note("Type a checkpoint filename or pick a label first", level="warn")
            return
        stored = self.win.stored_profile()
        if stored is None:
            self.host.note("Refused: Save the profile before editing its checkpoints", level="warn")
            return
        profiles.add_checkpoint(stored, text)
        profiles.upsert(stored)
        self.win.apply_profile(stored)
        self.checkpoint.value = ""
        self.host.note(f"Added checkpoint {text}", level="ok")

    def remove_checkpoint(self, _e: Any = None) -> None:
        from salad_studio import profiles

        stored = self.win.stored_profile()
        names = list(stored.checkpoints) if stored is not None else []
        if not names:
            self.host.note("Refused: The profile lists no checkpoints", level="warn")
            return
        last = names[-1]
        profiles.remove_checkpoint(stored, last)
        profiles.upsert(stored)
        self.win.apply_profile(stored)
        self.host.note(f"Removed checkpoint {last}", level="ok")

    # -- Images

    def _build_images(self) -> None:
        from salad_studio import image_deploy

        settings = image_deploy.load_settings()
        tags = image_deploy.tag_options(_document(), settings)
        self.image = w.combo(tags, value=tags[0] if tags else "", label_text="Image", width=380,
                             on_change=lambda _e: self._show_environment())
        self.show_tokens = w.check("show token values", False, on_change=lambda _e: self._show_environment())
        self.env_name = w.field("", label_text="NAME", width=220)
        self.env_value = w.field("", label_text="value", width=320, password=True, can_reveal=True)
        self.env_list = ft.Column([], spacing=2, tight=True)
        self.commands = ft.TextField(multiline=True, min_lines=7, max_lines=16, read_only=True,
                                     expand=True, text_size=12,
                                     text_style=ft.TextStyle(font_family="Consolas", size=12))
        self.own_image = ft.ExpansionTile(
            title=ft.Text("Your own image", size=12),
            controls=[
                w.row([w.field("", label_text="Name", width=160), w.field("", label_text="Tag", width=280)]),
                w.row([w.field("", label_text="Build arg", width=300),
                       w.field("", label_text="Context", width=200)]),
            ],
        )
        self.images_section = ft.Column(
            [
                w.heading("Container images", self.colors),
                w.row([self.image, self.show_tokens]),
                w.heading("Environment", self.colors), self.env_list,
                w.row([self.env_name, self.env_value, w.button("Add env", self.add_env),
                       w.button("Remove selected", self.remove_env),
                       w.button("Save environment", self.save_env)]),
                w.heading("Deploy", self.colors), self.commands,
                w.row([w.button("Copy commands", self.copy_commands)]), self.own_image,
            ],
            spacing=flet_theme.GAP["sm"], scroll=ft.ScrollMode.ALWAYS, expand=True,
        )
        self._show_environment()

    def _pick(self) -> str:
        """The image the box names, or the first one it offers: a box with no
        choice shows its first option, and the environment belongs to that one.
        A stored image's name stands for it: ``add_env`` files rows under the key."""
        from salad_studio import image_deploy

        clean = lambda tag: (image_deploy.entry_by_ref(_image_entries(image_deploy.load_settings()), tag)
                             or {}).get("key", "")
        if self.image.value and clean(str(self.image.value)):
            return str(self.image.value)
        first = (image_deploy.tag_options(_document(), image_deploy.load_settings()) or [""])[0]
        return first or str(self.image.value or "")

    def _show_environment(self) -> None:
        from salad_studio import image_deploy

        settings = image_deploy.load_settings()
        entry = image_deploy.entry_by_ref(_image_entries(settings), self._pick())
        include = bool(self.show_tokens.value)
        rows = image_deploy.env_rows(entry, image_deploy.extra_env(settings, entry["key"]),
                                     self._token_map()) if entry else []
        self.env_list.controls = [
            ft.Text(f"{row.get('name')}={image_deploy.shown_value(row, include_values=include)}",
                    size=12, font_family="Consolas", selectable=True)
            for row in rows
        ] or [ft.Text("(no entries)", size=12, color=self.colors["muted"])]
        self.commands.value = (image_deploy.deploy_script(
            entry, image_deploy.extra_env(settings, entry["key"]), include_values=include)
            if entry else "(no image selected)")
        refresh(self.env_list, self.commands)

    def _token_map(self) -> dict[str, str]:
        from salad_studio import tokens

        out: dict[str, str] = {}
        for kind, _label, _rel in tokens.TOKEN_SPECS:
            try:
                out[kind] = getattr(self.win.services, "token", tokens.read_token)(kind)
            except (OSError, AttributeError, TypeError):
                out[kind] = ""
        return out

    def add_env(self, _e: Any = None) -> None:
        from salad_studio import image_deploy

        name = str(self.env_name.value or "").strip()
        if not name:
            self.host.note("Refused: Name the environment variable first", level="warn")
            return
        settings = image_deploy.load_settings()
        ref = (image_deploy.entry_by_ref(_image_entries(settings), self._pick()) or {}).get("key", "")
        settings, refusal = image_deploy.add_env(settings, ref, name,
                                                 str(self.env_value.value or ""))
        if refusal:
            self.host.note(f"Refused: {refusal}", level="warn")
            return
        image_deploy.save_settings(settings)
        self.env_name.value = ""
        self.env_value.value = ""
        self._show_environment()
        self.host.note(f"Added {name}", level="ok")

    def remove_env(self, _e: Any = None) -> None:
        from salad_studio import image_deploy

        name = str(self.env_name.value or "").strip()
        if not name:
            self.host.note("Refused: type the NAME of the extra to remove", level="warn")
            return
        settings = image_deploy.load_settings()
        ref = (image_deploy.entry_by_ref(_image_entries(settings), self._pick()) or {}).get("key", "")
        settings, removed = image_deploy.remove_env(settings, ref, name)
        image_deploy.save_settings(settings)
        self._show_environment()
        self.host.note(f"Removed {name}" if removed else f"Refused: {name} is documented, not an extra",
                       level="ok" if removed else "warn")

    def save_env(self, _e: Any = None) -> None:
        from salad_studio import image_deploy

        image_deploy.save_settings(image_deploy.load_settings())
        self._show_environment()
        self.host.note("Saved the environment", level="ok")

    def copy_commands(self, _e: Any = None) -> None:
        try:
            self.host.page.set_clipboard(str(self.commands.value or ""))
        except (AttributeError, RuntimeError):
            self.host.note("Refused: the clipboard is not available", level="warn")
            return
        self.host.note("Copied the commands", level="ok")

    # -- Salad group

    def _build_policy(self) -> None:
        self.policy_group = ft.Text("", size=12, color=self.colors["muted"])
        self.policy_image = w.field("", label_text="Image", width=420)
        self.policy_us = w.check("US-only")
        self.gpu_boxes: dict[str, ft.Checkbox] = {}
        self.gpu_list = ft.Column([], spacing=0, tight=True)
        self.probe: dict[str, dict[str, ft.TextField]] = {"startup": {}, "readiness": {}}
        rows: list[ft.Control] = []
        for kind in ("startup", "readiness"):
            for key in PROBE_KEYS:
                self.probe[kind][key] = w.field("", label_text=key, width=150)
            rows.append(w.row([ft.Container(ft.Text(kind.title(), size=12), width=80),
                               *self.probe[kind].values()]))
        self.policy_section = ft.Column(
            [
                w.heading("Salad group for this profile", self.colors), self.policy_group,
                w.row([self.policy_image, self.policy_us]), self.gpu_list, *rows,
                w.row([w.button("Load from Salad", self.load_policy),
                       w.button("Apply to Salad", self.apply_policy),
                       w.button("Reallocate instance", self.reallocate)]),
            ],
            spacing=flet_theme.GAP["sm"], scroll=ft.ScrollMode.ALWAYS, expand=True,
        )
        self._policy: dict[str, Any] = {}
        self.show_policy(self.win.profile.policy)

    def show_policy(self, policy: dict[str, Any]) -> None:
        self._policy = dict(policy or {})
        self.policy_group.value = (f"{policy.get('group_name')}  v{policy.get('version') or '?'}"
                                   if policy.get("group_name") else "")
        self.policy_image.value = str(policy.get("image") or "")
        self.policy_us.value = "us" in [str(c).lower() for c in (policy.get("country_codes") or [])]
        selected = {str(x) for x in (policy.get("gpu_classes") or [])}
        for gid, box in self.gpu_boxes.items():
            box.value = gid in selected
        for kind in ("startup", "readiness"):
            src = policy.get(kind) or {}
            for key, field in self.probe[kind].items():
                field.value = str(src.get(key, ""))
        refresh(self.policy_group, self.policy_image, self.policy_us, self.gpu_list,
                *(f for kind in self.probe.values() for f in kind.values()))

    def _fill_gpus(self, classes: list[dict[str, Any]], keep: list[str]) -> None:
        wanted = {str(c.get("id")): str(c.get("name") or c.get("id")) for c in classes}
        for gid in keep:
            wanted.setdefault(gid, gid)
        self.gpu_boxes = {gid: w.check(name, gid in keep) for gid, name in sorted(wanted.items())}
        self.gpu_list.controls = list(self.gpu_boxes.values()) or [
            ft.Text("(press Load from Salad for the classes)", size=12, color=self.colors["muted"])]

    def policy_from_fields(self) -> dict[str, Any]:
        return {
            "image": str(self.policy_image.value or "").strip(),
            "country_codes": ["us"] if self.policy_us.value else [],
            "gpu_classes": [gid for gid, box in self.gpu_boxes.items() if box.value],
            "startup": {k: str(f.value or "") for k, f in self.probe["startup"].items()},
            "readiness": {k: str(f.value or "") for k, f in self.probe["readiness"].items()},
            "group_name": self._policy.get("group_name", ""),
            "version": self._policy.get("version"),
        }

    def _gateway(self) -> str:
        return (self.win.form.gateway or self.win.profile.gateway).strip()

    def load_policy(self, _e: Any = None) -> None:
        from salad_studio import salad_status

        gateway = self._gateway()
        if not gateway:
            self.host.dialog("Salad Studio", "Refused: the gateway URL is empty", level="error")
            return
        keep = [str(x) for x in (self.win.profile.policy.get("gpu_classes") or [])]

        def work() -> Any:
            classes = salad_status.list_gpu_classes(self.win.services.salad_key())
            policy, error = salad_status.load_policy(gateway, self.win.services.salad_key())
            return classes, policy, error

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self.host.dialog("Salad Studio", str(result), level="error")
                return
            classes, policy, error = result
            if error or policy is None:
                self.host.dialog("Salad Studio", error or "No policy came back.", level="error")
                return
            self._fill_gpus(list(classes or []), keep)
            self.show_policy(policy)
            self.host.note("Loaded the group's policy", level="ok")

        self.win.services.background(work, done)

    def apply_policy(self, _e: Any = None) -> None:
        from salad_studio import salad_status

        gateway = self._gateway()
        if not gateway:
            self.host.dialog("Salad Studio", "Refused: the gateway URL is empty", level="error")
            return
        policy = self.policy_from_fields()

        def work() -> Any:
            return salad_status.apply_policy(gateway, self.win.services.salad_key(), policy)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self.host.dialog("Salad Studio", str(result), level="error")
                return
            status, payload = result
            if int(status) != 200:
                self.host.dialog("Salad Studio", f"Salad refused the policy: {payload}", level="error")
                return
            self.host.note("Applied the policy to the Salad group", level="ok")

        self.win.services.background(work, done)

    def reallocate(self, _e: Any = None) -> None:
        from salad_studio import salad_status

        gateway = self._gateway()

        def go() -> None:
            def work() -> Any:
                return salad_status.reallocate_instance(gateway, self.win.services.salad_key())

            def done(result: Any) -> None:
                if isinstance(result, Exception):
                    self.host.dialog("Salad Studio", str(result), level="error")
                    return
                status, payload = result
                ok = int(status) in (200, 201, 204)
                self.host.note("Reallocated the instance" if ok else f"Salad refused: {payload}",
                               level="ok" if ok else "error")

            self.win.services.background(work, done)

        self.host.ask("Salad Studio",
                      "Reallocate the container instance now? Live renders on it are lost.", go)

    # -- Vast.ai

    def _build_vast(self) -> None:
        from salad_studio import vast

        self.vast_doc: dict[str, Any] = {}
        self.vast_rows: list[dict[str, Any]] = []
        self.offer_rows: list[dict[str, Any]] = []
        self._vast_index: int | None = None
        self.vast_endpoint = w.field("", label_text="Instance URL or id", width=420)
        self.vast_table_holder = ft.Column([], spacing=4, tight=True)
        self.offers_holder = ft.Column([], spacing=4, tight=True)
        self.vast_gpus = w.field(", ".join(vast.DEFAULT_GPU_NAMES), label_text="GPU models", width=300)
        self.vast_section = ft.Column(
            [
                w.heading("vast.ai instances", self.colors), self.vast_table_holder,
                w.row([self.vast_endpoint, w.button("Add instance", self.add_vast),
                       w.button("Fetch instances", self.fetch_vast),
                       w.button("Set image", self.set_vast_image),
                       w.button("New profile for instance", self.make_profile_for_vast),
                       w.button("Remove", self.remove_vast),
                       w.button("Save list", self.save_vast)]),
                w.heading("Rent a machine", self.colors),
                w.row([self.vast_gpus, w.button("Find offers", self.search_offers),
                       w.button("Create instance", self.rent_offer),
                       w.button("Replace if destroyed", self.replace_destroyed)]),
                ft.Text(f"Floors: max ${vast.REPLACE_DEFAULTS['max_price']:.2f}/hr, "
                        f"{vast.REPLACE_DEFAULTS['min_down_mbps']} down / "
                        f"{vast.REPLACE_DEFAULTS['min_up_mbps']} up Mbps, "
                        f"CUDA {vast.REPLACE_DEFAULTS['cuda_min']}, reliability "
                        f"{vast.REPLACE_DEFAULTS['min_reliability']}",
                        size=12, color=self.colors["muted"]),
                self.offers_holder,
            ],
            spacing=flet_theme.GAP["sm"], scroll=ft.ScrollMode.ALWAYS, expand=True,
        )
        self.show_vast()

    def show_vast(self) -> None:
        from salad_studio import vast

        self.vast_doc = vast.load_doc()
        self.vast_rows = [r for r in (vast.clean_row(x) for x in (self.vast_doc.get("instances") or [])) if r]
        active = str(self.vast_doc.get("active") or "")
        cells = [[str(vast.row_key(r)), vast.row_label(r), str(r.get("endpoint") or ""),
                  str(r.get("image") or ""), str(r.get("state") or ""), str(r.get("gpu_name") or ""),
                  "*" if str(r.get("endpoint") or "") == active else ""] for r in self.vast_rows]
        self.vast_table_holder.controls = [
            w.table(("Use", "Label", "Address", "Image", "State", "GPU", "Active"),
                    cells or [["(no instances)", "", "", "", "", "", ""]], on_row=self.select_vast)]
        offers = list(self.win.services.offers.values()) if self.win.services.offers else []
        self.offer_rows = sorted(offers, key=vast.offer_value)[:40]
        cells = [[vast.offer_cells(o).get(k, "") for k in ("gpu", "price", "perf", "value", "vram", "disk")]
                 for o in self.offer_rows]
        self.offers_holder.controls = [
            w.table(("GPU", "$/hr", "Perf", "Perf/$", "VRAM GB", "Disk GB"),
                    cells or [["(Find offers)", "", "", "", "", ""]], on_row=self.select_offer)]
        refresh(self.vast_table_holder, self.offers_holder)

    def _selected_row(self) -> dict[str, Any] | None:
        index = self._vast_index
        return self.vast_rows[index] if index is not None and 0 <= index < len(self.vast_rows) else None

    def select_vast(self, index: int) -> None:
        from salad_studio import vast

        if not (0 <= index < len(self.vast_rows)):
            return
        row = self.vast_rows[index]
        self.vast_doc = vast.set_active(self.vast_doc, vast.row_key(row))
        vast.save_doc(self.vast_doc)
        self._vast_index = index
        self.show_vast()
        self.host.note(f"Selected {vast.row_label(row)}", level="ok")

    def select_offer(self, index: int) -> None:
        from salad_studio import vast

        if 0 <= index < len(self.offer_rows):
            self.win.services.offers["selected"] = self.offer_rows[index]
            self.host.note(f"Selected {vast.offer_label(self.offer_rows[index])}", level="info")

    def add_vast(self, _e: Any = None) -> None:
        from salad_studio import vast

        endpoint = vast.normalize_endpoint(str(self.vast_endpoint.value or ""))
        if not endpoint:
            self.host.note("Refused: type an instance id or a host:port", level="warn")
            return
        self.vast_doc, refusal = vast.add_instance(self.vast_doc, endpoint)
        if refusal:
            self.host.note(f"Refused: {refusal}", level="warn")
            return
        vast.save_doc(self.vast_doc)
        self.vast_endpoint.value = ""
        self.show_vast()
        self.host.note(f"Added {endpoint}", level="ok")

    def fetch_vast(self, _e: Any = None) -> None:
        from salad_studio import vast

        def work() -> Any:
            return vast.fetch_records(self.win.services.token("vast"))

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self.host.dialog("Salad Studio", str(result), level="error")
                return
            if result.get("error"):
                self.host.dialog("Salad Studio", str(result["error"]), level="error")
                return
            self.vast_doc, summary = vast.reconcile(self.vast_doc, result.get("instances") or [],
                                                    complete=not result.get("truncated"))
            vast.save_doc(self.vast_doc)
            self.show_vast()
            self.host.note(f"Fetched {len(result.get('instances') or [])} instance(s)", level="ok")

        self.win.services.background(work, done)

    def set_vast_image(self, _e: Any = None) -> None:
        from salad_studio import image_deploy, vast

        row = self._selected_row()
        if row is None:
            self.host.note("Refused: select an instance first", level="warn")
            return
        entry = image_deploy.entry_by_ref(_image_entries(image_deploy.load_settings()),
                                          str(self.image.value or ""))
        image = str((entry or {}).get("tag") or "")
        key = vast.row_key(row)
        rows = []
        for existing in self.vast_doc.get("instances") or []:
            clean = vast.clean_row(existing)
            rows.append({**clean, "image": image} if clean and vast.row_key(clean) == key else existing)
        self.vast_doc = {**self.vast_doc, "instances": rows}
        vast.save_doc(self.vast_doc)
        self.show_vast()
        self.host.note(f"Set the image on {vast.row_label(row)}", level="ok")

    def make_profile_for_vast(self, _e: Any = None) -> None:
        from salad_studio import profiles, vast

        row = self._selected_row()
        if row is None:
            self.host.note("Refused: select an instance first", level="warn")
            return
        name = f"vast-{vast.row_key(row)}"
        p = profiles.default_profile(name)
        p.mode = "vast"
        p.gateway = str(row.get("endpoint") or "")
        profiles.upsert(p)
        profiles.set_active(name)
        self.win.apply_profile(p)
        self.show_profile()
        self.show_policy(p.policy)
        self.host.note(f"Created profile {name}", level="ok")

    def remove_vast(self, _e: Any = None) -> None:
        from salad_studio import vast

        row = self._selected_row()
        if row is None:
            self.host.note("Refused: select an instance first", level="warn")
            return

        def go() -> None:
            self.vast_doc, removed = vast.remove_instance(self.vast_doc, vast.row_key(row))
            vast.save_doc(self.vast_doc)
            self._vast_index = None
            self.show_vast()
            self.host.note("Removed the instance" if removed else
                           "Refused: the instance is not in the list",
                           level="ok" if removed else "warn")

        self.host.ask("Salad Studio",
                      f"Remove instance {vast.row_label(row)} from the list? The machine itself is not "
                      "destroyed.", go)

    def save_vast(self, _e: Any = None) -> None:
        from salad_studio import vast

        vast.save_doc(self.vast_doc)
        self.host.note("Saved the instance list", level="ok")

    def _criteria(self) -> dict[str, Any]:
        from salad_studio import vast

        criteria = vast.clean_replace(vast.REPLACE_DEFAULTS)
        names = [n.strip() for n in str(self.vast_gpus.value or "").split(",") if n.strip()]
        if names:
            criteria["gpu_names"] = names
        return criteria

    def search_offers(self, _e: Any = None) -> None:
        from salad_studio import vast

        criteria = self._criteria()

        def work() -> Any:
            return vast.search_offers(self.win.services.token("vast"), criteria)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self.host.dialog("Salad Studio", str(result), level="error")
                return
            if result.get("error"):
                self.host.dialog("Salad Studio", str(result["error"]), level="error")
                return
            offers = vast.matching_offers(list(result.get("offers") or []), criteria)
            self.win.services.offers = {str(o.get("id") or i): o for i, o in enumerate(offers)}
            self.show_vast()
            self.host.note(f"Found {len(offers)} offer(s)", level="ok")

        self.win.services.background(work, done)

    def rent_offer(self, _e: Any = None) -> None:
        from salad_studio import vast

        offer = self.win.services.offers.get("selected")
        if not offer:
            self.host.note("Refused: select an offer first", level="warn")
            return
        image = str(getattr(self.image, "value", "") or "")

        def go() -> None:
            def work() -> Any:
                return vast.rent_offer(self.win.services.token("vast"), offer, image=image,
                                       settings=vast.clean_replace(vast.REPLACE_DEFAULTS))

            def done(result: Any) -> None:
                if isinstance(result, Exception):
                    self.host.dialog("Salad Studio", str(result), level="error")
                    return
                self.vast_doc = vast.load_doc()
                self.show_vast()
                self.host.note(f"Rented the offer {vast.offer_label(offer)}", level="ok")

            self.win.services.background(work, done)

        self.host.ask("Salad Studio",
                      f"Rent {vast.offer_label(offer)}? "
                      "This spends money on your vast.ai account.", go)

    def replace_destroyed(self, _e: Any = None) -> None:
        from salad_studio import vast

        settings = self._criteria()
        row = self._selected_row() or {}
        image = str(row.get("image") or getattr(self.image, "value", "") or "")

        def work() -> Any:
            return vast.replace_destroyed(key=self.win.services.token("vast"),
                                          endpoint=str(row.get("endpoint") or ""),
                                          instance_id=row.get("id"), image=image, settings=settings)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self.host.dialog("Salad Studio", str(result), level="error")
                return
            self.show_vast()
            self.host.note(f"Replace: {result.get('message') or result.get('action')}", level="ok")

        self.win.services.background(work, done)
