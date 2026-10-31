"""The studio: its shell state, its form, its profile, its pages and its confirms.

The shell is one object on the core thread: the shell state a page or a tick
can change, the form Config and Prompt Settings both edit, the open profile,
the controllers, and the pending confirms. Every shell write publishes an
event, so a status line set by a timer reaches the browser without the page
having asked.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from dataclasses import dataclass, field, replace
from typing import Any

import hostings  # noqa: E402  the top-level module the profile's mode is read from
import profiles
from salad_studio import salad_status
from salad_studio.web.form import Form

REST_TEXT = "Start on Config: pick a profile and its target.   Ctrl+Tab moves between pages."
PLATE_LIMIT = 60
CONFIRM_CAP = 64
LEVELS = ("info", "ok", "warn", "error")


@dataclass(frozen=True)
class Line:
    text: str = ""
    level: str = "info"

    def as_dict(self) -> dict[str, str]:
        return {"text": self.text, "level": self.level}


@dataclass(frozen=True)
class GenWord:
    word: str = "Idle"
    busy: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"word": self.word, "busy": self.busy}


@dataclass
class Shell:
    """The window's own state, owned by the core thread."""

    core: Any
    hub: Any
    services: Any = None
    current: str = "config"
    status: Line = field(default_factory=lambda: Line(REST_TEXT))
    note_line: Line = field(default_factory=Line)
    gen: GenWord = field(default_factory=GenWord)
    salad_word: str = ""
    counts: tuple[int, int, int] = (0, 0, 0)
    plates: tuple[tuple[str, str], ...] = ()
    busy: dict[str, bool] = field(default_factory=dict)
    form: Form = field(default_factory=Form)
    profile: profiles.SaladProfile = field(default_factory=lambda: profiles.SaladProfile(name="klein"))
    controllers: Any = None
    engine: Any = None
    # The server's run token, set once it starts; a plate's URL carries it.
    run_token: str | None = None
    confirms: dict[str, tuple[str, str, dict[str, Any]]] = field(default_factory=dict)
    _ids: int = 0

    @property
    def Studio(self) -> "Shell":
        """The name the controllers and the API use for this object."""
        return self

    @property
    def shell(self) -> "Shell":
        """The engine names this object ``studio`` and its parts ``studio.shell``."""
        return self

    def __post_init__(self) -> None:
        if self.services is None:
            from salad_studio.web import services as services_mod

            self.services = services_mod.WebServices(self)
        self.refresh_plates()

    # -- identity and confirms

    def next_reply_id(self) -> str:
        self._ids += 1
        return f"r{self._ids}"

    def issue_confirm(self, page: str, action: str, args: dict[str, Any]) -> str:
        """A single-use token that names the action a Yes button will run.

        At most ``CONFIRM_CAP`` live: a dialog left open has no expiry, so the
        oldest is evicted rather than letting a session grow the dict forever.
        """
        token = "c_" + secrets.token_hex(8)
        self.confirms[token] = (page, action, dict(args))
        while len(self.confirms) > CONFIRM_CAP:
            self.confirms.pop(next(iter(self.confirms)))
        return token

    def take_confirm(self, token: str) -> tuple[str, str, dict[str, Any]] | None:
        return self.confirms.pop(token, None)

    # -- the profile

    def apply_profile(self, p: profiles.SaladProfile) -> None:
        """Show ``p`` in the form. A target whose URL is a vast.ai instance reads as vast."""
        mode = p.mode if p.mode in hostings.BY_KEY else hostings.DEFAULT
        self.profile = p
        self.form = Form().from_profile(p if mode == p.mode else replace(p, mode=mode))
        self.publish()

    def stored_profile(self) -> profiles.SaladProfile | None:
        """The saved profile the form edits."""
        return profiles.load_all().get(self.form.name)

    # -- pages

    def open_page(self, page_id: str) -> None:
        self.current = page_id
        self.publish()

    # -- the two lines

    def note(self, text: str, *, level: str = "info") -> None:
        """A note is the page's line and the shell's status line at once."""
        line = Line(text, level if level in LEVELS else "info")
        self.note_line = line
        self.status = line
        self.publish()

    def say(self, text: str, *, level: str = "info") -> None:
        """The window's line only: a tick or a Generate writes one without a page owning it."""
        self.status = Line(text, level if level in LEVELS else "info")
        self.publish()

    def message(self, text: str, *, level: str = "info") -> None:
        """Say it and log it. A page's result is both a line and a log entry."""
        self.say(text, level=level)
        self.services.log(level if level in LEVELS else "info", text)

    # -- a finished background action

    def publish_done(self, action_id: str, ctx: Any, result: Any) -> None:
        """A background action finished: answer the page that started it.

        The engine names this object ``studio`` and its parts ``studio.shell``
        (see :attr:`shell`).
        """
        if self.engine is None:
            return
        self.engine.finish(action_id, ctx, result)

    # -- the strip and the counters

    def refresh_plates(self) -> None:
        """The gallery: the newest history entries that have an image.

        A plate used to be a file in one output folder. The history is where a
        render is recorded, image and metadata together, so the gallery reads
        it there and a finished render appears without anything being moved.
        """
        from salad_studio import prompt_history

        plates: list[tuple[str, str]] = []
        for entry in prompt_history.list_prompts():
            image = Path(str(entry.get("image") or ""))
            key = str(entry.get("key") or "")
            if not key or image.suffix.lower() not in (".jpg", ".jpeg", ".png") or not image.is_file():
                continue
            # The page fetches a plate through its HttpClient, whose interceptor
            # sets the token header, so the URL carries nothing extra.
            plates.append((key, f"/api/thumbs/{image.name}"))
            if len(plates) >= PLATE_LIMIT:
                break
        self.plates = tuple(plates)

    def refresh_counts(self) -> None:
        self.counts = salad_status.strip_counts(self.services.snaps)
        self.salad_word = self.services.salad_word

    # -- the wire

    def state(self) -> dict[str, Any]:
        return self.state_dict()

    def state_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "status": self.status.as_dict(),
            "note": self.note_line.as_dict(),
            "gen": self.gen.as_dict(),
            "saladWord": self.salad_word,
            "counts": list(self.counts),
            "plates": [{"name": name, "url": url} for name, url in self.plates],
            "busy": dict(self.busy),
        }

    def publish(self) -> None:
        self.hub.publish("shell", {"shell": self.state_dict()})
