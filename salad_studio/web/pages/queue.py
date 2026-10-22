"""Queue: one row per request, read back from the queue itself on every refresh.

A row's key starts with ``kept-`` when the request is known only from the
finished history (after a restart), because the queue has no ``Job`` for it to
cancel or retry.

The summary is fields, not a sentence with runs of spaces in it: the page
decides how to lay out the counts.
"""
from __future__ import annotations

import time
from typing import Any

import salad_queue

COLUMNS = ("#", "Profile", "State", "Attempts", "Last status", "Reason", "Request", "Finished")
EMPTY_TEXT = "The queue is empty. Press Generate to submit a render."
CANCEL_NOTE = ("Cancel drops a request that has not been submitted yet. A request the "
               "container has already accepted keeps rendering.")


def _retried(queue: Any, job: Any) -> dict[str, Any]:
    """Run one failed job's own work again and report what the attempt did.

    ``SaladQueue.retry`` appends the job to its own line and then waits for its
    turn. The slot it appended is its own, and only the ``finally`` that has not
    run yet takes it away, so a retried ``Job`` waits on itself forever. A
    failed job is on no line, so it runs here and not through ``retry``, and
    the queue keeps the outcome under the job's id: the next state reads it, so
    the row shows what the retry did.
    """
    attempt = job.work
    if attempt is None:
        return {"state": job.state, "status": job.status, "reason": job.reason, "attempts": job.attempts}
    before = job.attempts
    queue._log("info", f"queue: request {job.id} retrying")
    result = salad_queue.as_attempt(attempt(job))
    outcome = salad_queue.classify(result)
    state = salad_queue.ACCEPTED if outcome == salad_queue.OK else salad_queue.FAILED
    reason = "" if state == salad_queue.ACCEPTED else salad_queue.reason_of(result)
    with queue._cond:
        job.state = state
        job.attempts = before + 1
        job.outcome = outcome
        job.status = int(result.status)
        job.accepted = bool(result.accepted)
        job.reason = reason
        job.result = result
    queue._log("ok" if state == salad_queue.ACCEPTED else "error",
               f"queue: request {job.id} {'accepted' if state == salad_queue.ACCEPTED else 'failed'}"
               f" when retried" + (f" ({reason})" if reason else ""))
    return {"state": state, "status": job.status, "reason": reason, "attempts": job.attempts}


def _finished_label(stamp: Any) -> str:
    try:
        seconds = float(stamp or 0)
    except (TypeError, ValueError):
        return ""
    return time.strftime("%H:%M", time.localtime(seconds)) if seconds > 0 else ""


def request_word(request: Any) -> str:
    """The Request cell: what the body says it renders, in one short phrase."""
    body = request if isinstance(request, dict) else {}
    return str(body.get("profile") or body.get("endpoint") or "(request)")


class QueueController:
    page = "queue"

    def __init__(self, studio: Any) -> None:
        self.studio = studio
        self.selected: str | None = None
        self.note = CANCEL_NOTE

    def register(self, table: Any) -> None:
        table.action("queue.view")(self.view)
        table.action("queue.refresh")(self.view)
        table.action("queue.select", need={"key": str})(self.select)
        table.action("queue.cancel")(self.cancel)
        table.action("queue.retry")(self.retry)
        table.action("queue.clear_finished")(self.clear_finished)

    def view(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        return self.state()

    def state(self) -> dict[str, Any]:
        queue = self.studio.services.gen_queue
        rows: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        live: set[int] = set()
        for job in queue.jobs():
            live.add(int(job.id))
            word = salad_queue.status_word(job.state)
            counts[word] = counts.get(word, 0) + 1
            rows.append({
                "key": str(job.id), "id": str(job.id), "profile": job.line or "(default)",
                "state": word, "attempts": str(job.attempts),
                "status": str(job.status) if job.status else "", "reason": job.reason or "",
                "request": request_word(job.request), "finished": "",
                "live": True, "cancellable": job.cancellable, "retryable": job.retryable,
            })
        kept = queue.finished()
        finished_at = {int(record.get("id") or 0): record.get("finished_at") for record in kept}
        for row in rows:
            row["finished"] = _finished_label(finished_at.get(int(row["id"])))
        for record in kept:
            rid = int(record.get("id") or 0)
            if rid in live:
                continue
            state = str(record.get("state") or "")
            counts[salad_queue.status_word(state)] = counts.get(salad_queue.status_word(state), 0) + 1
            rows.append({
                "key": f"kept-{rid}", "id": str(rid), "profile": str(record.get("profile") or "(default)"),
                "state": salad_queue.status_word(state), "attempts": str(record.get("attempts") or ""),
                "status": str(record.get("status") or ""), "reason": str(record.get("reason") or ""),
                "request": request_word(record.get("request")),
                "finished": _finished_label(record.get("finished_at")),
                "live": False, "cancellable": False, "retryable": False,
            })
        selected = next((row for row in rows if row["key"] == self.selected), None)
        return {
            "columns": list(COLUMNS),
            "rows": rows,
            "count": len(rows),
            "empty_text": "" if rows else EMPTY_TEXT,
            "summary": {
                "requests": len(rows),
                "pending": queue.pending(),
                "lines": queue.lines(),
                "states": [{"word": word, "count": n} for word, n in sorted(counts.items())],
            },
            "selected": selected["key"] if selected is not None else None,
            "can_cancel": bool(selected and selected["cancellable"]),
            "can_retry": bool(selected and selected["retryable"]),
            "note": self.note,
        }

    def _row(self, key: str) -> dict[str, Any] | None:
        return next((row for row in self.state()["rows"] if row["key"] == key), None)

    def _job(self) -> Any:
        """The queue's own ``Job`` for the selection; None for a kept row."""
        if not self.selected or not self.selected.isdigit():
            return None
        return self.studio.services.gen_queue.job_by_id(int(self.selected))

    # -- actions

    def select(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        if self._row(payload["key"]) is None:
            ctx.note("Queue: that request is gone; refresh the list", level="warn")
            self.selected = None
            return self.state()
        self.selected = payload["key"]
        return self.state()

    def cancel(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        job = self._job()
        if job is None:
            ctx.note("Queue: select a request first", level="warn")
            return self.state()
        if self.studio.services.gen_queue.cancel(job):
            self.note = f"Request {job.id} was cancelled before it was submitted."
            ctx.note(self.note, level="ok")
        else:
            self.note = (f"Request {job.id} is {salad_queue.status_word(job.state)} and has already "
                         "been sent, so it cannot be cancelled.")
            ctx.note(self.note, level="warn")
        return self.state()

    def retry(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        job = self._job()
        if job is None:
            ctx.note("Queue: select a request first", level="warn")
            return self.state()
        if not job.retryable:
            ctx.note(f"Queue: request {job.id} cannot be retried ({job.reason or job.state})", level="warn")
            return self.state()
        queue = self.studio.services.gen_queue
        jid = int(job.id)

        def work() -> Any:
            return _retried(queue, job)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self.note = f"Retrying request {jid} failed: {result}"
                ctx.note(self.note, level="error")
                ctx.log("error", f"Queue retry failed: {result}")
                return
            state = str((result or {}).get("state") or "")
            word = salad_queue.status_word(state)
            reason = str((result or {}).get("reason") or "")
            self.note = f"Request {jid} was retried: {word}." + (f" {reason}" if reason else "")
            ctx.note(self.note, level="ok" if state == salad_queue.ACCEPTED else "warn")

        self.note = f"Retrying request {jid}…"
        ctx.note(self.note)
        ctx.background(work, done)
        return self.state()

    def clear_finished(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        removed = self.studio.services.gen_queue.clear_finished()
        self.selected = None
        self.note = f"Cleared {removed} finished request(s)."
        ctx.note(self.note)
        return self.state()
