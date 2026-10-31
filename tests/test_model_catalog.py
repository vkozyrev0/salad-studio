"""model_catalog's pure decisions: the refs it accepts, and what it fetches alone.

The module's fetch paths talk to Civitai and to the local cache on disk, so these
drive the decisions that decide what those paths do — which refs name a model and
a version, which catalog rows the tool is willing to download without being
asked, and how a row is added to the index. (T5: the largest script in the repo
had no test.)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for _p in (TOOLS / "salad_studio", TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import model_catalog as mc  # noqa: E402


class Refs(unittest.TestCase):
    def test_the_short_form_names_a_model_and_a_version(self) -> None:
        self.assertEqual(mc.parse_ref("702491@866836"), (702491, 866836))
        self.assertEqual(mc.parse_ref("  702491@866836  "), (702491, 866836))

    def test_a_model_with_no_version_has_none(self) -> None:
        self.assertEqual(mc.parse_ref("702491"), (702491, None))

    def test_a_civitai_url_carries_the_model_and_its_query_version(self) -> None:
        self.assertEqual(
            mc.parse_ref("https://civitai.com/models/957327?modelVersionId=2725918"),
            (957327, 2725918),
        )
        self.assertEqual(
            mc.parse_ref("https://civitai.com/models/957327"), (957327, None)
        )

    def test_an_unrecognized_ref_is_refused_with_the_forms_it_wants(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            mc.parse_ref("not a ref at all")
        self.assertIn("702491@866836", str(caught.exception))


class WhatItDownloadsByItself(unittest.TestCase):
    """The gate that decides whether a catalog row is mirrored onto this machine."""

    def _item(self, **kwargs) -> dict:
        item = {
            "id": "civitai:1@2",
            "kind": "checkpoint",
            "source": {"host": "civitai", "size_bytes": 1024},
        }
        item.update(kwargs)
        return item

    def test_a_small_civitai_checkpoint_is_fetched(self) -> None:
        self.assertTrue(mc.should_autodownload(self._item(), False))

    def test_a_lora_is_never_fetched_without_force(self) -> None:
        """A LoRA is loaded from its URL when the graph runs, so nothing is mirrored."""
        self.assertFalse(mc.should_autodownload(self._item(kind="lora"), False))
        self.assertTrue(mc.should_autodownload(self._item(kind="lora"), True))

    def test_a_row_marked_do_not_redownload_is_left_alone(self) -> None:
        self.assertFalse(
            mc.should_autodownload(self._item(do_not_redownload=True), False)
        )

    def test_a_source_that_is_not_civitai_is_left_alone(self) -> None:
        self.assertFalse(
            mc.should_autodownload(
                self._item(source={"host": "huggingface", "size_bytes": 1024}), False
            )
        )

    def test_the_size_limit_is_inclusive(self) -> None:
        at_limit = {"host": "civitai", "size_bytes": mc.AUTO_MAX_BYTES}
        over = {"host": "civitai", "size_bytes": mc.AUTO_MAX_BYTES + 1}
        self.assertTrue(mc.should_autodownload(self._item(source=at_limit), False))
        self.assertFalse(mc.should_autodownload(self._item(source=over), False))

    def test_a_row_with_no_known_size_is_left_alone(self) -> None:
        self.assertFalse(
            mc.should_autodownload(self._item(source={"host": "civitai"}), False)
        )

    def test_force_overrides_every_refusal(self) -> None:
        for item in (
            self._item(kind="lora"),
            self._item(do_not_redownload=True),
            self._item(source={"host": "huggingface"}),
            self._item(source={"host": "civitai"}),
        ):
            with self.subTest(item=item):
                self.assertTrue(mc.should_autodownload(item, True))


class IndexRows(unittest.TestCase):
    def test_upsert_adds_then_updates_the_row_it_named(self) -> None:
        data = mc.empty_index()
        first = mc.upsert(data, {"id": "a", "name": "one", "kind": "checkpoint"})
        self.assertEqual(mc.find_item(data, "a"), first)
        again = mc.upsert(data, {"id": "a", "name": "renamed"})
        self.assertEqual(len(data["items"]), 1, "one id names one row")
        self.assertEqual(again["name"], "renamed")
        self.assertEqual(again["kind"], "checkpoint", "a field the update omits stays")
        self.assertIsNone(mc.find_item(data, "b"))

    def test_the_primary_file_is_the_one_the_version_marks(self) -> None:
        version = {
            "files": [
                {"name": "other.safetensors"},
                {"name": "main.safetensors", "primary": True},
            ]
        }
        self.assertEqual(mc.primary_file(version)["name"], "main.safetensors")

    def test_the_primary_file_falls_back_to_the_first_one(self) -> None:
        version = {"files": [{"name": "only.safetensors"}]}
        self.assertEqual(mc.primary_file(version)["name"], "only.safetensors")


class TheFetchExitCode(unittest.TestCase):
    """C2: `fetch` must not report success for a file that fails its sha256."""

    # An id the seed does not own: cmd_fetch seeds the KNOWN rows first, and one
    # of those would replace this row's source (and with it the local filename).
    REF = "civitai:999999@888888"

    def _index_with(self, root: Path, *, sha_matches: bool) -> str:
        """An index holding one Civitai checkpoint whose local file is present."""
        self.assertNotIn(
            self.REF, {row["id"] for row in mc.KNOWN}, "the seed would overwrite this row"
        )
        data = mc.empty_index()
        item = {
            "id": self.REF,
            "name": "probe checkpoint",
            "kind": "checkpoint",
            "source": {
                "host": "civitai",
                "filename": "probe.safetensors",
                "size_bytes": 1024,
            },
        }
        rel = mc.local_relpath(item)
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"the bytes on disk")
        item["source"]["sha256"] = (
            mc.sha256_file(dest) if sha_matches else "00" * 32
        )
        item["local_file"] = rel
        data["items"].append(item)
        mc.save_index(data)
        return self.REF.split(":", 1)[1]

    def _fetch(self, ref: str) -> int:
        args = argparse.Namespace(ref=ref, kind="checkpoint", use="", status="", force=False)
        # The item is in the index, so the command needs no network: civitai_version
        # is what it would call for an unknown ref.
        with mock.patch.object(
            mc, "civitai_version", side_effect=AssertionError("no network in this test")
        ):
            return mc.cmd_fetch(args)

    def test_a_corrupt_cached_file_exits_non_zero(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.dict(os.environ, {"ELDERMARK_MODEL_CACHE": str(root)}):
                ref = self._index_with(root, sha_matches=False)
                self.assertEqual(
                    self._fetch(ref), 2, "a hash failure must not exit 0"
                )

    def test_a_good_cached_file_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.dict(os.environ, {"ELDERMARK_MODEL_CACHE": str(root)}):
                ref = self._index_with(root, sha_matches=True)
                self.assertEqual(self._fetch(ref), 0)


class TheVersionGuard(unittest.TestCase):
    """C4: the guard compares the payload's own modelId, so it can fire."""

    def _payload(self, **fields) -> bytes:
        return json.dumps(fields).encode()

    def test_a_version_of_another_model_is_refused(self) -> None:
        payload = self._payload(id=2786085, modelId=2416142)
        with mock.patch.object(mc, "_http_get", return_value=(200, payload, "")):
            with self.assertRaises(SystemExit) as caught:
                mc.civitai_version(999, 2786085, "k")
        self.assertIn("belongs to model 2416142", str(caught.exception))

    def test_the_same_payload_is_accepted_for_its_own_model(self) -> None:
        payload = self._payload(id=2786085, modelId=2416142)
        with mock.patch.object(mc, "_http_get", return_value=(200, payload, "")):
            self.assertEqual(mc.civitai_version(2416142, 2786085, "k")["id"], 2786085)

    def test_a_payload_with_no_model_id_is_accepted(self) -> None:
        payload = self._payload(id=2786085)
        with mock.patch.object(mc, "_http_get", return_value=(200, payload, "")):
            self.assertEqual(mc.civitai_version(999, 2786085, "k")["id"], 2786085)


class TokensStayOffTheUserStore(unittest.TestCase):
    """``cmd_fetch`` reads the Civitai key, and reading seeds the token store.

    Every module reads ``salad_studio.tokens``. Whoever loads the package first
    decides which object that is, and a test module that ran before ``tests``
    could leave it a second copy on the operator's real ``studio-tokens.json``.
    Seeding through that copy wrote the real file, and the suite never noticed
    because it only ever moved the copy it knew about.
    """

    def test_fetching_a_model_never_writes_the_real_token_store(self) -> None:
        from salad_studio import tokens
        from tests._paths import _TempPaths

        # The path the store ships with, not whichever copy a module holds now.
        from run_salad_studio import PACKAGE

        real = PACKAGE / "studio-tokens.json"
        before = real.read_bytes() if real.is_file() else None
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        paths = _TempPaths(Path(td.name))
        # Seeding runs inside the first key read, so this is where the write lands.
        with paths, mock.patch.object(mc, "civitai_version", side_effect=SystemExit("no network here")):
            with mock.patch.dict(os.environ, {"ELDERMARK_MODEL_CACHE": td.name}):
                with self.assertRaises(SystemExit):
                    mc.cmd_fetch(argparse.Namespace(ref="civitai:999999@888888", kind="checkpoint",
                                                    use="", status="", force=False))
        after = real.read_bytes() if real.is_file() else None
        self.assertEqual(after, before, "fetching a model wrote the real token store")


if __name__ == "__main__":
    unittest.main()
