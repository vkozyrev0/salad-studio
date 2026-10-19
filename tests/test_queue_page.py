"""The Queue page: it renders the queue's own records, and its controls act on them.

The page is built against a fake host that carries a real ``SaladQueue`` on
its own ledger, so every assertion reads the rendered table back and compares
it with the queue. A click is delivered the way Flet delivers one: the
handler is called with an event ``control``, and ``page.update`` records the
repaint instead of sending it. The page draws no empty-state text of its own; a fresh
queue is read back as its empty sentence in the table and its "0 request(s)"
summary.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (HERE / ".." / "salad_studio", HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import flet as ft  # noqa: E402

import salad_queue as q  # noqa: E402
from salad_studio import flet_theme  # noqa: E402
from salad_studio.pages.queue_page import COLUMNS, EMPTY_TEXT, CANCEL_NOTE, QueuePage  # noqa: E402

def _read_finished() -> list[dict]:
    return json.loads(Path(q.LEDGER_PATH).read_text(encoding="utf-8")).get("finished") or []


def _write_finished(rows: list[dict]) -> None:
    path = Path(q.LEDGER_PATH)
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "containers": {}}
    doc["finished"] = rows
    path.write_text(json.dumps(doc), encoding="utf-8")


class FakePage:
    """The page object a control reaches through: no client, nothing is sent."""

    def __init__(self) -> None:
        self.controls: list = []
        self.sent = 0

    def add(self, *controls) -> None:
        self.controls.extend(controls)

    def update(self, *controls) -> None:
        self.sent += 1


class FakeHost:
    """What the page reaches on the window: the queue, the note, the log."""

    def __init__(self, queue: q.SaladQueue, colors: dict[str, str]) -> None:
        self.services = type("Services", (), {"gen_queue": queue})()
        self.colors = colors
        self.notes: list[tuple[str, str]] = []
        self.logs: list[tuple[str, str]] = []
        self.dialogs: list[tuple[str, str, str]] = []

    def note(self, text: str, *, level: str = "info") -> None:
        self.notes.append((level, text))

    def log(self, level: str, text: str) -> None:
        self.logs.append((level, text))

    def dialog(self, title: str, body: str, *, level: str = "info") -> None:
        self.dialogs.append((level, title, body))

    @property
    def last_note(self) -> str:
        return self.notes[-1][1] if self.notes else ""

    def button(self, label: str) -> ft.Control:
        """The page's control labelled ``label``, found by its own fields."""
        for control in self.buttons.controls:
            shown = [getattr(control, "text", None), getattr(control, "label", None)]
            # flet 1.0.4 keeps a button's label in its first positional slot.
            content = vars(control).get("_values", {}).get("content")
            shown.append(content if isinstance(content, str) else getattr(content, "value", None))
            if label in [word for word in shown if isinstance(word, str)]:
                return control
        raise AssertionError(f"no control labelled {label!r}")

    def click(self, label: str) -> None:
        self.button(label).on_click(None)


class QueuePageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_ledger = q.LEDGER_PATH
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        q.LEDGER_PATH = Path(self._td.name) / "studio-queue.json"
        self.addCleanup(setattr, q, "LEDGER_PATH", self._saved_ledger)
        self.page = FakePage()
        self.host = FakeHost(q.SaladQueue(ledger_path=q.LEDGER_PATH, sleep=lambda _s: None),
                             flet_theme.canvas_colors(True))
        self.host.page = self.page
        self.page.add(self.host)
        self.queue_page = QueuePage(self.host)
        # The page's own control tree, which ``ft.Page.controls`` copies away.
        self.host.buttons = self.queue_page.body.content.controls[0]

    @property
    def queue(self) -> q.SaladQueue:
        return self.host.services.gen_queue

    def open_page(self) -> None:
        self.page.update()
        self.queue_page.refresh()

    def table(self) -> ft.DataTable:
        holder = self.queue_page.table_holder
        self.assertEqual(len(holder.controls), 1, "the page draws exactly one table")
        return holder.controls[0]

    def column_names(self) -> list[str]:
        return [str(c.label.value) for c in self.table().columns]

    def rows(self) -> list[tuple[str, ...]]:
        """Every drawn row's cells; the blank row a fresh page draws reads as eight empty cells."""
        return [tuple(str(c.content.value) for c in row.cells) for row in self.table().rows]

    def row_texts(self) -> list[tuple[str, ...]]:
        return [cells for cells in self.rows() if any(cells)]

    def row(self, job_id: int | str) -> tuple[str, ...]:
        for cells in self.row_texts():
            if cells[0] == str(job_id):
                return cells
        self.fail(f"no row for request {job_id}")

    def state_of(self, job_id: int) -> str:
        """The state word the page shows for that request, or "" when it has no row."""
        for cells in self.row_texts():
            if cells[0] == str(job_id):
                return cells[self.column_names().index("State")]
        return ""

    def row_index(self, job_id: int | str) -> int:
        """The table index of the row for ``job_id``, a kept row included.

        A kept row is keyed ``kept-<id>``, so the page's keys are what find it.
        """
        keys = self.queue_page.keys
        if job_id in keys:
            return keys.index(job_id)
        for index, cells in enumerate(self.rows()):
            if cells[0] == str(job_id):
                return index
        self.fail(f"no row for request {job_id}")

    def select(self, job_id: int | str, page: QueuePage | None = None) -> None:
        """Click the row: its first cell forwards the click to the page's row handler.

        The cell carries its handler in flet's positional slots. A kept row is
        addressed by its own key, ``kept-<id>``.
        """
        page = page or self.queue_page
        table = page.table_holder.controls[0]
        keys = page.keys
        index = keys.index(job_id) if job_id in keys else self.row_index(job_id)
        cell = table.rows[index].cells[0]
        on_tap = vars(cell).get("_values", {}).get("on_tap") or cell.on_tap
        self.assertTrue(callable(on_tap), "a row must answer a click")
        on_tap(None)

    def _finish(self, job_id: int, outcome: q.Attempt, line: str) -> q.Job:
        """Run one request through its line on a worker and wait for the end.

        A line takes turns, so a second request on the same line waits for the
        first to end. That is the queue's contract, and a test that did not
        thread would wait on its own first request forever.
        """
        done = threading.Event()
        job = self.queue.enqueue(
            {"id": job_id, "url": "https://gw.example/prompt", "bytes": 12, "profile": line},
            lambda _job: outcome,
            line=line,
        )

        def wait() -> None:
            self.queue._wait_turn(job)
            try:
                if not job.terminal:
                    self.queue._run(job, job.work)
                    self.queue._note_activity(job)
            finally:
                self.queue._release(job)
                done.set()

        threading.Thread(target=wait, daemon=True).start()
        self.assertTrue(done.wait(15), f"request {job_id} never finished")
        return job

    def accept(self, job_id: int = 1, line: str = ""):
        return self._finish(job_id, q.Attempt(status=200, accepted=True, result="plate"), line)

    def fail(self, job_id: int = 2, message: str = "bad graph", line: str = ""):
        body = json.dumps({"error": {"message": message}}).encode()
        return self._finish(job_id, q.Attempt(status=400, body=body), line)

    # -- rendering --------------------------------------------------------
    def test_a_fresh_queue_shows_the_empty_state(self) -> None:
        self.open_page()
        self.assertEqual(self.row_texts(), [], "no request, no row")
        self.assertEqual(EMPTY_TEXT, "The queue is empty. Press Generate to submit a render.")
        self.assertIn("0 request", self.queue_page.summary.value)

        self.accept()
        self.queue_page.refresh()
        self.assertEqual([cells[0] for cells in self.rows()], ["1"], "the row replaces the empty state")

    def test_the_columns_are_the_eight_the_page_promises_in_order(self) -> None:
        self.assertEqual(list(COLUMNS), ["#", "Profile", "State", "Attempts", "Last status",
                                         "Reason", "Request", "Finished"])
        self.accept(1)
        self.open_page()
        self.assertEqual(self.column_names(), list(COLUMNS))
        for cells in self.rows():
            self.assertEqual(len(cells), len(COLUMNS), f"a row is short: {cells}")

    def test_the_page_renders_each_job_from_the_queues_records(self) -> None:
        self.accept(1, line="klein5090")
        self.fail(2, message="invalid graph node 94", line="klein")
        self.queue.enqueue({"id": 3, "url": "https://gw.example/prompt", "bytes": 12})
        self.open_page()

        cols = self.column_names()
        self.assertEqual(cols, list(COLUMNS))
        done, failed, waiting = self.row(1), self.row(2), self.row(3)
        self.assertEqual(done[cols.index("State")], q.status_word(q.ACCEPTED))
        self.assertEqual(failed[cols.index("State")], q.status_word(q.FAILED))
        self.assertEqual(waiting[cols.index("State")], q.status_word(q.PENDING))
        self.assertEqual(failed[cols.index("Last status")], "400", "the last status must be on the row")
        self.assertIn("invalid graph node 94", failed[cols.index("Reason")])
        self.assertEqual(failed[cols.index("Attempts")], "1", "the attempt count must be on the row")
        self.assertEqual(failed[cols.index("Request")], "klein",
                         "the Request cell names what it renders")
        self.assertEqual(done[cols.index("Profile")], "klein5090",
                         "the row carries the profile it dispatches to")
        self.assertEqual(failed[cols.index("Profile")], "klein")
        self.assertEqual(waiting[cols.index("Profile")], "(default)")

        recorded = {str(job.id): q.status_word(job.state) for job in self.queue.jobs()}
        self.assertEqual({cells[0]: cells[2] for cells in self.rows()}, recorded)
        self.assertIn("failed: 1", self.queue_page.summary.value)
        self.assertIn("done: 1", self.queue_page.summary.value)

    def test_the_row_word_follows_the_request_through_its_stages(self) -> None:
        self.open_page()
        waiting = self.queue.enqueue(
            {"id": 9, "url": "https://gw.example/prompt", "bytes": 12, "profile": "klein"},
            lambda _job: q.Attempt(status=200, accepted=True),
            line="klein",
        )
        self.queue_page.refresh()
        self.assertEqual(self.state_of(waiting.id), "waiting", "queued, not submitted yet")

        started = threading.Event()
        held = threading.Event()

        def attempt(_job):
            started.set()
            held.wait(20)
            return q.Attempt(status=200, accepted=True, result="plate")

        runner = threading.Thread(
            target=lambda: self.queue.deliver(
                {"id": 10, "url": "https://gw.example/prompt", "bytes": 12, "profile": "klein5090"},
                attempt,
                line="klein5090",
            ),
            daemon=True,
        )
        runner.start()
        self.assertTrue(started.wait(20), "the request never reached its attempt")
        submitted = self.queue.jobs()[-1]
        self.queue_page.refresh()
        self.assertEqual(self.state_of(submitted.id), "in progress", "submitted and running")
        held.set()
        runner.join(20)
        self.queue_page.refresh()
        self.assertEqual(self.state_of(submitted.id), "done", "accepted")

        self.fail(11)
        self.queue_page.refresh()
        self.assertEqual(self.state_of(11), "failed")
        self.queue.cancel(waiting)
        self.queue_page.refresh()
        self.assertEqual(self.state_of(waiting.id), "cancelled")

    def test_a_finished_request_survives_a_reopen_and_drops_when_aged_out(self) -> None:
        job_id = self.accept(1, line="klein").id
        self.open_page()
        self.assertEqual(self.state_of(job_id), q.status_word(q.ACCEPTED))
        self.assertEqual(sorted(r["id"] for r in _read_finished()), [job_id])

        # A second page on the same ledger is what a restart looks like.
        other_host = FakeHost(q.SaladQueue(ledger_path=q.LEDGER_PATH), self.host.colors)
        other = QueuePage(other_host)
        rows = [cells[0] for cells in self.rows_of(other)]
        self.assertEqual(rows, ["1"], "the finished row must survive a reopen")
        cells = self.rows_of(other)[0]
        cols = [str(column.label.value) for column in other.table_holder.controls[0].columns]
        self.assertEqual(cells[cols.index("State")], q.status_word(q.ACCEPTED), "still shown as done")
        self.assertTrue(cells[cols.index("Finished")], "with the time it finished")

        # Age it past the retention window.
        kept = _read_finished()
        kept[0]["finished_at"] = time.time() - q.FINISHED_RETENTION_S - 60
        _write_finished(kept)
        aged_host = FakeHost(q.SaladQueue(ledger_path=q.LEDGER_PATH), self.host.colors)
        aged = QueuePage(aged_host)
        self.assertEqual(self.rows_of(aged), [], "a row older than the window must drop off")
        unfinished = aged_host.services.gen_queue.enqueue(
            {"id": 2, "url": "https://gw.example/prompt", "bytes": 12, "profile": "klein"}
        )
        aged.refresh()
        rows = self.rows_of(aged)
        self.assertEqual([cells[0] for cells in rows], [str(unfinished.id)])
        self.assertEqual(rows[0][-2], q.status_word(q.PENDING),
                         "an unfinished request is never dropped by the window")

    def rows_of(self, page: QueuePage) -> list[tuple[str, ...]]:
        return [tuple(str(c.content.value) for c in row.cells) for row in page.table_holder.controls[0].rows
                if any(str(c.content.value) for c in row.cells)]

    # -- the controls -----------------------------------------------------
    def test_cancel_drops_a_request_that_was_never_submitted(self) -> None:
        calls: list[int] = []
        queued = self.queue.enqueue(
            {"id": 1, "url": "https://gw.example/prompt", "bytes": 12},
            lambda _job: calls.append(1) or q.Attempt(status=200),
        )
        self.open_page()
        self.select(1)
        self.host.click("Cancel selected")

        self.assertEqual(queued.state, q.CANCELLED)
        self.assertTrue(queued.terminal)
        self.assertEqual(queued.attempts, 0)
        self.assertEqual(calls, [], "the transport must never run a cancelled request")
        self.assertEqual(self.state_of(1), q.status_word(q.CANCELLED), "the row must follow the queue")
        self.assertEqual(self.host.last_note,
                         "Queue: request 1 cancelled before it was submitted")
        self.assertEqual(self.queue_page.note.value, self.host.last_note, "the page says it too")

    def test_cancel_refuses_a_request_already_sent_and_says_why(self) -> None:
        self.accept(1)
        self.open_page()
        self.select(1)
        self.host.click("Cancel selected")
        self.assertIn("already been sent", self.host.last_note)
        self.assertIn("cannot be cancelled", self.host.last_note)
        self.assertEqual(self.state_of(1), q.status_word(q.ACCEPTED), "the done row stays done")

    def test_retry_runs_a_failed_request_and_runs_it_off_the_page_thread(self) -> None:
        calls: list[int] = []
        entered = threading.Event()
        release = threading.Event()

        def transport(_request):
            calls.append(1)
            if len(calls) == 1:
                return q.Attempt(status=400, body=b'{"error": {"message": "first reason"}}')
            entered.set()
            release.wait(timeout=15)
            return q.Attempt(status=200, accepted=True, result="plate")

        failed = self.queue.deliver({"id": 1, "url": "https://gw/prompt", "bytes": 3}, transport)
        self.assertEqual(failed.state, q.FAILED)
        self.open_page()

        # The page's retry is handed to the window, which starts the work off
        # the page thread. Here the window is one worker thread, as it is in
        # this test's process, so the page never blocks on the render.
        worker: list[threading.Thread] = []

        def background(work, done):
            thread = threading.Thread(target=lambda: done(work()), daemon=True)
            worker.append(thread)
            thread.start()

        self.host.services.background = background
        self.select(1)
        self.host.click("Retry selected")
        self.assertIn("retrying request 1", self.host.last_note)

        self.assertTrue(entered.wait(timeout=10), "the retry never reached the transport")
        self.queue_page.refresh()
        self.assertEqual(self.state_of(1), q.status_word(q.RUNNING),
                         "the row shows the live retry, not the old failure")
        self.assertTrue(self.table().rows[self.row_index(1)].selected, "the retried row stays selected")

        release.set()
        for thread in worker:
            thread.join(15)
        self.assertEqual(failed.state, q.ACCEPTED)
        self.assertEqual(len(calls), 2, "the retry must ask the transport again")
        self.assertEqual(self.state_of(1), q.status_word(q.ACCEPTED))

    def test_retry_refuses_a_request_that_cannot_be_retried(self) -> None:
        self.accept(1)
        self.open_page()
        self.select(1)
        self.host.click("Retry selected")
        self.assertIn("cannot be retried", self.host.last_note)
        self.assertEqual(self.state_of(1), q.status_word(q.ACCEPTED))

    def test_clear_finished_drops_the_finished_rows(self) -> None:
        self.accept(1)
        self.fail(2)
        self.queue.enqueue({"id": 3, "url": "https://gw.example/prompt", "bytes": 12})
        self.open_page()
        self.assertEqual(len(self.table().rows), 3)
        self.host.click("Clear finished")
        self.assertEqual([job.id for job in self.queue.jobs()], [3], "only the waiting row survives")
        self.assertEqual([cells[0] for cells in self.rows()], ["3"], "the waiting row stays")
        self.assertIn("cleared 2", self.host.last_note)

    def test_a_control_with_nothing_selected_says_so(self) -> None:
        self.accept(1)
        self.open_page()
        self.host.click("Cancel selected")
        self.assertEqual(self.host.last_note, "Queue: select a request first")
        self.host.click("Retry selected")
        self.assertEqual(self.host.last_note, "Queue: select a request first")
        self.assertEqual(self.state_of(1), q.status_word(q.ACCEPTED), "nothing was touched")

    def test_a_kept_row_is_answered_without_a_job_behind_it(self) -> None:
        """A row kept from an earlier session has an id but no job in this window.

        The kept record is the one request 1 left on the ledger, and a second
        page on that ledger is the window that opened after a restart.
        """
        job_id = self.accept(1).id
        other_host = FakeHost(q.SaladQueue(ledger_path=q.LEDGER_PATH), self.host.colors)
        other_host.buttons = ft.Row()
        other = QueuePage(other_host)
        other_host.buttons = other.body.content.controls[0]
        rows = self.rows_of(other)
        self.assertEqual([cells[0] for cells in rows], [str(job_id)], "the kept row is on the page")

        other_keys = other.keys
        self.assertEqual(other_keys, [f"kept-{job_id}"], "a kept row is keyed by its own key")
        self.select(f"kept-{job_id}", page=other)
        other_host.click("Cancel selected")
        self.assertEqual(other_host.last_note, "Queue: select a request first")
        other_host.click("Retry selected")
        self.assertEqual(other_host.last_note, "Queue: select a request first")
        self.assertEqual([cells[0] for cells in self.rows_of(other)], [str(job_id)],
                         "and it stays on the page")

    def test_refresh_reads_the_queue_again(self) -> None:
        self.open_page()
        self.assertEqual(self.row_texts(), [], "the empty table draws no request")
        queued = self.queue.enqueue({"id": 5, "url": "https://gw.example/prompt", "bytes": 12})
        self.assertEqual(len(self.row_texts()), 0, "the page does not change until it refreshes")
        self.host.click("Refresh")
        self.assertEqual([cells[0] for cells in self.row_texts()], [str(queued.id)])

    def test_the_page_summarises_without_a_client(self) -> None:
        self.accept(1)
        self.open_page()
        self.assertIsInstance(self.queue_page, ft.Control)
        self.assertIn(CANCEL_NOTE, self.queue_page.note.value)
        self.assertNotIn("profiles in flight", self.queue_page.summary.value,
                         "one profile is not two in flight")


if __name__ == "__main__":
    unittest.main()
