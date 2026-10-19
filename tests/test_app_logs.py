"""Logs and the services behind them: masking in both panes, and the timers close cancels.

Ported from the Tk layout suite. The window is a real one on a stub page, its
stores are temp files, and the workers handed to ``AppServices.background`` run
on the calling thread so a probe's result lands before the next line.
"""
from __future__ import annotations

import asyncio
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
for _p in (HERE / ".." / "salad_studio", HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio import flet_app, flet_services, profiles, tokens  # noqa: E402
from salad_studio.flet_pump import Pump  # noqa: E402
from salad_studio.flet_services import AppServices  # noqa: E402
from tests._flet_window import TempStores, hidden_window, mount_opened, shown_texts  # noqa: E402


def run_inline(work, done) -> None:
    """``AppServices.background`` on the calling thread, its failure shown as the result."""
    try:
        result = work()
    except Exception as exc:  # noqa: BLE001 - the service shows a worker's failure
        result = exc
    done(result)


class Case(unittest.TestCase):
    def setUp(self) -> None:
        stores = TempStores()
        stores.__enter__()
        self.addCleanup(stores.__exit__, None, None, None)
        # List cleanups run in reverse, so this runs before the window's.
        inline = mock.patch.object(AppServices, "background", new=staticmethod(run_inline))
        inline.start()
        self.addCleanup(inline.stop)
        self.win, self.page = hidden_window()
        mount_opened(self.win)
        self.addCleanup(self.win.services.stop)

    def logs(self) -> object:
        return self.win.open_page("Logs")

    def studio_pane(self) -> list[str]:
        page = self.logs()
        page.refresh_lines()
        return shown_texts(page.studio_lines)

    def salad_pane(self) -> list[str]:
        page = self.logs()
        page.refresh_lines()
        return shown_texts(page.salad_lines)


class BothPanesMaskSecrets(Case):
    def test_a_container_log_line_is_masked_in_both_panes(self) -> None:
        secret = "hf_FIRSTSECRETVALUE1234"
        tokens.write_token("huggingface", secret)
        line = f"container stdout:\nHF_TOKEN={secret}\nready"
        self.win.services.set_salad_logs(line)
        self.win.log("info", line)
        self.logs()

        salad = "\n".join(self.salad_pane())
        studio = "\n".join(self.studio_pane())
        self.assertNotIn(secret, salad, f"the container pane leaked the token: {salad!r}")
        self.assertNotIn(secret, studio, f"the Studio pane leaked the token: {studio!r}")
        self.assertIn("…", salad, "the token is masked, not dropped")
        self.assertIn("…", studio)
        self.assertIn("ready", salad, "the rest of the container output is still shown")

    def test_a_token_written_after_the_cache_is_warm_is_masked_too(self) -> None:
        first = "hf_FIRSTSECRETVALUE1234"
        second = "civitai_SECONDT0KENvalue"
        tokens.write_token("huggingface", first)
        self.win.log("info", f"HF_TOKEN={first}")
        self.assertEqual(len(self.win.services.log_secrets()), 1, "the list is read and cached")

        tokens.write_token("civitai", second)
        self.win.services.set_salad_logs(f"civitai token {second}")
        self.win.log("info", f"civitai token {second}")
        self.logs()

        salad = "\n".join(self.salad_pane())
        studio = "\n".join(self.studio_pane())
        self.assertNotIn(second, salad, f"the container pane leaked the new token: {salad!r}")
        self.assertNotIn(second, studio, f"the Studio pane leaked the new token: {studio!r}")
        self.assertIn("…", salad)
        self.assertIn("…", studio)

    def test_logging_does_not_reread_the_token_store_once_the_cache_is_warm(self) -> None:
        real = tokens.read_token
        self.win.log("info", "warm")
        with mock.patch.object(tokens, "read_token", side_effect=real) as read:
            for _ in range(5):
                self.win.log("info", "warm log line")
            self.assertEqual(read.call_count, 0, "log() re-read the token store every line")

        self.win.open_page("Tokens").fields["salad"].value = "salad-test-key-1234"
        self.win.shell.pages["Tokens"].save_key()
        read.reset_mock()
        self.win.log("info", "after save")
        self.assertEqual(read.call_count, 0)

    def test_a_saved_key_is_masked_in_the_log_from_the_next_line(self) -> None:
        self.win.log("info", "before")
        tokens.write_token("salad", "salad-new-key-4321")
        self.win.log("info", "key salad-new-key-4321 used")
        self.assertIn("…", self.studio_pane()[-1])
        self.assertNotIn("salad-new-key-4321", "\n".join(self.studio_pane()))

    def test_the_logs_page_shows_a_quiet_pane_instead_of_nothing(self) -> None:
        self.assertEqual(self.salad_pane(), ["(nothing fetched yet)"])


class ClosingStopsTheTimers(Case):
    def test_start_timers_arms_one_shot_and_two_repeating_timers(self) -> None:
        pump = mock.Mock()
        pump.every.return_value = 2
        pump.call_later.return_value = 1
        services = AppServices(pump)
        services.start_timers()
        self.assertEqual(pump.call_later.call_args.args[0], 500, "a first silent probe after 500 ms")
        periods = [call.args[0] for call in pump.every.call_args_list]
        self.assertEqual(periods, [flet_services.SALAD_POLL_MS, flet_services.GEN_TICK_MS])

    def test_close_cancels_both_timers_and_refuses_work_after_it(self) -> None:
        pump = mock.Mock()
        pump.every.side_effect = [11, 22]
        services = AppServices(pump)
        services.start_timers()
        services.stop()
        self.assertEqual(sorted(call.args[0] for call in pump.cancel.call_args_list), [11, 22])
        self.assertTrue(services.closing)
        with mock.patch.object(services, "check_salad") as probe:
            services._salad_tick()
            services._gen_tick_fn()
        probe.assert_not_called()

    def test_the_window_close_event_stops_the_timers_and_remembers_the_page(self) -> None:
        from salad_studio import ui_state

        self.win.shell.open("Queue")
        with mock.patch.object(self.win.services, "stop") as stop:
            flet_app._on_window_event(self.win, type("E", (), {"type": "close"})())
        stop.assert_called_once_with()
        self.assertEqual(ui_state.load_state().get("tab"), "Queue")

    def test_another_window_event_leaves_the_timers_alone(self) -> None:
        with mock.patch.object(self.win.services, "stop") as stop:
            flet_app._on_window_event(self.win, type("E", (), {"type": "move"})())
        stop.assert_not_called()

    def test_a_worker_hands_its_result_back_after_background_returns(self) -> None:
        services = AppServices(Pump())
        seen: dict = {}

        async def scenario() -> None:
            services.background(lambda: "done", lambda result: seen.update(result=result))
            for _ in range(100):
                if seen:
                    break
                await asyncio.sleep(0.01)

        asyncio.run(scenario())
        self.assertEqual(seen.get("result"), "done")

    def test_a_failing_worker_hands_its_exception_back(self) -> None:
        services = AppServices(Pump())
        seen: dict = {}

        def work() -> None:
            raise OSError("offline")

        async def scenario() -> None:
            services.background(work, lambda result: seen.update(result=result))
            for _ in range(100):
                if seen:
                    break
                await asyncio.sleep(0.01)

        asyncio.run(scenario())
        self.assertIsInstance(seen.get("result"), OSError)


class TheProbe(Case):
    def test_an_empty_gateway_still_probes_every_profile_gateway(self) -> None:
        from salad_studio import salad_status

        self.win.form.gateway = ""
        want = {p.gateway for p in profiles.load_all().values() if p.gateway}
        snap = {"word": "Ready", "detail": "", "log_lines": []}
        with mock.patch.object(salad_status, "snapshot_gateway", return_value=snap) as probe:
            self.win.services.check_salad()
        self.assertEqual({call.args[0] for call in probe.call_args_list}, want)
        self.assertEqual(self.win.services.salad_word, "Ready")
        self.assertEqual(self.win.salad_label.value, "Ready")

    def test_a_stopped_group_reads_down(self) -> None:
        snapped = {"klein": {"word": "Stopped", "group": {"status": "stopped"}}}
        with mock.patch.object(self.win.services, "snaps", snapped):
            self.win.refresh_strip()
        self.assertEqual(len(self.win.strip_counts), 3)
        self.assertTrue(all(isinstance(label.value, str) for label in self.win.strip_counts))



if __name__ == "__main__":
    unittest.main()
