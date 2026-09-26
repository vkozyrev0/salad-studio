"""The metadata document drives routing and the AI instruction.

Each test writes a document to a temp file, loads it with the shipped loader,
and observes the effect on the shipped code. Nothing here reads the real
``~/.config/salad/studio-metadata.json``.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import profiles  # noqa: E402
import studio_meta as meta  # noqa: E402
from salad_studio import ai_helper as ai  # noqa: E402

SNOFS_UNET = "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors"
KLEIN_UNET = "flux-2-klein-base-9b-fp8.safetensors"
OTHER_GATEWAY = "https://other-group.example.salad.cloud"
SENTINEL = "SENTINEL_HINT_FROM_THE_DOCUMENT"


def _document(
    *,
    snofs_group: str = "klein5090",
    snofs_gateway: str = "",
    klein_group: str = "klein",
    hint: str = SENTINEL,
) -> dict:
    return {
        "version": 1,
        "routing": {
            "families": {
                "snofs": {
                    "group": snofs_group,
                    "gateway": snofs_gateway,
                    "image": "image-snofs",
                    "unets": [SNOFS_UNET],
                    "markers": ["snofs"],
                },
                "klein": {
                    "group": klein_group,
                    "image": "image-klein",
                    "unets": [KLEIN_UNET, "flux-2-klein-9b-fp8.safetensors"],
                    "markers": ["klein"],
                },
            }
        },
        "prompt": {
            "role": "You are the test prompt engineer.",
            "task": "Rewrite the two adjusted prompts:",
            "rules": [hint, "THE REPORTED ISSUE IS THE HIGHEST PRIORITY."],
            "reply_contract": 'Reply with ONLY {"issue": "", "positive": "", "negative": ""}.',
        },
    }


class DocumentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    def _write(self, doc: dict, name: str = "meta.json") -> Path:
        path = self.tmp / name
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_a_missing_document_is_empty_and_says_so(self) -> None:
        doc = meta.load(path=self.tmp / "absent.json")
        self.assertEqual(meta.families(doc), {})
        self.assertEqual(meta.family_for_unet(KLEIN_UNET, doc), "")
        self.assertIn("cannot read", doc["error"])

    def test_a_broken_document_reports_why_instead_of_raising(self) -> None:
        path = self.tmp / "meta.json"
        path.write_text("{not json", encoding="utf-8")
        doc = meta.load(path=path)
        self.assertIn("not JSON", doc["error"])
        self.assertEqual(meta.group_for_family("klein", doc), "")

    def test_a_hand_edited_document_is_coerced(self) -> None:
        path = self._write(
            {
                "routing": {"families": {"snofs": {"group": 7, "unets": SNOFS_UNET}}},
                "prompt": {"rules": "one rule"},
            }
        )
        doc = meta.load(path=path)
        self.assertEqual(meta.group_for_family("snofs", doc), "7")
        self.assertEqual(meta.family_for_unet(SNOFS_UNET, doc), "snofs")
        self.assertIn("one rule", meta.instruction(doc))

    def test_the_shipped_document_names_both_families(self) -> None:
        doc = meta.load()
        self.assertEqual(meta.family_for_unet(SNOFS_UNET, doc), "snofs")
        self.assertEqual(meta.family_for_unet(KLEIN_UNET, doc), "klein")
        self.assertEqual(meta.family_for_unet("flux-2-klein-9b-fp8.safetensors", doc), "klein")
        self.assertEqual(meta.group_for_family("snofs", doc), "klein5090")
        self.assertEqual(meta.group_for_family("klein", doc), "klein")
        self.assertEqual(doc["error"], "")

    def test_the_earlier_marker_wins(self) -> None:
        """The SNOFS cut is named snofs…_distilledV12KleinFp8 and matches both."""
        doc = meta.load()
        self.assertEqual(meta.family_for_unet("snofs_another_cut.safetensors", doc), "snofs")
        self.assertEqual(meta.family_for_unet("mystery_model.safetensors", doc), "")


class RoutingFromMetadataTest(unittest.TestCase):
    """The document, not the code, says where a graph goes."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.allp = {
            "klein": profiles.default_profile("klein"),
            "klein5090": profiles.default_profile("klein5090"),
        }
        self.assertNotEqual(
            self.allp["klein"].gateway,
            self.allp["klein5090"].gateway,
            "the two built-in groups must point at different gateways",
        )

    def _write(self, doc: dict) -> Path:
        path = self.tmp / "meta.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    @staticmethod
    def _graph(unet: str) -> dict:
        return {"prompt": {"70": {"class_type": "UNETLoader", "inputs": {"unet_name": unet}}}}

    def test_the_documents_group_decides_where_a_graph_goes(self) -> None:
        doc = meta.load(path=self._write(_document(snofs_group="klein")))
        got = profiles.route_payload(self._graph(SNOFS_UNET), self.allp, meta=doc)
        assert got is not None
        self.assertEqual(got[0], "klein")
        self.assertEqual(got[1].gateway, self.allp["klein"].gateway)

    def test_editing_only_the_document_changes_the_route(self) -> None:
        """Same graph, same profiles, same code: the file decides."""
        first = meta.load(path=self._write(_document(snofs_group="klein5090")))
        before = profiles.route_payload(self._graph(SNOFS_UNET), self.allp, meta=first)
        second = meta.load(path=self._write(_document(snofs_group="klein")))
        after = profiles.route_payload(self._graph(SNOFS_UNET), self.allp, meta=second)
        assert before is not None and after is not None
        self.assertEqual(before[0], "klein5090")
        self.assertEqual(after[0], "klein")
        self.assertEqual(before[1].gateway, self.allp["klein5090"].gateway)
        self.assertEqual(after[1].gateway, self.allp["klein"].gateway)

    def test_the_document_can_name_the_gateway_itself(self) -> None:
        doc = meta.load(
            path=self._write(_document(snofs_group="klein5090", snofs_gateway=OTHER_GATEWAY))
        )
        got = profiles.route_payload(self._graph(SNOFS_UNET), self.allp, meta=doc)
        assert got is not None
        self.assertEqual(got[0], "klein5090")
        self.assertEqual(got[1].gateway, OTHER_GATEWAY)

    def test_a_checkpoint_with_no_entry_is_refused_with_a_reason(self) -> None:
        doc = meta.load(path=self._write(_document()))
        route, refusal = profiles.plan_route(
            self._graph("mystery_model.safetensors"),
            self.allp["klein"],
            self.allp,
            meta=doc,
        )
        self.assertIsNone(route)
        self.assertIn("mystery_model.safetensors", refusal)
        self.assertIn("no entry in the routing metadata", refusal)
        self.assertIsNone(
            profiles.route_payload(self._graph("mystery_model.safetensors"), self.allp, meta=doc)
        )

    def test_a_family_whose_group_is_not_saved_is_refused(self) -> None:
        doc = meta.load(path=self._write(_document(snofs_group="a_group_we_never_saved")))
        route, refusal = profiles.plan_route(
            self._graph(SNOFS_UNET), self.allp["klein"], self.allp, meta=doc
        )
        self.assertIsNone(route)
        self.assertIn("a_group_we_never_saved", refusal)

    def test_a_matching_group_is_left_alone(self) -> None:
        doc = meta.load(path=self._write(_document()))
        route, refusal = profiles.plan_route(
            self._graph(SNOFS_UNET), self.allp["klein5090"], self.allp, meta=doc
        )
        self.assertIsNone(route)
        self.assertEqual(refusal, "")


class HintsFromMetadataTest(unittest.TestCase):
    """The AI layer's instruction comes out of the document."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    def _doc(self, hint: str) -> dict:
        path = self.tmp / "meta.json"
        path.write_text(json.dumps(_document(hint=hint)), encoding="utf-8")
        return meta.load(path=path)

    def test_the_instruction_is_assembled_from_the_document(self) -> None:
        doc = self._doc(SENTINEL)
        text = ai.system_instruction(doc)
        self.assertIn(SENTINEL, text)
        self.assertIn("You are the test prompt engineer.", text)
        self.assertIn("- THE REPORTED ISSUE IS THE HIGHEST PRIORITY.", text)

    def test_editing_the_document_changes_the_payload_that_is_sent(self) -> None:
        """The real request body, built by the shipped transport call."""
        bodies: list[dict] = []

        def send(request, timeout):
            bodies.append(json.loads(request.data.decode("utf-8")))
            return 200, json.dumps(
                {
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"positive": "P", "negative": "N"}',
                            },
                        }
                    ]
                }
            ).encode()

        for hint in (SENTINEL, "A_DIFFERENT_SENTINEL"):
            with mock.patch.object(ai, "_http_send", send):
                ai.help_with_prompts(
                    "ds-test-key-abcdef123456",
                    editor_positive="a plate",
                    meta=self._doc(hint),
                )
        self.assertEqual(len(bodies), 2)
        first, second = (body["messages"][0]["content"] for body in bodies)
        self.assertIn(SENTINEL, first)
        self.assertNotIn("A_DIFFERENT_SENTINEL", first)
        self.assertIn("A_DIFFERENT_SENTINEL", second)
        self.assertNotEqual(first, second)

    def test_the_hint_text_is_not_a_literal_in_the_ai_module(self) -> None:
        """Criterion: the rules live in the document, not in ai_helper."""
        source = Path(ai.__file__).read_text(encoding="utf-8")
        for phrase in ("Klein anatomy rules", "Name the position", "clinical anatomical"):
            self.assertNotIn(phrase, source)
        self.assertFalse(hasattr(ai, "SYSTEM_PROMPT"))


if __name__ == "__main__":
    unittest.main()
