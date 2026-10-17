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
PKG = HERE.parent / "salad_studio"
for _p in (PKG, HERE.parent):
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
    snofs_unets: list[str] | None = None,
    hint: str = SENTINEL,
) -> dict:
    return {
        "version": 1,
        "routing": {
            "families": {
                "snofs": {
                    "image": "image-snofs",
                    "unets": list(snofs_unets if snofs_unets is not None else [SNOFS_UNET]),
                    "markers": ["snofs"],
                },
                "klein": {
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
        self.assertEqual(meta.entry_for_family("klein", doc)["unets"], [])

    def test_a_hand_edited_document_is_coerced(self) -> None:
        path = self._write(
            {
                "routing": {"families": {"snofs": {"unets": SNOFS_UNET, "markers": None}}},
                "prompt": {"rules": "one rule"},
            }
        )
        doc = meta.load(path=path)
        self.assertEqual(meta.entry_for_family("snofs", doc)["unets"], [SNOFS_UNET])
        self.assertEqual(meta.family_for_unet(SNOFS_UNET, doc), "snofs")
        self.assertIn("one rule", meta.instruction(doc))

    def test_the_shipped_document_names_both_families(self) -> None:
        doc = meta.load()
        self.assertEqual(meta.family_for_unet(SNOFS_UNET, doc), "snofs")
        self.assertEqual(meta.family_for_unet(KLEIN_UNET, doc), "klein")
        self.assertEqual(meta.family_for_unet("flux-2-klein-9b-fp8.safetensors", doc), "klein")
        self.assertEqual(
            meta.entry_for_family("snofs", doc)["unets"], [SNOFS_UNET], "the seed list"
        )
        self.assertIn("prefetch6-snofs", meta.image_for_family("snofs", doc))
        self.assertEqual(doc["error"], "")

    def test_the_earlier_marker_wins(self) -> None:
        """The SNOFS cut is named snofs…_distilledV12KleinFp8 and matches both."""
        doc = meta.load()
        self.assertEqual(meta.family_for_unet("snofs_another_cut.safetensors", doc), "snofs")
        self.assertEqual(meta.family_for_unet("mystery_model.safetensors", doc), "")


class FamiliesFromMetadataTest(unittest.TestCase):
    """The document says what a family is and seeds a new profile's list.

    Which profile serves which checkpoint is the profile's own list, tested in
    test_profiles; this is the half the document still owns.
    """

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    def _write(self, doc: dict) -> Path:
        path = self.tmp / "meta.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_a_new_profile_is_seeded_from_the_document(self) -> None:
        doc = meta.load(path=self._write(_document()))
        self.assertEqual(profiles.seed_checkpoints("klein5090", doc), [SNOFS_UNET])
        self.assertEqual(
            profiles.seed_checkpoints("klein", doc),
            [KLEIN_UNET, "flux-2-klein-9b-fp8.safetensors"],
        )

    def test_editing_only_the_document_changes_the_seed(self) -> None:
        """Same code, same profile name: the file decides what a new one serves."""
        before = meta.load(path=self._write(_document(snofs_unets=[SNOFS_UNET])))
        after = meta.load(
            path=self._write(_document(snofs_unets=[SNOFS_UNET, "snofs_second_cut.safetensors"]))
        )
        self.assertEqual(profiles.seed_checkpoints("klein5090", before), [SNOFS_UNET])
        self.assertEqual(
            profiles.seed_checkpoints("klein5090", after),
            [SNOFS_UNET, "snofs_second_cut.safetensors"],
        )

    def test_an_unlisted_checkpoint_is_its_own_family(self) -> None:
        """So a checkpoint that does not exist yet is routable without a doc edit."""
        doc = meta.load(path=self._write(_document()))
        self.assertEqual(meta.family_for_unet("brand_new.safetensors", doc), "")
        self.assertEqual(
            profiles.checkpoint_family("brand_new.safetensors", doc), "brand_new.safetensors"
        )
        self.assertEqual(
            profiles.checkpoint_family("snofs_another_cut.safetensors", doc), "snofs"
        )

    def test_a_family_whose_seed_is_empty_starts_a_profile_with_no_checkpoints(self) -> None:
        doc = meta.load(path=self._write(_document(snofs_unets=[])))
        self.assertEqual(profiles.seed_checkpoints("klein5090", doc), [])
        # ... and such a profile is then routable for nothing until one is added.
        empty = profiles.SaladProfile(name="klein5090", gateway="https://empty.example/")
        route, refusal = profiles.plan_route(self._graph(SNOFS_UNET), empty, {"klein5090": empty})
        self.assertIsNone(route)
        self.assertIn("No profile lists", refusal)

    @staticmethod
    def _graph(unet: str) -> dict:
        return {"prompt": {"70": {"class_type": "UNETLoader", "inputs": {"unet_name": unet}}}}


class PolicyImageFromMetadataTest(unittest.TestCase):
    """The document's per-family image is where a config's Salad image starts.

    The config stores its own once it has one; until then, and as the fallback
    when neither it nor a live group supplies one, this is the image it has.
    """

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    def _write(self, doc: dict) -> Path:
        path = self.tmp / "meta.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def _doc(self) -> dict:
        return meta.load(path=self._write(_document()))

    def test_a_new_profile_starts_with_its_familys_image(self) -> None:
        doc = self._doc()
        klein = profiles.default_profile("klein", doc)
        snofs = profiles.default_profile("klein5090", doc)
        self.assertEqual(klein.policy, {"image": meta.image_for_family("klein", doc)})
        self.assertEqual(snofs.policy, {"image": meta.image_for_family("snofs", doc)})
        self.assertNotEqual(klein.policy["image"], snofs.policy["image"])
        self.assertEqual(
            profiles.policy_image_for(klein, doc), meta.image_for_family("klein", doc)
        )
        self.assertEqual(
            profiles.seeded_policy(klein, doc),
            {"image": meta.image_for_family("klein", doc)},
        )

    def test_editing_only_the_document_changes_the_image_a_config_starts_from(self) -> None:
        """Same code, same family: the file decides the image."""
        profile = profiles.SaladProfile(name="klein", checkpoints=[KLEIN_UNET])
        before = self._doc()
        after = meta.load(
            path=self._write(
                {
                    "routing": {
                        "families": {
                            "klein": {
                                "image": "docker.io/other/klein:9",
                                "unets": [KLEIN_UNET],
                                "markers": ["klein"],
                            }
                        }
                    }
                }
            )
        )
        self.assertNotEqual(
            profiles.policy_image_for(profile, before),
            profiles.policy_image_for(profile, after),
        )
        self.assertEqual(
            profiles.policy_image_for(profile, after),
            meta.image_for_family("klein", after),
        )
        self.assertEqual(
            profiles.seeded_policy(profile, after),
            {"image": meta.image_for_family("klein", after)},
        )

    def test_a_family_the_document_gives_no_image_is_imageless(self) -> None:
        doc = meta.load(
            path=self._write(
                {
                    "routing": {
                        "families": {
                            "klein": {"unets": [KLEIN_UNET], "markers": ["klein"]}
                        }
                    }
                }
            )
        )
        profile = profiles.SaladProfile(name="klein", checkpoints=[KLEIN_UNET])
        self.assertEqual(meta.image_for_family("klein", doc), "")
        self.assertEqual(profiles.policy_image_for(profile, doc), "")
        self.assertEqual(profiles.seeded_policy(profile, doc), {})
        self.assertEqual(profiles.default_profile("klein", doc).policy, {})

    def test_a_profile_with_no_checkpoints_has_no_family_to_take_an_image_from(self) -> None:
        doc = self._doc()
        empty = profiles.SaladProfile(name="empty")
        self.assertEqual(profiles.policy_image_for(empty, doc), "")
        self.assertEqual(profiles.seeded_policy(empty, doc), {})
        # ... while a profile that does list one has the document's image.
        self.assertTrue(
            profiles.policy_image_for(
                profiles.SaladProfile(name="klein", checkpoints=[KLEIN_UNET]), doc
            )
        )


class ProbeSettingsFromMetadataTest(unittest.TestCase):
    """The document's per-family probes are the settings a container runs.

    They are what a config with nothing stored starts from, and what the Config
    page falls back to when neither its stored policy nor a live group read
    answers, so a hand-edited document must not smuggle a key into a policy.
    """

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    def _write(self, payload: dict) -> Path:
        path = self.tmp / "meta.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_the_shipped_document_documents_both_probes_for_both_families(self) -> None:
        doc = meta.load()
        for family in ("snofs", "klein"):
            with self.subTest(family=family):
                documented = meta.families(doc)[family]
                got = meta.probe_settings_for_family(family, doc)
                self.assertEqual(sorted(got), [meta.READINESS, meta.STARTUP])
                for kind, key in (
                    (meta.STARTUP, meta.STARTUP_PROBE),
                    (meta.READINESS, meta.READINESS_PROBE),
                ):
                    self.assertEqual(sorted(got[kind]), sorted(meta.PROBE_KEYS))
                    self.assertEqual(got[kind], documented[key])

    def test_the_shipped_document_states_the_probes_the_groups_run(self) -> None:
        """The values the live groups are configured with, written down."""
        doc = meta.load()
        for family in ("snofs", "klein"):
            with self.subTest(family=family):
                got = meta.probe_settings_for_family(family, doc)
                self.assertEqual(
                    got[meta.STARTUP],
                    {
                        "path": "/health",
                        "port": 3000,
                        "initial_delay_seconds": 1200,
                        "period_seconds": 120,
                        "timeout_seconds": 10,
                        "failure_threshold": 20,
                    },
                )
                self.assertEqual(
                    got[meta.READINESS],
                    {
                        "path": "/ready",
                        "port": 3000,
                        "initial_delay_seconds": 0,
                        "period_seconds": 10,
                        "timeout_seconds": 5,
                        "failure_threshold": 20,
                    },
                )

    def test_a_family_with_no_documented_probes_comes_back_empty(self) -> None:
        doc = meta.load(path=self._write(_document()))
        self.assertEqual(meta.probe_settings_for_family("klein", doc), {})
        self.assertEqual(meta.probe_settings_for_family("nobody", doc), {})
        self.assertEqual(
            meta.probe_settings_for_family("klein", {"routing": {"families": {}}}), {}
        )
        self.assertEqual(meta.probe_settings_for_family("klein", None), {})

    def test_a_stray_key_inside_a_probe_is_dropped(self) -> None:
        path = self._write(
            {
                "routing": {
                    "families": {
                        "klein": {
                            "unets": [KLEIN_UNET],
                            "markers": ["klein"],
                            "startup_probe": {
                                "path": "/health",
                                "port": 3000,
                                "initial_delay_seconds": 1200,
                                "period_seconds": 120,
                                "timeout_seconds": 10,
                                "failure_threshold": 20,
                                "retries_left": 9,
                            },
                        }
                    }
                }
            }
        )
        self.assertIn(
            "retries_left",
            path.read_text(encoding="utf-8"),
            "the hand edit must be in the file this test drives",
        )
        got = meta.probe_settings_for_family("klein", meta.load(path=path))
        self.assertEqual(sorted(got), [meta.STARTUP], "readiness is not documented")
        self.assertEqual(sorted(got[meta.STARTUP]), sorted(meta.PROBE_KEYS))
        self.assertEqual(got[meta.STARTUP]["port"], 3000)

    def test_a_broken_or_empty_document_comes_back_empty_not_raising(self) -> None:
        for broken in (
            "junk",
            [],
            7,
            {},
            {"routing": "nope"},
            {"routing": {"families": "nope"}},
        ):
            with self.subTest(doc=broken):
                self.assertEqual(meta.probe_settings_for_family("klein", broken), {})


class IdleTimeoutFromMetadataTest(unittest.TestCase):
    """The queue's idle timeout is the document's setting, with a safe default."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    def _doc(self, payload: dict) -> dict:
        path = self.tmp / "meta.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return meta.load(path=path)

    def test_the_shipped_document_says_one_hour(self) -> None:
        self.assertEqual(
            meta.idle_stop_seconds(meta.load()), meta.DEFAULT_IDLE_STOP_S
        )
        self.assertEqual(meta.DEFAULT_IDLE_STOP_S, 3600)

    def test_a_different_timeout_is_read_from_the_document(self) -> None:
        self.assertEqual(meta.idle_stop_seconds(self._doc({"queue": {"idle_stop_s": 45}})), 45)
        self.assertEqual(
            meta.idle_stop_seconds(self._doc({"queue": {"idle_stop_s": "120"}})), 120
        )

    def test_a_nonsense_timeout_falls_back_to_the_default(self) -> None:
        for payload in (
            {"queue": {"idle_stop_s": 0}},
            {"queue": {"idle_stop_s": -5}},
            {"queue": {"idle_stop_s": "soon"}},
            {"queue": {"idle_stop_s": None}},
            {"queue": {}},
            {"queue": "nope"},
            {},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    meta.idle_stop_seconds(self._doc(payload)),
                    meta.DEFAULT_IDLE_STOP_S,
                    "a typo must not stop a container the moment it goes quiet",
                )

    def test_a_broken_document_still_yields_the_default(self) -> None:
        path = self.tmp / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(
            meta.idle_stop_seconds(meta.load(path=path)), meta.DEFAULT_IDLE_STOP_S
        )


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
