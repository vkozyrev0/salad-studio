"""Prompt Settings: the knobs a request carries, and the LoRAs it selects.

Width, height, steps, CFG and seed; the graph, scheduler and checkpoint
choices; and every LoRA as a checkbox. A change writes the window's form and
rebuilds the editor's JSON.

Layout: the body is one Row holding the knobs on the left and the LoRAs on the
right, each group a Column that scrolls alone. A Column body that holds all ten
form controls directly renders blank on flet 1.0.4 (measured); this grouping
paints on every measurement, including the first frame.
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
LORA_HALVES = 2
_WRAP = 1


class SettingsPage(Page):
    def __init__(self, host: Any) -> None:
        super().__init__("Prompt Settings",
                         "The graph, the knobs and the LoRAs the request carries.", host.colors)
        self.host = host
        self.win = host
        form = host.form
        self.width = w.field(form.width, label_text="Width", width=120, on_change=lambda _e: self.sync_form())
        self.height = w.field(form.height, label_text="Height", width=120, on_change=lambda _e: self.sync_form())
        self.steps = w.field(form.steps, label_text="Steps", width=120, on_change=lambda _e: self.sync_form())
        self.cfg = w.field(form.cfg, label_text="CFG", width=120, on_change=lambda _e: self.sync_form())
        self.seed = w.field(form.seed, label_text="Seed", width=160, on_change=lambda _e: self.sync_form())
        self.graph = w.combo(GRAPH_LABELS, value=lora_store.graph_label(form.graph), label_text="Graph",
                             width=220)
        self.scheduler = w.combo(
            SCHEDULER_LABELS,
            value="Simple (Civitai)" if form.scheduler == "simple" else "Flux2 (Klein)",
            label_text="Scheduler", width=220, on_change=lambda _e: self.sync_form())
        self.checkpoint = w.combo(CHECKPOINTS,
                                  value=request_json.unet_label(self.win.profile.primary_checkpoint),
                                  label_text="Checkpoint", width=220)
        self.selected = set(form.selected_loras)
        self.lora_boxes: dict[str, ft.Checkbox] = {}
        self.lora_left = ft.Column([], spacing=flet_theme.GAP["xs"], expand=True)
        self.lora_right = ft.Column([], spacing=flet_theme.GAP["xs"], expand=True)
        self._fill_loras()
        self.knob_row = ft.Row([self.width], spacing=flet_theme.GAP["sm"])
        self.choice_row = ft.Row([self.graph], spacing=flet_theme.GAP["sm"])
        self.lora_row = ft.Row([self.lora_left], spacing=flet_theme.GAP["lg"])

        self.body.content = ft.Column([self.knob_row], expand=True)
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
        half = (len(rows) + LORA_HALVES - 1) // LORA_HALVES
        boxes = list(self.lora_boxes.values())
        self.lora_left.controls = boxes[:half] or [
            ft.Text("No LoRAs for this graph.", size=12, color=self.colors["muted"])]
        self.lora_right.controls = boxes[half:]

    def show_form(self) -> None:
        """Draw the window's form, after a profile is loaded from elsewhere."""
        form = self.win.form
        self.width.value, self.height.value = form.width, form.height
        self.steps.value, self.cfg.value, self.seed.value = form.steps, form.cfg, form.seed
        self.graph.value = lora_store.graph_label(form.graph)
        self.scheduler.value = "Simple (Civitai)" if form.scheduler == "simple" else "Flux2 (Klein)"
        self.selected = set(form.selected_loras)
        self._fill_loras()
        refresh(self.width, self.height, self.steps, self.cfg, self.seed,
                self.graph, self.scheduler, self.lora_left, self.lora_right)

    def on_lora_toggle(self, lora_id: str) -> None:
        box = self.lora_boxes.get(lora_id)
        if box is None:
            return
        if box.value:
            self.selected.add(lora_id)
        else:
            self.selected.discard(lora_id)
        self.sync_form()

    def on_graph(self, e: Any) -> None:
        self.sync_form()
        self._fill_loras()
        refresh(self.lora_left, self.lora_right)

    def sync_form(self) -> None:
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
