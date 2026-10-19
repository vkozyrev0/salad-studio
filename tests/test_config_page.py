"""The Config page, driven through its controls and read back from them and from the stores.

Each test presses the page's button by its label and types into its fields, then
asserts what the user can see on the page and what the store now holds, so a
press that changes nothing fails here. Where the window has no page-level
control this page still shows (the Active profile box, the checkpoint list),
the assertion reads what the window's refresh draws for those.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
import warnings
from contextlib import contextmanager
from pathlib import Path
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


def _group(name: str, dns: str, image: str, gpu: str, startup_fail: int, readiness_fail: int) -> dict:
    """A Salad group payload shaped like the control plane's own."""
    return {
        "name": name,
        "version": 9,
        "networking": {"dns": dns},
        "container": {"image": image, "resources": {"gpu_classes": [gpu]}},
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


@contextmanager
def _warnings():
    """Flet warns about every field with neither a width nor a column; the page's are its own."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


class ConfigCase(unittest.TestCase):
    """A fresh temp store, the built-in profiles saved, and a Config page on a fake host."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.addCleanup(studio_meta.reset_cache)
        self.addCleanup(bare_meta.reset_cache)
        self._ctx = _TempPaths(Path(self._td.name))
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        profiles.ensure_builtin_profiles()
        self.host = self.open_profile(profiles.get_active() or "klein")
        self._patch_repaints()

    def open_profile(self, name: str) -> fh.Host:
        """A window showing ``name``, with its Config page built."""
        host = fh.Host()
        host.apply_profile(profiles.load_all()[name])
        with _warnings():
            host.page_config = ConfigPage(host)
        return host

    @property
    def page(self) -> ConfigPage:
        return self.host.page_config

    def use(self, name: str) -> None:
        self.host = self.open_profile(name)
        self._patch_repaints()

    def _patch_repaints(self) -> None:
        """A section repaints from its tab: Flet has it then, so the host stops saying it is missing."""
        patch = mock.patch.object(ft.Control, "update", lambda control: None, create=True)
        patch.start()
        self.addCleanup(patch.stop)

    def document(self) -> dict:
        return studio_meta.load()

    def stored(self, name: str) -> profiles.SaladProfile:
        return profiles.load_all()[name]

    def listed(self) -> list[str]:
        """The names the Active profile box offers, in order."""
        return [str(o.key) for o in self.page.profile_list.options]

    def open_section(self, key: str) -> None:
        self.page.tabs.on_change(mock.Mock(control=mock.Mock(selected={key})))

    def choose_profile(self, name: str) -> None:
        """Pick a profile in the Active profile box, as a user does."""
        self.page.profile_list.value = name
        self.page.profile_list.on_select(mock.Mock(control=self.page.profile_list))

    def choose_target(self, mode: str) -> None:
        self.page.target.selected = [mode]
        self.page.target.on_change(mock.Mock(control=self.page.target))

    def choose_image(self, tag: str) -> None:
        self.page.image.value = tag
        self.page.image.on_select(mock.Mock(control=self.page.image))

    @contextmanager
    def section(self, key: str):
        """The section tab is open while the press runs, as it is when a user presses it."""
        self.open_section(key)
        yield

    def press(self, label: str) -> None:
        with _warnings():
            fh.press(self.page, label)

    def table(self, index: int) -> list[list[str]]:
        tables = [c for c in fh.walk(self.page.vast_section) if isinstance(c, ft.DataTable)]
        return fh.table_rows(tables[index])

    def add_instance(self, typed: str) -> None:
        self.page.vast_endpoint.value = typed
        self.press("Add instance")


class ThePage(unittest.TestCase):
    def test_the_sections_are_the_four_a_deployment_runs(self) -> None:
        self.assertEqual([label for _key, label in SECTIONS],
                         ["Profile", "Images", "Salad group", "Vast.ai"])

    def test_each_segment_shows_its_own_section(self) -> None:
        case = ConfigCase("run")
        case.setUp()
        self.addCleanup(case.doCleanups)
        sections = (case.page.profile_section, case.page.images_section,
                    case.page.policy_section, case.page.vast_section)
        for section, (key, _label) in zip(sections, SECTIONS):
            case.open_section(key)
            self.assertIs(case.page.panel.content, section)


class ProfileManagement(ConfigCase):
    def test_the_page_adds_configures_and_removes_a_profile(self) -> None:
        self.assertEqual(self.listed(), ["klein", "klein5090"])

        self.page.name.value = "studio3"
        self.page.url.value = "https://third.example.salad.cloud"
        self.press("Add profile")

        self.assertEqual(self.listed(), ["klein", "klein5090", "studio3"], "the page must list it")
        added = self.stored("studio3")
        self.assertEqual(added.gateway, "https://third.example.salad.cloud")
        self.assertTrue(added.checkpoints, "a new profile is seeded with checkpoints")
        self.assertEqual(profiles.get_active(), "studio3")
        self.assertEqual(self.host.last_note(), ("ok", "Added profile studio3"))

        self.page.url.value = "https://configured.example.salad.cloud"
        self.press("Save profile")
        self.assertEqual(self.stored("studio3").gateway, "https://configured.example.salad.cloud")

        self.press("Delete profile")
        question = self.host.answer_yes()[0]
        self.assertIn("studio3", question)
        self.assertNotIn("studio3", profiles.load_all())
        self.assertEqual(self.listed(), ["klein", "klein5090"])

    def test_adding_a_name_that_exists_is_refused(self) -> None:
        self.page.name.value = "klein"
        before = self.stored("klein")
        self.press("Add profile")
        self.assertEqual(self.host.last_note(), ("warn", "Refused: there is already a profile named 'klein'"))
        self.assertEqual(self.stored("klein"), before)

    def test_removing_the_last_profile_leaves_a_default_behind(self) -> None:
        for name in ("klein", "klein5090"):
            self.choose_profile(name)
            self.press("Delete profile")
            self.host.answer_yes()
        self.assertEqual(self.listed(), ["klein"])
        self.assertEqual(self.stored("klein").name, "klein")
        self.assertEqual(profiles.get_active(), "klein", "the default becomes the active profile")

    def test_the_page_lists_every_configured_profile_in_order(self) -> None:
        for name in ("third", "fourth"):
            self.page.name.value = name
            self.press("Add profile")
        self.assertEqual(self.listed(), ["fourth", "klein", "klein5090", "third"])

    def test_picking_a_profile_loads_it_and_says_so(self) -> None:
        self.choose_profile("klein5090")
        self.assertEqual(profiles.get_active(), "klein5090")
        self.assertEqual(self.host.form.name, "klein5090")
        self.assertEqual(self.host.form.gateway, self.stored("klein5090").gateway)
        self.assertEqual(self.host.last_note(), ("info", "Loaded profile klein5090"))

    def test_saving_a_bad_size_names_the_field_in_the_dialog_and_the_line(self) -> None:
        self.host.form.width = "wide"
        self.press("Save profile")
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
        self.press("Save profile")
        self.assertTrue(self.host.dialogs[-1][2].startswith("Invalid size/steps: "), self.host.dialogs)
        self.assertIn("Steps", self.host.dialogs[-1][2])
        self.assertIn("Steps", self.host.last_note()[1])

    def test_deleting_a_saved_profile_asks_first(self) -> None:
        before = profiles.load_all()
        self.press("Delete profile")
        self.assertEqual(len(self.host.asks), 1, "a destructive Delete must ask first")
        self.assertIn("klein", self.host.asks[0][1], "and name the profile it is about to remove")
        self.assertIn("cannot be undone", self.host.asks[0][1])
        self.assertEqual(profiles.load_all(), before, "nothing is deleted before a Yes")

    def test_deleting_a_saved_profile_honours_a_yes(self) -> None:
        self.press("Delete profile")
        self.host.answer_yes()
        self.assertNotIn("klein", profiles.load_all(), "a Yes deletes it")
        self.assertEqual(self.host.last_note(), ("ok", "Deleted klein"))

    def test_deleting_a_name_that_was_never_saved_says_so_and_asks_nothing(self) -> None:
        before = profiles.load_all()
        self.page.name.value = "no-such-profile"
        self.press("Delete profile")
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
        self.press("Save profile")
        self.assertEqual(self.stored("klein").mode, "vast")

        self.choose_target("salad")
        self.choose_profile("klein")
        self.assertEqual(self.page.target.selected, ["vast"])
        self.assertEqual(self.page.url.label, "Instance URL")

    def test_use_the_selected_instance_fills_the_url_or_says_none(self) -> None:
        self.choose_target("vast")
        self.page.url.value = ""
        with self.section("vast"):
                self.press("Use the selected instance")
        self.assertEqual(self.host.last_note(), ("warn", "Refused: No vast.ai instance is selected."))
        self.assertEqual(self.page.url.value, "")

        self.add_instance("203.0.113.9:31234")
        with self.section("vast"):
                self.press("Use the selected instance")
        self.assertEqual(self.page.url.value, "http://203.0.113.9:31234")
        self.assertEqual(self.host.form.gateway, "http://203.0.113.9:31234")

    def test_use_the_selected_instance_refuses_a_row_without_an_endpoint(self) -> None:
        self.add_instance("203.0.113.9:31234")
        doc = vast.load_doc()
        doc["instances"][0]["endpoint"] = ""
        doc["active"] = ""
        vast.save_doc(doc)
        self.page.show_vast()
        with self.section("vast"):
                self.press("Use the selected instance")
        self.assertEqual(self.host.last_note(),
                         ("warn", "Refused: The selected vast.ai instance has no endpoint yet."))


class Checkpoints(ConfigCase):
    def shown(self) -> list[str]:
        return [str(c.value).removeprefix("• ") for c in self.page.checkpoint_list.controls]

    def test_the_page_adds_and_removes_a_checkpoint(self) -> None:
        before = self.stored("klein").checkpoints
        self.assertEqual(self.shown(), before)

        self.page.checkpoint.value = "flux-2-klein-5b-fp8.safetensors"
        self.press("Add")
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

        self.press("Remove selected")
        self.page.show_profile()
        self.assertNotIn("flux-2-klein-5b-fp8.safetensors", self.stored("klein").checkpoints)
        self.assertEqual(self.shown(), before)

    def test_removing_a_checkpoint_drops_the_last_one_listed(self) -> None:
        before = self.stored("klein").checkpoints
        self.press("Remove selected")
        self.assertEqual(self.stored("klein").checkpoints, before[:-1])
        self.assertEqual(self.host.last_note(), ("ok", f"Removed checkpoint {before[-1]}"))

    def test_an_empty_entry_says_so_instead_of_adding_blank(self) -> None:
        before = self.stored("klein").checkpoints
        self.page.checkpoint.value = "   "
        self.press("Add")
        self.assertEqual(self.host.last_note(),
                         ("warn", "Type a checkpoint filename or pick a label first"))
        self.assertEqual(self.stored("klein").checkpoints, before)

    def test_an_unsaved_profile_cannot_take_a_checkpoint(self) -> None:
        self.host.form.name = "not-saved"
        self.page.checkpoint.value = "flux-2-klein-5b-fp8.safetensors"
        self.press("Add")
        self.assertEqual(self.host.last_note(),
                         ("warn", "Refused: Save the profile before editing its checkpoints"))
        self.assertNotIn("not-saved", profiles.load_all())


class Images(ConfigCase):
    def setUp(self) -> None:
        super().setUp()
        self.open_section("images")

    def rows(self) -> dict[str, str]:
        return dict(str(c.value).split("=", 1) for c in self.page.env_list.controls if "=" in str(c.value))

    def drawn(self) -> str:
        return "\n".join(fh.texts(self.page.images_section))

    def test_both_documented_images_are_offered(self) -> None:
        self.assertEqual(sorted(str(o.key) for o in self.page.image.options), [KLEIN_TAG, SNOFS_TAG])

    def test_each_image_shows_its_build_command_and_its_environment(self) -> None:
        entries = {e["key"]: e for e in image_deploy.entries(self.document(), image_deploy.load_settings())}
        for family, entry in sorted(entries.items()):
            with self.subTest(family=family):
                self.choose_image(entry["tag"])
                commands = self.page.commands.value
                self.assertIn(f"docker build --build-arg {entry['build_arg']} -t {entry['tag']} "
                              f"{entry['context']}", commands)
                for key in (studio_meta.PORT_API, studio_meta.PORT_COMFY):
                    self.assertIn(f"-p {entry['ports'][key]}:{entry['ports'][key]}", commands)
                self.assertEqual(sorted(self.rows()), list(DOCUMENTED_ENV))
                self.assertIn(entry["gpu"], self.drawn(), "the GPU class a host needs is shown")

    def test_the_environment_masks_a_token_until_show_token_values(self) -> None:
        self.choose_image(KLEIN_TAG)
        self.assertEqual(self.rows()["STARTUP_CHECK_MAX_TRIES"], "120", "a documented value is shown")
        self.assertIn("HF_TOKEN=${HF_TOKEN}", self.page.commands.value)

        tok.write_token("huggingface", "hf_page_secret_value")
        self.press("Save environment")  # repaints the environment from the token store
        self.assertEqual(self.rows()["HF_TOKEN"], "set (…alue)", "a secret is masked")
        self.assertNotIn("hf_page_secret_value", self.page.commands.value)

        self.page.show_tokens.value = True
        self.press("Save environment")
        self.assertEqual(self.rows()["HF_TOKEN"], "hf_page_secret_value")
        self.assertIn("HF_TOKEN=hf_page_secret_value", self.page.commands.value)

    def test_an_added_row_is_saved_and_shown(self) -> None:
        self.choose_image(KLEIN_TAG)
        self.page.env_name.value = "VAST_TCP_PORT_22"
        self.page.env_value.value = "20000"
        self.press("Add env")
        self.assertEqual(self.host.last_note(), ("ok", "Added VAST_TCP_PORT_22"))
        self.assertEqual(image_deploy.load_settings()["env"]["klein"],
                         [{"name": "VAST_TCP_PORT_22", "value": "20000"}])
        self.assertEqual(self.rows()["VAST_TCP_PORT_22"], "20000")
        self.assertEqual((self.page.env_name.value, self.page.env_value.value), ("", ""), "the form is cleared")

    def test_a_documented_name_is_overridden_once_and_not_twice(self) -> None:
        self.choose_image(KLEIN_TAG)
        self.page.env_name.value = "HF_TOKEN"
        self.page.env_value.value = "override-value"
        self.press("Add env")
        self.assertEqual(self.rows()["HF_TOKEN"], "set (…alue)", "a secret stays masked")
        self.page.show_tokens.value = True
        self.press("Save environment")
        self.assertEqual(self.rows()["HF_TOKEN"], "override-value")

        self.page.env_name.value = "HF_TOKEN"
        self.page.env_value.value = "again"
        self.press("Add env")
        self.assertIn("already set", self.host.last_note()[1])
        self.page.env_name.value = "2FAST"
        self.press("Add env")
        self.assertIn("not a usable", self.host.last_note()[1])
        self.assertEqual(image_deploy.load_settings()["env"],
                         {"klein": [{"name": "HF_TOKEN", "value": "override-value"}]},
                         "the refusals changed nothing")

    def test_an_add_with_no_name_is_refused(self) -> None:
        self.page.env_name.value = ""
        self.press("Add env")
        self.assertEqual(self.host.last_note(), ("warn", "Refused: Name the environment variable first"))

    def test_removing_a_documented_row_says_the_document_owns_it(self) -> None:
        self.page.env_name.value = "HF_TOKEN"
        self.press("Remove selected")
        self.assertEqual(self.host.last_note(), ("warn", "Refused: HF_TOKEN is documented, not an extra"))
        self.assertEqual(len(self.rows()), 3, "nothing was removed")

    def test_removing_an_added_row_removes_it_from_the_store(self) -> None:
        self.page.env_name.value = "VAST_TCP_PORT_22"
        self.page.env_value.value = "20000"
        self.press("Add env")
        self.press("Remove selected")
        self.assertEqual(self.host.last_note(), ("ok", "Removed VAST_TCP_PORT_22"))
        self.assertEqual(image_deploy.load_settings()["env"].get("klein", []), [])

    def test_removing_with_no_name_typed_is_refused(self) -> None:
        self.page.env_name.value = ""
        self.press("Remove selected")
        self.assertEqual(self.host.last_note(), ("warn", "Refused: type the NAME of the extra to remove"))

    def test_copy_puts_the_commands_on_the_clipboard_without_a_token(self) -> None:
        tok.write_token("huggingface", "hf_clipboard_secret")
        self.choose_image(KLEIN_TAG)
        self.page.show_tokens.value = True
        self.press("Copy commands")
        text = self.host.page.clipboard
        for needle in ("docker build", "docker push", "docker run", "vastai create"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertIn(KLEIN_TAG, text)
        self.assertIn("hf_clipboard_secret", text, "a copy with the values shown carries the key")
        self.assertEqual(self.host.last_note(), ("ok", "Copied the commands"))

    def test_copy_without_a_clipboard_says_so(self) -> None:
        self.choose_image(KLEIN_TAG)

        def broken(_text):
            raise RuntimeError("no clipboard")

        self.host.page.set_clipboard = broken
        self.press("Copy commands")
        self.assertEqual(self.host.last_note(), ("warn", "Refused: the clipboard is not available"))


class SaladGroup(ConfigCase):
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
            with self.section("policy"):
                self.press("Load from Salad")

        self.assertEqual(reads, [klein.gateway], "the read names this profile's group")
        shown = self.shown()
        self.assertTrue(all(shown["startup"].values()), shown["startup"])
        self.assertEqual(shown["startup"]["failure_threshold"], "20")
        self.assertEqual(shown["readiness"]["failure_threshold"], "21")
        self.assertEqual(shown["startup"]["path"], "/health")
        self.assertEqual(shown["readiness"]["path"], "/ready")
        self.assertEqual(self.page.policy_image.value, "docker.io/example/klein:live")
        names = [str(box.label) for box in self.page.gpu_list.controls]
        self.assertIn("RTX 5090 (snofs)", names, "the class list came from the live read")
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
            with self.section("policy"):
                self.press("Load from Salad")
        self.assertEqual(self.host.dialogs[-1][2], "No container group matches this gateway DNS.")
        self.assertEqual(self.page.policy_image.value, documented["image"])
        for kind in ("startup", "readiness"):
            with self.subTest(kind=kind):
                self.assertEqual(self.shown()[kind], {k: str(v) for k, v in documented[kind].items()})

    def test_load_from_salad_refuses_an_empty_gateway(self) -> None:
        self.host.form.gateway = ""
        self.host.profile.gateway = ""
        with mock.patch.object(salad_status, "load_policy") as load:
            with self.section("policy"):
                self.press("Load from Salad")
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
            with self.section("policy"):
                self.press("Apply to Salad")
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
            with self.section("policy"):
                self.press("Apply to Salad")
        self.assertEqual(self.host.dialogs[-1][0], "error")
        self.assertIn("Salad refused the policy", self.host.dialogs[-1][2])
        self.assertIn("busy", self.host.dialogs[-1][2])

    def test_apply_refuses_an_empty_gateway_without_a_request(self) -> None:
        self.host.form.gateway = ""
        self.host.profile.gateway = ""
        with mock.patch.object(salad_status, "apply_policy") as send:
            with self.section("policy"):
                self.press("Apply to Salad")
        self.assertFalse(send.called)
        self.assertEqual(self.host.dialogs[-1], ("error", "Salad Studio", "Refused: the gateway URL is empty"))

    def test_a_new_profile_shows_the_documents_policy_for_its_family(self) -> None:
        self.page.name.value = "studio3"
        self.page.url.value = "https://third.example.salad.cloud"
        with self.section("policy"):
                self.press("Add profile")
        stored = self.stored("studio3").policy
        self.assertEqual(stored["image"], studio_meta.image_for_family("klein", self.document()))
        self.assertEqual(self.page.policy_image.value, stored["image"], "and the fields show it")

    def test_a_switch_shows_that_profiles_own_policy_and_writes_no_record(self) -> None:
        klein_saved = dict(self.stored("klein").policy)
        other_saved = dict(self.stored("klein5090").policy)
        snofs = studio_meta.image_for_family("snofs", self.document())

        self.choose_profile("klein5090")
        self.assertEqual(self.page.policy_image.value, snofs,
                         "klein5090 shows its own image, never klein's")
        self.assertFalse(self.page.policy_us.value, "klein's US-only must not follow")

        self.choose_profile("klein")
        self.assertEqual(self.page.policy_image.value, klein_saved["image"])
        self.assertEqual(self.stored("klein").policy, klein_saved, "a switch must write no record")
        self.assertEqual(self.stored("klein5090").policy, other_saved)

    def test_save_keeps_the_policy_of_each_profile_apart(self) -> None:
        self.page.policy_image.value = "docker.io/example/klein:tag1"
        self.page.policy_us.value = True
        self.fill("startup", "failure_threshold", "6")
        with self.section("policy"):
                self.press("Save profile")
        self.assertEqual(self.stored("klein").policy["image"], "docker.io/example/klein:tag1")
        self.assertEqual(self.stored("klein").policy["country_codes"], ["us"])
        self.assertEqual(self.stored("klein").policy["startup"]["failure_threshold"], "6")
        snofs = studio_meta.probe_settings_for_family("snofs", self.document())
        self.assertEqual(self.stored("klein5090").policy["startup"], snofs["startup"],
                         "the other profile keeps its own documented probes")
        self.assertNotIn("country_codes", self.stored("klein5090").policy)

    def test_reallocate_asks_first_and_reports_a_refusal_on_the_line(self) -> None:
        tok.write_token("salad", "reallocate-key")
        with mock.patch.object(salad_status, "reallocate_instance",
                               return_value=(500, "node refused the move")):
            with self.section("policy"):
                self.press("Reallocate instance")
            self.assertEqual(len(self.host.asks), 1, "a Reallocate asks before it destroys renders")
            self.host.answer_yes()
        self.assertEqual(self.host.last_note(), ("error", "Salad refused: node refused the move"))

    def test_reallocate_a_no_does_nothing(self) -> None:
        with mock.patch.object(salad_status, "reallocate_instance") as send:
            with self.section("policy"):
                self.press("Reallocate instance")
            self.host.answer_yes(lambda _body: False)
        self.assertFalse(send.called)
        self.assertEqual(self.host.notes, [])

    def test_reallocate_reports_a_created_instance(self) -> None:
        tok.write_token("salad", "reallocate-key")
        with mock.patch.object(salad_status, "reallocate_instance", return_value=(201, {})):
            with self.section("policy"):
                self.press("Reallocate instance")
            self.host.answer_yes()
        self.assertEqual(self.host.last_note(), ("ok", "Reallocated the instance"))


class VastInstances(ConfigCase):
    def setUp(self) -> None:
        super().setUp()
        self.open_section("vast")

    def test_the_section_starts_with_no_instance(self) -> None:
        self.assertEqual(self.table(0), [["(no instances)", "", "", "", "", "", ""]])

    def test_add_select_remove_and_save(self) -> None:
        self.add_instance("203.0.113.9:31234")
        self.add_instance("198.51.100.7:40111")
        self.assertEqual([row[2] for row in self.table(0)],
                         ["http://203.0.113.9:31234", "http://198.51.100.7:40111"])
        self.assertEqual(self.page.vast_endpoint.value, "", "the box is cleared for the next one")

        self.page.select_vast(1)
        self.assertEqual(vast.load_doc()["active"], "http://198.51.100.7:40111",
                         "the choice is on disk, not only on the page")
        self.assertEqual([row[6] for row in self.table(0)], ["", "*"], "the marked row is the active one")
        self.assertEqual(self.host.last_note(), ("ok", "Selected http://198.51.100.7:40111"))

        self.press("Remove")
        self.assertIn("198.51.100.7", self.host.asks[0][1], "the question names the instance")
        self.host.answer_yes()
        self.assertEqual([row[2] for row in self.table(0)], ["http://203.0.113.9:31234"])
        self.assertEqual(vast.load_doc()["instances"][0]["endpoint"], "http://203.0.113.9:31234")

        self.press("Save list")
        self.assertEqual(self.host.last_note(), ("ok", "Saved the instance list"))

    def test_a_remove_a_no_keeps_the_row(self) -> None:
        self.add_instance("203.0.113.9:31234")
        self.page.select_vast(0)
        self.press("Remove")
        self.host.answer_yes(lambda _body: False)
        self.assertEqual(len(vast.load_doc()["instances"]), 1)

    def test_a_typed_word_is_refused_and_nothing_is_saved(self) -> None:
        self.add_instance("not an address at all")
        self.assertEqual(self.table(0), [["(no instances)", "", "", "", "", "", ""]])
        self.assertEqual(vast.load_doc()["instances"], [])
        self.assertEqual(self.host.last_note(),
                         ("warn", "Refused: type an instance id or a host:port"))

    def test_a_press_that_selects_nothing_is_refused(self) -> None:
        for label in ("Set image", "New profile for instance", "Remove"):
            with self.subTest(label=label):
                self.press(label)
                self.assertEqual(self.host.last_note(), ("warn", "Refused: select an instance first"))
                self.assertEqual(self.host.asks, [])

    def test_two_instances_survive_a_reopened_page(self) -> None:
        for endpoint in ("203.0.113.9:31234", "198.51.100.7:40111"):
            self.add_instance(endpoint)
        self.use("klein")
        self.open_section("vast")
        self.assertEqual([row[2] for row in self.table(0)],
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
            self.press("Fetch instances")
        self.assertEqual(fetch.call_args.args, ("vast-page-key",), "the fetch uses the saved key")
        table = self.table(0)
        self.assertEqual([row[2] for row in table],
                         ["http://203.0.113.9:31234", "http://198.51.100.7:40111", ""],
                         "the stopped record is a row too; it just has no address")
        self.assertEqual(table[2][4], "exited")
        self.assertEqual(table[0][1], "klein-4090", "the label column shows the vast label")
        self.assertIsNone(vast.active_row(vast.load_doc()),
                          "Fetch does not promote a row it did not create")
        self.assertEqual(self.host.last_note(), ("ok", "Fetched 3 instance(s)"))

    def test_fetch_reconciles_the_evidence_state(self) -> None:
        """The measured store: one gone instance, one still booting."""
        vast.save_doc({"version": 1, "mode": "vast", "active": "http://1.193.138.161:40006",
                       "instances": [{"id": 56373341, "endpoint": "http://1.193.138.161:40006",
                                      "label": "", "gpu": "RTX 5090", "state": "running", "image": KLEIN_TAG}],
                       "replace": {},
                       "pending": {"contract": 56496191, "label": "salad-studio-53483606",
                                   "image": KLEIN_TAG}})
        old = profiles.default_profile("vast-old")
        old.mode, old.gateway = "vast", "http://1.193.138.161:40006"
        profiles.upsert(old)
        self.use("vast-old")
        self.open_section("vast")
        self.assertEqual([row[4] for row in self.table(0)][1:], ["creating"],
                         "the legacy pending contract reads as a creating row")

        record = {"id": 56496191, "label": "salad-studio-53483606", "actual_status": "loading",
                  "cur_state": "running", "public_ipaddr": "142.252.100.192", "ports": None,
                  "gpu_name": "RTX 5090"}
        with mock.patch.object(vast, "fetch_records",
                               return_value={"status": 200, "error": "", "instances": [record]}):
            self.press("Fetch instances")
        by_label = {row[1]: row for row in self.table(0) if row[1] in ("#56373341", "salad-studio-53483606")}
        self.assertEqual(by_label["#56373341"][4], "destroyed", "the deleted instance is not running")
        self.assertEqual(by_label["salad-studio-53483606"][2], "#56496191",
                         "no address until Comfy maps one")
        self.assertEqual(by_label["salad-studio-53483606"][4], "loading")
        self.assertEqual(vast.load_doc()["active"], "")
        self.assertEqual(profiles.load_all()["vast-old"].gateway, "",
                         "a vast profile holding the gone endpoint is cleared")

    def test_new_profile_for_instance_creates_a_vast_profile(self) -> None:
        self.add_instance("203.0.113.9:31234")
        self.page.select_vast(0)
        self.press("New profile for instance")
        name = self.host.form.name
        self.assertTrue(name.startswith("vast-"), name)
        stored = self.stored(name)
        self.assertEqual((stored.mode, stored.gateway), ("vast", "http://203.0.113.9:31234"))
        self.assertEqual(profiles.get_active(), name)
        self.assertIn(name, self.listed(), "the created profile is on the page")
        self.assertEqual(self.page.target.selected, ["vast"])
        self.assertEqual(self.page.url.label, "Instance URL")

    def test_set_image_records_which_image_a_row_runs(self) -> None:
        self.add_instance("203.0.113.9:31234")
        self.add_instance("198.51.100.7:40111")
        self.page.image.value = SNOFS_TAG
        self.page.select_vast(0)
        self.press("Set image")
        self.page.image.value = KLEIN_TAG
        self.page.select_vast(1)
        self.press("Set image")
        self.assertEqual([row["image"] for row in vast.load_doc()["instances"]], [SNOFS_TAG, KLEIN_TAG])


class VastOffers(ConfigCase):
    def setUp(self) -> None:
        super().setUp()
        self.open_section("vast")
        tok.write_token("vast", "vast-key")

    def search(self, offers: list[dict], seen: dict | None = None) -> None:
        def find(key, criteria, **_kwargs):
            if seen is not None:
                seen.update(criteria)
            return {"status": 200, "offers": offers, "error": ""}

        with mock.patch.object(vast, "search_offers", side_effect=find):
            self.press("Find offers")

    def test_the_rent_panel_starts_with_the_default_gpu_models(self) -> None:
        self.assertEqual(self.page.vast_gpus.value, "RTX 5090, RTX 4090")

    def test_find_offers_lists_them_highest_value_first(self) -> None:
        self.search([_offer(100, gpu_name="RTX 4090", dlperf_per_dphtotal=200.0),
                     _offer(200, gpu_name="RTX 5090", dlperf_per_dphtotal=500.0)])
        rows = self.table(1)
        self.assertEqual([row[0] for row in rows], ["RTX 5090", "RTX 4090"], "the best value is first")
        self.assertEqual(rows[0][3], "500")
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
            self.press("Create instance")
            self.assertIn("spends money", self.host.asks[0][1], "renting is a confirm")
            self.host.answer_yes()
        self.assertEqual(rent.call_args.args[1]["id"], 55818626, "the chosen offer goes to vast")
        self.assertEqual(rent.call_args.kwargs["image"], KLEIN_TAG)
        self.assertEqual(vast.load_doc()["active"], "http://203.0.113.55:40111")
        self.assertEqual([row[2] for row in self.table(0)][1:], ["http://203.0.113.55:40111"])
        self.assertEqual(self.host.last_note(), ("ok", f"Rented the offer {vast.offer_label(offer)}"))

    def test_renting_with_no_offer_is_refused(self) -> None:
        self.press("Create instance")
        self.assertEqual(self.host.last_note(), ("warn", "Refused: select an offer first"))
        self.assertEqual(self.host.asks, [])

    def test_a_failed_search_says_what_vast_answered(self) -> None:
        with mock.patch.object(vast, "search_offers",
                               return_value={"status": 401, "offers": [], "error": "HTTP 401: invalid key"}):
            self.press("Find offers")
        self.assertEqual(self.host.dialogs[-1], ("error", "Salad Studio", "HTTP 401: invalid key"))
        self.assertEqual(self.table(1), [["(Find offers)", "", "", "", "", ""]])

    def test_replace_if_destroyed_reports_what_it_did(self) -> None:
        with mock.patch.object(vast, "replace_destroyed",
                               return_value={"action": "alive", "message": "the instance is alive"}) as replace:
            self.press("Replace if destroyed")
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
