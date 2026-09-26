"""The real app entry path, run twice, with the persistence paths in a temp dir.

Constructing the window hidden is the closest this Windows-only Tk app gets to
a user launch. Two runs must agree: construction succeeds, the tab set is the
11 tabs, the log sink receives a real line, and a SNOFS graph routes to the
SNOFS group. A pass on one run and an empty result on the other is an app
defect, not noise to average away. The last check presses Generate twice with
the first render still in flight: the second press must wait in the app's own
queue, not be dropped.
"""
from __future__ import annotations

import base64
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

# Package-qualified on purpose: the app holds salad_studio.profiles, and this
# repo can load the same module twice (top-level and as a package), so patching
# the other copy would move paths the app never reads.
from salad_studio import lora_store, profiles, prompt_catalog, prompt_history, studio_meta  # noqa: E402
from salad_studio import tokens as tok  # noqa: E402
from salad_studio import ui_state  # noqa: E402

# Top-level, the opposite of the imports above and for the same reason: the app
# and the generator hold THIS copy of salad_queue, so the queue a test installs
# on the app must be built from this one too.
import salad_queue  # noqa: E402

TABS = (
    "Config",
    "Prompt Settings",
    "Policy",
    "Tokens",
    "LoRAs",
    "Prompt Editor",
    "Prompt Assist",
    "Prompt Catalog",
    "Import",
    "Prompt History",
    "Queue",
    "Logs",
)

# 2x2 JPEG (SOF0 height/width = 2): what a fake transport hands back as a plate.
_PLATE_B64 = base64.b64encode(
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00"
    b"\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b"
    b"\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \","
    b"#\x1c\x1c(7),01444\x1f'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x02\x00\x02\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x7f?\xff\xd9"
).decode("ascii")

try:
    import tkinter as tk
except ImportError as _tk_err:
    tk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = _tk_err
else:
    _TK_IMPORT_ERROR = None


class _Inline:
    """A Thread stand-in that runs the worker on the calling thread."""

    def __init__(self, target=None, **_kwargs) -> None:
        self._target = target

    def start(self) -> None:
        if self._target is not None:
            self._target()


def _pump(app, predicate, seconds: float) -> bool:
    """Run the app's own event loop until ``predicate`` holds or time runs out.

    A render worker hands its result back with ``after(0, ...)``, and Tk only
    accepts that call while the main thread is inside Tk, so waiting on an Event
    here would stall the very thread being waited for. ``predicate=None`` pumps
    for the full ``seconds``, which is how a background callback is let land.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate is not None and predicate():
            return True
        app.update()
        time.sleep(0.02)
    return predicate is not None and bool(predicate())


class _TempPaths:
    """Every path the app reads or writes, moved into a temp directory.

    The metadata document is pinned to a non-existent user file as well, so the
    launch check always runs against the shipped routing table.
    """

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp

    def __enter__(self):
        self.saved = {
            "profiles": profiles.PROFILES_PATH,
            "gw_klein": profiles.GATEWAY_KLEIN_PATH,
            "gw_5090": profiles.GATEWAY_KLEIN_5090_PATH,
            "extras": lora_store.EXTRAS_PATH,
            "catalog": prompt_catalog.CATALOG_PATH,
            "history": prompt_history.HISTORY_PATH,
            "thumbs": prompt_history.THUMBS_DIR,
            "tokens": tok.LOCAL_PATH,
            "config_home": tok.CONFIG_HOME,
            "state": ui_state.STATE_PATH,
            "meta": studio_meta.USER_PATH,
        }
        profiles.PROFILES_PATH = self.tmp / "studio-profiles.json"
        profiles.GATEWAY_KLEIN_PATH = self.tmp / "gateway-klein"
        profiles.GATEWAY_KLEIN_5090_PATH = self.tmp / "gateway-klein-5090"
        lora_store.EXTRAS_PATH = self.tmp / "studio-loras.json"
        prompt_catalog.CATALOG_PATH = self.tmp / "studio-prompt-catalog.json"
        prompt_history.HISTORY_PATH = self.tmp / "studio-prompt-history.json"
        prompt_history.THUMBS_DIR = self.tmp / "thumbs"
        tok.LOCAL_PATH = self.tmp / "studio-tokens.json"
        tok.CONFIG_HOME = self.tmp / "defaults"
        ui_state.STATE_PATH = self.tmp / "studio-ui.json"
        studio_meta.USER_PATH = self.tmp / "studio-metadata.json"
        studio_meta.reset_cache()
        return self

    def __exit__(self, *_exc) -> None:
        profiles.PROFILES_PATH = self.saved["profiles"]
        profiles.GATEWAY_KLEIN_PATH = self.saved["gw_klein"]
        profiles.GATEWAY_KLEIN_5090_PATH = self.saved["gw_5090"]
        lora_store.EXTRAS_PATH = self.saved["extras"]
        prompt_catalog.CATALOG_PATH = self.saved["catalog"]
        prompt_history.HISTORY_PATH = self.saved["history"]
        prompt_history.THUMBS_DIR = self.saved["thumbs"]
        tok.LOCAL_PATH = self.saved["tokens"]
        tok.CONFIG_HOME = self.saved["config_home"]
        ui_state.STATE_PATH = self.saved["state"]
        studio_meta.USER_PATH = self.saved["meta"]
        studio_meta.reset_cache()


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class LaunchCheck(unittest.TestCase):
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

    @staticmethod
    def _snofs_graph() -> dict:
        return {
            "prompt": {
                "70": {
                    "class_type": "UNETLoader",
                    "inputs": {"unet_name": profiles.SNOFS_UNET},
                }
            }
        }

    def _run_once(self) -> dict:
        from salad_studio.app import SaladStudio

        app = SaladStudio(show=False)
        app.withdraw()
        try:
            app.update_idletasks()
            tabs = tuple(app.nb.tab(i, "text") for i in range(len(app.nb.tabs())))
            app.log("info", "launch probe line")
            sink = app.log_text.get("1.0", "end")
            allp = profiles.load_all()
            route, refusal = profiles.plan_route(self._snofs_graph(), allp["klein"], allp)
            doc = studio_meta.default()
            return {
                "tabs": tabs,
                "sink_has_line": "launch probe line" in sink,
                "sink_has_boot": "Salad Studio started" in sink,
                "profiles": sorted(allp),
                "routed": route.name if route is not None else f"refused: {refusal}",
                "gateway": route.profile.gateway if route is not None else "",
                "meta_source": doc["source"],
                "meta_error": doc["error"],
            }
        finally:
            app.destroy()

    def test_two_launches_agree(self) -> None:
        with _TempPaths(self.tmp):
            first = self._run_once()
            second = self._run_once()
        print(json.dumps({"first": first, "second": second}, indent=2))

        self.assertEqual(first, second, "the two launches must agree")
        for run in (first, second):
            self.assertEqual(run["tabs"], TABS)
            self.assertTrue(run["sink_has_boot"], "the log sink missed the boot line")
            self.assertTrue(run["sink_has_line"], "the log sink missed a driven line")
            self.assertEqual(run["profiles"], ["klein", "klein5090"])
            self.assertEqual(
                run["routed"], "klein5090", "a SNOFS graph must reach the SNOFS group"
            )
            self.assertEqual(run["meta_error"], "", "the metadata document must load cleanly")

    def test_the_live_app_routes_a_snofs_graph_off_the_klein_group(self) -> None:
        """The same decision through the app's own Generate handler."""
        from salad_studio import app as app_mod

        with _TempPaths(self.tmp):
            tok.write_token("salad", "launch-probe-key")
            app = app_mod.SaladStudio(show=False)
            app.withdraw()
            try:
                app.update_idletasks()
                allp = profiles.load_all()
                klein, snofs = allp["klein"], allp["klein5090"]
                app.editor_text.delete("1.0", "end")
                app.editor_text.insert("1.0", json.dumps(self._snofs_graph()))
                app._rebuild_from_json()
                app.var_gateway.set(klein.gateway)
                app.var_salad_status.set("Ready")
                seen: dict = {}

                def fake_generate(**kwargs):
                    seen.update(kwargs)
                    raise RuntimeError("routing check only")

                with mock.patch.object(
                    app_mod.generator, "generate_from_payload", side_effect=fake_generate
                ), mock.patch.object(app_mod.messagebox, "showerror"), mock.patch(
                    "salad_studio.app.threading.Thread", _Inline
                ):
                    app._on_generate()
                    deadline = time.time() + 10
                    while time.time() < deadline and app._busy:
                        app.update()
                        time.sleep(0.02)
                self.assertEqual(seen.get("gateway"), snofs.gateway)
                self.assertIs(
                    seen.get("queue"),
                    app.gen_queue,
                    "the render must go through the app's own queue",
                )
            finally:
                app.destroy()

    def test_a_press_during_a_render_waits_in_the_queue(self) -> None:
        """Press 2 while press 1 is in flight: queued behind it, never dropped."""
        from salad_studio import app as app_mod

        first_post = threading.Event()
        container_free = threading.Event()
        lock = threading.Lock()
        posts: list[str] = []
        accepted: list[str] = []

        def transport(url, key=None, data=None, timeout=30):
            if str(url).endswith("/ready"):
                return 200, b"ok"
            with lock:
                posts.append(str(url))
                first = len(posts) == 1
            if first:
                # The container is up but its one Comfy instance is mid-render:
                # this POST hangs until the test lets the render finish, then
                # answers 503, which is the queue's signal to try again.
                first_post.set()
                if not container_free.wait(30):
                    raise AssertionError("the test never released the container")
                return 503, b'{"title": "replica unavailable"}'
            with lock:
                accepted.append(str(url))
            return 200, json.dumps({"images": [_PLATE_B64]}).encode()

        with _TempPaths(self.tmp), tempfile.TemporaryDirectory() as out_td:
            tok.write_token("salad", "queue-probe-key")
            app = app_mod.SaladStudio(show=False)
            app.withdraw()
            # The steps run inside mainloop(), because a render worker reports
            # back with after(0, ...) and Tk refuses that call unless the main
            # thread is in its loop. The body pumps update() for every wait.
            outcome: list[BaseException] = []
            ran: list[bool] = []
            try:
                with mock.patch.object(
                    app_mod.salad_status,
                    "snapshot_gateway",
                    # A stubbed replica probe: no network in a test, and a Ready
                    # replica is what leaves Generate pressable.
                    return_value={
                        "word": "Ready",
                        "detail": "stubbed probe",
                        "ready_ok": True,
                    },
                ), mock.patch.object(
                    app_mod.generator.salad_gen, "_req", side_effect=transport
                ), mock.patch.object(
                    app_mod, "OUT_DIR", Path(out_td)
                ), mock.patch.object(
                    app_mod.messagebox, "showerror"
                ), mock.patch.object(
                    app_mod.messagebox, "showinfo"
                ):

                    def body() -> None:
                        ran.append(True)
                        try:
                            app.update_idletasks()
                            allp = profiles.load_all()
                            app.editor_text.delete("1.0", "end")
                            app.editor_text.insert("1.0", json.dumps(self._snofs_graph()))
                            app._rebuild_from_json()
                            app.var_gateway.set(allp["klein"].gateway)
                            app.var_salad_status.set("Ready")
                            # The app's own queue, with the retry sleep removed so
                            # the retry happens at once instead of 8 s later.
                            app.gen_queue = salad_queue.SaladQueue(
                                on_log=app.log, sleep=lambda _s: None
                            )
                            app._apply_generate_gate("Ready")
                            self.assertEqual(
                                str(app.gen_btn.cget("state")),
                                "normal",
                                "a Ready replica must leave Generate pressable",
                            )
                            app.gen_btn.invoke()
                            self.assertTrue(
                                _pump(app, first_post.is_set, 60),
                                "the first press never reached /prompt",
                            )
                            app.gen_btn.invoke()
                            try:
                                self.assertEqual(
                                    app._gen_jobs,
                                    2,
                                    "the second press was dropped, not queued",
                                )
                                self.assertTrue(
                                    _pump(
                                        app,
                                        lambda: len(app.gen_queue.jobs()) >= 2,
                                        15,
                                    ),
                                    "the second press never reached the queue",
                                )
                                queued = app.gen_queue.jobs()
                                self.assertFalse(
                                    queued[1].terminal,
                                    "the queued press must still be waiting",
                                )
                                with lock:
                                    self.assertEqual(
                                        len(posts),
                                        1,
                                        "the queued press POSTed while the first "
                                        "render was still in flight",
                                    )
                            finally:
                                # Free the container even when an assertion above
                                # fired, so no worker outlives the fake transport.
                                container_free.set()
                                _pump(app, lambda: not app._busy, 60)
                            jobs = app.gen_queue.jobs()
                            self.assertFalse(app._busy, "both renders never finished")
                            self.assertEqual(
                                [job.state for job in jobs],
                                [salad_queue.ACCEPTED, salad_queue.ACCEPTED],
                                "both presses must end accepted",
                            )
                            self.assertEqual(
                                jobs[0].attempts,
                                2,
                                "the busy POST must be retried once",
                            )
                            self.assertEqual(
                                jobs[1].attempts, 1, "the queued press POSTs once"
                            )
                            with lock:
                                self.assertEqual(
                                    len(accepted), 2, "two renders must be submitted"
                                )
                        except BaseException as exc:  # noqa: BLE001 - re-raised below
                            outcome.append(exc)
                        finally:
                            # The app probes the replica 500 ms after it opens.
                            # Let that land while the stub is still installed, so
                            # no real request leaves the test and no callback
                            # thread outlives the window.
                            _pump(app, None, 1.0)
                            app.quit()

                    app.after(0, body)
                    app.mainloop()
                self.assertTrue(ran, "the test body never ran")
                if outcome:
                    raise outcome[0]
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
