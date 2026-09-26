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
        self.addCleanup(self.app.destroy)
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
            set(app._replica_vars),
            {"klein", "klein5090", "studio3"},
            "every profile gets a replica badge",
        )

        app.var_gateway.set("https://configured.example.salad.cloud")
        app._save_profile()
        self.assertEqual(
            self._stored("studio3")["gateway"], "https://configured.example.salad.cloud"
        )

        app._delete_profile()
        self.assertNotIn("studio3", self._doc()["profiles"])
        self.assertNotIn("studio3", self._listed())
        self.assertEqual(set(app._replica_vars), {"klein", "klein5090"})

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
    def test_generate_starts_the_routed_profiles_container(self) -> None:
        """A stopped container is started for the profile routing picked."""
        app = self.app
        stored = profiles.load_all()
        want = stored["klein5090"]
        fake = _FakeLifecycle({"klein5090": False, "klein": True})
        # idle_stop_s=0 so the tick below is allowed to stop it straight away.
        app.gen_queue = salad_queue.SaladQueue(
            on_log=app._on_queue_log, lifecycle=fake, sleep=lambda _s: None, idle_stop_s=0
        )
        tok.write_token("salad", "lifecycle-key")
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
        app.var_gateway.set(stored["klein"].gateway)  # routing moves it to klein5090
        app.var_salad_status.set("Ready")
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
                    # The app's own tick is what drives the idle check.
                    with mock.patch.object(
                        self.app_mod.salad_status,
                        "snapshot_gateway",
                        lambda gw, key: {"word": "Ready", "detail": ""},
                    ):
                        app._poll_salad_status()
                except BaseException as exc:  # noqa: BLE001 - re-raised below
                    outcome.append(exc)
                finally:
                    app.quit()

            app.after(0, body)
            app.mainloop()
        if outcome:
            raise outcome[0]

        self.assertEqual(
            fake.actions("start"),
            [("start", "klein5090", want.gateway)],
            "the routed profile's container was started, once",
        )
        self.assertEqual(len(posts), 1, "the render POSTed once")
        self.assertIn(urlparse(posts[0]).hostname, want.gateway)
        self.assertEqual(
            fake.actions("stop"),
            [("stop", "klein5090", want.gateway)],
            "the app's tick stopped the idle container",
        )


if __name__ == "__main__":
    unittest.main()
