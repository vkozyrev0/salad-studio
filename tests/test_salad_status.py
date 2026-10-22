"""Config gateway -> Salad group status (no live API)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PKG = TOOLS / "salad_studio"
for p in (str(TOOLS), str(PKG)):
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
        self.assertEqual(salad_status.short_status(info), "Downloading 0%")
        block = salad_status.generate_block_reason(info)
        self.assertIsNotNone(block)
        self.assertIn("Docker", block or "")
        self.assertIn(
            "Downloading",
            salad_status.WORD_COLORS,
            "a percent word is coloured by the family it names",
        )

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
        self.assertIsNot(reason, None)
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
        self.assertEqual(salad_status.short_status(info), "Ready")
        self.assertNotEqual(
            salad_status.WORD_COLORS["Ready"], salad_status.WORD_COLORS["Failed"]
        )
        self.assertNotEqual(
            salad_status.WORD_COLORS["Ready"], salad_status.WORD_COLORS["Starting"]
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


class ContainerCounts(unittest.TestCase):
    """The compact strip's three counts, over snapshots the probe really builds.

    Every case goes through the shipped ``check_container``, so the mapping is
    driven by the snapshot shape the probe produces, not by a hand-written dict.
    """

    GW = "https://persimmon-caraway-2tyczg3bbqh90fnp.salad.cloud"
    GROUP = "flux2-klein"

    def _snapshot(self, *, replicas: int, state: str, instances: list) -> dict:
        group = {
            "name": self.GROUP,
            "display_name": "Flux2 Klein",
            "version": 4,
            "replicas": replicas,
            "current_state": {"status": state, "description": ""},
            "container": {"image": "docker.io/example:tag"},
            "networking": {"dns": self.GW.split("//")[1], "port": 3000},
        }

        def _api(url, key):
            if url.endswith("/instances"):
                return 200, {"instances": instances}
            if url.endswith("/containers"):
                return 200, {"items": [group]}
            return 200, group

        with patch.object(salad_status, "_api_get", side_effect=_api), patch.object(
            salad_status, "_req", return_value=(503, b"still booting")
        ):
            return salad_status.check_container(self.GW, "key")

    def test_a_ready_replica_counts_as_ready(self) -> None:
        info = self._snapshot(
            replicas=1,
            state="running",
            instances=[{"state": "running", "ready": True, "started": True}],
        )
        self.assertEqual(salad_status.container_counts(info), (1, 0, 0))

    def test_an_allocating_replica_counts_as_starting(self) -> None:
        info = self._snapshot(
            replicas=1,
            state="deploying",
            instances=[{"state": "allocating", "ready": False, "started": False}],
        )
        self.assertEqual(salad_status.container_counts(info), (0, 1, 0))

    def test_a_creating_replica_counts_as_starting(self) -> None:
        info = self._snapshot(
            replicas=1,
            state="deploying",
            instances=[{"state": "creating", "ready": False, "started": False}],
        )
        self.assertEqual(salad_status.container_counts(info), (0, 1, 0))

    def test_a_pulling_replica_counts_as_starting(self) -> None:
        info = self._snapshot(
            replicas=1,
            state="deploying",
            instances=[
                {
                    "state": "creating",
                    "ready": False,
                    "started": False,
                    "pulling_progress": 0.2,
                }
            ],
        )
        self.assertEqual(salad_status.container_counts(info), (0, 1, 0))

    def test_a_running_replica_that_is_not_serving_counts_as_starting(self) -> None:
        info = self._snapshot(
            replicas=1,
            state="running",
            instances=[{"state": "running", "ready": False, "started": True}],
        )
        self.assertEqual(salad_status.container_counts(info), (0, 1, 0))

    def test_a_stopped_group_with_one_replica_counts_as_non_started(self) -> None:
        info = self._snapshot(replicas=1, state="stopped", instances=[])
        self.assertEqual(salad_status.container_counts(info), (0, 0, 1))

    def test_a_failed_group_with_one_replica_counts_as_non_started(self) -> None:
        info = self._snapshot(replicas=1, state="failed", instances=[])
        self.assertEqual(salad_status.container_counts(info), (0, 0, 1))

    def test_two_replicas_one_ready_one_creating(self) -> None:
        info = self._snapshot(
            replicas=2,
            state="running",
            instances=[
                {"state": "running", "ready": True, "started": True},
                {"state": "creating", "ready": False, "started": False},
            ],
        )
        self.assertEqual(salad_status.container_counts(info), (1, 1, 0))

    def test_more_instances_than_replicas_never_goes_below_zero(self) -> None:
        info = self._snapshot(
            replicas=1,
            state="running",
            instances=[
                {"state": "running", "ready": True, "started": True},
                {"state": "running", "ready": False, "started": False},
            ],
        )
        self.assertEqual(salad_status.container_counts(info), (1, 1, 0))

    def test_a_gateway_with_no_group_contributes_nothing(self) -> None:
        with patch.object(salad_status, "_api_get", return_value=(200, {"items": []})):
            info = salad_status.check_container(self.GW, "key")
        self.assertIsNone(info["group"])
        self.assertEqual(salad_status.container_counts(info), (0, 0, 0))

    def test_an_api_error_contributes_nothing(self) -> None:
        with patch.object(salad_status, "_api_get", return_value=(500, {"error": "boom"})):
            info = salad_status.check_container(self.GW, "key")
        self.assertIn("HTTP 500", str(info["error"]))
        self.assertEqual(salad_status.container_counts(info), (0, 0, 0))

    def test_no_snapshot_at_all_contributes_nothing(self) -> None:
        self.assertEqual(salad_status.container_counts(None), (0, 0, 0))
        self.assertEqual(salad_status.strip_counts({}), (0, 0, 0))
        self.assertEqual(salad_status.strip_counts(None), (0, 0, 0))

    def test_the_strip_sums_every_profiles_snapshot(self) -> None:
        ready = self._snapshot(
            replicas=1,
            state="running",
            instances=[{"state": "running", "ready": True, "started": True}],
        )
        stopped = self._snapshot(replicas=1, state="stopped", instances=[])
        booting = self._snapshot(
            replicas=1,
            state="deploying",
            instances=[{"state": "creating", "ready": False, "started": False}],
        )
        self.assertEqual(
            salad_status.strip_counts({"a": ready, "b": stopped, "c": booting}),
            (1, 1, 1),
        )

    def test_the_three_dot_colours_are_distinct_and_are_the_word_colours(self) -> None:
        """The dots carry what the words carried: Ready green, amber, failed red."""
        colors = salad_status.STRIP_COLORS
        self.assertEqual(len(colors), 3)
        self.assertEqual(len(set(colors)), 3, f"the three dots must differ: {colors}")
        self.assertEqual(colors[0], salad_status.WORD_COLORS["Ready"])
        self.assertEqual(colors[1], salad_status.WORD_COLORS["Creating"])
        self.assertEqual(colors[2], salad_status.WORD_COLORS["Failed"])

        def rgb(hexcolor: str) -> tuple[int, int, int]:
            h = hexcolor.lstrip("#")
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        green, amber, red = (rgb(c) for c in colors)
        self.assertTrue(green[1] > green[0] and green[1] > green[2], f"green: {green}")
        self.assertTrue(amber[0] > amber[1] > amber[2], f"amber: {amber}")
        self.assertTrue(red[0] > red[1] and red[0] > red[2], f"red: {red}")


class SourceButton(unittest.TestCase):
    def test_the_server_has_the_check_action_and_the_strip_counts(self) -> None:
        services = (PKG / "web" / "services.py").read_text(encoding="utf-8")
        self.assertIn("salad_status.snapshot_gateway", services)
        self.assertIn("check_salad(silent=True)", services)
        shell = (PKG / "web" / "shell.py").read_text(encoding="utf-8")
        self.assertIn("salad_status.strip_counts", shell)
        controllers = (PKG / "web" / "controllers.py").read_text(encoding="utf-8")
        self.assertIn('"shell.check_salad"', controllers)

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
        self.assertIsNot(pol, None)
        self.assertEqual(pol["startup"]["initial_delay_seconds"], 300)
        self.assertEqual(pol["version"], 5)


class PolicyImage(unittest.TestCase):
    """Which image a config shows, and the fields it shows with no live read.

    The stored policies are built by the shipped ``policy_from_group``, so the
    nested startup/readiness/gpu_classes/country_codes shape under test is the
    one the module really produces.
    """

    DOC = "docker.io/vkozyrev0/eldermark-klein:prefetch6-klein"

    def _stored(self, image: str) -> dict:
        return salad_status.policy_from_group(
            {
                "name": "flux2-klein",
                "version": 5,
                "container": {
                    "image": image,
                    "resources": {"gpu_classes": ["rtx-5090", "rtx-4090"]},
                },
                "country_codes": ["US", "CA"],
                "startup_probe": {
                    "http": {"path": "/health", "port": 3000},
                    "initial_delay_seconds": 300,
                },
                "readiness_probe": {"http": {"path": "/ready", "port": 3000}},
            }
        )

    def test_the_live_image_wins_over_the_stored_one(self) -> None:
        self.assertEqual(
            salad_status.resolve_policy_image(
                self._stored("docker.io/example:stored"),
                self._stored("docker.io/example:live"),
                self.DOC,
            ),
            "docker.io/example:live",
        )

    def test_the_stored_image_answers_when_the_live_read_has_none(self) -> None:
        stored = self._stored("docker.io/example:stored")
        for live in (None, self._stored(""), {"image": "   "}):
            with self.subTest(live=live):
                self.assertEqual(
                    salad_status.resolve_policy_image(stored, live, self.DOC),
                    "docker.io/example:stored",
                )

    def test_the_documents_image_answers_when_neither_policy_has_one(self) -> None:
        for live in (None, {}, self._stored("")):
            with self.subTest(live=live):
                self.assertEqual(
                    salad_status.resolve_policy_image(self._stored(""), live, self.DOC),
                    self.DOC,
                )

    def test_nothing_anywhere_answers_empty(self) -> None:
        self.assertEqual(salad_status.resolve_policy_image({}, None, ""), "")
        self.assertEqual(salad_status.resolve_policy_image(None, {}, ""), "")

    def test_whitespace_is_not_an_image(self) -> None:
        self.assertEqual(
            salad_status.resolve_policy_image({"image": "   "}, None, self.DOC), self.DOC
        )
        self.assertEqual(
            salad_status.resolve_policy_image(None, {"image": "\t"}, ""), ""
        )

    def test_the_answer_is_stripped(self) -> None:
        self.assertEqual(
            salad_status.resolve_policy_image(
                {"image": f"  {self.DOC}  "}, None, ""
            ),
            self.DOC,
        )
        self.assertEqual(
            salad_status.resolve_policy_image(None, None, f"  {self.DOC} "), self.DOC
        )

    def test_it_survives_none_a_non_dict_and_a_non_string_image(self) -> None:
        for bad in (None, {}, {"image": 5}, {"image": None}, "not a dict", ["x"]):
            with self.subTest(bad=bad):
                self.assertEqual(salad_status.resolve_policy_image(bad, None, ""), "")
                self.assertEqual(salad_status.resolve_policy_image(None, bad, ""), "")
        self.assertEqual(
            salad_status.resolve_policy_image(None, {"image": 12}, self.DOC), self.DOC
        )

    def test_resolved_policy_fills_blanks_and_returns_a_fresh_copy(self) -> None:
        """What the Config page shows, from the shipped resolver.

        The stored policy is the base, the document fills a blank, and the result
        is a copy: the page edits what it shows, so no nested value may be shared
        with the record behind it.
        """
        stored = self._stored("")
        shown = salad_status.resolved_policy(stored, None, {"image": self.DOC})
        self.assertEqual(shown["image"], self.DOC, "a blank image takes the document's")
        self.assertEqual(shown["group_name"], "flux2-klein", "the stored field stands")
        self.assertEqual(shown["startup"]["path"], "/health")
        self.assertEqual(shown["readiness"]["path"], "/ready")
        self.assertIsNot(shown, stored)
        self.assertIsNot(shown["startup"], stored["startup"])
        self.assertIsNot(shown["readiness"], stored["readiness"])
        shown["startup"]["path"] = "/ping"
        shown["image"] = "docker.io/example:edited"
        self.assertEqual(stored["startup"]["path"], "/health", "the record is untouched")
        self.assertEqual(stored["image"], "")
        stored_image = self._stored("docker.io/example:stored")
        self.assertEqual(
            salad_status.resolved_policy(stored_image, None, {"image": self.DOC})["image"],
            "docker.io/example:stored",
            "a stored image beats the document's",
        )


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


class GroupLifecycleCalls(unittest.TestCase):
    """Stop names the group behind the gateway, and carries the stored token."""

    GW = "https://apple-gadogado-5d0vs4l8x0j51hwy.salad.cloud"
    HOST = "apple-gadogado-5d0vs4l8x0j51hwy.salad.cloud"
    GROUP = "flux2-klein2"

    def _group(self, status: str) -> dict:
        return {
            "name": self.GROUP,
            "networking": {"dns": self.HOST},
            "current_state": {"status": status},
        }

    def _sender(
        self,
        *,
        groups: list[dict] | None = None,
        action_code: int = 202,
        action_payload: Any | None = None,
        record: list | None = None,
    ):
        listed = groups if groups is not None else [self._group("stopped")]

        def send(method, url, key, data=None):
            if record is not None:
                record.append((method, url, key, data))
            if url.endswith("/containers"):
                return 200, {"items": listed}
            if url.endswith("/start") or url.endswith("/stop"):
                return action_code, ({} if action_payload is None else action_payload)
            return 404, {"error": "not found"}

        return send

    def _url(self, action: str) -> str:
        return (
            f"{salad_status.API}/organizations/{salad_status.ORG}/projects/"
            f"{salad_status.PROJECT}/containers/{self.GROUP}/{action}"
        )

    def test_stop_names_the_resolved_group(self) -> None:
        calls: list = []
        life = salad_status.ContainerLifecycle(lambda: "k", sender=self._sender(record=calls))
        code, _message = life.stop("klein", self.GW)
        self.assertEqual(code, 202)
        self.assertEqual(
            [call for call in calls if call[0] == "POST"][0][1], self._url("stop")
        )

    def test_a_non_2xx_answer_comes_back_as_its_status_and_message(self) -> None:
        sender = self._sender(
            action_code=403, action_payload={"error": {"message": "quota exceeded"}}
        )
        code, message = salad_status.ContainerLifecycle(lambda: "k", sender=sender).stop(
            "klein", self.GW
        )
        self.assertEqual(code, 403)
        self.assertIn("quota exceeded", message)

    def test_a_gateway_with_no_group_is_refused_without_calling_the_action(self) -> None:
        calls: list = []
        life = salad_status.ContainerLifecycle(
            lambda: "k", sender=self._sender(groups=[], record=calls)
        )
        code, message = life.stop("klein", self.GW)
        self.assertEqual(code, 404)
        self.assertIn("No container group", message)
        self.assertEqual([call for call in calls if call[0] == "POST"], [])

    def test_group_is_running_reads_the_groups_own_state(self) -> None:
        for status, want in (
            ("stopped", False),
            ("running", True),
            ("pending", None),
            ("failed", None),
        ):
            with self.subTest(status=status):
                sender = self._sender(groups=[self._group(status)])
                self.assertIs(
                    salad_status.group_is_running(self.GW, "k", sender=sender), want
                )

    def test_group_is_running_is_unknown_without_a_matching_group(self) -> None:
        other = {
            "name": "someone-elses-group",
            "networking": {"dns": "other.example.salad.cloud"},
            "current_state": {"status": "running"},
        }
        self.assertIsNone(
            salad_status.group_is_running(
                self.GW, "k", sender=self._sender(groups=[other])
            ),
            "a group that is not this gateway's says nothing about this gateway",
        )
        self.assertIsNone(salad_status.group_is_running("", "k", sender=self._sender()))

    def test_the_lifecycle_client_resolves_the_group_from_the_gateway(self) -> None:
        calls: list = []
        life = salad_status.ContainerLifecycle(lambda: "tok", sender=self._sender(record=calls))
        code, message = life.stop("klein", self.GW)
        self.assertEqual((code, message), (202, ""))
        posts = [call for call in calls if call[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertTrue(
            posts[0][1].endswith(f"/containers/{self.GROUP}/stop"),
            f"the group came from the DNS, not the profile name: {posts[0][1]}",
        )
        self.assertNotIn("/klein/", posts[0][1])

    def test_the_lifecycle_client_reports_a_missing_token_as_a_refusal(self) -> None:
        life = salad_status.ContainerLifecycle(lambda: "", sender=self._sender())
        self.assertEqual(life.stop("klein", self.GW), (401, "no Salad token is stored"))
        self.assertIsNone(life.is_running("klein", self.GW))

    def test_the_lifecycle_client_survives_a_key_provider_that_raises(self) -> None:
        def broken() -> str:
            raise FileNotFoundError("no key file")

        life = salad_status.ContainerLifecycle(broken, sender=self._sender())
        self.assertEqual(life.stop("klein", self.GW)[0], 401)
        self.assertIsNone(life.is_running("klein", self.GW))

    def test_the_lifecycle_client_carries_the_servers_message(self) -> None:
        life = salad_status.ContainerLifecycle(
            lambda: "tok",
            sender=self._sender(
                action_code=403, action_payload={"error": {"message": "quota exceeded"}}
            ),
        )
        code, message = life.stop("klein", self.GW)
        self.assertEqual(code, 403)
        self.assertIn("quota exceeded", message)

    def test_a_profile_with_no_gateway_is_refused_without_a_call(self) -> None:
        calls: list = []
        life = salad_status.ContainerLifecycle(lambda: "tok", sender=self._sender(record=calls))
        code, message = life.stop("klein", "")
        self.assertEqual(code, 404)
        self.assertIn("no gateway", message)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
