"""Config gateway -> Salad group status (no live API)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for p in (str(TOOLS), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from salad_studio import salad_status  # noqa: E402


class FormatStatus(unittest.TestCase):
    def test_format_deploying_download(self) -> None:
        info = {
            "group": {
                "name": "flux2-klein",
                "display_name": "Flux2 Klein",
                "status": "deploying",
                "version": 4,
                "counts": {"creating_count": 1, "running_count": 0},
                "image": "docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-nolo",
            },
            "instances": [
                {
                    "state": "downloading",
                    "ready": False,
                    "started": False,
                    "pulling_progress": 0.0,
                }
            ],
            "ready_ok": False,
            "ready_explain": "GET https://host/ready, HTTP 522, origin TCP timeout",
        }
        line = salad_status.format_status(info)
        self.assertIn("Flux2 Klein", line)
        self.assertEqual(salad_status.short_status(info), "Downloading 0%")
        block = salad_status.generate_block_reason(info)
        self.assertIsNotNone(block)
        self.assertIn("Docker", block or "")
        self.assertEqual(salad_status.color_for_status("Downloading 33%"), salad_status.WORD_COLORS["Downloading"])

    def test_downloading_fraction_is_percent(self) -> None:
        info = {
            "ready_ok": False,
            "instances": [{"state": "downloading", "pulling_progress": 0.33}],
            "group": {"status": "deploying"},
        }
        self.assertEqual(salad_status.short_status(info), "Downloading 33%")

    def test_instance_download_beats_stale_ready(self) -> None:
        info = {
            "ready_ok": True,
            "ready_code": 200,
            "instances": [
                {
                    "state": "downloading",
                    "ready": False,
                    "started": False,
                    "pulling_progress": 0.41,
                }
            ],
            "group": {"status": "running"},
        }
        self.assertEqual(salad_status.short_status(info), "Downloading 41%")

    def test_pulling_instance_preferred_over_ready_sibling(self) -> None:
        info = {
            "ready_ok": True,
            "instances": [
                {"state": "running", "ready": True, "pulling_progress": 1.0},
                {"state": "downloading", "ready": False, "pulling_progress": 0.1},
            ],
            "group": {"status": "running"},
        }
        self.assertEqual(salad_status.short_status(info), "Downloading 10%")

    def test_empty_gateway_error(self) -> None:
        info = salad_status.check_container("", "k")
        self.assertIn("empty", info["error"].lower())

    def _ready_instance(self, ready_code: int) -> dict:
        """What Salad reports while Comfy is not answering at all.

        Measured 2026-09-22 with both groups refusing connections: the API still
        said the group was ``running`` and the instance ``ready``, while /ready
        returned Cloudflare 521.
        """
        return {
            "ready_ok": False,
            "ready_code": ready_code,
            "ready_explain": f"GET /ready, HTTP {ready_code}",
            "instances": [
                {"state": "running", "ready": True, "pulling_progress": 1.0, "gpu": "RTX 5090"}
            ],
            "group": {"status": "running", "name": "flux2-klein-5090", "version": 9},
        }

    def test_a_dead_origin_is_down_not_starting(self) -> None:
        """Salad says running/ready; the edge says the origin is gone.

        Reporting "Starting" here told the user a dead container was on its way up.
        """
        for code in (0, 520, 521, 522, 523, 524):
            with self.subTest(ready_code=code):
                self.assertEqual(
                    salad_status.short_status(self._ready_instance(code)), "Down"
                )

    def test_a_booting_replica_is_still_starting(self) -> None:
        """A 404 from /ready is a route not registered yet, not a dead origin."""
        info = self._ready_instance(404)
        info["ready_ok"] = False
        self.assertEqual(salad_status.short_status(info), "Ready")
        info["ready_code"] = 503
        self.assertEqual(salad_status.short_status(info), "Starting")

    def test_the_block_reason_for_a_dead_origin_says_down_and_why(self) -> None:
        reason = salad_status.generate_block_reason(self._ready_instance(521))
        assert reason is not None
        self.assertIn("Down", reason)
        self.assertNotIn("Replica is up", reason)
        self.assertIn("521", reason)


class MatchDns(unittest.TestCase):
    def test_matches_networking_dns(self) -> None:
        groups = {
            "items": [
                {
                    "name": "flux2-klein",
                    "display_name": "Flux2 Klein",
                    "version": 4,
                    "replicas": 1,
                    "current_state": {
                        "status": "running",
                        "description": "",
                        "instance_status_counts": {"running_count": 1},
                    },
                    "container": {"image": "docker.io/example:tag"},
                    "networking": {
                        "dns": "persimmon-caraway-2tyczg3bbqh90fnp.salad.cloud",
                        "port": 3000,
                    },
                }
            ]
        }
        instances = {
            "instances": [
                {
                    "state": "running",
                    "ready": True,
                    "started": True,
                    "pulling_progress": 1.0,
                }
            ]
        }

        def _api(url, key):
            if url.endswith("/instances"):
                return 200, instances
            if url.endswith("/flux2-klein"):
                return 200, groups["items"][0]
            if url.endswith("/containers"):
                return 200, groups
            return 404, {}

        with patch.object(salad_status, "_api_get", side_effect=_api), patch.object(
            salad_status, "_req", return_value=(200, b"ok")
        ):
            info = salad_status.check_container(
                "https://persimmon-caraway-2tyczg3bbqh90fnp.salad.cloud",
                "key",
            )
        self.assertIsNone(info.get("error"))
        self.assertTrue(info["ready_ok"])
        self.assertEqual(info["group"]["name"], "flux2-klein")
        self.assertEqual(info["instances"][0]["state"], "running")
        line = salad_status.format_status(info)
        self.assertIn("/ready 200", line)
        self.assertEqual(salad_status.short_status(info), "Ready")
        self.assertNotEqual(
            salad_status.WORD_COLORS["Ready"], salad_status.WORD_COLORS["Failed"]
        )
        self.assertNotEqual(
            salad_status.WORD_COLORS["Ready"], salad_status.WORD_COLORS["Starting"]
        )
        self.assertEqual(
            salad_status.color_for_status("Starting"),
            salad_status.WORD_COLORS["Starting"],
        )

    def test_check_container_skips_ready_while_downloading(self) -> None:
        groups = {
            "items": [
                {
                    "name": "flux2-klein",
                    "networking": {
                        "dns": "persimmon-caraway-2tyczg3bbqh90fnp.salad.cloud"
                    },
                    "current_state": {"status": "running"},
                }
            ]
        }
        instances = {
            "instances": [
                {
                    "state": "downloading",
                    "ready": False,
                    "started": False,
                    "pulling_progress": 0.2,
                }
            ]
        }

        def _api(url, key):
            if url.endswith("/instances"):
                return 200, instances
            if url.endswith("/flux2-klein"):
                return 200, groups["items"][0]
            if url.endswith("/containers"):
                return 200, groups
            return 404, {}

        with patch.object(salad_status, "_api_get", side_effect=_api), patch.object(
            salad_status, "_req", return_value=(200, b"ok")
        ) as ready:
            info = salad_status.check_container(
                "https://persimmon-caraway-2tyczg3bbqh90fnp.salad.cloud",
                "key",
            )
        ready.assert_not_called()
        self.assertFalse(info["ready_ok"])
        self.assertEqual(salad_status.short_status(info), "Downloading 20%")


class SourceButton(unittest.TestCase):
    def test_config_has_check_button(self) -> None:
        src = (HERE / "app.py").read_text(encoding="utf-8")
        self.assertIn("Check Salad status", src)
        self.assertIn("_check_salad_status", src)
        self.assertIn("salad_status.snapshot_gateway", src)
        self.assertIn("_schedule_salad_poll", src)
        self.assertIn("silent=True", src)
        self.assertIn("w is not self", src)
        self.assertIn('text="Policy"', src)
        self.assertIn("generate_block_reason", src)
        self.assertIn("snapshot_gateway", src)
        self.assertIn("load_policy", src)
        self.assertIn("Load from Salad", src)
        self.assertIn("Apply to Salad", src)


class PolicyRoundtrip(unittest.TestCase):
    def test_policy_from_group_reads_probes(self) -> None:
        g = {
            "name": "flux2-klein",
            "version": 5,
            "startup_probe": {
                "http": {"path": "/health", "port": 3000},
                "initial_delay_seconds": 300,
                "period_seconds": 60,
                "timeout_seconds": 10,
                "failure_threshold": 20,
            },
            "readiness_probe": {
                "http": {"path": "/ready", "port": 3000},
                "initial_delay_seconds": 0,
                "period_seconds": 10,
                "timeout_seconds": 5,
                "failure_threshold": 20,
            },
        }
        pol = salad_status.policy_from_group(g)
        self.assertEqual(pol["group_name"], "flux2-klein")
        self.assertEqual(pol["startup"]["initial_delay_seconds"], 300)
        self.assertEqual(pol["startup"]["period_seconds"], 60)
        self.assertEqual(pol["readiness"]["path"], "/ready")
        blurb = salad_status.explain_probe("startup", pol["startup"])
        self.assertIn("300", blurb)
        self.assertIn("/health", blurb)
        self.assertIn("60", blurb)
        self.assertIn("20", blurb)
        self.assertIn(str(300 + 20 * 60), blurb)
        rblurb = salad_status.explain_probe("readiness", pol["readiness"])
        self.assertIn("/ready", rblurb)
        self.assertIn("10", rblurb)

    def test_load_policy_refetches_group(self) -> None:
        listed = {
            "items": [
                {
                    "name": "flux2-klein",
                    "networking": {
                        "dns": "persimmon-caraway-2tyczg3bbqh90fnp.salad.cloud"
                    },
                    "startup_probe": {
                        "http": {"path": "/health", "port": 3000},
                        "initial_delay_seconds": 60,
                        "period_seconds": 30,
                        "timeout_seconds": 10,
                        "failure_threshold": 20,
                    },
                }
            ]
        }
        fresh = {
            "name": "flux2-klein",
            "version": 5,
            "startup_probe": {
                "http": {"path": "/health", "port": 3000},
                "initial_delay_seconds": 300,
                "period_seconds": 60,
                "timeout_seconds": 10,
                "failure_threshold": 20,
            },
            "readiness_probe": {
                "http": {"path": "/ready", "port": 3000},
                "initial_delay_seconds": 0,
                "period_seconds": 10,
                "timeout_seconds": 5,
                "failure_threshold": 20,
            },
        }

        def _api(url, key):
            if url.endswith("/containers"):
                return 200, listed
            if url.endswith("/flux2-klein"):
                return 200, fresh
            return 404, {}

        with patch.object(salad_status, "_api_get", side_effect=_api):
            pol, err = salad_status.load_policy(
                "https://persimmon-caraway-2tyczg3bbqh90fnp.salad.cloud",
                "key",
            )
        self.assertIsNone(err)
        assert pol is not None
        self.assertEqual(pol["startup"]["initial_delay_seconds"], 300)
        self.assertEqual(pol["version"], 5)


class ApiGetDelegation(unittest.TestCase):
    """_api_get is the GET shorthand: one delegation to _api_request."""

    def test_api_get_delegates_to_api_request_with_get(self) -> None:
        url = "https://api.salad.com/api/public/organizations/life-sim/gpu-classes"
        reply = (200, {"items": [{"id": "rtx-4090"}]})
        with patch.object(salad_status, "_api_request", return_value=reply) as req:
            got = salad_status._api_get(url, "key")
        self.assertIs(got, reply)
        self.assertEqual(list(req.call_args.args), ["GET", url, "key"])
        self.assertEqual(req.call_args.kwargs, {})


if __name__ == "__main__":
    unittest.main()
