"""Prompt Assist: ask DeepSeek or the local model for a fix, then commit it.

The reply is shown raw; the adjusted prompts are editable and are what
"Commit to Prompts + JSON" writes into the editor's prompt boxes and its JSON.
The round trip runs on a worker thread; the continuation count comes back in
the reply and is logged rather than retried here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import flet as ft

from salad_studio import ai_helper, flet_theme, flet_widgets as w, generator, ref_check, tokens
from salad_studio.flet_pump import refresh
from salad_studio.flet_services import OUT_DIR, help_round
from salad_studio.flet_shell import Page

LOCAL_DEFAULT = ai_helper.LOCAL_BASE_URL
INPUTS = ("editor_positive", "editor_negative", "adjusted_positive", "adjusted_negative",
          "request_json", "issue")


class AssistPage(Page):
    def __init__(self, host: Any) -> None:
        super().__init__("Prompt Assist", "Ask for a prompt fix, then commit it.", host.colors)
        self.host = host
        self.win = host
        self.local_url = w.field(LOCAL_DEFAULT, label_text="Local LLM URL", width=420)
        self.send_image = w.check("Send the latest generated image", False,
                                  on_change=lambda _e: self._image_note())
        self.image_note = ft.Text("", size=11, color=self.colors["muted"])
        self.issue = w.field("", label_text="Image issue / problem", multiline=True)
        self.adj_pos = w.field("", label_text="Adjusted positive prompt", multiline=True)
        self.adj_neg = w.field("", label_text="Adjusted negative prompt", multiline=True)
        self.state = ft.Text("", size=12, color=self.colors["muted"])
        self.reply = ft.TextField(multiline=True, min_lines=7, max_lines=20, read_only=True,
                                  expand=True, text_size=12)
        self.help_btn = w.button("Help (DeepSeek)", lambda _e: self.start("deepseek"), primary=True)
        self.local_btn = w.button("Help (local)", lambda _e: self.start("local"))
        self.commit_btn = w.button("Commit to Prompts + JSON", self.commit, primary=True)
        self.body.content = ft.Column(
            [
                ft.Row([self.local_url, self.send_image], spacing=flet_theme.GAP["sm"]),
                self.image_note,
                self.issue,
                self.adj_pos,
                self.adj_neg,
                ft.Row([self.help_btn, self.local_btn, self.commit_btn],
                       spacing=flet_theme.GAP["sm"]),
                self.state,
                ft.Text("Reply", size=12, weight=ft.FontWeight.W_600, color=self.colors["muted"]),
                ft.Container(self.reply, expand=True),
            ],
            spacing=flet_theme.GAP["sm"],
            expand=True,
            scroll=ft.ScrollMode.ALWAYS,
        )
        self._image_note()

    def latest_image(self) -> Path | None:
        plates = generator.list_history(OUT_DIR)
        return plates[0] if plates else None

    def _image_note(self) -> None:
        latest = self.latest_image()
        if not self.send_image.value:
            text = "off, no image is sent"
        elif latest is None:
            text = "no generated image yet, nothing will be attached"
        else:
            text = f"the newest plate, {latest.name}, is attached"
        self.image_note.value = text
        refresh(self.image_note)

    def _inputs(self) -> dict[str, str]:
        editor = self.win.shell.pages.get("Prompt Editor")
        base = editor.context() if editor is not None and hasattr(editor, "context") else {
            "editor_positive": "", "editor_negative": "", "request_json": ""}
        return {
            **base,
            "adjusted_positive": str(self.adj_pos.value or "").strip(),
            "adjusted_negative": str(self.adj_neg.value or "").strip(),
            "issue": str(self.issue.value or "").strip(),
        }

    def start(self, backend: str) -> None:
        if self.win.services.busy_flags.get("help"):
            return
        key = tokens.read_token("deepseek") if backend == "deepseek" else ""
        if backend == "deepseek" and not key:
            note = "No DeepSeek key is saved. Add it on the Tokens tab, then press Help again."
            self.reply.value = note
            refresh(self.reply)
            self.host.note(f"Refused: {note}", level="error")
            return
        self.win.services.busy_flags["help"] = True
        label = "DeepSeek" if backend == "deepseek" else "the local model"
        self.state.value = f"Asking {label}…"
        refresh(self.state)
        image = self.latest_image() if self.send_image.value else None
        if image is None and self.send_image.value:
            self.host.log("warn", "Prompt Assist: no generated image to attach")
        inputs = self._inputs()
        url = str(self.local_url.value or LOCAL_DEFAULT)
        self.host.note(f"Prompt Assist: asking {label}…", level="info")

        def work() -> Any:
            findings = ""
            try:
                payload = generator.parse_request_json(inputs["request_json"])
                resolved = ref_check.resolve_refs(payload)
                findings = ref_check.format_findings(resolved)
                missing = ref_check.unresolved(resolved)
                if missing:
                    self.host.log("warn", "Prompt Assist: unresolved weights "
                                  + ", ".join(str(f.get("name")) for f in missing))
            except (ValueError, TypeError) as exc:
                self.host.log("warn", f"Prompt Assist: request JSON is invalid ({exc})")
                findings = f"(the Prompt Editor JSON could not be parsed: {exc})"
            return help_round(key, local=backend != "deepseek", local_url=url, image_path=image,
                              findings=findings, **{k: inputs[k] for k in INPUTS})

        def done(result: Any) -> None:
            self.win.services.busy_flags["help"] = False
            if isinstance(result, Exception):
                self.state.value = f"{type(result).__name__}: {result}"
                self.host.dialog("Salad Studio", str(result), level="error")
                self.host.log("error", f"Prompt Assist: {result}")
            else:
                self._show(result)
            refresh(self.state)

        self.win.services.background(work, done)

    def _show(self, reply: dict[str, Any]) -> None:
        self.reply.value = str(reply.get("raw") or "")
        self.adj_pos.value = str(reply.get("positive") or "")
        self.adj_neg.value = str(reply.get("negative") or "")
        self.state.value = "The model answered"
        image = str(reply.get("image") or "")
        if image:
            self.host.log("info", f"Prompt Assist: attached {Path(image).name}")
        continued = int(reply.get("continued") or 0)
        if continued:
            self.host.log("warn", f"Prompt Assist: the reply needed {continued} continuation round(s)")
        refresh(self.reply, self.adj_pos, self.adj_neg)

    def commit(self, _e: Any = None) -> None:
        positive = str(self.adj_pos.value or "").strip()
        negative = str(self.adj_neg.value or "").strip()
        if not positive and not negative:
            self.host.dialog("Salad Studio", "The adjusted prompts are empty. Ask DeepSeek or the local "
                                            "model for help first.")
            return
        engine = self.win.ensure_page("Prompt Editor")
        patched = engine.commit_prompts(positive, negative)
        self.state.value = ("Prompt Assist: committed to the prompts and the JSON" if patched
                            else "Prompt Assist: committed (the JSON was rebuilt)")
        refresh(self.state)
        self.host.note(self.state.value, level="ok" if patched else "warn")
