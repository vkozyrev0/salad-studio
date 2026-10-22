"""Exhaustive check of the queue's submission promise.

The promise: a container that has accepted a request is never sent that
request again, and a job the container accepted is never retried.

The check drives the shipped ``SaladQueue`` with an injected transport and
clock, so there is no model to drift from the code. It enumerates every
sequence of transport outcomes up to four POSTs, for ``max_attempts`` 1 to 3,
runs the job to a terminal state, then presses Retry once and counts POSTs.

Exit 0: every sequence held. Exit 1: at least one sequence broke the promise,
and the failing sequences are printed.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# salad_queue imports studio_meta as a top-level module on purpose, so the
# package directory must be on sys.path, exactly as the app and tests do it.
sys.path.insert(0, str(ROOT / "salad_studio"))

import salad_queue as q  # noqa: E402

# One representative per way a transport can answer. A non-accepted 200 is
# separate from an accepted one because only the accepted flag licenses the
# no-second-POST rule.
OUTCOMES = {
    "ok-accepted": q.Attempt(status=200, accepted=True, result="plate"),
    "ok-plain": q.Attempt(status=200, result="plate"),
    "accepted-524": q.Attempt(status=524, accepted=True, error="the gateway gave up"),
    "accepted-500": q.Attempt(status=500, accepted=True, error="render failed"),
    "failed-400": q.Attempt(status=400, body=b'{"error": "invalid graph node 94"}'),
    "busy-503": q.Attempt(status=503, body=b'{"title": "unavailable"}'),
    "busy-502": q.Attempt(status=502),
    "busy-0": q.Attempt(status=0, error="ConnectionRefusedError: refused"),
}

MAX_POSTS = 4


class Transport:
    """Plays a scripted list of outcomes, one per POST, and records what it saw."""

    def __init__(self, script: tuple[str, ...]) -> None:
        self.script = list(script)
        self.posts = 0
        self.accepted_posts = 0
        self.post_after_accept = False

    def __call__(self, _job) -> q.Attempt:
        if self.accepted_posts:
            self.post_after_accept = True
        self.posts += 1
        # Running past the script means the queue asked for one POST too many.
        name = self.script.pop(0) if self.script else "failed-400"
        attempt = OUTCOMES[name]
        if attempt.accepted:
            self.accepted_posts += 1
        return attempt


def run(script: tuple[str, ...], max_attempts: int) -> list[str]:
    """One job through ``deliver`` and one Retry press. Returns what broke."""
    transport = Transport(script)
    queue = q.SaladQueue(
        sleep=lambda _s: None,
        now=lambda: 0.0,
        retry_sleep_s=0,
        max_attempts=max_attempts,
    )
    job = queue.deliver({"id": 1, "prompt": "plate"}, transport)
    problems: list[str] = []
    if transport.post_after_accept:
        problems.append("POST after an accepted POST")
    if job.accepted:
        if job.retryable:
            problems.append("an accepted job reported retryable")
        before = transport.posts
        queue.retry(job)
        if transport.posts != before:
            problems.append("retry() POSTed an accepted job")
    return problems


def main() -> int:
    failures: list[tuple[tuple[str, ...], int, list[str]]] = []
    checked = 0
    for length in range(1, MAX_POSTS + 1):
        for script in itertools.product(OUTCOMES, repeat=length):
            for max_attempts in (1, 2, 3):
                checked += 1
                problems = run(script, max_attempts)
                if problems:
                    failures.append((script, max_attempts, problems))
    print(f"sequences checked: {checked}")
    print(f"failures: {len(failures)}")
    for script, max_attempts, problems in failures[:20]:
        print(f"  {' -> '.join(script)} (max_attempts={max_attempts}): {'; '.join(problems)}")
    if failures:
        print("the queue would render a plate the container already accepted")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
