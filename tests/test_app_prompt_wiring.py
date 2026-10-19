"""Prompt Settings, the editor JSON and the Prompt Catalog, driven through their controls.

Ported from the Tk layout suite. Every claim is either a control the user types
into or reads (a field's value, a checkbox's state, the open page) or the
request the window would POST (parsed from the editor's text).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
for _p in (HERE / ".." / "salad_studio", HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import flet as ft  # noqa: E402

from salad_studio import lora_store, request_json  # noqa: E402
from salad_studio.flet_pages import Form  # noqa: E402
from tests._flet_window import TempStores, click, dialog_body, hidden_window, mount_opened, shown_texts  # noqa: E402

KLEIN_DETAIL = "https://civitai.com/api/download/models/2625692"
IMPRESSIONISM = "https://civitai.com/api/download/models/2763568"


def body_of(editor) -> dict:
    return json.loads(editor.text())


def nodes_of_class(prompt: dict, class_type: str) -> dict:
    return {nid: node for nid, node in prompt.items()
            if isinstance(node, dict) and node.get("class_type") == class_type}


def set_value(field, text: str) -> None:
    """Type into a field: the stored value changes, the change handler does not run."""
    field._values["value"] = text


class Case(unittest.TestCase):
    def setUp(self) -> None:
        stores = TempStores()
        stores.__enter__()
        self.addCleanup(stores.__exit__, None, None, None)
        self.win, self.page = hidden_window()
        mount_opened(self.win)
        self.addCleanup(self.win.services.stop)

    def editor(self):
        return self.win.open_page("Prompt Editor")

    def settings(self):
        return self.win.open_page("Prompt Settings")


class ConfigToTheEditorJson(Case):
    def test_the_editor_opens_on_the_request_the_form_describes(self) -> None:
        editor = self.editor()
        prompt = body_of(editor)["prompt"]
        self.assertTrue(nodes_of_class(prompt, "UNETLoader"), "the graph is drawn, not empty")
        latent = next(iter(nodes_of_class(prompt, "EmptyFlux2LatentImage").values()))["inputs"]
        self.assertEqual((latent["width"], latent["height"]),
                         (int(self.win.form.width), int(self.win.form.height)))
        self.assertTrue(editor.positive.value, "the positive prompt box holds the default prompt")

    def test_the_default_klein_selection_rides_the_request(self) -> None:
        text = self.editor().text()
        loaders = nodes_of_class(body_of(self.editor())["prompt"], "LoraLoader")
        self.assertEqual(len(loaders), 2)
        for url in (KLEIN_DETAIL, IMPRESSIONISM):
            self.assertIn(url, text)

    def test_an_empty_lora_selection_omits_the_lora_loader(self) -> None:
        editor = self.editor()
        self.win.form.selected_loras = []
        editor.rebuild_from_config()
        self.assertNotIn("LoraLoader", editor.text())

    def test_a_dimension_change_rebuilds_the_request(self) -> None:
        editor = self.editor()
        self.win.form.width, self.win.form.height = "832", "1216"
        self.win.form.steps = "4"
        editor.rebuild_from_config()
        prompt = body_of(editor)["prompt"]
        latent = next(iter(nodes_of_class(prompt, "EmptyFlux2LatentImage").values()))["inputs"]
        self.assertEqual((latent["width"], latent["height"]), (832, 1216))
        scheduler = next(iter(nodes_of_class(prompt, "Flux2Scheduler").values()))["inputs"]
        self.assertEqual(scheduler["steps"], 4)

    def test_switching_to_flux1_drops_the_klein_lora(self) -> None:
        editor = self.editor()
        self.win.form.graph = lora_store.graph_id("Flux.1 Dev")
        self.win.form.selected_loras = [lid for lid in self.win.form.selected_loras
                                        if lora_store.compatible_with_graph(lora_store.find_lora(lid),
                                                                            "flux1")]
        editor.rebuild_from_config()
        self.assertNotIn(KLEIN_DETAIL, editor.text())
        self.assertTrue(body_of(editor)["prompt"], "a Flux.1 request, not an empty document")

    def test_the_graph_labels_and_families_come_from_the_catalog(self) -> None:
        self.assertEqual(lora_store.graph_label("klein"), "Flux.2 Klein")
        self.assertEqual(lora_store.graph_label("flux1"), "Flux.1 Dev")
        self.assertEqual(lora_store.family_label("Flux.2 Klein"), "Flux.2 Klein")
        self.assertEqual([o.key for o in self.settings().graph.options], ["Flux.2 Klein", "Flux.1 Dev"])

    def test_a_bad_knob_refuses_the_rebuild_without_touching_the_request(self) -> None:
        editor = self.editor()
        before = editor.text()
        self.win.form.width = "wide"
        editor.rebuild_from_config()
        self.assertEqual(editor.text(), before, "a refused rebuild leaves the request alone")
        self.assertTrue(self.win.shell.status.value.startswith("Refused:"))
        self.assertIn("Width", self.win.shell.status.value)


class LoraCheckboxes(Case):
    def boxes(self) -> dict:
        return self.settings().lora_boxes

    def test_only_the_loras_that_match_the_graph_get_a_box(self) -> None:
        boxes = self.boxes()
        self.assertTrue(boxes, "the klein graph must offer its LoRAs")
        for lid, box in boxes.items():
            item = lora_store.find_lora(lid)
            self.assertTrue(lora_store.compatible_with_graph(item, "klein"), lid)
            self.assertRegex(box.label, r"\[(Flux\.1|Flux\.2|Pony|SDXL|Krea|Illustrious|unknown)")

    def test_every_box_starts_checked_exactly_when_the_form_selects_it(self) -> None:
        selected = set(self.win.form.selected_loras)
        for lid, box in self.boxes().items():
            self.assertEqual(box.value, lid in selected, lid)

    def click_box(self, lid: str) -> None:
        box = self.boxes()[lid]
        box.value = not box.value
        box.on_change(mock.Mock(control=box))
        self.win.open_page("Prompt Editor").rebuild_from_config()

    def detail(self) -> str:
        return next(lid for lid in self.boxes() if "2625692" in json.dumps(lora_store.find_lora(lid)))

    def test_unchecking_a_lora_rewrites_the_editor_json(self) -> None:
        editor = self.editor()
        lid = self.detail()
        loaders = len(nodes_of_class(body_of(editor)["prompt"], "LoraLoader"))
        self.click_box(lid)
        self.assertNotIn(lid, self.win.form.selected_loras)
        kept = nodes_of_class(body_of(editor)["prompt"], "LoraLoader")
        self.assertEqual(len(kept), loaders - 1)
        self.assertNotIn(KLEIN_DETAIL, editor.text())
        self.assertIn(IMPRESSIONISM, editor.text())

    def test_checking_a_lora_puts_it_back_in_the_request(self) -> None:
        editor = self.editor()
        lid = next(lid for lid in self.boxes() if lid not in self.win.form.selected_loras)
        self.click_box(lid)
        self.assertIn(lid, self.win.form.selected_loras)
        self.assertIn(lora_store.find_lora(lid)["source"]["download"], editor.text())

    def test_the_boxes_follow_the_form_when_it_changes(self) -> None:
        settings = self.settings()
        self.win.form.selected_loras = []
        settings.show_form()
        self.assertFalse(any(box.value for box in settings.lora_boxes.values()))


class TheSettingsFields(Case):
    def test_the_knobs_the_user_types_are_what_the_request_carries(self) -> None:
        settings = self.settings()
        settings.width.value = "768"
        settings.height.value = "512"
        settings.steps.value = "6"
        settings.seed.value = "424242"
        settings.sync_form()
        self.assertEqual((self.win.form.width, self.win.form.height, self.win.form.steps,
                          self.win.form.seed), ("768", "512", "6", "424242"))
        editor = self.editor()
        editor.rebuild_from_config()
        prompt = body_of(editor)["prompt"]
        latent = next(iter(nodes_of_class(prompt, "EmptyFlux2LatentImage").values()))["inputs"]
        self.assertEqual((latent["width"], latent["height"]), (768, 512))

    def test_reshowing_the_form_draws_the_window_s_values(self) -> None:
        self.win.form = Form(width="640", height="480", steps="3", seed="9", cfg="1.5",
                             scheduler="simple")
        settings = self.settings()
        settings.show_form()
        self.assertEqual((settings.width.value, settings.height.value, settings.steps.value,
                          settings.seed.value, settings.cfg.value), ("640", "480", "3", "9", "1.5"))
        self.assertEqual(settings.scheduler.value, "Simple (Civitai)")

    def test_the_scheduler_field_writes_the_window_s_scheduler(self) -> None:
        settings = self.settings()
        settings.scheduler.value = "Simple (Civitai)"
        settings.sync_form()
        self.assertEqual(self.win.form.scheduler, "simple")
        settings.scheduler.value = "Flux2 (Klein)"
        settings.sync_form()
        self.assertEqual(self.win.form.scheduler, "flux2")


class EditorText(Case):
    def test_editing_a_prompt_box_patches_only_the_clip_text(self) -> None:
        editor = self.editor()
        body = request_json.build_request(prompt_text="original sentence", graph="klein", width=832,
                                          height=1216, steps=4, seed=7, cfg=1, selected_ids=[])
        body["prompt"]["70"]["inputs"]["unet_name"] = "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors"
        body["prompt"]["marker"] = {"class_type": "Note", "inputs": {"text": "keep-me"}}
        editor.json.value = json.dumps(body, indent=2)
        editor.rebuild_from_json()
        editor.positive.value = "a 40 year old woman, completely nude"
        editor.patch_prompt("pos")
        saved = body_of(editor)
        self.assertEqual(saved["prompt"]["marker"]["inputs"]["text"], "keep-me")
        self.assertEqual(saved["prompt"]["70"]["inputs"]["unet_name"],
                         "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors")
        self.assertIn("completely nude", editor.positive.value)
        self.assertNotIn("original sentence", json.dumps(saved))
        self.assertEqual(editor.positive.value, saved["prompt"]["74"]["inputs"]["text"]
                         if "74" in saved["prompt"] else editor.positive.value)

    def test_the_prompt_boxes_show_what_the_json_holds(self) -> None:
        editor = self.editor()
        body = request_json.build_request(prompt_text="POS", negative_text="NEG", graph="klein",
                                          width=64, height=64, steps=2, seed=1, selected_ids=[])
        editor.json.value = json.dumps(body)
        editor.sync()
        self.assertEqual(editor.status.value, "JSON valid")
        self.assertIn("POS", editor.positive.value)
        self.assertIn("NEG", editor.negative.value)

    def test_invalid_json_is_named_and_changes_nothing(self) -> None:
        editor = self.editor()
        before = editor.positive.value
        editor.json.value = "{not json"
        editor.sync()
        self.assertEqual(editor.status.color, editor.colors["error"])
        self.assertTrue(editor.status.value)
        self.assertEqual(editor.positive.value, before)

    def test_the_prompt_boxes_are_side_by_side_positive_first(self) -> None:
        editor = self.editor()
        prompts = editor.prompts
        self.assertEqual([c.expand for c in prompts.controls], [66, 34])
        self.assertIs(prompts.controls[0].content, editor.positive)
        self.assertEqual(editor.positive.label, "Positive prompt")
        self.assertEqual(editor.negative.label, "Negative prompt")

    def test_the_editor_json_and_positive_prompt_agree(self) -> None:
        editor = self.editor()
        prompt = body_of(editor)["prompt"]
        clip = next(node for node in nodes_of_class(prompt, "CLIPTextEncode").values()
                    if node["inputs"].get("text") == editor.positive.value)
        self.assertTrue(clip, "the positive box is one of the text encodes")


class ThePromptCatalog(Case):
    def setUp(self) -> None:
        super().setUp()
        self.catalog = self.win.open_page("Prompt Catalog")

    def carry(self, name: str = "Sunrise") -> None:
        self.win.form.width, self.win.form.height = "832", "1216"
        self.editor().rebuild_from_config()
        self.catalog.name.value = name
        self.catalog.description.value = "a test entry"
        self.catalog.add()

    def test_catalog_copies_the_editor_prompt_and_loads_it_back(self) -> None:
        self.carry()
        self.assertEqual(self.catalog.catalog_status.value, "Copied 'Sunrise' from the Prompt Editor")
        self.assertTrue(self.catalog.entries, "the entry must be listed")
        table_text = " ".join(shown_texts(self.catalog.table_holder))
        for needle in ("Sunrise", "a test entry", "832×1216"):
            self.assertIn(needle, table_text)
        self.assertFalse(self.catalog.empty.visible)

        editor = self.editor()
        self.win.form.width, self.win.form.height = "512", "512"
        editor.rebuild_from_config()
        self.assertNotIn("832", editor.positive.value)
        self.catalog.load()
        self.assertEqual(self.win.shell.current, "Prompt Editor")
        latent = next(iter(nodes_of_class(body_of(editor)["prompt"], "EmptyFlux2LatentImage").values()))
        self.assertEqual(latent["inputs"]["width"], 832, "the kept request came back")
        self.assertIn("Loaded 'Sunrise'", self.win.shell.status.value)
        self.assertIn("Loaded 'Sunrise'", self.catalog.catalog_status.value)

    def test_catalog_needs_a_name_and_nothing_is_stored(self) -> None:
        self.catalog.add()
        self.assertEqual([dialog_body(box) for box in self.page.overlay],
                         ["Give the prompt a short name first."])
        self.assertEqual(self.catalog.entries, [])

    def test_catalog_needs_valid_editor_json(self) -> None:
        self.editor().json.value = "{broken"
        self.catalog.name.value = "Broken"
        self.catalog.add()
        self.assertIn("Prompt Editor JSON is invalid", dialog_body(self.page.overlay[-1]))
        self.assertEqual(self.catalog.entries, [])

    def test_catalog_refuses_to_copy_with_no_editor_open(self) -> None:
        self.assertNotIn("Prompt Editor", self.win.shell.pages)
        self.catalog.name.value = "Orphan"
        self.catalog.add()
        self.assertEqual(dialog_body(self.page.overlay[-1]), "Open the Prompt Editor first.")
        self.assertEqual(self.catalog.entries, [])

    def test_catalog_refuses_a_duplicate_name(self) -> None:
        self.carry("Twin")
        before = len(self.catalog.entries)
        self.carry("twin ")
        self.assertIn("'twin' is already in the catalog", dialog_body(self.page.overlay[-1]))
        self.assertEqual(len(self.catalog.entries), before)

    def test_catalog_update_json_and_metadata(self) -> None:
        self.carry("Editable")
        self.win.form.width = "512"
        self.editor().rebuild_from_config()
        self.catalog.update_json()
        self.assertEqual(self.catalog.catalog_status.value, "Updated the JSON of 'Editable'")
        kept = self.catalog.entries[0]["request"]
        latent = next(iter(nodes_of_class(kept["prompt"], "EmptyFlux2LatentImage").values()))
        self.assertEqual(latent["inputs"]["width"], 512)
        self.catalog.description.value = "renamed"
        self.catalog.save_meta()
        self.assertEqual(self.catalog.catalog_status.value, "Saved 'Editable'")
        self.assertEqual(self.catalog.entries[0].get("description"), "renamed")

    def test_catalog_actions_need_a_selection(self) -> None:
        for action in (self.catalog.update_json, self.catalog.save_meta, self.catalog.delete):
            self.catalog.selected = None
            action()
            self.assertEqual(dialog_body(self.page.overlay[-1]), "Select a catalog entry first.")

    def test_catalog_delete_asks_first(self) -> None:
        self.carry("Doomed")
        self.catalog.delete()
        box = self.page.overlay[-1]
        self.assertEqual(dialog_body(box), "Delete catalog entry 'Doomed'? This cannot be undone.")
        self.assertEqual([b.content for b in box.actions], ["No", "Yes"])
        click(box.actions[0])
        self.assertEqual(len(self.catalog.entries), 1, "No keeps the entry")
        self.catalog.delete()
        click(self.page.overlay[-1].actions[1])
        self.assertEqual(self.catalog.entries, [])
        self.assertTrue(self.catalog.empty.visible)
        self.assertIn("Deleted 'Doomed'", self.win.shell.status.value)
        self.assertEqual(self.win.shell.status.color, self.win.shell.colors["ok"])

    def test_the_empty_catalog_says_it_is_empty(self) -> None:
        self.catalog.refresh()
        self.assertTrue(self.catalog.empty.visible)
        self.assertTrue(self.catalog.empty.value)


class OtherPages(Case):
    def test_the_prompt_pages_are_on_the_rail(self) -> None:
        self.assertIn("Prompt Assist", self.win.shell.buttons)
        self.assertIn("Prompt Settings", self.win.shell.buttons)
        self.assertNotIn("Prompt", self.win.shell.buttons, "no separate Prompt page")

    def test_clear_import_drops_stashed_workflow_json(self) -> None:
        page = self.win.open_page("Import")
        blob = '{"nodes":[{"id":1,"type":"Note"}],"links":[]}'
        page.meta.value = "Sampler: Euler, Seed: 1"
        # A paste the box is too small to show is held in memory, as the Tk page did.
        padded = "x" * 20001
        page.workflow.value = padded
        page.on_workflow_typed()
        page.knob["cfg"].value = "5"
        page.knob["seed"].value = "99"
        self.assertEqual(page.workflow_text(), padded.strip())
        self.assertIn("in memory", page.workflow.value)
        self.assertNotIn("nodes", page.workflow.value)
        page.clear()
        self.assertEqual(page.workflow_text(), "")
        self.assertEqual(page.meta.value, "")
        self.assertEqual(page.workflow.value, "")
        self.assertEqual(page.knob["cfg"].value, "")
        self.assertEqual(page.knob["seed"].value, "")

    def test_import_issues_panel_flags_distilled_klein(self) -> None:
        from tests.test_comfy_import import DISTILLED, DISTILLED_META

        page = self.win.open_page("Import")
        page.meta.value = DISTILLED_META
        page.stash = json.dumps(DISTILLED)
        page.fill_knobs(quiet=True)
        shown = page.issues.value
        self.assertIn("Warnings:", shown)
        self.assertIn("ReferenceLatent", shown)
        self.assertIn("ConditioningZeroOut", shown)
        self.assertNotIn("full_encoder_small_decoder", shown)

    def test_import_fill_with_nothing_pasted_refuses_in_both_places(self) -> None:
        from salad_studio.pages.import_page import EMPTY_REFUSAL

        self.win.open_page("Import").fill_knobs()
        self.assertEqual(dialog_body(self.page.overlay[-1]), EMPTY_REFUSAL)
        self.assertEqual(self.win.shell.status.value, f"Refused: {EMPTY_REFUSAL}")

    def test_import_refuses_to_convert_an_empty_paste(self) -> None:
        from salad_studio.pages.import_page import NOTHING_TO_CONVERT

        self.win.open_page("Import").convert()
        self.assertEqual(dialog_body(self.page.overlay[-1]), NOTHING_TO_CONVERT)
        self.assertEqual(self.win.shell.status.value, f"Refused: {NOTHING_TO_CONVERT}")

    def test_no_shipped_string_sends_the_user_to_a_removed_tab(self) -> None:
        pkg = HERE.parent / "salad_studio"
        for path in [pkg / "README.md", *sorted(pkg.glob("*.py")), *sorted((pkg / "pages").glob("*.py"))]:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for needle in ("Vast.ai tab", "Images tab"):
                with self.subTest(path=path.name, needle=needle):
                    self.assertNotIn(needle, text, f"{path.name} still points the user at {needle}")

    def test_the_primary_action_on_each_page_is_the_filled_button(self) -> None:
        assist = self.win.open_page("Prompt Assist")
        import_page = self.win.open_page("Import")
        editor = self.editor()
        self.assertIsInstance(assist.help_btn, ft.Button)
        self.assertIsInstance(assist.commit_btn, ft.Button)
        self.assertNotIsInstance(assist.local_btn, ft.Button)
        self.assertIsInstance(import_page.body.content.controls[-1].controls[1], ft.Button)
        labels = [getattr(c, "content", None) for c in assist.body.content.controls[5].controls]
        self.assertEqual(labels, ["Help (DeepSeek)", "Help (local)", "Commit to Prompts + JSON"])
        self.assertTrue(editor.bar.controls, "the editor has its own action bar")


if __name__ == "__main__":
    unittest.main()
