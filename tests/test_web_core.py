"""The command loop: one thread owns state, callers wait, timers fire once.

The Flet window ran everything on its event loop, so a page handler could never
see a half-updated form. The server has HTTP threads instead, so that guarantee
has to be built. These tests drive the real ``Core`` with real threads.
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio.web.core import Core  # noqa: E402


class CoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.core = Core(workers=2).start()

    def tearDown(self) -> None:
        self.core.stop()

    def test_call_returns_the_handlers_result(self) -> None:
        self.assertEqual(self.core.call(lambda: 6 * 7), 42)

    def test_call_runs_on_the_core_thread(self) -> None:
        seen: list[int] = []
        self.core.call(lambda: seen.append(threading.get_ident()))
        self.assertEqual(seen, [self.core.ident])
        self.assertNotEqual(seen[0], threading.get_ident())

    def test_call_re_raises_the_handlers_exception_in_the_caller(self) -> None:
        def boom() -> None:
            raise ValueError("no such profile")

        with self.assertRaises(ValueError) as caught:
            self.core.call(boom)
        self.assertEqual(str(caught.exception), "no such profile")

    def test_call_from_inside_a_handler_runs_inline(self) -> None:
        inner = self.core.call(lambda: self.core.call(lambda: "nested"))
        self.assertEqual(inner, "nested")

    def test_concurrent_submits_never_overlap(self) -> None:
        active = 0
        peak = 0
        guard = threading.Lock()

        def job() -> None:
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with guard:
                active -= 1

        threads = [threading.Thread(target=self.core.submit, args=(job,)) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.core.call(lambda: None)
        self.assertEqual(peak, 1)

    def test_background_hands_its_result_back_on_the_core_thread(self) -> None:
        done = threading.Event()
        seen: dict[str, object] = {}

        def work() -> str:
            seen["worker"] = threading.get_ident()
            return "plate.jpg"

        def finish(result: object) -> None:
            seen["result"] = result
            seen["core"] = threading.get_ident()
            done.set()

        self.core.background(work, finish)
        self.assertTrue(done.wait(5))
        self.assertEqual(seen["result"], "plate.jpg")
        self.assertEqual(seen["core"], self.core.ident)
        self.assertNotEqual(seen["worker"], self.core.ident)

    def test_a_failing_worker_hands_its_exception_to_done(self) -> None:
        done = threading.Event()
        seen: dict[str, object] = {}

        def work() -> None:
            raise OSError("gateway refused")

        def finish(result: object) -> None:
            seen["result"] = result
            done.set()

        self.core.background(work, finish)
        self.assertTrue(done.wait(5))
        self.assertIsInstance(seen["result"], OSError)

    def test_an_every_timer_fires_repeatedly(self) -> None:
        ticks: list[float] = []
        self.core.every(30, lambda: ticks.append(time.monotonic()))
        deadline = time.monotonic() + 3
        while len(ticks) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertGreaterEqual(len(ticks), 3)

    def test_a_cancelled_timer_does_not_fire(self) -> None:
        fired: list[str] = []
        token = self.core.every(20, lambda: fired.append("tick"))
        self.core.cancel(token)
        self.core.call(lambda: None)
        time.sleep(0.1)
        self.core.call(lambda: None)
        self.assertEqual(fired, [])

    def test_call_later_fires_once(self) -> None:
        fired: list[str] = []
        self.core.call_later(30, lambda: fired.append("once"))
        deadline = time.monotonic() + 3
        while not fired and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.1)
        self.assertEqual(fired, ["once"])

    def test_a_timer_that_raises_does_not_stop_the_core(self) -> None:
        errors: list[BaseException] = []
        self.core.on_error = errors.append
        self.core.every(10, lambda: (_ for _ in ()).throw(RuntimeError("probe")))
        deadline = time.monotonic() + 2
        while not errors and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(errors, "the timer's error reached on_error")
        self.assertEqual(self.core.call(lambda: 7), 7, "the core still answers")

    def test_a_full_event_stream_drops_events_without_raising(self) -> None:
        from salad_studio.web.events import Subscription

        sub = Subscription(limit=2)
        failures: list[BaseException] = []

        def hammer() -> None:
            try:
                for number in range(2000):
                    sub.put("tick", number)
            except BaseException as exc:  # noqa: BLE001 - the publisher must never see one
                failures.append(exc)

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, [], "a stalled stream must not raise into the publisher")

    def test_a_full_stream_keeps_the_newest_events(self) -> None:
        from salad_studio.web.events import Subscription

        sub = Subscription(limit=2)
        sub.put("a", 1)
        sub.put("b", 2)
        sub.put("c", 3)
        self.assertEqual(sub.take(0), ("b", 2), "the oldest event is the one dropped")
        self.assertEqual(sub.take(0), ("c", 3), "the newest event survives")

    def test_stop_ends_the_thread(self) -> None:
        core = Core(workers=1).start()
        core.stop()
        self.assertFalse(core._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
