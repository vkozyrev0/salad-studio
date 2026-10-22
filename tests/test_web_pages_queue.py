"""The Queue page: one row per request, the counts as fields, and the three writes.

The page reads the queue the services share, so every test swaps in a queue of
its own and waits on the core thread for a background retry's answer.
"""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import salad_queue  # noqa: E402
from salad_studio.web.core import Core  # noqa: E402
from salad_studio.web.engine import WebEngine  # noqa: E402
from salad_studio.web.events import Hub  # noqa: E402
from salad_studio.web.pages.queue import EMPTY_TEXT, QueueController  # noqa: E402
from salad_studio.web.registry import ActionContext, Controllers  # noqa: E402
from salad_studio.web.shell import Shell  # noqa: E402


def refused(_job) -> salad_queue.Attempt:
    """A refusal the container sends: an HTTP error that retrying will not fix."""
    return salad_queue.Attempt(status=500, error="job not ready")


class QueuePageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = salad_queue.LEDGER_PATH
        salad_queue.LEDGER_PATH = Path(self.tmp.name) / "studio-queue.json"
        self.core = Core(workers=2).start()
        self.hub = Hub()
        self.studio = Shell(self.core, self.hub)
        self.studio.controllers = Controllers(self.studio)
        self.page = QueueController(self.studio)
        self.studio.controllers.add(self.page)
        self.queue = salad_queue.SaladQueue(
            sleep=lambda _s: None, ledger_path=Path(self.tmp.name) / "queue.json")
        self.studio.services.gen_queue = self.queue

    def tearDown(self) -> None:
        self.core.stop()
        salad_queue.LEDGER_PATH = self.saved
        self.tmp.cleanup()

    def call(self, action: str, args: dict | None = None):
        ctx = ActionContext(self.studio, "queue", action, args or {})
        result = self.studio.controllers.table.call(f"queue.{action}", dict(args or {}), ctx=ctx)
        self.assertIsNone(result.error, result.error)
        return result.data, ctx

    def failed(self, line: str = "klein") -> salad_queue.Job:
        """A job that ran and failed, as a Generate that gave up leaves one."""
        job = self.queue.enqueue({"profile": "klein", "gateway": "https://g"}, refused, line=line, checksum="c" + line)
        self.queue._run(job, refused)
        return job

    def test_an_empty_queue_says_so_and_counts_zero(self) -> None:
        state, _ctx = self.call("view")
        self.assertEqual(state["rows"], [])
        self.assertEqual(state["empty_text"], EMPTY_TEXT)
        self.assertEqual(state["summary"]["requests"], 0)
        self.assertEqual(state["summary"]["pending"], 0)
        self.assertEqual(state["summary"]["states"], [])
        self.assertFalse(state["can_cancel"])

    def test_the_summary_is_fields_and_each_row_shows_its_job(self) -> None:
        live = self.queue.enqueue({"profile": "klein"}, None, line="klein")
        done = self.queue.enqueue({"endpoint": "https://vast"}, refused, line="vast", checksum="cvast")
        self.queue._run(done, refused)
        state, _ctx = self.call("view")
        summary = state["summary"]
        self.assertEqual(summary["requests"], 2)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["lines"], {"klein": 1, "vast": 1})
        self.assertEqual({row["word"]: row["count"] for row in summary["states"]},
                         {"failed": 1, "waiting": 1})
        rows = {r["key"]: r for r in state["rows"]}
        self.assertEqual(rows[str(live.id)]["state"], "waiting")
        self.assertTrue(rows[str(live.id)]["cancellable"])
        failed = rows[str(done.id)]
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["attempts"], "1")
        self.assertEqual(failed["status"], "500")
        self.assertEqual(failed["request"], "https://vast")
        self.assertTrue(failed["finished"])
        self.assertTrue(failed["retryable"])

    def test_selecting_a_cancellable_request_then_cancelling_drops_it(self) -> None:
        job = self.queue.enqueue({"profile": "klein"}, None, line="klein")
        state, _ctx = self.call("select", {"key": str(job.id)})
        self.assertEqual(state["selected"], str(job.id))
        self.assertTrue(state["can_cancel"])
        state, ctx = self.call("cancel")
        self.assertEqual(job.state, salad_queue.CANCELLED)
        self.assertEqual(ctx.note_text[1], "ok")
        self.assertEqual(next(r for r in state["rows"] if r["key"] == str(job.id))["state"], "cancelled")
        self.assertIn("cancelled", state["note"])

    def test_a_submitted_request_is_refused_with_the_reason(self) -> None:
        job = self.failed()
        job.attempts = 2
        self.call("select", {"key": str(job.id)})
        _state, ctx = self.call("cancel")
        self.assertEqual(job.state, salad_queue.FAILED)
        self.assertEqual(ctx.note_text[1], "warn")
        self.assertIn("cannot be cancelled", ctx.note_text[0])

    def test_retry_runs_on_the_background_and_answers_on_core(self) -> None:
        job = self.failed()
        engine = WebEngine(self.studio)
        self.studio.engine = engine
        # The events the stream would carry, recorded rather than sent: the
        # engine publishes action_done to every open stream when retry ends.
        events: dict[str, list[dict]] = {}
        self.hub.publish = lambda name, data: events.setdefault(name, []).append(data)
        self.call("select", {"key": str(job.id)})
        status, reply = engine.handle({"page": "queue", "action": "retry", "args": {}})
        self.assertEqual(status, 200)
        self.assertTrue(reply["pending"])
        self.assertTrue(reply["busy"].get("retry"))
        deadline = time.monotonic() + 15
        while "action_done" not in events and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(events.get("action_done"), "the retry never answered")
        done = events["action_done"][0]["reply"]
        self.assertEqual(done["id"], reply["id"])
        self.assertTrue(done["ok"])
        self.assertEqual(done["shell"]["note"]["level"], "warn")
        self.assertEqual(done["shell"]["note"]["text"], "Request 1 was retried: failed. job not ready")
        self.assertEqual(job.attempts, 2, "the retry is the job's second try")
        self.assertEqual(done["busy"], {})

    def test_retry_of_a_waiting_request_is_refused(self) -> None:
        job = self.queue.enqueue({"profile": "klein"}, None, line="klein")
        self.call("select", {"key": str(job.id)})
        _state, ctx = self.call("retry")
        self.assertFalse(ctx.is_pending)
        self.assertEqual(ctx.note_text[1], "warn")
        self.assertEqual(job.state, salad_queue.PENDING)

    def test_clear_finished_drops_the_rows_and_says_how_many(self) -> None:
        self.failed()
        state, ctx = self.call("view")
        self.assertEqual(state["count"], 1)
        state, ctx = self.call("clear_finished")
        self.assertEqual(state["rows"], [])
        self.assertEqual(state["empty_text"], EMPTY_TEXT)
        self.assertIn("Cleared 1", ctx.note_text[0])

    def test_a_kept_row_from_an_earlier_session_is_shown_but_not_cancellable(self) -> None:
        kept = salad_queue.SaladQueue(ledger_path=Path(self.tmp.name) / "kept.json")
        job = kept.enqueue({"profile": "klein"}, refused, line="klein", checksum="c")
        kept._run(job, refused)
        self.studio.services.gen_queue = salad_queue.SaladQueue(
            ledger_path=Path(self.tmp.name) / "kept.json")
        state, _ctx = self.call("view")
        row = state["rows"][0]
        self.assertEqual(row["key"], f"kept-{job.id}")
        self.assertEqual(row["state"], "failed")
        self.assertFalse(row["cancellable"])
        self.assertFalse(row["retryable"])

    def test_selecting_a_row_that_is_gone_is_refused(self) -> None:
        _state, ctx = self.call("select", {"key": "nope"})
        self.assertEqual(ctx.note_text[1], "warn")


if __name__ == "__main__":
    unittest.main()
