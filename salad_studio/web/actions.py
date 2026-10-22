"""The action table: every request the page can make, by name.

A request names one action and carries a JSON object. The registry checks the
name and the payload's fields before the handler runs, so a refused request
has touched no store and left no half-written file. What a handler returns is
sent back as ``data``; a handler that raises is turned into an error by
``to_error``.

The table is the whole surface between the page and the stores. A page can do
nothing the table does not name, which is what makes the server's own tests
meaningful: they call the table directly, with no HTTP in the way.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

# What a page shows instead of a raw exception's text. The page reads ``kind``
# and draws a dialog; ``field`` lets a form put the message under the control
# that caused it.
ERROR_KINDS: tuple[str, ...] = ("unknown_action", "bad_payload", "refused", "failed")


class DuplicateAction(RuntimeError):
    """Two handlers registered under one name. A typo, not a runtime condition."""


@dataclass(frozen=True)
class ActionError:
    kind: str
    message: str
    field: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "message": self.message}
        if self.field is not None:
            out["field"] = self.field
        return out


@dataclass(frozen=True)
class ActionResult:
    """One call's answer: its data, or the one error that stopped it."""

    data: Any = None
    error: ActionError | None = None


def _check(name: str, value: Any, kind: type) -> ActionError | None:
    """A field's kind, with ``bool`` kept apart from ``int``.

    ``bool`` is checked first because it is an ``int`` to Python, and a page
    that sends a checkbox where a number belongs has found a real bug.
    """
    if kind is int and isinstance(value, bool):
        return ActionError("bad_payload", f"{name} must be {kind.__name__}, not bool", name)
    if not isinstance(value, kind):
        return ActionError("bad_payload", f"{name} must be {kind.__name__}", name)
    return None


@dataclass
class Registry:
    """Actions by name. Register once at import; the table does not change while serving."""

    _actions: dict[str, tuple[Callable[..., Any], dict[str, type]]] = field(default_factory=dict)

    def action(self, name: str, *, need: Mapping[str, type] | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register ``fn`` under ``name``, requiring ``need``'s fields of its payload."""
        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            if name in self._actions:
                raise DuplicateAction(f"{name} is registered twice")
            self._actions[name] = (fn, dict(need or {}))
            return fn
        return register

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._actions))

    def call(self, name: str, payload: Any, **extra: Any) -> ActionResult:
        """Run one action. ``extra`` reaches the handler as keyword arguments (``confirmed=``)."""
        entry = self._actions.get(name)
        if entry is None:
            return ActionResult(error=ActionError("unknown_action", f"no action named {name}"))
        fn, need = entry
        if not isinstance(payload, dict):
            return ActionResult(error=ActionError("bad_payload", "payload must be an object"))
        clean: dict[str, Any] = {}
        for key, kind in need.items():
            if key not in payload:
                return ActionResult(error=ActionError("bad_payload", f"{key} is required", key))
            bad = _check(key, payload[key], kind)
            if bad is not None:
                return ActionResult(error=bad)
            clean[key] = payload[key]
        try:
            data = fn(clean, **extra) if need else fn(payload, **extra)
        except Exception as exc:  # noqa: BLE001 - a handler's failure is shown to the page, not raised
            return ActionResult(error=to_error(exc))
        return ActionResult(data=data)


def to_error(exc: BaseException) -> ActionError:
    """A handler's exception as the page shows it.

    A refusal the store wrote for a person (``ValueError``) and a file the
    operating system refused keep their text. Anything else is a defect, and
    its text is left in the server's log rather than shown, because it may
    carry a key or a path the page has no business displaying.
    """
    if isinstance(exc, (ValueError, OSError)):
        return ActionError("refused", str(exc))
    detail = f"{type(exc).__name__} while running the action"
    if os.environ.get("SALAD_STUDIO_DEBUG") == "1":
        # A defect's own text names the cause, which shortens a live port's
        # debugging to one glance. SALAD_STUDIO_DEBUG turns it on.
        detail = f"{detail}: {exc}"
    return ActionError("failed", detail)
