"""Config on the web: its state, and the section each write belongs to.

Drives the action table with an ``ActionContext`` where the test only needs the
reply, and a ``WebEngine`` where it needs the full reply, the confirm token, or
the ``action_done`` a background action publishes.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import image_deploy  # noqa: E402
import profiles  # noqa: E402
import salad_status  # noqa: E402
import tokens  # noqa: E402
import vast  # noqa: E402
import salad_studio.profiles as shell_profiles  # noqa: E402  the copy ``shell`` reads through
from salad_studio.web.core import Core  # noqa: E402
from salad_studio.web.engine import WebEngine  # noqa: E402
from salad_studio.web.events import Hub  # noqa: E402
from salad_studio.web.pages import config as config_page  # noqa: E402
from salad_studio.web.registry import ActionContext, Controllers  # noqa: E402
from salad_studio.web.shell import Shell  # noqa: E402

USER_IMAGE = {"name": "mine", "tag": "me/mine:1", "context": "", "build_arg": "", "ports": {}}


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        import salad_studio.tokens as pkg_tokens

        tmp = Path(self.tmp.name)
        self.saved_paths = (profiles.PROFILES_PATH, image_deploy.SETTINGS_PATH, vast.INSTANCES_PATH)
        self.saved_users = (tokens.LOCAL_PATH, tokens.default_path, tokens.read_env_token,
                            tokens.seed_from_defaults)
        # ``salad_studio.profiles`` is a second copy with its own path constant,
        # and the shell reads through it.
        self.profile_copies = (profiles, shell_profiles)
        self.saved_shell_profiles = shell_profiles.PROFILES_PATH
        for module in self.profile_copies:
            module.PROFILES_PATH = tmp / "studio-profiles.json"
        image_deploy.SETTINGS_PATH = tmp / "studio-images.json"
        vast.INSTANCES_PATH = tmp / "studio-vast.json"
        for module in (tokens, pkg_tokens):
            module.LOCAL_PATH = tmp / "studio-tokens.json"
            module.default_path = lambda _kind: tmp / "no-default"
            module.read_env_token = lambda _kind: ""
            module.seed_from_defaults = lambda: []
        image_deploy.save_settings({"version": 1, "images": [dict(USER_IMAGE)], "env": {}})
        vast.save_doc(vast.empty_doc())
        self.core = Core(workers=2).start()
        self.hub = Hub()
        self.studio = Shell(self.core, self.hub)
        self.studio.controllers = Controllers(self.studio)
        self.studio.controllers.add(config_page.ConfigController(self.studio))
        self.studio.services.start(timers=False)
        self.engine = WebEngine(self.studio)
        self.studio.engine = self.engine  # the server wires this; a background action publishes through it
        self.ctl = self.studio.controllers.get("config")
        self.stored(profiles.default_profile("klein"))
        self.sub = self.hub.subscribe()
        self.notes: list[tuple[str, str]] = []

    def tearDown(self) -> None:
        self.hub.unsubscribe(self.sub)
        self.studio.services.stop()
        self.core.stop()
        profiles.PROFILES_PATH = self.saved_paths[0]
        shell_profiles.PROFILES_PATH = self.saved_shell_profiles
        image_deploy.SETTINGS_PATH, vast.INSTANCES_PATH = self.saved_paths[1:]
        (tokens.LOCAL_PATH, tokens.default_path, tokens.read_env_token,
         tokens.seed_from_defaults) = self.saved_users
        self.tmp.cleanup()

    # -- helpers

    def call(self, action: str, **args: Any) -> tuple[ActionContext, Any]:
        ctx = ActionContext(self.studio, "config", action, dict(args))
        keep = ctx.note
        ctx.note = lambda text, *, level="info": (self.notes.append((text, level)), keep(text, level=level))
        result = self.core.call(self.studio.controllers.table.call, f"config.{action}", dict(args), ctx=ctx)
        self.assertIsNone(result.error, result.error and result.error.message)
        return ctx, result.data

    def wait_done(self, timeout: float = 5.0) -> dict[str, Any]:
        """The reply a background action publishes when it finishes."""
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            item = self.sub.take(0.2)
            if item is not None and item[0] == "action_done":
                return item[1]["reply"]
        self.fail("no action_done came back")

    def stored(self, p: profiles.SaladProfile) -> None:
        """Save ``p``, and show it, as the shell keys the stored profile on the form's name."""
        if not p.gateway:
            p = replace(p, gateway="https://apple-gadogado.salad.cloud")
        for module in self.profile_copies:
            module.upsert(p)
            module.set_active(p.name)
        self.studio.apply_profile(p)

    # -- the view

    def test_the_view_carries_every_section_and_its_pieces(self) -> None:
        state = self.engine.page("config")["state"]
        self.assertEqual(state["section"], "profile")
        self.assertEqual([s["id"] for s in state["sections"]], ["profile", "images", "policy", "vast"])
        self.assertIn("selected_checkpoint", state["profile"])
        probes = state["policy"]["probes"]
        self.assertEqual(set(probes), {"startup", "readiness"})
        self.assertEqual(set(probes["startup"]), set(config_page.PROBE_KEYS))
        self.assertIn("instance_columns", state["vast"])
        self.assertIn("offer_columns", state["vast"])
        self.assertIsInstance(state["vast"]["instances"], list)

    def test_the_state_sends_options_not_the_whole_catalogue(self) -> None:
        state = self.ctl.state()
        self.assertEqual(set(state), {"section", "sections", "profile", "images", "policy", "vast"})
        self.assertNotIn("entries", state["vast"])
        self.assertNotIn("entries", state["images"], "the Images section sends tags, not entries")

    def test_the_images_section_opens_on_the_first_image_with_its_environment(self) -> None:
        images = self.ctl.state()["images"]
        self.assertTrue(images["tags"], "the Images tab needs something to offer")
        self.assertEqual(images["image"], images["tags"][0])
        self.assertTrue(images["env"], "the picked image's environment is what the section draws")
        self.assertIn("docker build", images["script"], "the deploy script goes with the image")

    def test_a_secret_is_masked_until_the_page_asks_to_see_it(self) -> None:
        tag = self.ctl.state()["images"]["tags"][0]
        self.ctl.set_env_image({"image": tag, "show_tokens": False}, ctx=None)
        masked = [row["value"] for row in self.ctl.state()["images"]["env"] if row["secret"]]
        self.ctl.set_env_image({"show_tokens": True}, ctx=None)
        shown = [row["value"] for row in self.ctl.state()["images"]["env"] if row["secret"]]
        for before, after in zip(masked, shown):
            if before.startswith("set (") or before.startswith("…"):
                self.assertNotEqual(before, after, "revealing a secret changes what the page holds")

    def test_selecting_a_checkpoint_is_visible_in_the_state(self) -> None:
        p = profiles.default_profile("two")
        p.checkpoints = ["a.safetensors", "b.safetensors"]
        self.stored(p)
        self.studio.apply_profile(p)
        self.assertEqual(self.ctl.state()["profile"]["selected_checkpoint"], "a.safetensors")
        self.call("select_checkpoint", name="b.safetensors")
        state = self.ctl.state()
        self.assertEqual(state["profile"]["selected_checkpoint"], "b.safetensors")
        self.assertEqual([c["name"] for c in state["profile"]["checkpoints"] if c["selected"]],
                         ["b.safetensors"])

    # -- a save writes what its section shows

    def test_a_profile_save_keeps_the_stored_policy(self) -> None:
        p = profiles.default_profile("saved")
        p.policy = {"group_name": "g", "version": 3, "image": "kept/image:1",
                    "country_codes": ["us"], "gpu_classes": ["gpu-1"],
                    "startup": {"path": "/kept"}}
        self.stored(p)
        self.studio.apply_profile(p)
        self.call("set_policy", image="typed/image:2", us_only=False)
        self.studio.form.width, self.studio.form.steps = "768", "12"
        self.call("save_profile", name="saved")
        stored = profiles.load_all()["saved"]
        self.assertEqual(stored.policy, p.policy)
        self.assertEqual((stored.width, stored.steps), (768, 12))

    def test_applying_the_policy_sends_what_the_policy_section_shows(self) -> None:
        sent: list[dict[str, Any]] = []
        saved = (salad_status.apply_policy, salad_status.list_gpu_classes)
        salad_status.apply_policy = lambda gw, key, policy: (sent.append(policy), (200, {}))[1]
        salad_status.list_gpu_classes = lambda key: []
        try:
            self.call("set_policy", image="typed/image:2", us_only=True, gpu_classes=["gpu-1"])
            _ctx, state = self.call("apply_policy")
            self.assertIn("open", state["policy"])
            reply = self.wait_done()
        finally:
            salad_status.apply_policy, salad_status.list_gpu_classes = saved
        self.assertTrue(reply["ok"], reply["error"])
        self.assertEqual(sent[0]["image"], "typed/image:2")
        self.assertEqual(sent[0]["country_codes"], ["us"])
        self.assertEqual(sent[0]["gpu_classes"], ["gpu-1"])

    def test_a_policy_image_keeps_a_tag_the_app_never_offered(self) -> None:
        """The image combo lists the catalogue's tags, and a hand-typed tag must still apply."""
        from salad_studio import studio_meta
        import image_deploy as deploy

        offered = [entry["tag"] for entry in deploy.entries(studio_meta.load(), deploy.load_settings())]
        self.assertTrue(offered, "the catalogue is empty, so this test proves nothing")
        for image in (offered[0], "hand/typed:tag"):
            with self.subTest(image=image):
                state = self.ctl.set_policy({"image": image}, ctx=None)
                self.assertEqual(state["policy"]["image"], image)

    def test_the_vast_set_image_uses_the_image_it_was_handed(self) -> None:
        doc, refusal = vast.add_instance(vast.load_doc(), "10.0.0.1:8188")
        self.assertEqual(refusal, "")
        vast.save_doc(vast.set_active(doc, "http://10.0.0.1:8188"))
        self.call("select_vast", index=0)
        self.call("set_vast_image", image="me/mine:1")
        self.assertIn("me/mine:1", json.dumps(vast.load_doc()))
        self.call("set_vast_image")
        self.assertIn("name the image", self.notes[-1][0])

    # -- the environment removes by name

    def test_remove_env_removes_the_named_row_not_the_typed_name(self) -> None:
        self.call("add_env", image="me/mine:1", name="A", value="1")
        self.call("add_env", image="me/mine:1", name="B", value="2")
        self.call("remove_env", image="me/mine:1", name="A")
        names = [row["name"] for row in image_deploy.load_settings()["env"]["mine"]]
        self.assertEqual(names, ["B"])
        self.assertIn("Removed A", self.notes[-1][0])

    def test_removing_a_documented_row_says_it_is_not_an_extra(self) -> None:
        self.call("remove_env", image="me/mine:1", name="HF_TOKEN")
        self.assertEqual(self.notes[-1][1], "warn")
        self.assertIn("documented", self.notes[-1][0])

    def test_add_env_on_a_documented_image_files_it_under_that_image(self) -> None:
        tag = image_deploy.tag_options(config_page._document(), image_deploy.load_settings())[0]
        entry = image_deploy.entry_by_ref(image_deploy.entries(config_page._document(), {}), tag)
        self.call("add_env", image=tag, name="MY_FLAG", value="1")
        self.assertEqual(image_deploy.load_settings()["env"][entry["key"]],
                         [{"name": "MY_FLAG", "value": "1"}])

    # -- refusals name the field

    def test_a_save_with_a_bad_knob_names_the_field(self) -> None:
        p = profiles.default_profile("klein")
        self.stored(p)
        self.studio.apply_profile(p)
        self.studio.form.steps = "twenty"
        ctx, state = self.call("save_profile", name="klein")
        self.assertIsInstance(state, dict)
        dialog = [e for e in ctx.effects if e["kind"] == "dialog"][0]
        self.assertEqual(dialog["field"], "steps")
        self.assertIn("Steps", dialog["body"])
        self.assertEqual(profiles.load_all()["klein"].steps, 20)

    def test_a_payload_field_of_the_wrong_kind_is_a_bad_payload(self) -> None:
        status, reply = self.engine.handle({"page": "config", "action": "select_vast",
                                            "args": {"index": "0"}})
        self.assertEqual(status, 200)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["errorDetail"]["kind"], "bad_payload")

    # -- confirms and background

    def test_delete_profile_asks_first_and_acts_on_the_named_profile(self) -> None:
        self.stored(profiles.default_profile("one"))
        self.stored(profiles.default_profile("two"))
        status, reply = self.engine.handle({"page": "config", "action": "delete_profile",
                                            "args": {"name": "two"}})
        self.assertEqual(status, 200)
        self.assertEqual(reply["effects"][0]["kind"], "confirm")
        self.assertIn("two", profiles.load_all())
        _status, done = self.engine.handle({"confirm": reply["effects"][0]["token"]})
        self.assertTrue(done["ok"], done["error"])
        self.assertNotIn("two", profiles.load_all())

    def test_a_refused_confirm_leaves_the_profile_alone(self) -> None:
        self.stored(profiles.default_profile("keep"))
        ctx, _state = self.call("delete_profile", name="keep")
        self.assertEqual(len(ctx.effects), 1)
        self.assertIn("keep", profiles.load_all())

    def test_loading_the_policy_answers_pending_then_completes(self) -> None:
        saved = (salad_status.list_gpu_classes, salad_status.load_policy)
        salad_status.list_gpu_classes = lambda key: [{"id": "gpu-1", "name": "RTX 5090"}]
        salad_status.load_policy = lambda gw, key: (
            {"image": "doc/image:1", "startup": {"path": "/health"}, "group_name": "grp",
             "version": 4, "gpu_classes": ["gpu-1"]}, None)
        try:
            self.studio.form.gateway = "https://apple-gadogado.salad.cloud"
            status, reply = self.engine.handle({"page": "config", "action": "load_policy", "args": {}})
            self.assertEqual(status, 200)
            self.assertTrue(reply["pending"])
            done = self.wait_done()
        finally:
            salad_status.list_gpu_classes, salad_status.load_policy = saved
        self.assertTrue(done["ok"], done["error"])
        policy = done["state"]["policy"]
        self.assertEqual(policy["group"], "grp  v4")
        self.assertEqual(policy["gpus"], [{"id": "gpu-1", "name": "RTX 5090", "selected": True}])
        self.assertEqual(policy["probes"]["startup"]["path"], "/health")

    def test_a_background_work_that_raises_is_reported_as_a_failed_action(self) -> None:
        saved = (salad_status.list_gpu_classes, salad_status.load_policy)
        salad_status.list_gpu_classes = lambda key: (_ for _ in ()).throw(RuntimeError("boom"))
        salad_status.load_policy = lambda gw, key: (None, "no")
        try:
            _status, reply = self.engine.handle({"page": "config", "action": "load_policy", "args": {}})
            self.assertTrue(reply["pending"])
            done = self.wait_done()
        finally:
            salad_status.list_gpu_classes, salad_status.load_policy = saved
        self.assertFalse(done["ok"])
        self.assertEqual(done["errorDetail"]["kind"], "failed")
        self.assertEqual(done["busy"], {})

    def test_a_group_with_no_policy_comes_back_as_a_dialog_in_done(self) -> None:
        saved = (salad_status.list_gpu_classes, salad_status.load_policy)
        salad_status.list_gpu_classes = lambda key: []
        salad_status.load_policy = lambda gw, key: (None, "No container group matches this gateway DNS.")
        try:
            _status, reply = self.engine.handle({"page": "config", "action": "load_policy", "args": {}})
            done = self.wait_done()
        finally:
            salad_status.list_gpu_classes, salad_status.load_policy = saved
        self.assertTrue(done["ok"])
        self.assertIn("No container group", [e["body"] for e in done["effects"] if e["kind"] == "dialog"][0])


if __name__ == "__main__":
    unittest.main()
