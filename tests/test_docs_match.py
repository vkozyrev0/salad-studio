"""The manuals must describe the app that shipped.

Every check below reads a real file and compares it with the shipped code: the
app manual's tab list against ``app.TAB_ORDER``, the manual's layer map against
the modules on disk, the stated test counts — the root suite and the
container-side one — against the number of test methods the suites actually
have, the workflow documents' ``§N`` references against the headings of the
documents they name, and the dated audits' FIXED claims against the code that
ships. A doc that drifts fails here instead of being discovered by a reader.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PKG = TOOLS / "salad_studio"
for _p in (PKG, TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import salad_queue as q  # noqa: E402
import studio_meta  # noqa: E402
from salad_studio import flet_shell  # noqa: E402

MANUAL = PKG / "README.md"
ROOT_README = TOOLS / "README.md"
DEPLOYMENT = TOOLS / "docs" / "workflow" / "23-salad-container-group-deployment.md"
# The container-side suite, and the one live doc that states a count for the
# root-suite recipe module. `salad_klein/README.md` documents both commands.
KLEIN = TOOLS / "salad_klein"
KLEIN_README = KLEIN / "README.md"
FLUX2_DOC = TOOLS / "docs" / "workflow" / "15-salad-flux2-klein-group.md"
HANDOFF = TOOLS / "docs" / "workflow" / "21-klein-image-handoff.md"


class TabListMatchesTheApp(unittest.TestCase):
    def test_the_manual_lists_every_tab_in_order(self) -> None:
        text = MANUAL.read_text(encoding="utf-8")
        head = text.split("## Layers", 1)[0]
        start = head.index("**Config**")
        block = head[start : head.index(").", start)]
        listed = re.findall(r"\*\*([^*]+)\*\*", block)
        self.assertEqual(
            listed,
            list(flet_shell.TAB_ORDER),
            "the manual's tab list must be the app's tab order",
        )

    def test_the_manual_documents_the_queue_page(self) -> None:
        text = " ".join(MANUAL.read_text(encoding="utf-8").split())
        self.assertIn("- **Queue**.", text)
        for word in ("Cancel selected", "Retry selected", "Clear finished"):
            self.assertIn(word, text)

    def test_the_manual_documents_the_container_lifecycle(self) -> None:
        """The queue stops idle containers and never starts one, and says so."""
        from salad_studio import salad_status

        manual = " ".join(MANUAL.read_text(encoding="utf-8").split())
        queue_bullet = manual.split("- **Queue**.", 1)[1].split("Klein group,", 1)[0]
        self.assertIn(
            studio_meta.IDLE_STOP,
            manual,
            "the manual must name the document's idle setting",
        )
        self.assertIn(f"{studio_meta.DEFAULT_IDLE_STOP_S}", manual)
        # The app stops through the lifecycle handle, and nothing in it starts a
        # container: the module-level start/stop wrappers are gone with it.
        self.assertTrue(
            hasattr(salad_status.ContainerLifecycle, "stop"),
            "the lifecycle handle lost its stop",
        )
        self.assertFalse(
            hasattr(salad_status, "stop_container_group"),
            "a module-level stop wrapper came back: ContainerLifecycle is the API",
        )
        self.assertFalse(
            hasattr(salad_status, "start_container_group"),
            "a start call came back: nothing in the app may start a container",
        )
        self.assertFalse(
            hasattr(salad_status.ContainerLifecycle, "start"),
            "the lifecycle handle gained a start again",
        )
        self.assertIn("stop", queue_bullet.lower())
        self.assertRegex(
            queue_bullet,
            r"never\s+\*\*starts\*\*",
            "the manual must say the queue never starts a container",
        )
        self.assertIn("idle", queue_bullet.lower())
        self.assertTrue(hasattr(q.SaladQueue, "idle_check"))
        self.assertTrue(hasattr(q.SaladQueue, "idle_timeout_s"))

    def test_the_manual_documents_profile_management(self) -> None:
        """The controls the Config page ships are the ones the manual names."""
        manual = " ".join(MANUAL.read_text(encoding="utf-8").split())
        source = (PKG / "pages" / "config.py").read_text(encoding="utf-8")
        for label in (
            "Add profile",
            "Delete profile",
            "Save profile",
            "Checkpoints this profile serves",
            "Remove selected",
        ):
            self.assertIn(label, source, f"the Config page no longer ships {label!r}")
            self.assertIn(label, manual, f"the manual never names {label!r}")
        self.assertIn("one line per profile", manual.lower())
        config_bullet = manual.split("- **Config**.", 1)[1].split(
            "- **Prompt Settings**.", 1
        )[0]
        self.assertIn(
            "**Profile**, **Images**, **Salad group**, **Vast.ai**",
            config_bullet,
            "the manual's Config bullet must name the four sub-tab labels in order",
        )


class LayerMapMatchesTheModules(unittest.TestCase):
    def test_every_module_the_map_names_exists(self) -> None:
        text = MANUAL.read_text(encoding="utf-8")
        section = text.split("## Layers", 1)[1].split("### Metadata document", 1)[0]
        named = sorted(set(re.findall(r"`([a-z_]+\.py)`", section)))
        self.assertTrue(named, "the layer map names no modules")
        for module in named:
            where = TOOLS if module == "salad_gen.py" else PKG
            self.assertTrue(
                (where / module).is_file(),
                f"the layer map names {module}, which is not in {where.name}/",
            )

    def test_every_module_in_the_package_is_mapped(self) -> None:
        text = MANUAL.read_text(encoding="utf-8")
        section = text.split("## Layers", 1)[1].split("### Metadata document", 1)[0]
        named = set(re.findall(r"`([a-z_]+\.py)`", section))
        shipped = {p.name for p in PKG.glob("*.py")}
        shipped.discard("__init__.py")
        missing = sorted(shipped - named)
        self.assertEqual(missing, [], f"the layer map does not name: {missing}")


class AssistPageMatchesTheManual(unittest.TestCase):
    """The manual's Prompt Assist text names the backends the shipped page has.

    The page has two backends that fill the same boxes, so a manual sentence
    that names only DeepSeek, or a pane title that does, is a drift the reader
    would trip over.
    """

    def test_the_manual_names_both_backends_and_matches_the_shipped_labels(self) -> None:
        manual = " ".join(MANUAL.read_text(encoding="utf-8").split())
        source = (PKG / "pages" / "assist.py").read_text(encoding="utf-8")
        self.assertIn("Help (DeepSeek)", manual, "the manual names the DeepSeek button")
        self.assertIn("Help (local)", manual, "and the local one")
        self.assertIn(
            "OpenAI-compatible", manual, "and says what the local one talks to"
        )
        self.assertIn(
            "LM Studio", manual, "and where the local server usually comes from"
        )

        self.assertIn('ft.Text("Reply"', source, "the reply pane's title must be in assist.py")
        for where, text in (("the manual", manual), ("assist.py", source)):
            self.assertNotIn(
                "DeepSeek reply", text, f"{where} still calls the pane DeepSeek-only"
            )
            self.assertNotIn(
                "no image is sent to DeepSeek",
                text,
                f"{where} still names one backend for the image note",
            )
            self.assertNotIn(
                "Ask DeepSeek for help first",
                text,
                f"{where} still names one backend for the empty-commit dialog",
            )


class RootReadmeTestCount(unittest.TestCase):
    def _real_count(self) -> int:
        """The suite's count, read by building it: a pattern over the files misses
        tests a base class supplies and counts a commented-out one."""
        suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_*.py")
        return suite.countTestCases()

    def test_every_stated_test_count_is_the_real_one(self) -> None:
        """Both manuals state the count, and both have drifted before."""
        real = self._real_count()
        for path in (ROOT_README, MANUAL):
            text = path.read_text(encoding="utf-8")
            match = re.search(r"#\s*(\d+)\s+tests", text)
            self.assertIsNotNone(
                match, f"{path.name} no longer states a test count"
            )
            self.assertEqual(
                int(match.group(1)),
                real,
                f"{path.name} says {match.group(1)} tests; the suite has {real}",
            )


# Each stated count is bound to the command it describes, so the root suite's
# `# 1092 tests` on the line above the container one is not read as its count.
CONTAINER_COMMAND = re.compile(
    r"cd\s+salad_klein\b[^\n]*unittest discover[^\n]*test_\*\.py"
)
CONTAINER_STATED = re.compile(
    r"cd\s+salad_klein\b[^\n]*unittest discover[^\n]*?test_\*\.py[^\n]*?#\s*(\d+)\s+tests"
)
RECIPE_COMMAND = re.compile(r'unittest discover -s tests -p "test_klein_recipes\.py"')
RECIPE_STATED = re.compile(
    r'unittest discover -s tests -p "test_klein_recipes\.py"'
    r"(?:[^\n]*\n){0,3}[^\n]*?\((\d+)\s+tests\)"
)


class ContainerSuiteCount(unittest.TestCase):
    """The container-side suite's stated counts must be the real ones.

    ``RootReadmeTestCount`` counts ``HERE`` (the root suite) and takes only the
    first count in each README, so the container line below it was invisible and
    ``salad_klein/README.md`` was read by no test at all — the count sat wrong
    in both READMEs for two audits (issue 5 in ``docs/issue-records.md``).
    """

    # The files that state a count today. A file that never states one cannot be
    # checked, so these three are required: deleting the line fails here.
    # `salad_klein/README.md` documents the commands but states no count, so it
    # is held to the command lines instead.
    MUST_STATE = (ROOT_README, MANUAL, FLUX2_DOC)

    def _count(self, paths) -> int:
        real = 0
        for path in paths:
            real += len(
                re.findall(r"^\s+def test_", path.read_text(encoding="utf-8"), re.M)
            )
        return real

    def test_the_stated_container_count_is_the_real_one(self) -> None:
        container = self._count(sorted(KLEIN.glob("test_*.py")))
        recipe = self._count([HERE / "test_klein_recipes.py"])
        self.assertGreater(container, 0, "no container-side test module was found")
        self.assertGreater(recipe, 0, "the recipe module has no test methods")

        # file, the command it must document, every count stated for it, the real one.
        sites = (
            (ROOT_README, CONTAINER_COMMAND, CONTAINER_STATED, container),
            (MANUAL, CONTAINER_COMMAND, CONTAINER_STATED, container),
            (KLEIN_README, CONTAINER_COMMAND, CONTAINER_STATED, container),
            (KLEIN_README, RECIPE_COMMAND, RECIPE_STATED, recipe),
            (FLUX2_DOC, RECIPE_COMMAND, RECIPE_STATED, recipe),
        )
        for path, command, stated_count, real in sites:
            with self.subTest(file=path.name, command=command.pattern):
                text = path.read_text(encoding="utf-8")
                self.assertRegex(
                    text, command, f"{path.name} no longer documents the command"
                )
                found = stated_count.findall(text)
                if path in self.MUST_STATE:
                    self.assertTrue(
                        found, f"{path.name} no longer states a test count"
                    )
                for number in found:
                    self.assertEqual(
                        int(number),
                        real,
                        f"{path.name} says {number} tests; the suite has {real}",
                    )


class DeploymentDocDescribesTheImages(unittest.TestCase):
    """Both container images this repo builds must be described where they are built.

    The shipped metadata document is the source of truth for which image serves
    which unet family, and it is what a config's image tag is seeded from, so a
    tag, a unet or the build arg that changes there and not in the deployment
    doc is a drift the reader would trip over.
    """

    def test_the_two_family_images_are_named_with_their_unets(self) -> None:
        doc = studio_meta.default()
        families = (doc.get("routing") or {}).get("families") or {}
        self.assertEqual(
            sorted(families),
            ["klein", "snofs"],
            "the document must map the two unet families",
        )
        text = DEPLOYMENT.read_text(encoding="utf-8")
        self.assertIn("KLEIN_UNET_SET", text, "the doc must name the build arg")
        for family, entry in sorted(families.items()):
            entry = entry if isinstance(entry, dict) else {}
            image = str(entry.get(studio_meta.IMAGE) or "").strip()
            with self.subTest(family=family):
                self.assertTrue(image, f"family {family} names no image")
                self.assertIn(image, text, f"the deployment doc does not name {image}")
            for unet in entry.get(studio_meta.UNETS) or []:
                with self.subTest(family=family, unet=unet):
                    self.assertIn(
                        str(unet),
                        text,
                        f"the deployment doc does not name {unet}, which {family} "
                        "downloads on its first boot",
                    )


AUDIT = TOOLS / "docs" / "history" / "59-salad-studio-audit-2026-09-26.md"

# Every dated audit, not one pinned file: a later audit must carry a resolution
# on each of its findings too. (T6 in the 2026-10-13 audit.)
AUDIT_GLOB = "*-audit-*.md"
# The resolution convention (a FIXED/DEFERRED word on every finding) starts with
# audit 61; 57-59 are the pre-convention records and stay as written.
RESOLUTION_CONVENTION_FROM = "61-"
AUDIT_AREAS = ("code", "test", "UI", "UX", "docs", "presentations")
RESOLUTIONS = ("FIXED", "DEFERRED")
FINDING_HEADING = re.compile(r"^### ([A-Z]+\d+), ([^\n]*)$", re.M)


def latest_audit() -> Path:
    audits = sorted((TOOLS / "docs" / "history").glob(AUDIT_GLOB))
    if not audits:
        raise AssertionError(f"no audit document in {TOOLS / 'docs' / 'history'}")
    return audits[-1]


def finding_problems(text: str) -> list[str]:
    """Why a finding has no resolution, one line per problem. Empty means none.

    Separate from the test so the rule can be driven with a document that breaks
    it: a check nobody has seen fail is a check that may not work.
    """
    problems: list[str] = []
    deferred: list[str] = []
    for tag, title in FINDING_HEADING.findall(text):
        # The resolution is the last word inside the heading's parenthesised
        # triple, so the closing paren comes off first.
        words = title.rstrip().rstrip(")")
        if not words.endswith(RESOLUTIONS):
            problems.append(f"{tag}: no FIXED or DEFERRED in {title!r}")
            continue
        if words.endswith("DEFERRED"):
            deferred.append(tag)
            body = text.split(f"### {tag},", 1)[1].split("\n### ", 1)[0]
            if "reason" not in body.lower():
                problems.append(f"{tag}: DEFERRED without a reason")
    # The scope section, whether or not a heading precedes it in the text.
    scope = re.split(r"(?m)^## 5\.", text)[-1].split("\n## ", 1)[0]
    for tag in deferred:
        if tag not in scope:
            problems.append(f"{tag}: DEFERRED but not listed in section 5")
    return problems


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
        self.assertIn("Queue", flet_shell.TAB_ORDER)
        from salad_studio.pages import queue_page

        self.assertTrue(hasattr(queue_page, "QueuePage"))
        confirmations.append(f"A1 queue page in TAB_ORDER at {flet_shell.TAB_ORDER.index('Queue')}")

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


class TheAuditRuleItself(unittest.TestCase):
    """The closure rule, driven with documents that break it."""

    def test_a_finding_with_no_resolution_is_a_problem(self) -> None:
        text = (
            "## 5. Out of scope\n\n"
            "### C1, a thing (code, High, executed)\n\n**Correction:** do it.\n"
        )
        problems = finding_problems(text)
        self.assertTrue(
            any("no FIXED or DEFERRED" in p for p in problems), problems
        )

    def test_a_deferred_finding_without_a_reason_is_a_problem(self) -> None:
        text = (
            "## 1. Verdict\n\n| Area | Verdict |\n|---|---|\n| Code | one finding |\n"
            "\n## 5. Out of scope\n\nNothing is deferred here.\n"
            "\n## 6. Index\n\n"
            "### C1, a thing (code, High, executed, DEFERRED)\n\nNothing here.\n"
        )
        problems = finding_problems(text)
        self.assertTrue(any("without a reason" in p for p in problems), problems)
        self.assertTrue(any("not listed in section 5" in p for p in problems), problems)

    def test_a_deferred_finding_listed_with_its_reason_is_clean(self) -> None:
        text = (
            "## 5. Out of scope\n\n- C1 is deferred, reason: the module is not in this repo.\n"
            "\n## 6. Index\n\n"
            "### C1, a thing (code, High, executed, DEFERRED)\n\n"
            "The reason is that the module is not in this repo.\n"
        )
        self.assertEqual(finding_problems(text), [])

    def test_a_fixed_finding_is_clean(self) -> None:
        text = "## 5. Out of scope\n\n### C1, a thing (code, High, executed, FIXED)\n\nDone.\n"
        self.assertEqual(finding_problems(text), [])


class EveryAuditButTheNewestIsResolved(unittest.TestCase):
    """An audit is written before its fixes, so the newest one is exempt.

    Every older audit must carry a resolution on each of its findings: that is
    the closure record a fix pass writes, and it is what stops a finding being
    dropped silently. The newest audit must instead look like an audit that has
    just landed: the six areas, and concrete findings. (T1 in
    docs/history/62-salad-studio-audit-2026-10-14.md.)
    """

    def _text(self) -> str:
        path = latest_audit()
        self.assertTrue(path.is_file(), f"the audit is missing: {path}")
        return path.read_text(encoding="utf-8")

    def test_the_newest_audit_covers_all_six_areas(self) -> None:
        text = self._text()
        for area in AUDIT_AREAS:
            self.assertIn(f"({area},", text, f"the audit has no {area} finding")

    def test_the_newest_audit_carries_concrete_findings(self) -> None:
        text = self._text()
        findings = FINDING_HEADING.findall(text)
        self.assertGreaterEqual(len(findings), 25, f"only {len(findings)} findings")
        for tag, title in findings:
            body = text.split(f"### {tag},", 1)[1].split("\n### ", 1)[0]
            # A path (optionally with a line), the gitignore, a workflow doc,
            # or a dotted symbol such as salad_queue.container_down_refusal: a
            # clean verdict names the surface it re-checked rather than a line.
            self.assertRegex(
                body,
                r"`[^`]*\.(py|md|json|txt|yaml)(:\d+(-\d+)?)?`"
                r"|`\.gitignore(:\d+)?`|docs/workflow/\d+"
                r"|`[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+`"
                r"|`[A-Za-z_][A-Za-z0-9_./-]*/`",
                f"{tag} cites no artifact",
            )

    def test_every_older_audit_carries_a_resolution(self) -> None:
        audits = sorted((TOOLS / "docs" / "history").glob(AUDIT_GLOB))
        self.assertGreaterEqual(len(audits), 2, "the audit cadence needs two audits")
        for path in audits[:-1]:
            if path.name < RESOLUTION_CONVENTION_FROM:
                continue
            with self.subTest(audit=path.name):
                self.assertEqual(
                    finding_problems(path.read_text(encoding="utf-8")),
                    [],
                    f"{path.name} is not resolved",
                )

    def test_audit_61s_fixed_claims_hold_in_the_shipped_code(self) -> None:
        from salad_studio import image_deploy, lora_store, profiles, salad_queue, salad_status, studio_meta

        confirmations: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # C7, C8, C9: the dead symbols the audit named are gone.
            self.assertFalse(hasattr(profiles, "route_payload"))
            self.assertFalse(hasattr(salad_status, "start_container_group"))
            self.assertFalse(hasattr(salad_queue, "TERMINAL_CODES"))
            confirmations.append("C7/C8/C9 the named dead symbols are gone")
            # C2, C3: both stores degrade on a truncated file.
            broken = root / "studio-profiles.json"
            broken.write_text('{"profiles": {"klein": ', encoding="utf-8")
            self.assertEqual(profiles.load_all(broken), {})
            extras = root / "studio-loras.json"
            extras.write_text("[{", encoding="utf-8")
            self.assertTrue(lora_store.list_loras(extras))
            confirmations.append("C2/C3 both stores degrade on a truncated file")
            # C5: a user image's ports survive the store round trip.
            ports = {studio_meta.PORT_API: 3000, studio_meta.PORT_COMFY: 8188}
            settings, refusal = image_deploy.add_image(
                image_deploy.empty_settings(), "probe", "user/x:1", ports=ports
            )
            self.assertEqual(refusal, "")
            store = root / "studio-images.json"
            image_deploy.save_settings(settings, store)
            entry = image_deploy.entry_by_ref(
                image_deploy.entries(studio_meta.default(), image_deploy.load_settings(store)),
                "probe",
            )
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry["ports"], ports)
            confirmations.append("C5 a user image keeps its ports through the store")
            # C1: the press refuses a stopped group with the queue's own sentence.
            sentence = salad_queue.container_down_refusal("klein", "https://gw.example")
            reason = salad_status.generate_dispatch_reason(
                {"group": {"status": "stopped"}},
                word="Stopped",
                profile="klein",
                gateway="https://gw.example",
            )
            self.assertEqual(reason, sentence)
            self.assertIsNone(
                salad_status.generate_dispatch_reason(
                    {"instances": [{"state": "running", "ready": True}]}, word="Ready"
                ),
                "a ready group is still dispatchable",
            )
            confirmations.append("C1 the press refuses a stopped group, and only that")
        for line in confirmations:
            print(f"latest audit fixed claim confirmed: {line}")
        self.assertEqual(len(confirmations), 4)


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
        source = (PKG / "civitai_verify.py").read_text(encoding="utf-8")
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
        self.assertIn(
            "salad_queue.MAX_ATTEMPTS",
            flat,
            "the POST cap must be salad_queue.MAX_ATTEMPTS, not the import-code cap",
        )
        self.assertIn("RETRY_SLEEP_S", flat, "the backoff must point at the constant")
        self.assertIn("studio_meta", flat, "routing's source must be named")
        for terminal in ("504", "524"):
            self.assertIn(terminal, flat, f"{terminal} must be named as terminal")
        self.assertIn("in-flight Studio render", flat)

    def test_the_test_command_is_the_repos_documented_one(self) -> None:
        documented = re.search(
            r'python -m unittest discover -s tests -p "test_\*\.py"',
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


class EveryRelativeLinkResolves(unittest.TestCase):
    """A markdown link to a file that moved is a dead end for a reader.

    Three of the 2026-10-13 audit's findings were exactly this (D2, D16, D19),
    and each was found by hand. This keeps them found.
    """

    SKIP = ("custom_nodes", "weights", "__pycache__", ".git")

    def test_no_markdown_link_points_at_a_missing_file(self) -> None:
        broken: list[str] = []
        checked = 0
        for path in sorted(TOOLS.rglob("*.md")):
            if any(part in self.SKIP for part in path.parts):
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                for target in re.findall(r"\]\(([^)\s]+)\)", line):
                    if target.startswith(("http://", "https://", "#", "mailto:")):
                        continue
                    relative = target.split("#", 1)[0]
                    if not relative:
                        continue
                    checked += 1
                    if not (path.parent / relative).exists():
                        broken.append(f"{path.relative_to(TOOLS)}:{number}: {target}")
        self.assertGreater(checked, 40, f"only {checked} relative links were found")
        self.assertEqual(
            broken, [], "relative links that go nowhere:\n" + "\n".join(broken)
        )


# The living docs: the workflow handbooks, the three READMEs and the skill. The
# dated records — `docs/history/` and the `docs/issue-records.md` record — quote
# defects verbatim, including symbols deleted afterwards, so they are not read here.
LIVING_DOCS = tuple(sorted((TOOLS / "docs" / "workflow").glob("*.md"))) + (
    ROOT_README,
    MANUAL,
    KLEIN_README,
    SKILL,
)
# The living-document count before the 2026-10-16 consolidation (14 living docs
# plus the six dated issue files). The dated closure states it; the current tree
# cannot re-derive it after the 2026-10-17 workflow merge.
CONSOLIDATION_BEFORE = 20


def route_payload_mentions(paths) -> list[str]:
    """``path:line`` for every document that still names the deleted routing call.

    Separate from the test so the rule can be driven with a document that breaks
    it: a check nobody has seen fail is a check that may not work.
    """
    found: list[str] = []
    for path in paths:
        where = path.relative_to(TOOLS) if path.is_relative_to(TOOLS) else path
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "route_payload" in line:
                found.append(f"{where}:{number}")
    return found


# The seven helpers issue 5 of `docs/issue-records.md` deleted: a
# repo-wide scan over every `.py` found exactly one occurrence of each name, its
# own `def`. The rule below reads the module's *source* rather than `hasattr`,
# because `_draw_grid` was a method: its name lived on `GraphPane`, not on
# `graph_view`.
DEAD_HELPER_MODULES = ("theme.py", "json_highlight.py", "graph_view.py")
DEAD_HELPERS = (
    ("theme.py", "palette_snapshot"),
    ("json_highlight.py", "token_kinds"),
    ("graph_view.py", "node_boxes"),
    ("graph_view.py", "round_polyline"),
    ("graph_view.py", "_draw_grid"),
    ("graph_view.py", "_wrap"),
    ("graph_view.py", "_rounded_rect"),
)

# The seven `def` blocks as they stood before that pass, verbatim. The
# pre-deletion text is not recoverable from the shipped file once it is deleted,
# so it is a literal here: it is what lets the rule be driven against the source
# it was written for, since a check nobody has seen fail is a check that may not
# work.
PRE_DELETION_DEFS = (
    (
        "theme.py",
        (
            "def palette_snapshot() -> Mapping[str, str]:\n"
            '    """Copy of PALETTE for callers that should not mutate the module dict."""\n'
            "    return dict(PALETTE)\n"
        ),
    ),
    (
        "json_highlight.py",
        (
            "def token_kinds(text: str) -> set[str]:\n"
            "    return {kind for kind, _s, _e in tokenize_json(text)}\n"
        ),
    ),
    (
        "graph_view.py",
        (
            "def node_boxes(prompt: Prompt) -> dict[str, tuple[float, float, float, float]]:\n"
            '    """Axis-aligned card rects from ``layout_xy`` + ``node_metrics``."""\n'
            "    return boxes_from_xy(prompt, layout_xy(prompt))\n"
        ),
    ),
    (
        "graph_view.py",
        (
            "def round_polyline(\n"
            "    pts: list[tuple[float, float]], radius: float = _WIRE_CORNER\n"
            ") -> list[tuple[float, float]]:\n"
            '    """Back-compat: chamfer then densify (no circular arcs)."""\n'
            "    return densify_polyline(chamfer_polyline(pts, cut=radius), step=10.0)\n"
        ),
    ),
    (
        "graph_view.py",
        (
            "    def _draw_grid(self, width: float, height: float) -> None:\n"
            "        step = 24\n"
            "        for x in range(0, int(width) + step, step):\n"
            "            self.canvas.create_line(x, 0, x, height, fill=_GRID, width=1)\n"
            "        for y in range(0, int(height) + step, step):\n"
            "            self.canvas.create_line(0, y, width, y, fill=_GRID, width=1)\n"
        ),
    ),
    (
        "graph_view.py",
        (
            'def _wrap(text: str, width: int) -> list[str]:\n'
            '    words = (text or "").replace("\\n", " ").split()\n'
            "    lines: list[str] = []\n"
            '    cur = ""\n'
            "    for w in words:\n"
            '        nxt = f"{cur} {w}".strip()\n'
            "        if len(nxt) > width and cur:\n"
            "            lines.append(cur)\n"
            "            cur = w\n"
            "        else:\n"
            "            cur = nxt\n"
            "    if cur:\n"
            "        lines.append(cur)\n"
            '    return lines or [""]\n'
        ),
    ),
    (
        "graph_view.py",
        (
            "def _rounded_rect(\n"
            "    canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, **kw: Any\n"
            ") -> int:\n"
            "    r = _CORNER\n"
            "    pts = [\n"
            "        x0 + r, y0,\n"
            "        x1 - r, y0,\n"
            "        x1, y0,\n"
            "        x1, y0 + r,\n"
            "        x1, y1 - r,\n"
            "        x1, y1,\n"
            "        x1 - r, y1,\n"
            "        x0 + r, y1,\n"
            "        x0, y1,\n"
            "        x0, y1 - r,\n"
            "        x0, y0 + r,\n"
            "        x0, y0,\n"
            "        x0 + r, y0,\n"
            "    ]\n"
            "    return canvas.create_polygon(pts, smooth=True, splinesteps=16, **kw)\n"
        ),
    ),
)


def shipped_sources() -> dict[str, str]:
    """The text of each module the seven helpers were deleted from."""
    return {name: (PKG / name).read_text(encoding="utf-8") for name in DEAD_HELPER_MODULES}


def dead_helpers_in(sources: dict[str, str]) -> list[str]:
    """``module:name`` for every deleted helper still defined in ``sources``.

    Separate from the test so the rule can be driven against a scratch copy of
    the pre-deletion source. ``sources`` maps a module's file name to its text,
    so the rule sees a ``def`` wherever it sits — module level or, as with
    ``_draw_grid``, in a class body.
    """
    found: list[str] = []
    for module, name in DEAD_HELPERS:
        text = sources.get(module, "")
        if re.search(rf"^[ \t]*def {re.escape(name)}\(", text, re.M):
            found.append(f"{module}:{name}")
    return found


class MoreFixedClaimsHoldInTheShippedCode(unittest.TestCase):
    """The rest of the audit's FIXED claims, checked against the code."""

    def test_the_history_poll_keeps_waiting_on_an_in_flight_entry(self) -> None:
        from salad_studio import generator

        answers = [
            (
                200,
                json.dumps(
                    {"p": {"status": {"status_str": "executing", "completed": False}}}
                ).encode(),
            ),
            (200, json.dumps({"p": {"images": ["QUJD"]}}).encode()),
        ]
        calls: list[int] = []

        def fetch(_url):
            calls.append(1)
            return answers[min(len(calls) - 1, len(answers) - 1)]

        self.assertEqual(
            generator.poll_history_image(
                fetch, "https://gw.example/history/p", "p", tries=3, sleep_s=0
            ),
            "QUJD",
        )

    def test_a_listing_cut_off_by_the_page_cap_says_so(self) -> None:
        from salad_studio import vast

        pages = [
            json.dumps(
                {
                    "instances": [
                        {
                            "id": n,
                            "public_ipaddr": "203.0.113.9",
                            "ports": {"8188/tcp": [{"HostPort": 31234}]},
                        }
                    ],
                    "next_token": f"page-{n}",
                }
            ).encode()
            for n in range(vast.MAX_PAGES)
        ]

        def transport(_request, _timeout):
            return 200, pages.pop(0)

        result = vast.fetch_instances("vast-key", sender=transport)
        self.assertTrue(result["truncated"], "a cut-off listing must say it is cut off")

    def test_a_zero_ready_budget_reports_itself(self) -> None:
        import salad_gen

        with self.assertRaises(SystemExit) as caught:
            salad_gen.wait_ready("https://gw.example", "k", timeout_s=0)
        self.assertIn("not ready after 0s", str(caught.exception))

    def test_the_strength_table_is_the_only_copy(self) -> None:
        """C15: the substring fallback that re-implemented the table is gone."""
        import lora_store as ls

        self.assertEqual(
            ls.strengths_for(
                {
                    "id": "civitai:9999@8888",
                    "source": {"download": "https://civitai.com/api/download/models/2795018"},
                }
            ),
            (1.0, 1.0),
            "an id that is not in the table must not pick a strength up by digits",
        )

    def test_the_dead_symbols_the_audit_named_are_gone(self) -> None:
        import ai_helper
        import comfy_import
        import face_prompt
        import generator
        import json_highlight
        import model_catalog
        import ref_check
        import theme
        import tokens as tok

        from salad_studio import civitai_verify, graph_model, profiles, salad_status

        absent = (
            (generator, ("read_key", "_body_snippet", "clear_history")),
            (comfy_import, ("SKIP_TYPES", "_primitive_value", "issues_from_pastes")),
            (ref_check, ("CIVITAI_VERSION",)),
            (civitai_verify, ("SAMPLE_URL", "visual_gap_actionable", "_WRONG_LORA_FAMILIES")),
            (model_catalog, ("salad_loader_name",)),
            (tok, ("token_path", "probe_all")),
            (ai_helper, ("content_of", "fetch_local_models")),
            (salad_status, ("shown_policy", "color_for_status", "format_status", "start_container_group")),
            (profiles, ("route_payload", "SNOFS_UNET", "SNOFS_MARKER", "_default_selected_loras")),
            # Issue 5 of docs/issue-records.md: seven helpers nothing
            # calls. `_draw_grid` was a method, so its name lived on the class.
            (theme, ("palette_snapshot",)),
            (json_highlight, ("token_kinds",)),
            (graph_model, ("node_boxes", "round_polyline", "_wrap", "_rounded_rect")),
            (graph_model.GraphModel, ("_draw_grid",)),
            (flet_shell, ("_build_nav_buttons", "SaladStudio", "TAB_ORDER_TK")),
            (
                face_prompt,
                (
                    "compose_face_system_prompt",
                    "compose_young_deanime_edit_prompt",
                    "compose_face_cleanup_edit_prompt",
                    "compose_body_age_edit_prompt",
                    "compose_body_negative",
                ),
            ),
        )
        for module, names in absent:
            for name in names:
                with self.subTest(module=module.__name__, name=name):
                    self.assertFalse(hasattr(module, name), f"{module.__name__}.{name} is back")
        # Gone from the module is not enough: doc 21 kept naming
        # `profiles.route_payload` after the function was deleted, so no living
        # document may name a deleted symbol either.
        self.assertIn(HANDOFF, LIVING_DOCS, "the handoff left the living-docs set")
        named = route_payload_mentions(LIVING_DOCS)
        self.assertEqual(
            named,
            [],
            "a living document still names the deleted routing call: "
            + ", ".join(named),
        )
        # The same for the seven helpers: the source rule below reads each
        # module's text, so a name that came back under a different binding is
        # caught as well.
        self.assertEqual(
            dead_helpers_in(shipped_sources()),
            [],
            "a helper nothing calls is back in the shipped source",
        )

    def test_the_dead_helper_rule_reports_the_pre_deletion_source(self) -> None:
        """The rule, driven against a scratch copy of the source it was written for.

        The scratch copy is the shipped module text with the seven deleted `def`
        blocks put back, so the check is shown to work rather than assumed to.
        It is read as text — the rule never parses it — so the method block keeps
        its own indentation.
        """
        scratch = shipped_sources()
        for module, block in PRE_DELETION_DEFS:
            scratch[module] = scratch[module] + "\n\n" + block
        self.assertEqual(
            dead_helpers_in(scratch),
            [f"{module}:{name}" for module, name in DEAD_HELPERS],
            "the rule must report all seven against the pre-deletion source",
        )

    def test_the_deployment_accessor_is_the_one_entries_uses(self) -> None:
        """C16: the module docstring named an accessor nothing called."""
        from salad_studio import studio_meta

        self.assertFalse(hasattr(studio_meta, "DEPLOYMENT_KEYS"))
        self.assertIn(
            "deployment_for_family", (PKG / "image_deploy.py").read_text(encoding="utf-8")
        )


# The anatomy recipe's shipped scheduler, and the doc line that states its step
# count. Doc 15 said "6 steps" for a 4-step recipe (issue 3 in
# docs/issue-records.md), so the two are read together and compared.
ANATOMY_RECIPE = KLEIN / "prompt_snofs_distilled_anatomy.json"
ANATOMY_STATED_STEPS = re.compile(
    r"prompt_snofs_distilled_anatomy\.json`[^\n]*?(\d+)\s+steps"
)


class KleinRecipeStepsMatchTheDoc(unittest.TestCase):
    """A recipe's stated step count must be the scheduler's steps."""

    def test_the_anatomy_recipes_steps_are_the_docs(self) -> None:
        body = json.loads(ANATOMY_RECIPE.read_text(encoding="utf-8"))
        nodes = (body.get("prompt") or {}).values()
        steps = [
            node["inputs"]["steps"]
            for node in nodes
            if isinstance(node, dict) and node.get("class_type") == "Flux2Scheduler"
        ]
        self.assertEqual(
            len(steps), 1, "the anatomy recipe must carry exactly one Flux2Scheduler"
        )
        stated = ANATOMY_STATED_STEPS.findall(FLUX2_DOC.read_text(encoding="utf-8"))
        self.assertTrue(stated, "doc 15 no longer states the anatomy recipe's steps")
        self.assertEqual(
            [int(number) for number in stated],
            steps,
            "doc 15 states a step count the shipped anatomy recipe does not have",
        )


# Every shipped Klein recipe, and the doc 15 sentence that tells a reader what to do
# with a `LoraLoader`'s `_meta` block. Parsing the shipped files finds 14 `LoraLoader`
# nodes and none carrying `_meta`, while doc 15 said to keep the block "on every
# `LoraLoader`" — advice that, followed, would make the reader's own node classify as
# foreign (doc 21 §5). (Issue 2 in `docs/issue-records.md`.)
KLEIN_RECIPES = tuple(sorted(KLEIN.glob("prompt_*.json")))
META_UNIVERSAL = re.compile(r"on every `?LoraLoader`?")


def lora_meta_nodes(paths) -> list[tuple[str, str, bool]]:
    """``(recipe, node id, carries _meta)`` for every shipped ``LoraLoader``."""
    found: list[tuple[str, str, bool]] = []
    for path in paths:
        body = json.loads(path.read_text(encoding="utf-8"))
        for node_id, node in (body.get("prompt") or {}).items():
            if isinstance(node, dict) and node.get("class_type") == "LoraLoader":
                found.append((path.name, str(node_id), bool(node.get("_meta"))))
    return found


def meta_advice_problems(text: str, nodes: list[tuple[str, str, bool]]) -> list[str]:
    """Why doc 15's `_meta` advice does not describe the shipped recipes.

    A `LoraLoader` that carries a block must be described; a shipped set where none
    does must not be described as universal. Separate from the test so the rule can
    be driven with the old text.
    """
    problems: list[str] = []
    flat = " ".join(text.split())
    carrying = [(recipe, node_id) for recipe, node_id, has_meta in nodes if has_meta]
    for recipe, node_id in carrying:
        if f"{recipe}:{node_id}" not in flat and f"node {node_id}" not in flat:
            problems.append(
                f"{recipe} node {node_id} carries a `_meta` block the doc never describes"
            )
    if not carrying and META_UNIVERSAL.search(flat):
        problems.append(
            "the doc requires a `_meta` block on every `LoraLoader`, but none of the "
            f"{len(nodes)} shipped `LoraLoader` nodes carries one"
        )
    return problems


class KleinMetaAdviceMatchesTheRecipes(unittest.TestCase):
    """Doc 15's `_meta` rule must describe the recipes this repo ships."""

    def test_the_advice_describes_the_shipped_lora_loaders(self) -> None:
        nodes = lora_meta_nodes(KLEIN_RECIPES)
        self.assertGreater(len(nodes), 0, "no shipped recipe carries a LoraLoader")
        for path in (FLUX2_DOC, HANDOFF):
            with self.subTest(doc=path.name):
                problems = meta_advice_problems(
                    path.read_text(encoding="utf-8"), nodes
                )
                self.assertEqual(problems, [], "\n".join(problems))

    def test_the_rule_catches_the_universal_claim(self) -> None:
        """The sentence issue 2 was found in must fail this rule."""
        nodes = lora_meta_nodes(KLEIN_RECIPES)
        old = (
            "### `_meta` on every `LoraLoader`\n"
            "\n"
            "Keep the `_meta.title` / `_meta.base` blocks on every `LoraLoader`: [doc 21 §5].\n"
        )
        with tempfile.TemporaryDirectory() as td:
            doc = Path(td) / "15-old.md"
            doc.write_text(old, encoding="utf-8")
            problems = meta_advice_problems(doc.read_text(encoding="utf-8"), nodes)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("on every `LoraLoader`", problems[0])


# The shipped scripts a living doc's tools table attributes options to, and the
# long options each parser accepts. Doc 14 called `ckpt_name` / `lora_name` CLI
# options when they are `flux_payload()` parameters the script rejects as
# arguments (issue 5 in docs/issue-records.md), so a bare name in the
# option column counts as an option unless the row says whose parameter it is.
DOCUMENTED_SCRIPTS = (
    "model_catalog.py",
    "salad_catalog_faces.py",
    "salad_gen.py",
    "salad_probe_ages.py",
)
ADD_ARGUMENT = re.compile(r'add_argument\(\s*"(--[a-z][a-z-]*)"')
BACKTICKED_OPTION = re.compile(r"`(--[a-z][a-z-]*|[a-z][a-z0-9]*_[a-z0-9_]+)`")


def parser_flags(script: Path) -> set[str]:
    """The long options a shipped script's parser accepts, read from its source."""
    return set(ADD_ARGUMENT.findall(script.read_text(encoding="utf-8")))


def option_problems(doc: Path, flags: dict[str, set[str]]) -> list[str]:
    """``name:line`` for every option a doc gives a script that the script lacks.

    Separate from the test so the rule can be driven with a document that breaks
    it: a check nobody has seen fail is a check that may not work.
    """
    problems: list[str] = []
    where = doc.relative_to(TOOLS) if doc.is_relative_to(TOOLS) else doc
    for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
        named = [name for name in DOCUMENTED_SCRIPTS if name in line]
        if not named:
            continue
        cells = (
            [cell.strip() for cell in line.strip("|").split("|")]
            if line.startswith("|")
            else []
        )
        for option in BACKTICKED_OPTION.findall(line):
            if option.startswith("--") and any(option in flags[n] for n in named):
                continue
            # A bare name is an option only in a table's option column, and only
            # when that column does not name the function it is a parameter of.
            if not option.startswith("--") and (
                len(cells) < 2 or option not in cells[1] or "flux_payload" in cells[1]
            ):
                continue
            problems.append(f"{where}:{number}: {named[0]} has no {option}")
    return problems


class DocumentedScriptOptionsAreRealFlags(unittest.TestCase):
    """A doc's tools table names only options the shipped script really has."""

    def test_every_option_a_living_doc_gives_a_script_is_a_flag(self) -> None:
        flags = {name: parser_flags(TOOLS / name) for name in DOCUMENTED_SCRIPTS}
        for name, accepted in flags.items():
            self.assertTrue(accepted, f"{name} no longer reads as an argparse script")
        problems: list[str] = []
        for doc in LIVING_DOCS:
            problems += option_problems(doc, flags)
        self.assertEqual(
            problems,
            [],
            "living docs give a script options it does not have:\n"
            + "\n".join(problems),
        )

    def test_the_rule_catches_an_option_the_script_does_not_have(self) -> None:
        """The doc line that carried issue 5 must fail this rule."""
        flags = {name: parser_flags(TOOLS / name) for name in DOCUMENTED_SCRIPTS}
        old = (
            "| `salad_gen.py` | `POST /prompt` Flux graph; optional `ckpt_name` / `lora_name` |\n"
        )
        with tempfile.TemporaryDirectory() as td:
            doc = Path(td) / "14-old.md"
            doc.write_text(old, encoding="utf-8")
            problems = option_problems(doc, flags)
        self.assertEqual(len(problems), 2, problems)
        self.assertIn("ckpt_name", problems[0])
        self.assertIn("lora_name", problems[1])


# The section references a document makes — `§3`, `§3.2` — must name a section it
# has. Doc 22 sent a reader to `§1.3` and to `§1.1`/`§6.3` and has none of them
# (issue 5 in `docs/issue-records.md`).
SECTION_REF = re.compile(r"§\s?(\d+(?:\.\d+)*[a-z]?)(?![\w])")
NUMBERED_HEADING = re.compile(r"(?m)^#{2,6}\s+(\d+(?:\.\d+)*[a-z]?)[.\s]")
# A blank line, a heading, a list item or a table row starts a block: a reference
# is read against the file a link in its own block names.
SECTION_BLOCK_START = re.compile(r"^(-|\*|\d+\.|\||#)")
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
DOC_NAME = re.compile(r"doc (\d+)")


def numbered_sections(text: str) -> set[str]:
    """The section numbers a document's headings give it: `## 3.` → `3`, `### 3.2` → `3.2`."""
    return set(NUMBERED_HEADING.findall(text))


# A `Route B` / `Route C` label names a route by its position in a comparison, so a
# document that uses one must also use `Route A`; otherwise the label points at a
# framing the reader cannot find. (Issue 3 in `docs/issue-records.md`: doc
# 22's Route A section and its `## 2.` were cut, leaving "Route B", "Route C" and
# "the three routes" naming a comparison the document no longer contains.)
ROUTE_LABEL = re.compile(r"\bRoute\s+([A-Z])\b")


def route_label_problems(path: Path, text: str) -> list[str]:
    """``path:line: Route X`` for every route label with no `Route A` to anchor it.

    Separate from the test so the rule can be driven with a document that breaks
    it: a check nobody has seen fail is a check that may not work.
    """
    where = path.relative_to(TOOLS) if path.is_relative_to(TOOLS) else path
    labels = set(ROUTE_LABEL.findall(text))
    if not labels or "A" in labels:
        return []
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        match = ROUTE_LABEL.search(line)
        if match:
            problems.append(
                f"{where}:{number}: Route {match.group(1)} names no Route A in this document"
            )
    return problems


def section_blocks(text: str) -> list[list[tuple[int, str]]]:
    """The text as blocks of ``(line number, line)``, one per heading, list item, table row or paragraph."""
    blocks: list[list[tuple[int, str]]] = []
    block: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if not stripped or SECTION_BLOCK_START.match(stripped):
            if block:
                blocks.append(block)
                block = []
        if stripped:
            block.append((number, line))
    if block:
        blocks.append(block)
    return blocks


def section_reference_problems(path: Path, text: str | None = None) -> list[str]:
    """``path:line: §N`` for every section reference that names no section.

    The file a reference names is the document a markdown link beside it points
    at, else the document that carries it; a `doc 15` written in prose is not a
    link, so a reference after one is left alone. Separate from the test so the
    rule can be driven with a document that breaks it: a check nobody has seen
    fail is a check that may not work.
    """
    if text is None:
        text = path.read_text(encoding="utf-8")
    where = path.relative_to(TOOLS) if path.is_relative_to(TOOLS) else path
    sections = {path: numbered_sections(text)}
    problems: list[str] = []
    for block in section_blocks(text):
        joined = "\n".join(line for _, line in block)
        starts: list[int] = []
        offset = 0
        for _, line in block:
            starts.append(offset)
            offset += len(line) + 1
        links = []
        for match in MARKDOWN_LINK.finditer(joined):
            dest = match.group(1).split("#", 1)[0]
            if dest.endswith(".md") and not dest.startswith(("http://", "https://", "/")):
                links.append((match.start(), match.end(), (path.parent / dest).resolve()))
        for index, ((number, line), start) in enumerate(zip(block, starts)):
            # A reference that opens a line whose link ends the line above it belongs
            # to that link: a long link wraps, and its `§1.2/§1.3` lands on the next line.
            wrapped = None
            if index and SECTION_REF.match(line.lstrip()):
                candidates = [
                    dest
                    for begin, end, dest in links
                    if starts[index - 1] <= end < starts[index]
                ]
                if candidates:
                    wrapped = candidates[-1]
            for match in SECTION_REF.finditer(line):
                at = start + match.start()
                target = None
                for begin, end, dest in links:
                    if begin <= at < end:  # the reference is inside the link's own text
                        target = dest
                        break
                if target is None:
                    target = wrapped
                if target is None:
                    if DOC_NAME.search(joined[:at]):
                        continue  # named in prose, not by a link the rule can follow
                    target = path
                if target not in sections:
                    if not target.is_file():
                        continue  # a link to a missing file is EveryRelativeLinkResolves' business
                    sections[target] = numbered_sections(target.read_text(encoding="utf-8"))
                if match.group(1) not in sections[target]:
                    problems.append(
                        f"{where}:{number}: §{match.group(1)} names no section of {target.name}"
                    )
    problems += route_label_problems(path, text)
    return problems


class SectionReferencesNameRealSections(unittest.TestCase):
    """A `§N` a living document names must be a section of the document it names.

    Issue 5 in `docs/issue-records.md`: doc 22 named `§1.3`, `§1.1` and
    `§6.3`, and has no such headings.
    """

    def test_every_section_reference_names_a_section(self) -> None:
        problems: list[str] = []
        checked = 0
        for doc in LIVING_DOCS:
            checked += len(SECTION_REF.findall(doc.read_text(encoding="utf-8")))
            problems += section_reference_problems(doc)
        self.assertGreater(checked, 20, f"only {checked} section references were found")
        self.assertEqual(
            problems,
            [],
            "section references that name no section:\n" + "\n".join(problems),
        )

    def test_the_rule_catches_a_reference_to_a_section_that_is_not_there(self) -> None:
        """The text issue 5 was found in must fail this rule."""
        old = (
            "# 22. Can we get anatomically correct two-body scenes *every time*?\n"
            "\n"
            "## 1. The headline\n"
            "\n"
            "Three findings, and both passes converge on all three.\n"
            "\n"
            "## 6. What would change the answer\n"
            "\n"
            "1. **A measured two-skeleton OpenPose recipe for SDXL at 1024.**\n"
            "\n"
            "## 7. Coverage gaps the passes themselves recorded\n"
            "\n"
            "- Two character LoRAs stacked normally blend into \"one face that's a blend of both\".\n"
            "  The fix (per-region delta masking, §1.3) is unavailable on SDXL [18].\n"
            "\n"
            "Full gap list of the two passes: retained above in condensed form; "
            "the binding ones are §1.1 and §6.3.\n"
        )
        with tempfile.TemporaryDirectory() as td:
            doc = Path(td) / "22-old.md"
            doc.write_text(old, encoding="utf-8")
            problems = section_reference_problems(doc)
        self.assertEqual(len(problems), 3, problems)
        for reference in ("§1.3", "§1.1", "§6.3"):
            self.assertTrue(
                any(reference in problem for problem in problems),
                f"the rule missed {reference}: {problems}",
            )

    def test_the_rule_catches_a_label_with_no_route_a(self) -> None:
        """The text issue 3 was found in must fail this rule."""
        old = (
            "# 22. Can we get anatomically correct two-body scenes *every time*?\n"
            "\n"
            "## 3. Route B. SDXL / Illustrious\n"
            "\n"
            "Text.\n"
            "\n"
            "## 4. Route C. 3D: anatomy by construction\n"
            "\n"
            "Text.\n"
        )
        with tempfile.TemporaryDirectory() as td:
            doc = Path(td) / "22-old.md"
            doc.write_text(old, encoding="utf-8")
            problems = section_reference_problems(doc)
        self.assertEqual(len(problems), 2, problems)
        for label in ("Route B", "Route C"):
            self.assertTrue(
                any(label in problem for problem in problems),
                f"the rule missed {label}: {problems}",
            )


# The living docs' factual pointers, each bound to the shipped artifact it names:
# the body composer, the anatomy recipes, the recipe test, the ledger and the
# record's proof lines. Every rule below reads the code the claim is about, so a
# pointer that drifts from the tree fails here instead of at a reader. (M2, P1,
# P2, P3, P4, P5 and N1 in docs/history/63-salad-studio-audit-2026-10-16.md.)
DOC14 = TOOLS / "docs" / "workflow" / "14-salad-comfy-live-findings.md"
DOC17 = TOOLS / "docs" / "workflow" / "22-two-body-correctness-research.md"
DOC19 = TOOLS / "docs" / "workflow" / "21-klein-image-handoff.md"
DOC22 = TOOLS / "docs" / "workflow" / "22-two-body-correctness-research.md"
ISSUE_RECORD = TOOLS / "docs" / "issue-records.md"
HISTORY_DIR = TOOLS / "docs" / "history"
HISTORY_63 = HISTORY_DIR / "63-salad-studio-audit-2026-10-16.md"
VENDOR = PKG / "graph_html" / "VENDOR.txt"
GRAPH_VIEW = PKG / "graph_view.py"
SALAD_GEN = TOOLS / "salad_gen.py"
KLEIN_PROBE = TOOLS / "salad_probe_klein.py"
FACE_PACK = TOOLS / "face_prompt_pack.json"
RECIPE_TEST = HERE / "test_klein_recipes.py"
ANATOMY_RECIPES = (
    ANATOMY_RECIPE,
    KLEIN / "prompt_snofs_distilled_anatomy_resms.json",
)


def body_compose_pointer_problems(
    text: str, composer_source: str, pack: dict
) -> list[str]:
    """Why doc 14's `Body compose:` pointer names a body path no code reads.

    The pointer must name the shipped composer and the pack keys it reads; a
    name the composer does not touch may only appear as unread. Separate from
    the test so the rule can be driven with the old text.
    """
    line = next((ln for ln in text.splitlines() if "Body compose:" in ln), None)
    if line is None:
        return ["doc 14 no longer carries a `Body compose:` pointer"]
    problems: list[str] = []
    if "_klein_body_prompt" not in line:
        problems.append("the pointer does not name the composer `_klein_body_prompt`")
    elif "_klein_body_prompt" not in composer_source:
        problems.append("salad_probe_klein.py no longer defines `_klein_body_prompt`")
    for key in ("body_age_markers", "body_pregnancy"):
        if key not in line:
            problems.append(f"the pointer does not name the pack key `{key}`")
        elif key not in composer_source:
            problems.append(f"the composer no longer reads `{key}`")
        if key not in pack:
            problems.append(f"face_prompt_pack.json no longer carries `{key}`")
    for dead in ("`body_style`", "`body_t2i`"):
        if dead in line and "unread" not in line:
            problems.append(f"the pointer still reads as a live call for {dead}")
    return problems


def anatomy_seed(path: Path) -> int:
    """The `noise_seed` the anatomy recipe's `RandomNoise` node carries."""
    body = json.loads(path.read_text(encoding="utf-8"))["prompt"]
    seeds = {
        int(node["inputs"]["noise_seed"])
        for node in body.values()
        if isinstance(node, dict) and node.get("class_type") == "RandomNoise"
    }
    if len(seeds) != 1:
        raise AssertionError(f"{path.name} must carry exactly one RandomNoise seed")
    return seeds.pop()


def anatomy_loaders(path: Path) -> list[tuple[int, float]]:
    """``(version_id, strength)`` for each `LoraLoader` the anatomy recipe ships."""
    body = json.loads(path.read_text(encoding="utf-8"))["prompt"]
    return [
        (
            int(str(node["inputs"]["lora_name"]).rstrip("/").rsplit("/", 1)[-1]),
            float(node["inputs"]["strength_model"]),
        )
        for node in body.values()
        if isinstance(node, dict) and node.get("class_type") == "LoraLoader"
    ]


ANATOMY_STATED_SEED = re.compile(r"seed\s*`(\d+)`")


def anatomy_seed_problems(text: str, seeds) -> list[str]:
    """Why doc 15's anatomy-recipe seed is not the seed the shipped files carry.

    Separate from the test so the rule can be driven with the old text.
    """
    stated = {int(number) for number in ANATOMY_STATED_SEED.findall(text)}
    if not stated:
        return ["doc 15 no longer states the anatomy recipe's seed"]
    shipped = {int(seed) for seed in seeds}
    return [
        f"doc 15 states seed {number}, which no shipped anatomy recipe carries"
        for number in sorted(stated - shipped)
    ]


LORA_REF = re.compile(r"civitai:(\d+)@(\d+)")
CHAIN_START = "`LoraLoader` chain"
CHAIN_END = "`CLIPTextEncode` nodes"


def anatomy_chain_problems(text: str, loaders) -> list[str]:
    """Why doc 15's anatomy LoRA chain is not the loaders the shipped files carry.

    ``loaders`` is ``(version_id, strength)`` per shipped ``LoraLoader``. The
    chain is the sentence between the `LoraLoader` chain phrase and the
    `CLIPTextEncode` clause, so a LoRA named only in the surrounding prose (the
    catalog-only penis LoRA, the back-pose enhancer) is not read as a member.
    Separate from the test so the rule can be driven with the old text.
    """
    if CHAIN_START not in text or CHAIN_END not in text:
        return ["doc 15 no longer describes the anatomy `LoraLoader` chain"]
    chain = text.split(CHAIN_START, 1)[1].split(CHAIN_END, 1)[0]
    shipped = {str(version) for version, _strength in loaders}
    stated = {version for _model, version in LORA_REF.findall(chain)}
    problems: list[str] = []
    missing = sorted(shipped - stated)
    if missing:
        problems.append(f"the chain never names the shipped loader(s) {missing}")
    extra = sorted(stated - shipped)
    if extra:
        problems.append(
            f"the chain names {extra}, which no shipped anatomy recipe carries"
        )
    return problems


FORBIDDEN_RE = re.compile(r"FORBIDDEN\s*=\s*\(([^)]*)\)")
PLACEHOLDER_CLAIM = re.compile(r"fails on ([^.]+)\.")


def forbidden_tokens(source: str) -> tuple[str, ...]:
    """The placeholder tokens `tests/test_klein_recipes.py` rejects, read from it."""
    match = FORBIDDEN_RE.search(source)
    return tuple(re.findall(r'"([^"]+)"', match.group(1))) if match else ()


def placeholder_claim_problems(
    text: str, forbidden, module_source: str
) -> list[str]:
    """Why doc 15's claim about the recipe test is not the rule that test has.

    Every token the claim names must be in the module's ``FORBIDDEN``, and a
    check the module does not carry — the angle-bracket one — must not be
    credited to it. Separate from the test so the rule can be driven with the
    old text.
    """
    match = PLACEHOLDER_CLAIM.search(" ".join(text.split()))
    if match is None:
        return ["doc 15 no longer states what `test_klein_recipes.py` fails on"]
    claim = match.group(1)
    problems: list[str] = []
    claimed = re.findall(r"`([^`]+)`", claim)
    if not claimed:
        problems.append("the claim names no placeholder token")
    extra = [token for token in claimed if token not in forbidden]
    if extra:
        problems.append(f"the claim names {extra}, which FORBIDDEN does not carry")
    if re.search(r"angle brackets?", claim) and "angle bracket" not in module_source.lower():
        problems.append(
            "the claim credits the test with an angle-bracket check the module lacks"
        )
    return problems


def prompt_pointer_problems(text: str, verdict: dict) -> list[str]:
    """Why doc 19's pointer at the verified prompt does not resolve to the ledger.

    Separate from the test so the rule can be driven with the old text.
    """
    flat = " ".join(text.split())
    problems: list[str] = []
    if re.search(r"(quoted|reproduced) below|negative below", flat):
        problems.append("doc 19 promises text quoted below it")
    if "prompt_ledger.json" not in flat or "verdicts[0]" not in flat:
        problems.append("doc 19 does not point at prompt_ledger.json's verdicts[0]")
    for field in ("prompt", "negative"):
        if not verdict.get(field):
            problems.append(f"prompt_ledger.json's verdicts[0] carries no {field}")
    return problems


DOC14_ROW_CITE = re.compile(
    r"`([^`]+)` row at `(docs/workflow/14-salad-comfy-live-findings\.md):(\d+)`"
)


def row_cite_problems(text: str, target_lines) -> list[str]:
    """Why a `docs/workflow/14` line cite does not land on the row it names.

    Separate from the test so the rule can be driven with the old text.
    """
    problems: list[str] = []
    for label, path, number in DOC14_ROW_CITE.findall(" ".join(text.split())):
        index = int(number) - 1
        line = target_lines[index] if 0 <= index < len(target_lines) else ""
        if label not in line:
            problems.append(f"{path}:{number} does not carry the {label!r} row")
    return problems


PROOF_REF = re.compile(r"tests/(test_\w+\.py)::(\w+)\.(\w+)")


def proof_class_problems(text: str, read_module) -> list[str]:
    """Why a proof line's `tests/module.py::Class.method` does not resolve.

    Separate from the test so the rule can be driven with the old text.
    """
    problems: list[str] = []
    for module, klass, method in PROOF_REF.findall(text):
        source = read_module(module)
        if source is None:
            problems.append(f"{module} does not exist")
            continue
        if not re.search(rf"^class {re.escape(klass)}\(", source, re.M):
            problems.append(f"{module} has no class {klass}")
        if not re.search(rf"^[ \t]+def {re.escape(method)}\(", source, re.M):
            problems.append(f"{module} has no method {method}")
    return problems


def _read_test_module(name: str):
    path = HERE / name
    return path.read_text(encoding="utf-8") if path.is_file() else None


def history_index_problems(readme: str, history_dir: Path) -> list[str]:
    """Why the root README's ``docs/history/`` row omits a dated record on disk.

    Separate from the test so the rule can be driven with the old text.
    """
    row = next(
        (line for line in readme.splitlines() if line.startswith("| `docs/history/`")),
        None,
    )
    if row is None:
        return ["the root README lost its docs/history/ row"]
    return [
        f"the docs/history/ row omits {path.name}"
        for path in sorted(history_dir.glob("*.md"))
        if path.name not in row
    ]


def klein_recipes_count_problems(text: str, real: int) -> list[str]:
    """Why a stated ``test_klein_recipes.py`` count is not the module's test methods.

    Separate from the test so the rule can be driven with the old text. ``real``
    is counted from the shipped module, not a literal.
    """
    problems: list[str] = []
    for match in re.finditer(r"test_klein_recipes\.py", text):
        window = text[match.end() : match.end() + 60]
        for number in re.findall(r"(\d+)\s+tests", window):
            if int(number) != real:
                problems.append(
                    f"states {number} tests for test_klein_recipes.py; the module has {real}"
                )
    return problems


def wrapper_result_problems(text: str, gen_source: str) -> list[str]:
    """Why doc 23's Result row is not what ``salad_gen.py`` reads from POST.

    Separate from the test so the rule can be driven with the old text.
    """
    result = next(
        (line for line in text.splitlines() if line.startswith("| Result |")),
        None,
    )
    if result is None:
        return ["doc 23 lost its Result row"]
    if "data.get(" not in gen_source or '"images"' not in gen_source:
        return ["salad_gen.py no longer reads images from the POST body"]
    problems: list[str] = []
    if "images[]" not in result and "`images`" not in result:
        problems.append("the Result row never names images[] from the wrapper POST")
    if "GET /history" in result and "images" not in result:
        problems.append(
            "the Result row gives GET /history as the only fetch, with no images[]"
        )
    return problems


def numbered_section_body(text: str, number: str) -> str:
    """The body of heading ``number`` in ``text``, up to the next heading of any depth."""
    match = re.search(rf"(?m)^#{{2,6}}\s+{re.escape(number)}[.\s]", text)
    if match is None:
        return ""
    rest = text[match.end() :]
    nxt = re.search(r"(?m)^#{2,6}\s+", rest)
    return rest[: nxt.start()] if nxt else rest


def docker_gpus_cite_problems(flux_text: str, deploy_text: str) -> list[str]:
    """Why a doc 15 docker-run / ``--gpus`` cite names a doc 23 section that has neither.

    Separate from the test so the rule can be driven with the old text. A range
    such as ``§1–§3`` is not a cite of §3.
    """
    problems: list[str] = []
    for match in re.finditer(r"doc 23 §(\d+(?:\.\d+)*)(?![–§-])", flux_text):
        number = match.group(1)
        start = flux_text.rfind("\n\n", 0, match.start()) + 2
        end = flux_text.find("\n\n", match.end())
        if end < 0:
            end = len(flux_text)
        block = flux_text[start:end]
        if "--gpus" not in block and "docker run" not in block:
            continue
        body = numbered_section_body(deploy_text, number)
        if "docker run" not in body and "--gpus" not in body:
            problems.append(
                f"doc 15 cites doc 23 §{number} for docker run / --gpus, "
                "and that section has neither"
            )
    return problems


def replica_recipe_problems(doc22: str, doc23: str) -> list[str]:
    """Why doc 22's replica default is not this repo's group recipe in doc 23.

    Separate from the test so the rule can be driven with the old text. Salad's
    product default and this repo's recipe are two facts.
    """
    field = re.search(
        r"\|\s*Replicas\s*\|\s*\*\*(\d+)\*\*[^\n]*until", doc23
    )
    if field is None:
        return ["doc 23 no longer sets Replicas to N until /ready"]
    recipe = int(field.group(1))
    bullet = next(
        (
            line
            for line in doc22.splitlines()
            if "replica" in line.lower() and "doc 23" in line
        ),
        None,
    )
    if bullet is None:
        return ["doc 22 no longer states a replica default next to the doc 23 cite"]
    problems: list[str] = []
    if f"{recipe} replica" not in bullet and f"**{recipe}**" not in bullet:
        problems.append(
            f"doc 22 never names this repo's group recipe of {recipe} replica"
        )
    if re.search(r"(?i)default is \*\*3 replicas\*\*", bullet) and "product default" not in bullet.lower():
        problems.append(
            "doc 22 states 3 replicas as the default without naming Salad's product default"
        )
    return problems


def appendix_data_row_count(text: str) -> int:
    """Data rows under ``### Appendix`` headings, skipping the header and separator."""
    count = 0
    in_app = False
    for line in text.splitlines():
        if line.startswith("### Appendix"):
            in_app = True
            continue
        if in_app and line.startswith("#"):
            in_app = False
            continue
        if not in_app or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells or cells[0] in {"Site", ""}:
            continue
        if set(line.replace("|", "").replace(" ", "")) <= set("-:"):
            continue
        count += 1
    return count


def issue_record_shape(text: str) -> dict[str, int]:
    """The counts the consolidation must state, read from the shipped file."""
    return {
        "lines": len(text.splitlines()),
        "h3": len(re.findall(r"^### ", text, re.M)),
        "numbered": len(re.findall(r"^### \d+\.", text, re.M)),
        "tag": len(re.findall(r"^### [A-Z]+\d+,", text, re.M)),
        "fixed": len(re.findall(r"^\*\*Fixed:\*\*", text, re.M)),
        "appendix_rows": appendix_data_row_count(text),
    }


def living_doc_count_problems(section: str) -> list[str]:
    """Why the consolidation's living-document count is not the tree.

    ``LIVING_DOCS`` plus ``issue-records.md`` is the after count. The before
    count is the tree on 2026-10-16, before the six dated issue files were
    consolidated and before the 2026-10-17 workflow merge; it is a dated fact,
    not something the current file count can re-derive.
    """
    match = re.search(
        r"living-document count fell \*\*(\d+) → (\d+)\*\*", section
    )
    if match is None:
        return ["the consolidation no longer states the living-document count"]
    before, after = int(match.group(1)), int(match.group(2))
    living = len(LIVING_DOCS)
    problems: list[str] = []
    if after != living + 1:
        problems.append(
            f"the consolidation says {after} living documents; "
            f"LIVING_DOCS is {living} plus issue-records.md is {living + 1}"
        )
    if before != CONSOLIDATION_BEFORE:
        problems.append(
            f"the consolidation says {before} before; the 2026-10-16 tree held "
            f"{CONSOLIDATION_BEFORE}"
        )
    docs_md = sorted(path.name for path in (TOOLS / "docs").glob("*.md"))
    if docs_md != ["issue-records.md"]:
        problems.append(f"docs/*.md is {docs_md}, not only issue-records.md")
    return problems


def closure_count_problems(text: str) -> list[str]:
    """Why the consolidation's stated counts are not the counts this file holds.

    Separate from the test so the rule can be driven with the old text. Every
    number is read from the shipped file.
    """
    if "## 4. The consolidation" not in text:
        return ["issue-records.md lost its consolidation section"]
    section = text.split("## 4. The consolidation", 1)[1].split("\n## ", 1)[0]
    shape = issue_record_shape(text)
    problems: list[str] = []
    line_m = re.search(r"this one document \((\d+) lines\)", section)
    if line_m is None:
        problems.append("the consolidation never states this file's line count")
    elif int(line_m.group(1)) != shape["lines"]:
        problems.append(
            f"the consolidation says {line_m.group(1)} lines; the file has {shape['lines']}"
        )
    tag_m = re.search(r"(\d+) `### <TAG>,` headings", section)
    if tag_m is None:
        problems.append("the consolidation never states the TAG-heading count")
    elif int(tag_m.group(1)) != shape["tag"]:
        problems.append(
            f"the consolidation says {tag_m.group(1)} TAG headings; the file has {shape['tag']}"
        )
    h3_m = re.search(r"(\d+) `###` headings", section)
    if h3_m is None:
        problems.append("the consolidation never states the ### heading count")
    elif int(h3_m.group(1)) != shape["h3"]:
        problems.append(
            f"the consolidation says {h3_m.group(1)} ### headings; the file has {shape['h3']}"
        )
    numbered_m = re.search(r"(\d+) numbered `### N\.` issues", section)
    if numbered_m is None:
        problems.append("the consolidation never states the numbered-issue count")
    elif int(numbered_m.group(1)) != shape["numbered"]:
        problems.append(
            f"the consolidation says {numbered_m.group(1)} numbered issues; "
            f"the file has {shape['numbered']}"
        )
    fixed_m = re.search(r"(\d+) `\*\*Fixed:\*\*`\s+lines", section)
    if fixed_m is None:
        problems.append("the consolidation never states the Fixed-line count")
    elif int(fixed_m.group(1)) != shape["fixed"]:
        problems.append(
            f"the consolidation says {fixed_m.group(1)} Fixed lines; the file has {shape['fixed']}"
        )
    app_m = re.search(r"(\d+) appendix rows", section)
    if app_m is None:
        problems.append("the consolidation never states the appendix-row count")
    elif int(app_m.group(1)) != shape["appendix_rows"]:
        problems.append(
            f"the consolidation says {app_m.group(1)} appendix rows; "
            f"the file has {shape['appendix_rows']}"
        )
    problems += living_doc_count_problems(section)
    return problems


HISTORY_63_PROOF_CLASSES = (
    "WaitReady",
    "CheckLoraUrls",
    "ClassificationTest",
    "ACutOffReplyIsContinued",
)


def history_63_index_problems(issue_text: str, history_text: str) -> list[str]:
    """Why issue-records.md does not index history 63's later Fixed lines and deleted sweep.

    History 63 is a dated record and is not edited. The clarification lives here.
    Separate from the test so the rule can be driven with the old text. The
    ``**Fixed:**`` count is read from history 63.
    """
    problems: list[str] = []
    fixed_n = len(re.findall(r"\*\*Fixed:\*\*", history_text))
    note = ""
    for marker in ("History 63", "history 63"):
        if marker in issue_text:
            note = issue_text.split(marker, 1)[1]
            break
    if not note:
        problems.append("issue-records.md has no History 63 note")
        return problems
    opening = history_text.split("## 1.", 1)[0]
    if "Nothing in the repo was changed" in opening or "No fixes" in history_text:
        if "after the audit was written" not in note and "landed after" not in note:
            problems.append(
                "the History 63 note never says the fixes landed after the audit was written"
            )
        if str(fixed_n) not in note:
            problems.append(
                f"the History 63 note never states history 63's {fixed_n} **Fixed:** lines"
            )
    if "issue-sweep-2026-10-16b.md" in history_text:
        if "issue-sweep-2026-10-16b.md" not in note:
            problems.append(
                "the History 63 note never names the deleted issue-sweep-2026-10-16b.md"
            )
        for name in HISTORY_63_PROOF_CLASSES:
            if name not in note:
                problems.append(f"the History 63 note never names {name}")
    return problems


def vendor_litegraph_problems(vendor: str, graph_view: str) -> list[str]:
    """Why VENDOR.txt's LiteGraph line is not the LiteGraph button in graph_view.py.

    Separate from the test so the rule can be driven with the old text. The
    labels are read from the shipped widget text.
    """
    browser = re.search(
        r'text="([^"]+)", command=self\._open_browser', graph_view
    )
    comfy = re.search(
        r'text="([^"]+)", command=self\._open_litegraph', graph_view
    )
    if browser is None or comfy is None:
        return ["graph_view.py no longer labels the two HTML buttons"]
    line = next(
        (ln for ln in vendor.splitlines() if "litegraph.html" in ln), None
    )
    if line is None:
        return ["VENDOR.txt lost its litegraph.html line"]
    problems: list[str] = []
    if comfy.group(1) not in line:
        problems.append(
            f"VENDOR.txt does not label LiteGraph {comfy.group(1)!r} (graph_view.py does)"
        )
    if browser.group(1) in line and comfy.group(1) not in line:
        problems.append(
            f"VENDOR.txt still labels LiteGraph with {browser.group(1)!r}"
        )
    return problems


def skill_max_attempts_problems(
    skill: str, queue_max: int, cv_max: int
) -> list[str]:
    """Why the skill uses one MAX_ATTEMPTS name for the queue cap and the import-code cap.

    Separate from the test so the rule can be driven with the old text. The two
    values are read from the shipped modules.
    """
    if "## What the POST meets" not in skill:
        return ["the skill lost its POST section"]
    post = skill.split("## What the POST meets", 1)[1].split("## ", 1)[0]
    problems: list[str] = []
    if "salad_queue.MAX_ATTEMPTS" not in post:
        problems.append("the POST paragraph does not name salad_queue.MAX_ATTEMPTS")
    bare = re.findall(r"(?<![\w.])MAX_ATTEMPTS", post)
    qualified = post.count("salad_queue.MAX_ATTEMPTS")
    if len(bare) > qualified:
        problems.append("the POST paragraph still uses a bare MAX_ATTEMPTS")
    if "civitai_verify.MAX_ATTEMPTS" not in skill:
        problems.append("the skill does not name civitai_verify.MAX_ATTEMPTS")
    if queue_max == cv_max:
        problems.append(
            f"salad_queue.MAX_ATTEMPTS and civitai_verify.MAX_ATTEMPTS are both {queue_max}"
        )
    return problems


def recipe_method_count(path: Path) -> int:
    """``def test_`` methods in a shipped test module."""
    return len(re.findall(r"^\s+def test_", path.read_text(encoding="utf-8"), re.M))


def civitai_verify_max_attempts() -> int:
    """``civitai_verify.MAX_ATTEMPTS``, read from the shipped source."""
    match = re.search(
        r"^MAX_ATTEMPTS = (\d+)",
        (PKG / "civitai_verify.py").read_text(encoding="utf-8"),
        re.M,
    )
    if match is None:
        raise AssertionError("civitai_verify.py no longer assigns MAX_ATTEMPTS")
    return int(match.group(1))


class LivingDocsNameTheShippedArtifacts(unittest.TestCase):
    """Every pointer a living doc makes must resolve to the shipped artifact."""

    def test_doc_14_body_pointer_names_the_shipped_composer(self) -> None:
        problems = body_compose_pointer_problems(
            DOC14.read_text(encoding="utf-8"),
            KLEIN_PROBE.read_text(encoding="utf-8"),
            json.loads(FACE_PACK.read_text(encoding="utf-8")),
        )
        self.assertEqual(problems, [], "\n".join(problems))

    def test_doc_15_anatomy_seed_is_the_shipped_seed(self) -> None:
        seeds = [anatomy_seed(path) for path in ANATOMY_RECIPES]
        self.assertEqual(len(set(seeds)), 1, "the two anatomy recipes disagree on the seed")
        problems = anatomy_seed_problems(FLUX2_DOC.read_text(encoding="utf-8"), seeds)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_doc_15_lora_chain_names_the_shipped_loaders(self) -> None:
        loaders: list[tuple[int, float]] = []
        for path in ANATOMY_RECIPES:
            loaders += anatomy_loaders(path)
        self.assertEqual(
            len(loaders), 8, "the two anatomy recipes must carry four loaders each"
        )
        problems = anatomy_chain_problems(FLUX2_DOC.read_text(encoding="utf-8"), loaders)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_doc_15_placeholder_claim_is_the_recipe_tests_rule(self) -> None:
        source = RECIPE_TEST.read_text(encoding="utf-8")
        forbidden = forbidden_tokens(source)
        self.assertTrue(forbidden, "test_klein_recipes.py no longer carries FORBIDDEN")
        problems = placeholder_claim_problems(
            FLUX2_DOC.read_text(encoding="utf-8"), forbidden, source
        )
        self.assertEqual(problems, [], "\n".join(problems))

    def test_doc_19_prompt_pointer_resolves_to_the_ledger(self) -> None:
        ledger = json.loads((KLEIN / "prompt_ledger.json").read_text(encoding="utf-8"))
        problems = prompt_pointer_problems(
            DOC19.read_text(encoding="utf-8"), ledger["verdicts"][0]
        )
        self.assertEqual(problems, [], "\n".join(problems))

    def test_doc_22_row_cite_lands_on_the_row(self) -> None:
        problems = row_cite_problems(
            DOC22.read_text(encoding="utf-8"),
            DOC14.read_text(encoding="utf-8").splitlines(),
        )
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_issue_record_names_real_test_classes(self) -> None:
        problems = proof_class_problems(
            ISSUE_RECORD.read_text(encoding="utf-8"), _read_test_module
        )
        self.assertEqual(problems, [], "\n".join(problems))
        self._assert_audit_docs_live()

    def _assert_audit_docs_live(self) -> None:
        """The 2026-10-16 docs-audit claims, each read from the shipped file."""
        issue_text = ISSUE_RECORD.read_text(encoding="utf-8")
        deploy_text = DEPLOYMENT.read_text(encoding="utf-8")
        with self.subTest("D-README-63"):
            self.assertEqual(
                history_index_problems(
                    ROOT_README.read_text(encoding="utf-8"), HISTORY_DIR
                ),
                [],
            )
        with self.subTest("D-IR-LEN-TAGS"):
            self.assertEqual(closure_count_problems(issue_text), [])
        with self.subTest("D-17-COUNT"):
            self.assertEqual(
                klein_recipes_count_problems(
                    DOC17.read_text(encoding="utf-8"),
                    recipe_method_count(HERE / "test_klein_recipes.py"),
                ),
                [],
            )
        with self.subTest("D-23-HISTORY"):
            self.assertEqual(
                wrapper_result_problems(
                    deploy_text, SALAD_GEN.read_text(encoding="utf-8")
                ),
                [],
            )
        with self.subTest("D-15-23-SEC"):
            self.assertEqual(
                docker_gpus_cite_problems(
                    FLUX2_DOC.read_text(encoding="utf-8"), deploy_text
                ),
                [],
            )
        with self.subTest("D-22-23-REPL"):
            self.assertEqual(
                replica_recipe_problems(
                    DOC22.read_text(encoding="utf-8"), deploy_text
                ),
                [],
            )
        with self.subTest("H-63"):
            self.assertEqual(
                history_63_index_problems(
                    issue_text, HISTORY_63.read_text(encoding="utf-8")
                ),
                [],
            )
        with self.subTest("P-VENDOR-LABEL"):
            self.assertEqual(
                vendor_litegraph_problems(
                    VENDOR.read_text(encoding="utf-8"),
                    GRAPH_VIEW.read_text(encoding="utf-8"),
                ),
                [],
            )
        with self.subTest("D-SKILL-MAX"):
            self.assertEqual(
                skill_max_attempts_problems(
                    SKILL.read_text(encoding="utf-8"),
                    q.MAX_ATTEMPTS,
                    civitai_verify_max_attempts(),
                ),
                [],
            )


class TheDocDriftRulesCatchTheOldText(unittest.TestCase):
    """Each rule, driven against the pre-fix text it was written for.

    A check nobody has seen fail is a check that may not work, so every rule
    above is re-run here on the text the audit found.
    """

    def test_the_body_pointer_rule_catches_the_pack_pointer(self) -> None:
        old = (
            "- Body compose: `face_prompt_pack.json` `body_style` + the "
            "`body_t2i` template\n"
        )
        problems = body_compose_pointer_problems(
            old,
            KLEIN_PROBE.read_text(encoding="utf-8"),
            json.loads(FACE_PACK.read_text(encoding="utf-8")),
        )
        self.assertTrue(problems, "the rule missed the pack pointer")
        self.assertTrue(any("_klein_body_prompt" in p for p in problems), problems)
        self.assertTrue(any("body_t2i" in p for p in problems), problems)

    def test_the_seed_rule_catches_the_old_seed(self) -> None:
        old = "832x1216, seed\n`823441907752101` in both files.\n"
        problems = anatomy_seed_problems(
            old, [anatomy_seed(path) for path in ANATOMY_RECIPES]
        )
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("823441907752101", problems[0])

    def test_the_chain_rule_catches_the_old_chain(self) -> None:
        old = (
            "The `LoraLoader` chain 70→80→81→82→83 is Detail Slider "
            "`civitai:2334190@2625692` −1.5, Klein Fixes NSFW "
            "`civitai:2482439@2790993` 1.0, Klein Anatomy / Quality Fixer v1.5 "
            "`civitai:2324991@2615554` 2.0, General Penis LoRA v1.0 "
            "`civitai:2333479@2624854` 0.8; the last loader takes both "
            "`CLIPTextEncode` nodes.\n"
        )
        loaders: list[tuple[int, float]] = []
        for path in ANATOMY_RECIPES:
            loaders += anatomy_loaders(path)
        problems = anatomy_chain_problems(old, loaders)
        self.assertTrue(problems, "the rule missed the old chain")
        self.assertTrue(any("2763568" in p for p in problems), problems)
        self.assertTrue(any("2624854" in p for p in problems), problems)

    def test_the_placeholder_rule_catches_the_angle_bracket_claim(self) -> None:
        old = (
            "`test_klein_recipes.py` fails on `REPLACE_THIS`, `TODO`, `TBD`, "
            "`XXX`, `FIXME` and angle brackets.\n"
        )
        source = RECIPE_TEST.read_text(encoding="utf-8")
        problems = placeholder_claim_problems(old, forbidden_tokens(source), source)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("angle-bracket", problems[0])

    def test_the_prompt_pointer_rule_catches_the_below_promise(self) -> None:
        old = (
            "Node 74 now contains the prompt quoted below, and node **67** "
            "(previously empty) holds the negative below.\n"
        )
        ledger = json.loads((KLEIN / "prompt_ledger.json").read_text(encoding="utf-8"))
        problems = prompt_pointer_problems(old, ledger["verdicts"][0])
        self.assertTrue(problems, "the rule missed the unkept promise")
        self.assertTrue(any("below" in p for p in problems), problems)

    def test_the_row_cite_rule_catches_the_five_line_miss(self) -> None:
        old = (
            "the `Official Salad Comfy recipes` row at "
            "`docs/workflow/14-salad-comfy-live-findings.md:42`\n"
        )
        problems = row_cite_problems(old, DOC14.read_text(encoding="utf-8").splitlines())
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(":42", problems[0])

    def test_the_proof_rule_catches_the_four_absent_classes(self) -> None:
        old = (
            "Proved by `tests/test_generator.py::TheWaitNamesWhatFailed."
            "test_the_last_probe_names_the_probe_count_and_the_budget`.\n"
            "Proved by `tests/test_generator.py::TheProbeSummary."
            "test_a_url_neither_method_answers_reports_the_summary`.\n"
            "Proved by `tests/test_salad_queue.py::TheGaveUpReason."
            "test_a_job_that_exhausts_its_attempts_records_the_gave_up_reason`.\n"
            "Proved by `tests/test_ai_helper.py::TheExhaustedBudget."
            "test_an_exhausted_budget_returns_the_stitched_text`.\n"
        )
        problems = proof_class_problems(old, _read_test_module)
        self.assertEqual(len(problems), 4, problems)
        for name in (
            "TheWaitNamesWhatFailed",
            "TheProbeSummary",
            "TheGaveUpReason",
            "TheExhaustedBudget",
        ):
            self.assertTrue(
                any(name in problem for problem in problems),
                f"the rule missed {name}: {problems}",
            )
        self._assert_audit_docs_old_text()

    def _assert_audit_docs_old_text(self) -> None:
        """Each 2026-10-16 docs-audit rule, driven against a scratch copy of the pre-fix text."""
        real_recipes = recipe_method_count(HERE / "test_klein_recipes.py")
        with tempfile.TemporaryDirectory() as td:
            scratch = Path(td)

            old_readme = scratch / "README.md"
            old_readme.write_text(
                "| `docs/history/` | Dated records of the studio: audits "
                "[57](docs/history/57-salad-studio-audit-2026-09.md), "
                "[58](docs/history/58-salad-studio-audit-2026-09-22.md), "
                "[59](docs/history/59-salad-studio-audit-2026-09-26.md), "
                "[61](docs/history/61-salad-studio-audit-2026-10-13.md), "
                "[62](docs/history/62-salad-studio-audit-2026-10-14.md), and the "
                "container-restart investigation "
                "[60](docs/history/60-salad-container-restart-2026-09-27.md). |\n",
                encoding="utf-8",
            )
            with self.subTest("D-README-63"):
                problems = history_index_problems(
                    old_readme.read_text(encoding="utf-8"), HISTORY_DIR
                )
                self.assertTrue(problems, "the rule missed the omitted history 63")
                self.assertTrue(
                    any("63-salad-studio-audit-2026-10-16.md" in p for p in problems),
                    problems,
                )

            old_ir = scratch / "issue-records.md"
            old_ir.write_text(
                "## 4. The consolidation\n\n"
                "The six dated issue records became this one document (1299 lines): "
                "`docs/*.md` now holds only `issue-records.md`, so the "
                "living-document count fell **19 → 14**. The extraction kept 48 "
                "`### <TAG>,` headings, 5 `**Fixed:**` lines and 83 appendix rows, "
                "and a survival check confirms each appears here.\n",
                encoding="utf-8",
            )
            with self.subTest("D-IR-LEN-TAGS"):
                problems = closure_count_problems(old_ir.read_text(encoding="utf-8"))
                self.assertTrue(problems, "the rule missed the stale closure counts")
                self.assertTrue(
                    any("1299" in p and "lines" in p for p in problems), problems
                )
                self.assertTrue(
                    any("48" in p and "TAG" in p for p in problems), problems
                )

            old_17 = scratch / "17.md"
            old_17.write_text(
                "- `salad_klein/README.md`; `tests/test_klein_recipes.py`, "
                "17 tests asserting the verified entry.\n",
                encoding="utf-8",
            )
            with self.subTest("D-17-COUNT"):
                problems = klein_recipes_count_problems(
                    old_17.read_text(encoding="utf-8"), real_recipes
                )
                self.assertTrue(problems, "the rule missed the 17-test claim")
                self.assertTrue(any("17" in p for p in problems), problems)

            old_23 = scratch / "23.md"
            old_23.write_text(
                "| Result | `GET /history/<prompt_id>` then `/view` for the image |\n\n"
                "`salad_gen.py` is a working caller.\n",
                encoding="utf-8",
            )
            with self.subTest("D-23-HISTORY"):
                problems = wrapper_result_problems(
                    old_23.read_text(encoding="utf-8"),
                    SALAD_GEN.read_text(encoding="utf-8"),
                )
                self.assertTrue(problems, "the rule missed GET /history as the Result")
                self.assertTrue(any("GET /history" in p for p in problems), problems)

            old_15 = scratch / "15.md"
            old_15.write_text(
                "a 24 GB local card adds `--gpus all -p 8188:8188`, "
                "[doc 23 §3](23-salad-container-group-deployment.md):\n",
                encoding="utf-8",
            )
            with self.subTest("D-15-23-SEC"):
                problems = docker_gpus_cite_problems(
                    old_15.read_text(encoding="utf-8"),
                    DEPLOYMENT.read_text(encoding="utf-8"),
                )
                self.assertTrue(problems, "the rule missed the docker cite of §3")
                self.assertTrue(any("§3" in p for p in problems), problems)

            old_22 = scratch / "22.md"
            old_22.write_text(
                "- Gateway and control-plane behaviour, including what cannot be "
                "changed after creation: doc 18 §3's table and doc 23 §2.2/§3. "
                "Default is **3 replicas**; at least 3 for testing and "
                "**at least 5 for production**, since nodes are "
                "**interruptible without warning** [9].\n",
                encoding="utf-8",
            )
            with self.subTest("D-22-23-REPL"):
                problems = replica_recipe_problems(
                    old_22.read_text(encoding="utf-8"),
                    DEPLOYMENT.read_text(encoding="utf-8"),
                )
                self.assertTrue(problems, "the rule missed the 3-replica default")
                self.assertTrue(
                    any(
                        "1 replica" in p or "3 replica" in p or "product default" in p
                        for p in problems
                    ),
                    problems,
                )

            old_ir_no63 = scratch / "issue-records-no63.md"
            old_ir_no63.write_text(
                "# Issue records\n\nThe six dated issue records became this one document.\n",
                encoding="utf-8",
            )
            with self.subTest("H-63"):
                problems = history_63_index_problems(
                    old_ir_no63.read_text(encoding="utf-8"),
                    HISTORY_63.read_text(encoding="utf-8"),
                )
                self.assertTrue(problems, "the rule missed a missing History 63 note")
                self.assertTrue(
                    any("History 63 note" in p for p in problems), problems
                )

            old_vendor = scratch / "VENDOR.txt"
            old_vendor.write_text(
                "  ComfyUI's editor engine. Kept as litegraph.html "
                "(Open in browser alternative).\n",
                encoding="utf-8",
            )
            with self.subTest("P-VENDOR-LABEL"):
                problems = vendor_litegraph_problems(
                    old_vendor.read_text(encoding="utf-8"),
                    GRAPH_VIEW.read_text(encoding="utf-8"),
                )
                self.assertTrue(problems, "the rule missed the LiteGraph button label")
                self.assertTrue(
                    any("Open as Comfy" in p or "Open in browser" in p for p in problems),
                    problems,
                )

            old_skill = scratch / "SKILL.md"
            old_skill.write_text(
                "## What the POST meets\n\n"
                "retried automatically, up to `MAX_ATTEMPTS` attempts with "
                "`RETRY_SLEEP_S` seconds between them.\n\n"
                "## Agent loop\n\n"
                "8. Cap: `MAX_ATTEMPTS` (`civitai_verify.py`).\n",
                encoding="utf-8",
            )
            with self.subTest("D-SKILL-MAX"):
                problems = skill_max_attempts_problems(
                    old_skill.read_text(encoding="utf-8"),
                    q.MAX_ATTEMPTS,
                    civitai_verify_max_attempts(),
                )
                self.assertTrue(problems, "the rule missed the shared MAX_ATTEMPTS name")
                self.assertTrue(
                    any("salad_queue.MAX_ATTEMPTS" in p for p in problems), problems
                )

            old_21 = scratch / "21.md"
            old_21.write_text(
                "9. **Keep `_meta` on every `LoraLoader`.** See §5. It is load-bearing.\n",
                encoding="utf-8",
            )
            with self.subTest("D-META-DRIFT"):
                nodes = lora_meta_nodes(KLEIN_RECIPES)
                problems = meta_advice_problems(
                    old_21.read_text(encoding="utf-8"), nodes
                )
                self.assertTrue(problems, "the rule missed doc 21's universal _meta claim")
                self.assertTrue(
                    any("on every `LoraLoader`" in p for p in problems), problems
                )


if __name__ == "__main__":
    unittest.main()
