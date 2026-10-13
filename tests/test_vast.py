"""Vast.ai picture generation: the control call, the instance store, the render.

The key is never in a source literal, so the tests that need one write it into a
temp token store. Every HTTP path is driven through the injected sender, which
is the same seam ``salad_status`` uses: the test records the real request object
the shipped code built and answers it, instead of reaching the network.
"""
from __future__ import annotations

import base64
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

from salad_studio import generator, tokens as tok, vast  # noqa: E402
from tests.test_launch import _Inline, _TempPaths  # noqa: E402

try:
    import tkinter as tk
except ImportError as _tk_err:
    tk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = _tk_err
else:
    _TK_IMPORT_ERROR = None

# A 2x2 JPEG: what a real Comfy answer carries as base64 in ``images[]``.
PLATE = base64.b64encode(
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xc0\x00\x0b\x08\x00\x02\x00\x02\x01\x01\x11\x00"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x7f?\xff\xd9"
).decode("ascii")

# A 1x1 PNG: what a plain ComfyUI's SaveImage writes, and what ``/view`` serves.
PNG_PLATE = base64.b64encode(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
    b"\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0"
    b"\x1f\x00\x05\x00\x01\xff\xab\xce6\x89\x00\x00\x00\x00IEND\xaeB`\x82"
).decode("ascii")

# What a plain ComfyUI answers /history with: the plate lives in the container.
HISTORY_FILE_BODY = {
    "abc-123": {
        "outputs": {
            "9": {
                "images": [
                    {"filename": "x_00001_.png", "subfolder": "", "type": "output"}
                ]
            }
        }
    }
}

# What the vast.ai instances endpoint answers for an account with two machines.
INSTANCES_BODY = {
    "instances": [
        {
            "id": 111,
            "label": "klein-4090",
            "gpu_name": "RTX 4090",
            "actual_status": "running",
            "public_ipaddr": "203.0.113.9",
            "ports": {"8188/tcp": [{"HostIp": "0.0.0.0", "HostPort": 31234}]},
        },
        {
            "id": 222,
            "label": "snofs-5090",
            "gpu_name": "RTX 5090",
            "actual_status": "running",
            "public_ipaddr": "198.51.100.7",
            "ports": {"8188/tcp": [{"HostIp": "0.0.0.0", "HostPort": 40111}]},
        },
        {
            # Stopped: no port mapping, so there is no endpoint to render on.
            "id": 333,
            "label": "stopped-one",
            "gpu_name": "RTX 3090",
            "actual_status": "exited",
            "public_ipaddr": "192.0.2.5",
            "ports": {},
        },
    ]
}


class _Recorder:
    """A transport that records the real request and answers a canned response."""

    def __init__(self, status: int = 200, body: bytes = b"{}") -> None:
        self.status = status
        self.body = body
        self.requests: list = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        return self.status, self.body


def _header(request, name: str) -> str | None:
    for key, value in request.headers.items():
        if key.lower() == name.lower():
            return str(value)
    return None


class EndpointDerivation(unittest.TestCase):
    def test_the_comfy_port_mapping_becomes_the_endpoint(self) -> None:
        instance = INSTANCES_BODY["instances"][0]
        self.assertEqual(vast.instance_endpoint(instance), "http://203.0.113.9:31234")

    def test_a_range_key_and_a_bare_port_value_are_read_too(self) -> None:
        ranged = {"public_ipaddr": "10.0.0.1", "ports": {"8188-8190/tcp": [{"HostPort": 3000}]}}
        bare = {"public_ipaddr": "10.0.0.2", "ports": {"8188/tcp": 3100}}
        self.assertEqual(vast.instance_endpoint(ranged), "http://10.0.0.1:3000")
        self.assertEqual(vast.instance_endpoint(bare), "http://10.0.0.2:3100")

    def test_the_other_comfy_ports_a_template_may_publish_are_used(self) -> None:
        """The vast.ai ComfyUI template serves 8188; some images use 18188 or 3000."""
        for port in vast.COMFY_PORTS:
            with self.subTest(port=port):
                instance = {
                    "public_ipaddr": "10.0.0.5",
                    "ports": {f"{port}/tcp": [{"HostPort": 40000 + port}]},
                }
                self.assertEqual(
                    vast.instance_endpoint(instance), f"http://10.0.0.5:{40000 + port}"
                )

    def test_8188_wins_when_the_template_maps_several_ports(self) -> None:
        instance = {
            "public_ipaddr": "10.0.0.6",
            "ports": {
                "22/tcp": [{"HostPort": 22022}],
                "8188/tcp": [{"HostPort": 31234}],
                "8888/tcp": [{"HostPort": 38888}],
            },
        }
        self.assertEqual(vast.instance_endpoint(instance), "http://10.0.0.6:31234")

    def test_one_other_non_ssh_port_is_used_when_no_comfy_port_is_mapped(self) -> None:
        """A template that publishes ComfyUI elsewhere is still usable."""
        instance = {
            "public_ipaddr": "10.0.0.7",
            "ports": {"22/tcp": [{"HostPort": 22022}], "5000/tcp": [{"HostPort": 35000}]},
        }
        self.assertEqual(vast.instance_endpoint(instance), "http://10.0.0.7:35000")

    def test_an_instance_with_no_comfy_mapping_has_no_endpoint(self) -> None:
        stopped = INSTANCES_BODY["instances"][2]
        self.assertEqual(vast.instance_endpoint(stopped), "")
        other_port = {"public_ipaddr": "10.0.0.3", "ports": {"22/tcp": [{"HostPort": 22}]}}
        self.assertEqual(vast.instance_endpoint(other_port), "", "ssh is never Comfy")
        ambiguous = {
            "public_ipaddr": "10.0.0.8",
            "ports": {"8888/tcp": [{"HostPort": 38888}], "5000/tcp": [{"HostPort": 35000}]},
        }
        self.assertEqual(
            vast.instance_endpoint(ambiguous), "", "two candidates is a guess, so it says so"
        )
        self.assertEqual(vast.instance_endpoint({"public_ipaddr": "10.0.0.4"}), "")
        self.assertEqual(vast.instance_endpoint({}), "")

    def test_a_typed_address_is_normalized_to_one_spelling(self) -> None:
        for typed in (
            "1.2.3.4:31234",
            "http://1.2.3.4:31234",
            "http://1.2.3.4:31234/",
            "  http://1.2.3.4:31234/prompt  ",
        ):
            with self.subTest(typed=typed):
                self.assertEqual(vast.normalize_endpoint(typed), "http://1.2.3.4:31234")
        self.assertEqual(vast.normalize_endpoint("https://host.example"), "https://host.example")
        for junk in ("", "   ", "http://", "/"):
            with self.subTest(junk=junk):
                self.assertEqual(vast.normalize_endpoint(junk), "")

    def test_the_prompt_url_is_the_instance_plus_prompt(self) -> None:
        self.assertEqual(vast.prompt_url("1.2.3.4:31234"), "http://1.2.3.4:31234/prompt")

    def test_the_view_url_carries_the_records_own_fields(self) -> None:
        url = vast.view_url(
            "1.2.3.4:31234",
            {"filename": "my plate_00001_.png", "subfolder": "sub dir", "type": "output"},
        )
        self.assertEqual(
            url,
            "http://1.2.3.4:31234/view?filename=my+plate_00001_.png"
            "&subfolder=sub+dir&type=output",
        )
        self.assertEqual(
            vast.view_url("1.2.3.4:31234", {"filename": "x.png"}),
            "http://1.2.3.4:31234/view?filename=x.png&subfolder=&type=output",
            "a record with no subfolder still names one",
        )


class ListInstances(unittest.TestCase):
    def test_the_instances_url_is_the_v1_endpoint(self) -> None:
        """v0 answers 410 deprecated_endpoint (measured live 2026-10-13)."""
        self.assertEqual(vast.INSTANCES_URL, "https://console.vast.ai/api/v1/instances/")

    def test_the_key_check_is_the_instances_call_with_a_bearer_token(self) -> None:
        request = tok.probe_request("vast", "vast-key-123")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, vast.INSTANCES_URL)
        self.assertEqual(_header(request, "Authorization"), "Bearer vast-key-123")

    def test_the_token_probe_spec_is_the_url_the_vast_client_uses(self) -> None:
        self.assertEqual(tok.PROBE_SPECS["vast"][0], vast.INSTANCES_URL)
        self.assertIn("vast", [kind for kind, _l, _r in tok.TOKEN_SPECS])

    def test_a_second_page_is_followed_so_a_bigger_account_is_not_truncated(self) -> None:
        first = {"instances": INSTANCES_BODY["instances"][:1], "next_token": "page-2"}
        second = {"instances": INSTANCES_BODY["instances"][1:2], "next_token": None}
        pages = [json.dumps(first).encode(), json.dumps(second).encode()]
        requests: list = []

        def transport(request, timeout):
            requests.append(request)
            return 200, pages.pop(0)

        result = vast.fetch_instances("vast-key-123", sender=transport)
        self.assertEqual(result["status"], 200)
        self.assertEqual(len(requests), 2, "the next page was asked for")
        self.assertIn("after_token=page-2", requests[1].full_url)
        self.assertEqual(
            [row["endpoint"] for row in result["instances"]],
            ["http://203.0.113.9:31234", "http://198.51.100.7:40111"],
        )

    def test_the_listing_carries_the_key_and_parses_the_instances(self) -> None:
        send = _Recorder(200, json.dumps(INSTANCES_BODY).encode())
        result = vast.fetch_instances("vast-key-123", sender=send)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["error"], "")
        self.assertEqual(len(send.requests), 1)
        request = send.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, vast.INSTANCES_URL)
        self.assertEqual(_header(request, "Authorization"), "Bearer vast-key-123")
        # The stopped instance maps no port, so only the two usable ones come back.
        self.assertEqual(
            [row["endpoint"] for row in result["instances"]],
            ["http://203.0.113.9:31234", "http://198.51.100.7:40111"],
        )
        self.assertEqual(result["instances"][0]["label"], "klein-4090")
        self.assertEqual(result["instances"][0]["gpu"], "RTX 4090")
        self.assertEqual(result["instances"][0]["state"], "running")
        self.assertEqual(result["instances"][0]["id"], 111)

    def test_a_rejected_key_is_reported_as_rejected(self) -> None:
        for status in (401, 403):
            with self.subTest(status=status):
                send = _Recorder(status, b'{"error": "invalid api key"}')
                result = vast.fetch_instances("bad-key", sender=send)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["instances"], [])
                self.assertIn(str(status), result["error"])

    def test_an_empty_or_unusable_answer_says_what_was_wrong(self) -> None:
        no_key = vast.fetch_instances("", sender=_Recorder(200, b"{}"))
        self.assertEqual(no_key["status"], 0)
        self.assertIn("no Vast.ai key", no_key["error"])

        not_json = vast.fetch_instances("k", sender=_Recorder(200, b"<html>nope"))
        self.assertEqual(not_json["status"], 200)
        self.assertIn("not JSON", not_json["error"])

        unreachable = vast.fetch_instances("k", sender=lambda _r, _t: (0, b""))
        self.assertEqual(unreachable["status"], 0)
        self.assertEqual(unreachable["instances"], [])

    def test_a_bare_instance_list_is_parsed_too(self) -> None:
        payload = [INSTANCES_BODY["instances"][0]]
        rows = vast.parse_instances(payload)
        self.assertEqual([row["endpoint"] for row in rows], ["http://203.0.113.9:31234"])
        self.assertEqual(vast.parse_instances({"instances": "nope"}), [])


class InstanceStore(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.path = Path(self._td.name) / "studio-vast.json"
        self._old = vast.INSTANCES_PATH
        vast.INSTANCES_PATH = self.path
        self.addCleanup(lambda: setattr(vast, "INSTANCES_PATH", self._old))

    def test_two_instances_survive_a_reload_from_disk(self) -> None:
        doc = vast.empty_doc()
        doc, err = vast.add_instance(doc, "203.0.113.9:31234", label="klein-4090")
        self.assertEqual(err, "")
        doc, err = vast.add_instance(doc, "http://198.51.100.7:40111", label="snofs-5090")
        self.assertEqual(err, "")
        vast.save_doc(doc)

        reloaded = vast.load_doc()
        self.assertEqual(
            [row["endpoint"] for row in reloaded["instances"]],
            ["http://203.0.113.9:31234", "http://198.51.100.7:40111"],
        )
        self.assertEqual(
            [row["label"] for row in reloaded["instances"]], ["klein-4090", "snofs-5090"]
        )
        # The first one added is the one Generate uses until the user picks another.
        self.assertEqual(reloaded["active"], "http://203.0.113.9:31234")
        self.assertEqual(vast.row_label(vast.active_row(reloaded) or {}), "klein-4090")

    def test_the_same_instance_twice_under_two_spellings_is_refused(self) -> None:
        doc = vast.empty_doc()
        doc, _ = vast.add_instance(doc, "1.2.3.4:31234")
        again, err = vast.add_instance(doc, "http://1.2.3.4:31234/")
        self.assertIn("already in the list", err)
        self.assertEqual(len(again["instances"]), 1, "a refusal changes nothing")

    def test_a_refusal_leaves_the_callers_document_alone(self) -> None:
        doc = vast.empty_doc()
        returned, err = vast.add_instance(doc, "   ")
        self.assertIn("Type an instance address", err)
        self.assertIs(returned, doc)
        self.assertEqual(doc["instances"], [])

    def test_removing_the_active_instance_selects_the_next_one(self) -> None:
        doc = vast.empty_doc()
        doc, _ = vast.add_instance(doc, "1.2.3.4:31234")
        doc, _ = vast.add_instance(doc, "5.6.7.8:40000")
        doc = vast.set_active(doc, "http://5.6.7.8:40000")
        doc, removed = vast.remove_instance(doc, "5.6.7.8:40000")
        self.assertTrue(removed)
        self.assertEqual(doc["active"], "http://1.2.3.4:31234")
        doc, removed = vast.remove_instance(doc, "http://1.2.3.4:31234")
        self.assertTrue(removed)
        self.assertEqual(doc["active"], "", "nothing left to Generate on")
        self.assertIsNone(vast.active_row(doc))
        _, removed = vast.remove_instance(doc, "1.2.3.4:31234")
        self.assertFalse(removed, "removing what is not there is not a change")

    def test_an_unknown_active_endpoint_is_cleared(self) -> None:
        vast.save_doc(
            {
                "mode": "vast",
                "active": "http://9.9.9.9:1",
                "instances": [{"endpoint": "http://1.2.3.4:31234"}],
            }
        )
        doc = vast.load_doc()
        self.assertEqual(doc["mode"], "vast", "the engine choice is kept")
        self.assertEqual(doc["active"], "", "but Generate cannot point at a row it cannot show")

    def test_the_mode_round_trips_and_an_unknown_one_keeps_salad(self) -> None:
        doc = vast.set_mode(vast.empty_doc(), vast.MODE_VAST)
        vast.save_doc(doc)
        self.assertEqual(vast.load_doc()["mode"], vast.MODE_VAST)
        self.assertEqual(vast.load_doc()["mode"], "vast")
        self.assertEqual(vast.set_mode(doc, "banana")["mode"], vast.MODE_SALAD)

    def test_a_missing_or_broken_file_reads_as_the_empty_document(self) -> None:
        self.assertEqual(vast.load_doc()["instances"], [])
        self.assertEqual(vast.load_doc()["mode"], vast.MODE_SALAD)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(vast.load_doc(), vast.empty_doc())
        self.path.write_text('["a list, not a document"]', encoding="utf-8")
        self.assertEqual(vast.load_doc(), vast.empty_doc())

    def test_the_store_is_outside_the_repository(self) -> None:
        """Instance rows are not secrets, but they belong to the user's config."""
        repo = Path(__file__).resolve().parent.parent
        self.assertFalse(
            str(self._old).lower().startswith(str(repo).lower()),
            f"the vast store must not live in the repo: {self._old}",
        )


class VastGeneration(unittest.TestCase):
    """The shipped render path, driven with an injected transport."""

    PAYLOAD = {
        "prompt": {
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "x", "images": ["8", 0]},
            }
        },
        "convert_output": {"format": "jpeg"},
    }

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.out = Path(self._td.name)

    def test_the_prompt_is_posted_to_the_instance_and_the_plate_is_written(self) -> None:
        send = _Recorder(200, json.dumps({"images": [PLATE]}).encode())
        logs: list[str] = []
        path = generator.generate_from_vast(
            endpoint="203.0.113.9:31234",
            payload=self.PAYLOAD,
            out_dir=self.out,
            on_log=lambda level, message: logs.append(f"{level}: {message}"),
            sender=send,
        )
        self.assertEqual(len(send.requests), 1, "one POST, one plate")
        request = send.requests[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "http://203.0.113.9:31234/prompt")
        body = json.loads(bytes(request.data).decode("utf-8"))
        self.assertEqual(body["prompt"]["9"]["class_type"], "SaveImage")
        self.assertEqual(body["convert_output"]["format"], "jpeg")
        self.assertIsNone(
            _header(request, "Authorization"),
            "a vast token must never be sent to a rented instance",
        )
        self.assertIsNone(_header(request, "Salad-Api-Key"), "nor the Salad one")
        self.assertTrue(path.is_file(), "the plate must be written")
        self.assertTrue(path.name.startswith("studio_") and path.name.endswith(".jpg"))
        self.assertEqual(path.read_bytes(), base64.b64decode(PLATE))
        self.assertTrue(any(entry.startswith("ok:") for entry in logs), logs)

    def test_a_rejected_post_raises_with_the_status(self) -> None:
        send = _Recorder(401, b'{"error": "unauthorized"}')
        with self.assertRaises(RuntimeError) as caught:
            generator.generate_from_vast(
                endpoint="1.2.3.4:31234",
                payload=self.PAYLOAD,
                out_dir=self.out,
                sender=send,
            )
        self.assertIn("401", str(caught.exception))
        self.assertEqual(list(self.out.glob("studio_*.jpg")), [], "no plate on a refusal")

    def test_a_prompt_id_answer_is_polled_on_the_same_instance(self) -> None:
        """A native Comfy answer carries no images[]; /history has them."""
        answers = [
            (200, json.dumps({"prompt_id": "abc-123"}).encode()),
            (200, json.dumps({"abc-123": {"outputs": {"9": {"images": [PLATE]}}}}).encode()),
        ]
        requests: list = []

        def transport(request, timeout):
            requests.append(request)
            return answers.pop(0) if answers else (200, b"{}")

        with mock.patch.object(generator.salad_gen.time, "sleep", lambda _s: None):
            path = generator.generate_from_vast(
                endpoint="1.2.3.4:31234",
                payload=self.PAYLOAD,
                out_dir=self.out,
                sender=transport,
            )
        self.assertEqual(len(requests), 2, "the POST, then one history read")
        self.assertEqual(requests[1].full_url, "http://1.2.3.4:31234/history/abc-123")
        self.assertIsNone(_header(requests[1], "Authorization"))
        self.assertEqual(path.read_bytes(), base64.b64decode(PLATE))

    def test_a_plain_comfyui_answer_is_fetched_from_view(self) -> None:
        """A plain ComfyUI: prompt_id, then /history, then /view for the plate.

        That is what the vast.ai ComfyUI template publishes on its own port, and
        its SaveImage writes a PNG, so the plate lands as ``studio_*.png``.
        """
        answers = [
            (200, json.dumps({"prompt_id": "abc-123"}).encode()),
            (200, json.dumps(HISTORY_FILE_BODY).encode()),
            (200, base64.b64decode(PNG_PLATE)),
        ]
        requests: list = []

        def transport(request, timeout):
            requests.append(request)
            return answers.pop(0) if answers else (200, b"{}")

        with mock.patch.object(generator.salad_gen.time, "sleep", lambda _s: None):
            path = generator.generate_from_vast(
                endpoint="203.0.113.9:31234",
                payload=self.PAYLOAD,
                out_dir=self.out,
                sender=transport,
            )
        self.assertEqual(
            [r.full_url for r in requests],
            [
                "http://203.0.113.9:31234/prompt",
                "http://203.0.113.9:31234/history/abc-123",
                "http://203.0.113.9:31234/view?filename=x_00001_.png&subfolder=&type=output",
            ],
            "the plate is fetched from /view with the record's own fields",
        )
        self.assertTrue(path.name.endswith(".png"), path.name)
        self.assertEqual(path.read_bytes(), base64.b64decode(PNG_PLATE))
        self.assertEqual(
            generator.list_history(self.out),
            [path],
            "the gallery must see a PNG plate as well as a JPEG one",
        )
        self.assertEqual(generator.clear_history(self.out), 1)

    def test_a_view_that_answers_nothing_is_reported(self) -> None:
        answers = [
            (200, json.dumps({"prompt_id": "abc-123"}).encode()),
            (200, json.dumps(HISTORY_FILE_BODY).encode()),
            (404, b"not found"),
        ]

        def transport(request, timeout):
            return answers.pop(0) if answers else (200, b"{}")

        with mock.patch.object(generator.salad_gen.time, "sleep", lambda _s: None):
            with self.assertRaises(RuntimeError) as caught:
                generator.generate_from_vast(
                    endpoint="203.0.113.9:31234",
                    payload=self.PAYLOAD,
                    out_dir=self.out,
                    sender=transport,
                )
        self.assertIn("/view", str(caught.exception))
        self.assertIn("404", str(caught.exception))
        self.assertEqual(list(self.out.glob("studio_*")), [], "no plate on a failure")

    def test_a_missing_endpoint_is_refused_by_name(self) -> None:
        with self.assertRaises(RuntimeError) as caught:
            generator.generate_from_vast(
                endpoint="  ", payload=self.PAYLOAD, out_dir=self.out
            )
        self.assertIn("Vast.ai tab", str(caught.exception))

    def test_an_answer_with_no_image_is_refused(self) -> None:
        send = _Recorder(200, json.dumps({"status": "ok"}).encode())
        with self.assertRaises(RuntimeError) as caught:
            generator.generate_from_vast(
                endpoint="1.2.3.4:31234",
                payload=self.PAYLOAD,
                out_dir=self.out,
                sender=send,
            )
        self.assertIn("no images", str(caught.exception))


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class VastTabAndGenerate(unittest.TestCase):
    """The Vast.ai page and the press, through the real window."""

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

    @staticmethod
    def _pump(app, predicate, seconds: float = 30.0) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if predicate():
                return True
            app.update()
            time.sleep(0.02)
        return bool(predicate())

    @staticmethod
    def _inline():
        """Run the page's worker on the calling thread.

        A render worker hands its result back with ``after(0, ...)``, which Tk
        only accepts from the thread that owns the window, so the worker runs
        inline here and ``update()`` lets that callback land. What is under test
        is the page's own wiring and the real POST, not the thread.
        """
        return mock.patch("salad_studio.app.threading.Thread", _Inline)

    def test_the_page_is_in_the_notebook_and_starts_on_salad(self) -> None:
        app = self._window()
        labels = [app.nb.tab(t, "text") for t in app.nb.tabs()]
        self.assertIn("Vast.ai", labels)
        self.assertEqual(labels, list(self.app_mod.TAB_ORDER))
        self.assertEqual(app.gen_mode(), "salad", "a fresh install renders on Salad")

    def test_the_key_lists_the_account_and_the_rows_are_saved(self) -> None:
        """The page's fetch: the stored key, the real request, the saved rows."""
        tok.write_token("vast", "vast-page-key")
        app = self._window()
        self.assertEqual(tok.read_token("vast"), "vast-page-key")
        send = _Recorder(200, json.dumps(INSTANCES_BODY).encode())
        with mock.patch.object(vast, "_send", send), self._inline():
            app._on_vast_fetch()
            self.assertTrue(
                self._pump(app, lambda: not app._vast_fetch_busy),
                "the fetch never came back",
            )
        self.assertEqual(len(send.requests), 1)
        self.assertEqual(send.requests[0].full_url, vast.INSTANCES_URL)
        self.assertEqual(_header(send.requests[0], "Authorization"), "Bearer vast-page-key")
        rows = [app.vast_tree.item(i, "values") for i in app.vast_tree.get_children()]
        self.assertEqual(
            [row[2] for row in rows],
            ["http://203.0.113.9:31234", "http://198.51.100.7:40111"],
        )
        self.assertEqual(rows[0][1], "klein-4090", "the label column shows the vast label")
        self.assertEqual(app._vast_active()["endpoint"], "http://203.0.113.9:31234")

    def test_a_rejected_key_is_reported_on_the_page(self) -> None:
        tok.write_token("vast", "stale-key")
        app = self._window()
        with mock.patch.object(
            vast, "_send", _Recorder(401, b'{"error": "bad key"}')
        ), self._inline():
            app._on_vast_fetch()
            self.assertTrue(self._pump(app, lambda: not app._vast_fetch_busy))
        self.assertIn("rejected", app.var_vast_status.get())
        self.assertEqual(app.vast_tree.get_children(), (), "no rows from a rejected key")

    def test_two_instances_typed_on_the_page_survive_a_restart(self) -> None:
        app = self._window()
        app.var_vast_new.set("203.0.113.9:31234, 198.51.100.7:40111")
        app._on_vast_add()
        self.assertEqual(len(app.vast_tree.get_children()), 2)
        app.var_gen_mode.set("vast")
        app._on_gen_mode()
        self._destroy(app)

        fresh = self._window()
        rows = [fresh.vast_tree.item(i, "values") for i in fresh.vast_tree.get_children()]
        self.assertEqual(
            [row[2] for row in rows],
            ["http://203.0.113.9:31234", "http://198.51.100.7:40111"],
            "both instances must come back after a restart",
        )
        self.assertEqual(fresh.gen_mode(), "vast", "and so must the engine choice")

    def test_selecting_a_row_points_generate_at_that_instance(self) -> None:
        app = self._window()
        app.var_vast_new.set("203.0.113.9:31234, 198.51.100.7:40111")
        app._on_vast_add()
        second = app.vast_tree.get_children()[1]
        app.vast_tree.selection_set(second)
        app._on_vast_select()

        self.assertEqual(app._vast_active()["endpoint"], "http://198.51.100.7:40111")
        self.assertEqual(
            vast.load_doc()["active"],
            "http://198.51.100.7:40111",
            "the choice must be on disk, not only on the page",
        )
        marks = [app.vast_tree.item(i, "values")[0] for i in app.vast_tree.get_children()]
        self.assertEqual(marks, ["", "●"], "the row Generate uses is the marked one")

    def test_pressing_generate_renders_on_the_selected_instance(self) -> None:
        """The whole press: the page's selection, the real POST, the plate."""
        app = self._window()
        app.var_vast_new.set("203.0.113.9:31234")
        app._on_vast_add()
        app.var_gen_mode.set("vast")
        app._on_gen_mode()
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert(
            "1.0",
            json.dumps(
                {
                    "prompt": {
                        "9": {
                            "class_type": "SaveImage",
                            "inputs": {"filename_prefix": "x", "images": ["8", 0]},
                        }
                    },
                    "convert_output": {"format": "jpeg"},
                }
            ),
        )
        send = _Recorder(200, json.dumps({"images": [PLATE]}).encode())
        with tempfile.TemporaryDirectory() as out_td, mock.patch.object(
            vast, "_send", send
        ), mock.patch.object(self.app_mod, "OUT_DIR", Path(out_td)), mock.patch.object(
            self.app_mod.messagebox, "showerror"
        ), self._inline():
            app.gen_btn.invoke()
            self.assertTrue(
                self._pump(app, lambda: not app._busy, 60), "the render never finished"
            )
            plates = sorted(Path(out_td).glob("studio_*.jpg"))
            self.assertEqual(len(plates), 1, "one press writes one plate")
            self.assertEqual(plates[0].read_bytes(), base64.b64decode(PLATE))
            self.assertTrue(plates[0].stat().st_size > 0)
        self.assertEqual(len(send.requests), 1)
        self.assertEqual(send.requests[0].full_url, "http://203.0.113.9:31234/prompt")
        self.assertEqual(send.requests[0].get_method(), "POST")

    def test_a_press_with_no_instance_selected_is_refused(self) -> None:
        app = self._window()
        app.var_gen_mode.set("vast")
        app._on_gen_mode()
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert(
            "1.0", json.dumps({"prompt": {"9": {"class_type": "SaveImage", "inputs": {}}}})
        )
        shown: list[str] = []
        with mock.patch.object(
            self.app_mod.messagebox, "showinfo", lambda *a, **k: shown.append(str(a))
        ):
            app._on_generate()
        self.assertTrue(shown, "the press must say why it cannot render")
        self.assertIn("Vast.ai tab", shown[0])
        self.assertFalse(app._busy)


if __name__ == "__main__":
    unittest.main()
