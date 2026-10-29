"""The Logs page: every Studio line with its level in text, and the container's log.

The page reads two things the services already hold: the Studio lines, which
are masked as they are logged, and the container's log with a version. The two
Salad actions are background work; their probes are replaced here.
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

import profiles  # noqa: E402
from salad_studio.web.core import Core  # noqa: E402
from salad_studio.web.events import Hub  # noqa: E402
from salad_studio.web.pages import logs as logs_page  # noqa: E402
from salad_studio.web.pages.logs import EMPTY_SALAD_TEXT, LogsController  # noqa: E402
from salad_studio.web.registry import ActionContext, Controllers  # noqa: E402
from salad_studio.web.services import WebServices  # noqa: E402


class Home:
    """What a Shell holds for Logs, without the plates a Shell builds on startup."""

    def __init__(self, core) -> None:
        self.core = core
        self.hub = Hub()
        self.busy: dict[str, bool] = {}
        self.note_line = None
        self.editor = None
        self.services = WebServices(self)

    def next_reply_id(self) -> str:
        return "r1"

    def publish_done(self, action_id, ctx, result) -> None:
        ctx.is_pending = False
        ctx.done = True
        if ctx.settle is not None:
            ctx.settle(result)


class LogsPageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (profiles.PROFILES_PATH, logs_page.salad_status.recent_log_lines,
                      logs_page.salad_status.snapshot_gateway)
        profiles.PROFILES_PATH = Path(self.tmp.name) / "studio-profiles.json"
        self.asked: dict[str, str] = {}

        def recent(key: str, *, group_name: str, **kw):
            self.asked["group"] = group_name
            return "line one\nline two"

        logs_page.salad_status.recent_log_lines = recent
        logs_page.salad_status.snapshot_gateway = lambda gateway, key: {"word": "Running"}
        self.core = Core(workers=2).start()
        self.hub = Hub()
        self.studio = Home(self.core)
        self.studio.controllers = Controllers(self.studio)
        self.page = LogsController(self.studio)
        self.studio.controllers.add(self.page)

    def tearDown(self) -> None:
        self.core.stop()
        (profiles.PROFILES_PATH, logs_page.salad_status.recent_log_lines,
         logs_page.salad_status.snapshot_gateway) = self.saved
        self.tmp.cleanup()

    def call(self, action: str, args: dict | None = None):
        ctx = ActionContext(self.studio, "logs", action, args or {})
        result = self.studio.controllers.table.call(f"logs.{action}", dict(args or {}), ctx=ctx)
        self.assertIsNone(result.error, result.error)
        return result.data, ctx

    def set_gateway(self) -> None:
        profiles.upsert(profiles.SaladProfile(name="klein", gateway="https://g.example"))

    def settle(self, ctx) -> None:
        # The work runs off thread; its outcome comes back on the core thread,
        # and an empty call on core is answered only after that outcome.
        deadline = time.monotonic() + 15
        while not getattr(ctx, "done", False) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.core.call(lambda: None)
        self.assertFalse(self.studio.busy)
        self.assertFalse(ctx.is_pending)

    def test_each_studio_line_carries_its_level_as_text(self) -> None:
        self.studio.services.log("warn", "the replica is still starting")
        self.studio.services.log("ok", "request 7 accepted")
        state, _ctx = self.call("view")
        self.assertEqual([line["level"] for line in state["lines"]], ["warn", "ok"])
        self.assertIn("the replica is still starting", state["lines"][0]["text"])
        self.assertEqual(set(state), {"lines", "salad", "salad_state", "token_states"})

    def test_the_container_log_starts_empty_and_says_so(self) -> None:
        state, _ctx = self.call("view")
        self.assertEqual(state["salad"]["text"], "")
        self.assertEqual(state["salad"]["empty_text"], EMPTY_SALAD_TEXT)
        self.assertEqual(state["salad"]["version"], 0)

    def test_clear_drops_the_studio_lines_and_leaves_the_container_log(self) -> None:
        services = self.studio.services
        services.log("info", "one")
        services.set_salad_logs("container output")
        state, ctx = self.call("clear")
        self.assertEqual(state["lines"], [])
        self.assertEqual(state["salad"]["text"], "container output")
        self.assertIn("cleared", ctx.note_text[0])

    def test_refresh_salad_logs_fetches_in_background_and_bumps_the_version(self) -> None:
        self.set_gateway()
        _state, ctx = self.call("refresh_salad_logs")
        self.assertTrue(ctx.is_pending)
        self.settle(ctx)
        state, _ctx = self.call("view")
        self.assertEqual(state["salad"]["version"], 1)
        self.assertEqual(state["salad"]["text"], "line one\nline two")
        self.assertEqual(state["salad"]["empty_text"], "")
        self.assertEqual(self.asked["group"], "klein")

    def test_refresh_without_a_gateway_says_so_in_the_state_not_the_log(self) -> None:
        _state, ctx = self.call("refresh_salad_logs")
        self.settle(ctx)
        state, _ctx = self.call("view")
        self.assertEqual(state["salad"]["text"], "", "the notice is not the container's log")
        self.assertEqual(state["salad"]["version"], 0, "nothing was fetched, so no new version")
        self.assertEqual(state["salad_state"], "No profile has a gateway, so there is no container log to read.")
        self.assertEqual(ctx.note_text[1], "warn")

    def test_check_salad_reports_each_profile_with_a_gateway(self) -> None:
        self.set_gateway()
        _state, ctx = self.call("check_salad")
        self.settle(ctx)
        state, _ctx = self.call("view")
        self.assertEqual(state["salad_state"], "klein: Running")


if __name__ == "__main__":
    unittest.main()
