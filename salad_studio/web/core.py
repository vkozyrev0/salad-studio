"""One thread owns the app's mutable state; everyone else hands it work.

A page action and a timer tick can both want to write the form, the queue
counters or a page's state. The way out of that is not a lock per object: it is
one owner. ``Core`` runs on its own thread and executes everything queued to
it, one item at a time, so every handler is single-threaded by construction.

Two ways in. ``submit`` queues work and returns; a timer, a worker's callback
and an event publisher use it. ``call`` queues work and waits for its result;
an HTTP handler uses it and gets the answer or exception back, exactly as if
the function had run inline.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

TICK_S = 0.02


class Core:
    """The command loop. ``start`` runs it on its own daemon thread."""

    def __init__(self, workers: int = 4) -> None:
        self._queue: list[tuple[Callable[..., Any], tuple, dict, Future | None]] = []
        self._timers: list[tuple[float, int, Callable[..., Any], tuple, dict, float]] = []
        self._repeating: dict[int, tuple[float, Callable[..., Any], tuple, dict, float]] = {}
        self._serial = 0
        self._closing = threading.Event()
        self._work = threading.Condition()
        self._thread: threading.Thread | None = None
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="studio-worker")

    # -- lifetime

    def start(self) -> "Core":
        self._thread = threading.Thread(target=self._run, name="studio-core", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._closing.set()
        with self._work:
            self._work.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.pool.shutdown(wait=False, cancel_futures=True)

    @property
    def ident(self) -> int | None:
        """The core thread's id, for a test that asserts a callback ran on it."""
        return self._thread.ident if self._thread is not None else None

    def on_core(self) -> bool:
        return threading.get_ident() == self.ident

    @property
    def closing(self) -> bool:
        return self._closing.is_set()

    # -- work

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Queue ``fn`` on the core thread. Runs before any clock is checked again."""
        with self._work:
            self._queue.append((fn, args, kwargs, None))
            self._work.notify()

    def call(self, fn: Callable[..., Any], *args: Any, timeout: float = 30.0, **kwargs: Any) -> Any:
        """Run ``fn`` on the core thread and return its result. An exception is re-raised."""
        if self.on_core():
            return fn(*args, **kwargs)
        done: Future = Future()
        with self._work:
            self._queue.append((fn, args, kwargs, done))
            self._work.notify()
        return done.result(timeout=timeout)

    def background(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Run ``work`` on the worker pool, then hand its result or exception to ``done`` on core."""
        def finish(future: Future) -> None:
            try:
                result: Any = future.result()
            except Exception as exc:  # noqa: BLE001 - a worker's failure is shown, not raised
                result = exc
            self.submit(done, result)

        self.pool.submit(work).add_done_callback(finish)

    # -- timers

    def call_later(self, ms: float, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> int:
        self._serial += 1
        with self._work:
            self._timers.append((time.monotonic() + ms / 1000, self._serial, fn, args, kwargs))
            self._work.notify()
        return self._serial

    def every(self, ms: float, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> int:
        self._serial += 1
        with self._work:
            self._repeating[self._serial] = (ms / 1000, fn, args, kwargs, time.monotonic() + ms / 1000)
            self._work.notify()
        return self._serial

    def cancel(self, token: int | None) -> None:
        if token is None:
            return
        with self._work:
            self._repeating.pop(token, None)
            self._timers = [row for row in self._timers if row[1] != token]

    # -- the loop

    def _run(self) -> None:
        while not self._closing.is_set():
            with self._work:
                if not self._queue and not self._has_due():
                    self._work.wait(self._next_wait())
                jobs, self._queue = self._queue, []
            for fn, args, kwargs, done in jobs:
                self._run_one(fn, args, kwargs, done)
            self._run_timers()

    def _run_one(self, fn: Callable[..., Any], args: tuple, kwargs: dict, done: Future | None) -> None:
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - a handler's failure belongs to its caller
            if done is not None:
                done.set_exception(exc)
            else:
                raise
        else:
            if done is not None:
                done.set_result(result)

    def _has_due(self) -> bool:
        now = time.monotonic()
        return any(row[0] <= now for row in self._timers) or any(
            row[4] <= now for row in self._repeating.values())

    def _next_wait(self) -> float:
        times = [row[0] for row in self._timers]
        times.extend(row[4] for row in self._repeating.values())
        if not times:
            return 1.0
        return max(0.0, min(0.25, min(times) - time.monotonic()))

    def _run_timers(self) -> None:
        now = time.monotonic()
        with self._work:
            due = [row for row in self._timers if row[0] <= now]
            if due:
                self._timers = [row for row in self._timers if row[0] > now]
            repeats = [row for row in self._repeating.values() if row[4] <= now]
            for period, fn, args, kwargs, at in repeats:
                for token, value in list(self._repeating.items()):
                    if value[1] is fn and value[4] == at:
                        self._repeating[token] = (period, fn, args, kwargs, at + period)
                        break
        for _at, _token, fn, args, kwargs in due:
            self._run_one(fn, args, kwargs, None)
        for _period, fn, args, kwargs, _at in repeats:
            self._run_one(fn, args, kwargs, None)
