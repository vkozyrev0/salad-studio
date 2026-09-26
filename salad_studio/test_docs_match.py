"""The manuals must describe the app that shipped.

Three checks, each reading the real file and comparing it with the shipped
code: the app manual's tab list against ``app.TAB_ORDER``, the manual's layer
map against the modules on disk, and the root README's test count against the
number of test methods the suite actually has. A doc that drifts fails here
instead of being discovered by a reader.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for _p in (HERE, TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import salad_queue as q  # noqa: E402
import studio_meta  # noqa: E402
from salad_studio import app as app_mod  # noqa: E402

MANUAL = HERE / "README.md"
ROOT_README = TOOLS / "README.md"


class TabListMatchesTheApp(unittest.TestCase):
    def test_the_manual_lists_every_tab_in_order(self) -> None:
        text = MANUAL.read_text(encoding="utf-8")
        head = text.split("## Layers", 1)[0]
        start = head.index("**Config**")
        block = head[start : head.index(").", start)]
        listed = re.findall(r"\*\*([^*]+)\*\*", block)
        self.assertEqual(
            listed,
            list(app_mod.TAB_ORDER),
            "the manual's tab list must be the app's tab order",
        )

    def test_the_manual_documents_the_queue_page(self) -> None:
        text = MANUAL.read_text(encoding="utf-8")
        self.assertIn("- **Queue**.", text)
        for word in ("Cancel selected", "Retry selected", "Clear finished"):
            self.assertIn(word, text)


class LayerMapMatchesTheModules(unittest.TestCase):
    def test_every_module_the_map_names_exists(self) -> None:
        text = MANUAL.read_text(encoding="utf-8")
        section = text.split("## Layers", 1)[1].split("### Metadata document", 1)[0]
        named = sorted(set(re.findall(r"`([a-z_]+\.py)`", section)))
        self.assertTrue(named, "the layer map names no modules")
        for module in named:
            where = TOOLS if module == "salad_gen.py" else HERE
            self.assertTrue(
                (where / module).is_file(),
                f"the layer map names {module}, which is not in {where.name}/",
            )

    def test_every_module_in_the_package_is_mapped(self) -> None:
        text = MANUAL.read_text(encoding="utf-8")
        section = text.split("## Layers", 1)[1].split("### Metadata document", 1)[0]
        named = set(re.findall(r"`([a-z_]+\.py)`", section))
        shipped = {p.name for p in HERE.glob("*.py")}
        shipped -= {p.name for p in HERE.glob("test_*.py")}
        shipped.discard("__init__.py")
        missing = sorted(shipped - named)
        self.assertEqual(missing, [], f"the layer map does not name: {missing}")


class RootReadmeTestCount(unittest.TestCase):
    def test_the_stated_test_count_is_the_real_one(self) -> None:
        text = ROOT_README.read_text(encoding="utf-8")
        match = re.search(r"#\s*(\d+)\s+tests", text)
        self.assertIsNotNone(match, "the quick start no longer states a test count")
        stated = int(match.group(1))
        real = 0
        for path in sorted(HERE.glob("test_*.py")):
            real += len(re.findall(r"^\s+def test_", path.read_text(encoding="utf-8"), re.M))
        self.assertEqual(
            stated,
            real,
            f"the root README says {stated} tests; the suite has {real}",
        )


AUDIT = TOOLS / "docs" / "history" / "59-salad-studio-audit-2026-09-26.md"


class AuditDocument(unittest.TestCase):
    """The audit is an artifact, and its 'fixed' claims are checked here."""

    AREAS = ("app", "layer", "docs", "test", "ui")

    def _text(self) -> str:
        self.assertTrue(AUDIT.is_file(), f"the audit is missing: {AUDIT}")
        return AUDIT.read_text(encoding="utf-8")

    def test_the_audit_names_all_five_areas(self) -> None:
        text = self._text().lower()
        for area in self.AREAS:
            self.assertIn(area, text, f"the audit does not cover {area}")

    def test_every_finding_cites_a_file_and_is_fixed_or_deferred(self) -> None:
        text = self._text()
        findings = re.findall(r"^### ([A-Z]\d+), ([^\n]*)$", text, re.M)
        self.assertGreaterEqual(len(findings), 10, "too few findings to be an audit")
        for tag, title in findings:
            self.assertRegex(
                title,
                r"(FIXED|DEFERRED)",
                f"finding {tag} is neither fixed nor deferred",
            )
            body = text.split(f"### {tag},", 1)[1].split("\n### ", 1)[0]
            self.assertRegex(
                body,
                r"`[^`]*\.(py|md|json)|docs/workflow/\d+",
                f"finding {tag} cites no file",
            )

    def test_three_fixed_findings_hold_in_the_shipped_code(self) -> None:
        from salad_studio import profiles

        confirmations: list[str] = []

        # A1: the queue page is in the tab set and renders a tree.
        self.assertIn("Queue", app_mod.TAB_ORDER)
        self.assertTrue(hasattr(app_mod.SaladStudio, "_build_queue_tab"))
        confirmations.append(f"A1 queue page in TAB_ORDER at {app_mod.TAB_ORDER.index('Queue')}")

        # A3: the dead routing helpers are gone.
        self.assertFalse(hasattr(profiles, "routing_conflict"))
        self.assertFalse(hasattr(profiles, "profile_for_family"))
        confirmations.append("A3 profiles.routing_conflict / profile_for_family removed")

        # L1: the queue carries the management operations.
        for name in ("cancel", "retry", "clear_finished", "job_by_id"):
            self.assertTrue(hasattr(q.SaladQueue, name), f"SaladQueue.{name} is missing")
        confirmations.append("L1 SaladQueue.cancel / retry / clear_finished / job_by_id exist")

        # L3: the metadata document names the current klein image tag.
        doc = studio_meta.load()
        image = studio_meta.image_for_family("klein", doc)
        self.assertIn("prefetch6-klein", image)
        confirmations.append(f"L3 studio-metadata.json klein image = {image}")

        # D2: the root README names the dependency the app imports.
        root = ROOT_README.read_text(encoding="utf-8")
        self.assertIn("tkwry", root)
        self.assertNotIn("`requests`", root)
        confirmations.append("D2 root README requirements name tkwry, not requests")

        for line in confirmations:
            print(f"audit fixed finding confirmed: {line}")
        self.assertEqual(len(confirmations), 5)


AUDIT = TOOLS / "docs" / "history" / "59-salad-studio-audit-2026-09-26.md"
SKILL = TOOLS / ".claude" / "skills" / "civitai-verify" / "SKILL.md"

# The skill's prose name for each class the ablation order puts in a family, so
# the order can be read from ablate_candidates() instead of restated here.
ABLATE_ORDER_TOKENS = (
    ("LoraLoader", "LoRAs"),
    ("CLIPTextEncode", "CLIP encodes"),
    ("UNETLoader", "UNET"),
)
# The journal contract: the step and skip strings the skill names must be the
# ones the driver writes.
JOURNAL_STRINGS = (
    "container-list",
    "audit-clip",
    "audit-loras",
    "pending_local_describe",
    "prompt-edit",
    "no mechanical import-code fix for these issues",
    "edit_import is off; conversion code was not modified",
)


class SkillMatchesTheCode(unittest.TestCase):
    """The skill's facts are the code's facts, and each has one home."""

    @classmethod
    def setUpClass(cls) -> None:
        from salad_studio import civitai_verify as cv

        cls.cv = cv
        cls.text = SKILL.read_text(encoding="utf-8")

    def _section(self, heading: str) -> str:
        self.assertIn(heading, self.text, f"the skill lost its {heading!r} section")
        return self.text.split(heading, 1)[1]

    @staticmethod
    def _flat(text: str) -> str:
        """The prose with its line wrapping removed, so phrases can be matched."""
        return " ".join(text.split())

    def test_the_skill_still_parses_as_a_skill(self) -> None:
        self.assertTrue(self.text.startswith("---\n"), "the frontmatter is gone")
        front = self.text.split("---\n", 2)[1]
        self.assertIn("name: civitai-verify", front)
        self.assertIn("description:", front)
        for heading in ("## Run", "| Flag | Meaning |", "## What the POST meets", "## Agent loop", "## Journal"):
            self.assertIn(heading, self.text)

    def test_the_description_matches_the_opt_in_design(self) -> None:
        front = self.text.split("---\n", 2)[1]
        self.assertNotIn("auto-fix", front, "the description promises automatic fixing")
        self.assertIn("--edit-import", front, "the description must name the opt-in flag")

    def test_every_flag_is_documented_and_exists(self) -> None:
        parser = self.cv.build_arg_parser()
        known = {opt for action in parser._actions for opt in action.option_strings}
        named = set(re.findall(r"`(--[a-z-]+)", self.text))
        self.assertTrue(named)
        self.assertEqual(sorted(named - known), [], "the skill documents flags the CLI does not have")
        missing = sorted(
            (known - named) - {"-h", "--help", "--site-description", "--generated-description"}
        )
        self.assertEqual(missing, [], "the CLI has flags the skill never mentions")
        # --site-description / --generated-description are named in prose without
        # a table row; they must still appear somewhere in the skill.
        for flag in ("--site-description", "--generated-description"):
            self.assertIn(flag, self.text)

    def test_the_retry_cap_and_ablation_default_come_from_the_cli(self) -> None:
        parser = self.cv.build_arg_parser()
        defaults = {
            opt: action.default
            for action in parser._actions
            for opt in action.option_strings
            if opt.startswith("--")
        }
        self.assertIn(
            f"default **{self.cv.MAX_ATTEMPTS}**", self.text, "the table's retry cap is not the CLI's"
        )
        self.assertEqual(defaults["--max-attempts"], self.cv.MAX_ATTEMPTS)
        self.assertIn(
            f"default {defaults['--max-ablate']}",
            self.text,
            "the table's --max-ablate default is not the CLI's",
        )

    def test_the_ablation_order_matches_ablate_candidates(self) -> None:
        body = {
            "prompt": {
                "1": {"class_type": "UNETLoader"},
                "2": {"class_type": "LoraLoader"},
                "3": {"class_type": "CLIPTextEncode"},
                "4": {"class_type": "KSampler"},
                "5": {"class_type": "SaveImage"},
            }
        }
        order = [cls for _nid, cls in self.cv.ablate_candidates(body)]
        row = [line for line in self.text.splitlines() if line.startswith("| `--ablate`")][0]
        code_rank = {cls: order.index(cls) for cls, _prose in ABLATE_ORDER_TOKENS}
        prose_rank = {prose: row.index(prose) for _cls, prose in ABLATE_ORDER_TOKENS}
        self.assertEqual(
            sorted(code_rank, key=code_rank.get),
            ["LoraLoader", "CLIPTextEncode", "UNETLoader"],
            "ablate_candidates no longer runs LoRAs, then CLIP, then the rest",
        )
        self.assertEqual(
            sorted(prose_rank, key=prose_rank.get),
            ["LoRAs", "CLIP encodes", "UNET"],
            "the table's ablation order is not the code's",
        )

    def test_the_journal_strings_are_the_drivers(self) -> None:
        source = (HERE / "civitai_verify.py").read_text(encoding="utf-8")
        for text in JOURNAL_STRINGS:
            self.assertIn(text, self.text, f"the skill no longer names {text!r}")
            self.assertIn(text, source, f"the driver no longer writes {text!r}")

    def test_the_queue_facts_come_from_salad_queue(self) -> None:
        section = self._section("## What the POST meets")
        flat = self._flat(section)
        statuses = re.findall(r"`(\d{3})`", flat.split("or a transport", 1)[0])
        self.assertEqual(
            [int(s) for s in statuses],
            list(q.BUSY_CODES),
            "the statuses the skill retries on are not salad_queue.BUSY_CODES",
        )
        self.assertIn("salad_queue.shared()", flat)
        self.assertIn("MAX_ATTEMPTS", flat, "the cap must point at the constant, not a number")
        self.assertIn("RETRY_SLEEP_S", flat, "the backoff must point at the constant")
        self.assertIn("studio_meta", flat, "routing's source must be named")
        for terminal in ("504", "524"):
            self.assertIn(terminal, flat, f"{terminal} must be named as terminal")
        self.assertIn("in-flight Studio render", flat)

    def test_the_test_command_is_the_repos_documented_one(self) -> None:
        documented = re.search(
            r'python -m unittest discover -s salad_studio -p "test_\*\.py"',
            ROOT_README.read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(documented, "the root README no longer documents the suite command")
        self.assertIn(documented.group(0), self.text)
        self.assertNotIn(
            "test_comfy_import salad_studio", self.text, "the three-module list is back"
        )

    def test_each_duplicated_fact_has_one_home(self) -> None:
        flat = self._flat(self.text)
        counts = {
            # The flag table owns the values.
            "default **5**": 1,
            "LoRAs, then CLIP encodes": 1,
            # One prose home each for the behaviors.
            "not the end": 1,
            "it is the only path that touches prompt text": 1,
        }
        for phrase, expected in counts.items():
            self.assertEqual(
                flat.count(phrase), expected, f"{phrase!r} appears {flat.count(phrase)}x"
            )
        gone = (
            "Prompt edits are opt-in",
            "unless `--allow-prompt-edit` is set",
            "not a dead stop",
            "Captions try xAI vision",
            "MAX_ATTEMPTS` (5)",
            "CLIP encodes, then the rest",
        )
        for phrase in gone:
            self.assertNotIn(phrase, flat, f"the deleted restatement {phrase!r} is back")


if __name__ == "__main__":
    unittest.main()
