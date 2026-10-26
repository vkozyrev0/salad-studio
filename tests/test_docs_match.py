"""The manuals must describe the app that shipped.

Every check below reads a real file and compares it with the shipped code: the
app manual's tab list against the page ids, the manual's layer map against
the modules on disk, the stated test counts — the root suite and the
container-side one — against the number of test methods the suites actually
have, the workflow documents' ``§N`` references against the headings of the
documents they name, and their pointers at shipped artifacts against the code
that ships. A doc that drifts fails here instead of being discovered by a reader.
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
from salad_studio.web.registry import PAGE_IDS  # noqa: E402

MANUAL = PKG / "README.md"
ROOT_README = TOOLS / "README.md"
DEPLOYMENT = TOOLS / "docs" / "workflow" / "23-salad-container-group-deployment.md"
# The container-side suite, and the one live doc that states a count for the
# root-suite recipe module. `salad_klein/README.md` documents both commands.
KLEIN = TOOLS / "salad_klein"
KLEIN_README = KLEIN / "README.md"
FLUX2_DOC = TOOLS / "docs" / "workflow" / "15-salad-flux2-klein-group.md"
HANDOFF = TOOLS / "docs" / "workflow" / "21-klein-image-handoff.md"


# The rail's titles, in the order the server installs the pages.
_PAGE_TITLES = ("Config", "Prompt Settings", "Tokens", "LoRAs", "Prompt Editor",
                "Prompt Assist", "Prompt Catalog", "Import", "Prompt History",
                "Queue", "Logs")


class TabListMatchesTheApp(unittest.TestCase):
    def test_the_manual_lists_every_tab_in_order(self) -> None:
        text = MANUAL.read_text(encoding="utf-8")
        head = text.split("## Layers", 1)[0]
        start = head.index("**Config**")
        block = head[start : head.index(").", start)]
        listed = re.findall(r"\*\*([^*]+)\*\*", block)
        self.assertEqual(
            listed,
            [name.strip() for name in _PAGE_TITLES],
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
        source = (PKG / "web" / "pages" / "config.py").read_text(encoding="utf-8")
        page = (TOOLS / "ui" / "src" / "app" / "pages" / "config" / "config-page.ts").read_text(
            encoding="utf-8")
        for label in (
            "Add profile",
            "Delete profile",
            "Save profile",
            "Checkpoints this profile serves",
            "Remove selected",
        ):
            self.assertIn(label, page, f"the Config page no longer ships {label!r}")
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
            web = PKG / "web" / module
            self.assertTrue(
                (where / module).is_file() or web.is_file(),
                f"the layer map names {module}, which is not in {where.name}/ or its web/",
            )

    def test_every_module_in_the_package_is_mapped(self) -> None:
        text = MANUAL.read_text(encoding="utf-8")
        section = text.split("## Layers", 1)[1].split("### Metadata document", 1)[0]
        named = set(re.findall(r"`([a-z_]+\.py)`", section))
        shipped = {p.name for p in PKG.glob("*.py")} | {p.name for p in (PKG / "web").glob("*.py")}
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
        source = (PKG / "web" / "pages" / "assist.py").read_text(encoding="utf-8")
        self.assertIn("Help (DeepSeek)", manual, "the manual names the DeepSeek button")
        self.assertIn("Help (local)", manual, "and the local one")
        self.assertIn("BACKENDS", source, "the controller names the backends it serves")
        self.assertIn(
            "OpenAI-compatible", manual, "and says what the local one talks to"
        )
        self.assertIn(
            "LM Studio", manual, "and where the local server usually comes from"
        )

        page = (TOOLS / "ui" / "src" / "app" / "pages" / "assist" / "assist-page.ts")
        page_text = page.read_text(encoding="utf-8")
        self.assertIn("Reply", page_text, "the reply pane's title must be on the page")
        for where, text in (("the manual", manual), ("assist.py", source), ("the page", page_text)):
            self.assertNotIn(
                "DeepSeek reply", text, f"{where} still calls the pane DeepSeek-only"
            )
            self.assertNotIn(
                "no image is sent to DeepSeek",
                text,
                f"{where} still names one backend for the image note",
            )
            self.assertNotIn(
                "Ask DeepSeek for help first.",
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
        """Both manuals state the count, and both have drifted before.

        One module can be run on its own, so that run counts only what it ran:
        the manuals state the whole suite, which is every module here.
        """
        real = self._real_count()
        whole = self._whole_count()
        for path in (ROOT_README, MANUAL):
            text = path.read_text(encoding="utf-8")
            match = re.search(r"#\s*(\d+)\s+tests", text)
            self.assertIsNotNone(
                match, f"{path.name} no longer states a test count"
            )
            stated = int(match.group(1))
            if real >= whole:
                self.assertEqual(
                    stated, real, f"{path.name} says {stated} tests; the suite has {real}"
                )
            else:
                # A module run counts only the modules it ran, so the stated
                # number, which counts the whole suite, is only a lower bound.
                self.assertGreaterEqual(
                    stated, real, f"{path.name} says {stated} tests; this run found {real}"
                )

    def _whole_count(self) -> int:
        """Every test here: a module this run has not imported is loaded to count it."""
        loader = unittest.defaultTestLoader
        per_module = sum(loader.loadTestsFromName(p.stem).countTestCases()
                         for p in HERE.glob("test_*.py"))
        return max(per_module, self._real_count())


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
    first count in each README, so the container line below it needs its own
    check, and ``salad_klein/README.md`` states no count at all.
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
    """A markdown link to a file that moved is a dead end for a reader."""

    # ``node_modules`` is the Angular app's installed packages: its own READMEs
    # are not this repo's docs, and their links are resolved from a registry.
    SKIP = ("custom_nodes", "weights", "__pycache__", ".git", "node_modules")

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


# The living docs: the workflow handbooks, the three READMEs and the skill.
LIVING_DOCS = tuple(sorted((TOOLS / "docs" / "workflow").glob("*.md"))) + (
    ROOT_README,
    MANUAL,
    KLEIN_README,
    SKILL,
)


# The anatomy recipe's shipped scheduler, and the doc line that states its step
# count. The two are read together and compared.
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
# with a `LoraLoader`'s `_meta` block. The shipped files decide whether the advice
# can claim a block on every node.
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
# long options each parser accepts. Doc 14 names `ckpt_name` / `lora_name` as
# `flux_payload()` parameters, so a bare name in the
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


# The section references a document makes - `§3`, `§3.2` - must name a section it
# has.
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
# framing the reader cannot find.
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
    """A `§N` a living document names must be a section of the document it names."""

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
# the body composer, the anatomy recipes, the recipe test and the ledger. Every
# rule below reads the code the claim is about, so a pointer that drifts from the
# tree fails here instead of at a reader.
DOC14 = TOOLS / "docs" / "workflow" / "14-salad-comfy-live-findings.md"
DOC19 = TOOLS / "docs" / "workflow" / "21-klein-image-handoff.md"
DOC22 = TOOLS / "docs" / "workflow" / "22-two-body-correctness-research.md"
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

    def test_doc_22_replica_default_is_the_group_recipe(self) -> None:
        problems = replica_recipe_problems(
            DOC22.read_text(encoding="utf-8"), DEPLOYMENT.read_text(encoding="utf-8")
        )
        self.assertEqual(problems, [], "\n".join(problems))

    def test_doc_23_result_row_is_what_salad_gen_reads(self) -> None:
        problems = wrapper_result_problems(
            DEPLOYMENT.read_text(encoding="utf-8"),
            SALAD_GEN.read_text(encoding="utf-8"),
        )
        self.assertEqual(problems, [], "\n".join(problems))

    def test_doc_15_docker_cite_names_a_section_with_the_command(self) -> None:
        problems = docker_gpus_cite_problems(
            FLUX2_DOC.read_text(encoding="utf-8"), DEPLOYMENT.read_text(encoding="utf-8")
        )
        self.assertEqual(problems, [], "\n".join(problems))

    def test_doc_15_recipe_count_is_the_module_count(self) -> None:
        problems = klein_recipes_count_problems(
            FLUX2_DOC.read_text(encoding="utf-8"),
            recipe_method_count(RECIPE_TEST),
        )
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_skill_names_the_two_retry_caps(self) -> None:
        problems = skill_max_attempts_problems(
            SKILL.read_text(encoding="utf-8"),
            q.MAX_ATTEMPTS,
            civitai_verify_max_attempts(),
        )
        self.assertEqual(problems, [], "\n".join(problems))


class TheDocDriftRulesCatchTheOldText(unittest.TestCase):
    """Each rule, driven against the pre-fix text it was written for.

    A check nobody has seen fail is a check that may not work, so each rule is
    re-run here on the text it was written for.
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


class ShippedArtifactsAreNamed(unittest.TestCase):
    def test_the_readme_names_the_ci_and_the_queue_check(self) -> None:
        text = ROOT_README.read_text(encoding="utf-8")
        self.assertIn(".github/workflows/checks.yml", text)
        self.assertIn("queue-submission-safety", text)

    def test_the_manual_names_the_history_columns(self) -> None:
        text = MANUAL.read_text(encoding="utf-8")
        for name in ("When", "Prompt", "Graph", "Rating", "Plate"):
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
