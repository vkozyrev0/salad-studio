"""One request, from the wire to a page's state and back.

The engine is the only code between HTTP and the controllers. It parses the
request at the boundary, refuses a payload that does not match, runs the action
on the core thread, then returns the page's whole state, the shell state, the
busy map and whatever the action asked the page to show.

A confirm is its own request. The dialog's Yes posts the token the server
issued, and the server restores the action and its arguments from it, so the
Yes button acts on the row that was selected when the dialog opened.
"""
from __future__ import annotations

from typing import Any

from salad_studio.web import actions


class WebEngine:
    def __init__(self, studio: Any) -> None:
        self.studio = studio
        self._building: set[str] = set()
        # Pages it serves state for ask for it through the table, the same way
        # a page asks another page. The table is filled before serving starts.
        studio.controllers.table.action("studio.view", need={"page": str})(self._view_action)

    # -- pages

    def page(self, page_id: str) -> dict[str, Any]:
        return self.studio.core.call(self._page_state, page_id)

    def _view_action(self, payload: dict[str, Any], *, ctx: Any = None) -> Any:
        page = payload["page"]
        controller = self.studio.controllers.get(page)
        return controller.state() if controller is not None else {}

    def handle(self, request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if "confirm" in request:
            token = request.get("confirm")
            if not isinstance(token, str):
                return 400, _refuse("bad_payload", "confirm must be a string")
            return self.studio.core.call(self._confirm, token)
        page = request.get("page")
        action = request.get("action")
        args = request.get("args", {})
        if not isinstance(page, str) or not isinstance(action, str):
            return 400, _refuse("bad_payload", "page and action are required")
        if not isinstance(args, dict):
            return 400, _refuse("bad_payload", "args must be an object")
        return self.studio.core.call(self._act, page, action, args, False)

    # -- on the core thread

    def _page_state(self, page_id: str) -> dict[str, Any]:
        self.studio.open_page(page_id)
        return {
            "ok": True,
            "page": page_id,
            "state": self._state(page_id),
            "shell": self.studio.state_dict(),
            "busy": self._busy(page_id),
        }

    def _act(self, page: str, action: str, args: dict[str, Any], confirmed: bool) -> tuple[int, dict[str, Any]]:
        from salad_studio.web.registry import ActionContext

        key = f"{page}.{action}"
        if self.studio.busy.get(key):
            return 409, {"ok": False, "error": {"kind": "busy", "message": f"{key} is already running"}}
        ctx = ActionContext(self.studio, page, action, args, confirmed=confirmed)
        self.studio.busy[key] = True
        try:
            result = self.studio.controllers.table.call(key, dict(args), ctx=ctx)
        finally:
            if not ctx.is_pending:
                self.studio.busy.pop(key, None)
        if result.error is not None:
            self.studio.say(result.error.message, level="error" if result.error.kind == "failed" else "warn")
            return 200, self._reply(page, ok=False, error=result.error.as_dict(), effects=ctx.effects, pending=ctx.is_pending)
        self._note(ctx)
        reply = self._reply(page, ok=True, effects=ctx.effects, pending=ctx.is_pending)
        if ctx.is_pending:
            reply["id"] = ctx.pending_id
        return 200, reply

    def finish(self, action_id: str, ctx: Any, result: Any) -> None:
        """Complete a background action on the core thread and tell every open stream."""
        key = f"{ctx.page}.{ctx.action}"
        self.studio.busy.pop(key, None)
        outcome = result
        if outcome is not None and callable(ctx.settle):
            # A worker's exception is a value like any other: the done step is
            # the page's one place to say what happened, and it can tell a
            # refusal from a payload better than a transport error can. What it
            # does not handle lands in the error below.
            try:
                ctx.settle(outcome)
                if isinstance(outcome, Exception) and ctx.error is None:
                    # The page reported the failure itself; the reply says so.
                    ctx.error = actions.to_error(outcome).as_dict()
            except Exception as exc:  # noqa: BLE001 - a reporter's failure is shown, not raised
                ctx.error = ctx.error or actions.to_error(exc).as_dict()
                self.studio.services.log("error", f"{key} finished badly: {exc}")
        self._note(ctx)
        reply = self._reply(ctx.page, ok=ctx.error is None, error=ctx.error,
                            effects=ctx.effects, pending=False)
        # The page's state dict is rebuilt per reply, but a dict copied into
        # the reply shares nothing with the controller: this is the state as
        # the event was sent, which is what a test and a replay both read.
        reply["id"] = action_id
        self.studio.hub.publish("action_done", {"id": action_id, "reply": reply})

    def _confirm(self, token: str) -> tuple[int, dict[str, Any]]:
        restored = self.studio.take_confirm(token)
        if restored is None:
            return 409, {"ok": False, "error": {"kind": "spent", "message": "that confirmation is no longer valid"}}
        page, action, args = restored
        return self._act(page, action, args, True)

    def _reply(self, page: str, *, ok: bool, effects: list[dict[str, Any]] | None = None,
               error: dict[str, Any] | None = None, pending: bool = False) -> dict[str, Any]:
        reply: dict[str, Any] = {
            "ok": ok,
            "id": "",
            "page": page,
            "pending": pending,
            "error": "",
            "state": self._state(page),
            "shell": self.studio.state_dict(),
            "busy": self._busy(page),
            "effects": effects or [],
        }
        if error is not None:
            reply["error"] = error["message"]
            reply["errorDetail"] = error
        self.studio.publish()
        return reply

    def _note(self, ctx: Any) -> None:
        if ctx.note_text is not None:
            text, level = ctx.note_text
            self.studio.note(text, level=level)

    def _state(self, page_id: str) -> Any:
        """Build one page's state on the core thread.

        The state is an entry in the action table, so a page that changes
        another page's state asks for that page's state the same way it asks
        for an action. The guard turns two pages that need each other's state
        into one refused entry instead of infinite recursion.
        """
        if page_id in self._building:
            return {"error": f"{page_id} is already being built"}
        self._building.add(page_id)
        try:
            result = self.studio.controllers.table.call("studio.view", {"page": page_id})
            if result.error is not None:
                return {"error": result.error.message}
            return result.data
        except Exception as exc:  # noqa: BLE001 - a page's own failure must not take the reply with it
            return {"error": actions.to_error(exc).message}
        finally:
            self._building.discard(page_id)

    def _busy(self, page_id: str) -> dict[str, bool]:
        prefix = f"{page_id}."
        return {key[len(prefix):]: True for key in self.studio.busy if key.startswith(prefix)}


def _refuse(kind: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"kind": kind, "message": message}}
