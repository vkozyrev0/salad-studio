"""The Queue page: it renders the queue's own records, and its controls act on them.

The page holds no job state of its own, so every assertion here reads the
rendered rows back and then compares them with ``app.gen_queue.jobs()``. The
window is built hidden and never mapped, the way the rest of the Tk suite does
it; requested geometry stands in for the on-screen size of an unmapped window.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import salad_queue as q  # noqa: E402
from salad_studio import profiles  # noqa: E402
from salad_studio.test_launch import _TempPaths  # noqa: E402

try:
    import tkinter as tk
except ImportError as _tk_err:
    tk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = _tk_err
else:
    _TK_IMPORT_ERROR = None


def _pump(app, predicate, seconds: float = 15.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        app.update()
        time.sleep(0.02)
    return predicate()


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class QueuePage(unittest.TestCase):
    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.app.update_idletasks()

    def _accept(self, job_id: int = 1, line: str = ""):
        return self.app.gen_queue.deliver(
            {"id": job_id, "url": "https://gw.example/prompt", "bytes": 12, "profile": line},
            lambda _job: q.Attempt(status=200, accepted=True, result="plate"),
            line=line,
        )

    def _fail(self, job_id: int = 2, message: str = "bad graph", line: str = ""):
        body = json.dumps({"error": {"message": message}}).encode()
        return self.app.gen_queue.deliver(
            {"id": job_id, "url": "https://gw.example/prompt", "bytes": 12, "profile": line},
            lambda _job: q.Attempt(status=400, body=body),
            line=line,
        )

    def _row(self, job_id: int) -> tuple[str, ...]:
        item = str(job_id)
        self.assertTrue(self.app.queue_tree.exists(item), f"no row for job {job_id}")
        return tuple(str(v) for v in self.app.queue_tree.item(item, "values"))

    def _row_state(self, job_id: int) -> str:
        """The state the page is showing for a job, or "" when it has no row yet."""
        item = str(job_id)
        if not self.app.queue_tree.exists(item):
            return ""
        return str(self.app.queue_tree.item(item, "values")[2])

    def _pump_state(self, job_id: int, want: str, seconds: float = 15.0) -> None:
        """Refresh the page until it shows ``want`` for that job."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.app._refresh_queue_page()
            if self._row_state(job_id) == want:
                return
            self.app.update()
            time.sleep(0.02)
        self.fail(f"the page never showed {want!r} for request {job_id}")

    def _open_page(self) -> None:
        """Open the Queue tab the way the nav does, then let it redraw.

        The tab-change event that refreshes the page needs the event loop, which
        a withdrawn test window only runs when ``update()`` is pumped.
        """
        self.app._goto_tab("Queue")
        self.app.update()
        self.app._refresh_queue_page()
        self.app.update_idletasks()

    # -- rendering --------------------------------------------------------
    def test_the_tab_set_includes_the_queue_page(self) -> None:
        labels = [self.app.nb.tab(t, "text") for t in self.app.nb.tabs()]
        self.assertEqual(labels, list(self.app_mod.TAB_ORDER))
        self.assertIn("Queue", labels)
        self.assertIn("Queue", self.app._nav_btns)

    def test_a_fresh_queue_shows_the_empty_state(self) -> None:
        self._open_page()
        self.assertEqual(self.app.queue_tree.get_children(), ())
        self.assertEqual(self.app.queue_empty_lbl.winfo_manager(), "grid")
        self.assertIn("empty", str(self.app.queue_empty_lbl.cget("text")).lower())
        self.assertIn("0 request", self.app.var_queue_summary.get())

        self._accept()
        self.app._refresh_queue_page()
        self.assertEqual(self.app.queue_empty_lbl.winfo_manager(), "", "the empty state must go")

    def test_the_page_renders_each_job_from_the_queues_records(self) -> None:
        accepted = self._accept(1, line="klein5090")
        failed = self._fail(2, message="invalid graph node 94", line="klein")
        queued = self.app.gen_queue.enqueue(
            {"id": 3, "url": "https://gw.example/prompt", "bytes": 12}
        )
        self._open_page()

        rows = [self._row(job.id) for job in (accepted, failed, queued)]
        self.assertEqual(rows[0][2], q.ACCEPTED)
        self.assertEqual(rows[1][2], q.FAILED)
        self.assertEqual(rows[2][2], q.PENDING)
        self.assertEqual(rows[1][4], "400", "the last status must be on the row")
        self.assertIn("invalid graph node 94", rows[1][5])
        self.assertEqual(rows[1][3], "1", "the attempt count must be on the row")
        self.assertIn("gw.example", rows[1][6], "the request must be on the row")
        self.assertIn("12 bytes", rows[1][6])
        self.assertEqual(rows[0][1], "klein5090", "the row carries the profile it dispatches to")
        self.assertEqual(rows[1][1], "klein")
        self.assertEqual(rows[2][1], "(default)")

        # The rows are the queue's own records, not a second copy.
        recorded = {str(job.id): job.state for job in self.app.gen_queue.jobs()}
        self.assertEqual(
            {str(self.app.queue_tree.item(i, "values")[0]): self.app.queue_tree.item(i, "values")[2]
             for i in self.app.queue_tree.get_children()},
            recorded,
        )
        self.assertIn("failed: 1", self.app.var_queue_summary.get())

    # -- controls ---------------------------------------------------------
    def test_cancel_selected_drops_a_request_that_was_never_submitted(self) -> None:
        calls: list[int] = []
        queued = self.app.gen_queue.enqueue(
            {"id": 1, "url": "https://gw.example/prompt", "bytes": 12},
            lambda _job: q.Attempt(status=200),
        )
        self._open_page()
        self.app.queue_tree.selection_set("1")
        self.app.queue_cancel_btn.invoke()

        self.assertEqual(queued.state, q.CANCELLED)
        self.assertTrue(queued.terminal)
        self.assertEqual(queued.attempts, 0)
        self.assertEqual(calls, [], "the transport must never be called for a cancelled job")
        self.assertEqual(self._row(1)[2], q.CANCELLED, "the row must follow the queue")

    def test_retry_selected_runs_off_the_tk_thread(self) -> None:
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

        failed = self.app.gen_queue.deliver({"id": 1, "url": "https://gw/prompt", "bytes": 3}, transport)
        self.assertEqual(failed.state, q.FAILED)
        self._open_page()
        self.app.queue_tree.selection_set("1")
        self.app.queue_retry_btn.invoke()

        # invoke() returned while the retry is still inside the transport: the
        # window stayed live instead of blocking on the render.
        self.assertTrue(entered.wait(timeout=10), "the retry never reached the transport")
        self.app.update()
        self.assertIn("retrying", self.app.status.get())
        self.app._refresh_queue_page()
        self.assertEqual(
            self._row_state(1), q.RUNNING, "the row shows the live retry, not the old failure"
        )

        release.set()
        self.assertTrue(_pump(self.app, lambda: failed.terminal), "the retry never ended")
        self.assertEqual(failed.state, q.ACCEPTED)
        self.assertEqual(len(calls), 2, "the retry must ask the transport again")
        self._pump_state(1, q.ACCEPTED)

    def test_clear_finished_drops_the_finished_rows(self) -> None:
        self._accept(1)
        self._fail(2)
        self._open_page()
        self.assertEqual(len(self.app.queue_tree.get_children()), 2)
        self.app.queue_clear_btn.invoke()
        self.assertEqual(self.app.gen_queue.jobs(), [])
        self.assertEqual(self.app.queue_tree.get_children(), ())
        self.assertEqual(self.app.queue_empty_lbl.winfo_manager(), "grid")
        self.assertIn("cleared 2", self.app.status.get())

    def test_a_control_with_nothing_selected_says_so(self) -> None:
        self._open_page()
        self.app.queue_cancel_btn.invoke()
        self.assertIn("select a request", self.app.status.get())
        self.app.queue_retry_btn.invoke()
        self.assertIn("select a request", self.app.status.get())

    # -- reachability and the UI read -------------------------------------
    def test_the_page_is_reachable_from_the_sidebar_and_the_tab_lookup(self) -> None:
        self._open_page()
        self.assertEqual(self.app.nb.tab(self.app.nb.select(), "text"), "Queue")
        self.app._goto_tab("Config")
        self.app.update_idletasks()
        self.app._nav_btns["Queue"].invoke()
        self.app.update_idletasks()
        self.assertEqual(self.app.nb.tab(self.app.nb.select(), "text"), "Queue")
        self.assertEqual(self.app.queue_tree.winfo_manager(), "grid")

    def test_the_page_geometry_and_row_text(self) -> None:
        self._accept(1)
        self._fail(2, message="invalid graph node 94")
        self._open_page()
        dump = {
            "page": str(self.app._queue),
            "page_req_width": self.app._queue.winfo_reqwidth(),
            "page_req_height": self.app._queue.winfo_reqheight(),
            "tree_manager": self.app.queue_tree.winfo_manager(),
            "tree_columns": [str(c) for c in self.app.queue_tree.cget("columns")],
            "tree_headings": [str(self.app.queue_tree.heading(c, "text")) for c in self.app.queue_tree.cget("columns")],
            "empty_state_manager": self.app.queue_empty_lbl.winfo_manager(),
            "summary": self.app.var_queue_summary.get(),
            "rows": [list(self._row(1)), list(self._row(2))],
            "nav_labels": list(self.app._nav_btns),
        }
        print(json.dumps(dump, indent=2))
        self.assertGreater(dump["page_req_width"], 1, "the page frame has no width")
        self.assertGreater(dump["page_req_height"], 1, "the page frame has no height")
        self.assertGreaterEqual(dump["page_req_width"], 600)
        for row in dump["rows"]:
            self.assertTrue(row[2] and row[3] and row[4], f"a row is unreadable: {row}")
        self.assertIn("Queue", dump["nav_labels"])

    def test_a_render_in_flight_appears_on_the_page(self) -> None:
        """The page shows a job the app itself submitted, and its outcome after."""
        plate = "QUJD"
        entered = threading.Event()
        release = threading.Event()

        def _req(url, key=None, data=None, timeout=30):
            if str(url).endswith("/ready"):
                return 200, b"ok"
            entered.set()
            release.wait(timeout=20)
            return 200, json.dumps({"images": [plate]}).encode()

        self.app.gen_queue = q.SaladQueue(on_log=self.app._on_queue_log, sleep=lambda _s: None)
        self.app.var_gateway.set(profiles.load_all()["klein"].gateway)
        self.app.var_salad_status.set("Ready")
        self.app.editor_text.delete("1.0", "end")
        self.app.editor_text.insert(
            "1.0",
            json.dumps(
                {
                    "prompt": {
                        "70": {
                            "class_type": "UNETLoader",
                            "inputs": {"unet_name": profiles.load_all()["klein"].primary_checkpoint},
                        }
                    }
                }
            ),
        )
        self.app._rebuild_from_json()
        from salad_studio import tokens as tok

        tok.write_token("salad", "queue-page-key")
        outcome: list[BaseException] = []
        with tempfile.TemporaryDirectory() as out_td, mock.patch.object(
            self.app_mod.generator.salad_gen, "_req", side_effect=_req
        ), mock.patch.object(self.app_mod, "OUT_DIR", Path(out_td)), mock.patch.object(
            self.app_mod.messagebox, "showerror"
        ):

            def body() -> None:
                # Inside mainloop(), and never blocking in it: the render worker
                # logs and reports back with after(), and a Tcl call from that
                # thread while the main thread sits inside a callback deadlocks.
                try:
                    self._open_page()
                    self.app._on_generate()
                    self.assertTrue(
                        _pump(self.app, entered.is_set, 30),
                        "the render never reached the transport",
                    )
                    self._pump_state(1, q.RUNNING)
                    self.assertEqual(self._row(1)[2], q.RUNNING)
                    self.assertEqual(self._row(1)[1], "klein", "the row names the profile")
                    release.set()
                    self.assertTrue(
                        _pump(self.app, lambda: not self.app._busy, 30),
                        "the render never finished",
                    )
                    self._pump_state(1, q.ACCEPTED)
                    self.assertEqual(self._row(1)[3], "1")
                except BaseException as exc:  # noqa: BLE001 - re-raised below
                    outcome.append(exc)
                finally:
                    release.set()
                    _pump(self.app, lambda: not self.app._busy, 30)
                    self.app.quit()

            self.app.after(0, body)
            self.app.mainloop()
        if outcome:
            raise outcome[0]


if __name__ == "__main__":
    unittest.main()
