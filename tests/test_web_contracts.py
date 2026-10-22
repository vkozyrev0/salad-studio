"""The page's actions and the server's table, checked at the seam.

The page tests drive a controller directly, so they pass even when the page
posts a name or a payload the table does not accept. These tests drive the
engine with what the page sends.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import profiles  # noqa: E402
import prompt_history  # noqa: E402
import salad_queue  # noqa: E402
import tokens  # noqa: E402
import vast  # noqa: E402
from PIL import Image  # noqa: E402
from salad_studio.web import controllers  # noqa: E402
from tests._studio import studio  # noqa: E402


class PageActionContractTest(unittest.TestCase):
    def test_settings_edits_use_the_registered_action(self) -> None:
        with studio() as made:
            status, reply = made.act("settings", "set_knobs", {"steps": "8"})
            self.assertEqual(status, 200)
            self.assertTrue(reply["ok"], reply.get("error"))
            self.assertEqual(made.state("settings")["knobs"]["steps"], "8")

            status, reply = made.act("settings", "set_form", {"steps": "9"})
            self.assertEqual(status, 200)
            self.assertFalse(reply["ok"])
            self.assertEqual(reply["error"], "no action named settings.set_form")

    def test_a_history_row_click_selects_it_for_rate_and_reuse(self) -> None:
        with studio() as made:
            prompt_history.add_request(
                {"prompt": {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "a plate"}}}},
                profile="klein", gateway="")
            row = made.state("history")["rows"][0]
            _status, selected = made.act("history", "select", {"id": row["id"]})
            self.assertTrue(selected["ok"])
            _status, rated = made.act("history", "rate", {"id": row["id"], "stars": 4})
            self.assertTrue(rated["ok"])
            self.assertEqual(prompt_history.list_prompts()[0].get("rating"), 4)

    def test_a_queue_row_click_selects_it_for_cancel(self) -> None:
        with studio() as made:
            job = made.studio.services.gen_queue.enqueue(
                {"profile": "klein"}, lambda _job: salad_queue.Attempt(), line="klein")
            _status, selected = made.act("queue", "select", {"key": str(job.id)})
            self.assertTrue(selected["ok"])
            _status, cancelled = made.act("queue", "cancel", {})
            self.assertTrue(cancelled["ok"])
            self.assertEqual(job.state, salad_queue.CANCELLED)

    def test_a_vast_instance_row_selects_by_index(self) -> None:
        with studio() as made:
            doc, refusal = vast.add_instance(vast.empty_doc(), "203.0.113.9:31234")
            self.assertEqual(refusal, "")
            vast.save_doc(doc)
            made.act("config", "section", {"section": "vast"})
            rows = made.state("config")["vast"]["instances"]
            self.assertTrue(rows)
            _status, selected = made.act("config", "select_vast", {"index": 0})
            self.assertTrue(selected["ok"])

    def test_the_editor_swaps_the_ids_the_page_sends(self) -> None:
        from tests.test_web_pages_editor import klein

        body = klein()
        prompt = body["prompt"]
        ids = [nid for nid, node in prompt.items()
               if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode"][:2]
        self.assertEqual(len(ids), 2, "the fixture carries two text encoders")
        before = {nid: prompt[nid]["inputs"]["text"] for nid in ids}
        with studio() as made:
            base = made.state("editor")["rev"]
            made.act("editor", "set_json", {"text": json.dumps(body), "base": base})
            _status, reply = made.act("editor", "swap_selected", {"ids": ids})
            self.assertTrue(reply["ok"], reply.get("error"))
            swapped = json.loads(made.state("editor")["json"])["prompt"]
            self.assertEqual(swapped[ids[0]]["inputs"]["text"], before[ids[1]])
            self.assertEqual(swapped[ids[1]]["inputs"]["text"], before[ids[0]])

    def test_a_normal_import_paste_stays_in_the_box(self) -> None:
        text = '{"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "x"}}}'
        with studio() as made:
            _status, _reply = made.act("import", "set_paste", {"workflow": text})
            self.assertEqual(made.state("import")["workflow"], text)
            _status, _reply = made.act("import", "set_paste", {"workflow": ""})
            self.assertEqual(made.state("import")["workflow"], "")

    def test_a_token_page_reads_each_slot_once(self) -> None:
        calls: list[str] = []
        real = tokens.read_token

        def counted(kind: str) -> str:
            calls.append(kind)
            return real(kind)

        with studio() as made:
            with mock.patch.object(tokens, "read_token", side_effect=counted):
                made.state("tokens")
        self.assertEqual(len(calls), 5, calls)


class RenderPathTest(unittest.TestCase):
    def test_a_gateway_path_or_scheme_still_matches_its_host(self) -> None:
        self.assertTrue(profiles.same_gateway("http://203.0.113.9:31234/prompt",
                                              "http://203.0.113.9:31234"))
        self.assertTrue(profiles.same_gateway("https://203.0.113.9:31234",
                                              "http://203.0.113.9:31234"))
        self.assertFalse(profiles.same_gateway("", ""))

    def test_a_trailing_slash_still_refuses_a_vast_endpoint(self) -> None:
        with studio() as made:
            doc, _refusal = vast.add_instance(vast.empty_doc(), "203.0.113.9:31234")
            vast.save_doc(doc)
            profile = profiles.SaladProfile(
                name="klein", gateway="http://203.0.113.9:31234/", mode="salad")
            reason = controllers.ShellController(made.studio)._dispatch_refusal({"prompt": {}}, profile)
            self.assertIn("vast.ai instance URL", reason)

    def test_a_plate_attaches_to_the_row_its_render_created(self) -> None:
        with studio() as made:
            with mock.patch.object(prompt_history.time, "time", side_effect=[1000, 1001]):
                older = prompt_history.add_request(
                    {"prompt": {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "older"}}}})
                newer = prompt_history.add_request(
                    {"prompt": {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "newer"}}}})
            self.assertNotEqual(older["ts"], newer["ts"])
            with tempfile.TemporaryDirectory() as tmp:
                plate = Path(tmp) / "plate.png"
                Image.new("RGB", (4, 4), (10, 20, 30)).save(plate)
                prompt_history.attach_image(plate, key=older["key"])
            rows = {row["key"]: row for row in prompt_history.list_prompts()}
            self.assertTrue(rows[older["key"]].get("image"))
            self.assertFalse(rows[newer["key"]].get("image"))

    def test_assist_finds_the_latest_plate_in_the_output_folder(self) -> None:
        with studio() as made:
            out = Path(made.studio.services.out_dir)
            out.mkdir(parents=True, exist_ok=True)
            plate = out / "studio_assist.png"
            plate.write_bytes(b"\x89PNG\r\n\x1a\n")
            made.studio.refresh_plates()
            assist = made.studio.controllers.get("assist")
            self.assertEqual(assist._latest_image(), plate)

    def test_a_png_plate_is_listed(self) -> None:
        with studio() as made:
            out = Path(made.studio.services.out_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "studio_test.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            self.assertIn("studio_test.png", [p.name for p in made.studio.services.plates()])


if __name__ == "__main__":
    unittest.main()
