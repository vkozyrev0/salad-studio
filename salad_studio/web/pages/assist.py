"""Prompt Assist: ask DeepSeek or the local model for a fix, then commit it.

Help is one network round trip. It runs on ``ctx.background``, so the page
answers at once with ``pending`` and ``action_done`` carries the reply; the
reply and the adjusted boxes are kept here for that done step to fill. The
commit writes through the editor controller, which owns the JSON.

The boxes the page edits arrive as ``edited``, an object the engine shares
with a state it has already handed to an event. So each action first copies
the five values it needs, and reads nothing else from that object. Help reads
the DeepSeek key and the editor's context before its worker starts, on the
core thread. Findings resolve against the LoRA store only, because the online
probe would hold the core thread, which every other page waits on.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import ai_helper  # noqa: E402  top-level, as the Flet page imported it
from salad_studio import generator, ref_check

LOCAL_DEFAULT = ai_helper.LOCAL_BASE_URL
BACKENDS = ("deepseek", "local")
COMMITTED = "Prompt Assist: committed to the prompts and the JSON"
REBUILT = "Prompt Assist: committed (the JSON was rebuilt)"
EDITED = ("localUrl", "sendImage", "issue", "positive", "negative")


class AssistController:
    page = "assist"

    def __init__(self, studio: Any) -> None:
        self.studio = studio
        self.local_url = LOCAL_DEFAULT
        self.send_image = False
        self.issue = ""
        self.positive = ""
        self.negative = ""
        self.reply = ""
        self.message = ("", "info")
        self.request: dict[str, Any] = {}  # this request's fields, kept by the registered form

    def register(self, table: Any) -> None:
        table.action("assist.view")(self.view)
        table.action("assist.help", need={"backend": str})(
            lambda payload, **extra: self.help(payload, **extra))
        table.action("assist.commit")(self.commit)

    def view(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        return self.state()

    def state(self) -> dict[str, Any]:
        image = self._latest_image()
        if not self.send_image:
            note = "off, no image is sent"
        elif image is None:
            note = "no generated image yet, nothing will be attached"
        else:
            note = f"the newest plate, {image.name}, is attached"
        return {
            "localUrl": self.local_url,
            "sendImage": self.send_image,
            "issue": self.issue,
            "positive": self.positive,
            "negative": self.negative,
            "imageNote": note,
            "reply": self.reply,
            "status": {"text": self.message[0], "level": self.message[1]},
        }

    # -- actions

    def help(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        self.request = payload
        backend = self._arg(ctx, "backend", payload.get("backend", ""))
        if backend not in BACKENDS:
            raise ValueError(f"there is no backend called {backend!r}")
        self._take(_boxes_from(self, payload, ctx))
        if backend == "deepseek" and not ctx.studio.services.token("deepseek"):
            return self._no_key(ctx)
        key = ctx.studio.services.token("deepseek") if backend == "deepseek" else ""
        label = "DeepSeek" if backend == "deepseek" else "the local model"
        image = self._latest_image() if self.send_image else None
        if image is None and self.send_image:
            ctx.log("warn", "Prompt Assist: no generated image to attach")
        editor = ctx.studio.controllers.get("editor")
        inputs = dict(editor.context()) if editor is not None else {}
        inputs.update(adjusted_positive=self.positive.strip(), adjusted_negative=self.negative.strip(),
                      issue=self.issue)
        findings = _findings(ctx, inputs["request_json"])
        url = self.local_url

        call = lambda: _ask(backend, key, url, image, findings, inputs)  # noqa: E731
        if ctx.confirmed:
            # The engine holds this action's busy key until the confirm's own
            # request is done, so a background run started here would be
            # refused when it lands. Ask now and answer in this reply.
            self._finish(_guarded(call), ctx)
            return self.state()

        ctx.background(lambda: _guarded(call), lambda result: self._finish(result, ctx))
        self.message = (f"Asking {label}…", "info")
        return self.state()

    def commit(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        self._take(_boxes_from(self, payload, ctx))
        if not self.positive.strip() and not self.negative.strip():
            ctx.dialog("Salad Studio", "The adjusted prompts are empty. Ask DeepSeek or the local "
                                      "model for help first.")
            return self.state()
        patched = ctx.studio.controllers.get("editor").commit_prompts(self.positive, self.negative)
        text = COMMITTED if patched else REBUILT
        self.message = (text, "info")
        ctx.note(text, level="ok" if patched else "warn")
        return self.state()

    # -- the two continuations

    def _no_key(self, ctx: Any) -> dict[str, Any]:
        note = "No DeepSeek key is saved. Add it on the Tokens tab, then press Help again."
        if ctx.confirmed:
            self.reply = note
            self.message = (f"Refused: {note}", "error")
            ctx.note(f"Refused: {note}", level="error")
            return self.state()
        ctx.effects.append({
            "kind": "confirm",
            "token": ctx.studio.issue_confirm("assist", "help", {
                "backend": "deepseek",
                "edited": {"localUrl": self.local_url, "sendImage": self.send_image,
                           "issue": self.issue, "positive": self.positive, "negative": self.negative},
            }),
            "title": "Ask DeepSeek",
            "body": note,
        })
        return self.state()

    def _finish(self, result: Any, ctx: Any) -> None:
        """The done step: the reply fills the boxes, a failure becomes the state line and a dialog."""
        if isinstance(result, ai_helper.ReplyError):
            raw = str(getattr(result, "raw", "") or "")
            if raw:
                self.reply = raw
            ctx.dialog("Salad Studio", raw or str(result), level="error")
            ctx.log("error", f"Prompt Assist: {result}")
            self.message = (str(result), "error")
            return
        if isinstance(result, Exception):
            diagnostic = str(result)
            ctx.dialog("Salad Studio", diagnostic, level="error")
            ctx.log("error", f"Prompt Assist: {diagnostic}")
            self.message = (f"{type(result).__name__}: {diagnostic}", "error")
            return
        self._show(result, ctx)

    def _show(self, reply: dict[str, Any], ctx: Any) -> None:
        """A prompt the reply does not carry leaves its box as the user left it."""
        self.reply = str(reply.get("raw") or "")
        if reply.get("positive"):
            self.positive = str(reply["positive"])
        if reply.get("negative"):
            self.negative = str(reply["negative"])
        self.message = ("The model answered", "info")
        image = str(reply.get("image") or "")
        if image:
            ctx.log("info", f"Prompt Assist: attached {Path(image).name}")
        continued = int(reply.get("continued") or 0)
        if continued:
            ctx.log("warn", f"Prompt Assist: the reply needed {continued} continuation round(s)")

    # -- the boxes the page edits

    def _take(self, edited: dict[str, Any]) -> None:
        """An absent box keeps its value; a blank one is blank. Only the five values are read."""
        url = edited.get("localUrl")
        if isinstance(url, str) and url.strip():
            self.local_url = url.strip()
        if "sendImage" in edited:
            self.send_image = bool(edited["sendImage"])
        for key in ("issue", "positive", "negative"):
            if key in edited:
                setattr(self, key, str(edited.get(key) or ""))

    def _arg(self, ctx: Any, name: str, default: Any) -> Any:
        """One request field: the handler's payload, then the context's copy of the request.

        The table hands a handler a filtered copy, and on this platform that
        copy has dropped a nested value without complaint. The context's
        ``args`` is the engine's own request object; either source is checked.
        """
        if name in self.request:
            return self.request[name]
        args = getattr(ctx, "args", None) or {}
        return args.get(name, default) if isinstance(args, dict) else default

    def _latest_image(self) -> Path | None:
        # The plate cache the shell already fills, rather than a second scan of the folder.
        plates = self.studio.plates
        return self.studio.services.plate_path(plates[0][0]) if plates else None


def _boxes_from(controller: Any, payload: dict[str, Any], ctx: Any) -> dict[str, Any]:
    for source in (controller.request, getattr(ctx, "args", None), payload):
        if isinstance(source, dict) and isinstance(source.get("edited"), dict):
            return source["edited"]
    return {}


def _findings(ctx: Any, text: str) -> str:
    try:
        payload = generator.parse_request_json(text)
        resolved = ref_check.resolve_refs(payload, lookup=_lookup_local)
        missing = ref_check.unresolved(resolved)
        if missing:
            ctx.log("warn", "Prompt Assist: unresolved weights "
                  + ", ".join(str(f.get("name")) for f in missing))
        return ref_check.format_findings(resolved)
    except (ValueError, TypeError) as exc:
        ctx.log("warn", f"Prompt Assist: request JSON is invalid ({exc})")
        return f"(the Prompt Editor JSON could not be parsed: {exc})"


def _guarded(call: Any) -> Any:
    """A failed round trip travels as a value, so the done step always runs and names it."""
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - the page shows it in a dialog and the log
        return exc


def _lookup_local(name: str, kind: str) -> dict[str, Any] | None:
    return ref_check.local_lookup(name)


def _ask(backend: str, key: str, url: str, image: Path | None, findings: str,
         inputs: dict[str, str]) -> dict[str, Any]:
    """The round trip. Its arguments are all it reads, so it may run on a worker or inline."""
    if backend == "deepseek":
        return ai_helper.help_with_prompts(key, findings=findings, image_path=image, **inputs)
    return ai_helper.help_with_prompts_local(url=url or LOCAL_DEFAULT, findings=findings,
                                             image_path=image, **inputs)
