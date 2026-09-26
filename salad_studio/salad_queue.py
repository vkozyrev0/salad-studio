"""The Salad request queue: hold a request while its container is busy.

A container runs one Comfy instance, so requests are serialized **per profile**:
the queue keeps one line per container profile, a request joins the line of the
profile that serves its checkpoint, and a request for another profile runs
beside it instead of waiting. A request the transport reports as "not available
yet" is retried automatically (no second click).

Two decisions, both pure and both tested on their own:

- :func:`classify` reads one attempt as ``ok``, ``busy`` or ``failed``. ``busy``
  means the container is not up yet (502/503/520/521/522/523, or a transport
  that never answered) and returns the request to its line. 504 and 524 are
  **terminal**: Cloudflare gives up at ~100 s while the job is still running, so
  a re-POST submits a *duplicate* render (docs/workflow/21, measured 2026-09-22).
  A request the container already accepted is never re-POSTed at all, so a
  post-acceptance timeout is a failure, not a retry.
- :func:`next_action` says what to do about that outcome on attempt *n*:
  ``accept``, ``retry`` or ``fail``.

:class:`SaladQueue` owns the lines and the retries. The transport and the clock
are injected, so a test drives real retries without sleeping.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import studio_meta

OK = "ok"
BUSY = "busy"
FAILED = "failed"

ACCEPT = "accept"
RETRY = "retry"
FAIL = "fail"

PENDING = "pending"
RUNNING = "running"
ACCEPTED = "accepted"
CANCELLED = "cancelled"

# The container is not available yet: replica still starting, gateway busy, or
# Cloudflare cannot reach the origin. Nothing was accepted, so retrying later
# submits no duplicate.
BUSY_CODES = (502, 503, 520, 521, 522, 523)
# 504 and 524 are NOT busy. Cloudflare returns them after giving up on a job the
# container may still be running, so the next attempt would render it twice.
TERMINAL_CODES = (504, 524)
MAX_ATTEMPTS = 6
RETRY_SLEEP_S = 8


@dataclass(frozen=True)
class Attempt:
    """One transport attempt.

    ``status`` is the HTTP status, or 0 when the transport never answered.
    ``accepted`` is True once the container has taken the job, which is what
    stops a later attempt from submitting it twice. ``error`` says why the
    attempt produced no result, and ``result`` is the caller's payload.
    """

    status: int = 0
    body: bytes | str = b""
    accepted: bool = False
    error: str = ""
    result: Any = None


def classify(attempt: Attempt) -> str:
    """``ok``, ``busy`` or ``failed`` for one attempt.

    An accepted request is never busy: the container has the job, so anything
    short of a clean answer is terminal.
    """
    if attempt.accepted:
        return OK if attempt.status == 200 and not attempt.error else FAILED
    if attempt.status == 200:
        return OK
    if attempt.status == 0 or attempt.status in BUSY_CODES:
        return BUSY
    return FAILED


def next_action(outcome: str, attempt: int, *, max_attempts: int = MAX_ATTEMPTS) -> str:
    """What to do after attempt number ``attempt`` (1-based) produced ``outcome``."""
    if outcome == OK:
        return ACCEPT
    if outcome == BUSY and attempt < max_attempts:
        return RETRY
    return FAIL


def request_gateway(request: Any) -> str:
    """The gateway a queued request will POST to, when the request carries one."""
    if isinstance(request, dict):
        return str(request.get("gateway") or "").strip()
    return ""


def reason_of(attempt: Attempt) -> str:
    """Why a failed attempt failed, in the server's own words when it sent any."""
    if attempt.error:
        return attempt.error
    raw = attempt.body
    text = (
        raw.decode("utf-8", "replace")
        if isinstance(raw, (bytes, bytearray))
        else str(raw or "")
    ).strip()
    if text:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            data = None
        if isinstance(data, dict):
            for key in ("error", "detail", "title", "message"):
                value = data.get(key)
                if isinstance(value, dict):
                    value = value.get("message") or value.get("detail") or value.get("type")
                if isinstance(value, str) and value.strip():
                    return f"HTTP {attempt.status}: {value.strip()[:200]}"
        return f"HTTP {attempt.status}: {text[:200]}"
    return f"HTTP {attempt.status}"


def as_attempt(value: Any) -> Attempt:
    """``value`` read as an :class:`Attempt`.

    A transport that returns ``(status, body)`` is accepted as it is, and so is
    an Attempt built by a second copy of this module, which is what a mixed
    import style produces.
    """
    if isinstance(value, Attempt):
        return value
    if isinstance(value, tuple) and len(value) == 2:
        return Attempt(status=int(value[0]), body=value[1])
    status = getattr(value, "status", None)
    if status is None:
        return Attempt(status=0, error=f"the transport returned {type(value).__name__}")
    return Attempt(
        status=int(status),
        body=getattr(value, "body", b""),
        accepted=bool(getattr(value, "accepted", False)),
        error=str(getattr(value, "error", "") or ""),
        result=getattr(value, "result", None),
    )


@dataclass
class Job:
    """One queued request, the work it was submitted with, and its outcome.

    ``work`` is the attempt callable, kept so a failed job can be retried from
    the queue page without the caller that submitted it. ``line`` is the profile
    whose container serves this request: jobs on different lines run at the same
    time, jobs on one line take turns.
    """

    id: int
    request: Any = None
    state: str = PENDING
    attempts: int = 0
    outcome: str = ""
    status: int = 0
    reason: str = ""
    result: Any = None
    waited_s: float = 0.0
    accepted: bool = False
    work: Callable[[Job], Attempt] | None = None
    line: str = ""

    @property
    def terminal(self) -> bool:
        return self.state in (ACCEPTED, FAILED, CANCELLED)

    @property
    def submitted(self) -> bool:
        """True once the transport has been asked, which is what cancel respects."""
        return self.attempts > 0 or self.accepted

    @property
    def cancellable(self) -> bool:
        """A job that has not been submitted yet can still be dropped."""
        return self.state == PENDING and not self.submitted

    @property
    def retryable(self) -> bool:
        """A failed job can be retried unless the container already took it.

        Re-POSTing an accepted job renders the plate twice, so an accepted
        failure is terminal for good (docs/workflow/21).
        """
        return self.state == FAILED and not self.accepted and self.work is not None


class SaladQueue:
    """One line per container profile: same line takes turns, lines run beside.

    ``send`` is not used directly: the caller passes an ``attempt(job)``
    callable to :meth:`deliver`, which performs one attempt and returns an
    :class:`Attempt`. ``sleep`` and ``now`` are injectable so tests never wait.
    """

    def __init__(
        self,
        *,
        on_log: Callable[[str, str], None] | None = None,
        sleep: Callable[[float], None] | None = None,
        now: Callable[[], float] | None = None,
        retry_sleep_s: float = RETRY_SLEEP_S,
        max_attempts: int = MAX_ATTEMPTS,
        lifecycle: Any | None = None,
        idle_stop_s: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.on_log = on_log
        self._sleep = sleep or time.sleep
        self._now = now or time.monotonic
        self.retry_sleep_s = retry_sleep_s
        self.max_attempts = max(1, int(max_attempts))
        # The container handle: is_running / start / stop. None means this queue
        # never touches containers, which is how the headless tests run.
        self.lifecycle = lifecycle
        # None means "read the timeout from the metadata document".
        self._idle_stop_s = idle_stop_s
        self.meta = meta
        self._cond = threading.Condition()
        self._lines: dict[str, list[Job]] = {}
        self._jobs: list[Job] = []
        self._next_id = 1
        # Per profile: the container we asked for, its gateway, and when its last
        # request finished. The idle check reads these and nothing else.
        self._started: set[str] = set()
        self._gateways: dict[str, str] = {}
        self._last_active: dict[str, float] = {}

    # -- the line ---------------------------------------------------------
    def _log(self, level: str, message: str) -> None:
        if self.on_log is not None:
            try:
                self.on_log(level, message)
            except Exception:  # noqa: BLE001 - a log sink must never break the queue
                pass

    def _line_of(self, line: str) -> list[Job]:
        """The jobs waiting for that profile's container, in submission order."""
        return self._lines.setdefault(line, [])

    def enqueue(
        self,
        request: Any = None,
        work: Callable[[Job], Attempt] | None = None,
        *,
        line: str = "",
    ) -> Job:
        """Append a request to its profile's line and return its job."""
        with self._cond:
            job = Job(id=self._next_id, request=request, work=work, line=str(line))
            self._next_id += 1
            waiting = self._line_of(job.line)
            waiting.append(job)
            self._jobs.append(job)
            gateway = request_gateway(request)
            if gateway and job.line:
                self._gateways[job.line] = gateway
            self._cond.notify_all()
            ahead = len(waiting) - 1
            self._log(
                "info",
                f"queue: request {job.id} queued on {job.line or 'the default line'}"
                + (f" ({ahead} ahead of it)" if ahead else ""),
            )
            return job

    def _wait_turn(self, job: Job) -> None:
        started = self._now()
        with self._cond:
            # A cancelled job is terminal, so the waiter returns instead of
            # waiting for a turn it will never get. Only this job's own line
            # matters: another profile's container is a different container.
            while (
                not job.terminal
                and self._lines.get(job.line)
                and self._lines[job.line][0] is not job
            ):
                self._cond.wait(0.25)
        job.waited_s = max(0.0, self._now() - started)
        if job.waited_s >= 0.05:
            self._log(
                "info",
                f"queue: request {job.id} starting on {job.line or 'the default line'} "
                f"after {job.waited_s:.1f}s",
            )

    def _release(self, job: Job) -> None:
        with self._cond:
            waiting = self._lines.get(job.line)
            if waiting is not None:
                self._lines[job.line] = [queued for queued in waiting if queued is not job]
            self._cond.notify_all()

    # -- running ----------------------------------------------------------
    def deliver(
        self,
        request: Any,
        attempt: Callable[[Job], Attempt],
        *,
        line: str = "",
    ) -> Job:
        """Queue ``request`` on its profile's line, wait for its turn, run it.

        ``attempt(job)`` performs one transport attempt and returns an
        :class:`Attempt`; the queue calls it again only while the outcome is
        ``busy``, so the transport sees one call per real POST.
        """
        job = self.enqueue(request, attempt, line=line)
        try:
            self._wait_turn(job)
            if job.terminal:
                self._log(
                    "info",
                    f"queue: request {job.id} was cancelled before it was submitted",
                )
                return job
            refusal = self._ensure_running(job)
            if refusal:
                job.state = FAILED
                job.reason = refusal
                self._log("error", f"queue: request {job.id} failed: {refusal}")
                return job
            self._run(job, attempt)
        finally:
            self._release(job)
        self._note_activity(job)
        return job

    # -- container lifecycle ----------------------------------------------
    def _ensure_running(self, job: Job) -> str:
        """Ask for this request's container once, before its first attempt.

        Returns ``""`` when the request may go ahead, or the reason it must not:
        a start the control plane rejected. A container that is already running
        is left alone, an unknown state is left alone (starting on a guess could
        double-start), and a profile whose start was already asked for is not
        asked again, however many attempts or retries the request makes.
        """
        if self.lifecycle is None or not job.line or job.line in self._started:
            return ""
        gateway = request_gateway(job.request)
        if not gateway:
            return ""
        running = self.lifecycle.is_running(job.line, gateway)
        if running is True:
            self._started.add(job.line)
            return ""
        if running is None:
            self._log(
                "warn",
                f"queue: {job.line} container state unknown; not starting it",
            )
            return ""
        code, message = self.lifecycle.start(job.line, gateway)
        code = int(code)
        if 200 <= code < 300:
            self._started.add(job.line)
            self._log(
                "info",
                f"queue: asked Salad to start {job.line} (HTTP {code}); the "
                "request waits for it to become ready",
            )
            return ""
        refusal = f"could not start the container for {job.line}: HTTP {code}"
        if message:
            refusal += f" ({message})"
        return refusal

    def _note_activity(self, job: Job) -> None:
        """Remember when this profile last had a request finish."""
        if not job.line or not job.terminal:
            return
        with self._cond:
            self._last_active[job.line] = self._now()

    def idle_timeout_s(self) -> int:
        """The idle-stop timeout: the injected value, else the metadata document."""
        if self._idle_stop_s is not None:
            return int(self._idle_stop_s)
        doc = self.meta if self.meta is not None else studio_meta.default()
        return studio_meta.idle_stop_seconds(doc)

    def idle_check(self) -> list[str]:
        """Stop every profile's container that has been idle past the timeout.

        Returns the profiles it asked Salad to stop. The app's tick calls this,
        and a headless caller calls it directly; the clock and the lifecycle
        client are injected, so neither the timeout nor the call is waited on.
        A profile with a request queued or in flight is never stopped, a stopped
        profile leaves the idle set so a second check cannot stop it twice, and a
        stop the control plane rejects is retried only after another full
        timeout has passed.
        """
        if self.lifecycle is None:
            return []
        seconds = self.idle_timeout_s()
        with self._cond:
            busy = {job.line for job in self._jobs if not job.terminal}
            due = [
                line
                for line in sorted(self._started)
                if line not in busy
                and line in self._last_active
                and self._now() - self._last_active[line] >= seconds
            ]
        stopped: list[str] = []
        for line in due:
            if self._stop_idle(line, seconds):
                stopped.append(line)
        return stopped

    def _stop_idle(self, line: str, seconds: int) -> bool:
        gateway = self._gateways.get(line, "")
        code, message = self.lifecycle.stop(line, gateway)
        code = int(code)
        if 200 <= code < 300:
            with self._cond:
                self._started.discard(line)
                self._last_active.pop(line, None)
            self._log(
                "info",
                f"queue: stopped {line} after {seconds}s idle (HTTP {code})",
            )
            return True
        with self._cond:
            # Keep the container on the books but do not hammer the API: the next
            # attempt waits another full timeout.
            self._last_active[line] = self._now()
        self._log("warn", f"queue: could not stop {line}: HTTP {code} {message}".strip())
        return False

    def containers(self) -> dict[str, str]:
        """The profiles whose container this queue started, and their gateways."""
        with self._cond:
            return {line: self._gateways.get(line, "") for line in sorted(self._started)}

    def _run(self, job: Job, attempt: Callable[[Job], Attempt]) -> None:
        job.state = RUNNING
        for number in range(1, self.max_attempts + 1):
            job.attempts = number
            try:
                result = attempt(job)
            except Exception as e:  # noqa: BLE001 - an attempt that raises did not land
                result = Attempt(status=0, error=f"{type(e).__name__}: {e}")
            result = as_attempt(result)
            job.status = int(result.status)
            job.accepted = bool(result.accepted)
            job.outcome = classify(result)
            job.result = result
            action = next_action(job.outcome, number, max_attempts=self.max_attempts)
            if action == ACCEPT:
                job.state = ACCEPTED
                self._log(
                    "ok",
                    f"queue: request {job.id} accepted on attempt {number}"
                    f"/{self.max_attempts}",
                )
                return
            if action == FAIL:
                job.state = FAILED
                job.reason = reason_of(result)
                self._log(
                    "error",
                    f"queue: request {job.id} failed on attempt {number}"
                    f"/{self.max_attempts} ({job.reason})",
                )
                return
            job.state = PENDING
            self._log(
                "warn",
                f"queue: request {job.id} is waiting for a container "
                f"({result.error or f'HTTP {job.status}'}); retry {number}"
                f"/{self.max_attempts} in {self.retry_sleep_s:g}s",
            )
            self._sleep(self.retry_sleep_s)
        job.state = FAILED
        job.reason = f"gave up after {self.max_attempts} attempts"
        self._log("error", f"queue: request {job.id} {job.reason}")

    # -- management -------------------------------------------------------
    def cancel(self, job: Job) -> bool:
        """Drop a job that has not been submitted yet. True when it was dropped.

        A job the transport has already been asked about is left alone: the
        container may be rendering it, and nothing here can call that back. The
        job becomes terminal, so a caller waiting for its turn returns instead
        of blocking, and its attempt never runs.
        """
        with self._cond:
            if not job.cancellable:
                self._log(
                    "warn",
                    f"queue: request {job.id} cannot be cancelled "
                    f"({job.state}, {job.attempts} attempt(s) already sent)",
                )
                return False
            job.state = CANCELLED
            job.reason = "cancelled before it was submitted"
            waiting = self._lines.get(job.line)
            if waiting is not None:
                self._lines[job.line] = [queued for queued in waiting if queued is not job]
            self._cond.notify_all()
            self._log("info", f"queue: request {job.id} cancelled")
            return True

    def retry(self, job: Job) -> Job:
        """Run a failed job's own work again, on its own profile's line.

        Blocks until the job is terminal again, so the caller reports the new
        outcome; the queue page calls this on a worker thread. Only a failed
        job is retried, and never one the container already accepted.
        """
        if not job.retryable:
            self._log(
                "warn",
                f"queue: request {job.id} cannot be retried ({job.reason or job.state})",
            )
            return job
        with self._cond:
            job.state = PENDING
            job.attempts = 0
            job.outcome = ""
            job.status = 0
            job.reason = ""
            job.result = None
            job.accepted = False
            job.waited_s = 0.0
            self._line_of(job.line).append(job)
            self._cond.notify_all()
            self._log("info", f"queue: request {job.id} retrying")
        try:
            self._wait_turn(job)
            if job.terminal:
                return job
            self._run(job, job.work)
        finally:
            self._release(job)
        self._note_activity(job)
        return job

    def clear_finished(self) -> int:
        """Drop every terminal job from the records. Returns how many went."""
        with self._cond:
            keep = [job for job in self._jobs if not job.terminal]
            removed = len(self._jobs) - len(keep)
            self._jobs = keep
        if removed:
            self._log("info", f"queue: cleared {removed} finished request(s)")
        return removed

    def job_by_id(self, job_id: int) -> Job | None:
        with self._cond:
            for job in self._jobs:
                if job.id == int(job_id):
                    return job
        return None

    # -- inspection -------------------------------------------------------
    def jobs(self) -> list[Job]:
        """Every job this queue has seen, in submission order."""
        with self._cond:
            return list(self._jobs)

    def pending(self) -> int:
        """Jobs queued or running, including the one being delivered."""
        with self._cond:
            return sum(1 for job in self._jobs if not job.terminal)

    def lines(self) -> dict[str, int]:
        """Jobs waiting on each profile's line, by line name (running included)."""
        with self._cond:
            return {line: len(jobs) for line, jobs in self._lines.items() if jobs}

    def busy(self) -> bool:
        with self._cond:
            return any(job.state == RUNNING for job in self._jobs)


_SHARED: SaladQueue | None = None


def shared() -> SaladQueue:
    """The process-wide queue the app and the generator share."""
    global _SHARED
    if _SHARED is None:
        _SHARED = SaladQueue()
    return _SHARED
