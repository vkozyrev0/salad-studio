"""Vast.ai picture generation: the control call, the instance store, the render.

The key is never in a source literal, so the tests that need one write it into a
temp token store. Every HTTP path is driven through the injected sender, which
is the same seam ``salad_status`` uses: the test records the real request object
the shipped code built and answers it, instead of reaching the network.
"""
from __future__ import annotations

import base64
import importlib.util
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

from salad_studio import generator, profiles, tokens as tok, vast  # noqa: E402
from tests.test_launch import _TempPaths  # noqa: E402

# The store ``vast.py`` ships, read by executing the file rather than by reading
# the live global: modules that build a window (test_app_layout, test_layers,
# test_theme) redirect ``vast.INSTANCES_PATH`` to a temp dir at import time, and
# their redirect is still in place when this module is imported.
_VAST_SOURCE = PKG / "vast.py"


def _shipped_instances_path() -> Path:
    """``INSTANCES_PATH`` as the shipped ``vast.py`` sets it."""
    spec = importlib.util.spec_from_file_location("_vast_shipped", _VAST_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - the file is right there
        raise AssertionError(f"cannot load {_VAST_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return Path(module.INSTANCES_PATH)


SHIPPED_INSTANCES_PATH = _shipped_instances_path()

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

# The state measured on 2026-10-18, verbatim from the report:
# ``~/.config/salad/studio-vast.json`` held a running row for an instance the
# account no longer lists, plus a ``pending`` contract for the one it does.
EVIDENCE_IMAGE = (
    "docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein"
)
EVIDENCE_LEGACY_DOC = {
    "version": 1,
    "mode": "vast",
    "active": "http://1.193.138.161:40006",
    "instances": [
        {
            "id": 56373341,
            "endpoint": "http://1.193.138.161:40006",
            "label": "",
            "gpu": "RTX 5090",
            "state": "running",
            "image": EVIDENCE_IMAGE,
        }
    ],
    "replace": {},
    "pending": {
        "contract": 56496191,
        "label": "salad-studio-53483606",
        "image": EVIDENCE_IMAGE,
    },
}
# ``fetch_records`` (unfiltered) as the live account answered it: the old
# instance is absent and the new one has no port mapping yet.
EVIDENCE_RECORD = {
    "id": 56496191,
    "label": "salad-studio-53483606",
    "actual_status": "loading",
    "cur_state": "running",
    "public_ipaddr": "142.252.100.192",
    "ports": None,
    "gpu_name": "RTX 5090",
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

    def test_the_salad_wrapper_port_wins_over_raw_comfyui(self) -> None:
        """The wrapper resolves Civitai LoRA URLs; 8188 only takes local files."""
        instance = {
            "public_ipaddr": "10.0.0.10",
            "ports": {
                "3000/tcp": [{"HostPort": 31080}],
                "8188/tcp": [{"HostPort": 31151}],
            },
        }
        self.assertEqual(
            vast.instance_endpoint(instance),
            "http://10.0.0.10:31080",
            "the wrapper is the port that can run a Civitai LoRA graph",
        )

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

    def test_text_that_names_no_host_is_refused_not_prefixed(self) -> None:
        """Issue 2: `http://` on anything made a typed phrase five instances.

        A word comes back as "" — what the docstring already promised — so the
        store can refuse it, and no address a user could reach before is lost:
        a host with a dot, a host with a port, and any explicit scheme still
        resolve to the same URL they did.
        """
        for typed in ("not", "not an address at all", "comfy-local", "host", "1"):
            with self.subTest(typed=typed):
                self.assertEqual(
                    vast.normalize_endpoint(typed),
                    "",
                    f"{typed!r} names no host and must not become an address",
                )
        for typed, want in (
            ("1.2.3.4:31234", "http://1.2.3.4:31234"),
            ("comfy-local:8188", "http://comfy-local:8188"),
            ("comfy.example", "http://comfy.example"),
            ("http://comfy-local", "http://comfy-local"),
            ("https://host.example/", "https://host.example"),
            ("http://1.2.3.4:31234/prompt", "http://1.2.3.4:31234"),
        ):
            with self.subTest(typed=typed):
                self.assertEqual(vast.normalize_endpoint(typed), want)

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

    def test_a_phrase_is_refused_word_by_word_not_stored(self) -> None:
        """Issue 2: the page splits the box on spaces, so each word is offered here.

        Every word names no host, so every one is refused and the document keeps
        no instance — five unusable endpoints is what the old prefix produced.
        """
        doc = vast.empty_doc()
        refusals = []
        for word in "not an address at all".split():
            doc, refusal = vast.add_instance(doc, word)
            refusals.append(refusal)
        self.assertTrue(all(refusals), f"every word must be refused: {refusals}")
        for refusal in refusals:
            self.assertIn("Type an instance address", refusal)
        self.assertEqual(doc["instances"], [], "nothing unusable is stored")
        self.assertEqual(doc["active"], "", "and nothing becomes the instance to render on")
        self.assertIsNone(vast.active_row(doc))

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
        """Instance rows are not secrets, but they belong to the user's config.

        The shipped path, not the live global: a window-building module redirects
        ``vast.INSTANCES_PATH`` to a temp dir, and a guard that read the global
        would be checking that redirect.
        """
        repo = Path(__file__).resolve().parent.parent
        self.assertFalse(
            str(SHIPPED_INSTANCES_PATH).lower().startswith(str(repo).lower()),
            f"the vast store must not live in the repo: {SHIPPED_INSTANCES_PATH}",
        )


class RowModel(unittest.TestCase):
    """A row is an instance identity: the endpoint is optional user state."""

    def test_the_key_is_the_id_else_the_endpoint(self) -> None:
        self.assertEqual(vast.row_key({"id": 56496191, "endpoint": ""}), "56496191")
        self.assertEqual(
            vast.row_key({"id": None, "endpoint": "1.193.138.161:40006"}),
            "http://1.193.138.161:40006",
            "an endpoint-only row is keyed by its one spelling",
        )

    def test_clean_row_keeps_an_id_with_no_endpoint(self) -> None:
        row = vast.clean_row(
            {"id": "56496191", "endpoint": "", "state": "Loading", "label": "new"}
        )
        self.assertEqual(
            row,
            {
                "id": 56496191,
                "endpoint": "",
                "label": "new",
                "gpu": "",
                "state": "loading",
                "image": "",
            },
        )

    def test_clean_row_drops_a_row_with_neither_id_nor_endpoint(self) -> None:
        for raw in ({"label": "x"}, {"id": "nope"}, {"id": 0}, {"endpoint": "  "}, "x"):
            with self.subTest(raw=raw):
                self.assertIsNone(vast.clean_row(raw))

    def test_clean_row_clears_the_endpoint_of_a_destroyed_row(self) -> None:
        row = vast.clean_row(
            {
                "id": 56373341,
                "endpoint": "http://1.193.138.161:40006",
                "state": "Destroyed",
                "image": EVIDENCE_IMAGE,
            }
        )
        self.assertEqual(row["endpoint"], "", "a destroyed instance has no address")
        self.assertEqual(row["state"], "destroyed")
        self.assertEqual(row["image"], EVIDENCE_IMAGE, "the image is user state")

    def test_row_label_falls_back_to_the_id(self) -> None:
        self.assertEqual(vast.row_label({"label": "klein"}), "klein")
        self.assertEqual(
            vast.row_label({"label": "", "endpoint": "http://1.2.3.4:31234"}),
            "http://1.2.3.4:31234",
        )
        self.assertEqual(vast.row_label({"label": "", "id": 7}), "#7")

    def test_upsert_matches_by_id_and_keeps_the_user_image_and_label(self) -> None:
        doc = {
            "instances": [
                {
                    "id": 7,
                    "endpoint": "",
                    "label": "my label",
                    "gpu": "",
                    "state": "creating",
                    "image": EVIDENCE_IMAGE,
                }
            ]
        }
        doc, status = vast.upsert_instance(
            doc,
            {
                "id": 7,
                "endpoint": "http://1.2.3.4:31234",
                "label": "",
                "gpu": "RTX 5090",
                "state": "running",
            },
        )
        self.assertEqual(status, "updated")
        row = doc["instances"][0]
        self.assertEqual(row["endpoint"], "http://1.2.3.4:31234")
        self.assertEqual(row["state"], "running")
        self.assertEqual(row["gpu"], "RTX 5090")
        self.assertEqual(row["label"], "my label", "an empty incoming label loses")
        self.assertEqual(row["image"], EVIDENCE_IMAGE, "the incoming row has no image")

    def test_upsert_matches_by_endpoint_when_the_id_is_new(self) -> None:
        doc = {"instances": [{"endpoint": "http://1.2.3.4:31234", "label": "typed"}]}
        doc, status = vast.upsert_instance(
            doc, {"id": 8, "endpoint": "http://1.2.3.4:31234", "state": "running"}
        )
        self.assertEqual(status, "updated")
        self.assertEqual(len(doc["instances"]), 1, "one instance, one row")
        self.assertEqual(doc["instances"][0]["id"], 8)
        self.assertEqual(doc["instances"][0]["label"], "typed")

    def test_upsert_reports_an_identical_row_as_unchanged(self) -> None:
        row = {
            "id": 7,
            "endpoint": "http://1.2.3.4:31234",
            "label": "x",
            "gpu": "",
            "state": "running",
            "image": "",
        }
        doc, status = vast.upsert_instance({"instances": [dict(row)]}, dict(row))
        self.assertEqual(status, "unchanged")
        self.assertEqual(doc["instances"], [row])

    def test_remove_and_set_active_use_the_row_key(self) -> None:
        doc = {
            "active": "http://1.2.3.4:31234",
            "instances": [
                {"id": 7, "endpoint": "http://1.2.3.4:31234"},
                {"id": 8, "endpoint": ""},
                {"id": 9, "endpoint": "http://5.6.7.8:40000"},
            ],
        }
        doc, removed = vast.remove_instance(doc, "7")
        self.assertTrue(removed)
        self.assertEqual([row["id"] for row in doc["instances"]], [8, 9])
        self.assertEqual(
            doc["active"],
            "http://5.6.7.8:40000",
            "the next row that has an endpoint becomes active",
        )
        doc = vast.set_active(doc, "8")
        self.assertEqual(doc["active"], "http://5.6.7.8:40000", "no endpoint, no target")
        doc = vast.set_active(doc, "http://5.6.7.8:40000")
        self.assertEqual(doc["active"], "http://5.6.7.8:40000")

    def test_active_row_is_never_a_row_without_an_endpoint(self) -> None:
        doc = {
            "active": "",
            "instances": [{"id": 7, "endpoint": "", "state": "loading"}],
        }
        self.assertIsNone(vast.active_row(doc))
        doc["active"] = "http://1.2.3.4:31234"
        doc["instances"][0]["endpoint"] = "http://1.2.3.4:31234"
        doc["instances"][0]["state"] = "destroyed"
        self.assertIsNone(vast.active_row(doc), "a destroyed row is never active")


class EvidenceReconciliation(unittest.TestCase):
    """The measured 2026-10-18 state, reconciled exactly as Fetch reads it."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.path = Path(self._td.name) / "studio-vast.json"

    def _evidence_doc(self) -> dict:
        """The stored document as the old build left it, folded by load_doc."""
        self.path.write_text(json.dumps(EVIDENCE_LEGACY_DOC), encoding="utf-8")
        return vast.load_doc(self.path)

    def _row(self, doc: dict, instance_id: int) -> dict:
        for row in doc["instances"]:
            if str(row.get("id") or "") == str(instance_id):
                return row
        raise AssertionError(f"no row {instance_id} in {doc['instances']}")

    def test_load_doc_folds_the_legacy_pending_into_a_creating_row(self) -> None:
        doc = self._evidence_doc()
        self.assertEqual(
            sorted(str(row["id"]) for row in doc["instances"]),
            ["56373341", "56496191"],
            "the old row and the contract the old build kept as pending",
        )
        self.assertEqual(
            self._row(doc, 56496191),
            {
                "id": 56496191,
                "endpoint": "",
                "label": "salad-studio-53483606",
                "gpu": "",
                "state": "creating",
                "image": EVIDENCE_IMAGE,
            },
        )
        self.assertEqual(doc["pending"], {}, "the one-slot shadow is gone")

    def test_a_pending_contract_that_already_has_a_row_is_not_duplicated(self) -> None:
        legacy = {**EVIDENCE_LEGACY_DOC}
        legacy["pending"] = {"contract": 56373341, "label": "x", "image": ""}
        self.path.write_text(json.dumps(legacy), encoding="utf-8")
        doc = vast.load_doc(self.path)
        self.assertEqual(
            [str(row["id"]) for row in doc["instances"]].count("56373341"), 1
        )

    def test_the_evidence_fetch_destroys_the_old_row_and_shows_the_new_one_loading(
        self,
    ) -> None:
        doc = self._evidence_doc()
        doc, summary = vast.reconcile(doc, [EVIDENCE_RECORD], complete=True)

        old = self._row(doc, 56373341)
        self.assertEqual(old["state"], "destroyed")
        self.assertEqual(old["endpoint"], "", "a destroyed instance has no address")
        self.assertEqual(old["image"], EVIDENCE_IMAGE, "the image is user state")

        new = self._row(doc, 56496191)
        self.assertEqual(new["state"], "loading")
        self.assertEqual(new["endpoint"], "", "no Comfy port is mapped yet")
        self.assertEqual(new["label"], "salad-studio-53483606")
        self.assertEqual(new["gpu"], "RTX 5090")
        self.assertEqual(new["image"], EVIDENCE_IMAGE, "the creating row's image survives")

        self.assertEqual(doc["active"], "", "the active endpoint is gone")
        self.assertEqual(sorted(summary["destroyed"]), ["56373341"])
        self.assertIn("http://1.193.138.161:40006", summary["gone_endpoints"])
        self.assertEqual(summary["promoted"], "")

    def test_a_second_fetch_promotes_the_creating_row_once_it_maps(self) -> None:
        doc = self._evidence_doc()
        doc, _summary = vast.reconcile(doc, [EVIDENCE_RECORD], complete=True)
        mapped = {
            **EVIDENCE_RECORD,
            "actual_status": "running",
            "ports": {"8188/tcp": [{"HostPort": 40006}]},
        }
        doc, summary = vast.reconcile(doc, [mapped], complete=True)
        row = self._row(doc, 56496191)
        self.assertEqual(row["endpoint"], "http://142.252.100.192:40006")
        self.assertEqual(row["state"], "running")
        self.assertEqual(doc["active"], "http://142.252.100.192:40006")
        self.assertEqual(summary["promoted"], "56496191")
        self.assertEqual(row["image"], EVIDENCE_IMAGE, "the image survives the promotion")

    def test_the_active_target_follows_an_endpoint_move(self) -> None:
        """A port preference change moves the row; the selection moves with it."""
        doc = {
            "active": "http://1.2.3.4:31151",
            "instances": [
                {
                    "id": 56507376,
                    "endpoint": "http://1.2.3.4:31151",
                    "label": "salad-studio-53518141",
                    "gpu": "RTX 5090",
                    "state": "running",
                    "image": "",
                }
            ],
        }
        record = {
            "id": 56507376,
            "public_ipaddr": "1.2.3.4",
            "actual_status": "running",
            "ports": {
                "3000/tcp": [{"HostPort": 31080}],
                "8188/tcp": [{"HostPort": 31151}],
            },
        }
        doc, summary = vast.reconcile(doc, [record], complete=True)
        self.assertEqual(doc["instances"][0]["endpoint"], "http://1.2.3.4:31080")
        self.assertEqual(doc["active"], "http://1.2.3.4:31080")
        self.assertIn("http://1.2.3.4:31151", summary["gone_endpoints"])

    def test_a_complete_listing_never_deletes_a_missing_row(self) -> None:
        doc = self._evidence_doc()
        doc, _summary = vast.reconcile(doc, [EVIDENCE_RECORD], complete=True)
        self.assertEqual(len(doc["instances"]), 2, "destroyed rows stay in the list")

    def test_a_truncated_listing_destroys_nothing(self) -> None:
        doc = self._evidence_doc()
        doc, summary = vast.reconcile(doc, [EVIDENCE_RECORD], complete=False)
        old = self._row(doc, 56373341)
        self.assertEqual(old["state"], "running")
        self.assertEqual(old["endpoint"], "http://1.193.138.161:40006")
        self.assertEqual(doc["active"], "http://1.193.138.161:40006")
        self.assertEqual(summary["destroyed"], [], "a partial list proves nothing is gone")

    def test_a_manual_row_is_never_touched(self) -> None:
        doc = {
            "active": "http://9.9.9.9:1",
            "instances": [
                {"endpoint": "http://9.9.9.9:1", "label": "typed", "state": ""}
            ],
        }
        doc, summary = vast.reconcile(doc, [], complete=True)
        self.assertEqual(
            doc["instances"][0]["endpoint"], "http://9.9.9.9:1", "no id, no reconciliation"
        )
        self.assertEqual(doc["instances"][0]["state"], "")
        self.assertEqual(doc["active"], "http://9.9.9.9:1")
        self.assertEqual(summary["destroyed"], [])

    def test_an_unmapped_record_keeps_its_real_state(self) -> None:
        record = {
            "id": 5,
            "actual_status": "stopped",
            "public_ipaddr": "192.0.2.5",
            "ports": {},
        }
        doc, _summary = vast.reconcile({"instances": []}, [record], complete=True)
        self.assertEqual(doc["instances"][0]["state"], "stopped")
        self.assertEqual(doc["instances"][0]["endpoint"], "")


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

    def test_a_200_with_no_images_reports_the_reason_not_a_type_error(self) -> None:
        """An accepted POST with no plate must name the empty answer."""
        send = _Recorder(
            200, json.dumps({"prompt": {"9": {"class_type": "SaveImage"}}}).encode()
        )
        with self.assertRaises(RuntimeError) as caught:
            generator.generate_from_vast(
                endpoint="1.2.3.4:31234",
                payload=self.PAYLOAD,
                out_dir=self.out,
                sender=send,
            )
        self.assertIn("no images", str(caught.exception))
        self.assertEqual(list(self.out.glob("studio_*")), [], "no plate on an empty answer")

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
        self.assertIn("Vast.ai instances", str(caught.exception))
        self.assertIn("Config page", str(caught.exception))

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


class VastTabAndGenerate(unittest.TestCase):
    """The Vast.ai section and the press, through the Config page and the window.

    ``tests._flet_host.Host`` runs the page's workers inline, so each press has
    its result before the next assertion, and a store read is a restart's read.
    """

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        tok.write_token("salad", "salad-key")

    def _window(self):
        """A window with every store in the temp dir, its active profile loaded, Config built."""
        from salad_studio.pages.config import ConfigPage
        from tests._flet_host import Host

        host = Host()
        profiles.ensure_builtin_profiles()
        active = profiles.get_active()
        host.apply_profile(profiles.load_all().get(active or "klein"))
        host.store_page("Config", ConfigPage(host))
        return host

    def _page(self, host):
        return host.pages["Config"]

    @staticmethod
    def _type_instances(page, typed: str) -> None:
        """Type addresses into the page's box and press Add instance, one address per press."""
        for address in typed.split(","):
            page.vast_endpoint.value = address.strip()
            page.add_vast()

    def test_the_section_is_on_the_config_page_and_starts_on_salad(self) -> None:
        from salad_studio.flet_shell import TAB_ORDER

        host = self._window()
        page = self._page(host)
        self.assertIn("vast", [segment.value for segment in page.tabs.segments],
                      "the vast.ai hosts are a Config section now")
        self.assertNotIn("Vast.ai", TAB_ORDER, "the vast page is part of Config now")
        self.assertEqual(TAB_ORDER[0], "Config", "and Config is the page a fresh window opens on")
        self.assertEqual(host.form.mode, "salad", "a fresh install renders on Salad")

    def test_the_key_lists_the_account_and_the_rows_are_saved(self) -> None:
        """The page's fetch: the stored key, the real request, the saved rows."""
        tok.write_token("vast", "vast-page-key")
        host = self._window()
        page = self._page(host)
        self.assertEqual(tok.read_token("vast"), "vast-page-key")
        send = _Recorder(200, json.dumps(INSTANCES_BODY).encode())
        with mock.patch.object(vast, "_send", send):
            page.fetch_vast()
        self.assertEqual(len(send.requests), 1)
        self.assertEqual(send.requests[0].full_url, vast.INSTANCES_URL)
        self.assertEqual(_header(send.requests[0], "Authorization"), "Bearer vast-page-key")
        self.assertEqual(
            [row["endpoint"] for row in page.vast_rows],
            ["http://203.0.113.9:31234", "http://198.51.100.7:40111", ""],
            "the stopped record is a row too; it just has no address",
        )
        self.assertEqual(vast.row_label(page.vast_rows[2]), "stopped-one")
        self.assertEqual(page.vast_rows[2]["state"], "exited")
        self.assertEqual(page.vast_rows[0]["label"], "klein-4090", "the row keeps the vast label")
        self.assertIsNone(
            vast.active_row(page.vast_doc),
            "Fetch does not promote a row it did not create; the user selects one",
        )
        self.assertIsNone(vast.load_doc()["active"] or None, "and nothing is active on disk")

        page.select_vast(0)
        self.assertEqual(vast.active_row(vast.load_doc())["endpoint"], "http://203.0.113.9:31234")

    def test_fetch_reconciles_the_evidence_state_in_a_hidden_window(self) -> None:
        """The report's exact store and account, through the page's Fetch button."""
        tok.write_token("vast", "vast-key")
        vast.INSTANCES_PATH.write_text(
            json.dumps(EVIDENCE_LEGACY_DOC), encoding="utf-8"
        )
        old = profiles.default_profile("vast-old")
        old.mode = "vast"
        old.gateway = "http://1.193.138.161:40006"
        profiles.upsert(old)

        host = self._window()
        page = self._page(host)
        self.assertEqual(
            page.target.selected, ["salad"],
            "a gateway with no vast.ai instance behind it reads as the Salad target",
        )
        self.assertEqual(
            sorted(vast.row_key(row) for row in page.vast_rows),
            ["56373341", "56496191"],
            "load_doc folds the legacy pending contract into a creating row",
        )
        self.assertEqual(vast.clean_row(page.vast_doc["instances"][1])["state"], "creating")

        send = _Recorder(200, json.dumps({"instances": [EVIDENCE_RECORD]}).encode())
        with mock.patch.object(vast, "_send", send):
            page.fetch_vast()

        rows = {vast.row_key(row): row for row in page.vast_rows}
        self.assertEqual(rows["56373341"]["state"], "destroyed", "the deleted instance is not running")
        self.assertEqual(rows["56373341"]["endpoint"], "")
        self.assertEqual(rows["56496191"]["state"], "loading")
        self.assertEqual(rows["56496191"]["endpoint"], "", "no address until Comfy maps one")
        self.assertEqual(sorted(rows), ["56373341", "56496191"])
        self.assertEqual(page.vast_doc["active"], "")
        self.assertEqual(page.vast_doc["pending"], {})

        stored = vast.load_doc()
        self.assertEqual(
            {str(row["id"]): row["state"] for row in stored["instances"]},
            {"56373341": "destroyed", "56496191": "loading"},
        )
        self.assertEqual(
            profiles.load_all()["vast-old"].gateway,
            "http://1.193.138.161:40006",
            "the page's Fetch reconciles the machine list, never a profile's target",
        )

    def test_selecting_a_loading_row_does_not_change_active(self) -> None:
        """A row with no endpoint is not a target, so selecting it leaves Generate where it was."""
        host = self._window()
        page = self._page(host)
        page.vast_doc = dict(page.vast_doc, active="", instances=[
            {
                "id": 777,
                "endpoint": "",
                "label": "booting",
                "gpu": "RTX 5090",
                "state": "loading",
                "image": EVIDENCE_IMAGE,
            }
        ])
        page.show_vast()
        page.select_vast(0)
        self.assertEqual(page.vast_doc["active"], "", "no endpoint, no active target")
        self.assertIsNone(vast.active_row(page.vast_doc))

    def test_generate_refuses_when_reconciliation_left_no_active_endpoint(self) -> None:
        host = self._window()
        page = self._page(host)
        doc = dict(page.vast_doc)
        doc["instances"] = [
            {
                "id": 777,
                "endpoint": "",
                "label": "booting",
                "gpu": "RTX 5090",
                "state": "loading",
                "image": EVIDENCE_IMAGE,
            }
        ]
        doc["active"] = ""
        page.vast_doc = doc
        vast.save_doc(page.vast_doc)
        page.show_vast()
        prof = profiles.load_all()[host.form.name]
        prof.mode = "vast"
        prof.gateway = ""
        profiles.upsert(prof)
        host.apply_profile(prof)
        self.assertIsNone(vast.active_row(page.vast_doc),
                          "a row with no endpoint is not a target Generate can POST to")
        self.assertEqual(page.vast_doc["active"], "")

    def test_a_rejected_key_is_reported_on_the_page(self) -> None:
        tok.write_token("vast", "stale-key")
        host = self._window()
        page = self._page(host)
        with mock.patch.object(vast, "_send", _Recorder(401, b'{"error": "bad key"}')):
            page.fetch_vast()
        self.assertIn("401", " ".join(body for _level, _title, body in host.dialogs))
        self.assertEqual(page.vast_rows, [], "no rows from a rejected key")

    def test_two_instances_typed_on_the_page_survive_a_restart(self) -> None:
        host = self._window()
        page = self._page(host)
        self._type_instances(page, "203.0.113.9:31234, 198.51.100.7:40111")
        self.assertEqual(len(page.vast_rows), 2)
        prof = profiles.load_all()[host.form.name]
        prof.mode = "vast"
        profiles.upsert(prof)
        self.assertEqual(profiles.load_all()[host.form.name].mode, "vast", "the target is on disk")

        fresh = self._window()
        rows = self._page(fresh).vast_rows
        self.assertEqual(
            [row["endpoint"] for row in rows],
            ["http://203.0.113.9:31234", "http://198.51.100.7:40111"],
            "both instances must come back after a restart",
        )
        self.assertEqual(fresh.form.mode, "vast", "and so must the engine choice")

    def test_the_profile_target_is_what_generate_uses(self) -> None:
        host = self._window()
        page = self._page(host)
        name = (host.form.name or "klein").strip()
        page._on_mode(type("E", (), {"control": type("C", (), {"selected": {"vast"}})()})())
        page.save_profile()
        self.assertEqual(profiles.load_all()[name].mode, "vast")
        self.assertEqual(host.form.mode, "vast")
        self.assertFalse(
            hasattr(page, "var_gen_mode"),
            "the vast.ai section must not carry a Salad/Vast engine radio of its own",
        )
        page._on_mode(type("E", (), {"control": type("C", (), {"selected": {"salad"}})()})())
        page.save_profile()
        self.assertEqual(profiles.load_all()[name].mode, "salad")
        self.assertEqual(host.form.mode, "salad")

    def test_selecting_a_row_points_generate_at_that_instance(self) -> None:
        host = self._window()
        page = self._page(host)
        self._type_instances(page, "203.0.113.9:31234, 198.51.100.7:40111")
        page.select_vast(1)

        self.assertEqual(vast.active_row(vast.load_doc())["endpoint"], "http://198.51.100.7:40111")
        self.assertEqual(
            vast.load_doc()["active"],
            "http://198.51.100.7:40111",
            "the choice must be on disk, not only on the page",
        )
        marks = ["*" if row["endpoint"] == page.vast_doc["active"] and row["endpoint"] else ""
                 for row in page.vast_rows]
        self.assertEqual(marks, ["", "*"], "the row Generate uses is the marked one")

    def test_new_profile_for_this_instance_creates_a_vast_profile(self) -> None:
        """The instance becomes a profile the Active profile box lists."""
        host = self._window()
        page = self._page(host)
        page.vast_endpoint.value = "203.0.113.9:31234"
        page.add_vast()
        page.select_vast(0)
        page.make_profile_for_vast()
        name = host.form.name
        self.assertTrue(name.startswith("vast-"), name)
        stored = profiles.load_all()[name]
        self.assertEqual(stored.mode, "vast")
        self.assertEqual(stored.gateway, "http://203.0.113.9:31234")
        self.assertEqual(host.form.mode, "vast")
        page.show_profile()
        self.assertEqual(page.target.selected, ["vast"])
        self.assertEqual(page.gateway_field.label, "Instance URL")
        self.assertIn(name, [option.key for option in page.profile_list.options])

    def test_a_listing_cut_off_by_the_page_cap_says_so(self) -> None:
        """C10: an account with more pages than MAX_PAGES must not look complete.

        Every page offers a next_token, so the loop runs out of pages with more
        to read. The listing reports that instead of returning a short list.
        """
        pages = [
            json.dumps(
                {"instances": INSTANCES_BODY["instances"][:1], "next_token": f"page-{n}"}
            ).encode()
            for n in range(vast.MAX_PAGES)
        ]
        asked: list = []

        def transport(request, timeout):
            asked.append(request)
            return 200, pages.pop(0)

        result = vast.fetch_instances("vast-key-123", sender=transport)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["error"], "")
        self.assertEqual(len(asked), vast.MAX_PAGES, "it read as many pages as it may")
        self.assertTrue(result["truncated"], "and said the account has more")
        self.assertEqual(len(result["instances"]), vast.MAX_PAGES)

    def test_a_listing_that_ends_inside_the_cap_is_not_truncated(self) -> None:
        pages = [
            json.dumps({"instances": INSTANCES_BODY["instances"][:1], "next_token": "page-2"}).encode(),
            json.dumps({"instances": INSTANCES_BODY["instances"][1:2], "next_token": None}).encode(),
        ]

        def transport(request, timeout):
            return 200, pages.pop(0)

        result = vast.fetch_instances("vast-key-123", sender=transport)
        self.assertFalse(result["truncated"], "the last page said there is no more")


class ReplacementSearch(unittest.TestCase):
    """The opt-in replacement: search, pick, create, and the live check."""

    POLICY = {
        "enabled": True,
        "max_price": 0.50,
        "min_down_mbps": 200,
        "min_up_mbps": 100,
        "cuda_min": 13.0,
        "min_reliability": 0.95,
        "gpu_names": ["RTX 5090", "RTX 4090"],
    }

    @staticmethod
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

    @staticmethod
    def _live(contract: int = 777) -> dict:
        return {
            "id": contract,
            "public_ipaddr": "203.0.113.9",
            "ports": {"8188/tcp": [{"HostPort": "40111"}]},
            "gpu_name": "RTX 4090",
            "actual_status": "running",
        }

    def test_the_query_carries_every_floor(self) -> None:
        query = vast.offer_query(
            {
                "max_price": 0.42,
                "min_down_mbps": 300,
                "min_up_mbps": 150,
                "cuda_min": 13.0,
                "min_reliability": 0.97,
                "gpu_names": ["RTX 5090"],
            }
        )
        self.assertEqual(query["dph_total"], {"lte": 0.42})
        self.assertEqual(query["inet_down"], {"gte": 300})
        self.assertEqual(query["inet_up"], {"gte": 150})
        self.assertEqual(query["cuda_max_good"], {"gte": 13.0})
        self.assertEqual(query["gpu_ram"], {"gte": 24000})
        self.assertEqual(query["gpu_name"], {"in": ["RTX 5090"]})
        self.assertEqual(query["reliability2"], {"gte": 0.97})
        self.assertEqual(query["type"], "on-demand")
        self.assertEqual(query["order"], [["dlperf_per_dphtotal", "desc"]])
        self.assertEqual(query["limit"], vast.OFFER_QUERY_LIMIT)

    def test_an_absent_gpu_list_queries_the_defaults_not_any_gpu(self) -> None:
        """The measured unfiltered search rents a Tesla P40 at $0.108/hr."""
        query = vast.offer_query({})
        self.assertEqual(
            query["gpu_name"], {"in": ["RTX 5090", "RTX 4090"]}
        )
        self.assertEqual(query["reliability2"], {"gte": 0.95})

    def test_clean_replace_restores_the_default_gpu_list(self) -> None:
        default = ["RTX 5090", "RTX 4090"]
        for raw in (None, "", " , ", [], (), set()):
            with self.subTest(raw=raw):
                got = vast.clean_replace({"gpu_names": raw})["gpu_names"]
                self.assertEqual(got, default)
                self.assertIsNot(got, vast.DEFAULT_GPU_NAMES)

    def test_a_gpu_list_keeps_order_dedupes_and_canonicalizes(self) -> None:
        got = vast.clean_replace(
            {"gpu_names": ["rtx 5090", "A100 pcie", "RTX 5090", " RTX 4090 "]}
        )["gpu_names"]
        self.assertEqual(got, ["RTX 5090", "A100 PCIE", "RTX 4090"])

    def test_the_reliability_floor_is_kept_only_in_range(self) -> None:
        self.assertEqual(
            vast.clean_replace({"min_reliability": 0.90})["min_reliability"], 0.90
        )
        for raw in (-0.1, 1.1, "nope"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    vast.clean_replace({"min_reliability": raw})["min_reliability"],
                    0.95,
                )

    def test_a_gpu_outside_the_list_is_refused(self) -> None:
        p40 = self._offer(
            1, gpu_name="Tesla P40", gpu_ram=24576, dph_total=0.108
        )
        self.assertFalse(vast.offer_meets(p40, self.POLICY), "the reported bug")
        only_5090 = {**self.POLICY, "gpu_names": ["RTX 5090"]}
        self.assertFalse(vast.offer_meets(self._offer(2), only_5090))
        self.assertTrue(vast.offer_meets(self._offer(3, gpu_name="RTX 5090"), only_5090))

    def test_reliability_below_the_floor_or_missing_is_refused(self) -> None:
        self.assertFalse(
            vast.offer_meets(self._offer(1, reliability2=0.94), self.POLICY)
        )
        missing = self._offer(2)
        missing.pop("reliability2")
        self.assertFalse(
            vast.offer_meets(missing, self.POLICY),
            "a host that cannot state its reliability fails closed",
        )
        self.assertTrue(vast.offer_meets(self._offer(3, reliability2=0.95), self.POLICY))

    def test_the_highest_value_offer_that_clears_every_floor_wins(self) -> None:
        offers = [
            self._offer(1, dph_total=0.40),
            self._offer(2, dph_total=0.30, inet_up=50),
            self._offer(3, dph_total=0.35, cuda_max_good=12.4),
            self._offer(4, dph_total=0.45),
        ]
        picked = vast.pick_offer(offers, self.POLICY)
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(
            picked["id"], 1, "value ties break by price, and the cheap ones fail a floor"
        )

    def test_the_pick_is_value_not_the_cheapest_price(self) -> None:
        cheap = self._offer(1, dph_total=0.20, dlperf_per_dphtotal=200.0)
        value = self._offer(2, dph_total=0.40, dlperf_per_dphtotal=500.0)
        picked = vast.pick_offer([cheap, value], self.POLICY)
        self.assertEqual(picked["id"], 2, "a 500 Perf/$ card buys more images")
        self.assertGreater(vast.offer_value(value), vast.offer_value(cheap))

    def test_value_outranks_price_across_gpu_tiers(self) -> None:
        """5090 at $0.60/199 perf (331/$) before 4090 at $0.30/97 perf (323/$)."""
        fast = self._offer(
            1,
            gpu_name="RTX 5090",
            dph_total=0.60,
            dlperf=199,
            dlperf_per_dphtotal=None,
        )
        cheap = self._offer(
            2,
            gpu_name="RTX 4090",
            dph_total=0.30,
            dlperf=97,
            dlperf_per_dphtotal=None,
        )
        ranked = vast.matching_offers(
            [cheap, fast], {**self.POLICY, "max_price": 0.70}
        )
        self.assertEqual([offer["id"] for offer in ranked], [1, 2])

    def test_within_one_gpu_tier_the_higher_value_offer_comes_first(self) -> None:
        good = self._offer(1, dlperf_per_dphtotal=300.0)
        better = self._offer(2, dph_total=0.45, dlperf_per_dphtotal=400.0)
        ranked = vast.matching_offers([good, better], self.POLICY)
        self.assertEqual([offer["id"] for offer in ranked], [2, 1])

    def test_the_gpu_preference_breaks_an_equal_value_tie(self) -> None:
        a4090 = self._offer(1, gpu_name="RTX 4090", dph_total=0.30, dlperf_per_dphtotal=300.0)
        a5090 = self._offer(2, gpu_name="RTX 5090", dph_total=0.60, dlperf_per_dphtotal=300.0)
        ranked = vast.matching_offers(
            [a4090, a5090], {**self.POLICY, "max_price": 0.70}
        )
        self.assertEqual([offer["id"] for offer in ranked], [2, 1])

    def test_the_offer_cells_match_the_contracts_formats(self) -> None:
        offer = self._offer(
            55818626,
            gpu_name="RTX 5090",
            dph_total=0.402,
            dlperf=199.198,
            dlperf_per_dphtotal=494.772,
            gpu_ram=24576,
            disk_space=338,
            cuda_max_good=13.0,
            inet_down=868,
            inet_up=722,
            reliability2=0.96,
            geolocation="Romania, RO",
        )
        self.assertEqual(
            vast.offer_cells(offer),
            {
                "gpu": "RTX 5090",
                "price": "$0.402",
                "perf": "199",
                "value": "495",
                "vram": "24",
                "disk": "338",
                "cuda": "13.0",
                "down": "868",
                "up": "722",
                "reliability": "0.960",
                "location": "Romania, RO",
                "offer": "55818626",
            },
        )
        missing = vast.offer_cells({"id": 7})
        self.assertEqual(missing["gpu"], "")
        self.assertEqual(missing["price"], "")
        self.assertEqual(missing["value"], "")
        self.assertEqual(missing["location"], "unknown")
        self.assertEqual(missing["offer"], "7")

    def test_a_manual_rent_is_one_put_to_the_chosen_offer(self) -> None:
        puts: list[str] = []
        live: list[dict] = []

        def sender(request, timeout):
            if request.get_method() == "PUT":
                puts.append(request.full_url)
                live.append(self._live(777))
                return 200, json.dumps({"success": True, "new_contract": 777}).encode()
            if request.full_url.endswith("/instances/"):
                return 200, json.dumps({"instances": live}).encode()
            raise AssertionError(request.full_url)

        chosen = self._offer(42, gpu_name="RTX 5090")
        result = vast.rent_offer(
            "vast-key",
            chosen,
            image="docker.io/example/klein:tag",
            label="salad-studio-42",
            sender=sender,
            sleep=lambda _s: None,
            tries=2,
        )
        self.assertEqual(result["action"], "created")
        self.assertEqual(result["contract"], 777)
        self.assertEqual(puts, ["https://console.vast.ai/api/v0/asks/42/"])
        self.assertEqual(result["row"]["label"], "salad-studio-42")
        self.assertEqual(result["row"]["image"], "docker.io/example/klein:tag")

    def test_an_unmapped_rent_is_created_with_no_row(self) -> None:
        def sender(request, timeout):
            if request.get_method() == "PUT":
                return 200, json.dumps({"success": True, "new_contract": 777}).encode()
            return 200, json.dumps({"instances": []}).encode()

        result = vast.rent_offer(
            "vast-key",
            self._offer(42),
            image="docker.io/example/klein:tag",
            sender=sender,
            sleep=lambda _s: None,
            tries=1,
        )
        self.assertEqual(result["action"], "created")
        self.assertIsNone(result["row"])
        self.assertIn("not mapped", result["message"])

    def test_a_refused_rent_is_an_error_with_no_second_put(self) -> None:
        asked: list[str] = []

        def sender(request, timeout):
            asked.append(request.full_url)
            return 410, json.dumps(
                {"success": False, "error": "no_such_ask", "msg": "taken"}
            ).encode()

        result = vast.rent_offer(
            "vast-key", self._offer(42), image="img", sender=sender
        )
        self.assertEqual(result["action"], "error")
        self.assertEqual(len(asked), 1, "a manual rent must never fall through")

    def test_a_rent_without_an_offer_id_is_refused(self) -> None:
        result = vast.rent_offer("vast-key", {"gpu_name": "RTX 5090"}, image="img")
        self.assertEqual(result["action"], "error")
        self.assertIn("no id", result["message"])

    def test_the_new_policy_fields_round_trip_through_the_document(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "studio-vast.json"
            doc = vast.empty_doc()
            doc["replace"] = {
                **self.POLICY,
                "min_reliability": 0.97,
                "gpu_names": ["RTX A6000", "rtx 5090"],
            }
            vast.save_doc(doc, path)
            loaded = vast.load_doc(path)
        self.assertEqual(loaded["replace"]["min_reliability"], 0.97)
        self.assertEqual(
            loaded["replace"]["gpu_names"], ["RTX A6000", "RTX 5090"]
        )

    def test_no_offer_meets_the_floors(self) -> None:
        self.assertIsNone(
            vast.pick_offer([self._offer(1, dph_total=0.90)], self.POLICY)
        )
        self.assertIsNone(vast.pick_offer([], self.POLICY))

    def test_a_create_is_a_put_with_the_image_disk_and_env(self) -> None:
        seen: dict = {}

        def sender(request, timeout):
            seen["method"] = request.get_method()
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data)
            return 200, json.dumps({"success": True, "new_contract": 777}).encode()

        result = vast.create_instance(
            "vast-key",
            123,
            image="docker.io/example/klein:tag",
            env="-p 8188:8188 -e HF_TOKEN=hf_x",
            label="salad-studio-klein",
            sender=sender,
        )
        self.assertEqual(result["contract"], 777)
        self.assertEqual(seen["method"], "PUT")
        self.assertEqual(seen["url"], "https://console.vast.ai/api/v0/asks/123/")
        self.assertEqual(seen["body"]["image"], "docker.io/example/klein:tag")
        self.assertEqual(seen["body"]["disk"], 100)
        self.assertEqual(seen["body"]["runtype"], "args")
        self.assertEqual(seen["body"]["env"], "-p 8188:8188 -e HF_TOKEN=hf_x")
        self.assertEqual(seen["body"]["label"], "salad-studio-klein")

    def test_the_env_carries_the_render_tokens_but_not_the_vast_key(self) -> None:
        env = vast.replacement_env(hf_token="hf_secret", civitai_token="civ_secret")
        self.assertIn("-p 3000:3000", env)
        self.assertIn("-p 8188:8188", env)
        self.assertIn("-e HF_TOKEN=hf_secret", env)
        self.assertIn("-e CIVITAI_API_TOKEN=civ_secret", env)
        self.assertNotIn("vast", env.lower())

    def test_an_alive_instance_is_not_created_again(self) -> None:
        def sender(request, timeout):
            self.assertTrue(request.full_url.endswith("/instances/"))
            return 200, json.dumps({"instances": [self._live()]}).encode()

        result = vast.replace_destroyed(
            key="vast-key",
            endpoint="http://203.0.113.9:40111",
            image="docker.io/example/klein:tag",
            settings=self.POLICY,
            sender=sender,
        )
        self.assertEqual(result["action"], "alive")
        self.assertEqual(result["row"]["endpoint"], "http://203.0.113.9:40111")

    def test_replacement_off_only_reports_the_instance_is_gone(self) -> None:
        def sender(request, timeout):
            return 200, json.dumps({"instances": []}).encode()

        result = vast.replace_destroyed(
            key="vast-key",
            endpoint="http://203.0.113.9:40111",
            image="docker.io/example/klein:tag",
            settings={**self.POLICY, "enabled": False},
            sender=sender,
        )
        self.assertEqual(result["action"], "missing")

    def test_a_gone_instance_is_replaced_by_the_best_value_offer(self) -> None:
        calls: list[tuple[str, str]] = []
        live: list[dict] = []

        def sender(request, timeout):
            calls.append((request.get_method(), request.full_url))
            if request.full_url.endswith("/instances/"):
                return 200, json.dumps({"instances": live}).encode()
            if request.full_url.endswith("/bundles/"):
                body = json.loads(request.data)
                self.assertEqual(body["dph_total"], {"lte": 0.50})
                return 200, json.dumps({"offers": [self._offer(4)]}).encode()
            if "/asks/" in request.full_url:
                live.append(self._live())
                return 200, json.dumps({"success": True, "new_contract": 777}).encode()
            raise AssertionError(request.full_url)

        result = vast.replace_destroyed(
            key="vast-key",
            endpoint="http://198.51.100.7:40000",
            image="docker.io/example/klein:tag",
            settings=self.POLICY,
            label="salad-studio-klein",
            sender=sender,
            sleep=lambda _s: None,
            tries=2,
        )
        self.assertEqual(result["action"], "created")
        self.assertEqual(result["contract"], 777)
        self.assertEqual(result["row"]["endpoint"], "http://203.0.113.9:40111")
        self.assertEqual(result["row"]["label"], "salad-studio-klein")
        self.assertTrue(any(method == "PUT" for method, _url in calls))
        self.assertTrue(any(url.endswith("/bundles/") for _m, url in calls))

    def test_no_offer_creates_nothing(self) -> None:
        calls: list[str] = []

        def sender(request, timeout):
            calls.append(request.full_url)
            if request.full_url.endswith("/instances/"):
                return 200, json.dumps({"instances": []}).encode()
            if request.full_url.endswith("/bundles/"):
                return 200, json.dumps({"offers": [self._offer(1, dph_total=9.0)]}).encode()
            raise AssertionError("no create may run")

        result = vast.replace_destroyed(
            key="vast-key",
            endpoint="http://198.51.100.7:40000",
            image="docker.io/example/klein:tag",
            settings=self.POLICY,
            sender=sender,
            sleep=lambda _s: None,
            tries=1,
        )
        self.assertEqual(result["action"], "no_offer")
        self.assertFalse(any("/asks/" in url for url in calls))

    def test_a_stopped_instance_is_not_replaced_by_a_duplicate(self) -> None:
        stopped = {"id": 5, "actual_status": "stopped", "public_ipaddr": None}

        def sender(request, timeout):
            return 200, json.dumps({"instances": [stopped]}).encode()

        result = vast.replace_destroyed(
            key="vast-key",
            endpoint="http://203.0.113.9:40111",
            instance_id=5,
            image="docker.io/example/klein:tag",
            settings=self.POLICY,
            sender=sender,
        )
        self.assertEqual(result["action"], "not_ready")
        self.assertIn("is stopped, not destroyed", result["message"])

    def test_save_doc_never_persists_a_pending_block(self) -> None:
        """The creating row is the durable record; ``pending`` is written empty."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "studio-vast.json"
            doc = vast.empty_doc()
            doc["pending"] = {
                "contract": 777,
                "label": "salad-studio-klein",
                "image": "docker.io/example/klein:tag",
            }
            vast.save_doc(doc, path)
            stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(stored["pending"], {})
        self.assertEqual(vast.load_doc(path)["pending"], {})

    def test_a_refused_offer_falls_through_to_the_next_best_value(self) -> None:
        """The create endpoint can refuse an offer the search still lists."""
        live: list[dict] = []
        asked: list[str] = []

        def sender(request, timeout):
            if request.full_url.endswith("/instances/"):
                return 200, json.dumps({"instances": live}).encode()
            if request.full_url.endswith("/bundles/"):
                return 200, json.dumps(
                    {"offers": [self._offer(1, dph_total=0.30), self._offer(2, dph_total=0.40)]}
                ).encode()
            asked.append(request.full_url)
            if request.full_url.endswith("/asks/1/"):
                return 410, json.dumps(
                    {"success": False, "error": "no_such_ask", "msg": "taken"}
                ).encode()
            live.append(self._live(888))
            return 200, json.dumps({"success": True, "new_contract": 888}).encode()

        result = vast.replace_destroyed(
            key="vast-key",
            endpoint="http://198.51.100.7:40000",
            image="docker.io/example/klein:tag",
            settings=self.POLICY,
            sender=sender,
            sleep=lambda _s: None,
            tries=2,
        )
        self.assertEqual(result["action"], "created")
        self.assertEqual(result["contract"], 888)
        self.assertEqual([url.rsplit("/", 2)[-2] for url in asked], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
