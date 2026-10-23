"""Prompt Editor: the request JSON every other page reads and writes.

The JSON, the two prompt texts and the graph live on this controller, which is
on the core thread. Catalog, History, Import and Prompt Assist reach them
through ``self.studio.controllers.get("editor")`` and the methods below
``state``. Nothing else edits them, so ``rev`` counts every write and a
keystroke carried over from a stale view is dropped rather than overwriting a
later one.

The rules for reading the text (which node is the positive encode, what a
patch does to it) live in this module with it.

``state()`` is pure: it reads what the last action stored. Network work
belongs in the action that needs it, never here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

import comfy_import
from salad_studio import graph_model as gm, request_json


class EditorController:
    page = "editor"

    def __init__(self, studio: Any) -> None:
        self.studio = studio
        self.rev = 0
        self.model = gm.GraphModel()
        self.status = ("", "info")
        self._set_payload(empty_payload())
        # The editor holds the request the settings describe from the start, so
        # Generate works on a fresh studio without a press nobody asked for.
        # A knob the store cannot hold leaves it empty, and Validate says why.
        self._rebuild_now(quiet=True)

    def register(self, table: Any) -> None:
        table.action("editor.view")(self.view)
        table.action("editor.recall")(self.recall)
        table.action("editor.set_json", need={"text": str, "base": int})(self.set_json)
        table.action("editor.set_prompt", need={"positive": str, "negative": str})(self.set_prompt)
        table.action("editor.rebuild_from_config")(self.rebuild_from_config)
        table.action("editor.rebuild_from_json")(self.rebuild_from_json)
        table.action("editor.validate")(self.validate)
        table.action("editor.swap_selected")(self.swap_selected)
        table.action("editor.move_node", need={"id": str, "x": float, "y": float})(self.move_node)

    def view(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        return self.state()

    def state(self) -> dict[str, Any]:
        return {
            "json": self.json,
            "positive": self.positive,
            "negative": self.negative,
            "status": {"text": self.status[0], "level": self.status[1]},
            "errors": _errors(self.json),
            "graph": _graph_dict(self.model),
            "rev": self.rev,
        }

    # -- what the other pages use

    def recall(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        """Put one history entry into the editor: its request, or its text when it has none.

        The request is an object or absent, so it is read from the payload
        rather than declared: the table's contract checks one kind per field.
        """
        request = payload.get("request")
        if isinstance(request, dict) and request:
            self._set_payload(request)
        else:
            self.set_positive_only(str(payload.get("text") or ""))
        return self.state()

    def text(self) -> str:
        """The JSON as typed. Generate and Catalog parse it themselves."""
        return self.json

    def context(self) -> dict[str, str]:
        """The three texts Prompt Assist sends."""
        return {
            "editor_positive": self.positive.strip(),
            "editor_negative": self.negative.strip(),
            "request_json": self.json.strip(),
        }

    def set_payload(self, payload: dict[str, Any]) -> None:
        """Replace the whole request. Catalog's load, History's reuse and Import's convert."""
        self._set_payload(payload)

    def set_positive_only(self, text: str) -> None:
        """History's bare prompts carry no JSON: keep the request, swap the positive text.

        An empty prompt has no text node to patch, so it is rebuilt from the
        form instead. Patching it would drop the text on the floor.
        """
        parsed = parse(self.json)
        if parsed.ok and parsed.prompt:
            prompt = patch_text(parsed.prompt, "pos", text)
            self._set_payload(with_prompt(parsed.payload, prompt))
            return
        graph = _profile(self.studio).graph
        self._set_payload(request_json.build_request(
            prompt_text=text, graph=graph if graph in ("klein", "flux1") else "klein",
            width=1024, height=1024, steps=20, seed=1, selected_ids=[]))

    def commit_prompts(self, positive: str, negative: str) -> bool:
        """Prompt Assist's commit. False means the JSON was invalid and was rebuilt from the form."""
        parsed = parse(self.json)
        if not parsed.ok:
            self._rebuild_now()
            return False
        prompt = patch_text(parsed.prompt, "pos", positive)
        prompt = patch_text(prompt, "neg", negative)
        self._set_payload(with_prompt(parsed.payload, prompt))
        return True

    # -- actions

    def set_json(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        """A keystroke from the JSON box, tagged with the revision it was typed into."""
        if payload["base"] != self.rev:
            self._say("An import replaced the JSON while you were typing. Your edit was dropped.", "warn")
            return self.state()
        self._read_json(payload["text"])
        return self.state()

    def set_prompt(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        parsed = parse(self.json)
        if not parsed.ok:
            return self.state()
        positive, negative = payload["positive"], payload["negative"]
        prompt = parsed.prompt
        for which, text in (("pos", positive), ("neg", negative)):
            current = prompt_texts(prompt)[0 if which == "pos" else 1]
            if current != text:
                prompt = patch_text(prompt, which, text)
        if prompt is parsed.prompt:
            return self.state()
        self._set_payload(with_prompt(parsed.payload, prompt), relayout=False)
        return self.state()

    def rebuild_from_config(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        """The request from the form's knobs. Runs on a worker; the page learns when it lands."""
        if ctx is None:
            self._rebuild_now()
            return self.state()
        # A confirm would collide with the busy key its own request still holds.
        if ctx.confirmed:
            self._rebuild_now()
            return self.state()
        # The form is copied first, so the worker reads no object the core
        # thread can replace. A knob it cannot hold refuses before any work.
        try:
            form, stored = _snapshot(self.studio)
        except ValueError as exc:
            self._say(f"Refused: {exc}", "warn")
            return self.state()

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                ctx.note(f"Refused: {result}", level="error")
                return
            self._set_payload(result)
            ctx.note("Rebuilt the request from Prompt Settings", level="ok")

        # No start note: the engine puts an action's last note on its own reply,
        # and a start note would land after this done note in action_done.
        ctx.background(lambda: _from_form(form, stored), done)
        return self.state()

    def rebuild_from_json(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        """Drop view positions and selection and lay the graph out afresh."""
        parsed = parse(self.json)
        if not parsed.ok:
            self._say(parsed.error, "error")
            return self.state()
        self._set_payload(with_prompt(parsed.payload, parsed.prompt))
        self._say("Rebuilt the request from the JSON", "ok")
        return self.state()

    def validate(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        errors = _errors(self.json)
        if errors:
            self._message(errors, "error")
        else:
            self._message(["JSON valid"], "ok")
        return self.state()

    def swap_selected(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        # The page keeps its own selection; the model's is only the fallback.
        ids = payload.get("ids")
        selected = [str(i) for i in ids] if isinstance(ids, list) and len(ids) == 2 else list(self.model.selected)
        if len(selected) != 2:
            self._say("Select two nodes first.", "warn")
            return self.state()
        parsed = parse(self.json)
        if not parsed.ok:
            return self.state()
        try:
            swapped = gm.swap_payloads(parsed.prompt, *selected)
        except ValueError as exc:
            self._say(str(exc), "warn")
            return self.state()
        self._set_payload(with_prompt(parsed.payload, swapped))
        self.model = self.model.with_selection(())
        return self.state()

    def move_node(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        """A dragged card's new view position. The JSON is unchanged."""
        node = self.model.node(payload["id"])
        if node is None:
            raise ValueError(f"there is no node {payload['id']!r}")
        moved = replace(node, x=float(payload["x"]), y=float(payload["y"]))
        self.model = replace(self.model, nodes=tuple(
            moved if n.id == moved.id else n for n in self.model.nodes), origin=("node", moved.id))
        self.rev += 1
        return self.state()

    # -- the one write path

    def _set_payload(self, payload: dict[str, Any], *, relayout: bool = True) -> None:
        self.json = json.dumps(payload, indent=2)
        self.positive, self.negative = prompt_texts(payload["prompt"])
        same = set(payload["prompt"]) == {n.id for n in self.model.nodes}
        self.model = self._notes(payload["prompt"]) if same and not relayout \
            else gm.relayout(self.model, payload["prompt"])
        self.rev += 1

    def _notes(self, prompt: dict[str, Any]) -> gm.GraphModel:
        """The same cards with the text each one shows, so typing keeps the view."""
        nodes = []
        for node in self.model.nodes:
            text = gm.clip_note(prompt.get(node.id) or {})
            nodes.append(node if text == node.note else replace(node, note=text))
        if all(new is old for new, old in zip(nodes, self.model.nodes)):
            return self.model
        return replace(self.model, nodes=tuple(nodes))

    def _read_json(self, text: str) -> None:
        """Keep the text as typed; lay the graph out from it only when it parses."""
        parsed = parse(text)
        if not parsed.ok:
            self.json = text
            self.rev += 1
            return
        previous = parse(self.json)
        kept = parsed.prompt == previous.prompt and parsed.payload == previous.payload
        self._set_payload(parsed.payload, relayout=not kept)
        self._message(["JSON valid"], "ok")

    def _rebuild_now(self, *, quiet: bool = False) -> None:
        try:
            self._set_payload(_from_form(*_snapshot(self.studio)))
        except ValueError as exc:
            if not quiet:
                self._say(f"Refused: {exc}", "warn")

    # -- the status

    def _say(self, text: str, level: str) -> None:
        self._message([text], level)

    def _message(self, lines: list[str], level: str) -> None:
        # The page draws the level. It is quiet on success, because the shell
        # note already carries the action's own words, and loud on a refusal.
        self.status = ("\n".join(lines), "info" if level == "ok" else level)


# -- reading the text


@dataclass(frozen=True)
class Parsed:
    """The editor text read once: the payload, the prompt inside it, and why it failed."""

    text: str
    payload: dict[str, Any] | None
    prompt: dict[str, Any]
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.payload is not None and not self.error


def parse(text: str) -> Parsed:
    raw = (text or "").strip()
    if not raw:
        return Parsed(text, None, {}, "the editor is empty")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return Parsed(text, None, {}, f"JSON invalid at line {exc.lineno}: {exc.msg}")
    if not isinstance(payload, dict):
        return Parsed(text, payload, {}, "the JSON is not an object")
    prompt = payload.get("prompt")
    if not isinstance(prompt, dict):
        return Parsed(text, payload, {}, "the JSON has no prompt object")
    return Parsed(text, payload, prompt)


def empty_payload() -> dict[str, Any]:
    return {"prompt": {}, "convert_output": dict(comfy_import.CONVERT_OUTPUT)}


def with_prompt(payload: dict[str, Any] | None, prompt: dict[str, Any]) -> dict[str, Any]:
    """The payload with a new prompt and its weight refs stamped. Invalid text keeps its shapes."""
    base = dict(payload) if isinstance(payload, dict) else empty_payload()
    base["prompt"] = prompt
    request_json.stamp_weight_refs(base)
    return base


def text_encodes(prompt: dict[str, Any]) -> tuple[str, str]:
    """(positive id, negative id). The roles are the CFG guider's, not the key order's.

    A request with no guider to say which encode is which still has encodes:
    the first one is the positive and the second the negative, the order
    ComfyUI's own editor keeps.
    """
    positive, negative = _linked_encodes(prompt)
    if positive or negative:
        return positive, negative
    encodes = [str(nid) for nid, node in prompt.items()
               if isinstance(node, dict) and str(node.get("class_type")) == "CLIPTextEncode"]
    return (encodes[0] if encodes else ""), (encodes[1] if len(encodes) > 1 else "")


def _linked_encodes(prompt: dict[str, Any]) -> tuple[str, str]:
    positive = negative = ""
    for nid, node in prompt.items():
        if not isinstance(node, dict) or str(node.get("class_type")) != "CLIPTextEncode":
            continue
        role = gm._clip_role(str(nid), prompt)
        if role == 0 and not positive:
            positive = str(nid)
        elif role == 1 and not negative:
            negative = str(nid)
    return positive, negative


def prompt_texts(prompt: dict[str, Any]) -> tuple[str, str]:
    positive, negative = text_encodes(prompt)

    def read(nid: str) -> str:
        node = prompt.get(nid) if nid else None
        return str((node or {}).get("inputs", {}).get("text", "")) if isinstance(node, dict) else ""

    return read(positive), read(negative)


def patch_text(prompt: dict[str, Any], which: str, text: str) -> dict[str, Any]:
    """A copy of the prompt with one CLIP text encode's text replaced. ``which`` is pos or neg."""
    nid = text_encodes(prompt)[0 if which == "pos" else 1]
    if not nid:
        return prompt
    out = json.loads(json.dumps(prompt))
    out[nid].setdefault("inputs", {})["text"] = text
    return out


# -- the rest of the page's own work


def _snapshot(studio: Any) -> tuple[Any, Any]:
    """A copy of the form and its stored profile, away from the studio's own.

    Raises ValueError naming a bad knob when the copy does not describe a
    profile, so a refusal reaches the page before any work is queued.
    """
    form = replace(studio.form)
    form.selected_loras = list(form.selected_loras)
    stored = studio.stored_profile()
    form.profile(stored)
    return form, stored


def _from_form(form: Any, stored: Any) -> dict[str, Any]:
    """The request the form describes, as Generate would build it. Raises ValueError naming a bad knob."""
    profile = form.profile(stored)
    return request_json.build_request(
        prompt_text="",
        graph=profile.graph,
        width=int(profile.width),
        height=int(profile.height),
        steps=int(profile.steps),
        seed=int(profile.seed),
        cfg=profile.cfg,
        selected_ids=list(profile.selected_loras) if profile.use_loras else [],
    )


def _profile(studio: Any) -> Any:
    from salad_studio import profiles

    return profiles.SaladProfile(name=studio.form.name)


def _errors(text: str) -> list[str]:
    """Every reason Generate would refuse this text, as separate lines."""
    parsed = parse(text)
    if not parsed.ok:
        return [parsed.error]
    if not parsed.prompt:
        return ["the request has no nodes"]
    try:
        request_json.config_from_payload(parsed.payload)
    except (ValueError, TypeError) as exc:
        return [f"the request is not a Salad request: {exc}"]
    return []


def _graph_dict(model: gm.GraphModel) -> dict[str, Any]:
    """The pane's model as plain dicts: what a canvas draws, with no widget objects."""
    return {
        "nodes": [
            {
                "id": n.id,
                "class": n.class_type,
                "title": n.title,
                "rect": {"x": n.x, "y": n.y, "w": n.w, "h": n.h},
                "ports": [
                    {"key": p.key, "name": p.name, "kind": p.kind, "color": p.color, "y": p.y}
                    for p in (*n.ins, *n.outs)
                ],
                "rows": [{"key": key, "value": value} for key, value in n.rows],
                "note": n.note,
                "selected": n.id in model.selected,
            }
            for n in model.nodes
        ],
        "edges": [
            {
                "source": e.source,
                "source_key": e.source_key,
                "target": e.target,
                "target_key": e.target_key,
                "color": e.color,
            }
            for e in model.edges
        ],
        "view": {"ox": model.view.ox, "oy": model.view.oy, "scale": model.view.scale},
    }
