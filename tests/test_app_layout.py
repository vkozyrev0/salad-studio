"""The Flet window as the user meets it: the rail, the status, the dialogs, Generate.

Ported from the Tk layout suite. A window here is the real one, built hidden on
a real ``ft.Page`` whose session is a stub (``tests._flet_window``): pages are
switched through the rail's own click handlers, shortcuts go through the
handler ``build`` put on ``page.on_keyboard_event``, and every claim reads a
control the user can see, a line the log carries, a store, or a recorded dialog.
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

from salad_studio import flet_app, flet_shell, profiles, request_json  # noqa: E402
from salad_studio.flet_pages import Form  # noqa: E402
from salad_studio.flet_services import AppServices  # noqa: E402
from salad_studio.flet_shell import TAB_ORDER  # noqa: E402
from tests._flet_window import (  # noqa: E402
    TempStores, buttons, click, contains, dialog_body, dialog_buttons, find_text, hidden_window,
    mount_opened, new_page, shown_texts, texts, walk,
)

SHIPPED = (
    "Config", "Prompt Settings", "Tokens", "LoRAs", "Prompt Editor", "Prompt Assist",
    "Prompt Catalog", "Import", "Prompt History", "Queue", "Logs",
)


def key(name: str, *, ctrl: bool = True, shift: bool = False) -> ft.KeyboardEvent:
    return ft.KeyboardEvent("key_down", None, name, shift, ctrl, False, False)


from tests._flet_window import setUpModule, tearDownModule  # noqa: F401,E402

class Case(unittest.TestCase):
    """A hidden window on temp stores, torn down after each test."""

    def setUp(self) -> None:
        stores = TempStores()
        stores.__enter__()
        self.addCleanup(stores.__exit__, None, None, None)
        self.win, self.page = hidden_window()
        mount_opened(self.win)
        self.addCleanup(self.win.services.stop)

    def open(self, name: str) -> object:
        return self.win.shell.open(name)

    def dialogs(self) -> list:
        return list(self.page.overlay)

    def generate_with(self, graph: dict) -> None:
        """Press Generate on ``graph``; the generator call is recorded, not sent."""
        self.win.open_page("Prompt Editor").set_payload(graph)
        with mock.patch("salad_studio.flet_services.AppServices.generate") as dispatch:
            self.win.generate()
        self.dispatch = dispatch


def graph_with_unet(unet: str) -> dict:
    return {
        "prompt": {
            "70": {"class_type": "UNETLoader",
                   "inputs": {"unet_name": unet, "weight_dtype": "default"}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["65", 0]}},
        },
        "convert_output": {"format": "jpeg"},
    }


class TheWindow(Case):
    def test_the_window_opens_on_config_with_the_shipped_rail(self) -> None:
        self.assertEqual(self.page.title, "Salad Studio")
        self.assertEqual(self.win.shell.current, "Config")
        self.assertEqual(list(self.win.shell.buttons), list(SHIPPED))
        self.assertEqual(tuple(SHIPPED), TAB_ORDER)
        self.assertEqual(self.win.shell.buttons["Config"].bgcolor,
                         self.win.shell.colors["primary_container"])
        self.assertIsNone(self.win.shell.buttons["Queue"].bgcolor)

    def test_a_rail_press_opens_that_page_and_leaves_the_others_built_once(self) -> None:
        rail = self.win.shell.buttons
        click(rail["Import"])
        self.assertEqual(self.win.shell.current, "Import")
        self.assertIs(self.win.shell.body_column.controls[-1], self.win.shell.pages["Import"])
        self.assertEqual(rail["Import"].bgcolor, self.win.shell.colors["primary_container"])
        self.assertIsNone(rail["Config"].bgcolor)
        click(rail["Queue"])
        self.assertEqual(self.win.shell.current, "Queue")
        self.assertEqual(rail["Queue"].bgcolor, self.win.shell.colors["primary_container"])

    def test_the_shortcut_handler_moves_between_pages(self) -> None:
        send = self.page.on_keyboard_event
        self.assertIsNotNone(send, "the window must wire the page's keyboard handler")
        send(key("Tab"))
        self.assertEqual(self.win.shell.current, "Prompt Settings")
        send(key("PageUp"))
        self.assertEqual(self.win.shell.current, "Config")
        send(key("7"))
        self.assertEqual(self.win.shell.current, "Prompt Catalog")
        send(key("0"))
        self.assertEqual(self.win.shell.current, "Config")
        send(key("Home", ctrl=False))
        self.assertEqual(self.win.shell.current, "Config", "a key without ctrl changes nothing")

    def test_the_action_bar_starts_idle_with_generate_and_the_replica_strip(self) -> None:
        bar = self.win.shell.action_bar
        labels = buttons(bar)
        for name in ("Generate", "Clean gallery", "Check Salad status"):
            self.assertIn(name, labels)
        self.assertEqual(self.win.gen_state.value, "Idle")
        self.assertTrue(contains(bar, self.win.gen_button))
        self.assertEqual(len(self.win.strip_dots), 3)
        self.assertEqual(len(set(dot.color for dot in self.win.strip_dots)), 3)
        self.assertEqual([count.value for count in self.win.strip_counts], ["0", "0", "0"])
        self.assertIn(texts(bar).count("●"), (3, 3))

    def test_a_note_lands_on_the_open_page_and_the_window_line(self) -> None:
        self.win.note("Saved the profile")
        config = self.win.shell.pages["Config"]
        self.assertEqual(config.note_text.value, "Saved the profile")
        self.assertEqual(self.win.shell.status.value, "Saved the profile")
        self.win.note("Refused: nothing", level="error")
        self.assertEqual(config.note_text.color, self.win.shell.colors["error"])
        self.assertEqual(self.win.shell.status.color, self.win.shell.colors["error"])

    def test_a_note_is_also_a_log_line(self) -> None:
        self.win.note("Saved the profile", level="ok")
        self.assertEqual(self.win.services.log_lines[-1][0], "ok")
        self.assertIn("Saved the profile", self.win.services.log_lines[-1][1])


class Dialogs(Case):
    def test_a_message_is_one_dialog_with_an_ok_that_closes_it(self) -> None:
        self.win.dialog("Salad Studio", "Gallery is already empty.")
        self.assertEqual(len(self.page.overlay), 1)
        box = self.page.overlay[0]
        self.assertTrue(box.open)
        self.assertEqual(dialog_body(box), "Gallery is already empty.")
        self.assertIn("Salad Studio", texts(box.title))
        self.assertEqual(list(dialog_buttons(box)), ["OK"])
        click(dialog_buttons(box)["OK"])
        self.assertFalse(box.open)
        self.assertEqual(self.page.overlay, [])
        self.assertEqual(self.win.dialogs, [])

    def test_a_confirm_asks_no_and_yes_and_no_keeps_everything(self) -> None:
        done = mock.Mock()
        self.win.ask("Salad Studio", "Delete this? This cannot be undone.", done)
        box = self.page.overlay[-1]
        self.assertEqual(dialog_body(box), "Delete this? This cannot be undone.")
        self.assertEqual(list(dialog_buttons(box)), ["No", "Yes"])
        click(dialog_buttons(box)["No"])
        done.assert_not_called()
        self.assertNotIn(box, self.page.overlay)

        self.win.ask("Salad Studio", "Delete this?", done)
        click(dialog_buttons(self.page.overlay[-1])["Yes"])
        done.assert_called_once_with()
        self.assertEqual(self.page.overlay, [])

    def test_clean_gallery_on_an_empty_gallery_says_so(self) -> None:
        with mock.patch.object(self.win.services, "plates", return_value=[]):
            click(buttons(self.win.shell.action_bar)["Clean gallery"])
        bodies = [dialog_body(box) for box in self.page.overlay]
        self.assertEqual(bodies, ["Gallery is already empty."])
        self.assertEqual(list(dialog_buttons(self.page.overlay[0])), ["OK"])

    def test_clean_gallery_asks_first_and_deletes_only_on_yes(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            plate = Path(tmp) / "plate.jpg"
            plate.write_bytes(b"jpeg")
            with mock.patch.object(self.win.services, "plates", return_value=[plate]), \
                    mock.patch("salad_studio.prompt_history.clear_thumbs", return_value=0):
                click(buttons(self.win.shell.action_bar)["Clean gallery"])
                box = self.page.overlay[-1]
                self.assertEqual(
                    dialog_body(box),
                    "Delete 1 image(s) from disk and clear the gallery? This cannot be undone.")
                click(dialog_buttons(box)["No"])
                self.assertTrue(plate.exists(), "No must keep the image")
                click(buttons(self.win.shell.action_bar)["Clean gallery"])
                click(dialog_buttons(self.page.overlay[-1])["Yes"])
            self.assertFalse(plate.exists(), "Yes deletes the plate")
            self.assertEqual(self.win.shell.status.value, "Deleted 1 gallery image(s)")


class StatusWords(Case):
    def test_every_status_word_leaves_generate_pressable(self) -> None:
        for word in ("", "Ready", "Down", "Stopped", "Starting", "Allocating"):
            with self.subTest(word=word):
                self.win.services.salad_word = word
                self.win._timer("salad")
                self.assertFalse(self.win.gen_button.disabled)
                self.assertEqual(self.win.salad_label.value, word or "…")
        self.assertFalse(hasattr(self.win, "_apply_generate_gate"))

    def test_the_strip_counts_what_the_probe_found(self) -> None:
        klein = self.win.form.gateway
        self.win.services.snaps = {
            "klein": {"word": "Ready", "group": {"status": "running"},
                      "instances": [{"state": "running", "ready": True}]},
            "klein5090": {"word": "Stopped", "group": {"status": "stopped"}},
        }
        self.win.refresh_strip()
        first = [count.value for count in self.win.strip_counts]
        self.win.services.snaps = {
            "klein": {"word": "Starting", "group": {"status": "running"},
                      "instances": [{"state": "creating", "ready": False}]},
            "klein5090": {"word": "Ready", "group": {"status": "running"},
                          "instances": [{"state": "running", "ready": True}]},
        }
        self.win.refresh_strip()
        second = [count.value for count in self.win.strip_counts]
        self.assertNotEqual(first, second, "the strip must follow the probe, not a constant")
        self.assertTrue(klein)


class Generate(Case):
    def setUp(self) -> None:
        super().setUp()
        self.klein = profiles.load_all()["klein"]
        self.win.form.gateway = self.klein.gateway
        self.win.form.name = "klein"

    def save_key(self) -> None:
        from salad_studio import tokens

        tokens.write_token("salad", "salad-test-key-1234")

    def press(self, graph: dict | None = None) -> mock.Mock:
        """Press Generate; the render is recorded, never sent."""
        if graph is not None:
            self.win.open_page("Prompt Editor").set_payload(graph)
        with mock.patch("salad_studio.flet_services.AppServices.generate") as dispatch:
            self.win.generate()
        return dispatch

    def test_generate_refuses_invalid_editor_json_with_both_surfaces(self) -> None:
        self.win.ensure_page("Prompt Editor").json.value = "{not json"
        dispatch = self.press()
        dispatch.assert_not_called()
        self.assertTrue(self.win.shell.status.value.startswith("Refused: the Prompt Editor JSON is invalid"))
        self.assertIn("Prompt Editor JSON is invalid", dialog_body(self.page.overlay[-1]))

    def test_generate_refuses_a_vast_profile_with_no_instance_and_says_so(self) -> None:
        self.win.form = Form(mode="vast", gateway="")
        dispatch = self.press(graph_with_unet(self.klein.primary_checkpoint))
        dispatch.assert_not_called()
        box = self.page.overlay[-1]
        self.assertEqual(dialog_body(box), "No vast.ai instance is selected.")
        self.assertEqual(self.win.shell.status.value, "Refused: No vast.ai instance is selected.")

    def test_a_salad_profile_holding_a_vast_url_is_refused_before_it_sends(self) -> None:
        """A Salad profile sends its key: a vast URL there would hand the key to the machine."""
        from salad_studio import vast

        endpoint = "http://198.51.100.7:40111"
        doc, refusal = vast.add_instance(vast.empty_doc(), endpoint)
        self.assertEqual(refusal, "")
        vast.save_doc(vast.set_active(doc, endpoint))
        self.win.form = Form(mode="salad", gateway=endpoint)
        self.save_key()
        # The Tk window re-read the instance list each time the page changed and
        # dropped a URL it found there; this window reads it only in its checks.
        listing = mock.patch.object(vast, "load_doc", return_value=vast.load_doc())
        listing.start()
        self.addCleanup(listing.stop)
        before = len(self.win.services.gen_queue.jobs())
        dispatch = self.press(graph_with_unet(self.klein.primary_checkpoint))
        dispatch.assert_not_called()
        self.assertEqual(len(self.win.services.gen_queue.jobs()), before, "nothing may be queued")
        self.assertIn("Refused:", self.win.shell.status.value)
        self.assertIn("vast.ai", dialog_body(self.page.overlay[-1]))

    def test_generate_refuses_with_both_surfaces_when_the_form_is_bad(self) -> None:
        self.win.form.width = "wide"
        dispatch = self.press(graph_with_unet(self.klein.primary_checkpoint))
        dispatch.assert_not_called()
        reason = "Width must be a whole number (got 'wide')"
        self.assertEqual(self.win.shell.status.value, f"Refused: {reason}")
        self.assertEqual(dialog_body(self.page.overlay[-1]), reason)

    def test_generate_refuses_without_a_salad_key(self) -> None:
        key = mock.patch.object(self.win.services, "salad_key", return_value="")
        key.start()
        self.addCleanup(key.stop)
        dispatch = self.press(graph_with_unet(self.klein.primary_checkpoint))
        dispatch.assert_not_called()
        self.assertEqual(dialog_body(self.page.overlay[-1]), "no Salad API key is saved")
        self.assertEqual(self.win.shell.status.value, "Refused: no Salad API key is saved")

    def test_generate_refuses_an_empty_gateway_for_a_graph_no_profile_serves(self) -> None:
        self.win.form.gateway = ""
        dispatch = self.press(graph_with_unet("flux1-dev.safetensors"))
        dispatch.assert_not_called()
        reason = dialog_body(self.page.overlay[-1])
        self.assertEqual(self.win.shell.status.value, f"Refused: {reason}")
        self.assertTrue(reason, "the dialog names the reason the press stopped")

    def test_a_press_the_window_cannot_dispatch_queues_nothing(self) -> None:
        queued = len(self.win.services.gen_queue.jobs())
        before = self.win.gen_state.value
        with mock.patch.object(self.win.services, "salad_key", return_value=""):
            self.press(graph_with_unet(self.klein.primary_checkpoint))
        self.assertEqual(len(self.win.services.gen_queue.jobs()), queued)
        self.assertEqual(self.win.gen_state.value, before, "a refusal must not say Starting")
        self.assertTrue(self.page.overlay, "the refusal must also raise a dialog")

    def test_every_known_gateway_probe_word_still_dispatches(self) -> None:
        self.save_key()
        for word in ("", "Ready", "Starting", "Allocating", "Creating", "Downloading 33%"):
            with self.subTest(word=word):
                self.win.services.salad_word = word
                dispatch = self.press(graph_with_unet(self.klein.primary_checkpoint))
                dispatch.assert_called_once()
                self.assertEqual(dispatch.call_args.args[1].gateway, self.klein.gateway)
                self.assertNotIn("Generate refused", self.win.shell.status.value)

    def test_a_press_while_a_render_is_in_flight_queues_behind_it(self) -> None:
        self.save_key()
        self.win.services.salad_word = "Starting"
        held: list = []
        hold = mock.patch.object(self.win.services, "background",
                                 side_effect=lambda work, done: held.append((work, done)))
        hold.start()
        self.addCleanup(hold.stop)
        dispatch = self.press(graph_with_unet(self.klein.primary_checkpoint))
        dispatch.assert_called_once()
        self.assertEqual(self.win.gen_state.value, "Starting…")
        self.assertEqual(self.win.shell.status.value, "Generating…")
        self.assertFalse(self.win.gen_button.disabled, "a render in flight keeps Generate live")

        other = graph_with_unet(self.klein.primary_checkpoint)
        other["prompt"]["9"]["inputs"]["filename_prefix"] = "second-plate"
        dispatch = self.press(other)
        dispatch.assert_called_once()
        self.assertEqual(self.win.gen_state.value, "Queued…")
        self.assertNotIn("Generate refused", self.win.shell.status.value)
        self.assertFalse(self.win.gen_button.disabled, "still live with two queued")

    def test_a_snofs_graph_is_routed_off_the_klein_group(self) -> None:
        self.save_key()
        klein, snofs = profiles.load_all()["klein"], profiles.load_all()["klein5090"]
        self.assertNotEqual(klein.gateway, snofs.gateway)
        dispatch = self.press(graph_with_unet(request_json.UNET_SNOFS))
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.args[1].gateway, snofs.gateway)

    def test_a_klein_graph_stays_on_the_klein_group(self) -> None:
        self.save_key()
        dispatch = self.press(graph_with_unet(self.klein.primary_checkpoint))
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.args[1].gateway, self.klein.gateway)

    def test_a_hand_typed_gateway_is_left_alone(self) -> None:
        self.save_key()
        custom = "https://custom.example.test/gateway"
        self.win.form.gateway = custom
        dispatch = self.press(graph_with_unet(request_json.UNET_SNOFS))
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.args[1].gateway, custom)


class TheStoresBackAfterEachWindow(unittest.TestCase):
    def test_the_temp_stores_restore_the_shipped_paths(self) -> None:
        from salad_studio import profiles as p

        before = p.PROFILES_PATH
        with TempStores():
            self.assertNotEqual(p.PROFILES_PATH, before)
        self.assertEqual(p.PROFILES_PATH, before)


if __name__ == "__main__":
    unittest.main()
