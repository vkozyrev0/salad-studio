"""Prompt Settings: the knobs a request carries, and the LoRAs it selects.

The knobs are typed text held in the window's form until a save turns them
into a profile through :meth:`Form.profile`, which refuses a bad one by name.
The LoRAs are the ones compatible with the chosen graph, each with whether the
form has it selected.
"""
from __future__ import annotations

from typing import Any

import lora_store
import profiles
import request_json

KNOBS: tuple[str, ...] = ("width", "height", "steps", "cfg", "seed")
SCHEDULER_LABELS: tuple[tuple[str, str], ...] = (("flux2", "Flux2 (Klein)"), ("simple", "Simple (Civitai)"))
_FIELD_OF: dict[str, str] = {"width": "width", "height": "height", "steps": "steps",
                             "cfg": "cfg", "seed": "seed"}


def _field_named(exc: ValueError) -> str | None:
    return _FIELD_OF.get(str(exc).split(" ", 1)[0].strip().lower())


def _scheduler_id(raw: str | None) -> str:
    return "simple" if "simple" in str(raw or "").lower() else "flux2"


def _choice(item: dict[str, Any], selected: bool) -> dict[str, Any]:
    """One LoRA as the page draws it: a name, a model family, a version.

    The family already sits beside every name, so the version drops it when its
    own text opens with it; the cell then says what the name and the family do
    not. A row imported with no name of its own shows its Civitai version id,
    not the label that would repeat it.
    """
    name = str(item.get("name") or "")
    if not name:
        source = item.get("source") or {}
        name = str(source.get("version_id") or item.get("id") or "")
    family = lora_store.family_label(item)
    version = lora_store.version_label(item)
    if version.lower().startswith(family.lower()):
        version = ""
    return {"id": str(item.get("id")), "name": name, "family": family,
            "version": version, "selected": selected}


class SettingsController:
    page = "settings"

    def __init__(self, studio: Any) -> None:
        self.studio = studio

    def register(self, table: Any) -> None:
        table.action("settings.view")(self.view)
        table.action("settings.set_knobs")(self.set_knobs)
        table.action("settings.toggle_lora", need={"id": str, "on": bool})(self.toggle_lora)
        table.action("settings.select_checkpoint")(self.select_checkpoint)
        table.action("settings.save")(self.save)

    def view(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        return self.state()

    def state(self) -> dict[str, Any]:
        form = self.studio.form
        graph = lora_store.graph_id(form.graph)
        selected = set(form.selected_loras)
        rows = [item for item in lora_store.list_loras() if lora_store.compatible_with_graph(item, graph)]
        profile = self.studio.profile
        return {
            "knobs": {name: str(getattr(form, name)) for name in KNOBS},
            "graphs": list(lora_store.GRAPH_CHOICES),
            "graph": lora_store.graph_label(graph),
            # Each choice as the id the select stores and the label it shows,
            # so a reply that does not change the scheduler leaves it alone.
            "schedulers": [{"id": key, "label": label} for key, label in SCHEDULER_LABELS],
            "scheduler": _scheduler_id(form.scheduler),
            "checkpoints": list(request_json.UNET_LABELS),
            "checkpoint": request_json.unet_label(profile.primary_checkpoint),
            "removeBg": form.remove_bg == "on",
            "loras": [_choice(item, str(item.get("id")) in selected) for item in rows],
        }

    # -- actions

    def set_knobs(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        """Write the typed strings into the form. A graph change re-filters the LoRAs."""
        form = self.studio.form
        for name in KNOBS:
            if name in payload:
                setattr(form, name, str(payload[name] or ""))
        if "graph" in payload:
            form.graph = lora_store.graph_id(str(payload.get("graph") or ""))
        if "scheduler" in payload:
            form.scheduler = _scheduler_id(str(payload.get("scheduler") or ""))
        if "remove_bg" in payload:
            form.remove_bg = "on" if payload.get("remove_bg") == "on" else ""
        self.studio.publish()
        return self.state()

    def toggle_lora(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        """Rebuild which LoRAs apply: the id is the one toggled, ``on`` its new value."""
        lora_id = str(payload.get("id") or "")
        item = next((i for i in lora_store.list_loras() if str(i.get("id")) == lora_id), None)
        if item is None:
            ctx.note(f"Refused: there is no LoRA with id {lora_id!r}", level="warn")
            return self.state()
        form = self.studio.form
        chosen = set(form.selected_loras)
        if payload.get("on"):
            chosen.add(lora_id)
        else:
            chosen.discard(lora_id)
        form.selected_loras = sorted(chosen)
        self.studio.publish()
        return self.state()

    def select_checkpoint(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        """The chosen checkpoint leads the profile's list, which is routing order."""
        stored = self.studio.stored_profile()
        unet = request_json.normalize_unet(str(payload.get("checkpoint") or ""))
        if stored is None or not unet or unet not in stored.checkpoints:
            ctx.note(f"Refused: {request_json.unet_label(unet)} is not one of this profile's checkpoints",
                     level="warn")
            return self.state()
        stored.checkpoints = [unet] + [c for c in stored.checkpoints if c != unet]
        profiles.upsert(stored)
        self.studio.profile = stored
        self.studio.publish()
        ctx.note(f"Checkpoint {unet} leads the profile's list", level="ok")
        return self.state()

    def save(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        """Turn the typed knobs into the profile's numeric fields."""
        stored = self.studio.stored_profile()
        if stored is None:
            ctx.note(f"Refused: there is no stored profile named {self.studio.form.name!r}", level="warn")
            return self.state()
        try:
            p = self.studio.form.profile(stored)
        except ValueError as exc:
            field = _field_named(exc)
            ctx.note(f"Refused: {exc}", level="error")
            if field is not None:
                ctx.effects.append({"kind": "dialog", "title": "Salad Studio",
                                    "body": f"Invalid knob: {exc}", "level": "error", "field": field})
            return self.state()
        profiles.upsert(p)
        self.studio.profile = p
        self.studio.publish()
        ctx.note(f"Saved the knobs to profile {p.name}", level="ok")
        return self.state()
