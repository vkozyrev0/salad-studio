"""The event stream: what the server tells the page without being asked.

A browser holds one ``GET /api/events`` open and reads server-sent events from
it. An event is a name and a JSON object, which is all Angular's
``EventSource`` needs to push a signal.

Every subscriber has its own bounded queue and its own writer thread. A page
that stops reading (a closed tab, a suspended browser) therefore never blocks
the code producing events: its queue fills and its oldest events drop, which
for this app is right, because each event carries the whole current value
rather than a delta.
"""
from __future__ import annotations

import json
import queue
import threading
from typing import Any


class Subscription:
    """One open event stream, with the queue of events waiting for it."""

    def __init__(self, limit: int = 200) -> None:
        self.ready = threading.Event()
        self._events: queue.Queue[tuple[str, Any] | None] = queue.Queue(maxsize=limit)
        self.closed = False

    def put(self, name: str, data: Any) -> None:
        """Hand one event to this stream, dropping the oldest when it is behind."""
        try:
            self._events.put_nowait((name, data))
        except queue.Full:
            try:
                self._events.get_nowait()
            except queue.Empty:
                pass
            self._events.put_nowait((name, data))
        self.ready.set()

    def close(self) -> None:
        self.closed = True
        try:
            self._events.put_nowait(None)
        except queue.Full:
            pass
        self.ready.set()

    def take(self, timeout: float) -> tuple[str, Any] | None:
        """The next event, or None when none arrives in ``timeout``."""
        try:
            item = self._events.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is None:
            raise StreamEnded
        return item


class StreamEnded(Exception):
    """The stream was closed by the server; the writer stops."""


def frame(name: str, data: Any) -> bytes:
    """One event as the bytes written to the stream, with a comment that keeps the socket warm."""
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


HELLO = b": connected\n\n"


class Hub:
    """Every open stream, and the one call that sends to all of them."""

    def __init__(self) -> None:
        self._subs: set[Subscription] = set()
        self._lock = threading.Lock()
        self.sent = 0

    def subscribe(self) -> Subscription:
        sub = Subscription()
        with self._lock:
            self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            self._subs.discard(sub)
        sub.close()

    def publish(self, name: str, data: Any) -> None:
        """Send one event to every open stream. Safe from any thread."""
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            if not sub.closed:
                sub.put(name, data)
        self.sent += 1

    def count(self) -> int:
        with self._lock:
            return len(self._subs)
