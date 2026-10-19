"""The Prompt Editor page's wiring, driven without a client: text in, graph and boxes out."""
from __future__ import annotations

import unittest

import flet as ft

from salad_studio import editor_logic, request_json
from salad_studio.pages.editor import EditorPage


class Host:
    def __init__(self) -> None:
        self.notes: list[tuple[str, str]] = []

    def note(self, text: str, *, level: str = "info") -> None:
        self.notes.append((text, level))


def klein_text(**overrides) -> str:
    body = request_json.build_request(prompt_text="a watercolour portrait of an adult", graph="klein",
                                      width=64, height=64, steps=4, seed=1, selected_ids=[])
    body.update(overrides)
    return editor_logic.dump(body)


class Sync(unittest.TestCase):
    def setUp(self) -> None:
        self.host = Host()
        self.page = EditorPage(self.host)

    def test_valid_json_lays_out_the_graph_and_fills_both_boxes(self) -> None:
        self.page.json.value = klein_text()
        self.page.sync()
        self.assertEqual(len(self.page.model.nodes), len(editor_logic.parse(self.page.json.value).prompt))
        self.assertEqual(self.page.positive.value, "a watercolour portrait of an adult")
        self.assertEqual(self.page.negative.value, "")
        self.assertEqual(self.page.status.value, "JSON valid")

    def test_broken_json_names_the_problem_and_leaves_the_graph_alone(self) -> None:
        self.page.json.value = klein_text()
        self.page.sync()
        before = self.page.model
        self.page.json.value = '{"prompt": {nope}}'
        self.page.sync()
        self.assertIn("line 1", self.page.status.value)
        self.assertIs(self.page.model, before)

    def test_a_second_identical_sync_keeps_the_same_model(self) -> None:
        self.page.json.value = klein_text()
        self.page.sync()
        first = self.page.model
        self.page.sync()
        self.assertIs(self.page.model, first)


class TextBoxes(unittest.TestCase):
    def setUp(self) -> None:
        self.__host = Host()
        self.page = EditorPage(self.__host)
        self.page.json.value = klein_text()
        self.page.sync()

    def test_typing_the_positive_box_patches_the_json_and_keeps_the_view(self) -> None:
        view = self.page.model.view
        self.page.positive.value = "a new positive"
        self.page.patch_prompt("pos")
        parsed = editor_logic.parse(self.page.json.value)
        self.assertEqual(editor_logic.prompt_texts(parsed.prompt)[0], "a new positive")
        self.assertEqual(self.page.model.view, view)

    def test_the_patched_payload_keeps_the_rest_of_the_request(self) -> None:
        self.page.negative.value = "blurry"
        self.page.patch_prompt("neg")
        parsed = editor_logic.parse(self.page.json.value)
        self.assertIn("convert_output", parsed.payload)
        self.assertEqual(editor_logic.prompt_texts(parsed.prompt)[1], "blurry")


class Swap(unittest.TestCase):
    def setUp(self) -> None:
        self.host = Host()
        self.page = EditorPage(self.host)
        self.page.json.value = klein_text()
        self.page.sync()

    def test_swapping_two_text_encodes_writes_the_exchange_back(self) -> None:
        prompt = editor_logic.parse(self.page.json.value).prompt
        pos, neg = editor_logic.text_encodes(prompt)
        self.page.model = self.page.model.with_selection((pos, neg))
        self.page.on_swap(self.page.model)
        after = editor_logic.parse(self.page.json.value)
        self.assertEqual(editor_logic.prompt_texts(after.prompt)[0], "")
        self.assertEqual(editor_logic.prompt_texts(after.prompt)[1], "a watercolour portrait of an adult")
        self.assertEqual(self.host.notes[-1][1], "ok")
        self.assertEqual(self.page.model.selected, ())

    def test_swapping_with_one_card_selected_says_so_and_changes_nothing(self) -> None:
        text = self.page.json.value
        self.page.model = self.page.model.with_selection((self.page.model.nodes[0].id,))
        self.page.on_swap(self.page.model)
        self.assertEqual(self.page.json.value, text)
        self.assertIn("two nodes", self.host.notes[-1][0])

    def test_swapping_two_different_types_is_refused(self) -> None:
        text = self.page.json.value
        ids = [n.id for n in self.page.model.nodes]
        self.page.model = self.page.model.with_selection((ids[0], ids[1]))
        self.page.on_swap(self.page.model)
        self.assertEqual(self.page.json.value, text)
        self.assertEqual(self.host.notes[-1][1], "warn")


class Rebuild(unittest.TestCase):
    def test_rebuild_from_json_replaces_the_layout(self) -> None:
        page = EditorPage(Host())
        page.json.value = klein_text()
        page.sync()
        nodes = list(page.model.nodes)
        moved = gm_nodes_with_one_removed(page.model)
        page.model = moved
        page.rebuild_from_json()
        self.assertEqual({n.id for n in page.model.nodes}, {n.id for n in nodes})


def gm_nodes_with_one_removed(model):
    from dataclasses import replace

    return replace(model, nodes=model.nodes[1:])


if __name__ == "__main__":
    unittest.main()
