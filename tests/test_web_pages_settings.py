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

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lora_store  # noqa: E402
import profiles  # noqa: E402
import salad_studio.profiles as shell_profiles  # noqa: E402  the copy ``shell`` reads through
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
        self.profile_copies = (profiles, shell_profiles)
        self.saved_profiles = (profiles.PROFILES_PATH, shell_profiles.PROFILES_PATH)
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

    def tearDown(self) -> None:
        self.hub.unsubscribe(self.sub)
        self.studio.services.stop()
        self.core.stop()
        profiles.PROFILES_PATH, shell_profiles.PROFILES_PATH = self.saved_profiles
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
        self.assertEqual(state["scheduler"], "Flux2 (Klein)")
        self.assertTrue(state["loras"])
        for row in state["loras"]:
            self.assertEqual(set(row), {"id", "label", "selected"})
        self.assertTrue(any(row["selected"] for row in state["loras"]))

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
        self.studio.apply_profile(self.profile)
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

    def test_a_page_with_no_background_work_answers_at_once(self) -> None:
        status, reply = self.engine.handle({"page": "settings", "action": "set_knobs",
                                            "args": {"width": "512"}})
        self.assertEqual(status, 200)
        self.assertTrue(reply["ok"])
        self.assertFalse(reply["pending"])
        self.assertEqual(reply["state"]["knobs"]["width"], "512")
        self.assertEqual(self.studio.form.width, "512")


def make_profile(name: str) -> profiles.SaladProfile:
    p = profiles.default_profile(name)
    return replace(p, gateway=p.gateway or "https://apple-gadogado.salad.cloud",
                   checkpoints=["flux-2-klein-base-9b-fp8.safetensors",
                                "flux-2-klein-9b-fp8.safetensors"])


if __name__ == "__main__":
    unittest.main()
