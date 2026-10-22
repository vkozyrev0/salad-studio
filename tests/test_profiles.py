"""Tests for salad_studio.profiles. Never touch the real ~/.config file."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "salad_studio"
for _p in (PKG, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def setUpModule() -> None:
    """This module builds a window, so its queue must not touch the real ledger."""
    from tests import _stores

    _stores.keep_queue_ledger_off_the_user_store()


def tearDownModule() -> None:
    from tests import _stores

    _stores.restore_queue_ledger()

from profiles import (
    add_checkpoint,
    checkpoint_family,
    mixed_family_reason,
    payload_unets,
    plan_route,
    policy_image_for,
    profile_for_gateway,
    profiles_for_checkpoint,
    remove_checkpoint,
    same_gateway,
    seed_checkpoints,
    seeded_policy,
    serving_family,
    unet_family,
    DEFAULT_KEY_PATH,
    KLEIN_5090_GATEWAY,
    KLEIN_GATEWAY,
    PROFILES_PATH,
    SaladProfile,
    default_profile,
    delete,
    ensure_builtin_profiles,
    get_active,
    load_all,
    save_all,
    set_active,
    upsert,
)

import studio_meta
from request_json import UNET_SNOFS as SNOFS_UNET  # noqa: E402

EXPECTED_FIELDS = (
    "name",
    "gateway",
    "mode",
    "key_path",
    "graph",
    "width",
    "height",
    "steps",
    "cfg",
    "seed",
    "scheduler",
    "checkpoints",
    "use_loras",
    "selected_loras",
    "policy",
)


class ProfilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.path = Path(self._td.name) / "studio-profiles.json"

    def _sample(self, name: str = "klein", **kwargs) -> SaladProfile:
        data = dict(
            name=name,
            gateway="https://example.salad.cloud",
            key_path=str(Path(self._td.name) / "key"),
            graph="klein",
            width=1024,
            height=768,
            steps=12,
            use_loras=False,
            selected_loras=[],
        )
        data.update(kwargs)
        return SaladProfile(**data)

    def test_default_profile_field_names(self) -> None:
        names = tuple(f.name for f in fields(SaladProfile))
        self.assertEqual(names, EXPECTED_FIELDS)
        profile = default_profile()
        self.assertEqual(tuple(profile.__dataclass_fields__), EXPECTED_FIELDS)
        for field_name in EXPECTED_FIELDS:
            self.assertTrue(hasattr(profile, field_name), field_name)
        self.assertEqual(profile.name, "klein")
        self.assertEqual(profile.graph, "klein")
        self.assertEqual(profile.width, 1024)
        self.assertEqual(profile.height, 1024)
        self.assertEqual(profile.steps, 20)
        self.assertIs(profile.use_loras, True)
        self.assertEqual(
            profile.selected_loras,
            [
                "civitai:2334190@2625692",
                "civitai:545264@2763568",
            ],
        )
        self.assertEqual(profile.key_path, DEFAULT_KEY_PATH)
        self.assertIsInstance(profile.gateway, str)
        named = default_profile("studio")
        self.assertEqual(named.name, "studio")
        self.assertEqual(named.graph, "klein")
        self.assertEqual(profile.mode, "salad")

    def test_ensure_builtin_adds_klein5090_without_clobber(self) -> None:
        import profiles as pr

        gwdir = Path(self._td.name)
        old_k, old_5 = pr.GATEWAY_KLEIN_PATH, pr.GATEWAY_KLEIN_5090_PATH
        pr.GATEWAY_KLEIN_PATH = gwdir / "gateway-klein"
        pr.GATEWAY_KLEIN_5090_PATH = gwdir / "gateway-klein-5090"
        try:
            k5090 = default_profile("klein5090")
            self.assertEqual(k5090.name, "klein5090")
            self.assertEqual(k5090.gateway, KLEIN_5090_GATEWAY)
            self.assertEqual(k5090.graph, "klein")
            self.assertEqual(default_profile("klein").gateway, KLEIN_GATEWAY)
            upsert(
                self._sample("klein", gateway="https://custom.salad.cloud"),
                self.path,
            )
            got = ensure_builtin_profiles(self.path)
            self.assertIn("klein", got)
            self.assertIn("klein5090", got)
            self.assertEqual(got["klein"].gateway, "https://custom.salad.cloud")
            self.assertEqual(got["klein5090"].gateway, KLEIN_5090_GATEWAY)
            self.assertTrue(pr.GATEWAY_KLEIN_5090_PATH.is_file())
            self.assertIn(
                "beet-ginger",
                pr.GATEWAY_KLEIN_5090_PATH.read_text(encoding="utf-8"),
            )
            upsert(
                self._sample("klein5090", gateway="https://other.salad.cloud"),
                self.path,
            )
            again = ensure_builtin_profiles(self.path)
            self.assertEqual(again["klein5090"].gateway, "https://other.salad.cloud")
        finally:
            pr.GATEWAY_KLEIN_PATH = old_k
            pr.GATEWAY_KLEIN_5090_PATH = old_5

    def test_load_missing_file_is_empty(self) -> None:
        self.assertEqual(load_all(self.path), {})
        self.assertIsNone(get_active(self.path))
        self.assertFalse(self.path.exists())

    def test_upsert_load_roundtrip(self) -> None:
        first = self._sample("klein")
        stored = upsert(first, self.path)
        self.assertIn("klein", stored)
        loaded = load_all(self.path)
        self.assertEqual(set(loaded), {"klein"})
        got = loaded["klein"]
        self.assertEqual(got.name, "klein")
        self.assertEqual(got.gateway, first.gateway)
        self.assertEqual(got.key_path, first.key_path)
        self.assertEqual(got.graph, "klein")
        self.assertEqual(got.mode, "salad")
        self.assertEqual(got.width, 1024)
        self.assertEqual(got.height, 768)
        self.assertEqual(got.steps, 12)
        self.assertIs(got.use_loras, False)
        self.assertEqual(got.selected_loras, [])
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIn("profiles", doc)
        self.assertIn("active", doc)
        self.assertIn("klein", doc["profiles"])
        self.assertEqual(set(doc["profiles"]["klein"]), set(EXPECTED_FIELDS))

    def test_upsert_updates_and_adds(self) -> None:
        upsert(self._sample("klein", steps=8), self.path)
        upsert(self._sample("klein", steps=30, use_loras=True), self.path)
        upsert(self._sample("flux1", graph="flux1", width=768), self.path)
        loaded = load_all(self.path)
        self.assertEqual(set(loaded), {"klein", "flux1"})
        self.assertEqual(loaded["klein"].steps, 30)
        self.assertIs(loaded["klein"].use_loras, True)
        self.assertEqual(
            loaded["klein"].selected_loras,
            [
                "civitai:2334190@2625692",
                "civitai:545264@2763568",
            ],
        )
        self.assertEqual(loaded["flux1"].graph, "flux1")
        self.assertEqual(loaded["flux1"].width, 768)

    def test_delete(self) -> None:
        upsert(self._sample("klein"), self.path)
        upsert(self._sample("flux1", graph="flux1"), self.path)
        remaining = delete("klein", self.path)
        self.assertEqual(set(remaining), {"flux1"})
        self.assertEqual(set(load_all(self.path)), {"flux1"})
        self.assertEqual(delete("missing", self.path).keys(), remaining.keys())

    def test_active(self) -> None:
        self.assertIsNone(get_active(self.path))
        upsert(self._sample("klein"), self.path)
        upsert(self._sample("flux1", graph="flux1"), self.path)
        set_active("klein", self.path)
        self.assertEqual(get_active(self.path), "klein")
        # save_all must preserve the active name
        save_all(load_all(self.path), self.path)
        self.assertEqual(get_active(self.path), "klein")
        set_active("flux1", self.path)
        self.assertEqual(get_active(self.path), "flux1")
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(doc["active"], "flux1")
        self.assertEqual(set(doc["profiles"]), {"klein", "flux1"})

    def test_mode_round_trips(self) -> None:
        upsert(self._sample("klein", mode="vast"), self.path)
        got = load_all(self.path)["klein"]
        self.assertEqual(got.mode, "vast")
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(doc["profiles"]["klein"]["mode"], "vast")

    def test_a_record_without_mode_loads_as_salad(self) -> None:
        upsert(self._sample("klein"), self.path)
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        doc["profiles"]["klein"].pop("mode", None)
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(load_all(self.path)["klein"].mode, "salad")

    def test_an_unknown_mode_coerces_to_salad(self) -> None:
        upsert(self._sample("klein"), self.path)
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        doc["profiles"]["klein"]["mode"] = "runpod"
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(load_all(self.path)["klein"].mode, "salad")

    def test_old_profile_use_loras_true_fills_klein_pair(self) -> None:
        doc = {
            "profiles": {
                "klein": {
                    "name": "klein",
                    "gateway": "https://example.salad.cloud",
                    "key_path": str(Path(self._td.name) / "key"),
                    "graph": "klein",
                    "width": 1024,
                    "height": 1024,
                    "steps": 20,
                    "use_loras": True,
                }
            },
            "active": "klein",
        }
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        loaded = load_all(self.path)["klein"]
        self.assertEqual(
            loaded.selected_loras,
            [
                "civitai:2334190@2625692",
                "civitai:545264@2763568",
            ],
        )

    def test_old_profile_use_loras_false_is_empty(self) -> None:
        doc = {
            "profiles": {
                "klein": {
                    "name": "klein",
                    "gateway": "https://example.salad.cloud",
                    "key_path": str(Path(self._td.name) / "key"),
                    "graph": "klein",
                    "width": 64,
                    "height": 64,
                    "steps": 4,
                    "use_loras": False,
                }
            },
            "active": "klein",
        }
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        loaded = load_all(self.path)["klein"]
        self.assertEqual(loaded.selected_loras, [])
        self.assertIs(loaded.use_loras, False)

    def test_never_uses_real_config_path(self) -> None:
        self.assertNotEqual(self.path.resolve(), PROFILES_PATH.resolve())
        upsert(self._sample("temp-only"), self.path)
        self.assertTrue(self.path.is_file())
        # The real studio-profiles.json must not be created by this test.
        # If it already existed, this test still never wrote to it.
        self.assertNotEqual(self.path, PROFILES_PATH)

    def test_non_numeric_fields_fall_back_to_defaults(self) -> None:
        """A hand-edited field must not abort load_all (audit L5)."""
        doc = {
            "profiles": {
                "klein": {
                    "name": "klein",
                    "gateway": "https://example.salad.cloud",
                    "key_path": str(Path(self._td.name) / "key"),
                    "graph": "klein",
                    "width": "wide",
                    "height": None,
                    "steps": "many",
                    "cfg": "high",
                    "seed": "abc",
                    "use_loras": False,
                }
            },
            "active": "klein",
        }
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        loaded = load_all(self.path)
        self.assertIn("klein", loaded)
        got = loaded["klein"]
        # Each bad field falls back to the SaladProfile default; the good
        # fields survive untouched.
        self.assertEqual(got.width, SaladProfile.width)
        self.assertEqual(got.height, SaladProfile.height)
        self.assertEqual(got.steps, SaladProfile.steps)
        self.assertEqual(got.cfg, SaladProfile.cfg)
        self.assertEqual(got.seed, SaladProfile.seed)
        self.assertEqual(got.gateway, "https://example.salad.cloud")
        self.assertEqual(got.graph, "klein")
        self.assertIs(got.use_loras, False)
        # ensure_builtin_profiles runs on app boot and must survive too.
        import profiles as pr

        old_k, old_5 = pr.GATEWAY_KLEIN_PATH, pr.GATEWAY_KLEIN_5090_PATH
        pr.GATEWAY_KLEIN_PATH = Path(self._td.name) / "gateway-klein"
        pr.GATEWAY_KLEIN_5090_PATH = Path(self._td.name) / "gateway-klein-5090"
        try:
            built = ensure_builtin_profiles(self.path)
        finally:
            pr.GATEWAY_KLEIN_PATH = old_k
            pr.GATEWAY_KLEIN_5090_PATH = old_5
        self.assertEqual(set(built), {"klein", "klein5090"})
        self.assertEqual(built["klein"].width, SaladProfile.width)


class UnetRoutingTest(unittest.TestCase):
    """SNOFS and non-SNOFS unets must never share a container group: a 24 GB card
    holds one ~9 GB unet beside the 8.66 GB text encoder, so a second unet forces
    Comfy to stream weights from host memory (240-576 s renders, measured)."""

    def _profile(self, name: str, unet: str) -> SaladProfile:
        return SaladProfile(name=name, gateway="https://example.test/", checkpoints=[unet])

    def _graph(self, unet: str) -> dict:
        return {
            "prompt": {
                "94": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
                "114": {"class_type": "SaveImage", "inputs": {"images": ["88", 0], "filename_prefix": "x"}},
            }
        }

    def test_family_of_a_name(self) -> None:
        self.assertEqual(unet_family("snofsSexNudesAndOther_distilledV12KleinFp8.safetensors"), "snofs")
        self.assertEqual(unet_family("SNOFS_anything.safetensors"), "snofs")
        self.assertEqual(unet_family("flux-2-klein-base-9b-fp8.safetensors"), "klein")
        self.assertEqual(unet_family("flux-2-klein-9b-fp8.safetensors"), "klein")
        self.assertEqual(unet_family(""), "")
        self.assertEqual(unet_family("   "), "")

    def test_payload_unets_reads_the_loader_deduped(self) -> None:
        payload = {"prompt": {
            "94": {"class_type": "UNETLoader", "inputs": {"unet_name": "a.safetensors"}},
            "95": {"class_type": "UNETLoader", "inputs": {"unet_name": "a.safetensors"}},
            "96": {"class_type": "UNETLoader", "inputs": {"unet_name": "b.safetensors"}},
        }}
        self.assertEqual(payload_unets(payload), ["a.safetensors", "b.safetensors"])
        self.assertEqual(payload_unets({"prompt": {}}), [])
        self.assertEqual(payload_unets(None), [])

    def test_the_two_builtin_profiles_are_the_two_families(self) -> None:
        """klein serves the plain unets; klein5090 serves the SNOFS cut."""
        self.assertEqual(checkpoint_family(default_profile("klein").primary_checkpoint), "klein")
        self.assertEqual(checkpoint_family(default_profile("klein5090").primary_checkpoint), "snofs")



class RoutingTest(unittest.TestCase):
    """A generation request goes to the group that serves the unet it loads."""

    def _all(self) -> dict:
        return {"klein": default_profile("klein"), "klein5090": default_profile("klein5090")}

    def _graph(self, unet: str) -> dict:
        return {"prompt": {"94": {"class_type": "UNETLoader", "inputs": {"unet_name": unet}}}}

    def test_the_two_builtins_serve_the_two_families(self) -> None:
        allp = self._all()
        self.assertEqual(checkpoint_family(allp["klein"].primary_checkpoint), "klein")
        self.assertEqual(checkpoint_family(allp["klein5090"].primary_checkpoint), "snofs")

    def test_each_family_routes_to_its_own_group(self) -> None:
        """The shipped decision: from the other family's profile, each graph routes home."""
        allp = self._all()
        cases = (
            ("flux-2-klein-base-9b-fp8.safetensors", "klein5090", "klein"),
            ("flux-2-klein-9b-fp8.safetensors", "klein5090", "klein"),
            ("snofsSexNudesAndOther_distilledV12KleinFp8.safetensors", "klein", "klein5090"),
        )
        for unet, form, want in cases:
            with self.subTest(unet=unet):
                route, refusal = plan_route(self._graph(unet), allp[form], allp)
                self.assertEqual(refusal, "")
                self.assertIsNotNone(route)
                self.assertIsNot(route, None)
                self.assertEqual(route.name, want)

    def test_a_checkpoint_no_profile_lists_is_refused(self) -> None:
        allp = self._all()
        route, refusal = plan_route(self._graph("snofs_x.safetensors"), allp["klein"], allp)
        self.assertIsNone(route)
        self.assertIn("No profile lists", refusal)

    def test_a_graph_with_no_unet_is_sent_where_the_form_points(self) -> None:
        allp = self._all()
        route, refusal = plan_route(
            {"prompt": {"1": {"class_type": "SaveImage", "inputs": {}}}}, allp["klein"], allp
        )
        self.assertIsNone(route)
        self.assertEqual(refusal, "")

    def test_serving_family_reads_the_profiles_own_unet(self) -> None:
        self.assertEqual(serving_family(default_profile("klein")), "klein")
        self.assertEqual(serving_family(default_profile("klein5090")), "snofs")

    def test_same_gateway_ignores_case_and_a_trailing_slash(self) -> None:
        base = "https://beet-ginger-abc.salad.cloud"
        self.assertTrue(same_gateway(base, base + "/"))
        self.assertTrue(same_gateway(base.upper(), base))
        self.assertTrue(same_gateway("  " + base + "  ", base))
        self.assertFalse(same_gateway(base, "https://apple-gadogado-xyz.salad.cloud"))
        # Two empty gateways are NOT the same: an unset gateway must still route.
        self.assertFalse(same_gateway("", ""))
        self.assertFalse(same_gateway("", base))

    def test_profile_for_gateway_finds_the_group_a_form_would_post_to(self) -> None:
        """The routing guard asks this, not the form's unet, see app._on_generate."""
        allp = self._all()
        klein, snofs = allp["klein"], allp["klein5090"]
        self.assertEqual(profile_for_gateway(klein.gateway, allp).name, "klein")
        self.assertEqual(profile_for_gateway(snofs.gateway + "/", allp).name, "klein5090")
        self.assertIsNone(profile_for_gateway("https://custom.example.test/gw", allp))
        self.assertIsNone(profile_for_gateway("", allp))


class CheckpointListTest(unittest.TestCase):
    """A profile owns the checkpoints its container serves, and the store keeps them."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.path = Path(self._td.name) / "studio-profiles.json"

    def test_a_multi_checkpoint_list_round_trips(self) -> None:
        listed = ["flux-2-klein-base-9b-fp8.safetensors", "flux-2-klein-9b-fp8.safetensors"]
        upsert(SaladProfile(name="klein", gateway="https://example.salad.cloud", checkpoints=listed), self.path)
        self.assertEqual(load_all(self.path)["klein"].checkpoints, listed)
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(doc["profiles"]["klein"]["checkpoints"], listed)
        self.assertNotIn("unet", doc["profiles"]["klein"], "the single-checkpoint field is gone")

    def test_an_entry_can_be_added_and_removed_and_persisted(self) -> None:
        upsert(
            SaladProfile(name="klein", checkpoints=["flux-2-klein-base-9b-fp8.safetensors"]),
            self.path,
        )
        stored = load_all(self.path)["klein"]
        self.assertEqual(add_checkpoint(stored, "flux-2-klein-9b-fp8.safetensors"), "")
        upsert(stored, self.path)
        stored = load_all(self.path)["klein"]
        self.assertEqual(
            stored.checkpoints,
            ["flux-2-klein-base-9b-fp8.safetensors", "flux-2-klein-9b-fp8.safetensors"],
        )
        self.assertTrue(remove_checkpoint(stored, "flux-2-klein-base-9b-fp8.safetensors"))
        upsert(stored, self.path)
        self.assertEqual(
            load_all(self.path)["klein"].checkpoints, ["flux-2-klein-9b-fp8.safetensors"]
        )

    def test_adding_a_checkpoint_of_another_family_is_allowed(self) -> None:
        profile = SaladProfile(name="snofs-group", checkpoints=[SNOFS_UNET])
        self.assertEqual(
            add_checkpoint(profile, "flux-2-klein-base-9b-fp8.safetensors"), ""
        )
        self.assertEqual(
            profile.checkpoints,
            [SNOFS_UNET, "flux-2-klein-base-9b-fp8.safetensors"],
        )
        self.assertIn("2 unet families", mixed_family_reason(profile))
        self.assertEqual(
            add_checkpoint(profile, SNOFS_UNET),
            f"{SNOFS_UNET} is already in 'snofs-group'.",
        )

    def test_a_legacy_single_checkpoint_record_loads_as_a_one_entry_list(self) -> None:
        legacy = {
            "profiles": {
                "klein": {
                    "name": "klein",
                    "gateway": "https://example.salad.cloud",
                    "unet": "flux-2-klein-base-9b-fp8.safetensors",
                }
            },
            "active": "klein",
        }
        self.path.write_text(json.dumps(legacy), encoding="utf-8")
        self.assertEqual(
            load_all(self.path)["klein"].checkpoints,
            ["flux-2-klein-base-9b-fp8.safetensors"],
        )

    def test_a_new_profile_is_seeded_from_the_metadata_document(self) -> None:
        self.assertEqual(seed_checkpoints("klein5090"), [SNOFS_UNET])
        self.assertIn("flux-2-klein-base-9b-fp8.safetensors", seed_checkpoints("klein"))
        self.assertEqual(default_profile("klein").checkpoints, seed_checkpoints("klein"))
        self.assertEqual(default_profile("klein5090").checkpoints, [SNOFS_UNET])

    def test_delete_removes_the_profile_from_the_store(self) -> None:
        upsert(SaladProfile(name="third", checkpoints=["a.safetensors"]), self.path)
        upsert(SaladProfile(name="fourth", checkpoints=["b.safetensors"]), self.path)
        self.assertEqual(sorted(delete("third", self.path)), ["fourth"])
        self.assertEqual(sorted(load_all(self.path)), ["fourth"])


class ProfilePolicyTest(unittest.TestCase):
    """Each stored config keeps its own Salad group policy across a reload."""

    KLEIN_UNET = "flux-2-klein-base-9b-fp8.safetensors"

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.path = Path(self._td.name) / "studio-profiles.json"

    def _policy(
        self,
        image: str,
        gpu_class: str,
        country: str,
        group_name: str = "klein-group",
        version: int = 1,
    ) -> dict:
        """The dict salad_status.policy_from_group returns for a real group."""
        probe = {
            "path": "/health",
            "port": 3000,
            "initial_delay_seconds": 60,
            "period_seconds": 10,
            "timeout_seconds": 5,
            "failure_threshold": 12,
        }
        return {
            "group_name": group_name,
            "version": version,
            "image": image,
            "gpu_classes": [gpu_class],
            "country_codes": [country],
            "startup": dict(probe),
            "readiness": dict(probe, path="/ready"),
        }

    def _store_two(self) -> tuple[dict, dict]:
        klein = self._policy("ghcr.io/x/klein:1", "rtx4090", "us")
        snofs = self._policy("ghcr.io/x/snofs:2", "rtx5090", "ca", "snofs-group", 4)
        upsert(SaladProfile(name="klein", policy=klein), self.path)
        upsert(SaladProfile(name="klein5090", policy=snofs), self.path)
        return klein, snofs

    def test_each_profile_loads_back_its_own_policy(self) -> None:
        klein, snofs = self._store_two()
        loaded = load_all(self.path)
        self.assertEqual(loaded["klein"].policy, klein)
        self.assertEqual(loaded["klein5090"].policy, snofs)
        self.assertNotEqual(loaded["klein"].policy, loaded["klein5090"].policy)
        self.assertIsNot(loaded["klein"].policy, loaded["klein5090"].policy)
        # Deep copy: no nested probe or list may be shared between two profiles.
        self.assertIsNot(
            loaded["klein"].policy["startup"], loaded["klein5090"].policy["startup"]
        )
        self.assertIsNot(
            loaded["klein"].policy["gpu_classes"],
            loaded["klein5090"].policy["gpu_classes"],
        )

    def test_a_record_with_no_policy_key_loads_the_documents_image(self) -> None:
        """A store written before the policy existed must not load imageless."""
        doc = {
            "profiles": {
                "klein": {
                    "name": "klein",
                    "gateway": "https://example.salad.cloud",
                    "checkpoints": [self.KLEIN_UNET],
                }
            },
            "active": "klein",
        }
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        loaded = load_all(self.path)["klein"]
        self.assertTrue(loaded.policy["image"], "the shipped document names a klein image")
        self.assertEqual(
            loaded.policy["image"],
            studio_meta.image_for_family("klein", studio_meta.default()),
        )
        # The load fills the image in and nothing else: the probes the Config
        # page shows come from the document, not from the stored record.
        seeded = seeded_policy(SaladProfile(name="klein", checkpoints=[self.KLEIN_UNET]))
        self.assertEqual(loaded.policy, {"image": seeded["image"]})

    def test_an_empty_stored_policy_comes_back_carrying_the_documents_image(self) -> None:
        upsert(
            SaladProfile(name="klein", checkpoints=[self.KLEIN_UNET], policy={}),
            self.path,
        )
        loaded = load_all(self.path)["klein"]
        self.assertTrue(loaded.policy["image"], "the shipped document names a klein image")
        self.assertEqual(
            loaded.policy["image"],
            studio_meta.image_for_family("klein", studio_meta.default()),
        )

    def test_an_imageless_stored_policy_keeps_its_fields_when_seeded(self) -> None:
        """The seed fills the image in; a stored probe or placement stays put."""
        upsert(
            SaladProfile(
                name="klein",
                checkpoints=[self.KLEIN_UNET],
                policy={
                    "gpu_classes": ["rtx4090"],
                    "country_codes": ["us"],
                    "startup": {"failure_threshold": "7"},
                },
            ),
            self.path,
        )
        loaded = load_all(self.path)["klein"]
        self.assertEqual(
            loaded.policy["image"],
            studio_meta.image_for_family("klein", studio_meta.default()),
            "the document's image fills the gap",
        )
        self.assertEqual(loaded.policy["gpu_classes"], ["rtx4090"])
        self.assertEqual(loaded.policy["country_codes"], ["us"])
        self.assertEqual(loaded.policy["startup"]["failure_threshold"], "7")

    def test_a_stored_image_is_its_own_and_beats_the_documents(self) -> None:
        upsert(
            SaladProfile(
                name="klein",
                checkpoints=[self.KLEIN_UNET],
                policy={"image": "docker.io/example/mine:tag"},
            ),
            self.path,
        )
        loaded = load_all(self.path)["klein"]
        self.assertEqual(loaded.policy["image"], "docker.io/example/mine:tag")
        self.assertNotEqual(
            loaded.policy["image"],
            studio_meta.image_for_family("klein", studio_meta.default()),
        )

    def test_a_stored_image_keeps_every_other_policy_field(self) -> None:
        mine = self._policy("docker.io/example/mine:tag", "rtx4090", "us")
        upsert(
            SaladProfile(name="klein", checkpoints=[self.KLEIN_UNET], policy=mine),
            self.path,
        )
        loaded = load_all(self.path)["klein"]
        self.assertEqual(loaded.policy, mine)
        self.assertEqual(loaded.policy["gpu_classes"], ["rtx4090"])
        self.assertEqual(loaded.policy["country_codes"], ["us"])
        self.assertEqual(loaded.policy["startup"]["failure_threshold"], 12)
        self.assertEqual(loaded.policy["readiness"]["path"], "/ready")

    def test_a_non_dict_policy_still_loads_the_documents_image(self) -> None:
        """Junk in the policy field must not crash, and must not lose the image."""
        expected = studio_meta.image_for_family("klein", studio_meta.default())
        self.assertTrue(expected, "the shipped document names a klein image")
        for junk in ("junk", ["image", "gpu_classes"], 7, None):
            with self.subTest(policy=junk):
                doc = {
                    "profiles": {
                        "klein": {
                            "name": "klein",
                            "checkpoints": [self.KLEIN_UNET],
                            "policy": junk,
                        }
                    },
                    "active": "klein",
                }
                self.path.write_text(json.dumps(doc), encoding="utf-8")
                self.assertEqual(
                    load_all(self.path)["klein"].policy, {"image": expected}
                )

    def test_a_non_dict_policy_loads_as_empty(self) -> None:
        for junk in ("junk", ["image", "gpu_classes"], 7, None):
            with self.subTest(policy=junk):
                doc = {
                    "profiles": {"klein": {"name": "klein", "policy": junk}},
                    "active": "klein",
                }
                self.path.write_text(json.dumps(doc), encoding="utf-8")
                self.assertEqual(load_all(self.path)["klein"].policy, {})

    def test_a_new_builtin_profile_starts_with_the_documents_image(self) -> None:
        doc = studio_meta.default()
        klein = default_profile("klein")
        snofs = default_profile("klein5090")
        # Pinned by value: the document's image and the probes it documents for
        # the family, not whatever default_profile just assigned.
        self.assertEqual(
            klein.policy,
            {
                "image": studio_meta.image_for_family("klein", doc),
                **studio_meta.probe_settings_for_family("klein", doc),
            },
        )
        self.assertEqual(
            snofs.policy,
            {
                "image": studio_meta.image_for_family("snofs", doc),
                **studio_meta.probe_settings_for_family("snofs", doc),
            },
        )
        self.assertEqual(
            klein.policy["image"],
            studio_meta.image_for_family("klein", studio_meta.default()),
        )
        self.assertEqual(
            snofs.policy["image"],
            studio_meta.image_for_family("snofs", studio_meta.default()),
        )
        self.assertNotEqual(klein.policy["image"], snofs.policy["image"])

    def test_policy_image_for_names_the_documents_image_or_nothing(self) -> None:
        klein = SaladProfile(name="klein", checkpoints=[self.KLEIN_UNET])
        self.assertEqual(
            policy_image_for(klein),
            studio_meta.image_for_family("klein", studio_meta.default()),
        )
        self.assertTrue(policy_image_for(klein), "the shipped document names a klein image")
        # No checkpoint is no family, so the document has nothing to name.
        self.assertEqual(policy_image_for(SaladProfile(name="empty")), "")
        self.assertEqual(
            policy_image_for(SaladProfile(name="empty"), studio_meta.default()), ""
        )
        # A document that names no image for the family is "" too.
        self.assertEqual(policy_image_for(klein, {"routing": {"families": {}}}), "")
        self.assertEqual(
            policy_image_for(
                klein,
                {"routing": {"families": {"klein": {"unets": [self.KLEIN_UNET]}}}},
            ),
            "",
        )

    def test_policy_image_for_never_raises_on_a_broken_document(self) -> None:
        klein = SaladProfile(name="klein", checkpoints=[self.KLEIN_UNET])
        for broken in ("junk", [], 7, {"routing": "nope"}, {"routing": {"families": "nope"}}):
            with self.subTest(meta=broken):
                self.assertEqual(policy_image_for(klein, broken), "")

    def test_seeded_policy_is_the_documents_settings_or_nothing(self) -> None:
        klein = SaladProfile(name="klein", checkpoints=[self.KLEIN_UNET])
        doc = studio_meta.default()
        image = studio_meta.image_for_family("klein", doc)
        probes = studio_meta.probe_settings_for_family("klein", doc)
        self.assertTrue(image, "the shipped document names a klein image")
        self.assertTrue(probes, "the shipped document documents klein's probes")
        self.assertEqual(seeded_policy(klein), {"image": image, **probes})
        self.assertEqual(seeded_policy(SaladProfile(name="empty")), {})
        self.assertEqual(seeded_policy(klein, {"routing": {"families": {}}}), {})
        self.assertEqual(
            seeded_policy(
                klein,
                {"routing": {"families": {"klein": {"image": "  ", "unets": [self.KLEIN_UNET]}}}},
            ),
            {},
        )

    def test_a_new_builtin_profile_starts_with_the_documents_probes(self) -> None:
        doc = studio_meta.default()
        for name, family in (("klein", "klein"), ("klein5090", "snofs")):
            with self.subTest(profile=name):
                profile = default_profile(name)
                self.assertEqual(
                    profile.policy,
                    {
                        "image": studio_meta.image_for_family(family, doc),
                        **studio_meta.probe_settings_for_family(family, doc),
                    },
                )
                self.assertEqual(sorted(profile.policy), ["image", "readiness", "startup"])

    def test_the_two_families_seed_the_probes_their_own_entry_documents(self) -> None:
        """Where the document tells the families apart, so do the seeded policies."""
        klein_probe = {
            "path": "/health",
            "port": 3000,
            "initial_delay_seconds": 900,
            "period_seconds": 60,
            "timeout_seconds": 10,
            "failure_threshold": 7,
        }
        snofs_probe = dict(klein_probe, initial_delay_seconds=30, failure_threshold=2)
        doc = {
            "routing": {
                "families": {
                    "klein": {
                        "image": "ghcr.io/x/klein:1",
                        "unets": [self.KLEIN_UNET],
                        "markers": ["klein"],
                        "startup_probe": klein_probe,
                        "readiness_probe": dict(klein_probe, path="/ready"),
                    },
                    "snofs": {
                        "unets": [SNOFS_UNET],
                        "markers": ["snofs"],
                        "startup_probe": snofs_probe,
                    },
                }
            }
        }
        klein = seeded_policy(
            SaladProfile(name="klein", checkpoints=[self.KLEIN_UNET]), doc
        )
        snofs = seeded_policy(
            SaladProfile(name="klein5090", checkpoints=[SNOFS_UNET]), doc
        )
        self.assertEqual(klein["startup"], klein_probe)
        self.assertEqual(klein["readiness"], dict(klein_probe, path="/ready"))
        self.assertNotEqual(klein["startup"], snofs["startup"])
        self.assertEqual(snofs["startup"], snofs_probe)
        # The document names no image and no readiness for snofs: neither is invented.
        self.assertEqual(sorted(snofs), ["startup"])

    def test_the_written_json_nests_each_policy_under_its_profile(self) -> None:
        klein, snofs = self._store_two()
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(doc["profiles"]["klein"]["policy"], klein)
        self.assertEqual(doc["profiles"]["klein5090"]["policy"], snofs)
        self.assertEqual(
            doc["profiles"]["klein5090"]["policy"]["readiness"]["path"], "/ready"
        )

    def test_editing_one_loaded_policy_does_not_change_the_other(self) -> None:
        klein, snofs = self._store_two()
        loaded = load_all(self.path)
        loaded["klein"].policy["image"] = "ghcr.io/x/klein:9"
        loaded["klein"].policy["startup"]["timeout_seconds"] = 99
        loaded["klein"].policy["gpu_classes"].append("rtx3090")
        save_all(loaded, self.path)

        again = load_all(self.path)
        self.assertEqual(again["klein"].policy["image"], "ghcr.io/x/klein:9")
        self.assertEqual(again["klein"].policy["startup"]["timeout_seconds"], 99)
        self.assertEqual(again["klein"].policy["gpu_classes"], ["rtx4090", "rtx3090"])
        self.assertEqual(again["klein5090"].policy, snofs)
        self.assertEqual(again["klein5090"].policy["image"], snofs["image"])
        self.assertEqual(again["klein5090"].policy["gpu_classes"], ["rtx5090"])
        self.assertNotEqual(again["klein"].policy, klein)


class RoutingByCheckpointListTest(unittest.TestCase):
    """Three profiles with distinct lists: the list decides, and a change moves it."""

    KLEIN_BASE = "flux-2-klein-base-9b-fp8.safetensors"
    KLEIN_DISTILLED = "flux-2-klein-9b-fp8.safetensors"
    KLEIN_THIRD = "flux-2-klein-3b-fp8.safetensors"

    def _all(self) -> dict[str, SaladProfile]:
        return {
            "klein": SaladProfile(
                name="klein",
                gateway="https://klein.example/",
                checkpoints=[self.KLEIN_BASE, self.KLEIN_DISTILLED],
            ),
            "snofs": SaladProfile(
                name="snofs", gateway="https://snofs.example/", checkpoints=[SNOFS_UNET]
            ),
            "third": SaladProfile(
                name="third", gateway="https://third.example/", checkpoints=[self.KLEIN_THIRD]
            ),
        }

    @staticmethod
    def _graph(unet: str) -> dict:
        return {"prompt": {"94": {"class_type": "UNETLoader", "inputs": {"unet_name": unet}}}}

    def test_three_profiles_each_route_their_own_checkpoint(self) -> None:
        """From another profile's form, each checkpoint routes to the profile that lists it."""
        allp = self._all()
        for name, unet, form in (
            ("klein", self.KLEIN_DISTILLED, "snofs"),
            ("snofs", SNOFS_UNET, "klein"),
            ("third", self.KLEIN_THIRD, "klein"),
        ):
            with self.subTest(profile=name):
                route, refusal = plan_route(self._graph(unet), allp[form], allp)
                self.assertEqual(refusal, "")
                self.assertIsNotNone(route)
                self.assertIsNot(route, None)
                self.assertEqual(route.name, name)
                self.assertEqual(route.profile.gateway, allp[name].gateway)

    def test_a_checkpoint_in_no_list_is_refused_with_a_reason(self) -> None:
        allp = self._all()
        route, refusal = plan_route(self._graph("mystery.safetensors"), allp["klein"], allp)
        self.assertIsNone(route)
        self.assertIn("mystery.safetensors", refusal)
        self.assertIn("No profile lists", refusal)

    def test_changing_only_a_profiles_list_changes_the_target(self) -> None:
        allp = self._all()
        moved = "flux-2-klein-4b-fp8.safetensors"
        allp["klein"].checkpoints.append(moved)
        route, refusal = plan_route(self._graph(moved), allp["snofs"], allp)
        self.assertEqual(refusal, "")
        self.assertIsNot(route, None)
        self.assertEqual(route.name, "klein")
        self.assertTrue(remove_checkpoint(allp["klein"], moved))
        allp["third"].checkpoints.append(moved)
        route, refusal = plan_route(self._graph(moved), allp["snofs"], allp)
        self.assertEqual(refusal, "")
        self.assertIsNot(route, None)
        self.assertEqual(route.name, "third")

    def test_a_checkpoint_two_profiles_list_is_refused_as_ambiguous(self) -> None:
        allp = self._all()
        allp["third"].checkpoints.append(self.KLEIN_DISTILLED)
        self.assertEqual(
            profiles_for_checkpoint(self.KLEIN_DISTILLED, allp), ["klein", "third"]
        )
        route, refusal = plan_route(self._graph(self.KLEIN_DISTILLED), allp["klein"], allp)
        self.assertIsNone(route)
        self.assertIn("ambiguous", refusal)

    def test_a_profile_that_mixes_families_routes_with_a_warning(self) -> None:
        allp = self._all()
        # SNOFS on one profile only, which also lists a klein cut.
        allp["snofs"].checkpoints = []
        allp["third"].checkpoints = [self.KLEIN_THIRD, SNOFS_UNET]
        self.assertIn("2 unet families", mixed_family_reason(allp["third"]))
        route, refusal = plan_route(self._graph(SNOFS_UNET), allp["klein"], allp)
        self.assertEqual(refusal, "")
        self.assertIsNot(route, None)
        self.assertEqual(route.name, "third")

    def test_the_profile_that_lists_it_is_left_alone(self) -> None:
        allp = self._all()
        route, refusal = plan_route(self._graph(self.KLEIN_BASE), allp["klein"], allp)
        self.assertIsNone(route)
        self.assertEqual(refusal, "")
        route, refusal = plan_route(self._graph(SNOFS_UNET), allp["snofs"], allp)
        self.assertIsNone(route)
        self.assertEqual(refusal, "")


class TruncatedStoreDegrades(unittest.TestCase):
    """C2: a half-written studio-profiles.json must not abort load_all.

    ``_save_doc`` writes in place, so a crash mid-write leaves truncated JSON.
    The loader has to read that as "no profiles" — an app that raises there does
    not start at all — and the store has to be writable again afterwards.
    """

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.path = Path(self._td.name) / "studio-profiles.json"

    def test_a_truncated_file_reads_as_no_profiles(self) -> None:
        self.path.write_text(
            '{"profiles": {"klein": {"name": "kle', encoding="utf-8"
        )
        self.assertEqual(load_all(self.path), {})

    def test_empty_non_json_and_wrong_shaped_files_read_as_no_profiles(self) -> None:
        for blob in ("", "   ", "not json at all", '["a", "list"]', '{"profiles": "nope"}'):
            with self.subTest(blob=blob):
                self.path.write_text(blob, encoding="utf-8")
                self.assertEqual(load_all(self.path), {})

    def test_the_store_is_writable_again_after_a_truncated_read(self) -> None:
        self.path.write_text('{"profiles": {"klein": ', encoding="utf-8")
        self.assertEqual(load_all(self.path), {}, "the broken file reads as empty")
        save_all({"klein": default_profile()}, self.path)
        self.assertEqual(sorted(load_all(self.path)), ["klein"], "and it saves again")


if __name__ == "__main__":
    unittest.main()
