"""Frame dispatch for the Flet UI. One loop, one frame per screen refresh.

Worker threads and Flet event handlers never touch a control. They call a
``Channel``, which records the call, and the loop runs it inside its own
frame. A burst of calls between two frames collapses into one repaint, which
is what a wheel or a drag produces.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


def refresh(*controls: Any) -> None:
    """Push controls to the client, or do nothing when they are not on a page yet."""
    for control in controls:
        try:
            control.update()
        except RuntimeError:
            return


class Channel:
    """A one-way hand-off from any thread to the frame loop."""

    def __init__(self, pump: "Pump") -> None:
        self._pump = pump
        self._pending: list[tuple[Callable[..., None], tuple, dict]] = []

    def post(self, fn: Callable[..., None], *args, **kwargs) -> None:
        self._pending.append((fn, args, kwargs))
        self._pump.wake()

    def drain(self) -> None:
        while self._pending:
            fn, args, kwargs = self._pending.pop(0)
            fn(*args, **kwargs)


class Pump:
    """Runs queued work once per frame. The only code that updates controls."""

    def __init__(self, interval: float = 1 / 60) -> None:
        self.interval = interval
        self._event = asyncio.Event()
        self.channel = Channel(self)
        self._jobs: list[tuple[Callable[..., None], tuple, dict]] = []
        self.frames = 0
        self.frame_ms: list[float] = []

    def wake(self) -> None:
        self._event.set()

    def schedule(self, fn: Callable[..., None], *args, **kwargs) -> None:
        """Run ``fn`` during the next frame. Safe to call from an event handler."""
        self._jobs.append((fn, args, kwargs))
        self.wake()

    async def run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._event.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
            self._event.clear()
            self.channel.drain()
            if not self._jobs:
                continue
            jobs, self._jobs = self._jobs, []
            for fn, args, kwargs in jobs:
                fn(*args, **kwargs)
            self.frames += 1
