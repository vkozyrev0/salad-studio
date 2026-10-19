"""Prompt Settings: the knobs a request carries, and the LoRAs it selects.

Width, height, steps, CFG and seed; the graph, scheduler and checkpoint
choices; and every LoRA as a checkbox. A change writes the window's form and
rebuilds the editor's JSON.

Layout: the body is one Row holding the knobs on the left and the LoRAs on the
right, each group a Column that scrolls alone. A Column body that holds all ten
form controls directly renders blank on flet 1.0.4, so the grouping stays.
"""
from __future__ import annotations

from typing import Any

import flet as ft

from salad_studio import flet_theme, flet_widgets as w, lora_store, request_json
from salad_studio.flet_pump import refresh
from salad_studio.flet_shell import Page

GRAPH_LABELS = lora_store.GRAPH_CHOICES
SCHEDULER_LABELS = ("Flux2 (Klein)", "Simple (Civitai)")
CHECKPOINTS = ("Base 9B", "Distilled 9B", "SNOFS 9B")


class SettingsPage(Page):
    def __init__(self, host: Any) -> None:
        super().__init__("Prompt Settings",
                         "The graph, the knobs and the LoRAs the request carries.", host.colors)
        self.host = host
        self.win = host
        form = host.form
        self.width = w.field(form.width, label_text="Width", width=120, on_change=self.sync_form)
        self.height = w.field(form.height, label_text="Height", width=120, on_change=self.sync_form)
        self.steps = w.field(form.steps, label_text="Steps", width=120, on_change=self.sync_form)
        self.cfg = w.field(form.cfg, label_text="CFG", width=120, on_change=self.sync_form)
        self.seed = w.field(form.seed, label_text="Seed", width=160, on_change=self.sync_form)
        self.graph = w.combo(GRAPH_LABELS, value=lora_store.graph_label(form.graph), label_text="Graph",
                             width=220, on_change=self.on_graph)
        self.scheduler = w.combo(
            SCHEDULER_LABELS,
            value="Simple (Civitai)" if form.scheduler == "simple" else "Flux2 (Klein)",
            label_text="Scheduler", width=220, on_change=self.sync_form)
        self.checkpoint = w.combo(CHECKPOINTS,
                                  value=request_json.unet_label(self.win.profile.primary_checkpoint),
                                  label_text="Checkpoint", width=220, on_change=self.on_checkpoint)
        self.selected = set(form.selected_loras)
        self.lora_boxes: dict[str, ft.Checkbox] = {}
        self.lora_left = ft.Column([], spacing=flet_theme.GAP["xs"])
        self.lora_right = ft.Column([], spacing=flet_theme.GAP["xs"])
        self._fill_loras()
        self.knobs = ft.Column(
            [self.width, self.height, self.steps, self.cfg, self.seed,
             self.graph, self.scheduler, self.checkpoint],
            spacing=flet_theme.GAP["sm"],
            scroll=ft.ScrollMode.ALWAYS,
            expand=True,
        )
        self.loras = ft.Column(
            [w.heading("LoRAs", self.colors),
             ft.Row([self.lora_left, self.lora_right], spacing=flet_theme.GAP["lg"])],
            spacing=flet_theme.GAP["sm"],
            expand=True,
        )
        self.body.content = ft.Row([self.knobs, self.loras], spacing=flet_theme.GAP["lg"],
                                   expand=True,
                                   vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.sync_form()

    def _fill_loras(self) -> None:
        graph = lora_store.graph_id(str(self.graph.value or ""))
        rows = [item for item in lora_store.list_loras() if lora_store.compatible_with_graph(item, graph)]
        self.lora_boxes = {
            str(item.get("id")): w.check(
                lora_store.config_label(item), str(item.get("id")) in self.selected,
                on_change=lambda _e, i=str(item.get("id")): self.on_lora_toggle(i))
            for item in rows
        }
        half = (len(rows) + 1) // 2
        boxes = list(self.lora_boxes.values())
        self.lora_left.controls = boxes[:half] or [
            ft.Text("No LoRAs for this graph.", size=12, color=self.colors["muted"])]
        self.lora_right.controls = boxes[half:]

    def show_form(self, _e: Any = None) -> None:
        """Draw the window's form, after a profile is loaded from elsewhere."""
        form = self.win.form
        self.width.value, self.height.value = form.width, form.height
        self.steps.value, self.cfg.value, self.seed.value = form.steps, form.cfg, form.seed
        self.graph.value = lora_store.graph_label(form.graph)
        self.scheduler.value = "Simple (Civitai)" if form.scheduler == "simple" else "Flux2 (Klein)"
        self.checkpoint.value = request_json.unet_label(self.win.profile.primary_checkpoint)
        self.selected = set(form.selected_loras)
        self._fill_loras()
        refresh(self.width, self.height, self.steps, self.cfg, self.seed,
                self.graph, self.scheduler, self.checkpoint, self.lora_left, self.lora_right)

    def on_lora_toggle(self, lora_id: str, _e: Any = None) -> None:
        box = self.lora_boxes.get(lora_id)
        if box is None:
            return
        if box.value:
            self.selected.add(lora_id)
        else:
            self.selected.discard(lora_id)
        self.sync_form()

    def on_graph(self, e: Any = None) -> None:
        """A new graph changes which LoRAs apply: the list follows it."""
        self.sync_form()
        self._fill_loras()
        refresh(self.lora_left, self.lora_right)

    def on_checkpoint(self, e: Any = None) -> None:
        """The chosen checkpoint leads the profile's list, which is routing order."""
        from salad_studio import profiles

        stored = self.win.stored_profile()
        unet = request_json.normalize_unet(str(self.checkpoint.value or ""))
        if stored is None or not unet or unet not in stored.checkpoints:
            return
        stored.checkpoints = [unet] + [c for c in stored.checkpoints if c != unet]
        profiles.upsert(stored)
        self.win.profile = stored
        self.host.note(f"Checkpoint {unet} leads the profile's list", level="ok")

    def sync_form(self, _e: Any = None) -> None:
        """Write the window's form back from what the controls show."""
        form = self.win.form
        form.width = str(self.width.value or "")
        form.height = str(self.height.value or "")
        form.steps = str(self.steps.value or "")
        form.cfg = str(self.cfg.value or "")
        form.seed = str(self.seed.value or "")
        form.graph = lora_store.graph_id(str(self.graph.value or ""))
        form.scheduler = "simple" if "simple" in str(self.scheduler.value or "").lower() else "flux2"
        form.selected_loras = sorted(self.selected)
        form.use_loras = bool(self.selected)
