"""The page controllers, and the shell's own actions.

A controller is one class per page: ``state()`` for what the page shows, and
one method per action. It never touches another page's state directly; when a
page has to change another, it asks the studio for that page's controller, or
it navigates and lets the page read what changed.

One controller owns each page's state and actions. The page modules live in
``salad_studio/web/pages``; this module holds the shell's own actions and the
tokens page.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# The top-level module, which is the one the page's token code and the dev
# server's isolation both configure. ``salad_studio.tokens`` is a second copy
# with its own path constant; a controller that used it would read a different
# store from the one the rest of the studio writes.
import profiles
import tokens
from salad_studio.web.shell import GenWord

SLOTS: tuple[tuple[str, str], ...] = (
    ("salad", "Salad"),
    ("huggingface", "Hugging Face"),
    ("civitai", "Civitai"),
    ("deepseek", "DeepSeek"),
    ("vast", "Vast.ai"),
)


def _slot_value(kind: str) -> str:
    try:
        return tokens.read_token(kind) or ""
    except (AttributeError, OSError):
        return ""


def _slot_state(kind: str) -> str:
    """The dot's state until a check answers: a stored key is unconfirmed, not valid."""
    return "unknown"


class TokensController:
    page = "tokens"

    def __init__(self, studio: Any) -> None:
        self.studio = studio
        self.states: dict[str, str] = {kind: "unknown" for kind, _label in SLOTS}

    def register(self, table: Any) -> None:
        table.action("tokens.view")(self.view)
        table.action("tokens.save_key", need={"values": dict})(self.save_key)
        table.action("tokens.reveal", need={"id": str})(self.reveal)
        table.action("tokens.check_keys")(self.check_keys)

    def view(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        return self.state()

    def state(self) -> dict[str, Any]:
        slots = []
        for kind, label in SLOTS:
            # One read per slot: read_token seeds the store, and seeding can
            # write the file.
            raw = _slot_value(kind)
            slots.append({
                "id": kind,
                "label": label,
                # The raw key never leaves the process. The page shows the
                # hint and keeps whatever the user types as the new value.
                "value": "",
                "present": bool(raw),
                "hint": tokens.masked(raw),
                "state": self.states.get(kind, "unknown"),
                "tooltip": {"valid": "accepted", "invalid": "rejected"}.get(
                    self.states.get(kind, "unknown"), "unconfirmed"),
            })
        return {"slots": slots}

    # -- actions

    def save_key(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        values = payload["values"]
        if not isinstance(values, dict) or set(values) - dict(SLOTS).keys():
            raise ValueError("values must name known token kinds")
        saved: list[str] = []
        for kind, label in SLOTS:
            if kind not in values:
                continue
            value = str(values[kind] or "").strip()
            if not value:
                continue
            try:
                tokens.write_token(kind, value)
            except OSError as exc:
                ctx.note(f"Could not save the {label} key: {exc}", level="error")
                ctx.dialog("Could not save the key", str(exc), level="error")
                return self.state()
            saved.append(label)
            self.states[kind] = "unknown"
        ctx.note(
            f"Saved {', '.join(saved)}. Check keys confirms each one." if saved
            else "Nothing to save: every field was empty.",
            level="ok" if saved else "warn")
        return self.state()

    def reveal(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        """One row's Show: hand that row's saved key to the page that asked.

        The key travels in this reply only. ``state`` still carries no key, and
        a reveal is not published to the event stream, so no other tab and no
        later page read ever sees it. It writes nothing: reading a key back is
        not saving it.
        """
        kind = payload["id"]
        if kind not in dict(SLOTS):
            ctx.note(f"Refused: {kind!r} is not a provider key", level="warn")
            return self.state()
        raw = _slot_value(kind)
        if not raw:
            ctx.note(f"No {dict(SLOTS)[kind]} key is saved to show.", level="warn")
            return self.state()
        ctx.effects.append({"kind": "reveal", "id": kind, "value": raw})
        ctx.note(f"Showing the {dict(SLOTS)[kind]} key. Hide puts it away.", level="ok")
        return self.state()

    def check_keys(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        # The page checks one provider at a time. A request that names kinds
        # probes only those; no kinds stays the old all-five check. An empty
        # list is a valid "check none", not the same thing as no list.
        requested = payload.get("kinds")
        labels = dict(SLOTS)
        if requested is None:
            wanted = [kind for kind, _label in SLOTS]
        else:
            if not isinstance(requested, list) or any(
                not isinstance(kind, str) or kind not in labels for kind in requested
            ):
                raise ValueError("kinds must be a list of known token kinds")
            wanted = [kind for kind, _label in SLOTS if kind in requested]
        if not wanted:
            ctx.note("No keys selected to check.", level="warn")
            return self.state()
        values = {kind: _slot_value(kind) for kind in wanted}

        def work() -> Any:
            out: dict[str, str] = {}
            for kind, value in values.items():
                try:
                    out[kind] = str(tokens.probe_token(kind, key=value or None).get("state") or "unknown")
                except Exception:  # noqa: BLE001 - a probe never fails the page
                    out[kind] = "unknown"
            return out

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                ctx.note(f"Could not check the keys: {result}", level="error")
                return
            self.states.update(result)
            # The answer belongs to this row, so it rides the reply: the page
            # turns its own dot without waiting for a reload.
            ctx.effects.append({"kind": "token_state", "states": dict(result)})
            if len(wanted) == 1:
                label = labels[wanted[0]]
                word = {"valid": "accepted", "invalid": "rejected"}.get(
                    result.get(wanted[0]), "unconfirmed")
                ctx.note(f"{label} key {word}.", level="warn" if word == "rejected" else "ok")
                return
            bad = [labels[kind] for kind in wanted if result.get(kind) == "invalid"]
            ctx.note("Checked the typed keys" if not bad else f"Rejected: {', '.join(bad)}",
                     level="ok" if not bad else "warn")

        ctx.background(work, done)
        ctx.note(f"Checking the {labels[wanted[0]]} key…" if len(wanted) == 1 else "Checking the keys…")
        return self.state()


class ShellController:
    """Generate, the gallery clean, and the check every page's bar offers.

    Generate reads two pages it does not own: the editor's JSON and the form
    the Settings page writes. It reaches them through the table, so the rule
    that one page never touches another's fields holds here too.
    """

    page = "shell"

    def __init__(self, studio: Any) -> None:
        self.studio = studio
        # The history row this press created, so its plate attaches to that row
        # even when another render finishes first.
        self._render_ts: int | None = None
        self._render_key: str | None = None

    def register(self, table: Any) -> None:
        table.action("shell.view")(self.view)
        table.action("shell.generate")(self.generate)
        table.action("shell.check_salad")(self.check_salad)
        table.action("shell.clean_gallery")(self.clean_gallery)
        table.action("shell.open_plate", need={"name": str})(self.open_plate)

    def view(self, payload: dict[str, Any], *, ctx: Any = None) -> dict[str, Any]:
        return self.state()

    def state(self) -> dict[str, Any]:
        return {}

    # -- actions

    def generate(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        from salad_studio import generator, profiles, prompt_history, salad_queue

        text = self._ask("editor", "text")
        try:
            body = generator.parse_request_json(text)
        except (ValueError, TypeError) as exc:
            return self._refused(ctx, f"Prompt Editor JSON is invalid: {exc}")
        try:
            profile = self.studio.form.profile(self.studio.stored_profile())
        except ValueError as exc:
            return self._refused(ctx, str(exc))
        refusal = self._dispatch_refusal(body, profile)
        if refusal:
            return self._refused(ctx, refusal)
        self.studio.services.log("info", f"Generate  {profile.mode}  {profile.gateway}  graph={profile.graph}")
        entry = None
        try:
            entry = prompt_history.add_request(body, profile=profile.name, gateway=profile.gateway)
        except OSError as exc:
            # The history entry is secondary; a locked file must not stop the render.
            self.studio.services.log("warn", f"history entry skipped: {exc}")
        self._render_ts = int(entry["ts"]) if entry and entry.get("ts") else None
        self._render_key = str(entry.get("key") or "") if entry else None
        self.studio.gen = GenWord(word="Generating", busy=True)
        self.studio.publish()
        self.studio.say("Generating")
        ctx.note(f"Generating on {profile.name}", level="info")
        ctx.background(
            lambda: self.studio.services.generate_sync(
                body, profile, self.studio.services.salad_key(),
                salad_queue.request_checksum(body), ts=self._render_ts,
                history_key=self._render_key),
            lambda outcome: self._generated(ctx, outcome))
        return {}

    def check_salad(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        started = self.studio.services.check_salad()
        if started:
            ctx.note("Checking the Salad gateways")
        else:
            ctx.note("A Salad check is already running. Its result lands in the toolbar counts.",
                     level="warn")
        return {}

    def clean_gallery(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        if not ctx.confirmed:
            ctx.effects.append({
                "kind": "confirm",
                "token": self.studio.issue_confirm("shell", "clean_gallery", {}),
                "title": "Clean the gallery",
                "body": ("This removes the picture from every render in the gallery. "
                         "The renders stay in Prompt History; it cannot be undone."),
            })
            return {}
        removed = self.studio.services.clean_gallery()
        self.studio.refresh_plates()
        ctx.note(f"Removed {removed} plate(s).", level="ok")
        return {}

    def open_plate(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        """A plate is a history row's image, named by that row's key."""
        from salad_studio import prompt_history

        path = prompt_history.image_of(payload["name"])
        if path is None:
            ctx.note("That render's picture is gone from the history.", level="warn")
            return {}
        self.studio.services.open_path(path)
        ctx.note(f"Opened the render from {path.name}", level="info")
        return {}

    # -- helpers

    def _ask(self, page: str, action: str, args: dict[str, Any] | None = None) -> Any:
        """Another page's own read, called on this thread.

        It is a method on the page's controller, not an action: ``editor.text``
        returns the JSON the editor holds, and registering it would put a read
        on the HTTP surface.
        """
        controller = self.studio.controllers.get(page)
        method = getattr(controller, action, None) if controller is not None else None
        if method is None:
            raise ValueError(f"no page method named {page}.{action}")
        return method(args) if args else method()

    def _refused(self, ctx: Any, message: str) -> dict[str, Any]:
        self.studio.services.log("error", f"Generate blocked: {message}")
        ctx.note(f"Refused: {message}", level="error")
        ctx.dialog("Salad Studio", message, level="error")
        return {}

    def _dispatch_refusal(self, body: dict[str, Any], profile: Any) -> str:
        """Why this press cannot be queued at all, in the page's words; "" when it can."""
        import profiles
        import vast

        if profile.mode == "vast":
            gateway = profile.gateway.strip()
            if not gateway:
                return "No vast.ai instance is selected."
            endpoints = {str(row.get("endpoint") or "").strip()
                         for row in (vast.load_doc().get("instances") or [])}
            if gateway not in endpoints and (
                profiles.is_salad_gateway(gateway)
                or any(profiles.same_gateway(p.gateway, gateway)
                       for p in profiles.load_all().values())
            ):
                return ("the Vast.ai target holds a Salad gateway, so the vast key would be "
                        "sent to that group. Pick the instance on the Config page, then "
                        "Generate again.")
            return ""
        route, refusal = profiles.plan_route(body, profile, profiles.load_all())
        if refusal:
            return refusal
        endpoints = {str(row.get("endpoint") or "").strip()
                     for row in (vast.load_doc().get("instances") or [])
                     if str(row.get("endpoint") or "").strip()}
        if route is not None:
            self.studio.services.log(
                "info", f"Routed to profile {route.name!r} (gateway {route.profile.gateway})")
            profile.gateway, profile.name, profile.mode = (
                route.profile.gateway, route.profile.name, route.profile.mode)
        if any(profiles.same_gateway(endpoint, profile.gateway) for endpoint in endpoints):
            return ("the Salad target holds a vast.ai instance URL, so the Salad key would be "
                    "sent to that machine. Pick the Salad gateway on the Config page, then "
                    "Generate again.")
        if not profile.gateway:
            return "the gateway URL is empty"
        if not self.studio.services.salad_key():
            return "no Salad API key is saved"
        return ""

    def _generated(self, ctx: Any, outcome: Any) -> None:
        from salad_studio import prompt_history
        from salad_studio.web.services import GenOutcome

        if not isinstance(outcome, GenOutcome):
            outcome = GenOutcome("failed", message=str(outcome))
        if outcome.kind == "refused":
            ctx.note(f"Refused: {outcome.message}", level="error")
        elif outcome.kind == "failed":
            self.studio.services.log("error", outcome.message)
            ctx.note("Failed. See Logs", level="error")
            ctx.dialog("Salad Studio", outcome.message, level="error")
        else:
            ctx.note(f"Wrote {outcome.out}", level="ok")
            if outcome.out is not None:
                try:
                    prompt_history.attach_image(Path(outcome.out), ts=self._render_ts,
                                                key=self._render_key or "")
                except (OSError, ValueError, TypeError) as exc:
                    self.studio.services.log("warn", f"history thumb skipped: {exc}")
            if outcome.warning:
                self.studio.services.log("warn", f"No background removal: {outcome.warning}")
                ctx.note(f"No background removal: {outcome.warning}", level="warn")
        self._render_ts = None
        self._render_key = None
        self.studio.gen = GenWord()
        self.studio.refresh_plates()
        self.studio.publish()


def install(controllers: Any) -> None:
    """Build every controller. Called once, on the core thread, before serving."""
    controllers.add(ShellController(controllers.studio))
    controllers.add(TokensController(controllers.studio))
