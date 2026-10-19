"""Prompt Editor: the request JSON, the graph beside it, and the two prompt boxes.

Domain state lives in the text of the controls and in the graph model; the
rules come from ``editor_logic`` and ``graph_model``. The page wires them
together and never holds a second copy of a prompt.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import flet as ft

from salad_studio import editor_logic, flet_theme, graph_canvas, graph_model as gm, request_json
from salad_studio.flet_pump import refresh
from salad_studio.flet_shell import Page


class EditorPage(Page):
    def __init__(self, host: Any, *, dark: bool = True) -> None:
        colors = flet_theme.canvas_colors(dark)
        super().__init__("Prompt Editor",
                         "The JSON body POSTed to the target's /prompt. The graph is drawn from it.",
                         colors)
        self.host = host
        self.win = host
        self.model = gm.GraphModel()
        self.graph = graph_canvas.GraphView(dark=dark, on_swap=self.on_swap)
        self.graph.bind(self._on_graph_change)
        self.json = ft.TextField(
            value=editor_logic.dump(editor_logic.empty_payload()),
            multiline=True,
            min_lines=12,
            expand=True,
            text_style=flet_theme._typography(flet_theme.DARK if dark else flet_theme.LIGHT)["mono"],
            border_radius=flet_theme.CONTROL_RADIUS,
            on_change=self.on_json_changed,
        )
        self.positive = ft.TextField(
            value=editor_logic.DEFAULT_POSITIVE.strip(),
            label="Positive prompt",
            multiline=True,
            min_lines=3,
            max_lines=6,
            text_size=12,
            on_change=lambda _e: self.patch_prompt("pos"),
        )
        self.negative = ft.TextField(
            label="Negative prompt", multiline=True, min_lines=3, max_lines=6, text_size=12,
            on_change=lambda _e: self.patch_prompt("neg"),
        )
        self.status = ft.Text("", size=12, color=colors["muted"])
        swap = ft.Button("Swap selected", on_click=self.on_swap_clicked)
        clear = ft.TextButton("Clear selection", on_click=self.clear_selection)
        bar = ft.Row([ft.Button("Rebuild from Config", on_click=self.rebuild_from_config),
                      ft.Button("Rebuild from JSON", on_click=self.rebuild_from_json),
                      ft.Button("Validate", on_click=self.validate),
                      self.status, ft.Container(expand=True), clear, swap],
                     spacing=flet_theme.GAP["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        # The JSON box and the graph share the pane, the graph taking the larger
        # share; the prompt boxes sit under them at 66/34, as the Tk pane did.
        self.split = ft.Row([ft.Container(self.json, expand=2), ft.Container(self.graph, expand=3)],
                            expand=True, spacing=flet_theme.GAP["sm"],
                            vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.prompts = ft.Row(
            [ft.Container(self.positive, expand=66), ft.Container(self.negative, expand=34)],
            spacing=flet_theme.GAP["sm"])
        self.bar = bar
        self.body.content = ft.Column([self.split, self.prompts, self.bar], expand=True,
                                      spacing=flet_theme.GAP["sm"])

    def note(self, text: str, *, level: str = "info") -> None:
        """An embedded page has no note line of its own: the window shows it in the bar."""
        if hasattr(self, "status"):
            self.status.value = text
            self.status.color = self.colors[level] if level in self.colors else self.colors["muted"]
            refresh(self.status)

    def context(self) -> dict[str, str]:
        """The three texts Prompt Assist sends: both prompts and the request JSON."""
        return {
            "editor_positive": str(self.positive.value or "").strip(),
            "editor_negative": str(self.negative.value or "").strip(),
            "request_json": str(self.json.value or "").strip(),
        }

    def text(self) -> str:
        return str(self.json.value or "")

    def set_positive_only(self, text: str) -> None:
        """History's bare prompts have no JSON: keep the request and replace the positive text."""
        parsed = editor_logic.parse(self.json.value)
        if parsed.ok:
            prompt = editor_logic.patch_text(parsed.prompt, "pos", text)
            self.set_payload(editor_logic.with_prompt(parsed.payload, prompt))
            return
        self.positive.value = text
        self.rebuild_from_config()

    def commit_prompts(self, positive: str, negative: str) -> bool:
        """Prompt Assist's commit: the boxes are the live source the JSON is patched from."""
        self.positive.value = positive
        self.negative.value = negative
        parsed = editor_logic.parse(self.json.value)
        if not parsed.ok:
            self.rebuild_from_config()
            refresh(self.positive, self.negative, self.json)
            return False
        prompt = editor_logic.patch_text(parsed.prompt, "pos", positive)
        prompt = editor_logic.patch_text(prompt, "neg", negative)
        self.set_payload(editor_logic.with_prompt(parsed.payload, prompt))
        return True

    def rebuild_from_config(self, _e: ft.ControlEvent | None = None) -> None:
        """Rebuild the request from the window's form: graph, knobs and the checked LoRAs."""
        form = self.win.form
        try:
            profile = form.profile(self.win.stored_profile())
        except ValueError as exc:
            self.host.note(f"Refused: {exc}", level="error")
            return
        payload = request_json_build(
            str(self.positive.value or "").strip(),
            negative=str(self.negative.value or "").strip(),
            profile=profile,
        )
        self.set_payload(payload)
        self.host.note("Rebuilt the request from Prompt Settings", level="ok")

    # -- JSON to graph

    def on_json_changed(self, _e: ft.ControlEvent | None = None) -> None:
        self.sync()

    def sync(self) -> None:
        """Read the editor text and bring the graph and the boxes up to date."""
        parsed = editor_logic.parse(self.json.value)
        if not parsed.ok:
            self.status.value = parsed.error
            self.status.color = self.colors["error"]
            refresh(self.status)
            return
        if set(parsed.prompt) != {n.id for n in self.model.nodes}:
            self.model = gm.relayout(self.model, parsed.prompt)
            self.graph.set_model(self.model)
            self.graph.repaint()
            self.graph.fit()
        else:
            self.model = self._move_prompts(self.model, parsed.prompt)
            self.graph.set_model(self.model, edges=False, nodes=True)
            self.graph.repaint()
        pos, neg = editor_logic.prompt_texts(parsed.prompt)
        if self.positive.value != pos:
            self.positive.value = pos
        if self.negative.value != neg:
            self.negative.value = neg
        self.status.value = "JSON valid"
        self.status.color = self.colors["ok"]
        refresh(self.positive, self.negative, self.status)

    def _move_prompts(self, model: gm.GraphModel, prompt: dict[str, Any]) -> gm.GraphModel:
        """The same nodes with the text each text-encode card shows, so typing keeps the view."""
        nodes = []
        for node in model.nodes:
            text = gm.clip_note(prompt.get(node.id) or {})
            nodes.append(node if text == node.note else replace(node, note=text))
        if all(new is old for new, old in zip(nodes, model.nodes)):
            return model
        return replace(model, nodes=tuple(nodes))

    # -- prompt boxes

    def patch_prompt(self, which: str) -> None:
        parsed = editor_logic.parse(self.json.value)
        if not parsed.ok:
            return
        box = self.positive if which == "pos" else self.negative
        patched = editor_logic.patch_text(parsed.prompt, which, box.value)
        if patched is parsed.prompt:
            return
        self.set_payload(editor_logic.with_prompt(parsed.payload, patched), relayout=False)

    def set_payload(self, payload: dict[str, Any], *, relayout: bool = True) -> None:
        text = editor_logic.dump(payload)
        self.json.value = text
        pos, neg = editor_logic.prompt_texts(payload["prompt"])
        self.positive.value = pos
        self.negative.value = neg
        refresh(self.json, self.positive, self.negative)
        if relayout:
            self.model = gm.relayout(self.model, payload["prompt"])
            self.graph.set_model(self.model)
            self.graph.repaint()
            self.graph.fit()

    def rebuild_from_json(self, _e: ft.ControlEvent | None = None) -> None:
        parsed = editor_logic.parse(self.json.value)
        if not parsed.ok:
            self.host.note(parsed.error, level="error")
            return
        self.set_payload(editor_logic.with_prompt(parsed.payload, parsed.prompt))
        self.host.note("Rebuilt the graph from the editor JSON")

    def validate(self, _e: ft.ControlEvent | None = None) -> None:
        ok, message = editor_logic.validate(self.json.value)
        self.status.value = message
        self.status.color = self.colors["ok"] if ok else self.colors["error"]
        refresh(self.status)
        self.host.note(message, level="ok" if ok else "error")

    # -- graph

    def _on_graph_change(self, model: gm.GraphModel, drag: bool = False) -> None:
        self.model = model
        self.graph.repaint()

    def clear_selection(self, _e: ft.ControlEvent | None = None) -> None:
        self.model = self.model.with_selection(())
        self.graph.set_model(self.model)
        self.graph.repaint()

    def on_swap_clicked(self, _e: ft.ControlEvent | None = None) -> None:
        self.on_swap(self.model)

    def on_swap(self, model: gm.GraphModel) -> None:
        """Swap two same-type cards' settings and write the result back to the text."""
        if len(model.selected) != 2:
            self.host.note("Select two nodes first.", level="warn")
            return
        parsed = editor_logic.parse(self.json.value)
        if not parsed.ok:
            self.host.note(parsed.error, level="error")
            return
        try:
            swapped = editor_logic.swap_text(parsed.prompt, *model.selected)
        except ValueError as exc:
            self.host.note(str(exc), level="warn")
            return
        self.set_payload(editor_logic.with_prompt(parsed.payload, swapped))
        self.model = model.with_selection(())
        self.graph.set_model(self.model)
        self.graph.repaint()
        self.host.note(f"Swapped {model.selected[0]} and {model.selected[1]}", level="ok")




def request_json_build(text: str, *, negative: str = "", profile: Any = None) -> dict[str, Any]:
    """A request body from a prompt and the form's knobs, as Generate would POST it."""
    from salad_studio import profiles

    p = profile or profiles.SaladProfile(name="klein")
    body = request_json.build_request(
        prompt_text=text,
        negative_text=negative,
        graph=p.graph,
        width=int(p.width),
        height=int(p.height),
        steps=int(p.steps),
        seed=int(p.seed),
        cfg=p.cfg,
        selected_ids=list(p.selected_loras) if p.use_loras else [],
    )
    return body
