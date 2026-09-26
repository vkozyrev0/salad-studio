"""Tests for salad_studio.profiles. Never touch the real ~/.config file."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

from profiles import (
    add_checkpoint,
    checkpoint_family,
    mixed_family_reason,
    payload_unets,
    plan_route,
    profile_for_gateway,
    profiles_for_checkpoint,
    remove_checkpoint,
    route_payload,
    same_gateway,
    seed_checkpoints,
    serving_family,
    unet_family,
    SNOFS_UNET,
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

EXPECTED_FIELDS = (
    "name",
    "gateway",
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


try:
    import tkinter as tk
except ImportError as _tk_err:
    tk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = _tk_err
else:
    _TK_IMPORT_ERROR = None


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class LiveCorruptProfilesFile(unittest.TestCase):
    """The shipped app must start with a non-numeric studio-profiles.json."""

    def test_app_starts_with_a_non_numeric_stored_field(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            raise unittest.SkipTest(f"Tk cannot initialize: {e}") from e

        from salad_studio import lora_store, prompt_history, tokens as tok, ui_state
        from salad_studio import profiles as sp
        from salad_studio.app import SaladStudio

        old = {
            "profiles": sp.PROFILES_PATH,
            "gw_klein": sp.GATEWAY_KLEIN_PATH,
            "gw_5090": sp.GATEWAY_KLEIN_5090_PATH,
            "extras": lora_store.EXTRAS_PATH,
            "hist": prompt_history.HISTORY_PATH,
            "thumbs": prompt_history.THUMBS_DIR,
            "local": tok.LOCAL_PATH,
            "cfg": tok.CONFIG_HOME,
            "state": ui_state.STATE_PATH,
        }
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            sp.PROFILES_PATH = tmp / "studio-profiles.json"
            sp.GATEWAY_KLEIN_PATH = tmp / "gateway-klein"
            sp.GATEWAY_KLEIN_5090_PATH = tmp / "gateway-klein-5090"
            lora_store.EXTRAS_PATH = tmp / "studio-loras.json"
            prompt_history.HISTORY_PATH = tmp / "studio-prompt-history.json"
            prompt_history.THUMBS_DIR = tmp / "thumbs"
            tok.LOCAL_PATH = tmp / "studio-tokens.json"
            tok.CONFIG_HOME = tmp / "defaults"
            ui_state.STATE_PATH = tmp / "studio-ui.json"
            try:
                sp.PROFILES_PATH.write_text(
                    json.dumps(
                        {
                            "profiles": {
                                "klein": {
                                    "name": "klein",
                                    "gateway": "https://example.salad.cloud",
                                    "graph": "klein",
                                    "width": "wide",
                                    "steps": "many",
                                }
                            },
                            "active": "klein",
                        }
                    ),
                    encoding="utf-8",
                )
                app = SaladStudio()
                app.withdraw()
                try:
                    app.update_idletasks()
                    self.assertIn("klein", app.profile_combo["values"])
                    self.assertIn("klein5090", app.profile_combo["values"])
                    self.assertEqual(app.var_width.get(), str(SaladProfile.width))
                    self.assertEqual(app.var_steps.get(), str(SaladProfile.steps))
                    self.assertEqual(
                        app.var_gateway.get(), "https://example.salad.cloud"
                    )
                finally:
                    app.destroy()
            finally:
                sp.PROFILES_PATH = old["profiles"]
                sp.GATEWAY_KLEIN_PATH = old["gw_klein"]
                sp.GATEWAY_KLEIN_5090_PATH = old["gw_5090"]
                lora_store.EXTRAS_PATH = old["extras"]
                prompt_history.HISTORY_PATH = old["hist"]
                prompt_history.THUMBS_DIR = old["thumbs"]
                tok.LOCAL_PATH = old["local"]
                tok.CONFIG_HOME = old["cfg"]
                ui_state.STATE_PATH = old["state"]


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
        allp = self._all()
        self.assertEqual(route_payload(self._graph("flux-2-klein-base-9b-fp8.safetensors"), allp)[0], "klein")
        self.assertEqual(route_payload(self._graph("flux-2-klein-9b-fp8.safetensors"), allp)[0], "klein")
        self.assertEqual(
            route_payload(self._graph("snofsSexNudesAndOther_distilledV12KleinFp8.safetensors"), allp)[0],
            "klein5090",
        )

    def test_a_family_no_group_serves_routes_to_nothing(self) -> None:
        self.assertIsNone(route_payload(self._graph("snofs_x.safetensors"), {"klein": default_profile("klein")}))

    def test_a_graph_with_no_unet_routes_to_nothing(self) -> None:
        self.assertIsNone(route_payload({"prompt": {"1": {"class_type": "SaveImage", "inputs": {}}}}, self._all()))

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

    def test_adding_a_checkpoint_of_another_family_is_refused(self) -> None:
        profile = SaladProfile(name="snofs-group", checkpoints=[SNOFS_UNET])
        reason = add_checkpoint(profile, "flux-2-klein-base-9b-fp8.safetensors")
        self.assertIn("one unet family", reason)
        self.assertEqual(profile.checkpoints, [SNOFS_UNET])
        self.assertEqual(add_checkpoint(profile, SNOFS_UNET), f"{SNOFS_UNET} is already in 'snofs-group'.")

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
        allp = self._all()
        for name, unet in (
            ("klein", self.KLEIN_DISTILLED),
            ("snofs", SNOFS_UNET),
            ("third", self.KLEIN_THIRD),
        ):
            with self.subTest(profile=name):
                got = route_payload(self._graph(unet), allp)
                self.assertIsNotNone(got)
                assert got is not None
                self.assertEqual(got[0], name)
                self.assertEqual(got[1].gateway, allp[name].gateway)

    def test_a_checkpoint_in_no_list_is_refused_with_a_reason(self) -> None:
        allp = self._all()
        route, refusal = plan_route(self._graph("mystery.safetensors"), allp["klein"], allp)
        self.assertIsNone(route)
        self.assertIn("mystery.safetensors", refusal)
        self.assertIn("No profile lists", refusal)
        self.assertIsNone(route_payload(self._graph("mystery.safetensors"), allp))

    def test_changing_only_a_profiles_list_changes_the_target(self) -> None:
        allp = self._all()
        moved = "flux-2-klein-4b-fp8.safetensors"
        allp["klein"].checkpoints.append(moved)
        self.assertEqual(route_payload(self._graph(moved), allp)[0], "klein")
        self.assertTrue(remove_checkpoint(allp["klein"], moved))
        allp["third"].checkpoints.append(moved)
        self.assertEqual(route_payload(self._graph(moved), allp)[0], "third")

    def test_a_checkpoint_two_profiles_list_is_refused_as_ambiguous(self) -> None:
        allp = self._all()
        allp["third"].checkpoints.append(self.KLEIN_DISTILLED)
        self.assertEqual(
            profiles_for_checkpoint(self.KLEIN_DISTILLED, allp), ["klein", "third"]
        )
        route, refusal = plan_route(self._graph(self.KLEIN_DISTILLED), allp["klein"], allp)
        self.assertIsNone(route)
        self.assertIn("ambiguous", refusal)

    def test_a_profile_that_mixes_families_is_refused(self) -> None:
        allp = self._all()
        # SNOFS on one profile only, which also lists a klein cut.
        allp["snofs"].checkpoints = []
        allp["third"].checkpoints = [self.KLEIN_THIRD, SNOFS_UNET]
        self.assertIn("2 unet families", mixed_family_reason(allp["third"]))
        route, refusal = plan_route(self._graph(SNOFS_UNET), allp["klein"], allp)
        self.assertIsNone(route)
        self.assertIn("unet families", refusal)
        self.assertIsNone(route_payload(self._graph(SNOFS_UNET), allp))

    def test_the_profile_that_lists_it_is_left_alone(self) -> None:
        allp = self._all()
        route, refusal = plan_route(self._graph(self.KLEIN_BASE), allp["klein"], allp)
        self.assertIsNone(route)
        self.assertEqual(refusal, "")
        route, refusal = plan_route(self._graph(SNOFS_UNET), allp["snofs"], allp)
        self.assertIsNone(route)
        self.assertEqual(refusal, "")


if __name__ == "__main__":
    unittest.main()
