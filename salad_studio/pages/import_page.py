"""Import: paste a Comfy workflow or Civitai data, fill the knobs, convert.

The workflow box keeps a large paste in memory and shows a one-line summary, so
a multi-megabyte graph does not crawl the text field. The knobs fill 400 ms after
a keystroke in the generation-data box and never overwrite one the user typed.
"""
from __future__ import annotations

from typing import Any

import flet as ft

from salad_studio import comfy_import, flet_theme, flet_widgets as w, prompt_history, request_json
from salad_studio.flet_pump import refresh
from salad_studio.flet_shell import Page

SCHEDULER_LABELS = ("Flux2 (Klein)", "Simple (Civitai)")
EMPTY_REFUSAL = ("Nothing to fill. Paste a Comfy workflow JSON and/or Civitai generation data "
                 "(prompt + Steps/CFG, or Sampler/Seed/Model).")
NOTHING_TO_CONVERT = ("Nothing to convert. Paste a Comfy workflow JSON and/or Civitai generation "
                      "data (prompt + Steps/CFG, or Sampler/Seed/Model).")
FILL_DELAY_MS = 400


class ImportPage(Page):
    def __init__(self, host: Any) -> None:
        super().__init__("Import", "Paste a Comfy workflow or Civitai data, then convert.", host.colors)
        self.host = host
        self.win = host
        self.stash: str = ""
        self._fill_token: int | None = None
        # Named ``url_field``: ``url`` is the page column's own hyperlink field.
        self.url_field = w.field("", label_text="Civitai image URL", width=560)
        self.meta = w.field("", label_text="Civitai generation data (prompt + Steps / CFG, or Sampler / Seed / Model)",
                             multiline=True, on_change=lambda _e: self._schedule_fill())
        self.workflow = w.field("", label_text="Comfy workflow JSON (a paste is held in memory)",
                                 multiline=True, on_change=lambda _e: self.on_workflow_typed())
        self.knob = {name: w.field("", label_text=label, width=110) for name, label in (
            ("cfg", "CFG"), ("seed", "Seed"), ("steps", "Steps"),
            ("width", "Width"), ("height", "Height"))}
        self.scheduler = w.combo(SCHEDULER_LABELS, value="Flux2 (Klein)", label_text="Scheduler",
                                 width=200, on_change=lambda _e: None)
        self.unet = w.combo(("",) + request_json.UNET_LABELS, value="", label_text="Checkpoint",
                            width=200, on_change=lambda _e: None)
        self.issues = ft.TextField(multiline=True, min_lines=8, max_lines=16, read_only=True,
                                   text_size=12, expand=True,
                                   text_style=ft.TextStyle(font_family="Segoe UI", size=12))
        self.issues_holder = ft.Container(self.issues, expand=True)
        self.body.content = ft.Column(
            [
                w.row([self.url_field, w.button("Fetch from Civitai", self.fetch_civitai, primary=True)]),
                ft.Container(self.meta, height=150),
                ft.Container(self.workflow, expand=True, height=220),
                w.row([*((v) for v in self.knob.values()), self.scheduler, self.unet]),
                w.heading("Salad replica issues", self.colors),
                self.issues_holder,
                w.row([w.button("Fill knobs from paste", lambda _e: self.fill_knobs()),
                       w.button("Convert to Prompt Editor", self.convert, primary=True),
                       w.button("Clear Import", self.clear)]),
            ],
            spacing=flet_theme.GAP["sm"],
            scroll=ft.ScrollMode.ALWAYS,
            expand=True,
        )
        self.set_issues(None)

    # -- paste handling

    def on_workflow_typed(self) -> None:
        text = str(self.workflow.value or "").strip()
        if text.startswith("[Comfy workflow JSON in memory"):
            return
        if len(text) > 20000:
            self.stash = text
            self.workflow.value = (f"[Comfy workflow JSON in memory, {len(text):,} characters]\n"
                                   "Not shown in this box so the UI stays fast. Convert uses this paste.\n"
                                   "Clear Import to drop it.")
            refresh(self.workflow)
            self._schedule_fill()

    def workflow_text(self) -> str:
        if self.stash.strip():
            return self.stash.strip()
        text = str(self.workflow.value or "").strip()
        if text.startswith("[Comfy workflow JSON in memory"):
            return ""
        return text

    def _schedule_fill(self) -> None:
        self.win.pump.cancel(self._fill_token)
        self._fill_token = self.win.pump.call_later(
            FILL_DELAY_MS, lambda: self.fill_knobs(only_empty=True, quiet=True))

    # -- issues

    def set_issues(self, issues: list[str] | None, notes: list[str] | None = None) -> None:
        notes = notes or []
        if issues:
            lines = ["This graph cannot run on the Salad Klein replica:", ""]
            lines.extend(f"• {item}" for item in issues)
            if notes:
                lines.extend(["", *(f"• {item}" for item in notes)])
            self.issues.value = "\n".join(lines)
            self.issues.color = self.colors["error"]
        elif notes:
            self.issues.value = "Warnings:\n\n" + "\n".join(f"• {item}" for item in notes)
            self.issues.color = self.colors["muted"]
        elif issues is None:
            self.issues.value = ""
            self.issues.color = self.colors["muted"]
        else:
            self.issues.value = "No replica issues."
            self.issues.color = self.colors["muted"]
        refresh(self.issues)

    # -- knobs

    def fill_knobs(self, *, only_empty: bool = False, quiet: bool = False,
                   _event: Any = None) -> None:
        workflow = self.workflow_text()
        meta = str(self.meta.value or "").strip()
        if not workflow and not meta:
            self.set_issues(None)
            if not quiet:
                self.host.dialog("Salad Studio", EMPTY_REFUSAL, level="error")
                self.host.note(f"Refused: {EMPTY_REFUSAL}", level="warn")
            return
        try:
            knobs = comfy_import.knobs_from_sources(meta, workflow)
        except Exception as exc:  # noqa: BLE001 - a paste is user input
            self.set_issues([f"Could not parse paste: {exc}"])
            if not quiet:
                self.host.dialog("Salad Studio", f"Could not parse paste: {exc}", level="error")
            return
        try:
            blocking, notes = comfy_import.inspect_pastes(meta, workflow)
        except Exception as exc:  # noqa: BLE001
            blocking, notes = [f"Could not inspect paste: {exc}"], []
        self.set_issues(blocking, notes)

        for name in ("cfg", "seed", "steps", "width", "height"):
            value = knobs.get(name)
            if value in (None, ""):
                continue
            field = self.knob[name]
            if only_empty and str(field.value or "").strip():
                continue
            field.value = str(value)
        if knobs.get("scheduler") and (not only_empty or str(self.scheduler.value or "") in ("", "Flux2 (Klein)")):
            self.scheduler.value = ("Simple (Civitai)" if str(knobs.get("scheduler")).lower() == "simple"
                                    else "Flux2 (Klein)")
        if knobs.get("unet") and (not only_empty or not str(self.unet.value or "").strip()):
            self.unet.value = request_json.unet_label(str(knobs.get("unet")))
        if not quiet:
            self.host.note("Import knobs filled from paste", level="info")
        try:
            for field in self.knob.values():
                field.update()
            self.scheduler.update()
            self.unet.update()
        except RuntimeError:
            return

    def knobs_from_form(self) -> dict[str, Any]:
        def num(name: str, integer: bool) -> Any:
            raw = str(self.knob[name].value or "").strip()
            if not raw:
                return None
            try:
                value = float(raw)
            except ValueError:
                return None
            return int(value) if integer else (int(value) if value == int(value) else value)

        return {
            "cfg": num("cfg", False),
            "seed": num("seed", True),
            "steps": num("steps", True),
            "width": num("width", True),
            "height": num("height", True),
            "scheduler": "simple" if "simple" in str(self.scheduler.value or "").lower() else "flux2",
            "unet": (request_json.normalize_unet(str(self.unet.value)) if str(self.unet.value or "").strip()
                     else None),
        }

    # -- actions

    def fetch_civitai(self, _e: Any = None) -> None:
        raw = str(self.url_field.value or "").strip() or str(self.meta.value or "").strip()
        image_id = comfy_import.ls.civitai_image_id(raw)
        if not image_id and raw.isdigit():
            image_id = raw
        if not image_id:
            self.host.dialog("Salad Studio",
                             "Paste a Civitai image URL like https://civitai.com/images/130704876",
                             level="error")
            return
        self.host.note(f"Fetching Civitai image {image_id}…", level="info")

        def work() -> Any:
            return comfy_import.fetch_civitai_image_pastes(image_id)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self.host.dialog("Salad Studio", str(result), level="error")
                return
            self.url_field.value = f"https://civitai.com/images/{image_id}"
            self.meta.value = str(result.get("metadata") or "")
            workflow = str(result.get("workflow") or "").strip()
            self.stash = workflow
            self.workflow.value = ""
            if workflow:
                self.on_workflow_typed()
            self.fill_knobs(only_empty=False, quiet=True)
            self.set_issues([])
            tool = str(result.get("tool") or "")
            word = " (Draw Things)" if "draw things" in tool.lower() else (" (Comfy)" if workflow else "")
            self.host.note(f"Fetched {image_id}{word}", level="ok")
            refresh(self.url_field, self.meta, self.workflow)

        self.win.services.background(work, done)

    def _has_generation_data(self, meta: str) -> bool:
        if not meta:
            return False
        if comfy_import.ls.civitai_image_id(meta):
            return True
        parsed = comfy_import.parse_civitai_metadata(meta)
        return any(parsed.get(k) not in (None, "", [], {}) for k in
                   ("steps", "cfg", "sampler", "scheduler", "seed", "model", "width", "height", "tools"))

    def convert(self, _e: Any = None) -> None:
        workflow = self.workflow_text()
        meta = str(self.meta.value or "").strip()
        url = str(self.url_field.value or "").strip()
        if url and comfy_import.ls.civitai_image_id(url) and not comfy_import.ls.civitai_image_id(meta):
            meta = url + "\n" + meta
        _, raw_graph = comfy_import.split_pastes(meta, workflow)
        if not raw_graph and not self._has_generation_data(meta):
            self.host.dialog("Salad Studio", NOTHING_TO_CONVERT, level="error")
            self.host.note(f"Refused: {NOTHING_TO_CONVERT}", level="warn")
            return
        try:
            self.fill_knobs(only_empty=True, quiet=True)
            payload = comfy_import.import_to_request(workflow_text=workflow, metadata_text=meta,
                                                     knobs=self.knobs_from_form())
        except (ValueError, TypeError) as exc:
            self.host.dialog("Salad Studio", f"Cannot convert Civitai paste: {exc}", level="error")
            self.host.note("Refused: cannot convert the Civitai paste", level="error")
            return
        self.stash = ""
        self.workflow.value = ""
        census = comfy_import.comfy_convert_census_note(workflow, payload)
        self.set_issues([], ([census] if census else []) + list(comfy_import.replica_issues(payload)))
        editor = self.win.open_page("Prompt Editor")
        editor.set_payload(payload)
        stats = prompt_history.request_stats(payload)
        self.host.note(census or "Imported Civitai workflow to Prompt Editor", level="ok")
        self.host.log("ok", f"imported Civitai paste  {stats}" + (f"  {census}" if census else ""))

    def clear(self, _e: Any = None) -> None:
        self.win.pump.cancel(self._fill_token)
        self.stash = ""
        self.meta.value = ""
        self.workflow.value = ""
        self.url_field.value = ""
        for field in self.knob.values():
            field.value = ""
        self.scheduler.value = "Flux2 (Klein)"
        self.unet.value = ""
        self.set_issues(None)
        self.host.note("Import paste cleared", level="info")
        try:
            for field in (self.meta, self.workflow, self.url_field, *self.knob.values(), self.scheduler, self.unet):
                field.update()
        except RuntimeError:
            return
