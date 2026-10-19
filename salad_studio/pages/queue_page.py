"""Queue: one row per request, read back from the queue itself on every refresh."""
from __future__ import annotations

import time
from typing import Any

import flet as ft

import salad_queue
from salad_studio import flet_theme, flet_widgets as w
from salad_studio.flet_shell import Page

COLUMNS = ("#", "Profile", "State", "Attempts", "Last status", "Reason", "Request", "Finished")
EMPTY_TEXT = "The queue is empty. Press Generate to submit a render."
CANCEL_NOTE = ("Cancel drops a request that has not been submitted yet. A request the "
               "container has already accepted keeps rendering.")


def _finished_label(stamp: Any) -> str:
    try:
        seconds = float(stamp or 0)
    except (TypeError, ValueError):
        return ""
    return time.strftime("%H:%M", time.localtime(seconds)) if seconds > 0 else ""


def request_word(request: Any) -> str:
    """The Request cell: what the body says it renders, in one short phrase."""
    body = request if isinstance(request, dict) else {}
    profile = str(body.get("profile") or "")
    endpoint = str(body.get("endpoint") or "")
    return profile or endpoint or "(request)"


class QueuePage(Page):
    def __init__(self, host: Any) -> None:
        super().__init__("Queue", "One row per request; the container is stopped when it sits idle.",
                         host.colors)
        self.host = host
        self.win = host
        self.keys: list[str] = []
        self.selected_key: str | None = None
        self.summary = ft.Text("", size=12, color=self.colors["muted"])
        self.cancel_note = ft.Text(CANCEL_NOTE, size=12, color=self.colors["muted"], selectable=True)
        self.table_holder = ft.Column(expand=True, scroll=ft.ScrollMode.ALWAYS)
        self.body.content = ft.Column(
            [
                w.row([w.button("Refresh", lambda _e: self.refresh()),
                       w.button("Cancel selected", self.cancel),
                       w.button("Retry selected", self.retry),
                       w.button("Clear finished", self.clear_finished),
                       self.summary]),
                self.table_holder,
                self.cancel_note,
            ],
            spacing=flet_theme.GAP["sm"], expand=True,
        )
        self.refresh()

    def rows(self) -> list[tuple[str, tuple[str, ...]]]:
        queue = self.win.services.gen_queue
        kept = queue.finished()
        finished_at = {int(r.get("id") or 0): r.get("finished_at") for r in kept}
        out: list[tuple[str, tuple[str, ...]]] = []
        live: set[int] = set()
        for job in queue.jobs():
            live.add(int(job.id))
            out.append((
                str(job.id),
                (str(job.id), job.line or "(default)", salad_queue.status_word(job.state),
                 str(job.attempts), str(job.status) if job.status else "", job.reason or "",
                 request_word(job.request), _finished_label(finished_at.get(int(job.id)))),
            ))
        for record in kept:
            rid = int(record.get("id") or 0)
            if rid in live:
                continue
            out.append((
                f"kept-{rid}",
                (str(rid), str(record.get("line") or "(default)"),
                 salad_queue.status_word(str(record.get("state") or "")),
                 str(record.get("attempts") or ""), str(record.get("status") or ""),
                 str(record.get("reason") or ""), request_word(record.get("request")),
                 _finished_label(record.get("finished_at"))),
            ))
        return out

    def refresh(self, _e: Any = None) -> None:
        rows = self.rows()
        self.keys = [key for key, _cells in rows]
        index = self.keys.index(self.selected_key) if self.selected_key in self.keys else None
        self.table_holder.controls = [w.table(COLUMNS, [cells for _k, cells in rows] or
                                              [[""] * len(COLUMNS)], on_row=self.select_row,
                                              selected=index)]
        counts: dict[str, int] = {}
        for job in self.win.services.gen_queue.jobs():
            word = salad_queue.status_word(job.state)
            counts[word] = counts.get(word, 0) + 1
        summary = f"{len(rows)} request(s)"
        pending = self.win.services.gen_queue.pending()
        if pending:
            summary += f", {pending} not finished"
        lines = self.win.services.gen_queue.lines()
        if len(lines) > 1:
            summary += f", {len(lines)} profiles in flight"
        if counts:
            summary += "   " + "   ".join(f"{state}: {n}" for state, n in sorted(counts.items()))
        self.summary.value = summary
        try:
            self.table_holder.update()
            self.summary.update()
        except RuntimeError:
            return

    def select_row(self, index: int) -> None:
        if 0 <= index < len(self.keys):
            self.selected_key = self.keys[index]
            self.refresh()

    def _job(self) -> Any:
        if self.selected_key is None:
            return None
        try:
            return self.win.services.gen_queue.job_by_id(int(self.selected_key))
        except ValueError:
            return None

    def _say(self, text: str) -> None:
        self.cancel_note.value = text
        self.host.note(text, level="info")

    def cancel(self, _e: Any = None) -> None:
        job = self._job()
        if job is None:
            self._say("Queue: select a request first")
            return
        if not job.cancellable:
            self._say(f"Queue: request {job.id} is {job.state} and has already been sent, "
                      "so it cannot be cancelled")
            self.refresh()
            return
        if self.win.services.gen_queue.cancel(job):
            self._say(f"Queue: request {job.id} cancelled before it was submitted")
        else:
            self._say(f"Queue: request {job.id} is {job.state} and has already been sent, "
                      "so it cannot be cancelled")
        self.refresh()

    def retry(self, _e: Any = None) -> None:
        job = self._job()
        if job is None:
            self._say("Queue: select a request first")
            return
        if not job.retryable:
            self._say(f"Queue: request {job.id} cannot be retried ({job.reason or job.state})")
            self.refresh()
            return
        self._say(f"Queue: retrying request {job.id}…")
        queue = self.win.services.gen_queue

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self.host.log("error", f"Queue retry failed: {result}")
            self.refresh()

        self.win.services.background(lambda: queue.retry(job), done)

    def clear_finished(self, _e: Any = None) -> None:
        removed = self.win.services.gen_queue.clear_finished()
        self._say(f"Queue: cleared {removed} finished request(s)")
        self.refresh()
