"""Frame dispatch for the Flet UI: one event loop turn, one frame.

Worker threads and Flet event handlers never touch a control. They hand a
callable to the pump, which runs it inside its own frame. A burst of calls
between two frames collapses into one turn, which is what a wheel or a drag
produces. Timers are the loop's own: ``call_later`` for one shot, ``every``
for a repeating one, both cancelled on close.

The loop sleeps on an ``asyncio.Event`` until there is work, so an idle window
costs nothing; a frame is one wake-up and one run of whatever was queued.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

FRAME_S = 1 / 60


def refresh(*controls: Any) -> None:
    """Push controls to the client, or do nothing when they are not on a page yet."""
    for control in controls:
        try:
            control.update()
        except RuntimeError:
            return


class Pump:
    """Runs queued work once per turn. The only code that updates controls."""

    def __init__(self, interval: float = FRAME_S) -> None:
        self.interval = interval
        self._event = asyncio.Event()
        self._jobs: list[tuple[Callable[..., None], tuple, dict]] = []
        self._later: list[tuple[float, int, Callable[..., None], tuple, dict]] = []
        self._repeating: dict[int, tuple[float, Callable[..., None], tuple, dict, float]] = {}
        self._serial = 0
        self._clock: Callable[[], float] = time.monotonic
        self.frames = 0

    def wake(self) -> None:
        self._event.set()

    def schedule(self, fn: Callable[..., None], *args, **kwargs) -> None:
        """Run ``fn`` during the next turn. Safe from an event handler or a worker.

        A worker may call this between turns; the list append is atomic under
        the GIL and the loop swaps the list out before it drains it.
        """
        self._jobs.append((fn, args, kwargs))
        self.wake()

    def call_later(self, ms: float, fn: Callable[..., None], *args, **kwargs) -> int:
        """Run ``fn`` once, no sooner than ``ms`` from now. Returns an id for ``cancel``."""
        self._serial += 1
        self._later.append((self._clock() + ms / 1000, self._serial, fn, args, kwargs))
        self.wake()
        return self._serial

    def every(self, ms: float, fn: Callable[..., None], *args, **kwargs) -> int:
        """Run ``fn`` every ``ms`` until ``cancel``. A slow call is not overlapped."""
        self._serial += 1
        self._repeating[self._serial] = (ms / 1000, fn, args, kwargs, self._clock() + ms / 1000)
        self.wake()
        return self._serial

    def cancel(self, token: int | None) -> None:
        """Drop a pending ``call_later`` or a running ``every``. Unknown ids are ignored."""
        if token is None:
            return
        self._repeating.pop(token, None)
        self._later = [row for row in self._later if row[1] != token]

    def _run_due(self) -> None:
        now = self._clock()
        if self._later:
            due = [row for row in self._later if row[0] <= now]
            if due:
                self._later = [row for row in self._later if row[0] > now]
                for _at, _token, fn, args, kwargs in due:
                    fn(*args, **kwargs)
        for token, (period, fn, args, kwargs, at) in list(self._repeating.items()):
            if at > now:
                continue
            self._repeating[token] = (period, fn, args, kwargs, at + period)
            fn(*args, **kwargs)

    def _next_due(self) -> float | None:
        """Seconds until the soonest timer, or None when none is pending."""
        times = [row[0] for row in self._later]
        times.extend(row[4] for row in self._repeating.values())
        if not times:
            return None
        return max(0.0, min(times) - self._clock())

    async def run(self) -> None:
        while True:
            wait = self._next_due()
            timeout = self.interval if wait is None else min(self.interval, wait)
            try:
                await asyncio.wait_for(self._event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
            self._event.clear()
            self._run_due()
            jobs, self._jobs = self._jobs, []
            for fn, args, kwargs in jobs:
                fn(*args, **kwargs)
            if jobs:
                self.frames += 1
