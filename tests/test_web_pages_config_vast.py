"""The Config page's profile, environment, Salad group, vast.ai, and LoRA verify paths.

Every action here reaches a store or a network. The stores come from
``tests._studio``, pointed at a temp directory; the network is always a fake.
Each test builds its own studio, because the config page keeps the selected
offer and the typed endpoint in its controller, where one test's pick would
reach another.

Actions run through the action table on the core thread with an
``ActionContext``, the style ``tests/test_web_pages_config.py`` uses. A
background action's work starts off the core thread; this waits on the
studio's busy map, which the engine clears after the done step has written the
page's note. The hub is not involved, so server timing cannot decide a result.

``vast`` takes a ``sender`` on each function and the page calls those functions
through its module global, so a test swaps ``config_page.vast._send``.
``salad_status`` has no sender, so those tests patch the function the page calls.
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import image_deploy  # noqa: E402
import lora_store  # noqa: E402
import profiles  # noqa: E402
import salad_status  # noqa: E402
import tokens  # noqa: E402
from salad_studio.web.pages import config as config_page  # noqa: E402
from salad_studio.web.registry import ActionContext  # noqa: E402
from tests._studio import Studio  # noqa: E402

# The object the page calls: its own import of the store.
vast = config_page.vast

VAST_KEY = "vast-key-7f21"
SALAD_KEY = "salad-key-1"
HF_TOKEN = "fake-hf-token"
CIVITAI_TOKEN = "fake-civitai-token"
KLEIN_TAG = "docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein"
VAST_PROFILE = "vast-http://203.0.113.9:31234"
RENTED_ENDPOINT = "http://198.51.100.20:40111"

OFFERS = [
    {"id": 101, "gpu_name": "RTX 5090", "dph_total": 0.41, "dlperf": 40.0,
     "gpu_ram": 32607, "disk_space": 200, "cuda_max_good": 13.0,
     "inet_down": 2400, "inet_up": 1200, "reliability2": 0.99},
    {"id": 102, "gpu_name": "RTX 4090", "dph_total": 0.33, "dlperf": 30.0,
     "gpu_ram": 24564, "disk_space": 180, "cuda_max_good": 13.0,
     "inet_down": 900, "inet_up": 400, "reliability2": 0.97},
    {"id": 103, "gpu_name": "RTX 4090", "dph_total": 0.29, "dlperf": 30.0,
     "gpu_ram": 24564, "disk_space": 180, "cuda_max_good": 13.0,
     "inet_down": 900, "inet_up": 400, "reliability2": 0.50},
]
LIVE_RECORD = {"id": 555, "public_ipaddr": "203.0.113.9", "actual_status": "running",
               "label": "live", "ports": {"8188/tcp": [{"HostPort": 31234}]}}
RENTED = {"id": 555, "endpoint": RENTED_ENDPOINT, "label": "", "gpu": "RTX 5090",
          "state": "running", "image": ""}


class _Transport:
    """Answers a vast.ai request by method and URL, and records every one."""

    def __init__(self, *, instances: list[dict] | None = None) -> None:
        self.requests: list = []
        self.instances = instances or []

    def __call__(self, request, timeout) -> tuple[int, bytes]:
        self.requests.append(request)
        url = request.full_url
        if url == vast.BUNDLES_URL:
            return 200, json.dumps({"offers": OFFERS}).encode()
        if request.get_method() == "PUT" and "/asks/" in url:
            return 200, json.dumps({"success": True, "new_contract": RENTED["id"]}).encode()
        if url.startswith(vast.INSTANCES_URL):
            return 200, json.dumps({"instances": self.instances}).encode()
        return 200, b"{}"

    def bodies(self, method: str) -> list[dict]:
        return [json.loads(bytes(r.data).decode("utf-8"))
                for r in self.requests if r.get_method() == method and r.data]

    def creates(self) -> list:
        return [r for r in self.requests if r.get_method() == "PUT" and "/asks/" in r.full_url]


def no_key(**kw) -> str:
    raise RuntimeError("no Vast.ai key saved")


def effect_token(reply: dict) -> str:
    [effect] = [e for e in reply["effects"] if e["kind"] == "confirm"]
    return effect["token"]


class _StudioTest(unittest.TestCase):
    """One studio per test, actions run on the action table."""

    def setUp(self) -> None:
        self.made = Studio()
        self.studio = self.made.shell
        for kind, _label, _rel in tokens.TOKEN_SPECS:
            self.studio.services.token(kind)

    def tearDown(self) -> None:
        self.made.stop()

    def run_ctx(self, page: str, action: str, args: dict | None = None) -> tuple[object, ActionContext]:
        ctx = ActionContext(self.studio, page, action, dict(args or {}))
        result = self.studio.core.call(self.studio.controllers.table.call, f"{page}.{action}",
                                       dict(args or {}), ctx=ctx)
        self.assertIsNone(result.error, result.error)
        return result.data, ctx

    def settled(self, page: str, action: str, timeout: float = 15.0) -> dict:
        """The page's state once ``action``'s background work has finished."""
        deadline = time.monotonic() + timeout
        while self.studio.busy.get(f"{page}.{action}"):
            self.assertLess(time.monotonic(), deadline, f"{action} never finished")
            time.sleep(0.02)
        time.sleep(0.05)
        state = self.studio.core.call(lambda: self.studio.controllers.get(page).state())
        return state if page == "loras" else state["vast"]

    def act(self, action: str, args: dict | None = None) -> tuple[object, ActionContext]:
        return self.run_ctx("config", action, args)

    def ok(self, action: str, args: dict | None = None) -> dict:
        state, ctx = self.act(action, args)
        return {"state": state, "effects": ctx.effects, "note": ctx.note_text, "error": ctx.error}

    def refused(self, action: str, args: dict | None = None) -> dict:
        reply = self.ok(action, args)
        self.assertEqual(reply["note"][1], "warn", reply["note"])
        return reply

    def background(self, action: str, args: dict | None = None) -> dict:
        _data, ctx = self.act(action, args)
        self.assertTrue(ctx.is_pending, f"{action} answered without the work")
        state = self.settled("config", action)
        self.assertIsNotNone(ctx.note_text, f"{action} never reported")
        return {"state": state, "effects": ctx.effects, "note": ctx.note_text, "error": ctx.error}

    def confirm(self, reply: dict) -> dict:
        """Press Yes and wait out whatever it starts."""
        status, done = self.made.engine.handle({"confirm": effect_token(reply)})
        self.assertEqual(status, 200, done)
        self.assertTrue(done["ok"], done.get("error"))
        state = self.settled("config", done["action"]) if done["pending"] else done["state"]["vast"]
        return {"state": state, "effects": done["effects"], "error": done["error"] or None}

    def save_keys(self, **keys: str) -> None:
        for kind, value in keys.items():
            tokens.write_token(kind, value)

    def select_first_visible_instance(self) -> None:
        """Select the first row that shows an endpoint; a typed row may sort first."""
        rows = self.state()["instances"]
        index = next(i for i, row in enumerate(rows) if row["endpoint"].startswith("http://"))
        self.ok("select_vast", {"index": index})

    def save_profile(self, name: str, gateway: str) -> None:
        # The shell keys save_profile on the form's name, not the payload's.
        self.studio.core.call(self.studio.form.__setattr__, "name", name)
        self.ok("save_profile", {"name": name, "gateway": gateway})

    def offers(self, gpus: str) -> dict:
        self.save_keys(vast=VAST_KEY)
        with mock.patch.object(config_page.vast, "_send", _Transport()):
            return self.background("search_offers", {"gpus": gpus})

    def state(self) -> dict:
        return self.made.state("config")["vast"]

    def vast(self) -> dict:
        """The Vast.ai section from the action the engine answers state through."""
        return self.studio.core.call(lambda: self.studio.controllers.get("config").state())["vast"]


class StoredKeys(_StudioTest):
    """An action with no key saved reports a refusal on the status line."""

    def test_searching_offers_with_no_vast_key_finds_nothing_and_says_why(self) -> None:
        done = self.background("search_offers", {"gpus": "RTX 5090"})
        self.assertEqual(done["effects"][-1]["body"], "no Vast.ai key saved")
        self.assertEqual(self.state()["offers"], [])

    def test_renting_after_the_yes_with_no_vast_key_never_sends_the_create(self) -> None:
        """The key is read after the Yes, so the store can lose it in between.

        ``services.token`` runs on the rent's own thread while the search's may
        still be reading the store, so the key is taken away through the step
        between the Yes and the PUT rather than by patching that method.
        """
        self.offers("RTX 5090")
        self.ok("select_offer", {"index": 0})
        transport = _Transport()
        with mock.patch.object(config_page.vast, "_send", transport), \
                mock.patch.object(config_page.vast, "replacement_env", side_effect=no_key):
            reply = self.ok("rent_offer", {"image": KLEIN_TAG})
            status, done = self.made.engine.handle({"confirm": effect_token(reply)})
            self.assertEqual(status, 200, done)
            deadline = time.monotonic() + 15
            while self.studio.busy.get("config.rent_offer"):
                self.assertLess(time.monotonic(), deadline, "the rent never finished")
                time.sleep(0.02)
        self.assertEqual(transport.creates(), [], "no key, no PUT")
        self.assertEqual(self.state()["instances"], [], "the rent added no instance")

    def test_replacing_with_no_vast_key_reports_the_refusal_not_a_crash(self) -> None:
        tokens.write_token("vast", "")
        done = self.background("replace_destroyed", {})
        self.assertEqual(done["effects"], [])
        self.assertEqual(done["note"], ("Replace: could not list the account's instances: no Vast.ai key saved", "ok"))


class Money(_StudioTest):
    def test_rent_without_the_yes_asks_first_and_starts_nothing(self) -> None:
        self.offers("RTX 5090")
        self.ok("select_offer", {"index": 0})
        before = self.state()["instances"]
        transport = _Transport()
        with mock.patch.object(config_page.vast, "_send", transport):
            reply = self.ok("rent_offer", {"image": KLEIN_TAG})
        [effect] = reply["effects"]
        self.assertEqual(effect["kind"], "confirm")
        self.assertIn("spends money", effect["body"])
        self.assertEqual(transport.requests, [], "nothing is sent before the Yes")
        self.assertFalse(self.studio.busy.get("config.rent_offer"), "and nothing runs")
        self.assertEqual(self.state()["instances"], before, "no instance was rented")

    def test_rent_after_the_yes_sends_the_image_and_both_render_tokens(self) -> None:
        self.save_keys(huggingface=HF_TOKEN, civitai=CIVITAI_TOKEN)
        self.offers("RTX 5090")
        self.ok("select_offer", {"index": 0})
        transport = _Transport()
        with mock.patch.object(config_page.vast, "_send", transport), \
                mock.patch.object(config_page.vast, "wait_for_instance",
                                  lambda key, contract, **kw: dict(RENTED, id=contract)):
            reply = self.ok("rent_offer", {"image": KLEIN_TAG})
            done = self.confirm(reply)
        [put] = transport.creates()
        self.assertTrue(put.full_url.endswith("/asks/101/"), "the selected offer, never another")
        [body] = transport.bodies("PUT")
        self.assertEqual(body["image"], KLEIN_TAG)
        self.assertIn(f"-e HF_TOKEN={HF_TOKEN}", body["env"])
        self.assertIn(f"-e CIVITAI_API_TOKEN={CIVITAI_TOKEN}", body["env"])
        self.assertNotIn(VAST_KEY, body["env"], "the control key never reaches the rented machine")
        self.assertIsNone(done["error"], done["error"])
        [row] = self.state()["instances"]
        self.assertEqual(row["endpoint"], RENTED_ENDPOINT)
        self.assertTrue(row["active"], "the rented instance is the one Generate uses")

    def test_rent_of_an_image_the_images_section_does_not_offer_is_refused_before_the_yes(self) -> None:
        self.offers("RTX 5090")
        self.ok("select_offer", {"index": 0})
        reply = self.refused("rent_offer", {"image": "registry.example/not-an-entry:1"})
        self.assertEqual(reply["effects"], [])
        self.assertIn("name the image", reply["note"][0])

    def test_rent_with_no_offer_selected_asks_for_one(self) -> None:
        reply = self.refused("rent_offer", {"image": KLEIN_TAG})
        self.assertIn("select an offer first", reply["note"][0])

    def test_replace_destroyed_with_replacement_switched_off_lists_the_account_and_stops(self) -> None:
        """The page passes the defaults, whose ``enabled`` is False, so it never rents here."""
        self.save_keys(vast=VAST_KEY)
        transport = _Transport()
        with mock.patch.object(config_page.vast, "_send", transport):
            done = self.background("replace_destroyed", {"gpus": "RTX 5090"})
        self.assertEqual(transport.creates(), [], "replacement is off by default: no rent")
        self.assertEqual([r.full_url for r in transport.requests], [vast.INSTANCES_URL],
                         "it lists the account and searches nothing")
        self.assertEqual(done["note"], ("Replace: the instance is gone and automatic replacement is off", "ok"))

    def test_replace_destroyed_of_a_live_instance_changes_nothing(self) -> None:
        done = self.replace_listing([LIVE_RECORD])
        self.assertEqual(done["note"], ("Replace: the instance is alive", "ok"))

    def test_replace_destroyed_of_a_booting_instance_does_not_call_it_destroyed(self) -> None:
        done = self.replace_listing([{**LIVE_RECORD, "actual_status": "loading", "ports": None}])
        self.assertNotEqual(done["note"][0], "Replace: the instance is alive")
        self.assertIn("gone", done["note"][0])

    def replace_listing(self, records: list[dict]) -> dict:
        """Replace the instance the page has selected, with the account listing ``records``."""
        self.save_keys(vast=VAST_KEY)
        self.ok("add_vast", {"endpoint": "203.0.113.9:31234"})
        self.select_first_visible_instance()
        transport = _Transport(instances=records)
        with mock.patch.object(config_page.vast, "_send", transport):
            done = self.background("replace_destroyed", {})
        self.assertEqual(transport.creates(), [], "nothing is rented for an instance that exists")
        return done


class Offers(_StudioTest):
    def test_the_search_lists_the_offers_that_clear_the_floors_best_value_first(self) -> None:
        self.save_keys(vast=VAST_KEY)
        transport = _Transport()
        with mock.patch.object(config_page.vast, "_send", transport):
            done = self.background("search_offers", {"gpus": "RTX 5090, RTX 4090"})
        self.assertEqual(transport.bodies("POST")[0]["gpu_name"]["in"], ["RTX 5090", "RTX 4090"])
        offers = [row[0] for row in self.vast()["offers"]]
        self.assertEqual(offers, ["RTX 4090", "RTX 5090"],
                         "the 0.50 reliability host is below the floor; the cheaper 4090 leads")
        self.assertIn("Found 2 offer(s)", done["note"][0])

    def test_selecting_an_offer_names_the_one_the_rent_will_use(self) -> None:
        self.offers("RTX 5090")
        reply = self.ok("select_offer", {"index": 0})
        self.assertEqual(self.vast()["selected_offer"], "RTX 5090 $0.410/hr, 2400/1200 Mbps")
        self.assertIn("Selected RTX 5090", reply["note"][0])

    def test_selecting_an_offer_outside_the_list_is_refused(self) -> None:
        reply = self.refused("select_offer", {"index": 0})
        self.assertIn("select an offer first", reply["note"][0])


class VastSection(_StudioTest):
    def test_an_endpoint_typed_then_added_is_in_the_store_on_disk(self) -> None:
        before = self.state()["instances"]
        self.ok("set_vast_endpoint", {"endpoint": "203.0.113.9:31234"})
        self.assertEqual(self.state()["instances"], before, "typing adds nothing yet")
        self.ok("add_vast", {})
        state = self.vast()
        self.assertIn("http://203.0.113.9:31234", [row["endpoint"] for row in state["instances"]])
        self.assertIn("http://203.0.113.9:31234",
                      [row["endpoint"] for row in vast.load_doc()["instances"]])

    def test_save_vast_leaves_the_list_readable_after_a_reload(self) -> None:
        before = self.state()["instances"]
        self.ok("add_vast", {"endpoint": "198.51.100.7:40111"})
        self.ok("save_vast", {})
        state = self.vast()
        self.assertIn("http://198.51.100.7:40111",
                      [r["endpoint"] for r in vast.load_doc()["instances"]])
        self.assertEqual([r["endpoint"] for r in state["instances"]],
                         [r["endpoint"] for r in before] + ["http://198.51.100.7:40111"])

    def test_the_gpu_list_typed_is_the_one_the_search_sends(self) -> None:
        self.save_keys(vast=VAST_KEY)
        self.ok("set_vast_gpus", {"gpus": "RTX A6000"})
        state = self.vast()
        self.assertEqual(state["gpus"], "RTX A6000")
        transport = _Transport()
        with mock.patch.object(config_page.vast, "_send", transport):
            self.background("search_offers", {})
        self.assertEqual(transport.bodies("POST")[0]["gpu_name"]["in"], ["RTX A6000"])

    def test_making_a_profile_without_an_instance_is_refused(self) -> None:
        reply = self.refused("make_profile_for_vast", {})
        self.assertIn("select an instance first", reply["note"][0])

    def test_a_profile_made_for_the_selected_instance_points_at_it(self) -> None:
        self.ok("add_vast", {"endpoint": "203.0.113.9:31234"})
        self.select_first_visible_instance()
        reply = self.ok("make_profile_for_vast", {})
        state = reply["state"]
        self.assertIn(VAST_PROFILE, state["profile"]["profiles"])
        saved = profiles.load_all()[VAST_PROFILE]
        self.assertEqual((saved.mode, saved.gateway), ("vast", "http://203.0.113.9:31234"))
        self.assertEqual(profiles.get_active(), VAST_PROFILE)

    def test_removing_with_no_instance_selected_is_refused(self) -> None:
        reply = self.refused("remove_vast", {})
        self.assertIn("select an instance first", reply["note"][0])

    def test_removing_an_instance_takes_the_yes_and_then_drops_it(self) -> None:
        self.ok("add_vast", {"endpoint": "198.51.100.7:40111"})
        rows = self.state()["instances"]
        index = [row["endpoint"] for row in rows].index("http://198.51.100.7:40111")
        self.ok("select_vast", {"index": index})
        reply = self.ok("remove_vast", {})
        self.assertEqual(reply["effects"][0]["kind"], "confirm")
        self.assertIn("http://198.51.100.7:40111",
                      [r["endpoint"] for r in vast.load_doc()["instances"]], "the Yes has not come yet")
        done = self.confirm(reply)
        self.assertNotIn("http://198.51.100.7:40111",
                         [r["endpoint"] for r in done["state"]["instances"]])
        self.assertNotIn("http://198.51.100.7:40111",
                         [r["endpoint"] for r in vast.load_doc()["instances"]])


class SaladGroup(_StudioTest):
    def test_reallocate_asks_first_then_calls_salad_with_the_gateway_and_key(self) -> None:
        tokens.write_token("salad", SALAD_KEY)
        self.save_profile("klein", "https://apple-gadogado.salad.cloud")
        with mock.patch.object(salad_status, "reallocate_instance", return_value=(200, {})) as call:
            reply = self.ok("reallocate", {})
            self.assertEqual(reply["effects"][0]["kind"], "confirm")
            self.assertFalse(call.called, "nothing is reallocated before the Yes")
            done = self.confirm(reply)
        call.assert_called_once_with("https://apple-gadogado.salad.cloud", SALAD_KEY)
        self.assertEqual(done["state"], self.vast(), "the page shows the studio's state")

    def test_a_refused_reallocate_says_what_salad_answered(self) -> None:
        tokens.write_token("salad", "")
        with mock.patch.object(salad_status, "reallocate_instance",
                               return_value=(404, {"error": "No instance to reallocate."})) as call:
            reply = self.ok("reallocate", {})
            done = self.confirm(reply)
        self.assertEqual(call.call_args.args[1], "", "no Salad key saved, so an empty one is sent")
        self.assertIsNone(done["error"], done["error"])


class ProfileSection(_StudioTest):
    def test_add_profile_stores_it_makes_it_active_and_the_page_lists_it(self) -> None:
        state = self.ok("add_profile", {"name": "second", "gateway": "https://second.example"})["state"]
        self.assertEqual(state["profile"]["profiles"], ["second"])
        self.assertEqual(profiles.get_active(), "second")
        self.assertEqual(profiles.load_all()["second"].gateway, "https://second.example")
        self.assertTrue(state["profile"]["checkpoints_editable"], "a stored profile owns its checkpoints")
        self.assertEqual(self.ok("add_profile", {"name": "third"})["note"], ("Added profile third", "ok"))

    def test_add_profile_with_a_taken_name_is_refused(self) -> None:
        self.ok("add_profile", {"name": "second"})
        reply = self.refused("add_profile", {"name": "second"})
        self.assertIn("already a profile named 'second'", reply["note"][0])

    def test_load_profile_switches_the_form_to_the_stored_one(self) -> None:
        self.ok("add_profile", {"name": "one", "gateway": "https://one.example"})
        self.ok("add_profile", {"name": "two", "gateway": "https://two.example"})
        state = self.ok("load_profile", {"name": "one"})["state"]
        self.assertEqual(state["profile"]["name"], "one")
        self.assertEqual(self.studio.form.gateway, "https://one.example")
        self.assertEqual(profiles.get_active(), "one")

    def test_load_profile_of_a_name_that_is_not_stored_is_refused(self) -> None:
        reply = self.refused("load_profile", {"name": "ghost"})
        self.assertIn("no profile named 'ghost'", reply["note"][0])

    def test_a_rename_through_save_profile_writes_the_new_name(self) -> None:
        self.ok("add_profile", {"name": "old-name", "gateway": "https://old.example"})
        state = self.ok("save_profile", {"name": "new-name", "gateway": "https://old.example"})["state"]
        self.assertIn("new-name", profiles.load_all())
        self.assertEqual(profiles.load_all()["new-name"].gateway, "https://old.example")
        self.assertEqual(state["profile"]["name"], "new-name")
        self.assertEqual(profiles.get_active(), "new-name")

    def test_a_checkpoint_added_is_stored_and_selected_then_removed(self) -> None:
        self.ok("add_profile", {"name": "klein"})
        name = "extra-klein-9b-fp8.safetensors"
        state = self.ok("add_checkpoint", {"text": name})["state"]
        self.assertIn(name, profiles.load_all()["klein"].checkpoints)
        self.assertEqual(state["profile"]["selected_checkpoint"], name)

        state = self.ok("remove_checkpoint", {"name": name})["state"]
        self.assertNotIn(name, profiles.load_all()["klein"].checkpoints)
        self.assertNotIn(name, [row["name"] for row in state["profile"]["checkpoints"]])

    def test_a_checkpoint_on_a_profile_that_is_not_saved_is_refused(self) -> None:
        reply = self.refused("add_checkpoint", {"text": "flux-2-klein-9b-fp8.safetensors"})
        self.assertIn("Save the profile", reply["note"][0])
        reply = self.refused("remove_checkpoint", {"name": "x.safetensors"})
        self.assertIn("lists no checkpoints", reply["note"][0])


class EnvSection(_StudioTest):
    def test_an_environment_row_added_survives_save_env(self) -> None:
        self.ok("add_env", {"image": "klein", "name": "MY_FLAG", "value": "1"})
        self.ok("save_env", {})
        rows = image_deploy.extra_env(image_deploy.load_settings(), "klein")
        self.assertIn("MY_FLAG", [row.get("name") for row in rows])


class Loras(_StudioTest):
    EXTRA = {
        "id": "civitai:9001@9002",
        "name": "Watercolor Ink",
        "kind": "lora",
        "base": "",
        "status": "user",
        "verified": False,
        "source": {"host": "civitai", "page": "https://civitai.com/models/9001",
                   "download": "https://civitai.com/api/download/models/9002",
                   "filename": "watercolor.safetensors", "version_id": 9002},
    }

    def row(self) -> dict:
        return next(r for r in self.made.state("loras")["rows"] if r["id"] == self.EXTRA["id"])

    def test_verify_selected_turns_an_unverified_row_verified(self) -> None:
        lora_store.write_extra(dict(self.EXTRA))
        self.made.act("loras", "select", {"id": self.EXTRA["id"]})
        self.assertFalse(self.row()["verified"])
        version = {"id": 9002, "modelId": 9001,
                   "files": [{"name": "watercolor.safetensors", "primary": True}]}
        with mock.patch.object(lora_store, "fetch_civitai_version", return_value=version):
            _data, ctx = self.run_ctx("loras", "verify_selected")
            self.assertTrue(ctx.is_pending, ctx.note_text)
            self.settled("loras", "verify_selected")
        self.assertTrue(self.row()["verified"], "the row on the page says verified")
        self.assertTrue(lora_store.find_lora(self.EXTRA["id"])["verified"], "and the store on disk")
        self.assertEqual(ctx.note_text, ("Watercolor Ink: verified", "ok"))


if __name__ == "__main__":
    unittest.main()
