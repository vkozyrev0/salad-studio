"""The Config page and the surfaces its handlers reach.

It drives Config profiles and their checkpoint lists and policy, Import Convert,
Generate's refusals, the idle container stop, Tokens "Check keys", LoRA
"Remove extra", and the Prompt History delete.

Every assertion reads the store back off disk or the page's own widgets, so a
control that changes nothing in the document fails here.
"""
from __future__ import annotations

import inspect
import json
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "salad_studio"
for _p in (PKG, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio import image_deploy  # noqa: E402
from salad_studio import profiles  # noqa: E402
from salad_studio import request_json  # noqa: E402
from salad_studio import salad_queue  # noqa: E402
from salad_studio import salad_status  # noqa: E402
from salad_studio import studio_meta  # noqa: E402
from salad_studio import tokens as tok  # noqa: E402
from salad_studio import vast  # noqa: E402
from tests import _nomodal  # noqa: E402
from tests.test_launch import _Inline, _TempPaths  # noqa: E402
from tests.test_salad_queue import _FakeLifecycle  # noqa: E402

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError as _tk_err:
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = _tk_err
else:
    _TK_IMPORT_ERROR = None


def _pump(app, predicate, seconds: float = 15.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        app.update()
        time.sleep(0.02)
    return predicate()


def _destroy_quietly(app) -> None:
    """Destroy a window, tolerating one a test already closed itself."""
    try:
        app.destroy()
    except tk.TclError:
        pass


def _ancestors(widget) -> list:
    """The widget's ancestors, innermost first, ending at the toplevel."""
    out = []
    node = getattr(widget, "master", None)
    while node is not None:
        out.append(node)
        node = getattr(node, "master", None)
    return out


def _old_form(func, edits: list[tuple[str, str]]):
    """The shipped function with a pass's edits undone: the old handler, rebuilt.

    ``edits`` are (shipped text, the text it replaced) pairs, applied to the
    source ``inspect.getsource`` returns. The old behaviour is therefore rebuilt
    from the shipped file rather than copied into a literal that could drift
    away from it, and a test can drive it to show what the fix changed.
    """
    source = textwrap.dedent(inspect.getsource(func))
    for new, old in edits:
        assert new in source, f"{func.__name__} no longer holds {new!r}"
        source = source.replace(new, old, 1)
    namespace: dict = {}
    exec(compile(source, f"<old {func.__name__}>", "exec"), func.__globals__, namespace)
    return namespace[func.__name__]


@contextmanager
def _allow_destructive_confirm():
    """Opt in to a destructive yes. The guard refuses those unless a test sets it."""
    previous = _nomodal.DESTRUCTIVE_ANSWER
    _nomodal.DESTRUCTIVE_ANSWER = True
    try:
        yield
    finally:
        _nomodal.DESTRUCTIVE_ANSWER = previous


class _HeldThread:
    """A Thread stand-in that does not run the worker: the test decides when.

    ``_Inline`` runs a worker on the calling thread, which is how a check is
    finished here, but it cannot leave a check in flight long enough for a
    second press. This one holds the worker until the test runs it, so the busy
    window is real and the handoff still goes through Tk's own ``after``.
    """

    held: list = []

    def __init__(self, target=None, **_kwargs) -> None:
        self.target = target
        _HeldThread.held.append(self)

    def start(self) -> None:
        pass


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class ConfigPage(unittest.TestCase):
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
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(_destroy_quietly, self.app)
        self.app.update_idletasks()

    # -- helpers ----------------------------------------------------------
    def _doc(self) -> dict:
        return json.loads(profiles.PROFILES_PATH.read_text(encoding="utf-8"))

    def _stored(self, name: str) -> dict:
        return self._doc()["profiles"][name]

    def _listed(self) -> list[str]:
        return [str(v) for v in self.app.profile_combo["values"]]

    def _rows(self) -> list[tuple[str, str]]:
        tree = self.app.checkpoint_tree
        return [tuple(str(v) for v in tree.item(i, "values")) for i in tree.get_children()]

    def _select(self, name: str) -> None:
        self.app.var_name.set(name)
        self.app._on_select_profile()

    # -- profile management ----------------------------------------------
    def test_the_page_adds_configures_and_removes_a_profile(self) -> None:
        app = self.app
        self.assertEqual(sorted(self._doc()["profiles"]), ["klein", "klein5090"])

        app.var_name.set("studio3")
        app.var_gateway.set("https://third.example.salad.cloud")
        app._on_add_profile()

        self.assertIn("studio3", self._listed(), "the page must list the added profile")
        added = self._stored("studio3")
        self.assertEqual(added["gateway"], "https://third.example.salad.cloud")
        self.assertTrue(added["checkpoints"], "a new profile is seeded with checkpoints")
        self.assertEqual(profiles.get_active(), "studio3")
        self.assertEqual(
            set(dict(app._status_targets())),
            {"klein", "klein5090", "studio3"},
            "every profile is probed, and the one strip counts them all",
        )
        # The strip is rebuilt with the profile set: it must survive the change.
        self.assertTrue(app._strip.winfo_exists(), "the strip is rebuilt, not dropped")
        self.assertIs(app._strip.master, app._replica_holder)
        self.assertEqual(len(app._strip_dots), 3, "still three segments, not one per profile")

        app.var_gateway.set("https://configured.example.salad.cloud")
        app._save_profile()
        self.assertEqual(
            self._stored("studio3")["gateway"], "https://configured.example.salad.cloud"
        )

        with _allow_destructive_confirm():
            app._delete_profile()
        self.assertNotIn("studio3", self._doc()["profiles"])
        self.assertNotIn("studio3", self._listed())
        self.assertEqual(set(dict(app._status_targets())), {"klein", "klein5090"})

    def test_removing_the_last_profile_leaves_the_app_usable(self) -> None:
        app = self.app
        for name in ("klein", "klein5090"):
            self._select(name)
            with _allow_destructive_confirm():
                app._delete_profile()
        self.assertEqual(sorted(self._doc()["profiles"]), ["klein"])
        self.assertEqual(self._listed(), ["klein"])
        self.assertTrue(app._status_targets(), "the app must still have a target")

    def test_the_page_lists_every_configured_profile(self) -> None:
        app = self.app
        for name in ("third", "fourth"):
            app.var_name.set(name)
            app._on_add_profile()
        self.assertEqual(self._listed(), ["fourth", "klein", "klein5090", "third"])
        self.assertEqual(len(app._status_targets()), 4)

    def test_config_sub_tabs_follow_the_registry(self) -> None:
        """The Config page's sub-tabs are the registry labels, in registry order."""
        app = self.app
        labels = [app._config_tabs.tab(t, "text") for t in app._config_tabs.tabs()]
        expected = [label for _key, label, _builder in self.app_mod.CONFIG_SECTIONS]
        self.assertEqual(labels, expected)
        self.assertEqual(labels, ["Profile", "Images", "Salad group", "Vast.ai"])
        self.assertEqual(
            tuple(key for key, _label, _builder in self.app_mod.CONFIG_SECTIONS),
            ("profile", "images", "policy", "vast"),
        )

    def test_each_config_section_holds_its_own_controls(self) -> None:
        """Each section's controls live on that section's tab, under `_config`."""
        app = self.app
        cases = (
            ("profile", ("checkpoint_tree", "profile_combo")),
            ("images", ("image_box", "image_env_tree", "image_script")),
            ("policy", ("_policy_section", "pol_image_box")),
            ("vast", ("vast_tree", "vast_image_box")),
        )
        for key, names in cases:
            page = app._config_section_pages[key]
            self.assertIn(
                app._config,
                _ancestors(page),
                f"the {key} tab page must descend from _config",
            )
            for name in names:
                widget = getattr(app, name)
                ancs = _ancestors(widget)
                self.assertIn(page, ancs, f"{name} must live on the {key} tab")
                self.assertIn(
                    app._config, ancs, f"{name} must still descend from _config"
                )

    def test_the_config_status_note_is_on_the_page_not_a_section(self) -> None:
        """A refusal on one tab stays visible whichever section is selected."""
        app = self.app
        want = str(app.var_config_note)
        note = None
        for child in app._config.winfo_children():
            try:
                if str(child.cget("textvariable")) == want:
                    note = child
                    break
            except tk.TclError:
                continue
        self.assertIsNotNone(note, "the status note must be a child of _config")
        self.assertIs(note.master, app._config)
        for key, page in app._config_section_pages.items():
            self.assertNotIn(
                page,
                _ancestors(note),
                f"the status note must not live on the {key} tab",
            )

    def test_the_window_opens_wide_enough_that_images_needs_no_hscroll(self) -> None:
        """The canvas request sizes the window so Images fits without a sideways bar."""
        app = self.app
        self.assertGreaterEqual(
            int(app.winfo_reqwidth()),
            self.app_mod.PAGE_OPENING_WIDTH,
            "the app's requested width must be at least PAGE_OPENING_WIDTH",
        )
        width = int(app.winfo_reqwidth())
        height = int(app.winfo_reqheight())
        try:
            app.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        app.geometry(f"{width}x{height}")
        app.deiconify()
        deadline = time.time() + 10.0
        while time.time() < deadline:
            app.update()
            if app.winfo_width() > 100 and app.winfo_height() > 100:
                break
            time.sleep(0.02)
        app._opened_width, app._opened_height = width, height
        app.geometry(f"{width}x{height}")
        for _ in range(5):
            app.update()
            time.sleep(0.02)
        app.update_idletasks()
        app._goto_tab("Config")
        app._config_tabs.select(app._config_section_pages["images"])
        app.update()
        app.update_idletasks()
        page = app._config_section_pages["images"]
        canvas = app._scroll_canvases[page]
        body = app._config_section_bodies["images"]
        self.assertGreaterEqual(
            int(canvas.winfo_width()),
            int(body.winfo_reqwidth()),
            "at the opening size the Images tab's canvas viewport must be wide "
            "enough that it needs no horizontal scrollbar",
        )

    def test_opening_a_config_section_refreshes_what_it_reads(self) -> None:
        """A key saved on Tokens reaches Images the moment its tab opens."""
        app = self.app
        tok.write_token("huggingface", "hf_saved_after_the_page_was_built")
        app._config_tabs.select(app._config_section_pages["images"])
        app.update()
        values = {
            str(app.image_env_tree.item(iid, "values")[0]): str(
                app.image_env_tree.item(iid, "values")[1]
            )
            for iid in app.image_env_tree.get_children()
        }
        self.assertIn(
            "HF_TOKEN", values, "the environment tree must list the documented entries"
        )
        self.assertNotEqual(
            values["HF_TOKEN"],
            "(missing)",
            "opening the Images tab must re-read the token store, or a key saved "
            "on Tokens stays invisible here",
        )

    # -- the config's own Salad policy ------------------------------------
    def test_a_config_owns_its_policy_and_the_policy_page_is_gone(self) -> None:
        """Each config stores and shows its own policy; no Policy tab, no global copy."""
        app = self.app
        labels = [app.nb.tab(t, "text") for t in app.nb.tabs()]
        self.assertEqual(labels, list(self.app_mod.TAB_ORDER))
        self.assertNotIn("Policy", labels, "the Policy page must be gone")
        self.assertNotIn("Policy", self.app_mod.TAB_ORDER)
        self.assertIn(
            app._config,
            _ancestors(app._policy_section),
            "the fields live on Config",
        )

        self._select("klein")
        app.var_pol_image.set("docker.io/example/klein:tag1")
        app.var_pol_us.set(True)
        app._pol_vars["startup"]["initial_delay_seconds"].set("120")
        app._pol_vars["startup"]["failure_threshold"].set("6")
        app._pol_vars["readiness"]["failure_threshold"].set("4")
        app._save_profile()

        stored = self._stored("klein")["policy"]
        self.assertEqual(stored["image"], "docker.io/example/klein:tag1")
        self.assertEqual(stored["country_codes"], ["us"])
        self.assertEqual(stored["startup"]["initial_delay_seconds"], "120")
        self.assertEqual(stored["startup"]["failure_threshold"], "6")
        self.assertEqual(stored["readiness"]["failure_threshold"], "4")
        # The other config keeps its own policy: the document's SNOFS settings, and
        # none of the fields typed above.
        other = self._stored("klein5090")["policy"]
        snofs = studio_meta.probe_settings_for_family("snofs", studio_meta.default())
        self.assertEqual(
            other["image"],
            studio_meta.image_for_family("snofs", studio_meta.default()),
        )
        self.assertEqual(
            other["startup"],
            snofs["startup"],
            "the other config carries its own family's documented probes",
        )
        self.assertNotIn("country_codes", other)

        self._select("klein5090")
        self.assertEqual(
            app.var_pol_image.get(),
            studio_meta.image_for_family("snofs", studio_meta.default()),
            "klein5090 shows its own image, never klein's",
        )
        self.assertNotEqual(app.var_pol_image.get(), "docker.io/example/klein:tag1")
        self.assertFalse(app.var_pol_us.get(), "klein's US-only must not follow")
        self.assertEqual(
            app._pol_vars["startup"]["failure_threshold"].get(),
            str(snofs["startup"]["failure_threshold"]),
            "and its own family's documented probe, not klein's saved one",
        )
        self.assertNotEqual(app._pol_vars["startup"]["failure_threshold"].get(), "6")

        self._select("klein")
        self.assertEqual(app.var_pol_image.get(), "docker.io/example/klein:tag1")
        self.assertTrue(app.var_pol_us.get())
        self.assertEqual(app._pol_vars["startup"]["failure_threshold"].get(), "6")

        state = app._capture_ui_state()
        self.assertEqual(
            [key for key in state if "policy" in key],
            [],
            "the policy must not be kept in the window's own state",
        )

    # -- switching re-checks that config's own group ----------------------
    def _group(self, name: str, dns: str, image: str, gpu: str, codes: list, startup_fail: int, readiness_fail: int) -> dict:
        """A Salad group payload shaped like the control plane's own."""
        return {
            "name": name,
            "version": 9,
            "networking": {"dns": dns},
            "container": {"image": image, "resources": {"gpu_classes": [gpu]}},
            "country_codes": codes,
            "startup_probe": {
                "http": {"path": "/health", "port": 3000},
                "initial_delay_seconds": 900,
                "period_seconds": 60,
                "timeout_seconds": 10,
                "failure_threshold": startup_fail,
            },
            "readiness_probe": {
                "http": {"path": "/ready", "port": 3000},
                "initial_delay_seconds": 0,
                "period_seconds": 10,
                "timeout_seconds": 5,
                "failure_threshold": readiness_fail,
            },
            "current_state": {"status": "running"},
        }

    def _recording_api(self, groups: dict[str, dict], classes: list[dict], calls: list) -> object:
        """A recorded transport: group lookups by name, the class list, nothing else."""

        def _api(method, url, key, data=None):
            calls.append((method, url, data))
            if url.endswith("/gpu-classes"):
                return 200, {"items": classes}
            if url.endswith("/containers"):
                return 200, {"items": list(groups.values())}
            for name, group in groups.items():
                if url.endswith(f"/{name}"):
                    return 200, group
            return 200, {}

        return _api

    def test_switching_config_repopulates_the_policy_from_that_configs_group(self) -> None:
        """Selecting a config re-reads its own group and fills the fields from it."""
        app = self.app
        allp = profiles.load_all()
        klein, other = allp["klein"], allp["klein5090"]
        klein_group = self._group(
            "flux2-klein2", urlparse(klein.gateway).hostname,
            "docker.io/example/klein:live", "gpu-klein", [], 20, 21,
        )
        other_group = self._group(
            "flux2-klein-5090", urlparse(other.gateway).hostname,
            "docker.io/example/snofs:live", "gpu-snofs", ["us"], 11, 12,
        )
        classes = [
            {"id": "gpu-klein", "name": "RTX 4090 (klein)"},
            {"id": "gpu-snofs", "name": "RTX 5090 (snofs)"},
        ]
        calls: list[str] = []
        tok.write_token("salad", "switch-key")
        klein_before = dict(self._stored("klein")["policy"])
        other_before = dict(self._stored("klein5090")["policy"])
        by_gateway = {
            f"https://{klein_group['networking']['dns']}": klein_group,
            f"https://{other_group['networking']['dns']}": other_group,
        }

        def _load(gw, key):
            """The shipped read the switch drives, recording which group it asked for."""
            calls.append(gw)
            group = by_gateway.get(str(gw))
            if group is None:
                return None, "No container group matches this gateway DNS."
            return salad_status.policy_from_group(group), None

        with mock.patch.object(
            self.app_mod.salad_status, "load_policy", side_effect=_load
        ), mock.patch.object(
            self.app_mod.salad_status, "list_gpu_classes", return_value=classes
        ), mock.patch.object(
            self.app_mod.salad_status, "snapshot_gateway", return_value={"word": "Ready"}
        ), mock.patch("salad_studio.app.threading.Thread", _Inline):
            self._select("klein")
            self.assertTrue(
                _pump(app, lambda: app.var_pol_image.get() == "docker.io/example/klein:live"),
                f"klein never filled: {app.var_pol_image.get()!r}",
            )
            calls.clear()
            self._select("klein5090")
            self.assertTrue(
                _pump(app, lambda: app.var_pol_image.get() == "docker.io/example/snofs:live"),
                f"klein5090 never filled: {app.var_pol_image.get()!r}",
            )
            switched = list(calls)
            self.assertTrue(
                _pump(app, lambda: app._pol_vars["readiness"]["failure_threshold"].get() == "12"),
                f"probe fields: {app._pol_vars['readiness']['failure_threshold'].get()!r}",
            )

        self.assertEqual(
            app._pol_vars["startup"]["initial_delay_seconds"].get(), "900"
        )
        self.assertEqual(app._pol_vars["readiness"]["period_seconds"].get(), "10")
        self.assertTrue(app.var_pol_us.get(), "that group's country codes")
        ticked = sorted(gid for gid, var in app._pol_gpu_vars.items() if var.get())
        self.assertEqual(ticked, ["gpu-snofs"], "that group's GPU classes, not klein's")
        self.assertIn(
            "RTX 5090 (snofs)",
            [str(name) for name in app._pol_gpu_names.values()],
            "the class list came from the live read",
        )
        # The switch read only that config's group.
        self.assertEqual(
            switched, [other.gateway], "the switch must read only the selected config's group"
        )
        # And it wrote no policy: both stored records still carry what they had.
        self.assertEqual(self._stored("klein")["policy"], klein_before)
        self.assertEqual(self._stored("klein5090")["policy"], other_before)

    def test_a_failed_recheck_leaves_the_documents_settings_standing(self) -> None:
        """A re-check that cannot read the group must not blank a field.

        The config's own stored policy and the metadata document's documented
        settings for its family are what is left on screen when the read fails.
        """
        app = self.app
        klein = profiles.load_all()["klein"]
        doc_image = studio_meta.image_for_family("klein", studio_meta.default())
        documented = studio_meta.probe_settings_for_family("klein", studio_meta.default())
        tok.write_token("salad", "failing-key")

        def _api(method, url, key, data=None):
            return 500, {"error": "boom"}

        with mock.patch.object(
            self.app_mod.salad_status, "_api_request", side_effect=_api
        ), mock.patch("salad_studio.app.threading.Thread", _Inline):
            self._select("klein")
            _pump(app, lambda: app.var_pol_image.get() == doc_image, 5)
        self.assertEqual(
            app.var_pol_image.get(), doc_image, "the document's image answers a failed read"
        )
        for kind in ("startup", "readiness"):
            with self.subTest(kind=kind):
                shown = {key: var.get() for key, var in app._pol_vars[kind].items()}
                self.assertEqual(
                    shown,
                    {key: str(value) for key, value in documented[kind].items()},
                    f"the document's documented {kind} settings must still be shown",
                )
                self.assertTrue(all(shown.values()), "and not one of them blank")
        self.assertEqual(
            self._stored("klein")["policy"]["image"], doc_image,
            "and the config keeps its own stored policy",
        )

    def test_a_new_config_is_seeded_with_the_documents_image(self) -> None:
        """Adding a config stores the metadata document's image for its family."""
        app = self.app
        app.var_name.set("studio3")
        app.var_gateway.set("https://third.example.salad.cloud")
        app._on_add_profile()
        stored = self._stored("studio3")["policy"]
        self.assertEqual(
            stored["image"],
            studio_meta.image_for_family("klein", studio_meta.default()),
            "a new config's image comes from the document",
        )
        self.assertEqual(
            app.var_pol_image.get(), stored["image"], "and the fields show it"
        )

    def test_a_switch_writes_no_record_and_a_failed_read_keeps_the_fields(self) -> None:
        """Switching fills the fields; only Save profile or Apply ever writes."""
        app = self.app
        doc_snofs = studio_meta.image_for_family("snofs", studio_meta.default())
        self._select("klein")
        app.var_pol_image.set("docker.io/example/klein:mine")
        app._pol_vars["startup"]["failure_threshold"].set("9")
        app._save_profile()
        klein_saved = dict(self._stored("klein")["policy"])
        other_saved = dict(self._stored("klein5090")["policy"])
        self.assertEqual(klein_saved["image"], "docker.io/example/klein:mine")
        tok.write_token("salad", "safety-key")

        def _api(method, url, key, data=None):
            return 500, {"error": "boom"}

        with mock.patch.object(
            self.app_mod.salad_status, "_api_request", side_effect=_api
        ), mock.patch.object(
            self.app_mod.salad_status, "snapshot_gateway", return_value={"word": "Down"}
        ), mock.patch("salad_studio.app.threading.Thread", _Inline):
            self._select("klein5090")
            _pump(app, lambda: app.var_pol_image.get() == doc_snofs, 5)
            self.assertEqual(
                app.var_pol_image.get(), doc_snofs,
                "an imageless config shows the document's image even when the read fails",
            )
            self._select("klein")
            _pump(app, lambda: app.var_pol_image.get() == "docker.io/example/klein:mine", 5)
            self.assertEqual(
                app.var_pol_image.get(), "docker.io/example/klein:mine",
                "a failed read keeps the config's own stored policy on screen",
            )
            self.assertEqual(app._pol_vars["startup"]["failure_threshold"].get(), "9")

        self.assertEqual(
            self._stored("klein")["policy"], klein_saved, "a switch must write no record"
        )
        self.assertEqual(self._stored("klein5090")["policy"], other_saved)

    def test_the_first_load_fills_every_policy_field_from_that_configs_group(self) -> None:
        """Opening on a config fills all twelve probe fields, not just the image.

        The window's first load is the case the user reported: the image came from
        the document and the probe fields stayed blank until a read answered.
        """
        app = self.app
        klein = profiles.load_all()["klein"]
        group = self._group(
            "flux2-klein2", urlparse(klein.gateway).hostname,
            "docker.io/example/klein:first", "gpu-klein", [], 17, 18,
        )
        reads: list[str] = []

        def _load(gw, key):
            reads.append(str(gw))
            return salad_status.policy_from_group(group), None

        tok.write_token("salad", "first-load-key")
        with mock.patch.object(
            self.app_mod.salad_status, "load_policy", side_effect=_load
        ), mock.patch.object(
            self.app_mod.salad_status, "list_gpu_classes", return_value=[]
        ), mock.patch.object(
            self.app_mod.salad_status, "snapshot_gateway", return_value={"word": "Ready"}
        ), mock.patch("salad_studio.app.threading.Thread", _Inline):
            self._select("klein")
            self.assertTrue(
                _pump(app, lambda: app.var_pol_image.get() == "docker.io/example/klein:first"),
                f"the first load never filled: {app.var_pol_image.get()!r}",
            )
        self.assertTrue(reads, "the first load must read the group")
        self.assertEqual(
            set(reads), {klein.gateway}, "every read names the selected config's group"
        )
        for kind, fail in (("startup", "17"), ("readiness", "18")):
            with self.subTest(kind=kind):
                shown = {key: var.get() for key, var in app._pol_vars[kind].items()}
                self.assertTrue(all(shown.values()), f"every {kind} field must be filled: {shown}")
                self.assertEqual(shown["failure_threshold"], fail, "the group's own value")
                self.assertEqual(shown["path"], "/health" if kind == "startup" else "/ready")

    def test_a_fresh_window_shows_the_documents_settings_before_any_read(self) -> None:
        """A config the store has nothing for still shows every field at once."""
        from salad_studio.app import SaladStudio

        documented = studio_meta.probe_settings_for_family("klein", studio_meta.default())
        self.app.destroy()
        self.app = SaladStudio(show=False)
        self.addCleanup(_destroy_quietly, self.app)
        self.app.withdraw()
        app = self.app
        app.update_idletasks()
        self.assertEqual(app.var_name.get().strip(), "klein", "the store's active config")
        self.assertEqual(
            app.var_pol_image.get(),
            studio_meta.image_for_family("klein", studio_meta.default()),
        )
        for kind in ("startup", "readiness"):
            with self.subTest(kind=kind):
                shown = {key: var.get() for key, var in app._pol_vars[kind].items()}
                self.assertEqual(
                    shown, {key: str(value) for key, value in documented[kind].items()}
                )

    def test_the_restored_config_is_the_one_whose_policy_is_shown(self) -> None:
        """A saved window state naming another config moves the fields with it."""
        from salad_studio import ui_state
        from salad_studio.app import SaladStudio

        allp = profiles.load_all()
        profiles.set_active("klein")
        ui_state.save_state({"profile": "klein5090", "tab": "Config", "gateway": allp["klein5090"].gateway})
        self.app.destroy()
        self.app = SaladStudio(show=False)
        self.addCleanup(_destroy_quietly, self.app)
        self.app.withdraw()
        app = self.app
        app.update_idletasks()
        self.assertEqual(
            app.var_name.get().strip(), "klein5090", "the restore names the config"
        )
        self.assertEqual(
            app.var_pol_image.get(),
            studio_meta.image_for_family("snofs", studio_meta.default()),
            "and the fields belong to that config, not to the store's active one",
        )
        self.assertEqual(
            [str(v) for v in app.checkpoint_tree.item(app.checkpoint_tree.get_children()[0], "values")][:1],
            [allp["klein5090"].primary_checkpoint],
            "the checkpoint list belongs to it too",
        )

    def test_the_restored_target_is_the_profiles_not_the_windows(self) -> None:
        """A stale window URL cannot pair a vast target with a Salad gateway."""
        from salad_studio import ui_state
        from salad_studio.app import SaladStudio

        prof = profiles.load_all()["klein5090"]
        prof.mode = "vast"
        prof.gateway = "http://10.0.0.9:40006"
        profiles.upsert(prof)
        ui_state.save_state(
            {
                "profile": "klein5090",
                "tab": "Config",
                "gateway": "https://stale.salad.cloud",
            }
        )
        self.app.destroy()
        self.app = SaladStudio(show=False)
        self.addCleanup(_destroy_quietly, self.app)
        self.app.withdraw()
        app = self.app
        app.update_idletasks()
        self.assertEqual(app.var_profile_mode.get(), "vast")
        self.assertEqual(
            app.var_gateway.get(),
            "http://10.0.0.9:40006",
            "the profile's target wins over the URL the window saved",
        )
        self.assertEqual(app.lbl_gateway.cget("text"), "Instance URL")

    def test_apply_to_salad_patches_this_configs_group_only(self) -> None:
        """Apply sends the selected config's policy to that config's group."""
        app = self.app
        allp = profiles.load_all()
        klein, other = allp["klein"], allp["klein5090"]
        self._select("klein")
        app.var_pol_image.set("docker.io/example/klein:tag2")
        app.var_pol_us.set(True)
        app._pol_vars["readiness"]["failure_threshold"].set("7")
        app._pol_vars["readiness"]["period_seconds"].set("20")

        calls: list[tuple[str, str, dict | None]] = []
        group = {
            "name": "flux2-klein2",
            "version": 4,
            "networking": {"dns": urlparse(klein.gateway).hostname},
            "container": {
                "image": "old:tag",
                "resources": {"cpu": 2, "memory": 4096, "gpu_classes": ["old-class"]},
            },
            "current_state": {"status": "running"},
        }

        def _api(method, url, key, data=None):
            calls.append((method, url, data))
            if url.endswith("/containers"):
                return 200, {"items": [group]}
            return 200, group

        tok.write_token("salad", "config-policy-key")
        with mock.patch.object(
            self.app_mod.salad_status, "_api_request", side_effect=_api
        ), mock.patch("salad_studio.app.threading.Thread", _Inline):
            app._apply_salad_policy()
            _pump(app, lambda: any(call[0] == "PATCH" for call in calls))
            _pump(app, lambda: "applied" in app.status.get())

        patches = [call for call in calls if call[0] == "PATCH"]
        self.assertEqual(len(patches), 1, f"exactly one PATCH: {calls}")
        _method, url, body = patches[0]
        self.assertIsNot(body, None)
        self.assertIn("flux2-klein2", url, "the PATCH must name this config's group")
        self.assertNotIn(
            urlparse(other.gateway).hostname,
            " ".join(call[1] for call in calls),
            "no call for the other config's group",
        )
        self.assertEqual(body["container"]["image"], "docker.io/example/klein:tag2")
        self.assertNotIn("resources", body["container"], "no GPU classes were ticked")
        self.assertEqual(body["country_codes"], ["us"])
        self.assertEqual(body["readiness_probe"]["failure_threshold"], 7)
        self.assertEqual(body["readiness_probe"]["period_seconds"], 20)
        self.assertEqual(body["startup_probe"]["http"]["path"], "/health")
        self.assertEqual(
            self._stored("klein")["policy"]["image"],
            "docker.io/example/klein:tag2",
            "the config keeps what it applied",
        )
        self.assertEqual(
            self._stored("klein5090")["policy"]["image"],
            studio_meta.image_for_family("snofs", studio_meta.default()),
            "the other config keeps its own image, untouched by the apply",
        )

    # -- checkpoint list --------------------------------------------------
    def test_the_page_adds_and_removes_a_checkpoint(self) -> None:
        app = self.app
        self._select("klein")
        before = profiles.load_all()["klein"].checkpoints
        self.assertEqual([row[0] for row in self._rows()], before)

        app.var_checkpoint.set("flux-2-klein-5b-fp8.safetensors")
        app._on_add_checkpoint()

        after = self._stored("klein")["checkpoints"]
        self.assertEqual(after, before + ["flux-2-klein-5b-fp8.safetensors"])
        self.assertEqual([row[0] for row in self._rows()], after, "the list shows the new entry")
        self.assertEqual(self._rows()[-1][1], "klein", "the family is shown next to it")

        # A graph loading the new checkpoint routes to that profile, no code edit.
        graph = {
            "prompt": {
                "70": {
                    "class_type": "UNETLoader",
                    "inputs": {"unet_name": "flux-2-klein-5b-fp8.safetensors"},
                }
            }
        }
        stored = profiles.load_all()
        route, refusal = profiles.plan_route(graph, stored["klein5090"], stored)
        self.assertEqual(refusal, "")
        self.assertIsNotNone(route)
        self.assertIsNot(route, None)
        self.assertEqual(route.name, "klein")

        iid = [
            i
            for i in app.checkpoint_tree.get_children()
            if app.checkpoint_tree.item(i, "values")[0] == "flux-2-klein-5b-fp8.safetensors"
        ][0]
        app.checkpoint_tree.selection_set(iid)
        app._on_remove_checkpoint()
        self.assertNotIn(
            "flux-2-klein-5b-fp8.safetensors", self._stored("klein")["checkpoints"]
        )
        self.assertEqual([row[0] for row in self._rows()], before)

    def test_a_checkpoint_of_another_family_is_added_with_a_warning(self) -> None:
        app = self.app
        self._select("klein5090")
        before = self._stored("klein5090")["checkpoints"]
        app.var_checkpoint.set("flux-2-klein-base-9b-fp8.safetensors")
        with mock.patch.object(self.app_mod.messagebox, "showwarning") as warn:
            app._on_add_checkpoint()
        self.assertTrue(warn.called, "the page must warn about the mixed list")
        self.assertIn("unet families", str(warn.call_args))
        after = self._stored("klein5090")["checkpoints"]
        self.assertEqual(after, [*before, "flux-2-klein-base-9b-fp8.safetensors"])

    def test_an_empty_entry_says_so_instead_of_adding_blank(self) -> None:
        app = self.app
        self._select("klein")
        before = self._stored("klein")["checkpoints"]
        app.var_checkpoint.set("   ")
        app._on_add_checkpoint()
        self.assertIn("Type a checkpoint", app.var_config_note.get())
        self.assertEqual(self._stored("klein")["checkpoints"], before)

    def test_the_target_radio_saves_and_reloads_with_the_profile(self) -> None:
        app = self.app
        name = (app.var_name.get() or "klein").strip()
        app.var_profile_mode.set("vast")
        app._on_profile_mode()
        app._save_profile()
        self.assertEqual(self._stored(name)["mode"], "vast")
        self.assertEqual(str(app.lbl_gateway.cget("text")), "Instance URL")
        self.assertEqual(str(app.btn_use_selected.cget("state")), "normal")
        app.var_profile_mode.set("salad")
        self._select(name)
        self.assertEqual(app.var_profile_mode.get(), "vast")
        self.assertEqual(app.var_profile_mode.get(), "vast")
        self.assertEqual(str(app.lbl_gateway.cget("text")), "Instance URL")

    def test_use_the_selected_instance_fills_the_url_or_says_none(self) -> None:
        app = self.app
        app.var_profile_mode.set("vast")
        app._on_profile_mode()
        app.var_gateway.set("")
        app._on_use_selected_instance()
        self.assertIn("instance", app.status.get().lower())
        self.assertEqual(app.var_gateway.get(), "")
        app.var_vast_new.set("203.0.113.9:31234")
        app._on_vast_add()
        app._on_use_selected_instance()
        self.assertEqual(app.var_gateway.get(), "http://203.0.113.9:31234")

    def test_a_vast_mode_profile_dispatches_without_the_salad_key(self) -> None:
        app = self.app
        Path(tok.LOCAL_PATH).unlink(missing_ok=True)
        self.assertEqual(tok.read_token("salad"), "")
        app.var_profile_mode.set("vast")
        app._on_profile_mode()
        app.var_vast_new.set("203.0.113.9:31234")
        app._on_vast_add()
        app.var_gateway.set("http://203.0.113.9:31234")
        seen: dict = {}

        def fake_vast(**kwargs):
            seen.update(kwargs)
            raise RuntimeError("dispatch check only")

        with mock.patch.object(
            self.app_mod.generator, "generate_from_vast", side_effect=fake_vast
        ), mock.patch.object(
            self.app_mod.generator, "generate_from_payload"
        ) as salad, mock.patch.object(
            self.app_mod.messagebox, "showerror"
        ), mock.patch(
            "salad_studio.app.threading.Thread", _Inline
        ):
            app._on_generate()
            _pump(app, lambda: not app._busy)
        self.assertEqual(salad.call_count, 0, "vast mode must not take the Salad path")
        self.assertEqual(seen.get("endpoint"), "http://203.0.113.9:31234")
        self.assertEqual(seen.get("line"), app.var_name.get())
        self.assertIs(seen.get("queue"), app.gen_queue)
        self.assertTrue(seen.get("checksum"))

    def test_the_replacement_policy_saves_and_reloads(self) -> None:
        app = self.app
        app.var_vast_replace.set(True)
        app.var_vast_price.set("0.42")
        app.var_vast_down.set("250")
        app.var_vast_up.set("120")
        app.var_vast_cuda.set("13.1")
        app.var_vast_reliability.set("0.97")
        app.var_vast_gpus.set("rtx 5090, RTX A6000")
        app._on_vast_save()
        policy = vast.load_doc()["replace"]
        self.assertEqual(
            policy,
            {
                "enabled": True,
                "max_price": 0.42,
                "min_down_mbps": 250.0,
                "min_up_mbps": 120.0,
                "cuda_min": 13.1,
                "min_reliability": 0.97,
                "gpu_names": ["RTX 5090", "RTX A6000"],
            },
        )
        self.assertTrue(app.var_vast_replace.get())

    def _vast_window(self) -> None:
        """Target vast.ai at one stored instance, with a replacement policy."""
        app = self.app
        tok.write_token("vast", "vast-key")
        tok.write_token("huggingface", "hf-key")
        app.var_profile_mode.set("vast")
        app._on_profile_mode()
        app.var_vast_new.set("203.0.113.9:31234")
        app._on_vast_add()
        app.var_gateway.set("http://203.0.113.9:31234")
        app.var_vast_replace.set(True)
        app.var_vast_price.set("0.50")
        app.var_vast_down.set("200")
        app.var_vast_up.set("100")
        app.var_vast_cuda.set("13")

    def test_a_gone_instance_is_replaced_and_the_press_does_not_post(self) -> None:
        app = self.app
        self._vast_window()
        created = {
            "action": "created",
            "contract": 777,
            "row": {
                "endpoint": "http://203.0.113.55:40111",
                "id": 777,
                "label": "salad-studio-klein",
                "image": "docker.io/example/klein:tag",
                "gpu": "RTX 4090",
                "state": "running",
            },
            "message": "created instance 777",
        }
        with mock.patch.object(
            self.app_mod.vast, "replace_destroyed", return_value=created
        ) as replace, mock.patch.object(
            self.app_mod.generator, "generate_from_vast"
        ) as post, mock.patch.object(
            self.app_mod.messagebox, "showerror"
        ), mock.patch(
            "salad_studio.app.threading.Thread", _Inline
        ):
            app._on_generate()
            _pump(app, lambda: not app._busy)
        self.assertFalse(post.called, "a created instance is not POSTed before it boots")
        self.assertTrue(replace.called)
        settings = replace.call_args.kwargs["settings"]
        self.assertTrue(settings["enabled"])
        self.assertEqual(app.var_gateway.get(), "http://203.0.113.55:40111")
        self.assertEqual(vast.load_doc()["active"], "http://203.0.113.55:40111")
        self.assertIn("created", app.status.get().lower())
        self.assertIn("ready", app.status.get().lower())

    def test_an_alive_instance_goes_straight_to_the_post(self) -> None:
        app = self.app
        self._vast_window()
        alive = {
            "action": "alive",
            "row": {
                "endpoint": "http://203.0.113.9:31234",
                "id": 1,
                "gpu": "RTX 4090",
                "state": "running",
            },
            "message": "the instance is alive",
        }
        seen: dict = {}

        def fake_vast(**kwargs):
            seen.update(kwargs)
            raise RuntimeError("dispatch check only")

        with mock.patch.object(
            self.app_mod.vast, "replace_destroyed", return_value=alive
        ), mock.patch.object(
            self.app_mod.generator, "generate_from_vast", side_effect=fake_vast
        ), mock.patch.object(
            self.app_mod.messagebox, "showerror"
        ), mock.patch(
            "salad_studio.app.threading.Thread", _Inline
        ):
            app._on_generate()
            _pump(app, lambda: not app._busy)
        self.assertEqual(seen.get("endpoint"), "http://203.0.113.9:31234")

    def test_a_dropped_apply_callback_clears_the_create_lock(self) -> None:
        """Generate's automatic path must not wedge the lock when _later fails."""
        app = self.app
        app.var_vast_image.set("docker.io/example/klein:tag")
        self._vast_window()
        alive = {
            "action": "alive",
            "row": {
                "endpoint": "http://203.0.113.9:31234",
                "id": 1,
                "gpu": "RTX 4090",
                "state": "running",
            },
            "message": "the instance is alive",
        }
        with mock.patch.object(
            self.app_mod.vast, "replace_destroyed", return_value=alive
        ), mock.patch.object(
            self.app_mod.generator,
            "generate_from_vast",
            return_value=Path(self.tmp) / "plate.jpg",
        ), mock.patch.object(
            app, "_later", return_value=None
        ), mock.patch(
            "salad_studio.app.threading.Thread", _Inline
        ):
            app._on_generate()
        self.assertFalse(
            app._vast_create_busy,
            "a callback that could not be scheduled must release the create lock",
        )

    def test_a_created_instance_without_an_endpoint_is_a_creating_row(self) -> None:
        """The contract is a durable row, not a one-slot pending shadow."""
        app = self.app
        app._vast_create_busy = True
        app._apply_vast_rent(
            {
                "action": "created",
                "contract": 777,
                "row": None,
                "label": "salad-studio-klein",
                "image": "docker.io/example/klein:tag",
                "message": "created instance 777; it has not mapped an endpoint yet",
            },
        )
        self.assertFalse(app._vast_create_busy)
        row = app._vast_doc["instances"][0]
        self.assertEqual(row["id"], 777)
        self.assertEqual(row["endpoint"], "")
        self.assertEqual(row["state"], "creating")
        self.assertEqual(row["label"], "salad-studio-klein")
        self.assertEqual(row["image"], "docker.io/example/klein:tag")
        self.assertEqual(app._vast_doc["pending"], {})
        self.assertEqual(vast.load_doc()["pending"], {})
        self.assertEqual(vast.load_doc()["instances"][0]["state"], "creating")
        self.assertIn("not mapped", app.status.get())

    # -- the rent panel --------------------------------------------------
    @staticmethod
    def _offer(offer_id: int, **overrides) -> dict:
        offer = {
            "id": offer_id,
            "gpu_name": "RTX 4090",
            "gpu_ram": 24576,
            "disk_space": 200,
            "cuda_max_good": 13.0,
            "inet_down": 500,
            "inet_up": 200,
            "dph_total": 0.40,
            "rentable": True,
            "reliability2": 0.99,
            "dlperf": 97.0,
            "dlperf_per_dphtotal": 250.0,
            "geolocation": "Testland, TL",
        }
        offer.update(overrides)
        return offer

    def _fill_offers(self, offers: list[dict]) -> None:
        """Put offers in the results table the way a search would."""
        app = self.app
        app._vast_offers = {str(offer["id"]): offer for offer in offers}
        for offer in offers:
            cells = vast.offer_cells(offer)
            app.vast_offer_tree.insert(
                "",
                "end",
                iid=str(offer["id"]),
                values=tuple(
                    cells[col]
                    for col, _heading, _width, _fill in self.app_mod.VAST_OFFER_GRID_COLUMNS
                ),
            )

    def test_the_rent_panel_starts_with_the_default_gpu_list(self) -> None:
        app = self.app
        self.assertEqual(app.var_vast_gpus.get(), "RTX 5090, RTX 4090")
        self.assertEqual(app.var_vast_reliability.get(), "0.95")

    def test_clearing_the_gpu_box_restores_the_defaults_before_the_search(self) -> None:
        app = self.app
        tok.write_token("vast", "vast-key")
        app.var_vast_gpus.set("  , ")
        seen: dict = {}

        def fake_search(key, criteria, **_kwargs):
            seen.update(criteria)
            return {"status": 200, "offers": [], "error": ""}

        with mock.patch.object(
            vast, "search_offers", side_effect=fake_search
        ), mock.patch("salad_studio.app.threading.Thread", _Inline):
            app._on_vast_search()
            self.assertTrue(_pump(app, lambda: not app._vast_search_busy))
        self.assertEqual(app.var_vast_gpus.get(), "RTX 5090, RTX 4090")
        self.assertEqual(seen["gpu_names"], ["RTX 5090", "RTX 4090"])
        self.assertEqual(
            vast.load_doc()["replace"]["gpu_names"], ["RTX 5090", "RTX 4090"]
        )

    def test_find_offers_lists_them_by_value_and_persists_the_criteria(self) -> None:
        app = self.app
        tok.write_token("vast", "vast-key")
        app.var_vast_gpus.set("RTX 5090, RTX 4090")
        low = self._offer(100, gpu_name="RTX 4090", dlperf_per_dphtotal=200.0)
        high = self._offer(200, gpu_name="RTX 5090", dlperf_per_dphtotal=500.0)
        result = {"status": 200, "offers": [low, high], "error": ""}
        with mock.patch.object(
            vast, "search_offers", return_value=result
        ), mock.patch("salad_studio.app.threading.Thread", _Inline):
            app._on_vast_search()
            self.assertTrue(_pump(app, lambda: not app._vast_search_busy))
        self.assertEqual(app.vast_offer_tree.get_children(), ("200", "100"))
        self.assertEqual(set(app._vast_offers), {"200", "100"})
        values = app.vast_offer_tree.item("200", "values")
        self.assertEqual(values[0], "RTX 5090", "the best value is the first row")
        self.assertEqual(values[3], "500")
        stored = vast.load_doc()["replace"]
        self.assertEqual(stored["gpu_names"], ["RTX 5090", "RTX 4090"])
        self.assertEqual(stored["min_reliability"], 0.95)
        self.assertIn("2 offer(s)", app.var_vast_offer_status.get())

    def test_renting_the_selected_offer_appends_and_activates_it(self) -> None:
        app = self.app
        tok.write_token("vast", "vast-key")
        name = app.var_name.get()
        app.var_profile_mode.set("vast")
        app._on_profile_mode()
        app._save_profile()
        app.var_vast_image.set("docker.io/example/klein:tag")
        self._fill_offers([self._offer(55818626, gpu_name="RTX 5090")])
        app.vast_offer_tree.selection_set("55818626")
        created = {
            "action": "created",
            "contract": 777,
            "row": {
                "endpoint": "http://203.0.113.55:40111",
                "id": 777,
                "label": "salad-studio-55818626",
                "image": "docker.io/example/klein:tag",
                "gpu": "RTX 5090",
                "state": "running",
            },
            "label": "salad-studio-55818626",
            "image": "docker.io/example/klein:tag",
            "message": "created instance 777 at http://203.0.113.55:40111",
        }
        with mock.patch.object(
            vast, "rent_offer", return_value=created
        ) as rent, mock.patch("salad_studio.app.threading.Thread", _Inline):
            app._on_vast_rent()
            self.assertTrue(_pump(app, lambda: not app._vast_create_busy))
        self.assertEqual(rent.call_args.args[1]["id"], 55818626)
        self.assertEqual(rent.call_args.kwargs["image"], "docker.io/example/klein:tag")
        self.assertEqual(rent.call_args.kwargs["label"], "salad-studio-55818626")
        self.assertEqual(vast.load_doc()["active"], "http://203.0.113.55:40111")
        self.assertEqual(
            [row["endpoint"] for row in vast.load_doc()["instances"]],
            ["http://203.0.113.55:40111"],
        )
        self.assertEqual(app.var_gateway.get(), "http://203.0.113.55:40111")
        self.assertEqual(
            profiles.load_all()[name].gateway, "http://203.0.113.55:40111"
        )

    def test_an_unmapped_rent_adds_a_creating_row_immediately(self) -> None:
        app = self.app
        tok.write_token("vast", "vast-key")
        app.var_vast_image.set("docker.io/example/klein:tag")
        self._fill_offers([self._offer(42, gpu_name="RTX 5090")])
        app.vast_offer_tree.selection_set("42")
        unmapped = {
            "action": "created",
            "contract": 777,
            "row": None,
            "label": "salad-studio-42",
            "image": "docker.io/example/klein:tag",
            "message": "created instance 777; it has not mapped an endpoint yet",
        }
        with mock.patch.object(
            vast, "rent_offer", return_value=unmapped
        ), mock.patch("salad_studio.app.threading.Thread", _Inline):
            app._on_vast_rent()
            self.assertTrue(_pump(app, lambda: not app._vast_create_busy))
        values = app.vast_tree.item("777", "values")
        self.assertEqual(values[2], "#777", "the row appears before its endpoint does")
        self.assertEqual(values[4], "creating")
        stored = vast.load_doc()["instances"]
        self.assertEqual([(row["id"], row["state"]) for row in stored], [(777, "creating")])
        self.assertEqual(vast.load_doc()["pending"], {})
        self.assertIn("has not mapped", app.status.get())

    def test_a_failed_search_is_reported_on_the_section_the_line_and_the_logs(
        self,
    ) -> None:
        app = self.app
        tok.write_token("vast", "vast-key")
        failed = {"status": 401, "offers": [], "error": "HTTP 401: invalid key"}
        with mock.patch.object(
            vast, "search_offers", return_value=failed
        ), mock.patch("salad_studio.app.threading.Thread", _Inline):
            app._on_vast_search()
            self.assertTrue(_pump(app, lambda: not app._vast_search_busy))
        note = app.var_vast_offer_status.get()
        self.assertIn("rejected", note)
        self.assertEqual(app.var_vast_status.get(), note)
        self.assertEqual(app.status.get(), note)
        self.assertIn("rejected", app.log_text.get("1.0", "end"))
        self.assertEqual(app.vast_offer_tree.get_children(), ())

    def test_the_offer_table_columns_are_the_cell_keys_in_order(self) -> None:
        cells = vast.offer_cells({"id": 1})
        self.assertEqual(
            tuple(cells),
            tuple(
                col
                for col, _heading, _width, _fill in self.app_mod.VAST_OFFER_GRID_COLUMNS
            ),
        )

    def test_the_create_lock_is_shared_by_rent_and_replace(self) -> None:
        app = self.app
        tok.write_token("vast", "vast-key")
        app.var_vast_image.set("docker.io/example/klein:tag")
        # An active instance with an image is what Replace needs to get past
        # its own guards, so a refusal here can only be the shared lock.
        app.var_vast_new.set("203.0.113.9:31234")
        app._on_vast_add()
        self.assertIsNotNone(app._vast_active(), "replace has a row to act on")
        self._fill_offers([self._offer(42)])
        app.vast_offer_tree.selection_set("42")
        unmapped = {
            "action": "created",
            "contract": 777,
            "row": None,
            "label": "salad-studio-42",
            "image": "docker.io/example/klein:tag",
            "message": "created instance 777; it has not mapped an endpoint yet",
        }
        with mock.patch.object(
            vast, "rent_offer", return_value=unmapped
        ), mock.patch.object(vast, "replace_destroyed") as replace, mock.patch(
            "salad_studio.app.threading.Thread", _HeldThread
        ):
            _HeldThread.held = []
            app._on_vast_rent()
            self.assertTrue(app._vast_create_busy, "rent takes the one create lock")
            app._on_vast_replace()
            self.assertFalse(replace.called, "replace waits for the same lock")
            self.assertEqual(
                app.var_vast_status.get(),
                "a replacement check is already running",
            )
            held = _HeldThread.held[-1]
            held.target()
            self.assertTrue(_pump(app, lambda: not app._vast_create_busy))

    def test_a_fetch_that_maps_the_creating_row_promotes_it(self) -> None:
        app = self.app
        name = app.var_name.get()
        app.var_profile_mode.set("vast")
        app._on_profile_mode()
        prof = profiles.load_all()[name]
        prof.mode = "vast"
        prof.gateway = ""
        profiles.upsert(prof)
        app.var_gateway.set("")
        doc = dict(app._vast_doc)
        doc["instances"] = [
            {
                "id": 777,
                "endpoint": "",
                "label": "salad-studio-42",
                "gpu": "RTX 5090",
                "state": "creating",
                "image": "docker.io/example/klein:tag",
            }
        ]
        doc["active"] = ""
        app._vast_doc = doc
        app._apply_vast_fetch(
            {
                "status": 200,
                "instances": [
                    {
                        "id": 777,
                        "label": "salad-studio-42",
                        "gpu_name": "RTX 5090",
                        "actual_status": "running",
                        "public_ipaddr": "203.0.113.77",
                        "ports": {"8188/tcp": [{"HostPort": 40111}]},
                    }
                ],
                "error": "",
            }
        )
        row = app._vast_doc["instances"][0]
        self.assertEqual(row["endpoint"], "http://203.0.113.77:40111")
        self.assertEqual(row["state"], "running")
        self.assertEqual(app._vast_doc["active"], "http://203.0.113.77:40111")
        self.assertEqual(row["image"], "docker.io/example/klein:tag")
        self.assertEqual(app._vast_doc["pending"], {})
        self.assertEqual(vast.load_doc()["pending"], {})
        self.assertEqual(
            profiles.load_all()[name].gateway,
            "http://203.0.113.77:40111",
            "the profile the user is on follows the promoted instance",
        )
        self.assertEqual(app.var_gateway.get(), "http://203.0.113.77:40111")

    # -- routing and the queue across profiles ----------------------------
    def _generate_with(self, graph_unet: str, form_profile: str) -> dict:
        """Drive the page's Generate for a graph, and report what it POSTed to."""
        app = self.app
        tok.write_token("salad", "config-page-key")
        stored = profiles.load_all()
        graph = {
            "prompt": {
                "70": {"class_type": "UNETLoader", "inputs": {"unet_name": graph_unet}}
            }
        }
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", json.dumps(graph))
        app._rebuild_from_json()
        app.var_gateway.set(stored[form_profile].gateway)
        app.var_salad_status.set("Ready")
        seen: dict = {}

        def fake_generate(**kwargs):
            seen.update(kwargs)
            raise RuntimeError("routing check only")

        with mock.patch.object(
            self.app_mod.generator, "generate_from_payload", side_effect=fake_generate
        ), mock.patch.object(self.app_mod.messagebox, "showerror"), mock.patch(
            "salad_studio.app.threading.Thread", _Inline
        ):
            app._on_generate()
            _pump(app, lambda: not app._busy)
        return seen

    def test_three_profiles_each_generate_to_their_own_gateway(self) -> None:
        app = self.app
        app.var_name.set("third")
        app.var_gateway.set("https://third.example.salad.cloud")
        app._on_add_profile()
        # A new profile is seeded with its family's cuts. Give this one a list of
        # its own so the graph's checkpoint names exactly one profile.
        seeded = profiles.load_all()["third"]
        seeded.checkpoints = []
        profiles.upsert(seeded)
        app._refresh_checkpoint_list(seeded)
        app.var_checkpoint.set("flux-2-klein-3b-fp8.safetensors")
        app._on_add_checkpoint()
        stored = profiles.load_all()
        self.assertEqual(stored["third"].checkpoints, ["flux-2-klein-3b-fp8.safetensors"])
        self.assertEqual(len(app._status_targets()), 3)

        cases = (
            (request_json.UNET_SNOFS, "klein", "klein5090"),
            ("flux-2-klein-3b-fp8.safetensors", "klein", "third"),
            ("flux-2-klein-base-9b-fp8.safetensors", "third", "klein"),
        )
        for unet, form, want in cases:
            with self.subTest(graph=unet, form=form):
                seen = self._generate_with(unet, form)
                self.assertEqual(
                    seen.get("gateway"),
                    stored[want].gateway,
                    f"a {unet} graph must POST to {want}",
                )
                self.assertEqual(seen.get("line"), want, "the queue line is the profile")

    def test_a_checkpoint_no_profile_lists_is_refused_on_the_page(self) -> None:
        app = self.app
        stored = profiles.load_all()
        graph = {
            "prompt": {
                "70": {
                    "class_type": "UNETLoader",
                    "inputs": {"unet_name": "no-such-checkpoint.safetensors"},
                }
            }
        }
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", json.dumps(graph))
        app._rebuild_from_json()
        app.var_gateway.set(stored["klein"].gateway)
        app.var_salad_status.set("Ready")
        with mock.patch.object(self.app_mod.messagebox, "showerror") as err:
            app._on_generate()
        self.assertTrue(err.called, "the page must refuse and say why")
        self.assertIn("No profile lists", str(err.call_args))
        self.assertFalse(app._busy)

    # -- the images the app deploys ----------------------------------------
    def _config_texts(self) -> list[str]:
        """Every string the Config page shows, from its own widgets."""
        from tkinter import ttk

        out: list[str] = []

        def walk(widget) -> None:
            if isinstance(widget, ttk.Combobox):
                out.extend(str(v) for v in widget.cget("values"))
            if isinstance(widget, ttk.Treeview):
                for item in widget.get_children():
                    out.extend(str(v) for v in widget.item(item, "values"))
            try:
                text = widget.cget("text")
            except tk.TclError:
                text = ""
            if text:
                out.append(str(text))
            try:
                variable = widget.cget("textvariable")
            except tk.TclError:
                variable = ""
            if variable:
                out.append(str(self.app.getvar(variable)))
            if isinstance(widget, tk.Text):
                out.append(widget.get("1.0", "end"))
            for child in widget.winfo_children():
                walk(child)

        walk(self.app._config)
        return out

    def test_both_salad_images_are_on_the_config_page_with_their_deployment(self) -> None:
        """Both tags the document ships, with what a host needs, on one page."""
        from salad_studio import image_deploy, studio_meta

        entries = {e["key"]: e for e in image_deploy.entries(studio_meta.default(), None)}
        self.assertEqual(sorted(entries), ["klein", "snofs"])
        app = self.app
        self.assertEqual(
            sorted(str(v) for v in app.image_box["values"]),
            ["klein", "snofs"],
            "the page picks one image per unet family",
        )
        self.assertEqual(
            sorted(str(v) for v in app.pol_image_box["values"]),
            sorted(entry["tag"] for entry in entries.values()),
            "the policy image field offers the document's tags",
        )

        for family, entry in sorted(entries.items()):
            with self.subTest(family=family):
                app.var_image_key.set(family)
                app._on_image_pick()
                app.update_idletasks()
                shown = "\n".join(self._config_texts())
                self.assertIn(entry["tag"], shown, "the tag must be shown on the page")
                self.assertIn(entry["build_arg"], shown, "with its build arg")
                self.assertIn(entry["context"], shown, "and its build context")
                for key in (studio_meta.PORT_API, studio_meta.PORT_COMFY):
                    self.assertIn(
                        str(entry["ports"][key]), shown, f"port {key} must be shown"
                    )
                for name in ("HF_TOKEN", "CIVITAI_API_TOKEN", "STARTUP_CHECK_MAX_TRIES"):
                    self.assertIn(name, shown, f"{name} must be shown")
                self.assertIn(entry["gpu"], shown, "and the GPU class")

    # -- container lifecycle ----------------------------------------------
    def _prepare_snofs_generate(self, app) -> tuple[str, str]:
        """A SNOFS graph on the klein form, so routing picks klein5090."""
        stored = profiles.load_all()
        graph = {
            "prompt": {
                "70": {
                    "class_type": "UNETLoader",
                    "inputs": {"unet_name": request_json.UNET_SNOFS},
                }
            }
        }
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", json.dumps(graph))
        app._rebuild_from_json()
        app.var_gateway.set(stored["klein"].gateway)
        app.var_salad_status.set("Ready")
        return "klein5090", stored["klein5090"].gateway

    def _render_once(self, app) -> list[str]:
        """Drive one Generate to completion inside a mainloop; returns the POST urls."""
        posts: list[str] = []
        outcome: list[BaseException] = []

        def _req(url, key=None, data=None, timeout=30):
            if str(url).endswith("/ready"):
                return 200, b"ok"
            posts.append(str(url))
            return 200, json.dumps({"images": ["QUJD"]}).encode()

        with tempfile.TemporaryDirectory() as out_td, mock.patch.object(
            self.app_mod.generator.salad_gen, "_req", side_effect=_req
        ), mock.patch.object(self.app_mod, "OUT_DIR", Path(out_td)), mock.patch.object(
            self.app_mod.messagebox, "showerror"
        ):

            def body() -> None:
                try:
                    app._on_generate()
                    self.assertTrue(
                        _pump(app, lambda: not app._busy, 30), "the render never finished"
                    )
                except BaseException as exc:  # noqa: BLE001 - re-raised below
                    outcome.append(exc)
                finally:
                    app.quit()

            app.after(0, body)
            app.mainloop()
        if outcome:
            raise outcome[0]
        return posts

    def _tick(self, app) -> None:
        """Run the app's own timer once, with the status probe stubbed."""
        with mock.patch.object(
            self.app_mod.salad_status,
            "snapshot_gateway",
            lambda gw, key: {"word": "Ready", "detail": ""},
        ):
            app._poll_salad_status()

    def _write_stale_ledger(self, profile: str, gateway: str) -> None:
        """A record as the app wrote it before it recorded who started a container.

        Its activity time is hours old, so the idle stop would fire immediately
        if the app treated that record as its own.
        """
        path = Path(salad_queue.LEDGER_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "containers": {
                        profile: {
                            "gateway": gateway,
                            "last_active": time.time() - 10 * 3600,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def _queue_on_the_users_container(self, app, running: dict) -> _FakeLifecycle:
        """The app's queue, on the redirected ledger, with a recording container handle."""
        fake = _FakeLifecycle(running)
        app.gen_queue = salad_queue.SaladQueue(
            on_log=app._on_queue_log,
            lifecycle=fake,
            ledger_path=salad_queue.LEDGER_PATH,
            idle_stop_s=3600,
        )
        return fake

    def test_opening_the_window_does_not_stop_a_container_the_app_did_not_start(self) -> None:
        """Criterion 1 through the window: a stale record must stop nothing.

        The group is running because the user started it by hand, and the record
        is one this app cannot say it started.
        """
        app = self.app
        klein = profiles.load_all()["klein"]
        self._write_stale_ledger("klein", klein.gateway)
        fake = self._queue_on_the_users_container(app, {"klein": True, "klein5090": True})
        app.log_text.delete("1.0", "end")
        self._tick(app)  # the startup probe adopts nothing
        app._run_idle_check()  # and the tick that runs the idle check stops nothing
        self.assertTrue(
            _pump(app, lambda: not app._idle_check_busy, 30), "the idle check never ran"
        )
        self.assertEqual(fake.actions("stop"), [], "the app must not stop it")
        self.assertEqual(fake.actions("start"), [], "nor start it")
        self.assertEqual(app.gen_queue.containers(), {}, "it owns nothing here")
        log = app.log_text.get("1.0", "end")
        self.assertNotIn("stopped", log.lower(), f"no idle stop may be logged: {log[-400:]}")
        self.assertIn(
            "does not say this app started",
            log,
            "the log must say why the container was left alone",
        )
        self.assertEqual(
            fake.running, {"klein": True, "klein5090": True}, "it is still running"
        )

    def test_the_first_request_does_not_cycle_a_container_the_app_did_not_start(self) -> None:
        """Criterion 2: the press neither stops nor starts the user's container."""
        app = self.app
        routed = profiles.load_all()["klein5090"]
        self._write_stale_ledger("klein5090", routed.gateway)
        fake = self._queue_on_the_users_container(app, {"klein5090": True, "klein": True})
        tok.write_token("salad", "user-container-key")
        _line, gateway = self._prepare_snofs_generate(app)
        app.log_text.delete("1.0", "end")
        posts = self._render_once(app)

        self.assertEqual(fake.actions("stop"), [], "the press must not stop it")
        self.assertEqual(fake.actions("start"), [], "nor start it")
        self.assertEqual(
            fake.actions("is_running"),
            [("is_running", "klein5090", gateway)],
            "the dispatch only asks whether it is up",
        )
        self.assertEqual(len(posts), 1, "and the render is POSTed to it")
        self.assertEqual(len(app.gen_queue.jobs()), 1, "the request is on the queue")

        # The tick right after the render must not stop it either: this app did
        # not start that container, and it has just used it.
        app._run_idle_check()
        self.assertTrue(
            _pump(app, lambda: not app._idle_check_busy, 30), "the idle check never ran"
        )
        self.assertEqual(fake.actions("stop"), [])
        self.assertEqual(
            app.gen_queue.containers(),
            {"klein5090": gateway},
            "this session may stop it once it idles: it has used that container",
        )
        record = json.loads(
            Path(salad_queue.LEDGER_PATH).read_text(encoding="utf-8")
        )["containers"]["klein5090"]
        self.assertFalse(
            record["started_by_app"],
            "but the record still says this app did not start it, so a later "
            "session leaves it alone",
        )

    def test_the_apps_tick_stops_the_container_the_render_used(self) -> None:
        """A container this app has rendered on is stopped once it idles."""
        app = self.app
        fake = _FakeLifecycle({"klein5090": True, "klein": True})
        # idle_stop_s=0 so the tick below is allowed to stop it straight away.
        app.gen_queue = salad_queue.SaladQueue(
            on_log=app._on_queue_log, lifecycle=fake, sleep=lambda _s: None, idle_stop_s=0
        )
        tok.write_token("salad", "lifecycle-key")
        _line, want_gateway = self._prepare_snofs_generate(app)
        posts = self._render_once(app)
        self._tick(app)
        # The idle check runs off the Tk thread, so wait for the stop it asks for.
        self.assertTrue(
            _pump(app, lambda: bool(fake.actions("stop")), 30),
            "the tick never asked for the idle stop",
        )

        self.assertEqual(
            fake.actions("start"),
            [],
            "the queue never starts a container",
        )
        self.assertEqual(len(posts), 1, "the render POSTed once")
        self.assertIn(urlparse(posts[0]).hostname, want_gateway)
        self.assertEqual(
            fake.actions("stop"),
            [("stop", "klein5090", want_gateway)],
            "the app's tick stopped the idle container",
        )

    def test_a_stopped_routed_container_is_refused_at_the_press(self) -> None:
        """C1: the badge says stopped, so the press refuses before it queues.

        Nothing reaches the queue and nothing is POSTed, the app never asks Salad
        to start anything, and the reason is on the status line as well as in the
        Logs.
        """
        app = self.app
        fake = _FakeLifecycle({"klein5090": False, "klein": True})
        # The app's own queue, with its container handle replaced: the queue must
        # be the object the app and the generator share, or an Attempt made here
        # is not an Attempt to the generator (one module object per process).
        app.gen_queue.lifecycle = fake
        # The idle stop this test does not want to fire: `idle_timeout_s()` reads
        # the queue's own `_idle_stop_s`, so writing any other name leaves the
        # metadata document's default in place.
        app.gen_queue._idle_stop_s = 3600
        tok.write_token("salad", "stopped-container-key")
        _line, gateway = self._prepare_snofs_generate(app)
        app.var_salad_status.set("Stopped")  # what the badge shows for a stopped group
        app._last_snaps = {"klein5090": {"word": "Stopped", "group": {"status": "stopped"}}}
        app.log_text.delete("1.0", "end")
        posts: list[str] = []

        def _req(url, key=None, data=None, timeout=30):
            posts.append(str(url))
            return 200, b"ok"

        probes: list[str] = []

        def snapshot(gateway, key):
            probes.append(str(gateway))
            return {"word": "Ready", "group": {"status": "running"}}

        with mock.patch.object(
            self.app_mod.generator.salad_gen, "_req", side_effect=_req
        ), mock.patch.object(
            self.app_mod.salad_status, "snapshot_gateway", side_effect=snapshot
        ), mock.patch.object(self.app_mod.messagebox, "showinfo") as info:
            # The app schedules one status check shortly after it is built, and it
            # asks every profile's gateway. Let that one run and then count only
            # what the press asks for, or this assertion would be satisfied by the
            # startup check instead of by the press.
            _pump(app, lambda: bool(probes), 5)
            # This harness pumps `update()` rather than running a mainloop, so the
            # worker's completion callback cannot be scheduled: `_later` records it
            # in `_dropped_afters` (C6) and the guard it would have cleared stays
            # set. Clear it so the press's own check can run.
            probes.clear()
            app._salad_check_busy = False
            app._on_generate()
            _pump(app, lambda: bool(probes), 5)

        self.assertEqual(posts, [], "nothing may be POSTed to a container that is down")
        self.assertEqual(
            fake.actions("start"),
            [],
            "a stopped container must never be started for a press",
        )
        self.assertEqual(
            fake.actions("is_running"),
            [],
            "the press refuses on the badge, before it asks the queue about the container",
        )
        self.assertTrue(
            probes,
            "the press's own refusal must ask the probe again (the startup check's "
            "probes are cleared above): the badge is up to a tick old, so a user who "
            "has just started the container would be refused again",
        )
        self.assertEqual(app.gen_queue.jobs(), [], "nothing is queued")
        self.assertTrue(info.called, "the press must say why")
        reason = str(info.call_args[0][1])
        self.assertIn("klein5090", reason, "the refusal names the profile")
        self.assertIn(gateway, reason, "and its gateway")
        log = app.log_text.get("1.0", "end")
        self.assertIn("Generate refused", log)
        self.assertIn("klein5090", log, "the Logs line names the profile")
        self.assertIn("Refused:", app.status.get(), "the status line says refused")
        self.assertFalse(app._busy)

    def test_a_group_that_goes_down_after_the_badge_is_reported_as_refused(self) -> None:
        """C1's race: the badge was Ready, the queue's own read says the group is down.

        The request is dispatched and then refused inside the queue, and the press
        must report that as a refusal — not as a failed render, and not with a
        second copy of the sentence in the Logs.
        """
        app = self.app
        fake = _FakeLifecycle({"klein5090": False, "klein": True})
        # The app's own queue, with its container handle replaced: the queue must
        # be the object the app and the generator share, or an Attempt made here
        # is not an Attempt to the generator (one module object per process).
        app.gen_queue.lifecycle = fake
        # The idle stop this test does not want to fire: `idle_timeout_s()` reads
        # the queue's own `_idle_stop_s`, so writing any other name leaves the
        # metadata document's default in place.
        app.gen_queue._idle_stop_s = 3600
        tok.write_token("salad", "race-key")
        _line, gateway = self._prepare_snofs_generate(app)
        app.var_salad_status.set("Ready")  # the badge the press reads
        app._last_snaps = {"klein5090": {"word": "Ready", "group": {"status": "running"}}}
        app.log_text.delete("1.0", "end")
        posts: list[str] = []

        def _req(url, key=None, data=None, timeout=30):
            posts.append(str(url))
            return 200, b"ok"

        outcome: list[BaseException] = []

        with mock.patch.object(
            self.app_mod.generator.salad_gen, "_req", side_effect=_req
        ), mock.patch.object(self.app_mod.messagebox, "showinfo") as info, mock.patch.object(
            self.app_mod.messagebox, "showerror"
        ) as err:

            def body() -> None:
                # Inside mainloop(), and never blocking in it: the render worker
                # reports back with after(), and a Tcl call from that thread while
                # the main thread sits outside the loop raises.
                try:
                    app._on_generate()
                    self.assertTrue(
                        _pump(app, lambda: not app._busy, 30), "the press never ended"
                    )
                except BaseException as exc:  # noqa: BLE001 - re-raised below
                    outcome.append(exc)
                finally:
                    app.quit()

            app.after(0, body)
            app.mainloop()
        if outcome:
            raise outcome[0]

        self.assertEqual(posts, [], "nothing may be POSTed to a container that is down")
        self.assertEqual(fake.actions("start"), [], "and it is never started")
        self.assertEqual(
            fake.actions("is_running"), [("is_running", "klein5090", gateway)],
            "the queue read the group's state itself",
        )
        jobs = app.gen_queue.jobs()
        self.assertEqual(len(jobs), 1, "the refused request is a row on the queue page")
        self.assertEqual(jobs[0].state, salad_queue.FAILED)
        self.assertIn("down", jobs[0].reason)
        self.assertFalse(
            err.called,
            f"a refusal is not a render failure; showerror got {err.call_args}",
        )
        self.assertTrue(info.called, "the refusal is reported")
        self.assertIn("Refused:", app.status.get(), "the status line says refused")
        log = app.log_text.get("1.0", "end")
        self.assertEqual(
            log.count("its group is not running"),
            1,
            f"the refusal sentence must appear once in the Logs, not once per "
            f"layer: {log[-600:]}",
        )
        self.assertNotIn("Failed. See Logs", app.status.get())

    def test_an_idle_container_is_stopped_after_a_restart(self) -> None:
        """The app the user reopened still knows which container to stop.

        This is the failure: the queue's record lived in memory, so closing and
        reopening Studio forgot the container and the idle hour never arrived.
        The record is one an earlier session wrote when it asked Salad to start
        the container; the app no longer starts containers itself, so such a
        record is what a reopened window still reads and honors.
        """
        clock = {"t": 5_000_000.0}
        app = self.app
        routed = profiles.load_all()["klein5090"]
        salad_queue.save_ledger(
            Path(salad_queue.LEDGER_PATH),
            {
                "klein5090": {
                    "gateway": routed.gateway,
                    "last_active": clock["t"] - 10,
                    "started_by_app": True,
                }
            },
        )
        first = _FakeLifecycle({"klein5090": True, "klein": True})
        app.gen_queue = salad_queue.SaladQueue(
            on_log=app._on_queue_log,
            lifecycle=first,
            now=lambda: clock["t"],
            ledger_path=salad_queue.LEDGER_PATH,
            idle_stop_s=3600,
        )
        self.assertEqual(app.gen_queue.containers(), {"klein5090": routed.gateway})
        self._tick(app)
        self.assertEqual(first.actions("stop"), [], "not idle yet")
        _destroy_quietly(app)  # the user closes Studio

        # A fresh window on the same temp config, an hour and a second later.
        clock["t"] += 3601
        second = _FakeLifecycle({"klein5090": True, "klein": True})
        fresh = self.app_mod.SaladStudio(show=False)
        self.addCleanup(_destroy_quietly, fresh)
        fresh.withdraw()
        fresh.gen_queue = salad_queue.SaladQueue(
            on_log=fresh._on_queue_log,
            lifecycle=second,
            now=lambda: clock["t"],
            ledger_path=salad_queue.LEDGER_PATH,
            idle_stop_s=3600,
        )
        self.assertEqual(
            fresh.gen_queue.containers(),
            {"klein5090": routed.gateway},
            "the reopened app must still own the container",
        )
        self._tick(fresh)
        self.assertTrue(
            _pump(fresh, lambda: bool(second.actions("stop")), 30),
            "the reopened app never asked for the idle stop",
        )
        self.assertEqual(second.actions("stop"), [("stop", "klein5090", routed.gateway)])
        self.assertEqual(second.actions("start"), [], "it was already up")


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class TheConfigPageTellsTheUserWhatWentWrong(unittest.TestCase):
    """Three of the five issues this pass fixed, each driven on the real window.

    Issue 2: with no Salad key the badge sat on its checking placeholder and no
    surface named the key, while the sentence that names it and the Tokens tab was
    discarded. Issue 3: Delete profile asked nothing and reported a deletion that
    never happened. Issue 4: the press's refusals left the status line carrying
    whatever it said before, so the one surface that outlives the dialog lied.
    """

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
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(_destroy_quietly, self.app)
        self.app.update_idletasks()

    # -- the missing key -------------------------------------------------
    def test_a_missing_salad_key_is_named_on_the_surfaces_the_user_reads(self) -> None:
        """No key is not a container that is down, and the app must say which."""
        app = self.app
        self.assertEqual(tok.read_token("salad"), "", "this drive starts with no key")
        app.var_gateway.set(profiles.load_all()["klein"].gateway)
        app.status.set("SENTINEL")
        app.log_text.delete("1.0", "end")

        app._check_salad_status()
        app.update_idletasks()

        self.assertEqual(
            app.var_salad_status.get(),
            "No key",
            "the badge must read the state, not sit on the checking placeholder",
        )
        logs = app.log_text.get("1.0", "end")
        self.assertIn("key", logs.lower(), "the Logs must name the key")
        self.assertIn("Tokens tab", logs, "and the tab that fixes it")
        self.assertEqual(
            app.status.get(),
            "SENTINEL",
            "the status line carries events, so a standing condition must not erase it",
        )
        self.assertEqual(app._strip_vars[0].get(), "0", "and no container is counted")

    def test_a_present_key_is_not_reported_as_a_key_problem(self) -> None:
        """The guard against a false positive: a key on disk takes the probe path."""
        app = self.app
        tok.write_token("salad", "a-real-key")
        app.var_gateway.set(profiles.load_all()["klein"].gateway)
        probed: list[str] = []

        def snapshot(gateway, key):
            probed.append(str(gateway))
            return {"word": "Ready", "group": {"status": "running"}}

        with mock.patch.object(
            self.app_mod.salad_status, "snapshot_gateway", side_effect=snapshot
        ):
            app._check_salad_status()
            _pump(app, lambda: bool(probed), 5)
        self.assertTrue(probed, "a key on disk must reach the probe")
        self.assertNotIn("No key", app.var_salad_status.get())
        self.assertNotIn("unavailable", app.status.get())

    # -- the profile delete ---------------------------------------------
    def test_deleting_a_saved_profile_asks_first_and_honours_a_no(self) -> None:
        app = self.app
        before = sorted(profiles.load_all())
        self.assertIn("klein", before)
        asked: list[str] = []

        def refuse(*a, **_k):
            asked.append(str(a))
            return False

        with mock.patch.object(self.app_mod.messagebox, "askyesno", side_effect=refuse):
            app.var_name.set("klein")
            app._delete_profile()
        self.assertTrue(asked, "a destructive Delete must ask first")
        self.assertIn("klein", asked[0], "and name the profile it is about to remove")
        self.assertEqual(sorted(profiles.load_all()), before, "a No leaves the profile alone")
        self.assertIn("Kept klein", app.status.get(), f"and says so: {app.status.get()!r}")

    def test_deleting_a_saved_profile_asks_first_and_honours_a_yes(self) -> None:
        app = self.app
        asked: list[str] = []
        with mock.patch.object(
            self.app_mod.messagebox,
            "askyesno",
            side_effect=lambda *a, **_k: asked.append(str(a)) or True,
        ):
            app.var_name.set("klein")
            app._delete_profile()
        self.assertTrue(asked, "the question is asked before a Yes too")
        self.assertNotIn("klein", profiles.load_all(), "a Yes deletes it")
        self.assertEqual(app.status.get(), "Deleted klein", "and reports the real name")

    def test_deleting_a_name_that_was_never_saved_says_so(self) -> None:
        """The old handler reported `Deleted no-such-profile` for a ghost."""
        app = self.app
        before = sorted(profiles.load_all())
        asked: list[str] = []
        with mock.patch.object(
            self.app_mod.messagebox,
            "askyesno",
            side_effect=lambda *a, **_k: asked.append(str(a)) or True,
        ):
            app.var_name.set("no-such-profile")
            app._delete_profile()
        self.assertEqual(sorted(profiles.load_all()), before, "nothing is deleted")
        self.assertEqual(
            app.status.get(),
            "No saved profile named no-such-profile",
            "the status line names the miss instead of claiming a deletion",
        )
        logs = app.log_text.get("1.0", "end")
        self.assertIn("nothing was deleted", logs)
        self.assertNotIn("Deleted no-such-profile", logs)
        self.assertEqual(asked, [], "there is nothing to confirm")

    # -- the press's refusals -------------------------------------------
    def _press(self, mutate) -> tuple[str, list[str], int]:
        """Press Generate once with the state `mutate` builds; report the surfaces."""
        app = self.app
        tok.write_token("salad", "a-real-key")
        app.var_salad_status.set("Ready")
        app.status.set("SENTINEL")
        app.log_text.delete("1.0", "end")
        mutate(app)
        dialogs: list[str] = []
        posts: list[str] = []

        def _req(url, key=None, data=None, timeout=30):
            posts.append(str(url))
            return 200, b"ok"

        with mock.patch.object(
            self.app_mod.messagebox,
            "showerror",
            side_effect=lambda *a, **_k: dialogs.append(str(a)),
        ), mock.patch.object(
            self.app_mod.messagebox,
            "showinfo",
            side_effect=lambda *a, **_k: dialogs.append(str(a)),
        ), mock.patch.object(
            self.app_mod.generator.salad_gen, "_req", side_effect=_req
        ):
            app._on_generate()
            _pump(app, lambda: False, 0.4)
        return app.status.get(), dialogs, len(posts)

    def test_invalid_json_is_refused_on_the_status_line_too(self) -> None:
        def mutate(app) -> None:
            app.editor_text.delete("1.0", "end")
            app.editor_text.insert("1.0", "{not json")

        status, dialogs, posts = self._press(mutate)
        self.assertTrue(dialogs, "the dialog still reports it")
        self.assertTrue(
            status.startswith("Refused:"),
            f"and the status line outlives the dialog: {status!r}",
        )
        self.assertIn("JSON", status)
        self.assertEqual(posts, 0)

    def test_a_bad_profile_field_is_refused_on_the_status_line_too(self) -> None:
        def mutate(app) -> None:
            app.var_width.set("not-a-number")

        status, dialogs, posts = self._press(mutate)
        self.assertTrue(dialogs, "the dialog still reports it")
        self.assertTrue(status.startswith("Refused:"), f"the status line too: {status!r}")
        self.assertEqual(posts, 0)

    def test_an_empty_gateway_is_refused_on_the_status_line_too(self) -> None:
        def mutate(app) -> None:
            app.var_gateway.set("")

        status, dialogs, posts = self._press(mutate)
        self.assertTrue(dialogs, "the dialog still reports it")
        self.assertTrue(status.startswith("Refused:"), f"the status line too: {status!r}")
        self.assertIn("gateway", status.lower())
        self.assertEqual(posts, 0)

    def test_an_unreadable_key_is_refused_on_the_status_line_too(self) -> None:
        def mutate(app) -> None:
            tok.write_token("salad", "a-real-key")
            Path(tok.LOCAL_PATH).unlink()

        status, dialogs, posts = self._press(mutate)
        self.assertTrue(dialogs, "the dialog still reports it")
        self.assertTrue(status.startswith("Refused:"), f"the status line too: {status!r}")
        self.assertIn("Tokens tab", status, "and names the fix")
        self.assertEqual(posts, 0)

    # -- the Vast.ai address box -----------------------------------------
    def _add(self, typed: str) -> list[str]:
        """Press Add instance with `typed`; report the dialogs it showed."""
        app = self.app
        app.var_vast_new.set(typed)
        app.log_text.delete("1.0", "end")
        dialogs: list[str] = []
        with mock.patch.object(
            self.app_mod.messagebox,
            "showinfo",
            side_effect=lambda *a, **_k: dialogs.append(str(a)),
        ):
            app._on_vast_add()
        return dialogs

    def _rows(self) -> list[str]:
        return [
            str(self.app.vast_tree.item(i, "values")[2])
            for i in self.app.vast_tree.get_children()
        ]

    def test_a_phrase_that_names_no_host_adds_no_instance(self) -> None:
        """Issue 2: one typed phrase became five instances and a success line."""
        dialogs = self._add("not an address at all")
        self.assertEqual(self._rows(), [], "a word is not an instance address")
        self.assertEqual(
            vast.load_doc()["instances"], [], "and none of it is persisted"
        )
        self.assertTrue(dialogs, "the press must say it refused")
        self.assertIn("Nothing was added", dialogs[0])
        self.assertIn(
            "Nothing was added",
            self.app.status.get(),
            f"the status line outlives the dialog: {self.app.status.get()!r}",
        )
        logs = self.app.log_text.get("1.0", "end")
        self.assertIn("Nothing was added", logs, "and the Logs keep the refusal")
        self.assertNotIn("added 5 instance(s)", logs)
        self.assertEqual(
            self.app.var_vast_status.get(),
            self.app.status.get(),
            "the section's own note says the same thing",
        )

    def test_a_partly_refused_press_names_what_was_added_and_what_was_not(self) -> None:
        """Issue 2: a press that added some of what it was given must say so."""
        dialogs = self._add("203.0.113.9:31234 not")
        self.assertEqual(dialogs, [], "something was added, so there is no refusal")
        self.assertEqual(self._rows(), ["http://203.0.113.9:31234"])
        self.assertEqual(
            [row["endpoint"] for row in vast.load_doc()["instances"]],
            ["http://203.0.113.9:31234"],
            "the usable address is the one that is kept",
        )
        status = self.app.status.get()
        self.assertIn("added 1 instance(s)", status)
        self.assertIn("refused 1", status, "and the refused word is named too")
        self.assertIn("not", status)
        logs = self.app.log_text.get("1.0", "end")
        self.assertIn("refused 1", logs, "the Logs carry both halves as well")
        self.assertIn("added 1 instance(s)", logs)


class TheImportPageAndTheHistoryDelete(unittest.TestCase):
    """This pass's issues 1 and 4, each driven on the real window.

    Issue 1: Convert with no workflow pasted and free text in the generation-data
    box replaced the Prompt Editor's own graph with a fabricated default and
    reported an import that never happened. Issue 4: Delete on the Prompt History
    page removed a stored prompt and its thumbnail without asking and without
    writing the status line, while the Catalog's Delete and the profile Delete
    both ask first.
    """

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
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod
        from salad_studio import prompt_history

        self.app_mod = app_mod
        self.prompt_history = prompt_history
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(_destroy_quietly, self.app)
        self.app.update_idletasks()

    def test_a_failed_conversion_writes_a_refusal_on_the_status_line(self) -> None:
        """The except branch logged and showed a dialog but left the success line."""
        app = self.app
        app.status.set("Imported Civitai workflow to Prompt Editor")
        app.import_workflow.delete("1.0", "end")
        app.import_meta.delete("1.0", "end")
        app.import_meta.insert("1.0", "Steps: 20, CFG: 5")
        with mock.patch.object(
            self.app_mod.comfy_import, "import_to_request", side_effect=ValueError("bad paste")
        ), mock.patch.object(self.app_mod.messagebox, "showerror"):
            app._on_import_civitai()
        self.assertIn("Refused", app.status.get())
        self.assertNotIn("Imported Civitai workflow", app.status.get())

    # -- Convert with nothing to convert ---------------------------
    def _press_convert(self) -> list[str]:
        """Press Convert on whatever the page holds; report the dialogs."""
        dialogs: list[str] = []

        def _note(*a, **_k):
            dialogs.append(str(a))

        # Convert resolves LoRA filenames through Civitai; answer offline so this
        # drives the app, not the network.
        with mock.patch.object(
            self.app_mod.messagebox, "showerror", side_effect=_note
        ), mock.patch.object(
            self.app_mod.messagebox, "showinfo", side_effect=_note
        ), mock.patch.object(
            self.app_mod.lora_store, "civitai_search_lora", return_value=None
        ):
            self.app._goto_tab("Import")
            self.app._on_import_civitai()
            self.app.update_idletasks()
        return dialogs

    def _empty_import_boxes(self) -> None:
        app = self.app
        app.var_imp_image_url.set("")
        app.import_meta.delete("1.0", "end")
        app.import_workflow.delete("1.0", "end")
        app._stash_import_workflow("")

    def test_convert_of_free_text_refuses_and_keeps_the_editors_graph(self) -> None:
        app = self.app
        mine = {
            "prompt": {
                "1": {"class_type": "KSampler", "inputs": {"seed": 424242, "steps": 7}}
            }
        }
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", json.dumps(mine))
        self._empty_import_boxes()
        app.import_meta.insert("1.0", "just some free text the user pasted")
        app.status.set("SENTINEL")
        app.log_text.delete("1.0", "end")

        self._press_convert()

        self.assertIn(
            "424242",
            app.editor_text.get("1.0", "end"),
            "a refusal must not replace the graph the user wrote",
        )
        status = app.status.get()
        self.assertTrue(
            status.startswith("Refused:"),
            f"the status line must carry the refusal: {status!r}",
        )
        self.assertIn("workflow", status, "and name what is missing")
        self.assertNotIn(
            "imported Civitai paste",
            app.log_text.get("1.0", "end"),
            "no import may be reported for a refusal",
        )

    def test_generation_data_is_not_mistaken_for_free_text(self) -> None:
        """The refusal must not swallow the pastes Convert is for."""
        app = self.app
        self.assertFalse(
            app._import_generation_data("just some free text the user pasted"),
            "bare text names no generation field",
        )
        self.assertTrue(
            app._import_generation_data(
                "a watercolour cat\nSteps: 20, CFG: 5, Sampler: Euler, Seed: 7"
            ),
            "prompt + Steps/CFG is generation data",
        )
        self.assertTrue(
            app._import_generation_data(
                "a portrait\nModel: FLUX.2-klein-9b-fp8, width: 3584, height: 2688, "
                "Tools: Draw Things"
            ),
            "a Draw Things paste is generation data",
        )
        self.assertTrue(
            app._import_generation_data("https://civitai.com/images/125073040"),
            "a Civitai image URL is fetched, not converted as text",
        )

    def test_convert_of_generation_data_with_no_workflow_still_converts(self) -> None:
        """The metadata-only route Convert has always had must survive the refusal."""
        app = self.app
        self._empty_import_boxes()
        app.import_meta.insert(
            "1.0", "a watercolour cat\nSteps: 20, CFG: 5, Sampler: Euler, Seed: 7"
        )
        app.status.set("SENTINEL")

        self._press_convert()

        self.assertNotIn(
            "Refused:", app.status.get(), "generation data is not free text"
        )
        payload = json.loads(app.editor_text.get("1.0", "end"))
        seeds = [
            node["inputs"].get("noise_seed")
            for node in payload["prompt"].values()
            if isinstance(node, dict) and node.get("class_type") == "RandomNoise"
        ]
        self.assertIn(7, seeds, f"the pasted Seed is the one that converts: {seeds}")

    # -- Delete on the Prompt History page -------------------------
    SEED_TEXT = "a distinctive sentinel prompt for the history delete"

    def _seed_history(self) -> None:
        entry = self.prompt_history.add_request(
            {
                "prompt": {
                    "1": {
                        "class_type": "CLIPTextEncode",
                        "inputs": {"text": self.SEED_TEXT},
                    }
                }
            },
            profile="klein",
        )
        self.assertIsNotNone(entry, "the seed must land in the store")
        self.app._refresh_prompt_history()
        rows = self.app.prompt_hist_tree.get_children()
        self.assertTrue(rows, "the seeded prompt must be listed")
        self.app.prompt_hist_tree.selection_set(rows[0])

    def test_deleting_a_stored_prompt_asks_first_and_honours_a_no(self) -> None:
        app = self.app
        self._seed_history()
        asked: list[str] = []

        def refuse(*a, **_k):
            asked.append(str(a))
            return False

        app.status.set("SENTINEL")
        with mock.patch.object(self.app_mod.messagebox, "askyesno", side_effect=refuse):
            app._delete_prompt_history()
        self.assertTrue(asked, "a destructive Delete must ask first")
        self.assertIn(self.SEED_TEXT, asked[0], "and name what it is about to remove")
        self.assertEqual(
            [row.get("text") for row in self.prompt_history.list_prompts()],
            [self.SEED_TEXT],
            "a No leaves the stored prompt alone",
        )
        self.assertIn("Kept", app.status.get(), f"and says so: {app.status.get()!r}")

    def test_deleting_a_stored_prompt_reports_what_went(self) -> None:
        app = self.app
        self._seed_history()
        with mock.patch.object(self.app_mod.messagebox, "askyesno", return_value=True):
            app._delete_prompt_history()
        self.assertEqual(self.prompt_history.list_prompts(), [], "a Yes deletes it")
        status = app.status.get()
        self.assertIn(
            self.SEED_TEXT, status, f"the status line names what went: {status!r}"
        )
        self.assertIn("Deleted", status)
        self.assertIn("deleted prompt history", app.log_text.get("1.0", "end"))


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class TheSweepOf2026_10_15b(unittest.TestCase):
    """Issues 2 and 4 of `docs/issue-sweep-2026-10-15b.md`, on the real window.

    Issue 2: both of ``_on_generate_vast``'s refusals reported through a dialog
    and the Logs and never wrote the status line, so it kept the last successful
    render's sentence beside a refused press. Issue 4: ``Remove extra`` acted on
    the first row of a multi-selection while the neighbouring ``Verify`` acted on
    all of them, so a selection of two extras left one behind under a singular
    report.
    """

    # The two lines this sweep added to _on_generate_vast, as (shipped, replaced).
    VAST_STATUS_EDITS = (
        ('            self.status.set("Refused: the Prompt Editor JSON is invalid")\n', ""),
        ('            self.status.set("Refused: no vast.ai instance is selected")\n', ""),
    )
    # Remove extra's whole new block, and the single-row block it replaced.
    REMOVE_NEW = (
        "    # The neighbouring Verify acts on every selected row, so this one does\n"
        "    # too: a selection of two extras is two removals, and the report says\n"
        "    # how many, because a row that stays behind must not read as removed.\n"
        "    removed: list[str] = []\n"
        "    refused: list[str] = []\n"
        "    for lid in sel:\n"
        "        if lora_store.remove_lora(lid):\n"
        "            removed.append(lid)\n"
        '            self.log("ok", f"removed extra LoRA {lid}")\n'
        "        else:\n"
        "            refused.append(lid)\n"
        "    if not removed:\n"
        '        note = "Known catalog LoRAs stay in the list; only extras added here can be removed."\n'
        '        self.status.set(f"Refused: {note}")\n'
        '        messagebox.showinfo("Salad Studio", note)\n'
        "        return\n"
        "    self._refresh_lora_lists()\n"
        '    note = f"Removed {len(removed)} extra LoRA(s): " + ", ".join(removed)\n'
        "    if refused:\n"
        '        note += f" ({len(refused)} known catalog LoRA(s) kept)"\n'
        "    self.status.set(note)\n"
        "    self._sync_editor()\n"
    )
    REMOVE_OLD = (
        "    lid = sel[0]\n"
        "    if not lora_store.remove_lora(lid):\n"
        "        messagebox.showinfo(\n"
        '            "Salad Studio",\n'
        '            "Known catalog LoRAs stay in the list; only extras added here can be removed.",\n'
        "        )\n"
        "        return\n"
        "    self._refresh_lora_lists()\n"
        '    self.status.set(f"Removed {lid}")\n'
        '    self.log("ok", f"removed extra LoRA {lid}")\n'
        "    self._sync_editor()\n"
    )

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
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(_destroy_quietly, self.app)
        self.app.update_idletasks()

    # -- the vast.ai refusals -------------------------------------------
    def _press_vast(self, mutate) -> tuple[str, list[str], int]:
        """Press Generate in vast.ai mode with the state ``mutate`` builds."""
        app = self.app
        app.var_profile_mode.set(vast.MODE_VAST)
        app.var_gateway.set("")
        app.status.set("SENTINEL")
        app.log_text.delete("1.0", "end")
        mutate(app)
        dialogs: list[str] = []
        posts: list[str] = []

        def _req(url, key=None, data=None, timeout=30):
            posts.append(str(url))
            return 200, b"ok"

        with mock.patch.object(
            self.app_mod.messagebox,
            "showinfo",
            side_effect=lambda *a, **_k: dialogs.append(str(a)),
        ), mock.patch.object(
            self.app_mod.messagebox,
            "showerror",
            side_effect=lambda *a, **_k: dialogs.append(str(a)),
        ), mock.patch.object(
            self.app_mod.generator, "generate_from_vast"
        ) as render, mock.patch.object(
            self.app_mod.generator.salad_gen, "_req", side_effect=_req
        ):
            app._on_generate()
            _pump(app, lambda: False, 0.3)
        self.assertEqual(render.call_count, 0, "a refused press must not render")
        return app.status.get(), dialogs, len(posts)

    def _drive_old_vast(self) -> str:
        """Press Generate on the old handler and report the status line it leaves."""
        app = self.app
        old = _old_form(self.app_mod.SaladStudio._on_generate_vast, self.VAST_STATUS_EDITS)
        app.var_profile_mode.set(vast.MODE_VAST)
        app.status.set(r"Wrote C:\plates\stale.png")
        with mock.patch.object(self.app_mod.messagebox, "showinfo"), mock.patch.object(
            self.app_mod.messagebox, "showerror"
        ):
            old(app)
            _pump(app, lambda: False, 0.3)
        return app.status.get()

    def test_a_vast_press_with_no_instance_refuses_on_the_status_line_too(self) -> None:
        """The no-instance refusal: the dialog is dismissed, the status line stays."""
        status, dialogs, posts = self._press_vast(lambda _app: None)
        self.assertTrue(dialogs, "the dialog still reports it")
        self.assertTrue(
            status.startswith("Refused:"), f"and the status line outlives it: {status!r}"
        )
        self.assertIn("instance", status.lower(), "with the cause the dialog carries")
        self.assertEqual(posts, 0)
        self.assertNotEqual(
            status, "SENTINEL", "the press must not leave the previous sentence standing"
        )
        self.assertEqual(
            self._drive_old_vast(),
            r"Wrote C:\plates\stale.png",
            "the old handler left the status line claiming the last success",
        )

    def test_a_vast_press_with_invalid_json_refuses_on_the_status_line_too(self) -> None:
        """The invalid-JSON refusal, the same rule the Salad sibling follows."""

        def mutate(app) -> None:
            app.editor_text.delete("1.0", "end")
            app.editor_text.insert("1.0", "{not json")

        status, dialogs, posts = self._press_vast(mutate)
        self.assertTrue(dialogs, "the dialog still reports it")
        self.assertTrue(
            status.startswith("Refused:"), f"and the status line outlives it: {status!r}"
        )
        self.assertIn("JSON", status, "with the cause the dialog carries")
        self.assertEqual(posts, 0)
        self.assertEqual(
            self._drive_old_vast(),
            r"Wrote C:\plates\stale.png",
            "the old handler left the status line claiming the last success",
        )

    # -- Remove extra over the whole selection --------------------------
    def _two_extras(self) -> list[str]:
        from salad_studio import lora_store

        app = self.app
        ids: list[str] = []
        for number, ref in ((1, "civitai:90001@90001"), (2, "civitai:90002@90002")):
            item = lora_store.add_lora(
                ref,
                name=f"Sweep Extra {number}",
                filename=f"sweep-extra-{number}.safetensors",
                verify=False,
            )
            ids.append(str(item.get("id") or ref))
        app._refresh_lora_lists()
        for lid in ids:
            self.assertTrue(app.lora_tree.exists(lid), f"{lid} must be in the grid")
        return ids

    def test_remove_extra_acts_on_the_whole_selection(self) -> None:
        """Two extras selected are two extras removed, and the report counts them."""
        from salad_studio import lora_store

        app = self.app
        ids = self._two_extras()
        app.lora_tree.selection_set(*ids)
        app.update_idletasks()
        self.assertEqual(
            tuple(app.lora_tree.selection()), tuple(ids), "this drive needs both selected"
        )

        with mock.patch.object(self.app_mod.messagebox, "showinfo") as info:
            app._on_remove_lora()
        self.assertFalse(info.called, "extras were removed, so there is no refusal")
        for lid in ids:
            self.assertFalse(app.lora_tree.exists(lid), f"{lid} must be gone from the grid")
            self.assertIsNone(lora_store.find_lora(lid), f"{lid} must be gone from the store")
        self.assertIn(
            "Removed 2", app.status.get(), f"the count must be named: {app.status.get()!r}"
        )
        logs = app.log_text.get("1.0", "end")
        for lid in ids:
            self.assertIn(lid, logs, "every removal is in the Logs")

        # The old handler, rebuilt from this file, removes the first row only.
        ids = self._two_extras()
        app.lora_tree.selection_set(*ids)
        app.update_idletasks()
        old = _old_form(
            self.app_mod.SaladStudio._on_remove_lora, [(self.REMOVE_NEW, self.REMOVE_OLD)]
        )
        with mock.patch.object(
            self.app_mod.SaladStudio, "_on_remove_lora", old
        ), mock.patch.object(self.app_mod.messagebox, "showinfo"):
            app._on_remove_lora()
        self.assertFalse(app.lora_tree.exists(ids[0]), "the old handler removes the first")
        self.assertTrue(
            app.lora_tree.exists(ids[1]),
            "and leaves the second of the selection behind, which is what the fix changed",
        )


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class TheSweepOf2026_10_16(unittest.TestCase):
    """Issues 4 and 5 of `docs/issue-sweep-2026-10-16.md`, on the real window.

    Issue 4: a press of Check keys while a check ran returned with no status
    line, no Log and no dialog, and the button stayed live — and the Tokens tab
    starts a check as it opens, so the busy window is reached without a press.
    Issue 5: four refusals reported through a dialog or the reply box and
    returned without writing the status line, so it kept the last success.
    """

    # The lines this pass added to each handler, as (shipped text, replaced).
    # `_old_form` dedents the source, so a method body starts at four spaces.
    PROBE_EDITS = (
        (
            (
                "    if self._token_probe_busy:\n"
                "        # The press cannot start a second check, so say why on the one\n"
                "        # surface that outlives it rather than returning silently.\n"
                '        self.status.set("Check keys: a key check is already running")\n'
                "        return\n"
            ),
            "    if self._token_probe_busy:\n        return\n",
        ),
        (
            (
                "    self._token_probe_busy = True\n"
                "    self._set_token_check_enabled(False)\n"
            ),
            "    self._token_probe_busy = True\n",
        ),
        (
            (
                "            self._token_probe_busy = False\n"
                "            self._set_token_check_enabled(True)\n"
            ),
            "            self._token_probe_busy = False\n",
        ),
    )
    ADD_ENV_EDITS = (
        (
            (
                "        # The dialog is the only surface that carries this, and it does not\n"
                "        # outlive the dismissal; the status line keeps the last success.\n"
                '        self.status.set(f"Refused: {refusal}")\n'
            ),
            "",
        ),
    )
    REMOVE_ENV_EDITS = (
        (
            (
                "    if entry is None or not selection:\n"
                '        self.status.set("Refused: Select an environment row first.")\n'
            ),
            "    if entry is None or not selection:\n",
        ),
        (
            (
                "    if not removed:\n"
                '        note = f"{name} comes from the metadata document, so remove it there."\n'
                '        self.status.set(f"Refused: {note}")\n'
                '        messagebox.showinfo("Salad Studio", note)\n'
            ),
            (
                "    if not removed:\n"
                "        messagebox.showinfo(\n"
                '            "Salad Studio",\n'
                '            f"{name} comes from the metadata document, so remove it there.",\n'
                "        )\n"
            ),
        ),
    )
    REMOVE_LORA_EDITS = (
        (
            (
                "    if not removed:\n"
                '        note = "Known catalog LoRAs stay in the list; only extras added here can be removed."\n'
                '        self.status.set(f"Refused: {note}")\n'
                '        messagebox.showinfo("Salad Studio", note)\n'
            ),
            (
                "    if not removed:\n"
                "        messagebox.showinfo(\n"
                '            "Salad Studio",\n'
                '            "Known catalog LoRAs stay in the list; only extras added here can be removed.",\n'
                "        )\n"
            ),
        ),
    )
    HELPER_EDITS = (
        (
            (
                "        if not key:\n"
                '            self.helper_state.set("No DeepSeek key. Save one on the Tokens tab")\n'
                "            note = (\n"
                '                "No DeepSeek key is saved. Add it on the Tokens tab, then press "\n'
                '                "Help again."\n'
                "            )\n"
                "            self._set_helper_reply(note)\n"
                "            # The reply box is the only surface carrying this, and the next\n"
                "            # reply overwrites it; the status line keeps the last success.\n"
                '            self.status.set(f"Refused: {note}")\n'
            ),
            (
                "        if not key:\n"
                '            self.helper_state.set("No DeepSeek key. Save one on the Tokens tab")\n'
                "            self._set_helper_reply(\n"
                '                "No DeepSeek key is saved. Add it on the Tokens tab, then press "\n'
                '                "Help again."\n'
                "            )\n"
            ),
        ),
    )

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
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(_destroy_quietly, self.app)
        self.app.update_idletasks()

    # -- the shared drives ---------------------------------------------
    def _controls(self, page) -> list:
        out: list = []

        def walk(node) -> None:
            for child in node.winfo_children():
                out.append(child)
                walk(child)

        walk(page)
        return out

    def _check_keys_button(self):
        """The Check keys button on the Tokens page, found by its label."""
        found = [
            w
            for w in self._controls(self.app._tokens)
            if isinstance(w, ttk.Button) and str(w.cget("text")) == "Check keys"
        ]
        self.assertEqual(len(found), 1, "the Tokens page keeps exactly one Check keys button")
        return found[0]

    def _assert_status_carries(self, sentence: str) -> str:
        """The status line must carry ``sentence`` rather than the last success."""
        status = self.app.status.get()
        self.assertNotEqual(
            status, "SENTINEL", "the status line must not keep the sentence it had"
        )
        self.assertIn(
            sentence, status, f"the status line must carry the refusal: {status!r}"
        )
        return status

    def _press_with_dialogs(self, method, *args) -> list[str]:
        """Press a handler, reporting every dialog's own sentence."""
        dialogs: list[str] = []

        def note(*a, **_k):
            dialogs.append(str(a[1]) if len(a) > 1 else "")

        with mock.patch.object(
            self.app_mod.messagebox, "showinfo", side_effect=note
        ), mock.patch.object(self.app_mod.messagebox, "showerror", side_effect=note):
            method(*args)
            self.app.update_idletasks()
        return dialogs

    # -- issue 4: Check keys while a check runs ------------------------
    def _drive_check(self, probe) -> dict:
        """Start a check that stays in flight, press again, then let it finish.

        The worker is held rather than run: ``_Inline`` would run the probe on
        this thread and the check would be over before a second press could
        happen. The held worker is run on this thread at the end, so the handoff
        still goes through Tk's own ``after``.
        """
        app = self.app
        button = self._check_keys_button()
        release = threading.Event()

        def slow(_kind):
            release.wait(20)
            return {"state": "valid", "detail": "HTTP 200"}

        _HeldThread.held = []
        out: dict = {}
        with mock.patch.object(
            self.app_mod.threading, "Thread", _HeldThread
        ), mock.patch.object(self.app_mod.tokens, "probe_token", side_effect=slow):
            probe(["salad"])
            out["busy"] = app._token_probe_busy
            out["state"] = str(button.cget("state"))
            out["checking"] = app._token_state.get("salad")
            app.status.set("SENTINEL")
            probe(["salad"])
            out["status"] = app.status.get()
            self.assertTrue(_HeldThread.held, "a check must start a worker")
            release.set()
            _HeldThread.held[-1].target()
            self.assertTrue(
                _pump(app, lambda: not app._token_probe_busy, 10),
                "the check must finish once its worker runs",
            )
        out["state_after"] = str(button.cget("state"))
        return out

    def test_check_keys_goes_down_while_a_check_runs_and_says_why(self) -> None:
        """The button the Tokens tab starts a check behind must not look live."""
        app = self.app
        live = self._drive_check(app._probe_tokens)
        self.assertTrue(live["busy"], "the check must be in flight")
        self.assertEqual(
            live["checking"], "checking", "the grid reads checking while the probe is out"
        )
        self.assertEqual(
            live["state"],
            "disabled",
            "a press while the probes are out changes nothing, so the button goes down",
        )
        self.assertNotEqual(
            live["status"], "SENTINEL", "the busy press must write the status line"
        )
        self.assertIn(
            "already running",
            live["status"],
            f"and name the running check: {live['status']!r}",
        )
        self.assertEqual(
            live["state_after"], "normal", "and the button comes back when the check ends"
        )

        # The old handler, rebuilt from this file, leaves the button live and the
        # busy press silent.
        old = _old_form(self.app_mod.SaladStudio._probe_tokens, self.PROBE_EDITS)
        stale = self._drive_check(lambda kinds: old(app, kinds))
        self.assertEqual(
            stale["state"], "normal", "the old handler left the button live while busy"
        )
        self.assertEqual(
            stale["status"],
            "SENTINEL",
            "and its busy return wrote nothing, which is what the fix changed",
        )

    # -- issue 5: the four refusals ------------------------------------
    def test_an_added_env_refusal_reaches_the_status_line(self) -> None:
        """A name the add refuses: the dialog is dismissed, the status line stays."""
        app = self.app
        app.var_image_env_name.set("")
        app.var_image_env_value.set("")
        app.status.set("SENTINEL")
        dialogs = self._press_with_dialogs(app._on_image_add_env)
        self.assertTrue(dialogs, "the dialog still reports it")
        self._assert_status_carries(dialogs[-1])

        old = _old_form(self.app_mod.SaladStudio._on_image_add_env, self.ADD_ENV_EDITS)
        app.status.set("SENTINEL")
        with mock.patch.object(
            self.app_mod.SaladStudio, "_on_image_add_env", old
        ), mock.patch.object(self.app_mod.messagebox, "showinfo"):
            app._on_image_add_env()
        self.assertEqual(
            app.status.get(),
            "SENTINEL",
            "the old handler reported through the dialog and left the status line stale",
        )

    def test_a_removed_env_refusal_reaches_the_status_line(self) -> None:
        """Both refusals: nothing selected, and a row the document owns."""
        app = self.app
        tree = app.image_env_tree
        for row in tree.selection():
            tree.selection_remove(row)
        app.status.set("SENTINEL")
        dialogs = self._press_with_dialogs(app._on_image_remove_env)
        self.assertTrue(dialogs, "the dialog still reports it")
        self._assert_status_carries(dialogs[-1])

        app._refresh_images_page()
        rows = tree.get_children()
        self.assertTrue(rows, "the page must list the documented environment")
        tree.selection_set(rows[0])
        app.update_idletasks()
        app.status.set("SENTINEL")
        dialogs = self._press_with_dialogs(app._on_image_remove_env)
        self.assertTrue(dialogs, "the document-owned row reports through the dialog")
        self.assertIn("metadata document", dialogs[-1], "and names the document")
        self._assert_status_carries(dialogs[-1])

        old = _old_form(self.app_mod.SaladStudio._on_image_remove_env, self.REMOVE_ENV_EDITS)
        for drive in ("nothing selected", "a document-owned row"):
            with self.subTest(refusal=drive):
                if drive == "nothing selected":
                    for row in tree.selection():
                        tree.selection_remove(row)
                else:
                    tree.selection_set(tree.get_children()[0])
                app.update_idletasks()
                app.status.set("SENTINEL")
                with mock.patch.object(
                    self.app_mod.SaladStudio, "_on_image_remove_env", old
                ), mock.patch.object(self.app_mod.messagebox, "showinfo"):
                    app._on_image_remove_env()
                self.assertEqual(
                    app.status.get(),
                    "SENTINEL",
                    f"the old handler left the status line stale for {drive}",
                )

    def test_removing_only_catalog_loras_reaches_the_status_line(self) -> None:
        """A selection the store refuses: the dialog is dismissed, the line stays."""
        app = self.app
        rows = app.lora_tree.get_children()
        self.assertTrue(rows, "the LoRA grid must list the catalog")
        app.lora_tree.selection_set(rows[0])
        app.update_idletasks()
        app.status.set("SENTINEL")
        dialogs = self._press_with_dialogs(app._on_remove_lora)
        self.assertTrue(dialogs, "the refusal still reports through the dialog")
        self.assertIn("catalog", dialogs[-1], "and names what it will not remove")
        self._assert_status_carries(dialogs[-1])

        old = _old_form(self.app_mod.SaladStudio._on_remove_lora, self.REMOVE_LORA_EDITS)
        app.lora_tree.selection_set(rows[0])
        app.update_idletasks()
        app.status.set("SENTINEL")
        with mock.patch.object(
            self.app_mod.SaladStudio, "_on_remove_lora", old
        ), mock.patch.object(self.app_mod.messagebox, "showinfo"):
            app._on_remove_lora()
        self.assertEqual(
            app.status.get(),
            "SENTINEL",
            "the old handler reported through the dialog and left the status line stale",
        )

    def test_prompt_assist_without_a_deepseek_key_reaches_the_status_line(self) -> None:
        """The reply box carries it, but the next reply overwrites it; the line stays."""
        app = self.app
        app.status.set("SENTINEL")
        with mock.patch.object(self.app_mod.tokens, "read_env_token", return_value=""):
            self.assertEqual(
                self.app_mod.tokens.read_token("deepseek"),
                "",
                "this drive needs the key to be missing",
            )
            app._start_helper_call("deepseek")
        app.update_idletasks()
        reply = app.helper_reply.get("1.0", "end").strip()
        self.assertTrue(reply, "the reply box still carries the refusal")
        self.assertIn("DeepSeek key", reply, "and names the key it wants")
        self._assert_status_carries(reply)
        self.assertFalse(app._helper_busy, "a refusal must not start a call")

        old = _old_form(self.app_mod.SaladStudio._start_helper_call, self.HELPER_EDITS)
        app.status.set("SENTINEL")
        with mock.patch.object(
            self.app_mod.SaladStudio, "_start_helper_call", old
        ), mock.patch.object(self.app_mod.tokens, "read_env_token", return_value=""):
            app._start_helper_call("deepseek")
        self.assertEqual(
            app.status.get(),
            "SENTINEL",
            "the old handler filled the reply box and left the status line stale",
        )


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class TheAuditOf2026_10_16(unittest.TestCase):
    """U1-U5, C4 and T4 of `docs/history/63-salad-studio-audit-2026-10-16.md`.

    U1: the window opened at the whole layout's requested size with no clamp
    against the screen, and three pages that bypassed `_scrollable_page` were
    what drove it past a laptop's bottom edge. U2: the eleven nav buttons are
    the only page switcher there is (theme hides the notebook's own tabs) and
    they answered no key and showed no focus. U3: the missing-key and
    bad-form-value Generate refusals wrote the status line and the dialog but
    not the Logs. U4: a bad Width/Height/Steps/CFG/Seed was reported as the
    interpreter's own exception, naming no field. U5: a typed port that names no
    port was dropped without a word. C4/T4: "Refresh Salad logs" was a silent
    no-op while a status poll ran, and the button stayed live.

    Every drive runs the shipped handler from a real start state and then the
    same handler rebuilt from this file with the fix's lines taken out
    (`_old_form`), so what the fix changed is the difference between the two.
    """

    # The lines each fix added, as (shipped text, replaced). `_old_form` dedents
    # the source, so a method body starts at four spaces.
    CATALOG_WRAP_EDITS = (
        (
            (
                "    # Wrapped the way its eight siblings are: five columns of Treeview would\n"
                "    # otherwise set the window's size for the whole layout. The frame the\n"
                "    # content lives in keeps the name it always had, so every control and\n"
                "    # every lookup below stays where it was.\n"
                "    self._catalog_page = ttk.Frame(self.nb)\n"
                "    self._catalog = self._scrollable_page(self._catalog_page)\n"
            ),
            (
                "    self._catalog_page = ttk.Frame(self.nb, padding=10)\n"
                "    self._catalog = self._catalog_page\n"
            ),
        ),
        (
            "    self._page_keeps_its_own_size(self._catalog, self.catalog_tree)\n",
            "",
        ),
    )
    HISTORY_WRAP_EDITS = (
        (
            (
                "    # Wrapped like its siblings: the stored prompts' grid is taller than a\n"
                "    # window, and the frame the content lives in keeps its own name.\n"
                "    self._prompt_hist_page = ttk.Frame(self.nb)\n"
                "    self._prompt_hist = self._scrollable_page(self._prompt_hist_page)\n"
            ),
            (
                "    self._prompt_hist_page = ttk.Frame(self.nb, padding=10)\n"
                "    self._prompt_hist = self._prompt_hist_page\n"
            ),
        ),
        (
            "    self._page_keeps_its_own_size(self._prompt_hist, self.prompt_hist_tree)\n",
            "",
        ),
    )
    QUEUE_WRAP_EDITS = (
        (
            (
                "    self._queue_page = ttk.Frame(self.nb)\n"
                "    self._queue = self._scrollable_page(self._queue_page)\n"
            ),
            (
                "    self._queue_page = ttk.Frame(self.nb, padding=10)\n"
                "    self._queue = self._queue_page\n"
            ),
        ),
        (
            "    self._page_keeps_its_own_size(self._queue, self.queue_tree)\n",
            "",
        ),
    )
    OPEN_SIZE_EDITS = (
        (
            "    self._opened_width, self._opened_height = self._fitted_size(width, height)\n",
            "    self._opened_width = width\n    self._opened_height = height\n",
        ),
        (
            '    self.geometry(f"{self._opened_width}x{self._opened_height}")\n',
            '    self.geometry(f"{width}x{height}")\n',
        ),
    )
    NAV_EDITS = (
        (
            "    self._nav_focused = None\n",
            "",
        ),
        (
            (
                "            # The ring is drawn in accent_hi while the button holds focus and\n"
                "            # in the button's own colour otherwise, so the keyboard can see\n"
                "            # where it is without the column shifting as focus moves.\n"
                "            highlightthickness=1,\n"
                '            highlightbackground=p["surface"],\n'
                '            highlightcolor=p["accent_hi"],\n'
            ),
            "            highlightthickness=0,\n",
        ),
        (
            (
                "        # theme hides the notebook's own tabs, so these buttons are the only\n"
                "        # page switcher there is: the keys a button answers everywhere else\n"
                "        # in the app have to work here too, or the switcher is mouse-only.\n"
                '        btn.bind("<Return>", lambda _e, n=name: self._goto_tab(n))\n'
                '        btn.bind("<space>", lambda _e, n=name: self._goto_tab(n))\n'
                '        btn.bind("<FocusIn>", lambda _e, b=btn: self._on_nav_focus(b, True))\n'
                '        btn.bind("<FocusOut>", lambda _e, b=btn: self._on_nav_focus(b, False))\n'
            ),
            "",
        ),
    )
    GENERATE_LOG_EDITS = (
        (
            '        self.log("error", f"Generate aborted: {e}")\n',
            "",
        ),
        (
            '        self.log("error", note)\n',
            "",
        ),
    )
    PROFILE_FORM_EDITS = (
        (
            (
                '        width=self._whole_number("Width", self.var_width.get(), 1024),\n'
                '        height=self._whole_number("Height", self.var_height.get(), 1024),\n'
                '        steps=self._whole_number("Steps", self.var_steps.get(), 20),\n'
                '        cfg=self._number("CFG", self.var_cfg.get(), 5),\n'
                '        seed=int(self._number("Seed", self.var_seed.get(), 1)),\n'
            ),
            (
                "        width=int(self.var_width.get() or 1024),\n"
                "        height=int(self.var_height.get() or 1024),\n"
                "        steps=int(self.var_steps.get() or 20),\n"
                "        cfg=float(self.var_cfg.get() or 5),\n"
                "        seed=int(float(self.var_seed.get() or 1)),\n"
            ),
        ),
    )
    ADD_IMAGE_EDITS = (
        (
            (
                "    bad_port = port_refusal(ports)\n"
                "    if bad_port:\n"
                "        return settings, bad_port\n"
            ),
            "",
        ),
    )
    SALAD_CHECK_EDITS = (
        (
            (
                "    # The Refresh Salad logs button reads the same probe this check owns, so\n"
                "    # it goes down with it and comes back when the check is done.\n"
                "    self._set_salad_logs_enabled(False)\n"
            ),
            "",
        ),
        (
            "            self._set_salad_logs_enabled(True)\n",
            "",
        ),
    )
    SALAD_LOGS_EDITS = (
        (
            (
                "    if self._salad_check_busy:\n"
                '        self.status.set("Refresh Salad logs: a status check is already running")\n'
                "        return\n"
            ),
            "",
        ),
    )

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
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(_destroy_quietly, self.app)
        self.app.update_idletasks()

    # -- shared drives -----------------------------------------------------
    def _pages(self, app) -> dict:
        """Each notebook page by the label the notebook shows for it."""
        return {
            str(app.nb.tab(tab, "text")): app.nb.nametowidget(tab) for tab in app.nb.tabs()
        }

    def _show(self, app) -> None:
        """Map the window without lighting it up, so key events reach it.

        A generated key goes to the focused widget and only a mapped window can
        hold focus, so the drive needs a real window; alpha 0 keeps it off the
        screen while it is one.
        """
        try:
            app.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        app.geometry("900x700")
        app.deiconify()
        deadline = time.time() + 10.0
        while time.time() < deadline:
            app.update()
            if app.winfo_viewable():
                break
            time.sleep(0.02)
        app.update_idletasks()

    def _old_page_window(self):
        """A window whose three oversize pages were built by the old builders."""
        catalog = _old_form(
            self.app_mod.SaladStudio._build_prompt_catalog_tab, self.CATALOG_WRAP_EDITS
        )
        history = _old_form(
            self.app_mod.SaladStudio._build_prompt_history_tab, self.HISTORY_WRAP_EDITS
        )
        queue = _old_form(
            self.app_mod.SaladStudio._build_queue_tab, self.QUEUE_WRAP_EDITS
        )
        with mock.patch.object(
            self.app_mod.SaladStudio, "_build_prompt_catalog_tab", catalog
        ), mock.patch.object(
            self.app_mod.SaladStudio, "_build_prompt_history_tab", history
        ), mock.patch.object(
            self.app_mod.SaladStudio, "_build_queue_tab", queue
        ):
            old = self.app_mod.SaladStudio(show=False)
        old.withdraw()
        self.addCleanup(_destroy_quietly, old)
        return old

    def _old_nav_window(self):
        """A window whose nav buttons were built by the old, unbound builder."""
        old_nav = _old_form(
            self.app_mod.SaladStudio._build_nav_buttons, self.NAV_EDITS
        )
        with mock.patch.object(
            self.app_mod.SaladStudio, "_build_nav_buttons", old_nav
        ):
            old = self.app_mod.SaladStudio(show=False)
        old.withdraw()
        self.addCleanup(_destroy_quietly, old)
        return old

    def _clear_logs(self) -> None:
        """Empty the Studio pane the way the page's own Clear button does.

        A disabled ``Text`` ignores ``delete``, so the state has to come off
        first or the "grew by N lines" drives read the startup lines back.
        """
        widget = self.app.log_text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.configure(state="disabled")

    def _press_generate(self, press) -> tuple[str, list[str], int, str]:
        """Press Generate, reporting the status line, the dialogs, the POSTs, the Logs."""
        app = self.app
        app.status.set("SENTINEL")
        self._clear_logs()
        dialogs: list[str] = []
        posts: list[str] = []

        def _req(url, key=None, data=None, timeout=30):
            posts.append(str(url))
            return 200, b"ok"

        def note(*a, **_k):
            dialogs.append(str(a[1]) if len(a) > 1 else "")

        with mock.patch.object(
            self.app_mod.messagebox, "showerror", side_effect=note
        ), mock.patch.object(
            self.app_mod.messagebox, "showinfo", side_effect=note
        ), mock.patch.object(
            self.app_mod.generator.salad_gen, "_req", side_effect=_req
        ):
            press()
            _pump(app, lambda: False, 0.4)
        return app.status.get(), dialogs, len(posts), app.log_text.get("1.0", "end")

    def _ready_to_generate(self) -> None:
        """The state a press needs to get past the editor and the routing."""
        app = self.app
        app.var_gateway.set(profiles.load_all()["klein"].gateway)
        app.var_salad_status.set("Ready")
        app.var_width.set("")

    # -- U1: the window that did not fit the screen ------------------------
    def test_the_three_pages_that_sized_the_window_now_scroll(self) -> None:
        """U1: Prompt Catalog, Prompt History and Queue go through the helper."""
        app = self.app
        pages = self._pages(app)
        for name in ("Prompt Catalog", "Prompt History", "Queue"):
            with self.subTest(page=name):
                self.assertIn(name, pages, "the page set changed")
                self.assertIn(
                    pages[name],
                    app._scroll_canvases,
                    f"{name} holds more than a window and must scroll",
                )

        old = self._old_page_window()
        old_pages = self._pages(old)
        for name in ("Prompt Catalog", "Prompt History", "Queue"):
            with self.subTest(page=name, layout="old"):
                self.assertNotIn(
                    old_pages[name],
                    old._scroll_canvases,
                    f"the old {name} page was a plain frame the notebook sized",
                )
        self.assertGreaterEqual(
            int(app.winfo_reqwidth()),
            self.app_mod.PAGE_OPENING_WIDTH,
            "the new form's request is at least the canvas size that now sizes the window",
        )
        self.assertGreater(
            int(old.winfo_reqwidth()),
            self.app_mod.PAGE_OPENING_WIDTH,
            "the old form's request came from the plain pages' content, not the "
            "canvas default that used to size the window",
        )

    def test_the_window_opens_inside_the_screen_it_has(self) -> None:
        """U1: the opened geometry is the layout size, cut to the work area."""
        app = self.app
        natural_w, natural_h = int(app.winfo_reqwidth()), int(app.winfo_reqheight())
        self.assertGreater(
            natural_h,
            600,
            "this drive needs a layout taller than the mocked work area",
        )
        self.assertGreater(natural_w, 480, "and wider than the smaller one")
        for work in ((1024, 600), (480, 520)):
            with self.subTest(work=work):
                with mock.patch.object(app, "_screen_work_area", return_value=work):
                    app._opened_size_held = False
                    app._hold_opened_size()
                self.assertEqual(
                    (app._opened_width, app._opened_height),
                    (min(natural_w, work[0]), min(natural_h, work[1])),
                    "the window opens at the layout, cut to the work area",
                )

        old = _old_form(
            self.app_mod.SaladStudio._hold_opened_size, self.OPEN_SIZE_EDITS
        )
        with mock.patch.object(app, "_screen_work_area", return_value=(1024, 600)):
            with mock.patch.object(self.app_mod.SaladStudio, "_hold_opened_size", old):
                app._opened_size_held = False
                app._hold_opened_size()
        self.assertEqual(
            (app._opened_width, app._opened_height),
            (natural_w, natural_h),
            "the old handler opened at the whole layout size",
        )
        self.assertGreater(
            app._opened_height, 600, "which is past the work area it was given"
        )

    # -- U2: the page switcher the keyboard could not use ------------------
    def test_the_nav_buttons_answer_the_keyboard_and_show_focus(self) -> None:
        """U2: <Return> and <space> switch page, and focus is visible."""
        app = self.app
        self._show(app)
        app._goto_tab("Config")
        app.update()
        btn = app._nav_btns["Logs"]
        btn.focus_force()
        app.update()

        self.assertIs(app._nav_focused, btn, "the keyboard is on the Logs button")
        self.assertEqual(
            str(btn.cget("highlightthickness")), "1", "and it can draw a focus ring"
        )
        self.assertEqual(
            str(btn.cget("highlightbackground")),
            str(self.app_mod.theme.PALETTE["accent_hi"]),
            "the ring is lit while it holds focus",
        )
        self.assertEqual(
            str(btn.cget("background")),
            str(self.app_mod.theme.PALETTE["surface_hi"]),
            "and its face is lightened, so focus is readable at a glance",
        )

        # Focus is read before any key is sent: a classic Button's own <space>
        # binding arms a delayed invoke, and that would re-open the page again
        # while the focus assertions below were being read.
        app.focus_force()
        app.update()
        self.assertIsNone(app._nav_focused, "leaving the button clears the focus state")
        self.assertEqual(
            str(btn.cget("background")),
            str(self.app_mod.theme.PALETTE["surface"]),
            "and the face goes back to the unselected colour",
        )

        btn.focus_force()
        app.update()
        btn.event_generate("<Return>")
        app.update()
        self.assertEqual(
            app.nb.tab(app.nb.select(), "text"),
            "Logs",
            "<Return> on the focused nav button switches page",
        )
        app._goto_tab("Config")
        app.update()
        btn.event_generate("<space>")
        _pump(app, lambda: False, 0.3)
        self.assertEqual(
            app.nb.tab(app.nb.select(), "text"),
            "Logs",
            "<space> switches page too",
        )

        old = self._old_nav_window()
        self._show(old)
        old._goto_tab("Config")
        old.update()
        old_btn = old._nav_btns["Logs"]
        old_btn.focus_force()
        old.update()
        self.assertIsNone(
            old._nav_focused, "the old button had no focus state to show"
        )
        self.assertEqual(
            str(old_btn.cget("highlightthickness")), "0", "and no ring to draw"
        )
        old_btn.event_generate("<Return>")
        old.update()
        self.assertEqual(
            old.nb.tab(old.nb.select(), "text"),
            "Config",
            "the old button answered no key, which is what the fix changed",
        )

    # -- U3: the two refusals that never reached the Logs ------------------
    def test_the_two_generate_refusals_reach_the_logs(self) -> None:
        """U3: the missing key and the bad form value log the same sentence."""
        app = self.app
        self._ready_to_generate()
        Path(tok.LOCAL_PATH).unlink(missing_ok=True)
        self.assertEqual(tok.read_token("salad"), "", "this drive starts with no key")
        status, dialogs, posts, logs = self._press_generate(app._on_generate)
        self.assertTrue(dialogs, "the dialog still reports it")
        self.assertIn("Tokens tab", status, "the status line names the fix")
        self.assertEqual(posts, 0, "a refused press POSTs nothing")
        self.assertEqual(dialogs[-1], status, "the dialog carries the status sentence")
        self.assertIn(status, logs, "the Logs carry that same sentence")
        self.assertIn("Salad API key is empty", status)
        self.assertIn("Tokens tab", status)

        tok.write_token("salad", "a-real-key")
        app.var_width.set("abc")
        status, dialogs, posts, logs = self._press_generate(app._on_generate)
        self.assertTrue(dialogs, "the dialog still reports it")
        self.assertIn("Width", status)
        self.assertEqual(posts, 0)
        self.assertIn("Generate aborted", logs, "the Logs keep the second refusal too")
        self.assertIn("Width must be a whole number", logs, "with the field it names")
        app.var_width.set("")

        # The old handlers, rebuilt from this file, returned without logging.
        old_salad = _old_form(
            self.app_mod.SaladStudio._generate_salad, (self.GENERATE_LOG_EDITS[1],)
        )
        Path(tok.LOCAL_PATH).unlink(missing_ok=True)
        with mock.patch.object(
            self.app_mod.SaladStudio, "_generate_salad", old_salad
        ):
            _status, dialogs, _posts, logs = self._press_generate(app._on_generate)
        self.assertTrue(dialogs, "the dialog reported it")
        self.assertNotIn(
            "Generate aborted", logs, "the old handler left the Logs without a word"
        )
        tok.write_token("salad", "a-real-key")
        app.var_width.set("abc")
        old_on = _old_form(
            self.app_mod.SaladStudio._on_generate, (self.GENERATE_LOG_EDITS[0],)
        )
        _status, dialogs, _posts, logs = self._press_generate(lambda: old_on(app))
        self.assertTrue(dialogs, "and the dialog reported this one too")
        self.assertNotIn(
            "Generate aborted", logs, "while the Logs stayed without a word again"
        )
        app.var_width.set("")
        app.var_width.set("")

    # -- U4: a bad number reported as a Python exception -------------------
    def test_a_bad_number_is_refused_by_the_name_of_its_field(self) -> None:
        """U4: each of the five numeric fields names itself when it cannot be read."""
        app = self.app
        self._ready_to_generate()
        tok.write_token("salad", "a-real-key")
        cases = (
            ("Width", "var_width", "abc"),
            ("Height", "var_height", "abc"),
            ("Steps", "var_steps", "3.5"),
            ("CFG", "var_cfg", "high"),
            ("Seed", "var_seed", "1e"),
        )
        for field, var, bad in cases:
            with self.subTest(field=field):
                getattr(app, var).set(bad)
                status, dialogs, posts, logs = self._press_generate(app._on_generate)
                self.assertTrue(dialogs, "the dialog still reports it")
                self.assertIn(field, status, f"the status line names the field: {status!r}")
                self.assertIn(field, dialogs[-1], "and so does the dialog")
                self.assertEqual(posts, 0, "a refused press POSTs nothing")
                self.assertIn(field, logs, "and the Logs name it too")
                getattr(app, var).set("")

        old = _old_form(
            self.app_mod.SaladStudio._profile_from_form, self.PROFILE_FORM_EDITS
        )
        with mock.patch.object(self.app_mod.SaladStudio, "_profile_from_form", old):
            for field, var, bad in cases:
                with self.subTest(field=field, layout="old"):
                    getattr(app, var).set(bad)
                    status, dialogs, _posts, _logs = self._press_generate(app._on_generate)
                    self.assertTrue(dialogs, "the dialog reported it")
                    self.assertNotIn(
                        field,
                        status,
                        f"the old handler named the literal, not the field: {status!r}",
                    )
                    getattr(app, var).set("")

    # -- U5: the port the form dropped without a word ----------------------
    def test_a_typed_port_that_names_no_port_is_refused_by_name(self) -> None:
        """U5: a port that is not a port is refused, naming the field."""
        app = self.app
        app.var_image_new_name.set("mine2")
        app.var_image_new_tag.set("mine2:1")
        app.var_image_new_api.set("3000/api")
        app.var_image_new_comfy.set("")
        dialogs = self._press_add_image()
        self.assertTrue(dialogs, "the press must say it refused")
        self.assertIn("API port", dialogs[-1], "and name the field the port is typed in")
        self.assertEqual(
            app._image_settings.get("images") or [], [], "nothing was added"
        )
        self.assertEqual(
            image_deploy.load_settings()["images"], [], "and none of it is stored"
        )

        # The old store kept only what int() accepted, so the typo became "no
        # port" while the page reported the image as added.
        old_add = _old_form(image_deploy.add_image, self.ADD_IMAGE_EDITS)
        with mock.patch.object(image_deploy, "add_image", old_add):
            dialogs = self._press_add_image()
        self.assertEqual(dialogs, [], "the old store refused nothing")
        rows = app._image_settings.get("images") or []
        self.assertEqual(
            [row["name"] for row in rows],
            ["mine2"],
            "it added the image with the port silently dropped",
        )
        self.assertEqual(rows[0]["ports"], {}, "and kept no port at all")

    def _press_add_image(self) -> list[str]:
        """Press Add image; report the dialog sentences it showed."""
        dialogs: list[str] = []
        with mock.patch.object(
            self.app_mod.messagebox,
            "showinfo",
            side_effect=lambda *a, **_k: dialogs.append(str(a[1]) if len(a) > 1 else ""),
        ):
            self.app._on_image_add_image()
            self.app.update_idletasks()
        return dialogs

    # -- C4 / T4: Refresh Salad logs during a poll -------------------------
    def _drive_salad_refresh(self, check, refresh, button=None) -> dict:
        """Hold a status check in flight, press Refresh, then let the check finish."""
        app = self.app
        # The window starts a status check of its own half a second in and polls
        # again every 15 s. Both are let go of first - with no key on disk the
        # startup one reports and returns without a worker - so the only check
        # in flight below is the one this drive starts.
        if app._salad_poll_after is not None:
            try:
                app.after_cancel(app._salad_poll_after)
            except tk.TclError:
                pass
            app._salad_poll_after = None
        Path(tok.LOCAL_PATH).unlink(missing_ok=True)
        _pump(app, lambda: False, 1.0)
        self.assertFalse(app._salad_check_busy, "no check may be in flight yet")

        tok.write_token("salad", "a-real-key")
        app.var_gateway.set(profiles.load_all()["klein"].gateway)
        button = button or app.refresh_salad_logs_btn
        release = threading.Event()

        def slow(_gateway, _key):
            release.wait(20)
            return {"word": "Ready", "group": {"status": "running"}}

        _HeldThread.held = []
        out: dict = {}
        with mock.patch.object(
            self.app_mod.threading, "Thread", _HeldThread
        ), mock.patch.object(
            self.app_mod.salad_status, "snapshot_gateway", side_effect=slow
        ):
            check()
            out["busy"] = app._salad_check_busy
            out["state"] = str(button.cget("state"))
            app.status.set("SENTINEL")
            refresh()
            out["status"] = app.status.get()
            self.assertTrue(_HeldThread.held, "a status check must start a worker")
            release.set()
            _HeldThread.held[-1].target()
            self.assertTrue(
                _pump(app, lambda: not app._salad_check_busy, 10),
                "the check must finish once its worker runs",
            )
        out["state_after"] = str(button.cget("state"))
        return out

    def test_refresh_salad_logs_goes_down_while_a_check_runs(self) -> None:
        """C4/T4: the button is disabled while busy and says why if pressed."""
        app = self.app
        live = self._drive_salad_refresh(app._check_salad_status, app._refresh_salad_logs)
        self.assertTrue(live["busy"], "the status check must be in flight")
        self.assertEqual(
            live["state"],
            "disabled",
            "a press while the probe is out can refresh nothing, so the button goes down",
        )
        self.assertNotEqual(
            live["status"], "SENTINEL", "the busy press must write the status line"
        )
        self.assertIn(
            "already running",
            live["status"],
            f"and name the check it cannot join: {live['status']!r}",
        )
        self.assertEqual(
            live["state_after"], "normal", "and the button comes back when the check ends"
        )

        old_check = _old_form(
            self.app_mod.SaladStudio._check_salad_status, self.SALAD_CHECK_EDITS
        )
        old_refresh = _old_form(
            self.app_mod.SaladStudio._refresh_salad_logs, self.SALAD_LOGS_EDITS
        )
        with mock.patch.object(
            self.app_mod.SaladStudio, "_check_salad_status", old_check
        ), mock.patch.object(
            self.app_mod.SaladStudio, "_refresh_salad_logs", old_refresh
        ):
            stale = self._drive_salad_refresh(app._check_salad_status, app._refresh_salad_logs)
        self.assertTrue(stale["busy"], "the old check was in flight too")
        self.assertEqual(
            stale["state"], "normal", "the old handler left the button live while busy"
        )
        self.assertEqual(
            stale["status"],
            "SENTINEL",
            "and its press wrote nothing, which is what the fix changed",
        )

    # -- U3: Tab from the nav reaches the page ----------------------------
    def _focus_after_tab_from_logs(self, app):
        self._show(app)
        app._goto_tab("Config")
        app.update()
        btn = app._nav_btns["Logs"]
        btn.focus_force()
        app.update()
        self.assertIs(app.focus_get(), btn, "the drive starts on the last nav button")
        btn.event_generate("<Tab>")
        app.update()
        return app.focus_get()

    def test_check_salad_status_goes_down_while_a_check_runs(self) -> None:
        """U8: the top-bar check is disabled while busy and says why if pressed."""
        app = self.app
        live = self._drive_salad_refresh(
            app._check_salad_status,
            app._check_salad_status,
            button=app.check_salad_btn,
        )
        self.assertTrue(live["busy"], "the status check must be in flight")
        self.assertEqual(
            live["state"], "disabled", "a check cannot join a check already running"
        )
        self.assertIn("already running", live["status"])
        self.assertEqual(
            live["state_after"], "normal", "and the button comes back when the check ends"
        )

    def _assert_tab_lands_on_the_page(self, app) -> None:
        focus = self._focus_after_tab_from_logs(app)
        self.assertIsNotNone(focus, "Tab from the nav must land somewhere")
        self.assertIsNot(focus, app.nb, "Tab must not die on the hidden notebook")
        page = app.nb.nametowidget(app.nb.select())
        node = focus
        while node is not None and node is not page:
            node = getattr(node, "master", None)
        self.assertIs(node, page, f"Tab landed on {focus}, not the open page")

    def _old_notebook_window(self):
        old_build = _old_form(
            self.app_mod.SaladStudio._build_notebook,
            ((", takefocus=0", ""),),
        )
        with mock.patch.object(self.app_mod.SaladStudio, "_build_notebook", old_build):
            old = self.app_mod.SaladStudio(show=False)
        old.withdraw()
        self.addCleanup(_destroy_quietly, old)
        return old

    def test_tab_from_the_nav_lands_on_the_page(self) -> None:
        """U3: Tab from the last nav button reaches the page's first control."""
        self._assert_tab_lands_on_the_page(self.app)
        old = self._old_notebook_window()
        self.assertIs(
            self._focus_after_tab_from_logs(old),
            old.nb,
            "the old notebook took the Tab itself",
        )

    # -- U6: one refusal sentence on the status line, the Logs, the dialog
    def _assert_one_refusal_sentence(self, status, dialogs, logs) -> None:
        self.assertTrue(dialogs, "the dialog must carry the refusal")
        self.assertEqual(dialogs[-1], status, "the dialog and the status line differ")
        self.assertIn(status, logs, "the Logs must carry that same sentence")

    def test_each_cited_generate_refusal_is_one_sentence(self) -> None:
        """U6: the missing key and the empty gateway each use one sentence."""
        app = self.app
        self._ready_to_generate()
        Path(tok.LOCAL_PATH).unlink(missing_ok=True)
        status, dialogs, posts, logs = self._press_generate(app._on_generate)
        self.assertEqual(posts, 0)
        self._assert_one_refusal_sentence(status, dialogs, logs)
        self.assertIn("Salad API key is empty", status)

        tok.write_token("salad", "a-real-key")
        app.var_gateway.set("")
        status, dialogs, posts, logs = self._press_generate(app._on_generate)
        self.assertEqual(posts, 0)
        self.assertEqual(status, "Refused: the gateway URL is empty")
        self._assert_one_refusal_sentence(status, dialogs, logs)

        old = _old_form(
            self.app_mod.SaladStudio._generate_salad,
            (
                (
                    '        note = f"Refused: {e}"\n'
                    "        self.status.set(note)\n"
                    '        self.log("error", note)\n'
                    '        messagebox.showerror("Salad Studio", note)\n',
                    '        self.status.set(f"Refused: {e}")\n'
                    '        self.log("error", f"Generate aborted: cannot read the Salad API key: {e}")\n'
                    '        messagebox.showerror("Salad Studio", f"Cannot read Salad API key: {e}")\n',
                ),
                (
                    '        note = "Refused: the gateway URL is empty"\n'
                    "        self.status.set(note)\n"
                    '        self.log("error", note)\n'
                    '        messagebox.showerror("Salad Studio", note)\n',
                    '        self.status.set("Refused: the gateway URL is empty")\n'
                    '        self.log("error", "Generate aborted: gateway URL is empty")\n'
                    '        messagebox.showerror("Salad Studio", "Gateway URL is empty.")\n',
                ),
            ),
        )
        Path(tok.LOCAL_PATH).unlink(missing_ok=True)
        with mock.patch.object(self.app_mod.SaladStudio, "_generate_salad", old):
            status, dialogs, _posts, logs = self._press_generate(app._on_generate)
        self.assertNotEqual(dialogs[-1], status, f"old key dialog {dialogs[-1]!r} status {status!r}")
        self.assertNotIn(status, logs)
        tok.write_token("salad", "a-real-key")
        app.var_gateway.set("")
        with mock.patch.object(self.app_mod.SaladStudio, "_generate_salad", old):
            status, dialogs, _posts, logs = self._press_generate(app._on_generate)
        self.assertNotEqual(
            dialogs[-1], status, f"old gateway dialog {dialogs[-1]!r} status {status!r}"
        )
        self.assertNotIn(status, logs)

    # -- U8: Add image writes the refusal to the status line and the Logs --
    def _assert_add_image_refusal_reaches_status_and_logs(self) -> None:
        app = self.app
        app.status.set("SENTINEL")
        self._clear_logs()
        app.var_image_new_name.set("mine2")
        app.var_image_new_tag.set("mine2:1")
        app.var_image_new_api.set("3000/api")
        app.var_image_new_comfy.set("")
        dialogs = self._press_add_image()
        self.assertTrue(dialogs, "the dialog still reports the bad port")
        sentence = f"Refused: {dialogs[-1]}"
        self.assertEqual(app.status.get(), sentence)
        self.assertIn(sentence, app.log_text.get("1.0", "end"))
        self.assertIn("API port", dialogs[-1])

    def test_add_image_refusal_reaches_the_status_line_and_the_logs(self) -> None:
        """U8: a bad port is on the status line and in the Logs, not only a dialog."""
        self._assert_add_image_refusal_reaches_status_and_logs()
        old = _old_form(
            self.app_mod.SaladStudio._on_image_add_image,
            (
                (
                    '        self.status.set(f"Refused: {refusal}")\n'
                    '        self.log("warn", f"Refused: {refusal}")\n',
                    "",
                ),
            ),
        )
        with mock.patch.object(self.app_mod.SaladStudio, "_on_image_add_image", old):
            self.app.status.set("SENTINEL")
            self._clear_logs()
            dialogs = self._press_add_image()
        self.assertTrue(dialogs, "the old handler still opened the dialog")
        self.assertEqual(self.app.status.get(), "SENTINEL", "and left the status line alone")
        self.assertNotIn("API port", self.app.log_text.get("1.0", "end"))

    # -- U11: Fill knobs with nothing pasted refuses -----------------------
    def _assert_empty_fill_refuses(self) -> None:
        app = self.app
        app.import_meta.delete("1.0", "end")
        app.import_workflow.delete("1.0", "end")
        app._import_workflow_stash = ""
        app.status.set("SENTINEL")
        self._clear_logs()
        _nomodal.reset()
        app._fill_import_knobs(quiet=True)
        self.assertEqual(app.status.get(), "SENTINEL", "a keystroke must stay quiet")
        self.assertEqual(_nomodal.CALLS, [], "a keystroke must not open a dialog")
        app._fill_import_knobs()
        status = app.status.get()
        self.assertTrue(status.startswith("Refused: Nothing to fill."), status)
        self.assertIn("fill knobs refused", app.log_text.get("1.0", "end"))
        self.assertTrue(_nomodal.CALLS, "the button must open the refusal")
        self.assertIn("Nothing to fill.", _nomodal.CALLS[-1][2])

    def test_fill_knobs_with_nothing_pasted_refuses(self) -> None:
        """U11: Fill knobs with both boxes empty refuses, the way Convert does."""
        self._assert_empty_fill_refuses()
        old = _old_form(
            self.app_mod.SaladStudio._fill_import_knobs,
            (
                (
                    "        if not quiet:\n"
                    "            note = (\n"
                    '                "Nothing to fill. Paste a Comfy workflow JSON and/or Civitai "\n'
                    '                "generation data (prompt + Steps/CFG, or Sampler/Seed/Model)."\n'
                    "            )\n"
                    '            self.status.set(f"Refused: {note}")\n'
                    '            self.log("warn", "fill knobs refused: no workflow and no generation data")\n'
                    '            messagebox.showerror("Salad Studio", note)\n',
                    "",
                ),
            ),
        )
        with mock.patch.object(self.app_mod.SaladStudio, "_fill_import_knobs", old):
            self.app.status.set("SENTINEL")
            self._clear_logs()
            _nomodal.reset()
            self.app._fill_import_knobs()
        self.assertEqual(self.app.status.get(), "SENTINEL", "the old handler changed nothing")
        self.assertEqual(_nomodal.CALLS, [], "and it opened no dialog")

    # -- STATUS: apply and reallocate write the dialog's sentence ----------
    def test_apply_and_reallocate_write_the_dialog_sentence(self) -> None:
        """Empty gateway and a failed reallocate land on the status line."""
        app = self.app
        app.var_gateway.set("")
        app.status.set("SENTINEL")
        _nomodal.reset()
        app._apply_salad_policy()
        self.assertEqual(app.status.get(), "Gateway URL is empty.")
        self.assertEqual(_nomodal.CALLS[-1][2], app.status.get())

        app.status.set("SENTINEL")
        _nomodal.reset()
        app._reallocate_instance()
        self.assertEqual(app.status.get(), "Gateway URL is empty.")
        self.assertEqual(_nomodal.CALLS[-1][2], app.status.get())
        self.assertEqual(_nomodal.CALLS[-1][0], "showerror")

        app.var_gateway.set(profiles.load_all()["klein"].gateway)
        tok.write_token("salad", "a-real-key")
        app.status.set("SENTINEL")
        _nomodal.reset()

        def boom(_gateway, _key):
            return 500, {"error": "node refused the move"}

        with _allow_destructive_confirm(), mock.patch.object(
            self.app_mod.salad_status, "reallocate_instance", side_effect=boom
        ), mock.patch.object(self.app_mod.threading, "Thread", _Inline):
            app._reallocate_instance()
            self.assertTrue(
                _pump(app, lambda: app.status.get() != "SENTINEL", 5),
                "the failed reallocate must leave its sentence on the status line",
            )
        self.assertEqual(app.status.get(), "node refused the move")
        self.assertEqual(_nomodal.CALLS[-1], ("showerror", "Salad Studio", "node refused the move"))

        old_apply = _old_form(
            self.app_mod.SaladStudio._apply_salad_policy,
            (('        self.status.set("Gateway URL is empty.")\n', ""),),
        )
        with mock.patch.object(self.app_mod.SaladStudio, "_apply_salad_policy", old_apply):
            app.var_gateway.set("")
            app.status.set("SENTINEL")
            app._apply_salad_policy()
        self.assertEqual(app.status.get(), "SENTINEL", "the old apply left the status line")

        old_empty = _old_form(
            self.app_mod.SaladStudio._reallocate_instance,
            (('        self.status.set("Gateway URL is empty.")\n', ""),),
        )
        with mock.patch.object(self.app_mod.SaladStudio, "_reallocate_instance", old_empty):
            app.status.set("SENTINEL")
            app._reallocate_instance()
        self.assertEqual(app.status.get(), "SENTINEL", "the old reallocate left the status line")

        old_fail = _old_form(
            self.app_mod.SaladStudio._reallocate_instance,
            (('                self.status.set(err)\n', ""),),
        )
        app.var_gateway.set(profiles.load_all()["klein"].gateway)
        app.status.set("SENTINEL")
        with _allow_destructive_confirm(), mock.patch.object(
            self.app_mod.SaladStudio, "_reallocate_instance", old_fail
        ), mock.patch.object(
            self.app_mod.salad_status, "reallocate_instance", side_effect=boom
        ), mock.patch.object(self.app_mod.threading, "Thread", _Inline):
            app._reallocate_instance()
            _pump(app, lambda: False, 0.5)
        self.assertEqual(
            app.status.get(), "SENTINEL", "the old failure path never wrote the status line"
        )

    # -- an after armed during destroy must not outlive its command --------
    def test_a_destroy_time_after_is_not_registered(self) -> None:
        """A <Destroy> binding that calls after() must not leave a run command."""
        app = self.app
        app.update()
        answers: list = []

        def late(_event=None):
            answers.append(app.after(0, lambda: None))

        app.bind("<Destroy>", late, add="+")
        app.destroy()
        self.assertTrue(answers, "child teardown must reach the binding")
        self.assertTrue(all(item is None for item in answers), f"scheduled {answers[:3]}")

        fresh = self.app_mod.SaladStudio(show=False)
        fresh.withdraw()
        self.addCleanup(_destroy_quietly, fresh)
        fresh.update_idletasks()
        fresh._closing = True
        old = _old_form(
            self.app_mod.SaladStudio.after,
            (
                (
                    "    if self._closing:\n"
                    "        # Destroy has started, so the cancel pass has already run or is\n"
                    "        # about to delete every Tcl command. Registering one now leaves\n"
                    '        # its script queued and Tk prints "invalid command name".\n'
                    '        self._dropped_afters.append(f"after({ms}): window is closing")\n'
                    "        return None\n",
                    "",
                ),
            ),
        )
        with mock.patch.object(self.app_mod.SaladStudio, "after", old):
            handle = fresh.after(0, lambda: None)
            self.assertIsNotNone(handle, "the old after still registered a command")
            fresh.after_cancel(handle)


if __name__ == "__main__":
    unittest.main()
