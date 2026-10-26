"""Prompt Settings on the web: the knobs, the graph's LoRAs, and the checkpoint order.

The knobs are text in the server's form until a save turns them into the
profile; a bad one is refused by name and nothing is written.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lora_store  # noqa: E402
import profiles  # noqa: E402
import salad_studio  # noqa: E402  the attribute is the one object both spellings get
from salad_studio.web import shell as shell_module  # noqa: E402  the shell's own view of it
import tokens  # noqa: E402
from salad_studio.web.core import Core  # noqa: E402
from salad_studio.web.engine import WebEngine  # noqa: E402
from salad_studio.web.events import Hub  # noqa: E402
from salad_studio.web.pages import settings as settings_page  # noqa: E402
from salad_studio.web.registry import ActionContext, Controllers  # noqa: E402
from salad_studio.web.shell import Shell  # noqa: E402

KLEIN_LORA = lora_store.DEFAULT_KLEIN_LORA_IDS[0]


class SettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        import salad_studio.tokens as pkg_tokens

        tmp = Path(self.tmp.name)
        self.profile_copies = (profiles, shell_module.profiles)
        self.saved_profiles = (profiles.PROFILES_PATH, shell_module.profiles.PROFILES_PATH)
        self.saved_loras = lora_store.EXTRAS_PATH
        self.saved_users = (tokens.LOCAL_PATH, tokens.default_path, tokens.read_env_token,
                            tokens.seed_from_defaults)
        for module in self.profile_copies:
            module.PROFILES_PATH = tmp / "studio-profiles.json"
        lora_store.EXTRAS_PATH = tmp / "studio-loras.json"
        for module in (tokens, pkg_tokens):
            module.LOCAL_PATH = tmp / "studio-tokens.json"
            module.default_path = lambda _kind: tmp / "no-default"
            module.read_env_token = lambda _kind: ""
            module.seed_from_defaults = lambda: []
        self.core = Core(workers=2).start()
        self.hub = Hub()
        self.studio = Shell(self.core, self.hub)
        self.studio.services.out_dir = Path(self.tmp.name) / "art"
        self.studio.controllers = Controllers(self.studio)
        self.studio.controllers.add(settings_page.SettingsController(self.studio))
        self.studio.services.start(timers=False)
        self.engine = WebEngine(self.studio)
        self.studio.engine = self.engine
        self.ctl = self.studio.controllers.get("settings")
        self.profile = make_profile("klein")
        for module in self.profile_copies:
            module.upsert(self.profile)
            module.set_active(self.profile.name)
        self.studio.apply_profile(self.profile)
        self.notes: list[tuple[str, str]] = []
        self.sub = self.hub.subscribe()

    def reload(self) -> None:
        """Show the stored profile again, on the core thread, as opening the studio does."""
        self.studio.apply_profile(self.studio.stored_profile())

    def tearDown(self) -> None:
        self.hub.unsubscribe(self.sub)
        self.studio.services.stop()
        self.core.stop()
        profiles.PROFILES_PATH, shell_module.profiles.PROFILES_PATH = self.saved_profiles
        lora_store.EXTRAS_PATH = self.saved_loras
        (tokens.LOCAL_PATH, tokens.default_path, tokens.read_env_token,
         tokens.seed_from_defaults) = self.saved_users
        self.tmp.cleanup()

    def call(self, action: str, **args: Any) -> tuple[ActionContext, Any]:
        ctx = ActionContext(self.studio, "settings", action, dict(args))
        keep = ctx.note
        ctx.note = lambda text, *, level="info": (self.notes.append((text, level)), keep(text, level=level))
        result = self.core.call(self.studio.controllers.table.call, f"settings.{action}", dict(args), ctx=ctx)
        self.assertIsNone(result.error, result.error and result.error.message)
        return ctx, result.data

    def stored(self) -> profiles.SaladProfile:
        return profiles.load_all()["klein"]

    # -- the view

    def test_the_view_carries_the_knobs_and_the_graphs_loras(self) -> None:
        state = self.engine.page("settings")["state"]
        self.assertEqual(set(state["knobs"]), {"width", "height", "steps", "cfg", "seed"})
        self.assertEqual(state["graphs"], list(lora_store.GRAPH_CHOICES))
        self.assertEqual(state["graph"], "Flux.2 Klein")
        self.assertIn(state["checkpoint"], state["checkpoints"])
        self.assertEqual(state["scheduler"], "flux2")
        self.assertEqual(state["schedulers"], [{"id": "flux2", "label": "Flux2 (Klein)"},
                                               {"id": "simple", "label": "Simple (Civitai)"}])
        self.assertTrue(state["loras"])
        for row in state["loras"]:
            self.assertEqual(set(row), {"id", "name", "family", "version", "selected"})
            self.assertNotIn(f"[{row['family']}]", row["name"], "the family is a field, not part of the name")
        self.assertTrue(any(row["selected"] for row in state["loras"]))

    def test_a_lora_names_its_family_and_only_the_version_the_name_omits(self) -> None:
        base = next(i for i in lora_store.list_loras() if lora_store.compatible_with_graph(i, "klein"))
        # The family already sits beside every name, so a version that opens
        # with it says the family twice; one that does not is the only thing
        # telling two versions of one name apart.
        repeats = {**base, "source": {**base.get("source", {}), "version_name": "Flux.2 Klein 9b - v2"}}
        differs = {**base, "source": {**base.get("source", {}), "version_name": "Anime v3"}}
        with mock.patch.object(settings_page.lora_store, "list_loras", return_value=[repeats, differs]):
            rows = self.ctl.state()["loras"]
        self.assertEqual([row["version"] for row in rows], ["", "Anime v3"])
        self.assertEqual({row["family"] for row in rows}, {"Flux.2 Klein"})

    def test_a_row_with_no_name_of_its_own_shows_its_civitai_id(self) -> None:
        klein = next(i for i in lora_store.list_loras()
                     if lora_store.compatible_with_graph(i, "klein"))
        item = {**klein, "name": "", "id": "civitai:2374977@2679241",
                "source": {**klein.get("source", {}), "version_id": 2679241, "version_name": "v2.0"}}
        with mock.patch.object(settings_page.lora_store, "list_loras", return_value=[item]):
            [row] = self.ctl.state()["loras"]
        self.assertEqual((row["name"], row["version"]), ("2679241", "v2.0"))

    def test_a_graph_change_returns_the_loras_that_graph_accepts(self) -> None:
        self.call("set_knobs", graph="Flux.1 Dev")
        state = self.ctl.state()
        self.assertEqual(state["graph"], "Flux.1 Dev")
        wanted = [str(i.get("id")) for i in lora_store.list_loras()
                  if lora_store.compatible_with_graph(i, "flux1")]
        self.assertEqual([row["id"] for row in state["loras"]], wanted)
        klein = [str(i.get("id")) for i in lora_store.list_loras()
                 if lora_store.compatible_with_graph(i, "klein")]
        self.assertNotEqual(sorted(wanted), sorted(klein))
        self.assertTrue(set(wanted).isdisjoint(klein))

    def test_a_checked_lora_is_the_forms_selection(self) -> None:
        self.call("toggle_lora", id=KLEIN_LORA, on=False)
        self.assertNotIn(KLEIN_LORA, self.studio.form.selected_loras)
        state = self.ctl.state()
        self.assertFalse([row for row in state["loras"] if row["id"] == KLEIN_LORA][0]["selected"])
        self.call("toggle_lora", id=KLEIN_LORA, on=True)
        self.assertIn(KLEIN_LORA, self.studio.form.selected_loras)

    def test_a_lora_outside_the_graph_is_refused(self) -> None:
        self.call("toggle_lora", id="civitai:no-such@1", on=True)
        self.assertEqual(self.notes[-1][1], "warn")
        self.assertIn("no LoRA", self.notes[-1][0])

    # -- a save writes what the section shows

    def test_a_save_turns_the_typed_knobs_into_the_profile(self) -> None:
        self.call("set_knobs", width="768", height="768", steps="8", cfg="1.5", seed="42",
                  scheduler="Simple (Civitai)", graph="Flux.1 Dev")
        self.call("toggle_lora", id=KLEIN_LORA, on=False)
        self.call("toggle_lora", id=KLEIN_LORA, on=True)
        ctx, state = self.call("save")
        self.assertEqual(self.notes[-1][1], "ok")
        self.assertEqual(set(state), {"knobs", "graphs", "graph", "schedulers", "scheduler",
                                      "checkpoints", "checkpoint", "loras"})
        saved = self.stored()
        self.assertEqual((saved.width, saved.height, saved.steps, saved.cfg, saved.seed),
                         (768, 768, 8, 1.5, 42))
        self.assertEqual(saved.scheduler, "simple")
        self.assertEqual(saved.graph, "flux1")
        self.assertIn(KLEIN_LORA, saved.selected_loras)
        self.assertEqual(profiles.load_all()["klein"].width, 768)

    def test_a_save_keeps_the_policy_the_profile_stored(self) -> None:
        self.call("save")
        self.assertEqual(self.stored().policy, self.profile.policy)

    # -- refusals name the knob

    def test_a_bad_knob_is_refused_by_name_and_nothing_is_written(self) -> None:
        self.call("set_knobs", steps="many")
        ctx, _state = self.call("save")
        self.assertEqual(self.notes[-1][1], "error")
        self.assertIn("Steps", self.notes[-1][0])
        dialog = [e for e in ctx.effects if e["kind"] == "dialog"][0]
        self.assertEqual(dialog["field"], "steps")
        self.assertEqual(self.stored().steps, 20)

    def test_a_payload_field_of_the_wrong_kind_is_a_bad_payload(self) -> None:
        status, reply = self.engine.handle({"page": "settings", "action": "toggle_lora",
                                            "args": {"id": KLEIN_LORA, "on": 1}})
        self.assertEqual(status, 200)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["errorDetail"]["field"], "on")

    # -- the checkpoint leads

    def test_selecting_a_checkpoint_reorders_the_stored_profile(self) -> None:
        self.profile = replace(self.profile, checkpoints=["flux-2-klein-base-9b-fp8.safetensors",
                                                           "flux-2-klein-9b-fp8.safetensors"])
        for module in self.profile_copies:
            module.upsert(self.profile)
        self.core.call(self.reload)
        self.assertEqual(self.ctl.state()["checkpoint"], "Base 9B")
        self.call("select_checkpoint", checkpoint="Distilled 9B")
        self.assertEqual(self.stored().checkpoints[0], "flux-2-klein-9b-fp8.safetensors")
        self.assertEqual(self.ctl.state()["checkpoint"], "Distilled 9B")

    def test_a_checkpoint_the_profile_does_not_serve_is_refused(self) -> None:
        self.profile = replace(self.profile, checkpoints=["a.safetensors"])
        for module in self.profile_copies:
            module.upsert(self.profile)
        self.studio.apply_profile(self.profile)
        self.call("select_checkpoint", checkpoint="SNOFS 9B")
        self.assertEqual(self.notes[-1][1], "warn")
        self.assertEqual(self.stored().checkpoints, ["a.safetensors"])

    def test_the_scheduler_the_page_shows_is_the_one_stored(self) -> None:
        """A reply carries the id, so a toggle that re-sends the list cannot reset the control."""
        self.studio.form.scheduler = "simple"
        self.assertEqual(self.ctl.state()["scheduler"], "simple")
        self.call("toggle_lora", id=KLEIN_LORA, on=True)
        self.assertEqual(self.ctl.state()["scheduler"], "simple")

    def test_a_page_with_no_background_work_answers_at_once(self) -> None:
        status, reply = self.engine.handle({"page": "settings", "action": "set_knobs",
                                            "args": {"width": "512"}})
        self.assertEqual(status, 200)
        self.assertTrue(reply["ok"])
        self.assertFalse(reply["pending"])
        self.assertEqual(reply["state"]["knobs"]["width"], "512")
        self.assertEqual(self.studio.form.width, "512")


class ProfileStoreCoherenceTest(unittest.TestCase):
    """The shell and the controllers must read the same profile file.

    They do not by default: ``salad_studio.profiles`` and the top-level
    ``profiles`` are two copies with two paths, and a test, a dev server or a
    driver that repoints the top-level one leaves the shell on the other. That
    is how Save to profile came to refuse a profile it had just saved.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.saved = {
            "top": profiles.PROFILES_PATH,
            "pkg": shell_module.profiles.PROFILES_PATH,
            "lora": lora_store.EXTRAS_PATH,
        }
        # Deliberately apart: the shell alone would read the package copy's file.
        profiles.PROFILES_PATH = tmp / "top" / "studio-profiles.json"
        shell_module.profiles.PROFILES_PATH = tmp / "pkg" / "studio-profiles.json"
        lora_store.EXTRAS_PATH = tmp / "loras.json"
        # The store the shell reads is registered by the controllers' module,
        # so importing it is part of standing the studio up.
        import salad_studio.web.controllers  # noqa: F401
        self.core = Core().start()
        self.studio = Shell(self.core, Hub())
        self.studio.services.out_dir = tmp / "art"
        self.studio.controllers = Controllers(self.studio)
        self.studio.controllers.add(settings_page.SettingsController(self.studio))

    def tearDown(self) -> None:
        self.core.stop()
        profiles.PROFILES_PATH = self.saved["top"]
        shell_module.profiles.PROFILES_PATH = self.saved["pkg"]
        lora_store.EXTRAS_PATH = self.saved["lora"]
        self.tmp.cleanup()

    def call(self, action: str, args: dict | None = None):
        ctx = ActionContext(self.studio, "settings", action, args or {})
        return self.studio.controllers.table.call(f"settings.{action}", dict(args or {}), ctx=ctx), ctx

    def test_one_store_answers_for_both_spellings(self) -> None:
        """A short import and the package attribute are the same module object.

        Two objects mean two path constants, and a test that repoints one
        leaves the other reading the person's real file.
        """
        import salad_studio

        self.assertIs(sys.modules["profiles"], salad_studio.profiles)
        self.assertIs(shell_module.profiles, salad_studio.profiles)
        self.assertIs(sys.modules["salad_queue"].Attempt, salad_studio.salad_queue.Attempt)

    def test_the_shell_finds_a_profile_the_controllers_wrote(self) -> None:
        """A save in the controllers must be the profile the shell reads back, on the core thread."""
        profiles.upsert(profiles.default_profile("klein"))
        self.assertEqual(self.core.call(lambda: self.studio.stored_profile().name), "klein")
        self.studio.form.cfg = "2.5"
        self.call("save")
        self.assertEqual(self.core.call(lambda: self.studio.stored_profile().cfg), 2.5)

    def test_save_writes_the_profile_the_page_edits(self) -> None:
        profiles.upsert(profiles.default_profile("klein"))
        self.core.call(lambda: self.studio.apply_profile(profiles.load_all()["klein"]))
        self.studio.form.cfg = "2.5"
        result, ctx = self.call("save")
        self.assertIsNone(result.error)
        self.assertEqual(profiles.load_all()["klein"].cfg, 2.5)
        self.assertEqual(ctx.note_text[1], "ok")

    def test_the_checkpoint_list_offers_the_label_the_page_sent(self) -> None:
        p = profiles.default_profile("klein")
        profiles.upsert(replace(p, checkpoints=["snofs-klein-9b-fp8.safetensors"]))
        self.core.call(lambda: self.studio.apply_profile(profiles.load_all()["klein"]))
        state = self.studio.controllers.get("settings").state()
        self.assertIn(state["checkpoint"], state["checkpoints"])


def make_profile(name: str) -> profiles.SaladProfile:
    p = profiles.default_profile(name)
    return replace(p, gateway=p.gateway or "https://apple-gadogado.salad.cloud",
                   checkpoints=["flux-2-klein-base-9b-fp8.safetensors",
                                "flux-2-klein-9b-fp8.safetensors"])


if __name__ == "__main__":
    unittest.main()
