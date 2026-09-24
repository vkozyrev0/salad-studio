"""The Klein prompt catalog cannot drift from what was run.

``salad_klein/prompt_catalog.json`` quotes prompt text out of the
recipe files (and, for candidates, out of the ledger). This module re-reads both
sides and enforces the three invariants the catalog rests on:

1. **Text** — every catalogued prompt equals the text at the source it names: the
   named node of the named recipe file, or the ledger pointer for a candidate.
2. **Well-formedness** — every catalogued recipe parses as a Comfy ``/prompt``
   payload and every node edge in it resolves to a node present in that graph.
3. **Coverage** — every ledger entry a human judged ``good`` appears in the
   catalog, and nothing appears in the catalog without such a verdict. A
   candidate is recorded with an explicit "not a success" warning.

**Not** ``test_prompt_catalog.py`` — that one covers the runtime Prompt Catalog
*store* (``salad_studio/prompt_catalog.py``, the user's named request JSONs under
``~/.config/salad/``). This module is about the in-repo Klein artifact.

Run from the repo root::

    python -m unittest salad_studio.test_klein_prompt_catalog

The check is meant to have teeth: mutating a character inside a catalogued prompt
or pointing an entry at a recipe that lacks that text must fail it.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for p in (str(TOOLS), str(HERE)):
    if str(p) not in sys.path:
        sys.path.insert(0, p)

from salad_studio import comfy_import as ci  # noqa: E402
from salad_studio import json_highlight  # noqa: E402

REPO = TOOLS  # the tool's own root; salad_klein/ sits beside the package
KLEIN = TOOLS / "salad_klein"
CATALOG = KLEIN / "prompt_catalog.json"
LEDGER = KLEIN / "prompt_ledger.json"

# Edges are [node_id, output_slot]; the first element must name a node.
EDGE_SLOTS = (0, 1)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_pointer(doc: object, pointer: str) -> object:
    """RFC-6901-ish pointer: ``/a/0/b`` into a loaded JSON document."""
    cur = doc
    for raw in [p for p in pointer.split("/") if p != ""]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            cur = cur[int(token)]
        elif isinstance(cur, dict):
            cur = cur[token]
        else:  # pragma: no cover - a malformed pointer in the artifact
            raise AssertionError(f"pointer {pointer!r} ran off the document at {token!r}")
    return cur


def _edges(node: dict) -> list[tuple[str, object]]:
    """Every ``[node_id, slot]`` input on a node, with its input name."""
    out = []
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        return out
    for name, value in inputs.items():
        if (
            isinstance(value, list)
            and len(value) == 2
            and isinstance(value[0], str)
            and value[1] in EDGE_SLOTS
        ):
            out.append((name, value))
    return out


class CatalogShape(unittest.TestCase):
    def test_catalog_is_present_and_parses(self) -> None:
        self.assertTrue(CATALOG.is_file(), f"missing {CATALOG}")
        doc = _load(CATALOG)
        self.assertEqual(doc["schema"], 1)
        self.assertIn("operating_point", doc)
        self.assertTrue(doc["entries"], "the catalog has no verified entries")

    def test_every_entry_carries_what_the_reader_needs(self) -> None:
        for entry in _load(CATALOG)["entries"]:
            with self.subTest(entry=entry.get("id")):
                for field in (
                    "id", "status", "recipe", "positive_node", "negative_node",
                    "positive", "negative", "graph", "seeds",
                ):
                    self.assertIn(field, entry, field)
                self.assertEqual(entry["status"], "verified")
                self.assertTrue(entry["positive"].strip(), "empty positive prompt")
                self.assertTrue(entry["negative"].strip(), "empty negative prompt")
                self.assertTrue(entry["seeds"], "no seeds recorded")

    def test_a_verified_entry_has_a_good_seed_with_verdict_words(self) -> None:
        """A 'success' without a human's own words is not a success."""
        for entry in _load(CATALOG)["entries"]:
            with self.subTest(entry=entry.get("id")):
                good = [s for s in entry["seeds"] if s["verdict"] == "good"]
                self.assertTrue(good, "no seed judged good")
                for row in good:
                    self.assertTrue(
                        (row.get("user_verdict") or "").strip(),
                        f"seed {row['seed']} is 'good' with no verdict words",
                    )

    def test_candidates_are_labelled_and_never_presented_as_successes(self) -> None:
        for cand in _load(CATALOG).get("candidates", []):
            with self.subTest(candidate=cand.get("id")):
                self.assertEqual(cand["status"], "candidate-unverified")
                self.assertIn("NOT", cand["warning"])


class TextMatchesItsSource(unittest.TestCase):
    """(a) each catalogued prompt's text equals the source it names."""

    def test_each_prompt_equals_its_recipe_node(self) -> None:
        for entry in _load(CATALOG)["entries"]:
            with self.subTest(entry=entry["id"]):
                recipe = REPO / entry["recipe"]
                self.assertTrue(recipe.is_file(), f"missing recipe {recipe}")
                prompt = _load(recipe)["prompt"]
                for field, node_key in (
                    ("positive", "positive_node"),
                    ("negative", "negative_node"),
                ):
                    node = entry[node_key]
                    self.assertIn(node, prompt, f"node {node} is not in {entry['recipe']}")
                    self.assertEqual(
                        prompt[node]["inputs"]["text"],
                        entry[field],
                        f"{entry['id']}.{field} no longer matches node {node} of {entry['recipe']}",
                    )

    def test_each_candidate_prompt_equals_its_ledger_pointer(self) -> None:
        ledger = _load(LEDGER)
        for cand in _load(CATALOG).get("candidates", []):
            self.assertEqual(cand["source"], "salad_klein/prompt_ledger.json")
            with self.subTest(candidate=cand["id"]):
                self.assertEqual(
                    _resolve_pointer(ledger, cand["negative_pointer"]), cand["negative"]
                )
                for row in cand["prompts"]:
                    self.assertEqual(
                        _resolve_pointer(ledger, row["ledger_pointer"]),
                        row["text"],
                        f"{cand['id']}.{row['id']} drifted from the ledger",
                    )

    def test_operating_point_matches_the_ledger(self) -> None:
        self.assertEqual(_load(CATALOG)["operating_point"], _load(LEDGER)["graph"])

    def test_the_entry_graph_matches_its_recipe(self) -> None:
        for entry in _load(CATALOG)["entries"]:
            with self.subTest(entry=entry["id"]):
                prompt = _load(REPO / entry["recipe"])["prompt"]
                g = entry["graph"]
                unet = next(n for n in prompt.values() if n.get("class_type") == "UNETLoader")
                sched = next(n for n in prompt.values() if n.get("class_type") == "Flux2Scheduler")
                guid = next(n for n in prompt.values() if n.get("class_type") == "CFGGuider")
                sel = next(n for n in prompt.values() if n.get("class_type") == "KSamplerSelect")
                self.assertEqual(g["unet"], unet["inputs"]["unet_name"])
                self.assertEqual(g["steps"], sched["inputs"]["steps"])
                self.assertEqual(g["cfg"], guid["inputs"]["cfg"])
                self.assertEqual(g["sampler"], sel["inputs"]["sampler_name"])
                loras = [
                    nid for nid, n in prompt.items()
                    if isinstance(n, dict) and str(n.get("class_type", "")).startswith("LoraLoader")
                ]
                self.assertEqual([row["node"] for row in g["loras"]], sorted(loras, key=int))


class RecipesAreWellFormed(unittest.TestCase):
    """(b) every catalogued recipe is a valid Comfy payload with resolving edges."""

    def _recipes(self) -> list[Path]:
        paths = [REPO / e["recipe"] for e in _load(CATALOG)["entries"]]
        return sorted(set(paths))

    def test_each_recipe_passes_the_editor_gate(self) -> None:
        for path in self._recipes():
            with self.subTest(recipe=path.name):
                ok, msg = json_highlight.verify_request_json(path.read_text(encoding="utf-8"))
                self.assertTrue(ok, f"{path.name}: {msg}")

    def test_every_node_edge_resolves(self) -> None:
        for path in self._recipes():
            with self.subTest(recipe=path.name):
                prompt = _load(path)["prompt"]
                ids = set(prompt)
                dangling = [
                    (nid, name, edge)
                    for nid, node in prompt.items()
                    if isinstance(node, dict)
                    for name, edge in _edges(node)
                    if edge[0] not in ids
                ]
                self.assertEqual(dangling, [], f"{path.name} has dangling edges")

    def test_every_recipe_has_exactly_one_save_image_sink(self) -> None:
        for path in self._recipes():
            with self.subTest(recipe=path.name):
                prompt = _load(path)["prompt"]
                sinks = [
                    nid for nid, n in prompt.items()
                    if isinstance(n, dict) and n.get("class_type") == "SaveImage"
                ]
                self.assertEqual(len(sinks), 1, f"{path.name}: SaveImage sinks {sinks}")

    def test_the_post_copy_keeps_the_prompt_text(self) -> None:
        """The text the replica is asked for is the text the catalog quotes."""
        for entry in _load(CATALOG)["entries"]:
            with self.subTest(entry=entry["id"]):
                posted = ci.prompt_for_salad_replica(_load(REPO / entry["recipe"])["prompt"])
                self.assertEqual(
                    posted[entry["positive_node"]]["inputs"]["text"], entry["positive"]
                )
                self.assertEqual(
                    posted[entry["negative_node"]]["inputs"]["text"], entry["negative"]
                )


class LedgerCoverage(unittest.TestCase):
    """(c) every human 'good' verdict is catalogued, and nothing else is."""

    def test_every_good_verdict_appears_in_the_catalog(self) -> None:
        ledger = _load(LEDGER)
        catalogued = {e["id"] for e in _load(CATALOG)["entries"]}
        for verdict in ledger.get("verdicts", []):
            if verdict.get("status") != "good":
                continue
            with self.subTest(verdict=verdict.get("id")):
                self.assertIn(
                    verdict["id"], catalogued,
                    f"{verdict['id']} is judged good but is not in the catalog",
                )

    def test_every_catalogued_entry_has_a_good_ledger_verdict(self) -> None:
        ledger = _load(LEDGER)
        good = {
            v["id"] for v in ledger.get("verdicts", []) if v.get("status") == "good"
        }
        for entry in _load(CATALOG)["entries"]:
            with self.subTest(entry=entry["id"]):
                self.assertIn(entry["id"], good, "catalogued without a human verdict")

    def test_a_ledger_candidate_is_not_a_catalog_entry(self) -> None:
        ledger = _load(LEDGER)
        entry_ids = {e["id"] for e in _load(CATALOG)["entries"]}
        for cand in ledger.get("candidates", []):
            with self.subTest(candidate=cand.get("id")):
                self.assertNotIn(cand["id"], entry_ids, "a candidate was promoted to an entry")


if __name__ == "__main__":
    unittest.main()
