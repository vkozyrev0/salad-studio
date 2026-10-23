"""Import: paste a Comfy workflow or Civitai data, fill the knobs, convert.

The paste lives on the controller, because every box refills from it: a
workflow over ``STASH_CHARS`` is held here and the box shows only a summary, and
Fetch replaces all three boxes from one result. The browser keeps whatever is
typed in the boxes and sends it with each action, so nothing waits on a timer.

The state carries the knobs as a list the page lays out, and the replica issues
as plain strings. What was found and what was converted go in two separate
fields, so a fill after a convert cannot hide the issues the convert found.
"""
from __future__ import annotations

from typing import Any

import comfy_import
import prompt_history
import request_json
from salad_studio.web import actions

PAGE = "import"
SCHEDULER_LABELS = ("Flux2 (Klein)", "Simple (Civitai)")
DEFAULT_SCHEDULER = SCHEDULER_LABELS[0]
EMPTY_REFUSAL = ("Nothing to fill. Paste a Comfy workflow JSON and/or Civitai generation data "
                 "(prompt + Steps/CFG, or Sampler/Seed/Model).")
NOTHING_TO_CONVERT = ("Nothing to convert. Paste a Comfy workflow JSON and/or Civitai generation "
                      "data (prompt + Steps/CFG, or Sampler/Seed/Model).")
# Past this, the box shows a summary and the controller keeps the text, so a
# multi-megabyte graph does not crawl the field.
STASH_CHARS = 20000
STASH_SUMMARY = "[Comfy workflow JSON in memory, {n:,} characters]\n{scheduler}"
STASH_NOTE = "Not shown in this box so the UI stays fast. Convert uses this paste.\nClear Import to drop it."
KNOBS: tuple[tuple[str, str], ...] = (
    ("cfg", "CFG"), ("seed", "Seed"), ("steps", "Steps"), ("width", "Width"), ("height", "Height"),
)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _scheduler_label(raw: str) -> str:
    return "Simple (Civitai)" if raw.lower() == "simple" else DEFAULT_SCHEDULER


def _number(raw: str, integer: bool) -> Any:
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return int(value) if integer or value == int(value) else value


class ImportController:
    page = PAGE

    def __init__(self, studio: Any) -> None:
        self.studio = studio
        self.url = ""
        self.meta = ""
        self.workflow = ""
        self.stash = ""
        self.edit_rev = 0
        self.knobs: dict[str, str] = {name: "" for name, _label in KNOBS}
        self.scheduler = DEFAULT_SCHEDULER
        self.unet = ""
        self.issues: list[str] = []
        self.notes: list[str] = []
        self.inspected = False

    def register(self, table: Any) -> None:
        table.action("import.view")(self.view)
        table.action("import.set_paste")(self.set_paste)
        table.action("import.fill_knobs")(self.fill_knobs)
        table.action("import.convert")(self.convert)
        table.action("import.fetch_civitai")(self.fetch_civitai)
        table.action("import.clear_import")(self.clear_import)

    def view(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        return self.state()

    def state(self) -> dict[str, Any]:
        shown = (STASH_SUMMARY.format(n=len(self.stash), scheduler=STASH_NOTE)
                 if self.stash else self.workflow)
        return {
            "url": self.url,
            "meta": self.meta,
            "workflow": shown,
            "stashed": bool(self.stash),
            "knobs": [
                {"key": name, "label": label, "value": self.knobs.get(name, "")}
                for name, label in KNOBS
            ],
            "scheduler": self.scheduler,
            "scheduler_labels": list(SCHEDULER_LABELS),
            "unet": self.unet,
            "unet_labels": list(request_json.UNET_LABELS),
            "issues": list(self.issues),
            "notes": list(self.notes),
            "inspected": self.inspected,
        }

    # -- the paste

    def _workflow(self, payload: dict[str, Any]) -> str:
        if self.stash:
            return self.stash
        if self.workflow:
            return self.workflow
        return _text(payload.get("workflow"))

    def _adopt(self, payload: dict[str, Any]) -> None:
        """Take the boxes the page sent as what the next action sees."""
        # An empty string is a field the page cleared. JSON's null is a field
        # the page omitted, and must leave the held value alone.
        url = payload.get("url")
        if isinstance(url, str):
            self.url = url.strip()
        meta = payload.get("meta")
        if isinstance(meta, str):
            self.meta = _text(meta)
        workflow = payload.get("workflow")
        if isinstance(workflow, str):
            typed = workflow.strip()
            if self.stash and typed and not typed.startswith("[Comfy workflow JSON in memory"):
                # Typing over the summary drops the paste it stood for.
                self.stash = ""
            if len(workflow) > STASH_CHARS:
                self.stash = workflow
                self.workflow = ""
            elif not (self.stash and typed.startswith("[Comfy workflow JSON in memory")):
                # A normal paste stays in the box; the page re-seeds from state.
                self.workflow = workflow
        for name, _label in KNOBS:
            if name in payload:
                self.knobs[name] = str(payload[name])
        if "scheduler" in payload:
            self.scheduler = str(payload["scheduler"] or DEFAULT_SCHEDULER)
        if "unet" in payload:
            self.unet = str(payload["unet"] or "")

    def set_paste(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        """The page's one write of a box: large pastes move into the stash."""
        self.edit_rev += 1
        self._adopt(payload)
        return self.state()

    def _knobs_from_form(self) -> dict[str, Any]:
        return {
            "cfg": _number(self.knobs["cfg"], integer=False),
            "seed": _number(self.knobs["seed"], integer=True),
            "steps": _number(self.knobs["steps"], integer=True),
            "width": _number(self.knobs["width"], integer=True),
            "height": _number(self.knobs["height"], integer=True),
            "scheduler": "simple" if "simple" in self.scheduler.lower() else "flux2",
            "unet": request_json.normalize_unet(self.unet) if self.unet.strip() else None,
        }

    def _extras_path(self) -> Any:
        return getattr(self.studio.services, "extras_path", None)

    # -- actions

    def fill_knobs(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        self._adopt(payload)
        workflow = self._workflow(payload)
        meta = self.meta
        if not workflow and not meta:
            self.issues, self.notes, self.inspected = [], [], False
            ctx.dialog("Salad Studio", EMPTY_REFUSAL, level="error")
            ctx.note(f"Refused: {EMPTY_REFUSAL}", level="warn")
            return self.state()
        only_empty = bool(payload.get("only_empty"))

        def work() -> dict[str, Any]:
            return self._fill(workflow, meta, only_empty=only_empty)

        def done(filled: Any) -> None:
            if isinstance(filled, Exception):
                self.issues, self.notes, self.inspected = [str(filled)], [], True
                ctx.dialog("Salad Studio", f"Could not fill knobs: {filled}", level="error")
                return
            self._take_fill(filled)
            if "error" in filled:
                ctx.dialog("Salad Studio", f"Could not parse paste: {filled['error']}", level="error")
                return
            ctx.note("Import knobs filled from paste", level="info")

        ctx.background(work, done)
        return self.state()

    def _fill(self, workflow: str, meta: str, *, only_empty: bool) -> dict[str, Any]:
        """Knobs and the issue report for one paste. Runs off the core thread, never changes self."""
        try:
            knobs = comfy_import.knobs_from_sources(meta, workflow)
        except Exception as exc:  # noqa: BLE001 - a paste is user input
            return {"error": str(exc)}
        try:
            issues, notes = comfy_import.inspect_pastes(meta, workflow)
        except Exception as exc:  # noqa: BLE001
            issues, notes = [f"Could not inspect paste: {exc}"], []
        values = {name: str(knobs.get(name)) for name, _label in KNOBS if knobs.get(name) not in (None, "")}
        scheduler = _scheduler_label(str(knobs["scheduler"])) if knobs.get("scheduler") else ""
        unet = request_json.unet_label(str(knobs["unet"])) if knobs.get("unet") else ""
        return {"issues": issues, "notes": notes, "knobs": values, "scheduler": scheduler,
                "unet": unet, "only_empty": only_empty}

    def _take_fill(self, filled: dict[str, Any]) -> None:
        """A refused fill keeps the issues it found, rather than clearing them."""
        if "error" in filled:
            self.issues, self.notes, self.inspected = [f"Could not parse paste: {filled['error']}"], [], True
            return
        self.issues = list(filled["issues"])
        self.notes = list(filled["notes"])
        self.inspected = True
        only_empty = bool(filled["only_empty"])
        for name, _label in KNOBS:
            value = filled["knobs"].get(name)
            if value is None or (only_empty and self.knobs[name].strip()):
                continue
            self.knobs[name] = value
        if filled["scheduler"] and (not only_empty or self.scheduler in ("", DEFAULT_SCHEDULER)):
            self.scheduler = filled["scheduler"]
        if filled["unet"] and (not only_empty or not self.unet.strip()):
            self.unet = filled["unet"]

    def convert(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        self._adopt(payload)
        editor = self.studio.controllers.get("editor")
        if editor is None:
            ctx.dialog("Salad Studio", "Open the Prompt Editor first.", level="error")
            return self.state()
        workflow = self._workflow(payload)
        meta = self.meta
        if self.url and comfy_import.ls.civitai_image_id(self.url) and not comfy_import.ls.civitai_image_id(meta):
            meta = self.url + "\n" + meta
        try:
            _meta_text, raw_graph = comfy_import.split_pastes(meta, workflow)
        except (TypeError, ValueError):
            raw_graph = ""
        if not raw_graph and not self._has_generation_data(meta):
            ctx.dialog("Salad Studio", NOTHING_TO_CONVERT, level="error")
            ctx.note(f"Refused: {NOTHING_TO_CONVERT}", level="warn")
            return self.state()
        only_empty = bool(payload.get("fill_empty"))
        form = self._knobs_from_form()
        # The two selects are always the page's; the numeric knobs only when the
        # press asked to fill the form.
        knobs = form if only_empty else {"scheduler": form["scheduler"], "unet": form["unet"]}
        extras = self._extras_path()

        def work() -> dict[str, Any]:
            # The report is built beside the request, so it runs off the core thread too.
            try:
                body = comfy_import.import_to_request(workflow_text=workflow, metadata_text=meta,
                                                      knobs=knobs, extras_path=extras)
                return {"body": body, "issues": [str(n) for n in comfy_import.replica_issues(body)],
                        "census": comfy_import.comfy_convert_census_note(workflow, body)}
            except (ValueError, TypeError) as exc:
                return {"refused": str(exc)}
            except Exception as exc:  # noqa: BLE001 - a defect's text never reaches the page
                return {"failed": exc}

        def done(result: dict[str, Any]) -> None:
            if "refused" in result:
                ctx.note("Refused: cannot convert the Civitai paste", level="error")
                ctx.dialog("Salad Studio", f"Cannot convert Civitai paste: {result['refused']}", level="error")
                return
            if "failed" in result:
                ctx.note(actions.to_error(result["failed"]).message, level="error")
                return
            self.stash = ""
            self.issues = list(result["issues"])
            self.notes = ([result["census"]] if result["census"] else []) + self.issues
            self.inspected = True
            body = result["body"]
            census = result["census"]
            editor.set_payload(body)
            ctx.navigate("editor")
            stats = prompt_history.request_stats(body)
            ctx.note(census or "Imported Civitai workflow to Prompt Editor", level="ok")
            ctx.log("ok", f"imported Civitai paste  {stats}" + (f"  {census}" if census else ""))

        ctx.background(work, done)
        ctx.note("Converting the paste…")
        return self.state()

    def _has_generation_data(self, meta: str) -> bool:
        if not meta:
            return False
        if comfy_import.ls.civitai_image_id(meta):
            return True
        parsed = comfy_import.parse_civitai_metadata(meta)
        return any(parsed.get(k) not in (None, "", [], {}) for k in
                   ("steps", "cfg", "sampler", "scheduler", "seed", "model", "width", "height", "tools"))

    def fetch_civitai(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        self._adopt(payload)
        raw = self.url or self.meta
        image_id = comfy_import.ls.civitai_image_id(raw)
        if not image_id and raw.isdigit():
            image_id = raw
        if not image_id:
            ctx.dialog("Salad Studio",
                       "Paste a Civitai image URL like https://civitai.com/images/130704876",
                       level="error")
            return self.state()

        def work() -> dict[str, Any]:
            result = comfy_import.fetch_civitai_image_pastes(image_id)
            workflow = str(result.get("workflow") or "").strip()
            meta = str(result.get("metadata") or "")
            return {**result, "filled": self._fill(workflow, meta, only_empty=False)}

        start_rev = self.edit_rev

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                if isinstance(result, (ValueError, OSError)):
                    ctx.dialog("Salad Studio", str(result), level="error")
                return
            if self.edit_rev != start_rev:
                ctx.note("Fetch finished, but the paste changed; the fetched workflow was not applied.",
                         level="warn")
                return
            workflow = str(result.get("workflow") or "").strip()
            self.issues, self.notes, self.inspected = [], [], False
            self.url = f"https://civitai.com/images/{image_id}"
            self.meta = str(result.get("metadata") or "")
            self.stash = workflow if len(workflow) > STASH_CHARS else ""
            self.workflow = "" if self.stash else workflow
            self._take_fill(result.get("filled") or {})
            tool = str(result.get("tool") or "")
            word = " (Draw Things)" if "draw things" in tool.lower() else (" (Comfy)" if workflow else "")
            ctx.note(f"Fetched {image_id}{word}", level="ok")

        ctx.background(work, done)
        ctx.note(f"Fetching Civitai image {image_id}…", level="info")
        return self.state()

    def clear_import(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        self._adopt(payload)
        self.url = ""
        self.meta = ""
        self.workflow = ""
        self.stash = ""
        self.knobs = {name: "" for name, _label in KNOBS}
        self.scheduler = DEFAULT_SCHEDULER
        self.unet = ""
        self.issues, self.notes, self.inspected = [], [], False
        ctx.note("Import paste cleared", level="info")
        return self.state()
