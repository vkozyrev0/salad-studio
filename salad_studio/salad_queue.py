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

:class:`SaladQueue` owns the lines and the retries, and keeps a short record of
the requests that finished: what the Queue page says each row is doing
(:func:`status_word`), and what the user still sees when they come back to the
window (see :data:`FINISHED_RETENTION_S`). The transport and the clock are
injected, so a test drives real retries without sleeping.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import studio_meta
import studio_log

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

# What the Queue page calls each state. A state with no word here is shown as
# it is, so a state this table has not learned yet is visible rather than blank.
STATUS_WORDS = {
    PENDING: "waiting",
    RUNNING: "in progress",
    ACCEPTED: "done",
    FAILED: "failed",
    CANCELLED: "cancelled",
}


def status_word(state: str) -> str:
    """The human word for a job's state, for the Queue page to show.

    Pure and total: a state this table does not know comes back as itself, so
    the page reads a state name it can report instead of an empty cell.
    """
    return STATUS_WORDS.get(state, state)


# Which containers this app has used, and when each last had work. The idle stop
# is the app's job, so the record has to outlive the process: a restart used to
# forget every container it had started, and the idle hour then never arrived.
LEDGER_PATH = Path.home() / ".config" / "salad" / "studio-queue.json"
LEDGER_VERSION = 1
# How long a finished request stays on the Queue page. Hours, not minutes: a
# render takes minutes, and the user comes back to the window afterwards to see
# what just happened, so a row that expired while they were away is the bug.
FINISHED_RETENTION_S = 4 * 3600
# A stop that comes back "no such group" is not retried forever.
GONE_CODES = (404,)

# The container is not available yet: replica still starting, gateway busy, or
# Cloudflare cannot reach the origin. Nothing was accepted, so retrying later
# submits no duplicate.
BUSY_CODES = (502, 503, 520, 521, 522, 523)
# 504 and 524 are NOT busy. Cloudflare returns them after giving up on a job the
# container may still be running, so the next attempt would render it twice;
# classify() reads them as failed, which is what makes them terminal.
MAX_ATTEMPTS = 6
RETRY_SLEEP_S = 8
# One ledger write at a time, process-wide: Windows refuses a replace while a
# concurrent reader or another replace holds the target.
_SAVE_LOCK = threading.Lock()


def load_ledger(path: Path | None) -> dict[str, dict[str, Any]]:
    """The container records: profile to ``{gateway, last_active, started_by_app}``.

    ``last_active`` is epoch seconds. ``started_by_app`` says whether this app
    asked Salad to start that container, which is the only thing that licenses
    stopping it when it idles: Salad does not report who started a container, and
    a record that cannot say so - one written before this field existed, or one
    that says the app did not start it - must be left alone, so the user's own
    container is never shut down under them.

    A missing, unreadable or hand-broken file reads as "no records".
    """
    if path is None:
        return {}
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    rows = data.get("containers") if isinstance(data, dict) else None
    if not isinstance(rows, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, row in rows.items():
        if not isinstance(row, dict):
            continue
        try:
            last = float(row.get("last_active") or 0.0)
        except (TypeError, ValueError):
            last = 0.0
        out[str(name)] = {
            "gateway": str(row.get("gateway") or ""),
            "last_active": last,
            "started_by_app": bool(row.get("started_by_app")),
        }
    return out


def load_finished(path: Path | None) -> list[dict[str, Any]]:
    """The finished-request records the file carries, oldest first.

    A file written before this list existed has none, so an older ledger reads
    as "nothing finished yet" instead of an error, and one unreadable row is
    dropped rather than taking the whole record down with it.
    """
    if path is None:
        return []
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    rows = data.get("finished") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "profile": str(row.get("profile") or ""),
                    "state": str(row.get("state") or ""),
                    "status": int(row.get("status") or 0),
                    "reason": str(row.get("reason") or ""),
                    "finished_at": float(row.get("finished_at") or 0.0),
                }
            )
        except (TypeError, ValueError):
            continue
    return out


def save_ledger(
    path: Path | None,
    records: dict[str, dict[str, Any]],
    finished: list[dict[str, Any]] | None = None,
) -> str:
    """Write the records. Returns ``""``, or why it could not be written.

    ``finished`` is the finished-request history, oldest first. It shares this
    file with the container records because both answer the same question after
    a restart ("what has this app done?"), and one file keeps them in step.
    """
    if path is None:
        return ""
    target = Path(path)
    payload = {
        "version": LEDGER_VERSION,
        "containers": records,
        "finished": list(finished or []),
    }
    try:
        with _SAVE_LOCK:
            target.parent.mkdir(parents=True, exist_ok=True)
            # A fixed ``<name>.tmp`` lets two writers truncate each other's file
            # and then publish the mixture, or fail the second replace outright.
            fd, tmp_name = tempfile.mkstemp(
                prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
                os.replace(tmp_name, target)
            finally:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass
    except OSError as e:
        return str(e)
    return ""


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


def container_down_refusal(profile: str, gateway: str) -> str:
    """The refusal for a group that is not running, shared by the press and the queue.

    The press asks this before it queues anything, and ``ensure_container`` asks
    it again when a request is about to be submitted (the group may have stopped
    since the badge was read). One sentence in both places, so what the user sees
    when they press and what the queue logs are the same words.
    """
    return (
        f"the container for profile {profile!r} ({gateway}) is down: its group is "
        "not running, and this app does not start containers. Start it in the "
        "Salad console, then Generate again."
    )


def request_checksum(request: Any) -> str:
    """A stable digest of a request, so a repeated press can be recognised.

    The request is canonicalised before hashing: dict key order and the
    spacing of a re-serialised payload do not change the digest, so the same
    plate built twice by two code paths compares equal. Anything the JSON
    encoder cannot represent is stringified rather than dropped, which keeps
    two different payloads apart instead of collapsing them onto one digest.
    """
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def reason_of(attempt: Attempt) -> str:
    """Why a failed attempt failed, in the server's own words when it sent any.

    The reason is stored in the ledger and shown on the Queue page, so it is
    redacted here: a Comfy error may quote the LoRA URL it was given, token and
    all, and neither the file nor the page is a place for a secret.
    """
    if attempt.error:
        return studio_log.redact(attempt.error)
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
                    return studio_log.redact(f"HTTP {attempt.status}: {value.strip()[:200]}")
        return studio_log.redact(f"HTTP {attempt.status}: {text[:200]}")
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
    checksum: str = ""
    order: int = 0

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
        ledger_path: Path | None = None,
    ) -> None:
        self.on_log = on_log
        self._sleep = sleep or time.sleep
        # Epoch seconds by default, not a monotonic counter: the ownership record
        # is written to disk and read back by a later process, so its timestamps
        # have to mean the same thing in both.
        self._now = now or time.time
        self.retry_sleep_s = retry_sleep_s
        self.max_attempts = max(1, int(max_attempts))
        # The container handle: is_running / start / stop. None means this queue
        # never touches containers, which is how the headless tests run.
        self.lifecycle = lifecycle
        # None means "read the timeout from the metadata document".
        self._idle_stop_s = idle_stop_s
        self.meta = meta
        # None means "keep the record in memory only".
        self.ledger_path = Path(ledger_path) if ledger_path is not None else None
        self._cond = threading.Condition()
        # Serializes snapshot + write, so a slower older snapshot cannot replace
        # a newer one and drop a record another thread just added.
        self._save_lock = threading.Lock()
        self._lines: dict[str, list[Job]] = {}
        self._jobs: list[Job] = []
        self._next_id = 1
        self._next_order = 0
        # Per profile: the container we own (persisted), its gateway, when its
        # last request finished, and whether this app asked Salad to start it.
        # The idle check reads these and nothing else. They are seeded from the
        # ledger, so a reopened app still knows what to stop - and a record that
        # cannot say this app started the container is not ours, so a container
        # the user started by hand is left running instead of being shut down.
        records = load_ledger(self.ledger_path)
        ours = {name: row for name, row in records.items() if row["started_by_app"]}
        for name, row in sorted(records.items()):
            if not row["started_by_app"]:
                self._log(
                    "info",
                    f"queue: leaving {name} alone; its record does not say this app "
                    "started its container",
                )
        self._owned: set[str] = set(ours)
        self._started_by_app: set[str] = set(ours)
        self._gateways: dict[str, str] = {
            name: row["gateway"] for name, row in ours.items() if row["gateway"]
        }
        self._last_active: dict[str, float] = {
            name: row["last_active"] for name, row in ours.items() if row["last_active"]
        }
        if len(ours) != len(records):
            # Drop the records that are not ours: keeping them would only repeat
            # the line above on every start.
            drop_foreign = True
        else:
            drop_foreign = False
        # The finished-request history, oldest first. Without a ledger it lives
        # only in memory, which is still what the page needs for the session.
        self._finished: list[dict[str, Any]] = load_finished(self.ledger_path)
        # Request ids continue past the recorded ones: a reopened window shows the
        # history it kept, and the next request must not take an id a kept row
        # already owns (the page keys its rows by id, and `_finish` replaces the
        # row for an id, so a reused id would drop a row the user came back for).
        if self._finished:
            self._next_id = 1 + max(
                int(row.get("id") or 0) for row in self._finished
            )
        if records:
            self._log(
                "info",
                f"queue: {len(records)} container record(s) from {self.ledger_path}: "
                + ", ".join(sorted(records)),
            )
        if drop_foreign:
            self._save_ledger()

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
        checksum: str = "",
    ) -> Job:
        """Append a request to its profile's line and return its job.

        ``checksum`` lets a caller that already digested the request pass its
        digest in, so the press and the enqueue agree on the same value; an
        empty one is computed here.
        """
        with self._cond:
            self._next_order += 1
            job = Job(
                id=self._next_id,
                request=request,
                work=work,
                line=str(line),
                checksum=str(checksum) or request_checksum(request),
                order=self._next_order,
            )
            self._next_id += 1
            waiting = self._line_of(job.line)
            waiting.append(job)
            self._jobs.append(job)
            gateway = request_gateway(request)
            if gateway and job.line:
                self._gateways[job.line] = gateway
            self._cond.notify_all()
            ahead = len(waiting) - 1
        # Outside the lock: the log callback can block on the log sink, and the
        # refresh path may be waiting on this same lock.
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
        ensure: bool = True,
        checksum: str = "",
    ) -> Job:
        """Queue ``request`` on its profile's line, wait for its turn, run it.

        ``attempt(job)`` performs one transport attempt and returns an
        :class:`Attempt`; the queue calls it again only while the outcome is
        ``busy``, so the transport sees one call per real POST. ``ensure=False``
        is for a caller that already asked :meth:`ensure_container` and waited
        for readiness itself (the generator does), so one request never asks for
        the same container twice. ``checksum`` is passed on to
        :meth:`enqueue`.
        """
        job = self.enqueue(request, attempt, line=line, checksum=checksum)
        try:
            self._wait_turn(job)
            if job.terminal:
                self._log(
                    "info",
                    f"queue: request {job.id} was cancelled before it was submitted",
                )
                return job
            gateway = request_gateway(job.request)
            if job.line and gateway:
                # Running a request through the queue is what makes this app
                # responsible for stopping that container later, whatever the
                # state read says: an inconclusive read (pending, failed, an API
                # error) must not exempt it for the rest of the session. A vast
                # request carries no gateway; adopting it would make the idle
                # stop try to stop a Salad container that does not exist.
                self.adopt(job.line, gateway)
            refusal = (
                self.ensure_container(job.line, request_gateway(job.request))
                if ensure
                else ""
            )
            if refusal:
                job.state = FAILED
                job.reason = refusal
                self._log("error", f"queue: request {job.id} failed: {refusal}")
                self._finish(job)
                return job
            self._run(job, attempt)
        finally:
            self._release(job)
        self._note_activity(job)
        return job

    # -- container ownership ----------------------------------------------
    def records(self) -> dict[str, dict[str, Any]]:
        """The persisted view: profile to its gateway, last activity and provenance."""
        with self._cond:
            return {
                line: {
                    "gateway": self._gateways.get(line, ""),
                    "last_active": self._last_active.get(line, 0.0),
                    "started_by_app": line in self._started_by_app,
                }
                for line in sorted(self._owned)
            }

    def _save_ledger(self) -> None:
        if self.ledger_path is None:
            return
        with self._save_lock:
            with self._cond:
                records = self.records()
                finished = [dict(row) for row in self._finished]
            reason = save_ledger(self.ledger_path, records, finished)
        if reason:
            self._log("warn", f"queue: could not write {self.ledger_path}: {reason}")

    def adopt(
        self,
        profile: str,
        gateway: str = "",
        *,
        last_active: float | None = None,
        started_by_app: bool = False,
    ) -> bool:
        """Own a container: this app is now the one that stops it when it idles.

        Returns True when that was news. The first adoption starts the idle
        clock; re-adopting an owned container only refreshes its gateway, so a
        check every fifteen seconds cannot keep pushing the stop away.

        ``started_by_app`` records that this app asked Salad to start the
        container, which is the fact the idle stop is licensed by and the one
        that survives a restart. A request dispatched to a container that was
        already running owns it for this session only: the app has used it, so it
        may stop it when it idles, but it did not start it, so a later session
        must not.
        """
        name = str(profile or "").strip()
        if not name:
            return False
        with self._cond:
            fresh = name not in self._owned
            self._owned.add(name)
            if started_by_app:
                self._started_by_app.add(name)
            if gateway:
                self._gateways[name] = str(gateway)
            if fresh or last_active is not None:
                self._last_active[name] = self._now() if last_active is None else float(last_active)
            elif name not in self._last_active:
                self._last_active[name] = self._now()
        if fresh:
            self._log("info", f"queue: {name} is tracked for the idle stop")
            self._save_ledger()
        elif started_by_app:
            self._save_ledger()
        return fresh

    def refresh(self, profile: str, gateway: str = "") -> bool:
        """Follow a container this queue already owns; own nothing new.

        The status probe calls this for every group it finds running. It may only
        refresh what the record already knows - the gateway - because a container
        the user started by hand is not this app's to stop, and probing the
        status of a running group must never be what hands it over.
        """
        name = str(profile or "").strip()
        if not name or name not in self._owned:
            return False
        with self._cond:
            if not gateway or self._gateways.get(name, "") == gateway:
                return False
            self._gateways[name] = str(gateway)
        self._save_ledger()
        return True

    # -- container lifecycle ----------------------------------------------
    def ensure_container(self, profile: str, gateway: str) -> str:
        """Whether ``profile``'s group can take a request. Returns a refusal or "".

        A group that is **not running** is refused, naming the profile and its
        gateway. Starting a container is the user's call, not a side effect of
        pressing Generate: an app that boots a container on its own also runs up
        a bill, and a request aimed at a container the user deliberately stopped
        must not quietly start it. The refusal tells the user to start it in the
        Salad console and press Generate again.

        The state is read **every** time a request is about to be submitted: a
        container that was up earlier in the session may have been stopped since
        (the idle stop, the console, a crash), so an earlier read is not evidence
        that it is still up. A group that is already running is left alone, and
        an inconclusive read (pending, failed, an API error) refuses nothing and
        starts nothing: a request aimed at a group whose state cannot be read is
        still worth trying, and the readiness wait reports what the container
        does.
        """
        name = str(profile or "").strip()
        if self.lifecycle is None or not name or not gateway:
            return ""
        running = self.lifecycle.is_running(name, gateway)
        if running is True:
            return ""
        if running is None:
            self._log(
                "warn",
                f"queue: {name} container state unknown; not starting it",
            )
            return ""
        refusal = container_down_refusal(name, gateway)
        self._log("warn", f"queue: {name} is down; not starting it ({gateway})")
        return refusal

    def group_state(self, profile: str, gateway: str) -> str:
        """The group's raw state ("running", "stopped", "pending", …) or "".

        The readiness wait uses this: a booting replica answers 404 on /ready,
        the same as a running one that has no probe endpoint at all.
        """
        if self.lifecycle is None or not getattr(self.lifecycle, "group_state", None):
            return ""
        try:
            return str(self.lifecycle.group_state(str(profile or ""), str(gateway or "")) or "")
        except Exception:  # noqa: BLE001 - an unreadable state is "", not a crash
            return ""

    def _note_activity(self, job: Job) -> None:
        """Remember when this profile last had a request finish."""
        if not job.line or not job.terminal:
            return
        with self._cond:
            self._last_active[job.line] = self._now()
        self._save_ledger()

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
                for line in sorted(self._owned)
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
            self._forget(line)
            self._log(
                "info",
                f"queue: stopped {line} after {seconds}s idle (HTTP {code})",
            )
            return True
        if code in GONE_CODES:
            # Nothing answers to that gateway any more, so there is nothing to
            # stop and no reason to keep asking.
            self._forget(line)
            self._log(
                "warn",
                f"queue: {line} has no group to stop ({message or f'HTTP {code}'}); "
                "dropping the record",
            )
            return False
        with self._cond:
            # Keep the container on the books but do not hammer the API: the next
            # attempt waits another full timeout.
            self._last_active[line] = self._now()
        self._save_ledger()
        self._log("warn", f"queue: could not stop {line}: HTTP {code} {message}".strip())
        return False

    def _forget(self, line: str) -> None:
        with self._cond:
            self._owned.discard(line)
            self._last_active.pop(line, None)
            self._gateways.pop(line, None)
        self._save_ledger()

    def containers(self) -> dict[str, str]:
        """The profiles whose container this queue owns, and their gateways."""
        with self._cond:
            return {line: self._gateways.get(line, "") for line in sorted(self._owned)}

    # -- finished requests ------------------------------------------------
    def _finish(self, job: Job) -> None:
        """Record a job that has just turned terminal, for the Queue page.

        Called at the transition itself and reading the state off the job, so
        the record cannot disagree with the row the page is showing. A request
        that is retried and ends terminal again replaces its own earlier
        record: the history is one row per request, not one per attempt.
        """
        if not job.terminal:
            return
        record = {
            "id": int(job.id),
            "profile": str(job.line),
            "state": str(job.state),
            "status": int(job.status),
            "reason": str(job.reason),
            "finished_at": float(self._now()),
        }
        with self._cond:
            self._finished = [row for row in self._finished if row["id"] != record["id"]]
            self._finished.append(record)
        self._save_ledger()

    def finished(self) -> list[dict[str, Any]]:
        """The finished requests still inside the window, newest first.

        The window is read against the injected clock, and a record that has
        aged out is pruned from the file as well, so the history cannot grow
        without bound. Only a request that turned terminal is ever recorded, so
        the window can never drop one that has not finished.
        """
        now = self._now()
        with self._cond:
            kept = [
                row
                for row in self._finished
                if now - float(row["finished_at"]) < FINISHED_RETENTION_S
            ]
            dropped = len(kept) != len(self._finished)
            if dropped:
                self._finished = kept
        if dropped:
            self._save_ledger()
        return [dict(row) for row in reversed(kept)]

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
                self._finish(job)
                return
            if action == FAIL:
                if job.outcome == BUSY:
                    # The attempts are spent with the container still busy, so
                    # there is no retry left: fall out for the tail below, which
                    # records why the job gave up. A definitive failure keeps
                    # its own reason and returns here.
                    break
                job.state = FAILED
                job.reason = reason_of(result)
                self._log(
                    "error",
                    f"queue: request {job.id} failed on attempt {number}"
                    f"/{self.max_attempts} ({job.reason})",
                )
                self._finish(job)
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
        self._finish(job)

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
        self._finish(job)
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
            self._next_order += 1
            job.order = self._next_order
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
        """Drop every terminal job from the records, and the finished history.

        This is the page's "Clear finished": the history of what just happened
        describes the rows it goes with, so clearing the rows clears it too.
        Returns how many jobs went.
        """
        with self._cond:
            keep = [job for job in self._jobs if not job.terminal]
            gone = [job for job in self._jobs if job.terminal]
            removed = len(gone)
            known = {job.id for job in gone}
            # A row restored from an earlier session lives only in _finished,
            # so the count the page reports must include it too.
            extra = sum(
                1 for row in self._finished if int(row.get("id", -1)) not in known
            )
            self._jobs = keep
            had_finished = bool(self._finished)
            self._finished = []
        total = removed + extra
        if total:
            self._log("info", f"queue: cleared {total} finished request(s)")
        if had_finished:
            self._save_ledger()
        return total

    def job_by_id(self, job_id: int) -> Job | None:
        with self._cond:
            for job in self._jobs:
                if job.id == int(job_id):
                    return job
        return None

    # -- inspection -------------------------------------------------------
    def head_of(self, line: str = "") -> Job | None:
        """The queue's first item, in queue order, on ``line`` (any line if "").

        A cancelled job is skipped: it never reached a container, so it is not
        a submission a repeat press could duplicate. An accepted or failed row
        still counts, because the question is what the queue's first item is,
        not what state it ended in. None when the line holds nothing.
        """
        name = str(line)
        with self._cond:
            candidates = [
                job
                for job in self._jobs
                if job.state != CANCELLED and (not name or job.line == name)
            ]
            return min(candidates, key=lambda job: job.order, default=None)

    def duplicate_of_head(
        self, request: Any = None, *, line: str = "", checksum: str = ""
    ) -> Job | None:
        """The head of the queue when it carries this same request, else None.

        The press consults this before enqueueing: an identical request sitting
        at the head would be submitted twice back to back, so it is refused.
        Only the head counts. An identical request further down the queue is not
        the head, so the press is allowed: the contract is head-only, and the
        rows behind the head may still be cancelled or retried before they run.
        """
        digest = str(checksum) or (request_checksum(request) if request is not None else "")
        head = self.head_of(line)
        if head is None or not head.checksum or not digest:
            return None
        return head if head.checksum == digest else None

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
