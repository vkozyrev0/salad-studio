"""The Config page: its four sections, driven through their controls and read back from the stores.

Each test types into the page's fields and calls the handler its button carries,
then asserts what a user sees on the page (a field's value, the environment
list, the commands, the tables) and what the stores now hold, so a press that
changes nothing fails here.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "salad_studio"
for _p in (PKG, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import flet as ft  # noqa: E402

import studio_meta as bare_meta  # noqa: E402  the copy image_deploy and profiles hold
from salad_studio import image_deploy, profiles, salad_status, studio_meta  # noqa: E402
from salad_studio import tokens as tok  # noqa: E402
from salad_studio import vast  # noqa: E402
from salad_studio.flet_pages import Form  # noqa: E402
from salad_studio.pages.config import PROBE_KEYS, SECTIONS, ConfigPage  # noqa: E402
from tests import _flet_host as fh  # noqa: E402
from tests.test_launch import _TempPaths  # noqa: E402

KLEIN_TAG = "docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein"
SNOFS_TAG = "docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-snofs"
DOCUMENTED_ENV = ("CIVITAI_API_TOKEN", "HF_TOKEN", "STARTUP_CHECK_MAX_TRIES")


def _offer(offer_id: int, **overrides) -> dict:
    offer = {
        "id": offer_id, "gpu_name": "RTX 4090", "gpu_ram": 24576, "disk_space": 200,
        "cuda_max_good": 13.0, "inet_down": 500, "inet_up": 200, "dph_total": 0.40,
        "rentable": True, "reliability2": 0.99, "dlperf": 97.0, "dlperf_per_dphtotal": 250.0,
        "geolocation": "Testland, TL",
    }
    offer.update(overrides)
    return offer


def _group(name: str, dns: str, image: str, gpu: str, startup_fail: int, readiness_fail: int) -> dict:
    """A Salad group payload shaped like the control plane's own."""
    return {
        "name": name, "version": 9, "networking": {"dns": dns},
        "container": {"image": image, "resources": {"gpu_classes": [gpu]}},
        "startup_probe": {"http": {"path": "/health", "port": 3000}, "initial_delay_seconds": 900,
                          "period_seconds": 60, "timeout_seconds": 10,
                          "failure_threshold": startup_fail},
        "readiness_probe": {"http": {"path": "/ready", "port": 3000}, "initial_delay_seconds": 0,
                            "period_seconds": 10, "timeout_seconds": 5,
                            "failure_threshold": readiness_fail},
        "current_state": {"status": "running"},
    }


@contextmanager
def _quiet():
    """Flet warns about every field with neither a width nor a column; the page's are its own."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def _walk(control: Any) -> list[Any]:
    """Every control under ``control``; tables and their cells included."""
    seen: set[int] = set()
    out: list[Any] = []

    def visit(node: Any) -> None:
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        out.append(node)
        if isinstance(node, (list, tuple)):
            for item in node:
                visit(item)
            return
        for attr in ("content", "controls", "actions", "segments", "rows", "cells"):
            visit(getattr(node, attr, None))

    visit(control)
    return out


def _table(page: ConfigPage, index: int) -> list[list[str]]:
    """The index'th table on the Vast.ai section, as the text in each cell."""
    tables = [c for c in _walk(page.vast_section) if isinstance(c, ft.DataTable)]
    return [[str(cell.content.value) for cell in row.cells] for row in tables[index].rows]


class ConfigCase(unittest.TestCase):
    """Temp stores, the built-in profiles saved, and a Config page on a fake host."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.addCleanup(studio_meta.reset_cache)
        self.addCleanup(bare_meta.reset_cache)
        self._ctx = _TempPaths(Path(self._td.name))
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        profiles.ensure_builtin_profiles()
        self.host = self.open_window(profiles.get_active() or "klein")

    def open_window(self, name: str) -> fh.Host:
        """A window showing ``name``, with its Config page built and its Profile tab open."""
        host = fh.Host()
        host.apply_profile(profiles.load_all()[name])
        with _quiet(), mock.patch.object(ft.Page, "update", lambda *_a: None):
            host.page_config = ConfigPage(host)
        return host

    @property
    def page(self) -> ConfigPage:
        return self.host.page_config

    def stored(self, name: str) -> profiles.SaladProfile:
        return profiles.load_all()[name]

    def document(self) -> dict:
        return studio_meta.load()

    def listed(self) -> list[str]:
        """The names the Active profile box offers, in order."""
        return [str(o.key) for o in self.page.profile_list.options]

    def open(self, key: str) -> None:
        self.page.tabs.on_change(mock.Mock(control=mock.Mock(selected={key})))

    def choose_profile(self, name: str) -> None:
        self.page.profile_list.value = name
        self.page.load_profile(name)

    def choose_target(self, mode: str) -> None:
        self.page.target.selected = [mode]
        self.page.target.on_change(mock.Mock(control=self.page.target))

    def fetched(self, *instances: dict) -> None:
        """Paste a listing into the store, as Fetch does: a stopped row has an id and no address."""
        from salad_studio import vast

        doc, _ = vast.reconcile(vast.load_doc(), list(instances), complete=True)
        vast.save_doc(doc)
        self.page.show_vast()



class ThePage(unittest.TestCase):
    def test_the_sections_are_the_four_a_deployment_runs(self) -> None:
        self.assertEqual([label for _key, label in SECTIONS],
                         ["Profile", "Images", "Salad group", "Vast.ai"])


class ProfileManagement(ConfigCase):
    def test_the_page_adds_configures_and_removes_a_profile(self) -> None:
        self.assertEqual(self.listed(), ["klein", "klein5090"])
        self.page.name.value = "studio3"
        self.page.url.value = "https://third.example.salad.cloud"
        self.page.add_profile()
        self.assertEqual(self.listed(), ["klein", "klein5090", "studio3"], "the page lists it")
        added = self.stored("studio3")
        self.assertEqual(added.gateway, "https://third.example.salad.cloud")
        self.assertTrue(added.checkpoints, "a new profile is seeded with checkpoints")
        self.assertEqual(profiles.get_active(), "studio3")
        self.assertEqual(self.host.last_note(), ("ok", "Added profile studio3"))

        self.page.url.value = "https://configured.example.salad.cloud"
        self.page.save_profile()
        self.assertEqual(self.stored("studio3").gateway, "https://configured.example.salad.cloud")

        self.page.delete_profile()
        self.assertIn("studio3", self.host.asks[0][1])
        self.host.answer_yes()
        self.assertNotIn("studio3", profiles.load_all())
        self.assertEqual(self.listed(), ["klein", "klein5090"])

    def test_adding_a_name_that_exists_is_refused(self) -> None:
        before = self.stored("klein")
        self.page.name.value = "klein"
        self.page.add_profile()
        self.assertEqual(self.host.last_note(), ("warn", "Refused: there is already a profile named 'klein'"))
        self.assertEqual(self.stored("klein"), before)

    def test_removing_the_last_profile_leaves_a_default_behind(self) -> None:
        for name in ("klein", "klein5090"):
            self.choose_profile(name)
            self.page.delete_profile()
            self.host.answer_yes()
        self.assertEqual(self.listed(), ["klein"])
        self.assertEqual(profiles.get_active(), "klein", "the default becomes the active profile")

    def test_the_page_lists_every_configured_profile_in_order(self) -> None:
        for name in ("third", "fourth"):
            self.page.name.value = name
            self.page.add_profile()
        self.assertEqual(self.listed(), ["fourth", "klein", "klein5090", "third"])

    def test_picking_a_profile_loads_it_and_says_so(self) -> None:
        self.choose_profile("klein5090")
        self.assertEqual(profiles.get_active(), "klein5090")
        self.assertEqual(self.host.form.name, "klein5090")
        self.assertEqual(self.host.form.gateway, self.stored("klein5090").gateway)
        self.assertEqual(self.host.last_note(), ("info", "Loaded profile klein5090"))

    def test_saving_a_bad_size_names_the_field_in_the_dialog_and_the_line(self) -> None:
        self.host.form.width = "wide"
        self.page.save_profile()
        level, _title, body = self.host.dialogs[-1]
        self.assertEqual(level, "error")
        self.assertTrue(body.startswith("Invalid size/steps: "), body)
        self.assertIn("Width", body)
        self.assertIn("'wide'", body)
        self.assertEqual(self.host.last_note()[0], "error")
        self.assertIn("Refused:", self.host.last_note()[1])
        self.assertEqual(self.stored("klein").width, 1024, "a refused save writes nothing")

    def test_saving_bad_steps_names_steps(self) -> None:
        self.host.form.steps = "many"
        self.page.save_profile()
        self.assertIn("Steps", self.host.dialogs[-1][2])
        self.assertIn("Steps", self.host.last_note()[1])

    def test_deleting_a_saved_profile_asks_first(self) -> None:
        before = profiles.load_all()
        self.page.delete_profile()
        self.assertIn("klein", self.host.asks[0][1], "the question names the profile")
        self.assertIn("cannot be undone", self.host.asks[0][1])
        self.assertEqual(profiles.load_all(), before, "nothing is deleted before a Yes")

    def test_deleting_a_saved_profile_honours_a_yes(self) -> None:
        self.page.delete_profile()
        self.host.answer_yes()
        self.assertNotIn("klein", profiles.load_all(), "a Yes deletes it")
        self.assertEqual(self.host.last_note(), ("ok", "Deleted klein"))

    def test_deleting_a_name_that_was_never_saved_says_so_and_asks_nothing(self) -> None:
        before = profiles.load_all()
        self.page.name.value = "no-such-profile"
        self.page.delete_profile()
        self.assertEqual(profiles.load_all(), before)
        self.assertEqual(self.host.last_note(), ("warn", "Refused: there is no profile named 'no-such-profile'"))
        self.assertEqual(self.host.asks, [], "there is nothing to confirm")



class Target(ConfigCase):
    def test_the_target_switches_the_url_label(self) -> None:
        self.assertEqual(self.page.url.label, "Gateway URL")
        self.choose_target("vast")
        self.assertEqual(self.page.url.label, "Instance URL")
        self.assertEqual(self.host.form.mode, "vast")
        self.choose_target("salad")
        self.assertEqual(self.page.url.label, "Gateway URL")
        self.assertEqual(self.host.form.mode, "salad")

    def test_the_target_saves_and_reloads_with_the_profile(self) -> None:
        self.choose_target("vast")
        self.page.save_profile()
        self.assertEqual(self.stored("klein").mode, "vast")
        self.choose_target("salad")
        self.choose_profile("klein")
        self.assertEqual(self.page.target.selected, ["vast"])
        self.assertEqual(self.page.url.label, "Instance URL")

    def test_use_the_selected_instance_fills_the_url_or_says_none(self) -> None:
        self.page.url.value = ""
        self.page.use_selected_instance()
        self.assertEqual(self.host.last_note(), ("warn", "Refused: No vast.ai instance is selected."))
        self.assertEqual(self.page.url.value, "")

        self.page.vast_endpoint.value = "203.0.113.9:31234"
        self.page.add_vast()
        self.page.use_selected_instance()
        self.assertEqual(self.page.url.value, "http://203.0.113.9:31234")
        self.assertEqual(self.host.form.gateway, "http://203.0.113.9:31234")

    def test_use_the_selected_instance_refuses_a_row_without_an_endpoint(self) -> None:
        self.fetched({"id": 777, "label": "booting", "actual_status": "loading", "ports": None})
        self.page.url.value = ""
        self.page.use_selected_instance()
        self.assertEqual(self.host.last_note(), ("warn", "Refused: No vast.ai instance is selected."),
                         "a row with no address is nothing Generate can reach")
        self.assertEqual(self.page.url.value, "")


class Checkpoints(ConfigCase):
    def shown(self) -> list[str]:
        return [str(c.value).removeprefix("• ") for c in self.page.checkpoint_list.controls]

    def test_the_page_adds_and_removes_a_checkpoint(self) -> None:
        before = self.stored("klein").checkpoints
        self.assertEqual(self.shown(), before)
        self.page.checkpoint.value = "flux-2-klein-5b-fp8.safetensors"
        self.page.add_checkpoint()
        self.page.show_profile()  # the window redraws the list after a load
        after = self.stored("klein").checkpoints
        self.assertEqual(after, before + ["flux-2-klein-5b-fp8.safetensors"])
        self.assertEqual(self.shown(), after, "the list shows the new entry")
        self.assertEqual(self.page.checkpoint.value, "", "the entry box is cleared")

        graph = {"prompt": {"70": {"class_type": "UNETLoader",
                                   "inputs": {"unet_name": "flux-2-klein-5b-fp8.safetensors"}}}}
        route, refusal = profiles.plan_route(graph, self.stored("klein5090"), profiles.load_all())
        self.assertEqual(refusal, "")
        self.assertEqual(route.name, "klein", "a graph loading the checkpoint routes to this profile")

        self.page.remove_checkpoint()
        self.assertNotIn("flux-2-klein-5b-fp8.safetensors", self.stored("klein").checkpoints)

    def test_removing_a_checkpoint_drops_the_last_one_listed(self) -> None:
        before = self.stored("klein").checkpoints
        self.page.remove_checkpoint()
        self.assertEqual(self.stored("klein").checkpoints, before[:-1])
        self.assertEqual(self.host.last_note(), ("ok", f"Removed checkpoint {before[-1]}"))

    def test_an_empty_entry_says_so_instead_of_adding_blank(self) -> None:
        before = self.stored("klein").checkpoints
        self.page.checkpoint.value = "   "
        self.page.add_checkpoint()
        self.assertEqual(self.host.last_note(),
                         ("warn", "Type a checkpoint filename or pick a label first"))
        self.assertEqual(self.stored("klein").checkpoints, before)

    def test_an_unsaved_profile_cannot_take_a_checkpoint(self) -> None:
        self.host.form.name = "not-saved"
        self.page.checkpoint.value = "flux-2-klein-5b-fp8.safetensors"
        self.page.add_checkpoint()
        self.assertEqual(self.host.last_note(),
                         ("warn", "Refused: Save the profile before editing its checkpoints"))
        self.assertNotIn("not-saved", profiles.load_all())


class Images(ConfigCase):
    def setUp(self) -> None:
        super().setUp()
        self.open("images")

    def rows(self) -> dict[str, str]:
        return dict(str(c.value).split("=", 1) for c in self.page.env_list.controls if "=" in str(c.value))

    def pick(self, tag: str) -> None:
        self.page.image.value = tag
        self.page.image.on_select(mock.Mock(control=self.page.image))

    def test_both_documented_images_are_offered(self) -> None:
        self.assertEqual(sorted(str(o.key) for o in self.page.image.options), [KLEIN_TAG, SNOFS_TAG])

    def test_each_image_shows_its_build_command_and_its_environment(self) -> None:
        documented = {e["tag"]: e for e in image_deploy.entries(self.document(), {})}
        for tag, entry in sorted(documented.items()):
            with self.subTest(tag=tag):
                self.pick(tag)
                self.assertIn(f"docker build --build-arg {entry['build_arg']} -t {tag} "
                              f"{entry['context']}", self.page.commands.value)
                for port in entry["ports"].values():
                    self.assertIn(f"-p {port}:{port}", self.page.commands.value)
                self.assertEqual(sorted(self.rows()), list(DOCUMENTED_ENV))
                self.assertIn(entry["gpu"], self.page.commands.value,
                              "the GPU class a host needs is shown")

    def test_the_environment_masks_a_token_until_show_token_values(self) -> None:
        self.pick(KLEIN_TAG)
        self.assertEqual(self.rows()["STARTUP_CHECK_MAX_TRIES"], "120", "a documented value is shown")
        tok.write_token("huggingface", "hf_page_secret_value")
        self.page.save_env()  # repaints the environment from the token store
        self.assertEqual(self.rows()["HF_TOKEN"], "set (…alue)", "a secret is masked")
        self.assertNotIn("hf_page_secret_value", self.page.commands.value)

        self.page.show_tokens.value = True
        self.page.save_env()
        self.assertEqual(self.rows()["HF_TOKEN"], "hf_page_secret_value")

    def test_an_added_row_is_saved_and_shown(self) -> None:
        self.pick(KLEIN_TAG)
        self.page.env_name.value = "VAST_TCP_PORT_22"
        self.page.env_value.value = "20000"
        self.page.add_env()
        self.assertEqual(self.host.last_note(), ("ok", "Added VAST_TCP_PORT_22"))
        self.assertEqual(image_deploy.load_settings()["env"]["klein"],
                         [{"name": "VAST_TCP_PORT_22", "value": "20000"}])
        self.assertEqual(self.rows()["VAST_TCP_PORT_22"], "20000", "the list shows the new row")
        self.assertEqual((self.page.env_name.value, self.page.env_value.value), ("", ""), "the form is cleared")

    def test_a_documented_name_is_overridden_once_and_not_twice(self) -> None:
        self.pick(KLEIN_TAG)
        self.page.env_name.value = "HF_TOKEN"
        self.page.env_value.value = "override-value"
        self.page.add_env()
        self.assertEqual(self.rows()["HF_TOKEN"], "set (…alue)", "a secret stays masked")
        self.page.env_name.value = "HF_TOKEN"
        self.page.env_value.value = "again"
        self.page.add_env()
        self.assertIn("already set", self.host.last_note()[1])
        self.page.env_name.value = "2FAST"
        self.page.add_env()
        self.assertIn("not a usable", self.host.last_note()[1])
        self.assertEqual(image_deploy.load_settings()["env"],
                         {"klein": [{"name": "HF_TOKEN", "value": "override-value"}]},
                         "the refusals changed nothing")

    def test_an_add_with_no_name_is_refused(self) -> None:
        self.page.env_name.value = ""
        self.page.add_env()
        self.assertEqual(self.host.last_note(), ("warn", "Refused: Name the environment variable first"))

    def test_removing_a_documented_row_says_the_document_owns_it(self) -> None:
        self.page.env_name.value = "HF_TOKEN"
        self.page.remove_env()
        self.assertEqual(self.host.last_note(), ("warn", "Refused: HF_TOKEN is documented, not an extra"))
        self.assertEqual(len(self.rows()), 3, "nothing was removed")

    def test_removing_an_added_row_removes_it_from_the_store(self) -> None:
        self.page.env_name.value = "VAST_TCP_PORT_22"
        self.page.env_value.value = "20000"
        self.page.add_env()
        self.page.env_name.value = "VAST_TCP_PORT_22"  # Add clears the form
        self.page.remove_env()
        self.assertEqual(self.host.last_note(), ("ok", "Removed VAST_TCP_PORT_22"))
        self.assertEqual(image_deploy.load_settings()["env"].get("klein", []), [])

    def test_removing_with_no_name_typed_is_refused(self) -> None:
        self.page.env_name.value = ""
        self.page.remove_env()
        self.assertEqual(self.host.last_note(), ("warn", "Refused: type the NAME of the extra to remove"))

    def test_copy_puts_the_commands_on_the_clipboard_without_a_token(self) -> None:
        tok.write_token("huggingface", "hf_clipboard_secret")
        self.pick(KLEIN_TAG)
        self.page.copy_commands()
        text = self.host.page.clipboard
        for needle in ("docker build", "docker push", "docker run", "vastai create"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertIn(KLEIN_TAG, text)
        self.assertNotIn("hf_clipboard_secret", text, "a copy must not carry the token")
        self.assertEqual(self.host.last_note(), ("ok", "Copied the commands"))

    def test_copy_without_a_clipboard_says_so(self) -> None:
        def broken(_text):
            raise RuntimeError("no clipboard")

        self.host.page.set_clipboard = broken
        self.page.copy_commands()
        self.assertEqual(self.host.last_note(), ("warn", "Refused: the clipboard is not available"))


class SaladGroup(ConfigCase):
    def setUp(self) -> None:
        super().setUp()
        self.open("policy")

    def shown(self) -> dict[str, dict[str, str]]:
        return {kind: {k: str(f.value or "") for k, f in self.page.probe[kind].items()}
                for kind in ("startup", "readiness")}

    def fill(self, kind: str, key: str, value: str) -> None:
        self.page.probe[kind][key].value = value

    def test_the_fields_carry_every_probe_key(self) -> None:
        self.assertEqual(set(self.page.probe["startup"]), set(PROBE_KEYS))
        self.assertEqual(set(self.page.probe["readiness"]), set(PROBE_KEYS))

    def test_load_from_salad_fills_every_probe_field_and_the_class_list(self) -> None:
        klein = self.stored("klein")
        group = _group("flux2-klein2", urlparse(klein.gateway).hostname, "docker.io/example/klein:live",
                       "gpu-klein", 20, 21)
        reads: list[str] = []

        def load(gw, key):
            reads.append(str(gw))
            return salad_status.policy_from_group(group), None

        tok.write_token("salad", "load-key")
        with mock.patch.object(salad_status, "load_policy", side_effect=load), \
                mock.patch.object(salad_status, "list_gpu_classes",
                                  return_value=[{"id": "gpu-klein", "name": "RTX 4090 (klein)"},
                                                {"id": "gpu-snofs", "name": "RTX 5090 (snofs)"}]):
            self.page.load_policy()
        self.assertEqual(reads, [klein.gateway], "the read names this profile's group")
        shown = self.shown()
        self.assertEqual((shown["startup"]["failure_threshold"], shown["startup"]["initial_delay_seconds"]),
                         ("20", "900"))
        self.assertEqual(shown["readiness"]["failure_threshold"], "21")
        self.assertEqual((shown["startup"]["path"], shown["readiness"]["path"]), ("/health", "/ready"))
        self.assertEqual(self.page.policy_image.value, "docker.io/example/klein:live")
        self.assertIn("RTX 5090 (snofs)", [str(box.label) for box in self.page.gpu_list.controls],
                      "the class list came from the live read")
        self.assertEqual(self.host.last_note(), ("ok", "Loaded the group's policy"))
        self.assertEqual(self.stored("klein").policy["image"],
                         studio_meta.image_for_family("klein", self.document()),
                         "a read does not write the profile")

    def test_a_failed_read_keeps_the_stored_policy_on_screen(self) -> None:
        documented = self.stored("klein").policy
        tok.write_token("salad", "failing-key")
        with mock.patch.object(salad_status, "load_policy",
                               return_value=(None, "No container group matches this gateway DNS.")), \
                mock.patch.object(salad_status, "list_gpu_classes", return_value=[]):
            self.page.load_policy()
        self.assertEqual(self.host.dialogs[-1][2], "No container group matches this gateway DNS.")
        self.assertEqual(self.page.policy_image.value, documented["image"])
        for kind in ("startup", "readiness"):
            with self.subTest(kind=kind):
                self.assertEqual(self.shown()[kind],
                                 {k: str(documented[kind].get(k, "")) for k in PROBE_KEYS})

    def test_load_from_salad_refuses_an_empty_gateway(self) -> None:
        self.host.form.gateway = ""
        self.host.profile.gateway = ""
        with mock.patch.object(salad_status, "load_policy") as load:
            self.page.load_policy()
        self.assertFalse(load.called)
        self.assertEqual(self.host.dialogs[-1], ("error", "Salad Studio", "Refused: the gateway URL is empty"))

    def test_apply_to_salad_sends_the_fields_to_this_profiles_group(self) -> None:
        klein = self.stored("klein")
        self.page.policy_image.value = "docker.io/example/klein:tag2"
        self.page.policy_us.value = True
        self.fill("readiness", "failure_threshold", "7")
        self.fill("readiness", "period_seconds", "20")
        tok.write_token("salad", "apply-key")
        with mock.patch.object(salad_status, "apply_policy", return_value=(200, {})) as send:
            self.page.apply_policy()
        self.assertEqual(send.call_args.args[0], klein.gateway, "the PATCH names this profile's group")
        self.assertEqual(send.call_args.args[1], "apply-key", "with the saved key")
        policy = send.call_args.args[2]
        self.assertEqual(policy["image"], "docker.io/example/klein:tag2")
        self.assertEqual(policy["country_codes"], ["us"])
        self.assertEqual(policy["gpu_classes"], [], "no GPU classes were ticked")
        self.assertEqual(policy["readiness"]["failure_threshold"], "7")
        self.assertEqual(policy["readiness"]["period_seconds"], "20")
        self.assertEqual(policy["startup"]["path"], "/health")
        self.assertEqual(self.host.last_note(), ("ok", "Applied the policy to the Salad group"))
        self.assertEqual(self.stored("klein").policy["image"], klein.policy["image"],
                         "Apply writes the group, not the profile")

    def test_apply_refused_by_salad_names_what_salad_said(self) -> None:
        tok.write_token("salad", "apply-key")
        with mock.patch.object(salad_status, "apply_policy", return_value=(409, {"error": "busy"})):
            self.page.apply_policy()
        self.assertEqual(self.host.dialogs[-1][0], "error")
        self.assertIn("Salad refused the policy", self.host.dialogs[-1][2])
        self.assertIn("busy", self.host.dialogs[-1][2])

    def test_apply_refuses_an_empty_gateway_without_a_request(self) -> None:
        self.host.form.gateway = ""
        self.host.profile.gateway = ""
        with mock.patch.object(salad_status, "apply_policy") as send:
            self.page.apply_policy()
        self.assertFalse(send.called)
        self.assertEqual(self.host.dialogs[-1], ("error", "Salad Studio", "Refused: the gateway URL is empty"))

    def test_a_new_profile_shows_the_documents_policy_for_its_family(self) -> None:
        self.page.name.value = "studio3"
        self.page.url.value = "https://third.example.salad.cloud"
        self.page.add_profile()
        stored = self.stored("studio3").policy
        self.assertEqual(stored["image"], studio_meta.image_for_family("klein", self.document()))
        self.assertEqual(self.page.policy_image.value, stored["image"], "and the fields show it")

    def test_a_switch_shows_that_profiles_own_policy_and_writes_no_record(self) -> None:
        klein_saved = dict(self.stored("klein").policy)
        other_saved = dict(self.stored("klein5090").policy)
        snofs = studio_meta.image_for_family("snofs", self.document())

        self.choose_profile("klein5090")
        self.assertEqual(self.page.policy_image.value, snofs, "klein5090 shows its own image")
        self.assertFalse(self.page.policy_us.value, "klein's US-only must not follow")
        self.choose_profile("klein")
        self.assertEqual(self.page.policy_image.value, klein_saved["image"])
        self.assertEqual(self.stored("klein").policy, klein_saved, "a switch must write no record")
        self.assertEqual(self.stored("klein5090").policy, other_saved)

    def test_save_keeps_the_policy_of_each_profile_apart(self) -> None:
        """Save writes this profile's own policy, as the Tk page did, and leaves the other's."""
        self.page.policy_image.value = "docker.io/example/klein:tag1"
        self.page.policy_us.value = True
        self.fill("startup", "failure_threshold", "6")
        self.page.save_profile()
        saved = self.stored("klein").policy
        self.assertEqual(saved["image"], "docker.io/example/klein:tag1",
                         "Save keeps the image the fields show")
        self.assertEqual(saved["country_codes"], ["us"])
        self.assertEqual(saved["startup"]["failure_threshold"], "6")
        snofs = studio_meta.probe_settings_for_family("snofs", self.document())
        self.assertEqual(self.stored("klein5090").policy["startup"], snofs["startup"],
                         "the other profile keeps its own documented probes")
        self.assertNotIn("country_codes", self.stored("klein5090").policy)

    def test_reallocate_asks_first_and_reports_a_refusal_on_the_line(self) -> None:
        tok.write_token("salad", "reallocate-key")
        with mock.patch.object(salad_status, "reallocate_instance", return_value=(500, "node refused the move")):
            self.page.reallocate()
            self.assertIn("Live renders", self.host.asks[0][1], "the question names what is lost")
            self.host.answer_yes()
        self.assertEqual(self.host.last_note(), ("error", "Salad refused: node refused the move"))

    def test_reallocate_a_no_does_nothing(self) -> None:
        with mock.patch.object(salad_status, "reallocate_instance") as send:
            self.page.reallocate()
            self.host.answer_yes(lambda _body: False)
        self.assertFalse(send.called)
        self.assertEqual(self.host.notes, [])

    def test_a_second_press_is_answered_after_the_first_returns(self) -> None:
        """Work runs in the background; the page is not told until the store holds it."""
        tok.write_token("salad", "reallocate-key")
        self.host.services.hold = True
        with mock.patch.object(salad_status, "reallocate_instance", return_value=(204, {})):
            self.page.reallocate()
            self.host.answer_yes()
            self.assertEqual(self.host.notes, [], "nothing is reported while the call is out")
            self.host.services.release()
        self.assertEqual(self.host.last_note(), ("ok", "Reallocated the instance"))

    def test_reallocate_reports_a_created_instance(self) -> None:
        tok.write_token("salad", "reallocate-key")
        with mock.patch.object(salad_status, "reallocate_instance", return_value=(201, {})):
            self.page.reallocate()
            self.host.answer_yes()
        self.assertEqual(self.host.last_note(), ("ok", "Reallocated the instance"))


class VastInstances(ConfigCase):
    def setUp(self) -> None:
        super().setUp()
        self.open("vast")

    def add(self, typed: str) -> None:
        self.page.vast_endpoint.value = typed
        self.page.add_vast()

    def test_the_section_starts_with_no_instance(self) -> None:
        self.assertEqual(_table(self.page, 0), [["(no instances)", "", "", "", "", "", ""]])

    def test_add_select_remove_and_save(self) -> None:
        self.add("203.0.113.9:31234")
        self.add("198.51.100.7:40111")
        self.assertEqual([row[2] for row in _table(self.page, 0)],
                         ["http://203.0.113.9:31234", "http://198.51.100.7:40111"])
        self.assertEqual(self.page.vast_endpoint.value, "", "the box is cleared for the next one")

        self.page.select_vast(1)
        self.assertEqual(vast.load_doc()["active"], "http://198.51.100.7:40111", "the choice is on disk")
        self.assertEqual([row[6] for row in _table(self.page, 0)], ["", "*"], "the active row is marked")

        self.page.remove_vast()
        self.assertIn("198.51.100.7", self.host.asks[0][1])
        self.host.answer_yes()
        self.assertEqual([row[2] for row in _table(self.page, 0)], ["http://203.0.113.9:31234"])
        self.assertEqual(self.host.last_note(), ("ok", "Removed the instance"))

        self.page.save_vast()
        self.assertEqual(self.host.last_note(), ("ok", "Saved the instance list"))

    def test_a_typed_word_is_refused_and_nothing_is_saved(self) -> None:
        self.add("not an address at all")
        self.assertEqual(_table(self.page, 0), [["(no instances)", "", "", "", "", "", ""]])
        self.assertEqual(vast.load_doc()["instances"], [])
        self.assertEqual(self.host.last_note(), ("warn", "Refused: type an instance id or a host:port"))

    def test_a_press_that_selects_nothing_is_refused(self) -> None:
        for action in (self.page.set_vast_image, self.page.make_profile_for_vast, self.page.remove_vast):
            with self.subTest(action=action.__name__):
                action()
                self.assertEqual(self.host.last_note(), ("warn", "Refused: select an instance first"))
                self.assertEqual(self.host.asks, [])

    def test_two_instances_survive_a_reopened_page(self) -> None:
        for endpoint in ("203.0.113.9:31234", "198.51.100.7:40111"):
            self.add(endpoint)
        self.host = self.open_window("klein")
        self.open("vast")
        self.assertEqual([row[2] for row in _table(self.page, 0)],
                         ["http://203.0.113.9:31234", "http://198.51.100.7:40111"],
                         "both instances come back after a restart")

    def test_fetch_lists_the_account_and_does_not_pick_a_row(self) -> None:
        tok.write_token("vast", "vast-page-key")
        rows = [
            {"id": 111, "label": "klein-4090", "gpu_name": "RTX 4090", "actual_status": "running",
             "public_ipaddr": "203.0.113.9", "ports": {"8188/tcp": [{"HostPort": 31234}]}},
            {"id": 222, "label": "snofs-5090", "gpu_name": "RTX 5090", "actual_status": "running",
             "public_ipaddr": "198.51.100.7", "ports": {"8188/tcp": [{"HostPort": 40111}]}},
            {"id": 333, "label": "stopped-one", "gpu_name": "RTX 3090", "actual_status": "exited",
             "public_ipaddr": "192.0.2.5", "ports": {}},
        ]
        with mock.patch.object(vast, "fetch_records",
                               return_value={"status": 200, "error": "", "instances": rows}) as fetch:
            self.page.fetch_vast()
        self.assertEqual(fetch.call_args.args, ("vast-page-key",), "the fetch uses the saved key")
        table = _table(self.page, 0)
        self.assertEqual([row[2] for row in table],
                         ["http://203.0.113.9:31234", "http://198.51.100.7:40111", "#333"],
                         "the stopped record is a row too; it shows its id where its address would be")
        self.assertEqual(table[2][4], "exited")
        self.assertEqual(table[0][1], "klein-4090", "the label column shows the vast label")
        self.assertIsNone(vast.active_row(vast.load_doc()), "Fetch does not promote a row it did not create")
        self.assertEqual(self.host.last_note(), ("ok", "Fetched 3 instance(s)"))

    def test_fetch_reconciles_the_evidence_state(self) -> None:
        """The measured store: one gone instance, one still booting."""
        vast.INSTANCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        vast.INSTANCES_PATH.write_text(json.dumps({"version": 1, "mode": "vast",
                                                   "active": "http://1.193.138.161:40006",
                                                   "instances": [{"id": 56373341,
                                                                  "endpoint": "http://1.193.138.161:40006",
                                                                  "label": "", "gpu": "RTX 5090",
                                                                  "state": "running", "image": KLEIN_TAG}],
                                                   "replace": {},
                                                   "pending": {"contract": 56496191,
                                                               "label": "salad-studio-53483606",
                                                               "image": KLEIN_TAG}}),
                                encoding="utf-8")
        old = profiles.default_profile("vast-old")
        old.mode, old.gateway = "vast", "http://1.193.138.161:40006"
        profiles.upsert(old)
        self.host = self.open_window("vast-old")
        self.open("vast")
        rows = _table(self.page, 0)
        self.assertEqual([row[0] for row in rows], ["56373341", "56496191"],
                         "a row is keyed by the instance id the account assigned")
        self.assertEqual(rows[1][1:3], ["salad-studio-53483606", "#56496191"],
                         "a row with no address shows its id where its address would be")
        self.assertEqual(rows[1][4], "creating")

        record = {"id": 56496191, "label": "salad-studio-53483606", "actual_status": "loading",
                  "cur_state": "running", "public_ipaddr": "142.252.100.192", "ports": None,
                  "gpu_name": "RTX 5090"}
        with mock.patch.object(vast, "fetch_records",
                               return_value={"status": 200, "error": "", "instances": [record]}):
            self.page.fetch_vast()
        rows = {row[0]: row for row in _table(self.page, 0)}
        self.assertEqual(rows["56373341"][4], "destroyed", "the deleted instance is not running")
        self.assertEqual(rows["56496191"][2], "#56496191", "the booting instance shows no address, only its id")
        self.assertEqual(rows["56496191"][4], "loading")
        self.assertEqual(vast.load_doc()["active"], "", "a destroyed row is never the target")

    def test_new_profile_for_instance_creates_a_vast_profile(self) -> None:
        self.add("203.0.113.9:31234")
        self.page.select_vast(0)
        self.page.make_profile_for_vast()
        name = self.host.form.name
        self.assertTrue(name.startswith("vast-"), name)
        stored = self.stored(name)
        self.assertEqual((stored.mode, stored.gateway), ("vast", "http://203.0.113.9:31234"))
        self.assertEqual(profiles.get_active(), name)
        self.assertIn(name, self.listed(), "the created profile is on the page")
        self.assertEqual(self.page.target.selected, ["vast"])
        self.assertEqual(self.page.url.label, "Instance URL")

    def test_set_image_records_which_image_a_row_runs(self) -> None:
        self.add("203.0.113.9:31234")
        self.add("198.51.100.7:40111")
        for index, tag in ((0, SNOFS_TAG), (1, KLEIN_TAG)):
            self.page.image.value = tag
            self.page.select_vast(index)
            self.page.set_vast_image()
        self.assertEqual([row["image"] for row in vast.load_doc()["instances"]], [SNOFS_TAG, KLEIN_TAG])


class VastOffers(ConfigCase):
    def setUp(self) -> None:
        super().setUp()
        self.open("vast")
        tok.write_token("vast", "vast-key")

    def search(self, offers: list[dict], seen: dict | None = None) -> None:
        def find(key, criteria, **_kwargs):
            if seen is not None:
                seen.update(criteria)
            return {"status": 200, "offers": offers, "error": ""}

        with mock.patch.object(vast, "search_offers", side_effect=find):
            self.page.search_offers()

    def test_the_rent_panel_starts_with_the_default_gpu_models(self) -> None:
        self.assertEqual(self.page.vast_gpus.value, "RTX 5090, RTX 4090")

    def test_find_offers_lists_them_as_vast_ranked_them(self) -> None:
        self.search([_offer(100, gpu_name="RTX 4090", dlperf_per_dphtotal=200.0),
                     _offer(200, gpu_name="RTX 5090", dlperf_per_dphtotal=500.0)])
        rows = _table(self.page, 1)
        self.assertEqual([row[0] for row in rows], ["RTX 4090", "RTX 5090"])
        self.assertEqual([row[3] for row in rows], ["200", "500"], "the API's own perf per dollar")
        self.assertEqual(self.host.last_note(), ("ok", "Found 2 offer(s)"))

    def test_an_empty_gpu_box_searches_the_defaults(self) -> None:
        seen: dict = {}
        self.page.vast_gpus.value = "  , "
        self.search([], seen)
        self.assertEqual(seen["gpu_names"], ["RTX 5090", "RTX 4090"])

    def test_selecting_an_offer_then_renting_asks_and_spends(self) -> None:
        offer = _offer(55818626, gpu_name="RTX 5090")
        self.search([offer])
        self.page.select_offer(0)
        self.assertEqual(self.host.last_note(), ("info", f"Selected {vast.offer_label(offer)}"))
        created = {"action": "created", "contract": 777,
                   "row": {"endpoint": "http://203.0.113.55:40111", "id": 777,
                           "label": "salad-studio-55818626", "gpu": "RTX 5090", "state": "running"},
                   "message": "created instance 777 at http://203.0.113.55:40111"}
        self.page.image.value = KLEIN_TAG
        with mock.patch.object(vast, "rent_offer", return_value=created) as rent:
            self.page.rent_offer()
            question = self.host.asks[0][1]
            self.assertIn("spends money", question, "renting is a confirm")
            self.assertNotIn("for $250.000", question, "the question names one price, not a value ratio")
            self.host.answer_yes()
        self.assertEqual(rent.call_args.args[1]["id"], 55818626, "the chosen offer goes to vast")
        self.assertEqual(rent.call_args.kwargs["image"], KLEIN_TAG)
        self.assertEqual(self.host.last_note(), ("ok", "created instance 777 at http://203.0.113.55:40111"))
        listing = vast.load_doc()
        self.assertEqual([row.get("endpoint") for row in listing.get("instances") or []],
                         ["http://203.0.113.55:40111"], "the rented instance is recorded")
        self.assertEqual(listing.get("active"), "http://203.0.113.55:40111",
                         "and Generate targets it")

    def test_renting_with_no_offer_is_refused(self) -> None:
        self.page.rent_offer()
        self.assertEqual(self.host.last_note(), ("warn", "Refused: select an offer first"))
        self.assertEqual(self.host.asks, [])

    def test_a_failed_search_says_what_vast_answered(self) -> None:
        with mock.patch.object(vast, "search_offers",
                               return_value={"status": 401, "offers": [], "error": "HTTP 401: invalid key"}):
            self.page.search_offers()
        self.assertEqual(self.host.dialogs[-1], ("error", "Salad Studio", "HTTP 401: invalid key"))

    def test_replace_if_destroyed_reports_what_it_did(self) -> None:
        with mock.patch.object(vast, "replace_destroyed",
                               return_value={"action": "alive", "message": "the instance is alive"}) as replace:
            self.page.replace_destroyed()
        self.assertEqual(self.host.last_note(), ("ok", "Replace: the instance is alive"))
        self.assertEqual(replace.call_args.kwargs["key"], "vast-key", "the press uses the saved key")


class TheForm(unittest.TestCase):
    """The window's form, which the Config fields write into and Generate reads."""

    def test_a_bad_number_is_refused_by_the_name_of_its_field(self) -> None:
        for field, raw, word in (("width", "wide", "Width"), ("steps", "many", "Steps"),
                                 ("cfg", "fast", "CFG"), ("seed", "x", "Seed")):
            with self.subTest(field=field):
                with self.assertRaises(ValueError) as caught:
                    Form(**{field: raw}).profile(None)
                self.assertIn(word, str(caught.exception))
                self.assertIn(repr(raw), str(caught.exception))

    def test_an_empty_number_takes_the_default(self) -> None:
        p = Form(width="", steps="", cfg="", seed="").profile(None)
        self.assertEqual((p.width, p.height, p.steps, p.cfg, p.seed), (1024, 1024, 20, 1.0, 1))


if __name__ == "__main__":
    unittest.main()
