"""The page ids, the action table every page registers into, and the contexts.

A page is a controller with one method per action. The HTTP layer never calls a
controller directly: it calls the table, which runs on the core thread, which
calls the controller. That is the only order in which state stays consistent.

The table lives here rather than in ``actions`` because a controller registers
its actions when it is built, and building one needs the studio. The two
modules would import each other; this one is imported last and owned by the
server.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from salad_studio.web.actions import Registry, to_error, ActionError

PAGE_IDS: tuple[str, ...] = (
    "config", "settings", "tokens", "loras", "editor", "assist",
    "catalog", "import", "history", "queue", "logs",
)
SHELL_ID = "shell"


@dataclass
class ActionContext:
    """What an action may do besides return its page's state."""

    studio: Any
    page: str
    action: str
    args: dict[str, Any]
    confirmed: bool = False
    effects: list[dict[str, Any]] = field(default_factory=list)
    note_text: tuple[str, str] | None = None
    is_pending: bool = False
    settle: Callable[[Any], None] | None = None
    error: dict[str, Any] | None = None
    pending_id: str = ""

    def note(self, text: str, *, level: str = "info") -> None:
        self.note_text = (text, level)

    def say(self, text: str, *, level: str = "error") -> None:
        """A line on the window's status bar, for a failure no page reporter described."""
        self.studio.say(text, level=level)

    def dialog(self, title: str, body: str, *, level: str = "info") -> None:
        self.effects.append({"kind": "dialog", "title": title, "body": body, "level": level})

    def navigate(self, page: str) -> None:
        self.effects.append({"kind": "navigate", "page": page})

    def log(self, level: str, text: str) -> None:
        self.studio.shell.services.log(level, text)

    def background(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Run ``work`` off the core thread, then hand its result to ``done`` on core.

        The page answers at once with ``pending`` and the action's id; when the
        work finishes the server publishes ``action_done`` with the page's new
        state. ``done`` gets the state, because a reporter's note often has to
        name something in it.
        """
        self.is_pending = True
        action_id = self.studio.next_reply_id()
        self.pending_id = action_id

        def finish(result: Any) -> None:
            self.studio.publish_done(action_id, self, result)

        self.settle = done
        self.studio.core.background(work, finish)


class Controllers:
    """One controller per page, built on first open."""

    def __init__(self, studio: Any) -> None:
        self.studio = studio
        self.table = Registry()
        self._built: dict[str, Any] = {}

    def add(self, controller: Any) -> None:
        self._built[controller.page] = controller
        controller.register(self.table)

    def get(self, page_id: str) -> Any:
        return self._built.get(page_id)

    def call(self, page: str, action: str, args: Any, *, confirmed: bool = False) -> Any:
        """The table's name for one page's action, so two pages' ``save`` never collide."""
        return self.table.call(f"{page}.{action}", {"args": args} if args is not None else {}, confirmed=confirmed)

    def names(self) -> tuple[str, ...]:
        return self.table.names()
