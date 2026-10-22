"""The Import tab converts Civitai image 125073040 through the shipped path.

The Civitai fetch is served from the recorded fixture, so this drives the real
Fetch and Convert handlers with no network call.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "salad_studio"
for _p in (PKG, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio import comfy_import  # noqa: E402
from tests._paths import _TempPaths  # noqa: E402

FIXTURE = HERE / "civitai_fixtures" / "image_125073040.json"
FIXTURES = HERE / "civitai_fixtures"


def _redirect_convert_off_the_network(case: unittest.TestCase) -> None:
    """Serve the fixture from the lora_store Convert actually calls.

    ``comfy_import`` binds top-level ``lora_store`` as ``ls``. That object is
    not ``salad_studio.lora_store``, so a patch on the package copy never
    lands. ``ls.EXTRAS_PATH`` is also the user's file unless it moves: Convert
    writes each resolved LoRA there.
    """
    ls = comfy_import.ls
    search = mock.patch.object(ls, "civitai_search_lora", return_value=None)
    search.start()
    case.addCleanup(search.stop)
    fetch = mock.patch.object(
        ls, "fetch_civitai_image", return_value=case.fixture["image"]
    )
    fetch.start()
    case.addCleanup(fetch.stop)
    saved = ls.EXTRAS_PATH
    ls.EXTRAS_PATH = case.tmp / "studio-loras.json"
    case.addCleanup(setattr, ls, "EXTRAS_PATH", saved)


class ImportFetchConvertOnTheServer(unittest.TestCase):
    """The same Civitai import, driven through the action table."""

    def setUp(self) -> None:
        from tests._studio import Studio

        self.s = Studio()
        self.addCleanup(self.s.stop)
        self.tmp = Path(self.s.tmp.name)
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        _redirect_convert_off_the_network(self)

    def _settle(self, call):
        """Run a background action and wait for the reply it publishes."""
        sub = self.s.shell.hub.subscribe()
        self.addCleanup(self.s.shell.hub.unsubscribe, sub)
        call()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                item = sub.take(timeout=0.1)
            except Exception:
                break
            if item and item[0] == "action_done":
                return item[1]["reply"]
        self.fail("the background action never answered")

    def test_the_import_produces_a_runnable_klein_request(self) -> None:
        controller = self.s.shell.controllers.get("import")
        pastes = {
            "workflow": json.dumps(self.fixture.get("workflow") or {}),
            "metadata": self.fixture.get("metadata") or "",
            "tool": self.fixture.get("tool") or "",
        }
        with mock.patch.object(comfy_import, "fetch_civitai_image_pastes", return_value=pastes):
            reply = self._settle(lambda: controller.fetch_civitai(
                {"url": self.fixture["source"]}, ctx=_ctx(self.s)))
        self.assertTrue(reply["ok"])

        reply = self._settle(lambda: controller.convert({}, ctx=_ctx(self.s)))
        self.assertTrue(reply["ok"])
        editor = self.s.state("editor")
        self.assertIn("CLIPTextEncode", editor["json"])
        self.assertEqual(editor["errors"], [], "the converted request must validate")


def _ctx(s) -> object:
    from salad_studio.web.registry import ActionContext

    return ActionContext(studio=s.shell, page="import", action="", args={})


if __name__ == "__main__":
    unittest.main()
