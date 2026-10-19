"""The Flet foundation: theme contrast in both modes, and a frame loop that coalesces."""
from __future__ import annotations

import asyncio
import threading
import unittest

import flet as ft

from salad_studio import flet_theme
from salad_studio.flet_pump import Pump


class Theme(unittest.TestCase):
    def test_no_text_role_falls_below_the_contrast_bar(self) -> None:
        self.assertEqual(flet_theme.check_contrast(), [])

    def test_both_modes_are_material_3_and_seeded_from_the_studio_palette(self) -> None:
        light = flet_theme._theme(flet_theme.LIGHT, flet_theme.LIGHT_CANVAS, False)
        dark = flet_theme._theme(flet_theme.DARK, flet_theme.DARK_CANVAS, True)
        self.assertTrue(light.use_material3)
        self.assertTrue(dark.use_material3)
        self.assertEqual(dark.color_scheme.surface, "#1B2836")
        self.assertEqual(dark.color_scheme.primary, "#E39AA9")
        self.assertNotEqual(light.color_scheme.surface, dark.color_scheme.surface)

    def test_spacing_scale_has_four_steps(self) -> None:
        self.assertEqual(sorted(flet_theme.GAP.values()), [4, 8, 12, 16])


class PumpBehaviour(unittest.TestCase):
    def test_a_worker_thread_schedules_and_the_loop_runs_it(self) -> None:
        async def scenario() -> tuple[list[str], int]:
            pump = Pump(interval=0.02)
            runner = asyncio.create_task(pump.run())
            seen: list[str] = []
            loop = asyncio.get_running_loop()

            def worker() -> None:
                for i in range(20):
                    loop.call_soon_threadsafe(pump.schedule, seen.append, str(i))

            threading.Thread(target=worker).start()
            await asyncio.sleep(0.25)
            pump.schedule(seen.append, "job")
            await asyncio.sleep(0.15)
            runner.cancel()
            return seen, pump.frames

        seen, frames = asyncio.run(scenario())
        self.assertEqual(seen[-1], "job")
        self.assertEqual(sorted(seen[:-1], key=int), [str(i) for i in range(20)])
        self.assertGreaterEqual(frames, 1)

    def test_timers_run_once_or_every_interval_and_cancel(self) -> None:
        async def scenario() -> tuple[list[str], list[str]]:
            pump = Pump(interval=0.01)
            runner = asyncio.create_task(pump.run())
            once: list[str] = []
            often: list[str] = []
            pump.call_later(10, once.append, "one")
            timer = pump.every(20, often.append, "tick")
            await asyncio.sleep(0.12)
            pump.cancel(timer)
            await asyncio.sleep(0.06)
            runner.cancel()
            return once, often

        once, often = asyncio.run(scenario())
        self.assertEqual(once, ["one"])
        self.assertGreaterEqual(len(often), 3)
        self.assertLessEqual(len(often), 6)


if __name__ == "__main__":
    unittest.main()
