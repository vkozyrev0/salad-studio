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

import image_deploy as deploy  # noqa: E402  the module the page reads through
from salad_studio import studio_meta  # noqa: E402
from tests._paths import _TempPaths  # noqa: E402

KLEIN_TAG = "docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein"
SNOFS_TAG = "docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-snofs"


class UserImagesAreStored(unittest.TestCase):
    """The user's own images and their extra environment, as the Config page stores them."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        self._saved = (deploy.SETTINGS_PATH, deploy.load_settings())
        self.addCleanup(lambda: (setattr(deploy, "SETTINGS_PATH", self._saved[0]),
                                 deploy.save_settings(self._saved[1])))

    @staticmethod
    def _entry(entry_name: str) -> dict:
        settings = deploy.load_settings()
        return deploy.entry_by_ref(deploy.entries(studio_meta.load(), settings), entry_name) or {}

    @staticmethod
    def _rows(entry_name: str, *, include: bool = False) -> dict[str, dict[str, str]]:
        from salad_studio import tokens as tok

        settings = deploy.load_settings()
        entry = UserImagesAreStored._entry(entry_name)
        token_map = {slot: tok.read_token(slot) for slot, _label, _rel in tok.TOKEN_SPECS
                     if slot in ('huggingface', 'civitai')}
        rows = deploy.env_rows(entry, deploy.extra_env(settings, entry["key"]), token_map)
        return {row["name"]: row for row in rows}

    @staticmethod
    def _shown(name: str, *, include: bool = False) -> str:
        return deploy.shown_value(UserImagesAreStored._rows("klein")[name], include_values=include)

    def test_an_added_row_is_saved_and_survives_a_restart(self) -> None:
        settings, refusal = deploy.add_env(deploy.load_settings(), self._entry("klein")["key"],
                                           "VAST_TCP_PORT_22", "20000")
        self.assertEqual(refusal, "")
        deploy.save_settings(settings)
        self.assertEqual(
            deploy.load_settings()["env"]["klein"],
            [{"name": "VAST_TCP_PORT_22", "value": "20000"}],
        )
        rows = self._rows("klein")
        self.assertEqual(self._shown("VAST_TCP_PORT_22"), "20000")
        self.assertEqual(rows["VAST_TCP_PORT_22"]["source"], "yours")

    def test_a_documented_name_overridden_once_and_not_twice(self) -> None:
        """An override of a documented name is allowed; a second copy is not."""
        settings = deploy.load_settings()
        key = self._entry("klein")["key"]
        settings, refusal = deploy.add_env(settings, key, "HF_TOKEN", "override-value")
        deploy.save_settings(settings)
        self.assertEqual(refusal, "")
        self.assertEqual(self._shown("HF_TOKEN"), "set (…alue)", "a secret stays masked")
        self.assertEqual(self._shown("HF_TOKEN", include=True), "override-value")
        self.assertEqual(self._rows("klein")["HF_TOKEN"]["source"], "yours", "the user's row wins")

        again, refusal = deploy.add_env(settings, key, "HF_TOKEN", "again")
        self.assertIn("already set", refusal)
        bad, refusal = deploy.add_env(settings, key, "2FAST", "1")
        self.assertIn("not a usable", refusal)
        self.assertEqual(
            settings["env"],
            {"klein": [{"name": "HF_TOKEN", "value": "override-value"}]},
            "a refusal changes nothing",
        )

    def test_removing_a_documented_row_says_the_document_owns_it(self) -> None:
        settings = deploy.load_settings()
        key = self._entry("klein")["key"]
        after, removed = deploy.remove_env(settings, key, "HF_TOKEN")
        self.assertFalse(removed)
        self.assertEqual(after, settings, "nothing was removed")
        self.assertEqual(len(self._rows("klein")), 3)

    def test_an_image_added_with_its_ports_publishes_them(self) -> None:
        """C1+U1: the two fields are what makes a user image's commands publish a port."""
        settings = deploy.load_settings()
        settings, refusal = deploy.add_image(
            settings, "my-fork", "user/eldermark-klein:test",
            build_arg="KLEIN_UNET_SET=snofs",
            ports={studio_meta.PORT_API: 3000, studio_meta.PORT_COMFY: 8188},
        )
        self.assertEqual(refusal, "")
        deploy.save_settings(settings)
        self.assertEqual(
            deploy.load_settings()["images"][0]["ports"],
            {studio_meta.PORT_API: 3000, studio_meta.PORT_COMFY: 8188},
        )
        entries = deploy.entries(studio_meta.load(), deploy.load_settings())
        self.assertEqual([entry["key"] for entry in entries], ["klein", "snofs", "my-fork"],
                         "the user's image is listed after the document's")
        self.assertIn("user/eldermark-klein:test", deploy.tag_options(studio_meta.load(), deploy.load_settings()))
        entry = deploy.entry_by_ref(entries, "my-fork")
        assert entry is not None
        script = deploy.deploy_script(entry, [], include_values=False)
        self.assertIn("docker build --build-arg KLEIN_UNET_SET=snofs -t user/eldermark-klein:test", script)
        self.assertIn("-p 3000:3000", script, "the docker run line must publish the port")
        self.assertIn("-p 8188:8188", script)
        self.assertEqual(deploy.port_args(entry), ["-p 3000:3000", "-p 8188:8188"])
        self.assertIn("-p 3000:3000", deploy.vast_create_command(entry, []))

    def test_an_image_added_with_no_ports_publishes_none(self) -> None:
        settings, refusal = deploy.add_image(deploy.load_settings(), "plain", "user/x:2")
        self.assertEqual(refusal, "")
        self.assertEqual(settings["images"][0]["ports"], {})
        entry = deploy.entry_by_ref(deploy.entries(studio_meta.load(), settings), "plain")
        assert entry is not None
        self.assertNotIn("-p ", deploy.deploy_script(entry, []).split("# vast.ai")[0])

    def test_an_image_added_then_removed_leaves_the_documents_two(self) -> None:
        settings, _ = deploy.add_image(deploy.load_settings(), "my-fork", "user/eldermark-klein:test")
        deploy.save_settings(settings)
        settings, removed = deploy.remove_image(deploy.load_settings(), "my-fork")
        self.assertTrue(removed)
        deploy.save_settings(settings)
        self.assertEqual([entry["key"] for entry in deploy.entries(studio_meta.load(), deploy.load_settings())],
                         ["klein", "snofs"])
        self.assertNotIn("user/eldermark-klein:test", deploy.tag_options(studio_meta.load(), deploy.load_settings()))


if __name__ == "__main__":
    unittest.main()
