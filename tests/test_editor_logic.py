"""Editor rules the Flet page calls: parsing, text roles, text patching, Swap, Validate."""
from __future__ import annotations

import unittest

import salad_studio.editor_logic as el
import salad_studio.request_json as request_json


def klein_body() -> dict:
    return request_json.build_request(prompt_text="a watercolour portrait of an adult",
                                      graph="klein", width=64, height=64, steps=4, seed=1,
                                      selected_ids=[])


class Parsing(unittest.TestCase):
    def test_a_built_request_round_trips(self) -> None:
        body = klein_body()
        parsed = el.parse(el.dump(body))
        self.assertTrue(parsed.ok)
        self.assertEqual(len(parsed.prompt), len(body["prompt"]))

    def test_broken_text_names_the_line(self) -> None:
        parsed = el.parse('{"prompt": {oops}}')
        self.assertFalse(parsed.ok)
        self.assertIn("line 1", parsed.error)

    def test_missing_prompt_is_refused_with_a_reason(self) -> None:
        parsed = el.parse('{"x": 1}')
        self.assertFalse(parsed.ok)
        self.assertIn("no prompt", parsed.error)


class TextRoles(unittest.TestCase):
    def setUp(self) -> None:
        self.prompt = klein_body()["prompt"]

    def test_positive_and_negative_are_found_by_role(self) -> None:
        pos, neg = el.text_encodes(self.prompt)
        self.assertTrue(pos and neg)
        self.assertNotEqual(pos, neg)
        texts = el.prompt_texts(self.prompt)
        self.assertEqual(texts[0], "a watercolour portrait of an adult")

    def test_patching_one_side_leaves_the_other(self) -> None:
        patch = el.patch_text(self.prompt, "pos", "changed")
        self.assertEqual(el.prompt_texts(patch)[0], "changed")
        self.assertEqual(el.prompt_texts(patch)[1], el.prompt_texts(self.prompt)[1])
        self.assertEqual(el.prompt_texts(self.prompt)[0], "a watercolour portrait of an adult")

    def test_swap_exchanges_the_two_texts(self) -> None:
        before = el.prompt_texts(self.prompt)
        pos, neg = el.text_encodes(self.prompt)
        after = el.prompt_texts(el.swap_text(self.prompt, pos, neg))
        self.assertEqual(after[0], before[1])
        self.assertEqual(after[1], before[0])

    def test_swap_of_different_types_is_refused_by_the_algorithm(self) -> None:
        ids = list(self.prompt)
        a = el.text_encodes(self.prompt)[0]
        other = next(n for n in ids if self.prompt[n]["class_type"] != "CLIPTextEncode")
        with self.assertRaises(ValueError):
            el.swap_text(self.prompt, a, other)


class Validation(unittest.TestCase):
    def test_a_built_request_passes(self) -> None:
        ok, message = el.validate(el.dump(klein_body()))
        self.assertTrue(ok, message)
        self.assertEqual(message, "JSON valid")

    def test_a_payload_without_a_prompt_is_refused(self) -> None:
        ok, message = el.validate('{"x": 1}')
        self.assertFalse(ok)
        self.assertIn("prompt", message)


if __name__ == "__main__":
    unittest.main()
