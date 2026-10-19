"""The real app entry path, built headless, with the persistence paths in a temp dir.

Nothing maps a window and no client is connected. ``flet_app.build`` runs
against a page that answers ``add`` and ``update`` by recording them, and the
startup probe is replaced so the build opens no socket. Two builds must agree:
the window opens on Config, the rail lists all eleven pages, every page builds
from the shipped stores and a real line lands in the log sink, and a SNOFS
graph routes to the SNOFS group. The last check presses Generate twice with the
first render still in flight: the second press must wait, not be dropped.
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
for _p in (HERE / ".." / "salad_studio", HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Package-qualified on purpose: the window holds salad_studio.profiles, and this
# repo can load the same module twice (top-level and as a package), so patching
# the other copy would move paths the window never reads.
from salad_studio import (  # noqa: E402
    flet_app, flet_services, flet_shell, image_deploy, lora_store, profiles,
    prompt_catalog, prompt_history, request_json, salad_queue, studio_meta,
    tokens as tok, ui_state, vast,
)

# The window imports the queue top-level; this module holds the package copy.
# The window's shared instance lives on the first, so it is reached by name.
SERVICES_QUEUE = sys.modules["salad_queue"]


class FakePage:
    """An ``ft.Page`` stand-in with no client: ``add`` and ``update`` record instead of sending."""

    def __init__(self) -> None:
        self.title = ""
        self.window = type("Window", (), {})()
        self.controls: list = []
        self.overlay: list = []
        self.adds = 0
        self.updates = 0
        self.on_keyboard_event = None

    def add(self, *controls) -> None:
        self.adds += 1
        self.controls.extend(controls)

    def update(self, *controls) -> None:
        self.updates += 1


class _TempPaths:
    """Every path the window reads or writes, moved into a temp directory.

    The metadata document is pinned to a non-existent user file as well, so the
    launch check always runs against the shipped routing table.
    """

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp

    def __enter__(self):
        # Two copies of salad_queue exist in a test process: the window imports
        # it top-level while some tests import it as salad_studio.salad_queue, so
        # both have to be redirected or one of them writes the real config.
        import salad_queue as top_queue

        from salad_studio import salad_queue as pkg_queue

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
            "ledger": top_queue.LEDGER_PATH,
            "ledger_pkg": pkg_queue.LEDGER_PATH,
            "vast": vast.INSTANCES_PATH,
            "images": image_deploy.SETTINGS_PATH,
            "out": flet_services.OUT_DIR,
            "shared": salad_queue._SHARED,
            "services_shared": SERVICES_QUEUE._SHARED,
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
        ledger = self.tmp / "studio-queue.json"
        top_queue.LEDGER_PATH = ledger
        pkg_queue.LEDGER_PATH = ledger
        # A fresh shared queue per window: a test window must not see the jobs a
        # previous test left on the module's one queue. The window's queue lives
        # on the top-level module, not on the package's copy.
        salad_queue._SHARED = None
        SERVICES_QUEUE._SHARED = None
        # The Vast.ai page reads this file at construction, and its engine
        # choice decides where Generate POSTs: no test may read the real one.
        vast.INSTANCES_PATH = self.tmp / "studio-vast.json"
        # The Images page reads the user's own images and extra environment.
        image_deploy.SETTINGS_PATH = self.tmp / "studio-images.json"
        # Plates and the history strip read this tree.
        flet_services.OUT_DIR = self.tmp / "out"
        studio_meta.reset_cache()
        return self

    def __exit__(self, *_exc) -> None:
        import salad_queue as top_queue

        from salad_studio import salad_queue as pkg_queue

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
        top_queue.LEDGER_PATH = self.saved["ledger"]
        pkg_queue.LEDGER_PATH = self.saved["ledger_pkg"]
        vast.INSTANCES_PATH = self.saved["vast"]
        image_deploy.SETTINGS_PATH = self.saved["images"]
        flet_services.OUT_DIR = self.saved["out"]
        salad_queue._SHARED = self.saved["shared"]
        SERVICES_QUEUE._SHARED = self.saved.get("services_shared")
        studio_meta.reset_cache()


def _build() -> tuple[object, FakePage]:
    """The window the app opens on, built without a client and with no network.

    The queue is one object per process, so a second window in the same run
    starts from whatever the first left in it; each build starts from empty.
    """
    from salad_studio import salad_queue as queue_mod

    queue = queue_mod.shared()
    queue.clear_finished()
    page = FakePage()
    with mock.patch.object(flet_services.AppServices, "check_salad", lambda *a, **k: None), \
            mock.patch.object(flet_services.AppServices, "run_idle_check", lambda *a, **k: None):
        win = flet_app.build(page, show=False)
    return win, page


def _marked(win) -> str:
    """The rail button the shell marks as open."""
    marked = [name for name, button in win.shell.buttons.items()
              if button.bgcolor == win.shell.colors["primary_container"]]
    return marked[0] if len(marked) == 1 else ",".join(marked)


def _pump(win, predicate, seconds: float = 15.0) -> bool:
    """Run the window's own frame pump until ``predicate`` holds."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        win.pump._run_due()
        jobs, win.pump._jobs = win.pump._jobs, []
        for fn, args, kwargs in jobs:
            fn(*args, **kwargs)
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class LaunchCheck(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    @staticmethod
    def _snofs_graph() -> dict:
        return {
            "prompt": {
                "70": {
                    "class_type": "UNETLoader",
                    "inputs": {"unet_name": request_json.UNET_SNOFS},
                }
            }
        }

    def _run_once(self) -> dict:
        win, page = _build()
        run: dict = {"adds": page.adds, "first_page": _marked(win)}
        # A page built but never shown: the shell is on the page, the first
        # page is open, and no page control has been sent anywhere.
        win.services.log("info", "launch probe line")
        sink = "\n".join(text for _level, text in win.services.log_lines)
        allp = profiles.load_all()
        route, refusal = profiles.plan_route(self._snofs_graph(), allp["klein"], allp)
        doc = studio_meta.default()
        opened: dict[str, str] = {}
        build_errors: dict[str, str] = {}
        for name in flet_shell.TAB_ORDER:
            try:
                win.shell.open(name)
                opened[name] = type(win.shell.pages[name]).__name__
            except Exception as exc:  # noqa: BLE001 - reported, not raised here
                build_errors[name] = f"{type(exc).__name__}: {exc}"
        run.update(
            rail=[button.name for button in win.shell.buttons.values()],
            opened=opened,
            build_errors=build_errors,
            sink_has_line="launch probe line" in sink,
            profiles=sorted(allp),
            routed=route.name if route is not None else f"refused: {refusal}",
            gateway=route.profile.gateway if route is not None else "",
            meta_source=doc["source"],
            meta_error=doc["error"],
        )
        win.services.stop()
        return run

    def test_two_launches_agree(self) -> None:
        with _TempPaths(self.tmp):
            first = self._run_once()
            second = self._run_once()
        print(json.dumps({"first": first, "second": second}, indent=2))

        self.assertEqual(first, second, "the two launches must agree")
        for run in (first, second):
            self.assertEqual(run["rail"], list(flet_shell.TAB_ORDER), "the rail holds the eleven pages")
            self.assertEqual(run["first_page"], "Config", "the window opens on Config")
            self.assertEqual(run["adds"], 1, "the shell is added to the page exactly once")
            self.assertEqual(run["build_errors"], {}, "every page must build without a client")
            self.assertEqual(run["opened"]["Queue"], "QueuePage")
            self.assertTrue(run["sink_has_line"], "the log sink missed a driven line")
            self.assertEqual(run["profiles"], ["klein", "klein5090"])
            self.assertEqual(run["routed"], "klein5090", "a SNOFS graph must reach the SNOFS group")
            self.assertEqual(run["meta_error"], "", "the metadata document must load cleanly")

    def test_generate_routes_a_snofs_graph_off_the_klein_group(self) -> None:
        """The same decision through the window's own Generate handler."""
        with _TempPaths(self.tmp):
            tok.write_token("salad", "launch-probe-key")
            win, _page = _build()
            allp = profiles.load_all()
            klein, snofs = allp["klein"], allp["klein5090"]
            win.ensure_page("Prompt Editor").json.value = json.dumps(self._snofs_graph())
            win.form.name, win.form.gateway = klein.name, klein.gateway
            seen: dict = {}

            def gather(payload, profile, key, checksum):
                seen.update(profile=profile, key=key, checksum=checksum)

            with mock.patch.object(win.services, "generate", side_effect=gather):
                win.generate()

            self.assertEqual(seen["profile"].gateway, snofs.gateway,
                             "the press must send the SNOFS request to the SNOFS group")
            self.assertEqual(seen["profile"].name, "klein5090")
            self.assertEqual(seen["key"], "launch-probe-key")
            self.assertNotEqual(seen["checksum"], "", "the request is digested before it is queued")
            self.assertEqual(win.dialogs, [], "a routed press is not refused")
            self.assertTrue(win.gen_state.value.startswith("Starting"), win.gen_state.value)

    def test_a_press_during_a_render_waits_in_the_queue(self) -> None:
        """Press 2 while press 1 is in flight: it is queued, never dropped.

        The window's worker seam runs the real worker on a thread of its own
        and counts it. Every render is held at the transport until the test
        lets it go, so the first is in flight for both presses.
        """
        first_post = threading.Event()
        release = threading.Event()
        both_done = threading.Event()
        lock = threading.Lock()
        workers: list[threading.Thread] = []
        posts: list[str] = []

        def transport(url, key=None, data=None, timeout=30):
            if str(url).endswith("/ready"):
                return 200, b"ok"
            with lock:
                posts.append(str(url))
            # The container is up but its one Comfy instance is mid-render:
            # this POST hangs until the test lets the render finish.
            first_post.set()
            release.wait(30)
            return 200, json.dumps({"images": ["QUJD"]}).encode()

        with _TempPaths(self.tmp):
            tok.write_token("salad", "queue-probe-key")
            win, _page = _build()
            allp = profiles.load_all()
            editor = win.ensure_page("Prompt Editor")
            editor.json.value = json.dumps(self._snofs_graph())
            win.form.name, win.form.gateway = "klein", allp["klein"].gateway

            def counted_background(_self, work, done):
                def run(work=work, done=done) -> None:
                    done(work())
                    with lock:
                        if len(workers) == 2:
                            both_done.set()
                worker = threading.Thread(target=run, daemon=True, name=f"generate-{len(workers) + 1}")
                workers.append(worker)
                worker.start()

            # The key probe must answer at once: an unauthorized reply outside a
            # running loop leaves an SDK thread behind that outlives the test.
            win.services.gen_queue.lifecycle.is_running = lambda _profile, _gateway: True
            with mock.patch("salad_studio.generator.salad_gen._req", side_effect=transport), \
                    mock.patch.object(flet_services.AppServices, "background", counted_background):
                try:
                    win.gen_button.on_click(None)
                    self.assertTrue(_pump(win, first_post.is_set, 30),
                                    "the first press never reached /prompt")
                    self.assertEqual(win.gen_state.value, "Starting…")

                    other = self._snofs_graph()
                    other["prompt"]["9"] = {
                        "class_type": "SaveImage",
                        "inputs": {"filename_prefix": "second", "images": ["70", 0]},
                    }
                    editor.json.value = json.dumps(other)
                    win.gen_button.on_click(None)
                    self.assertEqual(len(workers), 2, "the second press was dropped, not queued")
                    self.assertEqual(win.gen_state.value, "Queued…",
                                     "the second press reports it is waiting")
                finally:
                    release.set()
                    for worker in workers:
                        worker.join(30)
                    self.assertTrue(_pump(win, both_done.is_set, 30), "both renders never finished")

            self.assertTrue(win.gen_state.value.endswith("render(s) still queued")
                            or win.gen_state.value.startswith("Done in"), win.gen_state.value)
            self.assertNotEqual(workers[0], threading.main_thread(), "a render runs off the page thread")
            jobs = win.services.gen_queue.jobs()
            self.assertEqual([job.state for job in jobs], [salad_queue.ACCEPTED, salad_queue.ACCEPTED],
                             "both presses must end accepted")
            self.assertEqual(jobs[0].attempts, 1, "the held POST is accepted, not re-sent")
            self.assertEqual(jobs[1].attempts, 1, "the queued press POSTs once")
            self.assertNotEqual(jobs[1].checksum, jobs[0].checksum,
                                "the second press must be a different request")
            with lock:
                self.assertEqual(len(posts), 2, "each press reaches /prompt once")
