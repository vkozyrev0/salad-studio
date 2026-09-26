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
import studio_meta  # noqa: E402


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


class PerProfileDispatchTest(unittest.TestCase):
    """One line per profile: a blocked container holds only its own requests."""

    def test_another_profiles_request_runs_while_one_is_blocked(self) -> None:
        line, _gate, _logs = _queue()
        entered = threading.Event()
        release = threading.Event()
        calls: list[tuple[str, str]] = []

        def transport(request):
            calls.append((request["profile"], request["gateway"]))
            if request["profile"] == "klein":
                entered.set()
                release.wait(timeout=15)
                return q.Attempt(status=200, accepted=True, result="plate-klein")
            return q.Attempt(status=200, accepted=True, result="plate-snofs")

        done: dict[str, q.Job] = {}

        def deliver(rid: str, profile: str, gateway: str) -> None:
            done[rid] = line.deliver(
                {"id": rid, "profile": profile, "gateway": gateway},
                lambda _job: transport({"profile": profile, "gateway": gateway}),
                line=profile,
            )

        first = threading.Thread(
            target=deliver, args=("a1", "klein", "https://klein.example/"), daemon=True
        )
        first.start()
        self.assertTrue(entered.wait(timeout=15), "the first request never reached the transport")

        same = threading.Thread(
            target=deliver, args=("a2", "klein", "https://klein.example/"), daemon=True
        )
        other = threading.Thread(
            target=deliver, args=("b1", "snofs", "https://snofs.example/"), daemon=True
        )
        same.start()
        other.start()

        deadline = time.time() + 15
        while time.time() < deadline and not any(p == "snofs" for p, _g in calls):
            time.sleep(0.01)
        self.assertTrue(
            any(p == "snofs" for p, _g in calls),
            "a request for another profile waited behind the blocked one",
        )
        klein_jobs = [job for job in line.jobs() if job.line == "klein"]
        self.assertEqual(
            [job.state for job in klein_jobs],
            [q.RUNNING, q.PENDING],
            "a second request for the same profile must still wait its turn",
        )
        self.assertEqual(
            len([p for p, _g in calls if p == "klein"]),
            1,
            "one container takes one POST at a time",
        )
        self.assertEqual(line.lines(), {"klein": 2}, "the other line has drained")

        release.set()
        for thread in (first, same, other):
            thread.join(timeout=15)
        self.assertEqual(done["a1"].state, q.ACCEPTED)
        self.assertEqual(done["a2"].state, q.ACCEPTED)
        self.assertEqual(done["b1"].state, q.ACCEPTED)
        self.assertEqual(done["a1"].result.result, "plate-klein")
        self.assertEqual(done["a2"].result.result, "plate-klein")
        self.assertEqual(done["b1"].result.result, "plate-snofs")
        self.assertEqual(
            dict(calls),
            {"klein": "https://klein.example/", "snofs": "https://snofs.example/"},
            "every transport call carried its own profile's gateway",
        )
        self.assertEqual(line.lines(), {})

    def test_a_retry_rejoins_its_own_profiles_line(self) -> None:
        def transport(_request):
            return q.Attempt(status=400, body=b'{"error": {"message": "bad graph"}}')

        line, _gate, _logs = _queue()
        job = line.deliver({"id": 1}, transport, line="klein")
        self.assertEqual(job.state, q.FAILED)
        self.assertEqual(job.line, "klein")
        self.assertTrue(job.retryable)
        line.retry(job)
        self.assertEqual(job.state, q.FAILED)
        self.assertEqual(job.line, "klein", "a retry stays on the profile that owns it")


class _FakeLifecycle:
    """The container handle the queue is given, with every call recorded."""

    def __init__(
        self,
        running: dict[str, bool | None] | None = None,
        *,
        start_code: int = 202,
        stop_code: int = 202,
        start_message: str = "",
    ) -> None:
        self.running = dict(running or {})
        self.start_code = start_code
        self.stop_code = stop_code
        self.start_message = start_message
        self.calls: list[tuple[str, str, str]] = []

    def is_running(self, profile: str, gateway: str) -> bool | None:
        self.calls.append(("is_running", profile, gateway))
        return self.running.get(profile)

    def start(self, profile: str, gateway: str) -> tuple[int, str]:
        self.calls.append(("start", profile, gateway))
        return self.start_code, self.start_message

    def stop(self, profile: str, gateway: str) -> tuple[int, str]:
        self.calls.append(("stop", profile, gateway))
        return self.stop_code, ""

    def actions(self, name: str) -> list[tuple[str, str, str]]:
        return [call for call in self.calls if call[0] == name]


class LifecycleStartTest(unittest.TestCase):
    """The queue starts the container a request needs, once."""

    KLEIN_GW = "https://klein.example/"
    SNOFS_GW = "https://snofs.example/"

    def _accept(self, calls: list[str]):
        def transport(job):
            # The queue hands the attempt the job, not the request payload.
            profile = str((job.request or {}).get("profile") or "")
            calls.append(profile)
            return q.Attempt(status=200, accepted=True, result=f"plate-{profile}")

        return transport

    def test_a_stopped_container_is_started_once_and_the_request_runs(self) -> None:
        life = _FakeLifecycle({"klein": False})
        line, _gate, logs = _queue(lifecycle=life)
        calls: list[str] = []
        job = line.deliver(
            {"gateway": self.KLEIN_GW, "profile": "klein"},
            self._accept(calls),
            line="klein",
        )
        self.assertEqual(job.state, q.ACCEPTED)
        self.assertEqual(job.result.result, "plate-klein")
        self.assertEqual(
            life.actions("start"),
            [("start", "klein", self.KLEIN_GW)],
            "exactly one start, naming that profile's gateway",
        )
        self.assertEqual(calls, ["klein"], "the request ran after the start")
        self.assertEqual(line.containers(), {"klein": self.KLEIN_GW})
        self.assertTrue(any("asked Salad to start" in entry for entry in logs))

    def test_a_running_container_is_not_started(self) -> None:
        life = _FakeLifecycle({"klein": True})
        line, _gate, _logs = _queue(lifecycle=life)
        calls: list[str] = []
        job = line.deliver(
            {"gateway": self.KLEIN_GW, "profile": "klein"}, self._accept(calls), line="klein"
        )
        self.assertEqual(job.state, q.ACCEPTED)
        self.assertEqual(life.actions("start"), [], "a running container is left alone")
        self.assertEqual(life.actions("is_running"), [("is_running", "klein", self.KLEIN_GW)])

    def test_an_unknown_state_is_left_alone(self) -> None:
        life = _FakeLifecycle({"klein": None})
        line, _gate, logs = _queue(lifecycle=life)
        calls: list[str] = []
        job = line.deliver(
            {"gateway": self.KLEIN_GW, "profile": "klein"}, self._accept(calls), line="klein"
        )
        self.assertEqual(job.state, q.ACCEPTED)
        self.assertEqual(life.actions("start"), [], "never start on a guess")
        self.assertTrue(any("state unknown" in entry for entry in logs))

    def test_two_profiles_each_start_their_own_container(self) -> None:
        life = _FakeLifecycle({"klein": False, "snofs": False})
        line, _gate, _logs = _queue(lifecycle=life)
        calls: list[str] = []
        klein = line.deliver(
            {"gateway": self.KLEIN_GW, "profile": "klein"}, self._accept(calls), line="klein"
        )
        snofs = line.deliver(
            {"gateway": self.SNOFS_GW, "profile": "snofs"}, self._accept(calls), line="snofs"
        )
        self.assertEqual(klein.state, q.ACCEPTED)
        self.assertEqual(snofs.state, q.ACCEPTED)
        self.assertEqual(
            life.actions("start"),
            [("start", "klein", self.KLEIN_GW), ("start", "snofs", self.SNOFS_GW)],
        )
        self.assertEqual(
            line.containers(), {"klein": self.KLEIN_GW, "snofs": self.SNOFS_GW}
        )

    def test_a_rejected_start_ends_the_request_with_the_reason(self) -> None:
        life = _FakeLifecycle({"klein": False}, start_code=403, start_message="quota exceeded")
        line, _gate, _logs = _queue(lifecycle=life)
        calls: list[str] = []
        job = line.deliver(
            {"gateway": self.KLEIN_GW, "profile": "klein"}, self._accept(calls), line="klein"
        )
        self.assertEqual(job.state, q.FAILED)
        self.assertIn("HTTP 403", job.reason)
        self.assertIn("quota exceeded", job.reason)
        self.assertEqual(calls, [], "the request never reached the transport")
        self.assertEqual(line.containers(), {}, "a container that failed to start is not tracked")

    def test_the_start_is_asked_once_however_many_attempts_the_request_makes(self) -> None:
        life = _FakeLifecycle({"klein": False})
        line, gate, _logs = _queue(lifecycle=life)
        seen: list[int] = []

        def transport(_request):
            seen.append(1)
            if len(seen) == 1:
                return q.Attempt(status=503, body=b'{"title": "replica unavailable"}')
            return q.Attempt(status=200, accepted=True, result="plate")

        job = line.deliver(
            {"gateway": self.KLEIN_GW, "profile": "klein"}, transport, line="klein"
        )
        self.assertEqual(job.state, q.ACCEPTED)
        self.assertEqual(job.attempts, 2, "the busy attempt was retried")
        self.assertEqual(len(life.actions("start")), 1, "one start, not one per attempt")
        self.assertEqual(gate.slept, [8])

    def test_a_retry_does_not_start_the_container_again(self) -> None:
        life = _FakeLifecycle({"klein": False})
        line, _gate, _logs = _queue(lifecycle=life)
        seen: list[int] = []

        def transport(_request):
            seen.append(1)
            if len(seen) == 1:
                return q.Attempt(status=400, body=b'{"error": {"message": "bad graph"}}')
            return q.Attempt(status=200, accepted=True, result="plate")

        job = line.deliver(
            {"gateway": self.KLEIN_GW, "profile": "klein"}, transport, line="klein"
        )
        self.assertEqual(job.state, q.FAILED)
        self.assertEqual(len(life.actions("start")), 1)
        line.retry(job)
        self.assertEqual(job.state, q.ACCEPTED)
        self.assertEqual(len(life.actions("start")), 1, "the retry reuses the running container")

    def test_a_queue_without_a_lifecycle_still_delivers(self) -> None:
        line, _gate, _logs = _queue()
        calls: list[str] = []
        job = line.deliver(
            {"gateway": self.KLEIN_GW, "profile": "klein"}, self._accept(calls), line="klein"
        )
        self.assertEqual(job.state, q.ACCEPTED)
        self.assertEqual(line.containers(), {})


class LifecycleIdleTest(unittest.TestCase):
    """A container is stopped after the configured idle timeout, and once."""

    GW = "https://klein.example/"
    REQUEST = {"gateway": "https://klein.example/", "profile": "klein"}

    def _run_one(self, line, *, gate, line_name: str = "klein") -> q.Job:
        def transport(_request):
            return q.Attempt(status=200, accepted=True, result="plate")

        return line.deliver(
            {"gateway": self.GW, "profile": line_name}, transport, line=line_name
        )

    def test_no_stop_before_the_timeout_and_one_after_it(self) -> None:
        life = _FakeLifecycle({"klein": False})
        line, gate, logs = _queue(lifecycle=life, idle_stop_s=3600)
        job = self._run_one(line, gate=gate)
        self.assertEqual(job.state, q.ACCEPTED)

        gate.t += 3599
        self.assertEqual(line.idle_check(), [], "not idle long enough to stop")
        self.assertEqual(life.actions("stop"), [])

        gate.t += 2
        self.assertEqual(line.idle_check(), ["klein"])
        self.assertEqual(life.actions("stop"), [("stop", "klein", self.GW)])
        self.assertEqual(line.containers(), {}, "a stopped container leaves the books")
        self.assertTrue(any("stopped klein after 3600s idle" in entry for entry in logs))

    def test_a_second_check_does_not_stop_it_twice(self) -> None:
        life = _FakeLifecycle({"klein": False})
        line, gate, _logs = _queue(lifecycle=life, idle_stop_s=3600)
        self._run_one(line, gate=gate)
        gate.t += 3601
        self.assertEqual(line.idle_check(), ["klein"])
        self.assertEqual(line.idle_check(), [], "nothing left to stop")
        self.assertEqual(len(life.actions("stop")), 1)

    def test_a_request_in_flight_holds_the_container_open(self) -> None:
        life = _FakeLifecycle({"klein": False})
        line, gate, _logs = _queue(lifecycle=life, idle_stop_s=60)
        entered = threading.Event()
        release = threading.Event()

        def transport(_request):
            entered.set()
            release.wait(timeout=15)
            return q.Attempt(status=200, accepted=True, result="plate")

        done: dict[str, q.Job] = {}
        thread = threading.Thread(
            target=lambda: done.setdefault(
                "job",
                line.deliver(
                    {"gateway": self.GW, "profile": "klein"}, transport, line="klein"
                ),
            ),
            daemon=True,
        )
        thread.start()
        self.assertTrue(entered.wait(timeout=15), "the request never reached the transport")

        gate.t += 600
        self.assertEqual(line.idle_check(), [], "a request in flight holds the container")
        self.assertEqual(life.actions("stop"), [])

        release.set()
        thread.join(timeout=15)
        self.assertEqual(done["job"].state, q.ACCEPTED)
        gate.t += 61
        self.assertEqual(line.idle_check(), ["klein"], "idle again once the request finished")
        self.assertEqual(len(life.actions("stop")), 1)

    def test_a_queued_request_holds_the_container_open(self) -> None:
        life = _FakeLifecycle({"klein": False})
        line, gate, _logs = _queue(lifecycle=life, idle_stop_s=60)
        self._run_one(line, gate=gate)
        queued = line.enqueue({"gateway": self.GW, "profile": "klein"}, line="klein")
        gate.t += 600
        self.assertEqual(line.idle_check(), [], "a queued request holds the container")
        self.assertEqual(queued.state, q.PENDING)
        self.assertEqual(life.actions("stop"), [])

    def test_the_timeout_comes_from_the_metadata_document(self) -> None:
        life = _FakeLifecycle({"klein": False})
        with TemporaryDirectory() as td:
            path = Path(td) / "studio-metadata.json"
            path.write_text(json.dumps({"queue": {"idle_stop_s": 45}}), encoding="utf-8")
            doc = studio_meta.load(path=path)
            line, gate, _logs = _queue(lifecycle=life, meta=doc)
            self.assertEqual(line.idle_timeout_s(), 45, "the document, not a literal")
            self._run_one(line, gate=gate)
            gate.t += 44
            self.assertEqual(line.idle_check(), [])
            gate.t += 2
            self.assertEqual(line.idle_check(), ["klein"], "the document's timeout")

        # The shipped document says one hour, so the same run would not stop yet.
        shipped = _FakeLifecycle({"klein": False})
        line2, gate2, _logs2 = _queue(lifecycle=shipped, meta=studio_meta.load())
        self.assertEqual(line2.idle_timeout_s(), studio_meta.DEFAULT_IDLE_STOP_S)
        self._run_one(line2, gate=gate2)
        gate2.t += 46
        self.assertEqual(line2.idle_check(), [])

    def test_a_rejected_stop_is_reported_and_not_retried_immediately(self) -> None:
        life = _FakeLifecycle({"klein": False}, stop_code=500)
        line, gate, logs = _queue(lifecycle=life, idle_stop_s=60)
        self._run_one(line, gate=gate)
        gate.t += 61
        self.assertEqual(line.idle_check(), [], "the stop failed")
        self.assertEqual(len(life.actions("stop")), 1)
        self.assertEqual(line.containers(), {"klein": self.GW}, "still on the books")
        self.assertTrue(any("could not stop klein" in entry for entry in logs))

        gate.t += 1
        self.assertEqual(line.idle_check(), [], "not retried on the next tick")
        self.assertEqual(len(life.actions("stop")), 1)
        gate.t += 60
        self.assertEqual(line.idle_check(), [], "and not while the stop keeps failing")
        self.assertEqual(len(life.actions("stop")), 2, "retried after another full timeout")

    def test_a_container_that_was_already_running_is_stopped_when_idle(self) -> None:
        life = _FakeLifecycle({"klein": True})
        line, gate, _logs = _queue(lifecycle=life, idle_stop_s=60)
        self._run_one(line, gate=gate)
        self.assertEqual(life.actions("start"), [], "it was already up")
        gate.t += 61
        self.assertEqual(line.idle_check(), ["klein"])
        self.assertEqual(life.actions("stop"), [("stop", "klein", self.GW)])

    def test_a_profile_the_queue_never_touched_is_not_stopped(self) -> None:
        life = _FakeLifecycle({"klein": False})
        line, gate, _logs = _queue(lifecycle=life, idle_stop_s=60)
        gate.t += 10_000
        self.assertEqual(line.idle_check(), [])
        self.assertEqual(life.calls, [], "no container of ours to stop")


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
