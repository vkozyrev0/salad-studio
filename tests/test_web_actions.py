"""The action table: one name per request, and a refusal that costs nothing.

The server's contract is a flat table of action names. A request that names an
action the table lacks is refused by the server before it touches a store, and
the same goes for a payload with a missing or mistyped field. Tests here work on
a stand-in table so they can check the table's rules without a store on disk.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio.web import actions  # noqa: E402


class RegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[dict] = []
        self.registry = actions.Registry()

        @self.registry.action("tokens.read")
        def _read(payload: dict) -> dict:
            self.calls.append(payload)
            return {"value": "secret"}

        @self.registry.action("tokens.save", need={"slot": str, "value": str})
        def _save(payload: dict) -> dict:
            self.calls.append(payload)
            return {"saved": payload["slot"]}

    def test_an_unknown_action_is_refused_without_running_anything(self) -> None:
        result = self.registry.call("tokens.nope", {})
        self.assertEqual(result.error.kind, "unknown_action")
        self.assertEqual(self.calls, [])

    def test_a_missing_field_is_refused_and_names_the_field(self) -> None:
        result = self.registry.call("tokens.save", {"slot": "salad"})
        self.assertEqual(result.error.kind, "bad_payload")
        self.assertEqual(result.error.field, "value")
        self.assertEqual(self.calls, [])

    def test_a_field_of_the_wrong_type_is_refused_and_names_the_field(self) -> None:
        result = self.registry.call("tokens.save", {"slot": "salad", "value": 7})
        self.assertEqual(result.error.kind, "bad_payload")
        self.assertEqual(result.error.field, "value")
        self.assertIn("str", result.error.message)
        self.assertEqual(self.calls, [])

    def test_a_bool_is_not_text(self) -> None:
        result = self.registry.call("tokens.save", {"slot": "salad", "value": True})
        self.assertEqual(result.error.kind, "bad_payload")

    def test_a_well_formed_call_runs_once_with_only_the_named_fields(self) -> None:
        result = self.registry.call("tokens.save", {"slot": "salad", "value": "k", "extra": 1})
        self.assertEqual(result.error, None)
        self.assertEqual(result.data, {"saved": "salad"})
        self.assertEqual(self.calls, [{"slot": "salad", "value": "k"}])

    def test_an_action_with_no_contract_passes_the_payload_through(self) -> None:
        result = self.registry.call("tokens.read", {"anything": 1})
        self.assertEqual(result.error, None)
        self.assertEqual(result.data, {"value": "secret"})

    def test_two_actions_of_one_name_is_refused_at_registration(self) -> None:
        with self.assertRaises(actions.DuplicateAction):
            @self.registry.action("tokens.read")
            def _again(_payload: dict) -> dict:
                return {}


class ErrorMappingTest(unittest.TestCase):
    """A refusal a page shows to a person keeps its text; an unplanned one does not leak."""

    def test_a_refusal_carries_the_message_the_page_shows(self) -> None:
        err = actions.to_error(ValueError("A profile needs a name"))
        self.assertEqual(err.kind, "refused")
        self.assertEqual(err.message, "A profile needs a name")

    def test_an_unplanned_failure_is_reported_without_its_text(self) -> None:
        err = actions.to_error(KeyError("SECRET_TOKEN"))
        self.assertEqual(err.kind, "failed")
        self.assertNotIn("SECRET_TOKEN", err.message)

    def test_an_os_error_keeps_its_message(self) -> None:
        err = actions.to_error(FileNotFoundError("no such file: profiles.json"))
        self.assertEqual(err.kind, "refused")
        self.assertIn("profiles.json", err.message)


if __name__ == "__main__":
    unittest.main()
