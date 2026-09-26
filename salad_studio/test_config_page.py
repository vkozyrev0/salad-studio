"""The Config page manages profiles and their checkpoint lists, through the store.

Every assertion reads the store back off disk or the page's own widgets, so a
control that changes nothing in the document fails here.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio import profiles  # noqa: E402
from salad_studio import salad_queue  # noqa: E402
from salad_studio import salad_status  # noqa: E402
from salad_studio import studio_meta  # noqa: E402
from salad_studio import tokens as tok  # noqa: E402
from salad_studio.test_launch import _Inline, _TempPaths  # noqa: E402
from salad_studio.test_salad_queue import _FakeLifecycle  # noqa: E402

try:
    import tkinter as tk
except ImportError as _tk_err:
    tk = None  # type: ignore[assignment]
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

        app._delete_profile()
        self.assertNotIn("studio3", self._doc()["profiles"])
        self.assertNotIn("studio3", self._listed())
        self.assertEqual(set(dict(app._status_targets())), {"klein", "klein5090"})

    def test_removing_the_last_profile_leaves_the_app_usable(self) -> None:
        app = self.app
        for name in ("klein", "klein5090"):
            self._select(name)
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

    # -- the config's own Salad policy ------------------------------------
    def test_a_config_owns_its_policy_and_the_policy_page_is_gone(self) -> None:
        """Each config stores and shows its own policy; no Policy tab, no global copy."""
        app = self.app
        labels = [app.nb.tab(t, "text") for t in app.nb.tabs()]
        self.assertEqual(labels, list(self.app_mod.TAB_ORDER))
        self.assertNotIn("Policy", labels, "the Policy page must be gone")
        self.assertNotIn("Policy", self.app_mod.TAB_ORDER)
        self.assertIs(app._policy_section.master, app._config, "the fields live on Config")

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
        assert body is not None
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
        assert route is not None
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

    def test_a_checkpoint_of_another_family_is_refused_on_the_page(self) -> None:
        app = self.app
        self._select("klein5090")
        before = self._stored("klein5090")["checkpoints"]
        app.var_checkpoint.set("flux-2-klein-base-9b-fp8.safetensors")
        with mock.patch.object(self.app_mod.messagebox, "showinfo") as info:
            app._on_add_checkpoint()
        self.assertTrue(info.called, "the page must say why it refused")
        self.assertIn("one unet family", str(info.call_args))
        self.assertEqual(self._stored("klein5090")["checkpoints"], before)

    def test_an_empty_entry_says_so_instead_of_adding_blank(self) -> None:
        app = self.app
        self._select("klein")
        before = self._stored("klein")["checkpoints"]
        app.var_checkpoint.set("   ")
        app._on_add_checkpoint()
        self.assertIn("Type a checkpoint", app.var_config_note.get())
        self.assertEqual(self._stored("klein")["checkpoints"], before)

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
            (profiles.SNOFS_UNET, "klein", "klein5090"),
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

    # -- container lifecycle ----------------------------------------------
    def _prepare_snofs_generate(self, app) -> tuple[str, str]:
        """A SNOFS graph on the klein form, so routing picks klein5090."""
        stored = profiles.load_all()
        graph = {
            "prompt": {
                "70": {
                    "class_type": "UNETLoader",
                    "inputs": {"unet_name": profiles.SNOFS_UNET},
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

    def test_generate_starts_the_routed_profiles_container(self) -> None:
        """A stopped container is started for the profile routing picked."""
        app = self.app
        fake = _FakeLifecycle({"klein5090": False, "klein": True})
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
            [("start", "klein5090", want_gateway)],
            "the routed profile's container was started, once",
        )
        self.assertEqual(len(posts), 1, "the render POSTed once")
        self.assertIn(urlparse(posts[0]).hostname, want_gateway)
        self.assertEqual(
            fake.actions("stop"),
            [("stop", "klein5090", want_gateway)],
            "the app's tick stopped the idle container",
        )

    def test_a_stopped_routed_container_is_started_and_the_render_runs(self) -> None:
        """The press is not refused, the queue starts the container, the plate lands."""
        app = self.app
        fake = _FakeLifecycle({"klein5090": False, "klein": True})
        app.gen_queue = salad_queue.SaladQueue(
            on_log=app._on_queue_log, lifecycle=fake, sleep=lambda _s: None, idle_stop_s=3600
        )
        tok.write_token("salad", "stopped-container-key")
        _line, gateway = self._prepare_snofs_generate(app)
        app.var_salad_status.set("Stopped")  # what the badge shows for a stopped group
        app.log_text.delete("1.0", "end")
        refusals: list[str] = []
        with mock.patch.object(
            self.app_mod.messagebox, "showinfo", lambda *a, **k: refusals.append(str(a))
        ):
            posts = self._render_once(app)

        self.assertEqual(refusals, [], "a stopped container must not be refused")
        self.assertNotIn(
            "Generate blocked", app.log_text.get("1.0", "end"), "no refusal for a stopped group"
        )
        self.assertEqual(
            fake.actions("start"),
            [("start", "klein5090", gateway)],
            "the routed profile's stopped container is started once",
        )
        self.assertEqual(fake.actions("is_running"), [("is_running", "klein5090", gateway)])
        self.assertEqual(len(posts), 1, "the render is POSTed after the start")
        self.assertIn(urlparse(posts[0]).hostname, gateway)

    def test_an_idle_container_is_stopped_after_a_restart(self) -> None:
        """The app the user reopened still knows which container to stop.

        This is the failure: the queue's record lived in memory, so closing and
        reopening Studio forgot the container and the idle hour never arrived.
        """
        clock = {"t": 5_000_000.0}
        first = _FakeLifecycle({"klein5090": True, "klein": True})
        app = self.app
        app.gen_queue = salad_queue.SaladQueue(
            on_log=app._on_queue_log,
            lifecycle=first,
            now=lambda: clock["t"],
            ledger_path=salad_queue.LEDGER_PATH,
            idle_stop_s=3600,
        )
        tok.write_token("salad", "restart-key")
        _line, gateway = self._prepare_snofs_generate(app)
        self._render_once(app)
        self.assertEqual(app.gen_queue.containers(), {"klein5090": gateway})
        self.assertTrue(
            salad_queue.LEDGER_PATH.is_file(), "the record must be on disk"
        )
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
            {"klein5090": gateway},
            "the reopened app must still own the container",
        )
        self._tick(fresh)
        self.assertTrue(
            _pump(fresh, lambda: bool(second.actions("stop")), 30),
            "the reopened app never asked for the idle stop",
        )
        self.assertEqual(second.actions("stop"), [("stop", "klein5090", gateway)])
        self.assertEqual(second.actions("start"), [], "it was already up")


if __name__ == "__main__":
    unittest.main()
