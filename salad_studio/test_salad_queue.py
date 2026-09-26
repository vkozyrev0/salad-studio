"""The Salad request queue: retention, automatic retry, busy versus failed.

The queue is driven with an injected transport and an injected clock, so the
retries under test are the shipped ones and no test waits 8 s for one. Each
outcome is asserted on the queue's own recorded job, not on log text.
"""
from __future__ import annotations

import base64
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import generator  # noqa: E402
import salad_queue as q  # noqa: E402


class ClassifyTest(unittest.TestCase):
    """One attempt's status, read as ok / busy / failed."""

    def test_a_container_that_is_not_up_yet_is_busy(self) -> None:
        for status in (502, 503, 520, 521, 522, 523):
            self.assertEqual(q.classify(q.Attempt(status=status)), q.BUSY, status)

    def test_a_definitive_rejection_is_failed(self) -> None:
        for status in (400, 401, 403, 404, 405, 422, 500):
            self.assertEqual(q.classify(q.Attempt(status=status)), q.FAILED, status)

    def test_a_gateway_timeout_is_not_busy(self) -> None:
        """504/524: Cloudflare gave up while the job may still be running.

        A retry would submit a duplicate render (docs/workflow/21, measured).
        """
        for status in (504, 524):
            self.assertEqual(q.classify(q.Attempt(status=status)), q.FAILED, status)

    def test_a_transport_that_never_answered_is_busy(self) -> None:
        self.assertEqual(q.classify(q.Attempt(status=0, error="URLError: refused")), q.BUSY)

    def test_an_accepted_request_is_never_busy(self) -> None:
        self.assertEqual(q.classify(q.Attempt(status=200, accepted=True)), q.OK)
        for status in (502, 503, 524):
            self.assertEqual(
                q.classify(q.Attempt(status=status, accepted=True)), q.FAILED, status
            )
        self.assertEqual(
            q.classify(q.Attempt(status=200, accepted=True, error="no images")), q.FAILED
        )

    def test_next_action_stops_retrying_busy_at_the_cap(self) -> None:
        self.assertEqual(q.next_action(q.OK, 1), q.ACCEPT)
        self.assertEqual(q.next_action(q.FAILED, 1), q.FAIL)
        self.assertEqual(q.next_action(q.BUSY, 1, max_attempts=3), q.RETRY)
        self.assertEqual(q.next_action(q.BUSY, 3, max_attempts=3), q.FAIL)

    def test_the_reason_is_the_servers_own_words(self) -> None:
        attempt = q.Attempt(
            status=400, body=b'{"error": {"message": "invalid graph node 94"}}'
        )
        self.assertIn("invalid graph node 94", q.reason_of(attempt))
        self.assertIn("HTTP 400", q.reason_of(attempt))
        self.assertEqual(q.reason_of(q.Attempt(status=0, error="URLError")), "URLError")
        self.assertEqual(q.reason_of(q.Attempt(status=404, body=b"")), "HTTP 404")


class _Gate:
    """An injected clock, so no test waits 8 s for a backoff.

    With ``hold`` set, the sleep parks the queue between two attempts until the
    test lets it through, which is what makes "a second request arrives while
    the first is in flight" deterministic.
    """

    def __init__(self, hold: bool = False) -> None:
        self.hold = hold
        self.refused = threading.Event()
        self.let_through = threading.Event()
        self.slept: list[float] = []
        self.t = 0.0

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        if not self.hold:
            self.t += seconds
            return
        self.refused.set()
        self.let_through.wait(timeout=10)
        self.t += seconds

    def now(self) -> float:
        return self.t


def _queue(transport=None, *, hold: bool = False, **kwargs) -> tuple[q.SaladQueue, _Gate, list[str]]:
    gate = _Gate(hold)
    logs: list[str] = []
    line = q.SaladQueue(
        on_log=lambda level, message: logs.append(f"{level}:{message}"),
        sleep=gate.sleep,
        now=gate.now,
        **kwargs,
    )
    return line, gate, logs


class RetentionTest(unittest.TestCase):
    """A request submitted while another is in flight is kept, not dropped."""

    def test_two_requests_while_the_container_is_busy_both_get_through(self) -> None:
        line, gate, logs = _queue(hold=True)
        attempts = {"n": 0}

        def transport(request):
            attempts["n"] += 1
            if attempts["n"] <= 2:
                return q.Attempt(status=503, body=b'{"title": "replica unavailable"}')
            return q.Attempt(status=200, accepted=True, result=f"plate-{request['id']}")

        done: dict[int, q.Job] = {}

        def deliver(rid: int) -> None:
            done[rid] = line.deliver({"id": rid}, lambda _job: transport({"id": rid}))

        first = threading.Thread(target=deliver, args=(1,), daemon=True)
        first.start()
        self.assertTrue(gate.refused.wait(timeout=10), "the first request was not retried")
        # The first request is parked mid-retry: submit the second one now.
        second = threading.Thread(target=deliver, args=(2,), daemon=True)
        second.start()
        time.sleep(0.2)
        self.assertEqual(len(line.jobs()), 2)
        self.assertEqual(
            line.jobs()[1].state,
            q.PENDING,
            "the second request must wait its turn, not run beside the first",
        )
        gate.let_through.set()
        first.join(timeout=10)
        second.join(timeout=10)

        self.assertEqual(sorted(done), [1, 2])
        for rid in (1, 2):
            self.assertEqual(done[rid].state, q.ACCEPTED, rid)
            self.assertEqual(done[rid].outcome, q.OK, rid)
            self.assertEqual(done[rid].result.result, f"plate-{rid}", rid)
        self.assertEqual(attempts["n"], 4)
        self.assertEqual(done[1].attempts, 3)
        self.assertEqual(gate.slept, [8, 8], "each busy attempt waits one backoff")
        self.assertTrue(
            any("waiting for a container" in line_ for line_ in logs),
            "the automatic retry must be visible in the queue's log",
        )
        self.assertFalse(line.pending(), "nothing is left in the queue")


class ClassificationTest(unittest.TestCase):
    """Busy returns to the queue; a failure is terminal with its reason."""

    def test_a_503_is_retried_and_then_accepted(self) -> None:
        seen: list[int] = []

        def transport(_request):
            status = 503 if not seen else 200
            seen.append(status)
            if status == 200:
                return q.Attempt(status=200, accepted=True, result="plate")
            return q.Attempt(status=503, body=b'{"title": "replica unavailable"}')

        line, gate, _logs = _queue(transport)
        job = line.deliver({"id": 1}, transport)
        self.assertEqual(seen, [503, 200])
        self.assertEqual(job.state, q.ACCEPTED)
        self.assertEqual(job.attempts, 2)
        self.assertEqual(gate.slept, [8])

    def test_a_400_fails_once_with_the_servers_reason(self) -> None:
        calls: list[dict] = []

        def transport(request):
            calls.append(request)
            return q.Attempt(
                status=400, body=b'{"error": {"message": "invalid graph node 94"}}'
            )

        line, gate, _logs = _queue(transport)
        job = line.deliver({"id": 1}, transport)
        self.assertEqual(job.state, q.FAILED)
        self.assertEqual(job.outcome, q.FAILED)
        self.assertEqual(job.status, 400)
        self.assertEqual(job.attempts, 1)
        self.assertEqual(len(calls), 1, "a rejected request is never sent again")
        self.assertIn("invalid graph node 94", job.reason)
        self.assertEqual(gate.slept, [], "a rejection is not a busy container")

    def test_a_524_after_acceptance_is_terminal_and_posts_once(self) -> None:
        calls: list[dict] = []

        def transport(request):
            calls.append(request)
            return q.Attempt(
                status=524,
                accepted=True,
                error="the gateway gave up while the job was running",
            )

        line, gate, _logs = _queue(transport)
        job = line.deliver({"id": 1}, transport)
        self.assertEqual(job.state, q.FAILED)
        self.assertEqual(job.outcome, q.FAILED)
        self.assertEqual(job.attempts, 1)
        self.assertEqual(len(calls), 1, "an accepted job is never POSTed twice")
        self.assertEqual(gate.slept, [])

    def test_a_transport_that_raises_is_retried_as_busy(self) -> None:
        calls: list[int] = []

        def transport(_request):
            calls.append(1)
            if len(calls) == 1:
                raise ConnectionRefusedError("the replica is not up")
            return q.Attempt(status=200, accepted=True, result="plate")

        line, _gate, logs = _queue(transport)
        job = line.deliver({"id": 1}, transport)
        self.assertEqual(job.state, q.ACCEPTED)
        self.assertEqual(len(calls), 2)
        self.assertTrue(any("ConnectionRefusedError" in line_ for line_ in logs))

    def test_the_attempt_cap_ends_a_container_that_never_comes_up(self) -> None:
        calls: list[int] = []

        def transport(_request):
            calls.append(1)
            return q.Attempt(status=503, body=b'{"title": "unavailable"}')

        line, gate, _logs = _queue(transport, max_attempts=3)
        job = line.deliver({"id": 1}, transport)
        self.assertEqual(job.state, q.FAILED)
        self.assertEqual(job.attempts, 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(gate.slept, [8, 8])


class ManagementTest(unittest.TestCase):
    """Cancel a job that has not been submitted, retry a failed one, clear the rest."""

    def test_a_queued_request_can_be_cancelled_before_it_is_submitted(self) -> None:
        line, gate, logs = _queue(hold=True)
        calls: list[int] = []

        def transport(request):
            calls.append(int(request["id"]))
            if calls.count(int(request["id"])) == 1 and request["id"] == 1:
                return q.Attempt(status=503, body=b'{"title": "replica unavailable"}')
            return q.Attempt(
                status=200, accepted=True, result=f"plate-{request['id']}"
            )

        done: dict[int, q.Job] = {}

        def deliver(rid: int) -> None:
            done[rid] = line.deliver({"id": rid}, lambda _job: transport({"id": rid}))

        first = threading.Thread(target=deliver, args=(1,), daemon=True)
        first.start()
        self.assertTrue(gate.refused.wait(timeout=10))
        second = threading.Thread(target=deliver, args=(2,), daemon=True)
        second.start()
        deadline = time.time() + 5
        while time.time() < deadline and len(line.jobs()) < 2:
            time.sleep(0.01)
        queued = line.jobs()[1]
        self.assertEqual(queued.state, q.PENDING)
        self.assertTrue(queued.cancellable)

        self.assertTrue(line.cancel(queued))
        self.assertEqual(queued.state, q.CANCELLED)
        self.assertTrue(queued.terminal, "a cancelled job must be terminal")
        self.assertEqual(queued.attempts, 0)
        self.assertFalse(line.cancel(queued), "cancelling twice is not a new cancel")

        gate.let_through.set()
        first.join(timeout=10)
        second.join(timeout=10)
        self.assertFalse(second.is_alive(), "the cancelled caller must return")
        self.assertEqual(done[2].state, q.CANCELLED)
        self.assertIsNone(done[2].result)
        self.assertNotIn(2, calls, "the transport must never be called for a cancelled job")
        self.assertEqual(done[1].state, q.ACCEPTED)
        self.assertTrue(any("cancelled" in line_ for line_ in logs))

    def test_a_submitted_request_is_not_cancellable(self) -> None:
        def transport(_request):
            return q.Attempt(status=400, body=b'{"error": {"message": "bad graph"}}')

        line, _gate, logs = _queue(transport)
        job = line.deliver({"id": 1}, transport)
        self.assertEqual(job.state, q.FAILED)
        self.assertTrue(job.submitted)
        self.assertFalse(job.cancellable)
        self.assertFalse(line.cancel(job), "a submitted job must not be cancelled")
        self.assertEqual(job.state, q.FAILED)
        self.assertTrue(any("cannot be cancelled" in line_ for line_ in logs))

    def test_a_failed_request_is_retried_through_the_queue(self) -> None:
        calls: list[int] = []

        def transport(_request):
            calls.append(1)
            if len(calls) == 1:
                return q.Attempt(
                    status=400, body=b'{"error": {"message": "invalid graph node 94"}}'
                )
            return q.Attempt(status=200, accepted=True, result="plate")

        line, _gate, _logs = _queue(transport)
        job = line.deliver({"id": 1}, transport)
        self.assertEqual(job.state, q.FAILED)
        self.assertIn("invalid graph node 94", job.reason)
        self.assertTrue(job.retryable)

        line.retry(job)
        self.assertEqual(job.state, q.ACCEPTED)
        self.assertEqual(len(calls), 2, "the retry must ask the transport again")
        self.assertEqual(job.reason, "", "an accepted retry carries no failure reason")
        self.assertEqual(job.result.result, "plate")

    def test_a_retried_request_can_fail_again_with_its_new_reason(self) -> None:
        bodies = [
            b'{"error": {"message": "first reason"}}',
            b'{"error": {"message": "second reason"}}',
        ]

        def transport(_request):
            return q.Attempt(status=400, body=bodies.pop(0))

        line, _gate, _logs = _queue(transport)
        job = line.deliver({"id": 1}, transport)
        self.assertIn("first reason", job.reason)
        line.retry(job)
        self.assertEqual(job.state, q.FAILED)
        self.assertIn("second reason", job.reason, "the retry records its own reason")

    def test_a_failure_after_acceptance_is_not_retryable(self) -> None:
        calls: list[int] = []

        def transport(_request):
            calls.append(1)
            return q.Attempt(status=524, accepted=True, error="the gateway gave up")

        line, _gate, _logs = _queue(transport)
        job = line.deliver({"id": 1}, transport)
        self.assertEqual(job.state, q.FAILED)
        self.assertTrue(job.accepted)
        self.assertFalse(job.retryable, "an accepted job must never be re-POSTed")
        line.retry(job)
        self.assertEqual(len(calls), 1)
        self.assertEqual(job.state, q.FAILED)

    def test_clearing_finished_requests_keeps_the_live_ones(self) -> None:
        line, _gate, logs = _queue()
        line.deliver({"id": 1}, lambda _job: q.Attempt(status=200, accepted=True, result="p"))
        line.deliver({"id": 2}, lambda _job: q.Attempt(status=400, body=b'{"title": "bad"}'))
        line.deliver({"id": 4}, lambda _job: q.Attempt(status=200, accepted=True, result="p"))
        # Queued last: a job nobody has run yet holds the head of the line, so
        # enqueueing it behind the delivered ones keeps the line honest.
        queued = line.enqueue({"id": 3}, lambda _job: q.Attempt(status=200))

        self.assertEqual(line.clear_finished(), 3)
        self.assertEqual([job.id for job in line.jobs()], [queued.id])
        self.assertEqual(line.pending(), 1)
        self.assertTrue(any("cleared" in line_ for line_ in logs))
        self.assertEqual(line.clear_finished(), 0, "nothing finished is left to clear")


class GeneratorThroughTheQueue(unittest.TestCase):
    """The shipped generator path really does POST through the queue."""

    def test_a_busy_container_is_retried_by_generate_from_payload(self) -> None:
        plate = base64.b64encode(b"jpeg-bytes").decode("ascii")
        posts: list[str] = []

        def _req(url, key, data=None, timeout=30):
            if url.endswith("/ready"):
                return 200, b"ok"
            posts.append(url)
            if len(posts) == 1:
                return 503, b'{"title": "replica unavailable"}'
            return 200, json.dumps({"images": [plate]}).encode()

        payload = {
            "prompt": {
                "9": {
                    "class_type": "SaveImage",
                    "inputs": {"filename_prefix": "x", "images": ["8", 0]},
                }
            },
            "convert_output": {"format": "jpeg"},
        }
        line = q.SaladQueue(sleep=lambda _s: None, now=lambda: 0.0)
        with TemporaryDirectory() as td:
            with patch.object(generator.salad_gen, "_req", side_effect=_req):
                path = generator.generate_from_payload(
                    gateway="https://example.salad.test/",
                    key="test-key",
                    payload=payload,
                    out_dir=Path(td),
                    queue=line,
                )
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), b"jpeg-bytes")
        self.assertEqual(len(posts), 2, "one retry, then the plate")
        self.assertEqual(line.jobs()[0].state, q.ACCEPTED)
        self.assertEqual(line.jobs()[0].attempts, 2)


if __name__ == "__main__":
    unittest.main()
