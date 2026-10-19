"""The list pages: Prompt History, the Queue and the bottom history strip say when they are empty.

Ported from the Tk layout suite. Each page is built in the real window on a
stub page over temp stores; rows are added and removed through the stores the
pages read, and the assertions are what the pages show.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
for _p in (HERE / ".." / "salad_studio", HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio import prompt_history, request_json  # noqa: E402
from salad_studio.flet_shell import HistoryStrip  # noqa: E402
from tests._flet_window import (  # noqa: E402
    TempStores, buttons, click, dialog_body, hidden_window, mount_opened, shown_texts,
)


def run_inline(work, done) -> None:
    try:
        result = work()
    except Exception as exc:  # noqa: BLE001 - a page shows a worker's failure
        result = exc
    done(result)


from tests._flet_window import setUpModule, tearDownModule  # noqa: F401,E402

class Case(unittest.TestCase):
    def setUp(self) -> None:
        stores = TempStores()
        stores.__enter__()
        self.addCleanup(stores.__exit__, None, None, None)
        def inline_background(_services, work, done):
            run_inline(work, done)

        inline = mock.patch("salad_studio.flet_services.AppServices.background", inline_background)
        inline.start()
        self.addCleanup(inline.stop)
        self.win, self.page = hidden_window()
        mount_opened(self.win)
        self.addCleanup(self.win.services.stop)

    def history(self):
        return self.win.open_page("Prompt History")

    def queue(self):
        return self.win.open_page("Queue")

    def add_request(self, text: str = "a plate") -> dict:
        body = request_json.build_request(prompt_text=text, graph="klein", width=64, height=64,
                                          steps=2, seed=1, selected_ids=[])
        entry = prompt_history.add_request(body, profile="klein", gateway="https://example.test")
        self.assertIsNotNone(entry)
        return entry


class ListSurfacesSayWhenTheyAreEmpty(Case):
    def test_every_list_surface_states_that_it_is_empty(self) -> None:
        history = self.history()
        self.assertTrue(history.empty.visible)
        self.assertTrue(history.empty.value)
        queue = self.queue()
        self.assertEqual(queue.summary.value.count("0 request"), 1)
        self.assertEqual(queue.table_holder.controls, [])
        self.assertEqual(queue.summary.value.count("0 request"), 1,
                         "an empty queue shows no table to click, and its summary says so")
        self.assertTrue(queue.cancel_note.value)
        strip = HistoryStrip(self.win.shell.colors, on_open=lambda _p: None)
        strip.show([], lambda _i: None)
        self.assertTrue(strip.empty.visible)
        self.assertTrue(strip.empty.value)

    def test_rows_hide_the_state_and_emptying_brings_it_back(self) -> None:
        history = self.history()
        entry = self.add_request()
        history.refresh()
        self.assertFalse(history.empty.visible)
        self.assertIn("a plate", " ".join(shown_texts(history.table_holder)))
        prompt_history.remove_at(0)
        history.refresh()
        self.assertTrue(history.empty.visible)
        self.assertNotIn("a plate", " ".join(shown_texts(history.table_holder)))

        strip = HistoryStrip(self.win.shell.colors, on_open=lambda _p: None)
        strip.show([("one.jpg", None)], lambda _i: None)
        self.assertFalse(strip.empty.visible)
        self.assertTrue(strip.list.visible)
        self.assertEqual(len(strip.list.controls), 1)
        strip.show([], lambda _i: None)
        self.assertTrue(strip.empty.visible)
        self.assertFalse(strip.list.visible)

    def test_a_strip_click_opens_the_plate_it_names(self) -> None:
        strip = HistoryStrip(self.win.shell.colors, on_open=lambda _p: None)
        opened: list = []
        strip.show([("a.jpg", None), ("b.jpg", None)], opened.append)
        click(strip.list.controls[1])
        self.assertEqual(opened, [1])


class PromptHistory(Case):
    def test_picking_a_prompt_needs_a_row_first(self) -> None:
        click(buttons(self.history())["Reuse"])
        self.assertEqual(dialog_body(self.page.overlay[-1]), "Select a prompt to reuse.")

    def test_reuse_loads_the_request_into_the_editor(self) -> None:
        self.add_request("reused text")
        history = self.history()
        history.select_row(0)
        click(buttons(history)["Reuse"])
        self.assertEqual(self.win.shell.current, "Prompt Editor")
        editor = self.win.shell.pages["Prompt Editor"]
        self.assertIn("reused text", editor.text())
        self.assertIn("Reused request JSON from history", self.win.shell.status.value)

    def test_rating_a_render_asks_for_a_selection_first(self) -> None:
        history = self.history()
        history.rate(3)
        self.assertIn("select a render first", self.win.shell.status.value)
        self.add_request()
        history.refresh()
        history.select_row(0)
        history.rate(4)
        self.assertEqual(prompt_history.rating_of(history.rows[0]), 4)
        self.assertIn("rated 4 stars", self.win.shell.status.value)
        history.rate(0)
        self.assertIn("rating cleared", self.win.shell.status.value)

    def test_delete_asks_first_and_no_keeps_the_row(self) -> None:
        self.add_request()
        history = self.history()
        history.select_row(0)
        click(buttons(history)["Delete"])
        box = self.page.overlay[-1]
        self.assertEqual(dialog_body(box), "Delete this prompt history entry? This cannot be undone.")
        click(box.actions[0])
        self.assertEqual(len(history.rows), 1)
        click(buttons(history)["Delete"])
        click(self.page.overlay[-1].actions[1])
        self.assertEqual(history.rows, [])
        self.assertTrue(history.empty.visible)
        self.assertIn("Deleted the history entry", self.win.shell.status.value)


class TheQueue(Case):
    def test_a_queued_request_becomes_a_row(self) -> None:
        import salad_queue as q

        q_page = self.queue()
        before = len(q_page.rows())
        job = self.win.services.gen_queue.enqueue(
            {"gateway": "https://example.test", "profile": "klein"},
            lambda _job: q.Attempt(status=200, accepted=True), line="klein", checksum="abc")
        q_page.refresh()
        self.assertEqual(len(q_page.rows()), before + 1)
        row = next(cells for key, cells in q_page.rows() if key == str(job.id))
        self.assertEqual(row[1], "klein")
        self.assertIn("1 request", q_page.summary.value)

    def test_cancel_without_a_selection_says_what_to_do(self) -> None:
        click(buttons(self.queue())["Cancel selected"])
        self.assertIn("select a request first", self.win.shell.status.value)

    def test_cancel_says_why_a_sent_request_cannot_be_cancelled(self) -> None:
        import salad_queue as q

        q_page = self.queue()
        job = self.win.services.gen_queue.enqueue({"profile": "klein"}, None, line="klein")
        self.win.services.gen_queue.cancel(job) if job.state == "pending" else None
        q_page.select_row(0)
        click(buttons(q_page)["Cancel selected"])
        self.assertTrue(self.win.shell.status.value.startswith("Queue: request"))

    def test_the_page_names_the_cancel_rule(self) -> None:
        note = self.queue().cancel_note.value
        self.assertIn("Cancel drops a request that has not been submitted yet", note)


if __name__ == "__main__":
    unittest.main()


class TheHistoryStripIsFilled(Case):
    def test_a_finished_plate_reaches_the_strip(self) -> None:
        from PIL import Image

        from salad_studio import flet_services

        flet_services.OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = flet_services.OUT_DIR / "studio_strip_probe.jpg"
        Image.new("RGB", (40, 30), (200, 30, 30)).save(path)
        self.addCleanup(path.unlink, True)
        self.win.refresh_history_strip()
        strip = self.win.shell.strip
        names = [c.tooltip for c in strip.list.controls]
        self.assertIn(path.name, names, "the newest plate is on the strip")
        self.assertFalse(strip.empty.visible, "the empty line goes once a plate is there")

    def test_a_strip_click_opens_the_plate_it_names(self) -> None:
        opened: list = []
        self.win._open_plate = opened.append
        paths = [Path("a.jpg"), Path("b.jpg")]
        self.win.shell.strip.show([("a.jpg", None), ("b.jpg", None)],
                                  lambda index: self.win._open_plate(paths[index]))
        click(self.win.shell.strip.list.controls[1])
        self.assertEqual([path.name for path in opened], ["b.jpg"],
                         "the second thumb opens the second plate")
