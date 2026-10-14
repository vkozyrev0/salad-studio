"""Image deployment: the two images, their env params, and the deploy commands.

The facts come from the shipped metadata document and the user's own store is a
temp file, so every test drives the shipped functions with values it can read
back. The token values are passed in as a map, never read from the token store.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "salad_studio"
for _p in (PKG, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio import image_deploy as deploy, studio_meta  # noqa: E402
from tests.test_launch import _TempPaths  # noqa: E402

try:
    import tkinter as tk
except ImportError as _tk_err:
    tk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = _tk_err
else:
    _TK_IMPORT_ERROR = None

KLEIN_TAG = "docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein"
SNOFS_TAG = "docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-snofs"
TOKENS = {"huggingface": "hf_supersecret_value", "civitai": "civitai_secret_value"}


class EntriesFromTheDocument(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = studio_meta.load()
        self.entries = deploy.entries(self.doc)

    def test_both_images_are_entries_with_their_deployment_facts(self) -> None:
        by_key = {entry["key"]: entry for entry in self.entries}
        self.assertEqual(sorted(by_key), ["klein", "snofs"])
        klein = by_key["klein"]
        self.assertEqual(klein["tag"], KLEIN_TAG)
        self.assertEqual(klein["build_arg"], "KLEIN_UNET_SET=base,distilled")
        self.assertEqual(klein["context"], "salad_klein")
        self.assertEqual(klein["gpu"], "RTX 4090 24 GB")
        self.assertEqual(klein["disk_gb"], 100)
        self.assertEqual(
            klein["ports"], {studio_meta.PORT_API: 3000, studio_meta.PORT_COMFY: 8188}
        )
        self.assertEqual(
            [row[studio_meta.ENV_NAME] for row in klein["env"]],
            ["HF_TOKEN", "CIVITAI_API_TOKEN", "STARTUP_CHECK_MAX_TRIES"],
        )
        self.assertEqual(by_key["snofs"]["build_arg"], "KLEIN_UNET_SET=snofs")
        self.assertEqual(by_key["snofs"]["gpu"], "RTX 5090 32 GB")
        self.assertTrue(all(entry["source"] == deploy.SOURCE_DOCUMENT for entry in self.entries))

    def test_a_reference_finds_the_entry_by_key_family_or_tag(self) -> None:
        for ref in ("klein", "snofs", KLEIN_TAG, KLEIN_TAG.upper(), "  klein  "):
            with self.subTest(ref=ref):
                found = deploy.entry_by_ref(self.entries, ref)
                self.assertIsNotNone(found, ref)
                self.assertIn("klein", str(found["key"]) + str(found["tag"]))
        self.assertIsNone(deploy.entry_by_ref(self.entries, ""))
        self.assertIsNone(deploy.entry_by_ref(self.entries, "no-such-image"))

    def test_the_tag_options_are_what_a_page_offers_as_a_reference(self) -> None:
        self.assertEqual(deploy.tag_options(self.doc), [KLEIN_TAG, SNOFS_TAG])

    def test_a_family_the_document_gives_no_image_is_not_an_entry(self) -> None:
        doc = {"routing": {"families": {"klein": {"image": "", "unets": ["x"]}}}}
        self.assertEqual(deploy.entries(doc), [])
        self.assertEqual(deploy.entries(None), [])


class EnvRows(unittest.TestCase):
    def setUp(self) -> None:
        self.entry = deploy.entry_by_ref(deploy.entries(studio_meta.load()), "klein")

    def test_a_token_slot_is_resolved_and_a_literal_is_kept(self) -> None:
        rows = deploy.env_rows(self.entry, None, TOKENS)
        by_name = {row[studio_meta.ENV_NAME]: row for row in rows}
        self.assertEqual(by_name["HF_TOKEN"][studio_meta.ENV_VALUE], "hf_supersecret_value")
        self.assertEqual(by_name["HF_TOKEN"]["source"], "token")
        self.assertEqual(by_name["HF_TOKEN"]["secret"], "yes")
        self.assertIn("gated", by_name["HF_TOKEN"][studio_meta.ENV_NOTE])
        self.assertEqual(by_name["STARTUP_CHECK_MAX_TRIES"][studio_meta.ENV_VALUE], "120")
        self.assertEqual(by_name["STARTUP_CHECK_MAX_TRIES"]["source"], "document")
        self.assertEqual(by_name["STARTUP_CHECK_MAX_TRIES"]["secret"], "no")

    def test_the_users_row_replaces_the_documented_one(self) -> None:
        rows = deploy.env_rows(
            self.entry, [{studio_meta.ENV_NAME: "HF_TOKEN", studio_meta.ENV_VALUE: "mine"}], TOKENS
        )
        hf = [row for row in rows if row[studio_meta.ENV_NAME] == "HF_TOKEN"]
        self.assertEqual(len(hf), 1, "one row per name, not two")
        self.assertEqual(hf[0][studio_meta.ENV_VALUE], "mine")
        self.assertEqual(hf[0]["source"], "yours")

    def test_the_users_own_row_is_appended(self) -> None:
        rows = deploy.env_rows(
            self.entry, [{studio_meta.ENV_NAME: "VAST_TCP_PORT_22", studio_meta.ENV_VALUE: "20000"}], TOKENS
        )
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1][studio_meta.ENV_NAME], "VAST_TCP_PORT_22")
        self.assertEqual(rows[-1]["source"], "yours")

    def test_a_secret_is_masked_until_the_caller_asks_for_it(self) -> None:
        rows = deploy.env_rows(self.entry, None, TOKENS)
        hf = next(row for row in rows if row[studio_meta.ENV_NAME] == "HF_TOKEN")
        self.assertEqual(deploy.shown_value(hf), "set (…alue)")
        self.assertEqual(deploy.shown_value(hf, include_values=True), "hf_supersecret_value")
        startup = next(row for row in rows if row[studio_meta.ENV_NAME] == "STARTUP_CHECK_MAX_TRIES")
        self.assertEqual(deploy.shown_value(startup), "120", "a literal is never masked")
        self.assertEqual(deploy.mask(""), "(missing)")


class Commands(unittest.TestCase):
    def setUp(self) -> None:
        self.entry = deploy.entry_by_ref(deploy.entries(studio_meta.load()), "snofs")
        self.rows = deploy.env_rows(self.entry, None, TOKENS)

    def test_build_and_push_carry_the_tag_the_arg_and_the_context(self) -> None:
        self.assertEqual(
            deploy.build_command(self.entry),
            f"docker build --build-arg KLEIN_UNET_SET=snofs -t {SNOFS_TAG} salad_klein",
        )
        self.assertEqual(deploy.push_command(self.entry), f"docker push {SNOFS_TAG}")

    def test_the_docker_run_line_carries_the_ports_and_the_env(self) -> None:
        line = deploy.docker_run_command(self.entry, self.rows)
        self.assertTrue(line.startswith("docker run --gpus all"), line)
        self.assertIn("-p 3000:3000", line)
        self.assertIn("-p 8188:8188", line)
        self.assertIn("-e HF_TOKEN=${HF_TOKEN}", line, "a secret stays a placeholder")
        self.assertIn("-e STARTUP_CHECK_MAX_TRIES=120", line)
        self.assertTrue(line.endswith(SNOFS_TAG), line)

    def test_the_vast_line_names_the_image_the_disk_the_ports_and_the_env(self) -> None:
        line = deploy.vast_create_command(self.entry, self.rows)
        self.assertIn("vastai create instance OFFER_ID", line)
        self.assertIn(f"--image {SNOFS_TAG}", line)
        self.assertIn("--disk 100", line)
        self.assertIn("-p 3000:3000", line)
        self.assertIn("-p 8188:8188", line)
        self.assertIn("-e CIVITAI_API_TOKEN=${CIVITAI_API_TOKEN}", line)
        self.assertNotIn(
            "--onstart-cmd",
            line,
            "the image's own ENTRYPOINT does the first-boot download",
        )

    def test_asking_for_the_values_puts_the_real_ones_in_the_command(self) -> None:
        line = deploy.vast_create_command(self.entry, self.rows, include_values=True)
        self.assertIn("-e HF_TOKEN=hf_supersecret_value", line)
        self.assertNotIn("${HF_TOKEN}", line)

    def test_the_salad_fields_mask_the_secrets_and_name_the_ports(self) -> None:
        fields = dict(deploy.salad_fields(self.entry, self.rows))
        self.assertEqual(fields["Image"], SNOFS_TAG)
        self.assertEqual(fields["Container gateway port"], "3000")
        self.assertEqual(fields["Comfy port (direct)"], "8188")
        self.assertEqual(fields["GPU"], "RTX 5090 32 GB")
        self.assertIn("HF_TOKEN=set (…alue)", fields["Env"])
        self.assertNotIn("hf_supersecret_value", fields["Env"])
        shown = dict(deploy.salad_fields(self.entry, self.rows, include_values=True))
        self.assertIn("HF_TOKEN=hf_supersecret_value", shown["Env"])

    def test_the_deploy_script_covers_both_hosts(self) -> None:
        text = deploy.deploy_script(self.entry, self.rows)
        for needle in ("docker build", "docker push", "docker run", "vastai create", "Salad portal fields"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertNotIn("hf_supersecret_value", text, "the shown script leaks no token")


class SettingsStore(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.path = Path(self._td.name) / "studio-images.json"
        self._old = deploy.SETTINGS_PATH
        deploy.SETTINGS_PATH = self.path
        self.addCleanup(lambda: setattr(deploy, "SETTINGS_PATH", self._old))

    def test_two_extra_rows_survive_a_reload(self) -> None:
        settings = deploy.empty_settings()
        settings, err = deploy.add_env(settings, "klein", "VAST_TCP_PORT_22", "20000")
        self.assertEqual(err, "")
        settings, err = deploy.add_env(settings, "klein", "MY_FLAG", "1")
        self.assertEqual(err, "")
        deploy.save_settings(settings)

        reloaded = deploy.load_settings()
        self.assertEqual(
            [(row[studio_meta.ENV_NAME], row[studio_meta.ENV_VALUE]) for row in deploy.extra_env(reloaded, "klein")],
            [("VAST_TCP_PORT_22", "20000"), ("MY_FLAG", "1")],
        )
        self.assertEqual(deploy.extra_env(reloaded, "snofs"), [], "filed per image")

    def test_the_same_name_twice_is_refused_and_a_bad_name_is_too(self) -> None:
        settings, _ = deploy.add_env(deploy.empty_settings(), "klein", "A_B", "1")
        again, err = deploy.add_env(settings, "klein", "A_B", "2")
        self.assertIn("already set", err)
        self.assertEqual(len(deploy.extra_env(again, "klein")), 1, "a refusal changes nothing")
        for bad in ("", "   ", "2FAST", "NOT A NAME", "no-dashes"):
            with self.subTest(bad=bad):
                _, refusal = deploy.add_env(settings, "klein", bad, "1")
                self.assertTrue(refusal, bad)

    def test_removing_a_row_and_the_last_one_empties_the_image(self) -> None:
        settings, _ = deploy.add_env(deploy.empty_settings(), "klein", "A", "1")
        settings, _ = deploy.add_env(settings, "klein", "B", "2")
        settings, removed = deploy.remove_env(settings, "klein", "A")
        self.assertTrue(removed)
        self.assertEqual([row[studio_meta.ENV_NAME] for row in deploy.extra_env(settings, "klein")], ["B"])
        settings, removed = deploy.remove_env(settings, "klein", "B")
        self.assertTrue(removed)
        self.assertEqual(deploy.extra_env(settings, "klein"), [])
        _, removed = deploy.remove_env(settings, "klein", "B")
        self.assertFalse(removed, "removing what is not there is not a change")

    def test_the_users_own_image_is_an_entry_and_removable_with_its_env(self) -> None:
        settings, err = deploy.add_image(
            deploy.empty_settings(), "my-fork", "user/eldermark-klein:test", build_arg="KLEIN_UNET_SET=snofs"
        )
        self.assertEqual(err, "")
        settings, _ = deploy.add_env(settings, "my-fork", "MY_FLAG", "1")
        doc = studio_meta.load()
        found = deploy.entry_by_ref(deploy.entries(doc, settings), "my-fork")
        self.assertIsNotNone(found)
        self.assertEqual(found["source"], deploy.SOURCE_SETTINGS)
        self.assertEqual(found["tag"], "user/eldermark-klein:test")
        self.assertEqual(found["build_arg"], "KLEIN_UNET_SET=snofs")
        self.assertIn("user/eldermark-klein:test", deploy.tag_options(doc, settings))
        self.assertEqual(len(deploy.entries(doc, settings)), 3)

        settings, removed = deploy.remove_image(settings, "my-fork")
        self.assertTrue(removed)
        self.assertEqual(len(deploy.entries(doc, settings)), 2)
        self.assertEqual(deploy.extra_env(settings, "my-fork"), [], "its env went with it")

    def test_a_nameless_image_and_a_duplicate_name_are_refused(self) -> None:
        settings = deploy.empty_settings()
        _, err = deploy.add_image(settings, "", "user/x:1")
        self.assertIn("name", err)
        _, err = deploy.add_image(settings, "x", "  ")
        self.assertIn("tag", err)
        settings, _ = deploy.add_image(settings, "x", "user/x:1")
        _, err = deploy.add_image(settings, "X", "user/x:2")
        self.assertIn("already in the list", err)

    def test_a_missing_or_broken_store_reads_as_empty(self) -> None:
        self.assertEqual(deploy.load_settings(), deploy.empty_settings())
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(deploy.load_settings(), deploy.empty_settings())
        self.path.write_text('{"images": [{"name": "x"}], "env": {"x": [{"value": "1"}]}}', encoding="utf-8")
        loaded = deploy.load_settings()
        self.assertEqual(loaded["images"], [], "a row with no tag is not an image")
        self.assertEqual(loaded["env"], {}, "a row with no name is not an env entry")

    def test_the_store_is_outside_the_repository(self) -> None:
        repo = Path(__file__).resolve().parent.parent
        self.assertFalse(
            str(self._old).lower().startswith(str(repo).lower()),
            f"the image store must not live in the repo: {self._old}",
        )


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class ImagesPage(unittest.TestCase):
    """The page, through the real window, with every path in a temp dir."""

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

    def _window(self):
        app = self.app_mod.SaladStudio(show=False)
        app.withdraw()
        self.addCleanup(self._destroy, app)
        app.update_idletasks()
        return app

    @staticmethod
    def _destroy(app) -> None:
        try:
            app.destroy()
        except tk.TclError:
            pass

    def _rows(self, app) -> list[tuple[str, ...]]:
        tree = app.image_env_tree
        return [tuple(str(v) for v in tree.item(i, "values")) for i in tree.get_children()]

    def test_the_section_is_on_the_config_page_and_shows_both_images(self) -> None:
        app = self._window()
        labels = [app.nb.tab(t, "text") for t in app.nb.tabs()]
        self.assertNotIn("Images", labels, "the images page is part of Config now")
        self.assertEqual(labels, list(self.app_mod.TAB_ORDER))
        node = app.image_env_tree.master
        while node is not None and node is not app._config:
            node = node.master
        self.assertIs(node, app._config, "the images section must live on Config")
        self.assertEqual(tuple(app.image_box["values"]), ("klein", "snofs"))
        self.assertIn("RTX 4090 24 GB", app.var_image_facts.get())
        self.assertIn("3000", app.var_image_facts.get())

    def test_the_page_shows_the_documented_environment_with_secrets_masked(self) -> None:
        from salad_studio import tokens as tok

        tok.write_token("huggingface", "hf_page_secret_value")
        app = self._window()
        rows = dict((row[0], row) for row in self._rows(app))
        self.assertEqual(
            sorted(rows), ["CIVITAI_API_TOKEN", "HF_TOKEN", "STARTUP_CHECK_MAX_TRIES"]
        )
        self.assertEqual(rows["HF_TOKEN"][1], "set (…alue)", "a secret is masked")
        self.assertEqual(rows["HF_TOKEN"][2], "token")
        self.assertEqual(rows["STARTUP_CHECK_MAX_TRIES"][1], "120")
        self.assertIn("gated", rows["HF_TOKEN"][3])

        app.var_image_include.set(True)
        app._refresh_images_page()
        shown = dict((row[0], row) for row in self._rows(app))
        self.assertEqual(shown["HF_TOKEN"][1], "hf_page_secret_value")

    def test_an_added_row_is_saved_and_survives_a_restart(self) -> None:
        app = self._window()
        app.var_image_env_name.set("VAST_TCP_PORT_22")
        app.var_image_env_value.set("20000")
        app._on_image_add_env()
        self.assertIn("added", app.var_image_status.get())
        self.assertEqual(
            deploy.load_settings()["env"]["klein"],
            [{"name": "VAST_TCP_PORT_22", "value": "20000"}],
        )
        rows = dict((row[0], row) for row in self._rows(app))
        self.assertEqual(rows["VAST_TCP_PORT_22"][1], "20000")
        self.assertEqual(rows["VAST_TCP_PORT_22"][2], "yours")
        self.assertEqual(app.var_image_env_name.get(), "", "the form is cleared")
        self._destroy(app)

        fresh = self._window()
        rows = dict((row[0], row) for row in self._rows(fresh))
        self.assertEqual(
            rows["VAST_TCP_PORT_22"][1], "20000", "the row must come back after a restart"
        )

    def test_the_page_refuses_a_duplicate_and_a_bad_name(self) -> None:
        """An override of a documented name is allowed; a second copy is not."""
        app = self._window()
        app.var_image_env_name.set("HF_TOKEN")
        app.var_image_env_value.set("override-value")
        app._on_image_add_env()
        rows = dict((row[0], row) for row in self._rows(app))
        self.assertEqual(rows["HF_TOKEN"][1], "set (…alue)", "a secret stays masked")
        self.assertEqual(rows["HF_TOKEN"][2], "yours", "the user's row wins")
        app.var_image_include.set(True)
        app._refresh_images_page()
        rows = dict((row[0], row) for row in self._rows(app))
        self.assertEqual(rows["HF_TOKEN"][1], "override-value")
        app.var_image_include.set(False)
        app._refresh_images_page()

        shown: list[str] = []
        app.var_image_env_name.set("HF_TOKEN")
        app.var_image_env_value.set("again")
        with mock.patch.object(
            self.app_mod.messagebox, "showinfo", lambda *a, **k: shown.append(str(a))
        ):
            app._on_image_add_env()
        self.assertTrue(shown and "already set" in shown[0])
        app.var_image_env_name.set("2FAST")
        with mock.patch.object(
            self.app_mod.messagebox, "showinfo", lambda *a, **k: shown.append(str(a))
        ):
            app._on_image_add_env()
        self.assertIn("not a usable", shown[-1])
        self.assertEqual(
            deploy.load_settings()["env"],
            {"klein": [{"name": "HF_TOKEN", "value": "override-value"}]},
            "the refusals changed nothing",
        )

    def test_removing_a_documented_row_says_the_document_owns_it(self) -> None:
        app = self._window()
        first = app.image_env_tree.get_children()[0]
        app.image_env_tree.selection_set(first)
        shown: list[str] = []
        with mock.patch.object(
            self.app_mod.messagebox, "showinfo", lambda *a, **k: shown.append(str(a))
        ):
            app._on_image_remove_env()
        self.assertTrue(shown and "metadata document" in shown[0])
        self.assertEqual(len(self._rows(app)), 3, "nothing was removed")

    def test_copy_puts_the_commands_on_the_clipboard_without_a_token(self) -> None:
        from salad_studio import tokens as tok

        tok.write_token("huggingface", "hf_clipboard_secret")
        app = self._window()
        app._on_image_copy()
        text = app.clipboard_get()
        for needle in ("docker build", "docker push", "docker run", "vastai create", "Salad portal fields"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertIn(KLEIN_TAG, text)
        self.assertIn("--build-arg KLEIN_UNET_SET=base,distilled", text)
        self.assertIn("-p 3000:3000", text)
        self.assertIn("HF_TOKEN=${HF_TOKEN}", text)
        self.assertNotIn("hf_clipboard_secret", text, "a copy must not carry the token")
        self.assertNotIn(
            "hf_clipboard_secret", app.log_text.get("1.0", "end"), "nor may the log"
        )
        self.assertIn("placeholders", app.var_image_status.get())

        app.var_image_include.set(True)
        app._refresh_images_page()
        app._on_image_copy()
        self.assertIn("hf_clipboard_secret", app.clipboard_get())

    def test_the_page_adds_and_removes_the_users_own_image(self) -> None:
        app = self._window()
        app.var_image_new_name.set("my-fork")
        app.var_image_new_tag.set("user/eldermark-klein:test")
        app.var_image_new_arg.set("KLEIN_UNET_SET=snofs")
        app._on_image_add_image()
        self.assertEqual(app.var_image_key.get(), "my-fork")
        self.assertEqual(
            app.image_box["values"], ("klein", "snofs", "my-fork")
        )
        self.assertIn("user/eldermark-klein:test", app.pol_image_box["values"])
        self.assertIn("user/eldermark-klein:test", app.vast_image_box["values"])
        self.assertIn(
            "docker build --build-arg KLEIN_UNET_SET=snofs -t user/eldermark-klein:test",
            app.image_script.get("1.0", "end"),
        )

        app._on_image_remove_image()
        self.assertEqual(app.image_box["values"], ("klein", "snofs"))
        self.assertNotIn("user/eldermark-klein:test", app.pol_image_box["values"])

    def test_a_documented_image_cannot_be_removed_from_the_page(self) -> None:
        app = self._window()
        app.var_image_key.set("klein")
        app._on_image_pick()
        shown: list[str] = []
        with mock.patch.object(
            self.app_mod.messagebox, "showinfo", lambda *a, **k: shown.append(str(a))
        ):
            app._on_image_remove_image()
        self.assertTrue(shown and "document owns" in shown[0])
        self.assertEqual(app.image_box["values"], ("klein", "snofs"))

    def test_the_config_page_offers_the_tags_and_still_takes_a_typed_one(self) -> None:
        app = self._window()
        self.assertEqual(tuple(app.pol_image_box["values"]), (KLEIN_TAG, SNOFS_TAG))
        app.var_pol_image.set(SNOFS_TAG)
        self.assertEqual(app._policy_from_form()["image"], SNOFS_TAG)
        app.var_pol_image.set("hand/typed:tag")
        self.assertEqual(
            app._policy_from_form()["image"],
            "hand/typed:tag",
            "a tag the app was never told about must still be usable",
        )

    def test_a_vast_instance_row_records_which_image_it_runs(self) -> None:
        app = self._window()
        app.var_vast_new.set("203.0.113.9:31234")
        app.var_vast_image.set(SNOFS_TAG)
        app._on_vast_add()
        row = app.vast_tree.item(app.vast_tree.get_children()[0], "values")
        self.assertEqual(row[3], SNOFS_TAG, "the row shows the image it runs")
        self.assertEqual(deploy.entry_by_ref(deploy.entries(studio_meta.load(), None), SNOFS_TAG)["key"], "snofs")
        from salad_studio import vast as vast_mod

        self.assertEqual(vast_mod.load_doc()["instances"][0]["image"], SNOFS_TAG)

        # A fetched instance arrives with no image; the page can set one.
        app.var_vast_new.set("198.51.100.7:40111")
        app.var_vast_image.set("")
        app._on_vast_add()
        second = app.vast_tree.get_children()[1]
        app.vast_tree.selection_set(second)
        app.var_vast_image.set(KLEIN_TAG)
        app._on_vast_set_image()
        rows = [row for row in vast_mod.load_doc()["instances"]]
        self.assertEqual(rows[1]["image"], KLEIN_TAG)
        self.assertEqual(rows[0]["image"], SNOFS_TAG, "the other row is untouched")


if __name__ == "__main__":
    unittest.main()
