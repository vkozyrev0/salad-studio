"""Behaviour tests for the live Salad Studio window: tabs, LoRA tab, JSON reflection."""
from __future__ import annotations

import http.server
import inspect
import json
import os
import socket
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PKG = TOOLS / "salad_studio"
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(TOOLS))

import request_json as rj  # noqa: E402
from lora_store import DEFAULT_KLEIN_LORA_IDS  # noqa: E402
from tests.test_launch import _TempPaths  # noqa: E402

# Every app construction in this module builds a queue that writes its container
# ledger. Redirect it here, once, for both copies of salad_queue (the app imports
# it top-level, these tests import it as salad_studio.salad_queue): no test in
# this module may touch the real ~/.config/salad/studio-queue.json.
_LEDGER_DIR = tempfile.TemporaryDirectory()
import salad_queue as _top_queue  # noqa: E402
from salad_studio import image_deploy as _image_deploy  # noqa: E402
from salad_studio import salad_queue as _pkg_queue  # noqa: E402
from salad_studio import vast as _vast  # noqa: E402

# Same reason for the Vast.ai page: its engine choice decides where a Generate
# press goes, so a window built here must not read the user's own file. The
# Images page's store is read at construction for the same reason. Both are put
# back by tearDownModule, so no later module inherits this redirect.
_STORES = (
    (_top_queue, "LEDGER_PATH"),
    (_pkg_queue, "LEDGER_PATH"),
    (_vast, "INSTANCES_PATH"),
    (_image_deploy, "SETTINGS_PATH"),
)
_STORES_SAVED: list[tuple[object, str, Path]] = []


def setUpModule() -> None:
    """Redirect the stores a window built in this module reads and writes."""
    for module, name in _STORES:
        _STORES_SAVED.append((module, name, getattr(module, name)))
    ledger = Path(_LEDGER_DIR.name) / "studio-queue.json"
    _top_queue.LEDGER_PATH = ledger
    _pkg_queue.LEDGER_PATH = ledger
    _vast.INSTANCES_PATH = Path(_LEDGER_DIR.name) / "studio-vast.json"
    _image_deploy.SETTINGS_PATH = Path(_LEDGER_DIR.name) / "studio-images.json"


def tearDownModule() -> None:
    """Put the shipped stores back: a later module must see them, not this redirect."""
    for module, name, saved in reversed(_STORES_SAVED):
        setattr(module, name, saved)
    _STORES_SAVED.clear()


class AppTabs(unittest.TestCase):
    def test_config_lora_selection_is_in_editor_json(self) -> None:
        """Same function the Prompt Editor tab calls via _sync_editor."""
        body = rj.build_request(
            prompt_text="studio prompt",
            graph="klein",
            width=1024,
            height=1024,
            steps=20,
            seed=1,
            selected_ids=list(DEFAULT_KLEIN_LORA_IDS),
        )
        dumped = json.dumps(body, indent=2)
        self.assertIn("LoraLoader", dumped)
        self.assertIn("https://civitai.com/api/download/models/2625692", dumped)
        self.assertIn("https://civitai.com/api/download/models/2763568", dumped)
        empty = rj.build_request(
            prompt_text="studio prompt",
            graph="klein",
            width=1024,
            height=1024,
            steps=20,
            seed=1,
            selected_ids=[],
        )
        empty_dump = json.dumps(empty)
        self.assertNotIn("LoraLoader", empty_dump)

    def test_config_labels_and_families_match_the_catalog(self) -> None:
        """The LoRA tab's label helpers, driven with real catalog rows."""
        from lora_store import config_label, family_label, find_lora

        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "studio-loras.json"
            klein = find_lora("civitai:2334190@2625692", extras)
            ultra = find_lora("civitai:796382@1026423", extras)
        self.assertTrue(klein is not None and ultra is not None)
        self.assertIn("Flux.2 Klein", config_label(klein))
        self.assertIn("Flux.1 Dev", config_label(ultra))
        self.assertEqual(family_label(klein), "Flux.2 Klein")


try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError as _tk_err:
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = _tk_err
else:
    _TK_IMPORT_ERROR = None


def _old_form(func, edits: list[tuple[str, str]]):
    """The shipped function with a pass's edits undone: the old handler, rebuilt.

    ``edits`` are (shipped text, the text it replaced) pairs, applied to the
    source ``inspect.getsource`` returns. The old behaviour is therefore rebuilt
    from the shipped file rather than copied into a literal that could drift
    away from it, and a test can drive it to show what the fix changed.
    """
    source = textwrap.dedent(inspect.getsource(func))
    for new, old in edits:
        assert new in source, f"{func.__name__} no longer holds {new!r}"
        source = source.replace(new, old, 1)
    namespace: dict = {}
    exec(compile(source, f"<old {func.__name__}>", "exec"), func.__globals__, namespace)
    return namespace[func.__name__]


def _redirect_store(module, name: str, value) -> tuple:
    """Point a module-level store at ``value``; return the undo for ``addCleanup``.

    Every window class here redirects the stores the app reads and writes, and
    Tk windows are built in many of them. Without the undo the redirect outlives
    the class, and a later ``_TempPaths`` then saves the redirect as though it
    were the shipped path, so the leak outlives the whole run.
    """
    saved = (module, name, getattr(module, name))
    setattr(module, name, value)
    return saved


def _put_stores_back(saved: list) -> None:
    """Undo what ``_redirect_store`` did, newest first."""
    for module, name, value in reversed(saved):
        setattr(module, name, value)


def _layout_window(app, size: str) -> None:
    """Lay ``app`` out at ``size`` and keep it there while the test measures.

    A window holds the size it opened with and re-applies it on a few startup
    timers (``SaladStudio._hold_opened_size``), shrinking a window that grew by
    more than 48 px; one of those landing mid-measurement would resize the
    window under the test. Telling the window that this is the size it opened at
    makes those re-applies no-ops.
    """
    want_w, want_h = (int(part) for part in size.split("x"))
    app.geometry(size)
    app.deiconify()
    deadline = time.time() + 10.0
    while time.time() < deadline:
        app.update()
        if app.winfo_width() > 100 and app.winfo_height() > 100:
            break
        time.sleep(0.02)
    app._opened_width, app._opened_height = want_w, want_h
    app.geometry(size)
    for _ in range(5):
        app.update()
        time.sleep(0.02)
    app.update_idletasks()
    assert (int(app.winfo_width()), int(app.winfo_height())) == (want_w, want_h), (
        f"the window must be laid out at {size} for this measurement, not "
        f"{app.winfo_width()}x{app.winfo_height()}"
    )


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class ConfigCheckboxCompat(unittest.TestCase):
    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        tmp = Path(self._td.name)
        from salad_studio.app import SaladStudio
        from salad_studio import lora_store, profiles

        saved = [
            _redirect_store(profiles, "PROFILES_PATH", tmp / "studio-profiles.json"),
            _redirect_store(lora_store, "EXTRAS_PATH", tmp / "studio-loras.json"),
        ]
        self.addCleanup(_put_stores_back, saved)
        self.app = SaladStudio(show=False)
        self.app.withdraw()
        self.app.update_idletasks()
        self.addCleanup(self.app.destroy)

    def test_mismatched_checkboxes_disabled_for_graph(self) -> None:
        from salad_studio import lora_store

        app = self.app
        klein_id = "civitai:2334190@2625692"
        ultra_id = "civitai:796382@1026423"
        cols = tuple(app.lora_tree.cget("columns"))
        self.assertIn("model", cols)
        self.assertIn("verified", cols)
        self.assertIn("version", cols)
        self.assertEqual(app.lora_tree.heading("model", "text"), "Model")
        self.assertEqual(app.lora_tree.heading("verified", "text"), "Verified")
        app.var_graph.set(lora_store.graph_label("klein"))
        app.update_idletasks()
        self.assertEqual(
            str(app._lora_checks[ultra_id].cget("state")), "disabled"
        )
        self.assertIn("Flux.1 Dev", str(app._lora_checks[ultra_id].cget("text")))
        klein_state = str(app._lora_checks[klein_id].cget("state"))
        self.assertIn(klein_state, ("normal", "active"))
        self.assertIn("Flux.2 Klein", str(app._lora_checks[klein_id].cget("text")))
        app.var_graph.set(lora_store.graph_label("flux1"))
        app.update_idletasks()
        self.assertEqual(
            str(app._lora_checks[klein_id].cget("state")), "disabled"
        )
        ultra_state = str(app._lora_checks[ultra_id].cget("state"))
        self.assertIn(ultra_state, ("normal", "active"))

    def test_graph_combo_uses_family_labels_and_loras_do_not_vscroll(self) -> None:
        from salad_studio.app import LORA_CHECK_COLUMNS
        from salad_studio import lora_store, theme

        app = self.app
        klein_id = "civitai:2334190@2625692"
        ultra_id = "civitai:796382@1026423"
        shown = tuple(app.graph_combo.cget("values"))
        self.assertIn("Flux.1 Dev", shown)
        self.assertIn("Flux.2 Klein", shown)
        self.assertEqual(shown, lora_store.GRAPH_CHOICES)
        self.assertEqual(app.var_graph.get(), "Flux.2 Klein")
        for cb in app._lora_checks.values():
            text = str(cb.cget("text"))
            self.assertRegex(
                text,
                r"\[(Flux\.1|Flux\.2|Pony|SDXL|Krea|Illustrious|unknown)",
                text,
            )
        app.var_graph.set("Flux.2 Klein")
        app.update_idletasks()
        self.assertEqual(
            str(app._lora_checks[ultra_id].cget("state")), "disabled"
        )
        self.assertIn(
            str(app._lora_checks[klein_id].cget("state")),
            ("normal", "active"),
        )
        app.var_graph.set("Flux.1 Dev")
        app.update_idletasks()
        self.assertEqual(
            str(app._lora_checks[klein_id].cget("state")), "disabled"
        )
        self.assertIn(
            str(app._lora_checks[ultra_id].cget("state")),
            ("normal", "active"),
        )
        self.assertFalse(hasattr(app, "_lora_canvas"))
        self.assertFalse(hasattr(app, "_lora_vscroll"))
        for child in app._config.winfo_children():
            if isinstance(child, ttk.Scrollbar):
                self.assertNotEqual(str(child.cget("orient")), "vertical")
        cols = {
            int(cb.grid_info()["column"])
            for cb in app._lora_checks.values()
        }
        self.assertGreaterEqual(len(cols), 2)
        self.assertLessEqual(max(cols), LORA_CHECK_COLUMNS - 1)
        style = ttk.Style(app)
        expand = style.map("TNotebook.Tab", "expand")
        joined = str(expand)
        self.assertIn("selected", joined)
        sel = theme.NOTEBOOK_TAB_EXPAND_SELECTED
        unsel = theme.NOTEBOOK_TAB_EXPAND_UNSELECTED
        self.assertEqual(sel[3], 0)
        self.assertGreater(unsel[3], 0)


def _editor_body(app) -> dict:
    raw = app.editor_text.get("1.0", "end").strip()
    return json.loads(raw)


def _prompt_text(app) -> str:
    return app.prompt_text.get("1.0", "end").strip()


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class LiveFieldSync(unittest.TestCase):
    """Drive the live window: LoRA toggle, library select, Config writes, profile switch."""

    KLEIN_DETAIL = "civitai:2334190@2625692"
    KLEIN_IMPRESSIONISM = "civitai:545264@2763568"
    FLUX1_ULTRA = "civitai:796382@1026423"

    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        tmp = Path(self._td.name)
        from salad_studio.app import SaladStudio
        from salad_studio import lora_store, profiles, prompt_catalog, prompt_history, tokens

        self.profiles = profiles
        self.lora_store = lora_store
        self.tokens = tokens
        self.prompt_catalog = prompt_catalog
        self.prompt_history = prompt_history
        saved = [
            _redirect_store(profiles, "PROFILES_PATH", tmp / "studio-profiles.json"),
            _redirect_store(lora_store, "EXTRAS_PATH", tmp / "studio-loras.json"),
            # The app's own log() reads the token store; keep it off the real files.
            _redirect_store(tokens, "LOCAL_PATH", tmp / "studio-tokens.json"),
            _redirect_store(tokens, "CONFIG_HOME", tmp / "defaults"),
            _redirect_store(prompt_catalog, "CATALOG_PATH", tmp / "studio-prompt-catalog.json"),
            _redirect_store(prompt_history, "HISTORY_PATH", tmp / "studio-prompt-history.json"),
            _redirect_store(prompt_history, "THUMBS_DIR", tmp / "studio-prompt-thumbs"),
        ]
        from salad_studio import ui_state

        saved.append(_redirect_store(ui_state, "STATE_PATH", tmp / "studio-ui.json"))
        self.addCleanup(_put_stores_back, saved)
        self.app = SaladStudio(show=False)
        self.app.withdraw()
        self.app.update_idletasks()
        self.addCleanup(self.app.destroy)

    def _expected(self, *, graph: str, width: int, height: int, steps: int, selected_ids: list[str]) -> dict:
        return rj.build_request(
            prompt_text=_prompt_text(self.app),
            graph=graph,
            width=width,
            height=height,
            steps=steps,
            seed=int(float(self.app.var_seed.get() or 1)),
            cfg=float(self.app.var_cfg.get() or 5),
            unet=rj.normalize_unet(self.app.var_unet.get()),
            selected_ids=selected_ids,
        )

    def test_lora_checkbox_rewrites_prompt_editor(self) -> None:
        app = self.app
        before = _editor_body(app)
        self.assertEqual(
            before,
            self._expected(
                graph="klein",
                width=int(app.var_width.get()),
                height=int(app.var_height.get()),
                steps=int(app.var_steps.get()),
                selected_ids=list(DEFAULT_KLEIN_LORA_IDS),
            ),
        )
        cb = app._lora_checks[self.KLEIN_IMPRESSIONISM]
        self.assertIn(str(cb.cget("state")), ("normal", "active"))
        cb.invoke()
        app.update_idletasks()
        app.update()
        app._on_lora_toggle()
        want = [self.KLEIN_DETAIL]
        self.assertEqual(
            _editor_body(app),
            self._expected(
                graph="klein",
                width=int(app.var_width.get()),
                height=int(app.var_height.get()),
                steps=int(app.var_steps.get()),
                selected_ids=want,
            ),
        )
        dumped = app.editor_text.get("1.0", "end")
        self.assertIn("https://civitai.com/api/download/models/2625692", dumped)
        self.assertNotIn("2763568", dumped)

    def test_loras_tab_selection_fills_edit_fields(self) -> None:
        app = self.app
        rows = list(app.lora_tree.get_children())
        self.assertGreaterEqual(len(rows), 2)
        first, second = rows[0], rows[1]
        self.assertNotEqual(first, second)
        app.lora_tree.selection_set(first)
        app.lora_tree.event_generate("<<TreeviewSelect>>")
        app.update_idletasks()
        item0 = self.lora_store.find_lora(first)
        self.assertIsNot(item0, None)
        self.assertEqual(app.var_lora_name.get(), str(item0.get("name") or ""))
        self.assertEqual(app.var_lora_family.get(), self.lora_store.family_label(item0))
        sm0, sc0 = self.lora_store.strengths_for(item0)
        self.assertEqual(app.var_lora_sm.get(), str(sm0))
        self.assertEqual(app.var_lora_sc.get(), str(sc0))
        src0 = item0.get("source") or {}
        self.assertEqual(
            app.var_lora_file.get(),
            str(src0.get("filename") or "") or self.lora_store.comfy_lora_name(item0),
        )

        app.lora_tree.selection_set(second)
        app.lora_tree.event_generate("<<TreeviewSelect>>")
        app.update_idletasks()
        item1 = self.lora_store.find_lora(second)
        self.assertIsNot(item1, None)
        self.assertEqual(app.var_lora_name.get(), str(item1.get("name") or ""))
        self.assertEqual(app.var_lora_family.get(), self.lora_store.family_label(item1))
        sm1, sc1 = self.lora_store.strengths_for(item1)
        self.assertEqual(app.var_lora_sm.get(), str(sm1))
        self.assertEqual(app.var_lora_sc.get(), str(sc1))
        src1 = item1.get("source") or {}
        self.assertEqual(
            app.var_lora_file.get(),
            str(src1.get("filename") or "") or self.lora_store.comfy_lora_name(item1),
        )

    @staticmethod
    def _button_texts(widget) -> set[str]:
        """Every Button label in the widget tree under ``widget``."""
        out: set[str] = set()
        for child in widget.winfo_children():
            if isinstance(child, (tk.Button, ttk.Button)):
                out.add(str(child.cget("text")))
            out |= LiveFieldSync._button_texts(child)
        return out

    # --- the LoRA grid: the verified dot, the sort, the find box ---------
    @staticmethod
    def _lora_cell(app, lid: str, column: str) -> str:
        """One cell of one grid row, read back off the tree."""
        cols = tuple(app.lora_tree.cget("columns"))
        return str(app.lora_tree.item(lid, "values")[cols.index(column)])

    def _add_lora(self, ref: str, name: str, *, verified: bool) -> str:
        """One library row with a state of its own, added through the shipped store.

        The filename is distinct because the store keeps one row per Civitai
        version, filename or visible name.
        """
        from salad_studio import lora_store

        item = lora_store.add_lora(
            ref,
            name=name,
            filename=f"{name.lower().replace(' ', '-')}.safetensors",
            verify=False,
            verified=verified,
        )
        self.app._refresh_lora_lists()
        return str(item.get("id") or ref)

    def test_the_verified_dot_comes_first_and_the_widget_carries_its_state(self) -> None:
        """Verified leads the grid, its cell is a dot, and the row's tag is its colour."""
        from salad_studio import theme

        app = self.app
        cols = tuple(app.lora_tree.cget("columns"))
        self.assertEqual(cols[0], "verified", "the verified column must come first")
        self.assertEqual(app.lora_tree.heading("verified", "text"), "Verified")
        good = self._add_lora("civitai:9001@11", "Zeta verified", verified=True)
        bad = self._add_lora("civitai:9002@12", "Alpha unverified", verified=False)

        self.assertEqual(self._lora_cell(app, good, "verified"), "●")
        self.assertEqual(self._lora_cell(app, bad, "verified"), "●")
        self.assertEqual(
            tuple(app.lora_tree.item(good, "tags")), ("verified",), "the row's own tag"
        )
        self.assertEqual(tuple(app.lora_tree.item(bad, "tags")), ("unverified",))
        green = str(app.lora_tree.tag_configure("verified", "foreground"))
        red = str(app.lora_tree.tag_configure("unverified", "foreground"))
        self.assertEqual(green, theme.PALETTE["valid"])
        self.assertEqual(red, theme.PALETTE["invalid"])
        self.assertNotEqual(green, red, "the two states must not look alike")
        for lid in app.lora_tree.get_children():
            for cell in app.lora_tree.item(lid, "values"):
                self.assertNotIn(str(cell).lower(), ("yes", "no"), "the dot replaced yes/no")

    def test_a_heading_click_sorts_the_grid_and_again_reverses_it(self) -> None:
        """A heading orders the rows by its column; the same heading reverses it."""
        app = self.app
        self._add_lora("civitai:9101@11", "Aaa first", verified=True)
        self._add_lora("civitai:9102@12", "Zzz last", verified=False)

        app._sort_lora_tree("name")
        names = [self._lora_cell(app, lid, "name") for lid in app.lora_tree.get_children()]
        self.assertEqual(names, sorted(names, key=str.lower), "ascending by name")
        app._sort_lora_tree("name")
        names = [self._lora_cell(app, lid, "name") for lid in app.lora_tree.get_children()]
        self.assertEqual(
            names, sorted(names, key=str.lower, reverse=True), "the second click reverses"
        )

        app._sort_lora_tree("verified")
        tags = [
            app.lora_tree.item(lid, "tags")[0] for lid in app.lora_tree.get_children()
        ]
        self.assertEqual(
            tags,
            sorted(tags, key=lambda tag: 0 if tag == "unverified" else 1),
            "ascending puts the unverified rows first",
        )
        app._sort_lora_tree("verified")
        tags = [
            app.lora_tree.item(lid, "tags")[0] for lid in app.lora_tree.get_children()
        ]
        self.assertEqual(tags[0], "verified", "reversing puts the verified rows first")

    def test_the_find_box_narrows_the_grid_by_name(self) -> None:
        """Part of a name, any case, any position; clearing brings every row back."""
        app = self.app
        self._add_lora("civitai:9201@11", "Marmalade Klein", verified=True)
        self._add_lora("civitai:9202@12", "Stone Lantern", verified=False)
        every = list(app.lora_tree.get_children())

        app.var_lora_find.set("MARMAL")
        shown = list(app.lora_tree.get_children())
        self.assertTrue(shown, "the fragment must match")
        self.assertLess(len(shown), len(every), "and it must narrow the grid")
        for lid in shown:
            self.assertIn("marmal", self._lora_cell(app, lid, "name").lower())

        app.var_lora_find.set("alade")  # a fragment from the middle of the name
        self.assertEqual(len(list(app.lora_tree.get_children())), 1)

        app.var_lora_find.set("")
        self.assertEqual(
            list(app.lora_tree.get_children()), every, "clearing brings every row back"
        )

    def test_the_find_box_and_a_heading_sort_compose(self) -> None:
        """A narrowed grid still sorts, and a sorted grid still narrows."""
        app = self.app
        self._add_lora("civitai:9301@11", "Qz Compose Beta", verified=True)
        self._add_lora("civitai:9302@12", "Qz Compose Alpha", verified=False)
        self._add_lora("civitai:9303@13", "Qz Other Row", verified=False)
        app._sort_lora_tree("name")
        app.var_lora_find.set("compose")
        names = [self._lora_cell(app, lid, "name") for lid in app.lora_tree.get_children()]
        self.assertEqual(
            names, ["Qz Compose Alpha", "Qz Compose Beta"], "filtered and ordered"
        )
        app._sort_lora_tree("name")
        names = [self._lora_cell(app, lid, "name") for lid in app.lora_tree.get_children()]
        self.assertEqual(
            names, ["Qz Compose Beta", "Qz Compose Alpha"], "the sort still applies"
        )

    def test_lora_tab_controls_exist_and_call_the_store(self) -> None:
        app = self.app
        labels = self._button_texts(app._loras)
        for want in ("Save edits", "Verify", "Verify unverified"):
            self.assertIn(want, labels)
        cols = tuple(app.lora_tree.cget("columns"))
        for col, heading in (
            ("id", "Id"),
            ("model", "Model"),
            ("version", "Version"),
            ("verified", "Verified"),
        ):
            self.assertIn(col, cols)
            self.assertEqual(app.lora_tree.heading(col, "text"), heading)

        rows = list(app.lora_tree.get_children())
        self.assertTrue(rows)
        lid = rows[0]
        app.lora_tree.selection_set(lid)
        self.assertEqual(app.lora_tree.selection(), (lid,))

        # Save edits -> edit_lora(selected id, form values)
        expected_name = app.var_lora_name.get().strip() or None
        expected_family = app.var_lora_family.get()
        with mock.patch.object(self.lora_store, "edit_lora") as edit:
            app._on_edit_lora()
        edit.assert_called_once()
        self.assertEqual(edit.call_args.args[0], lid)
        self.assertEqual(edit.call_args.kwargs["name"], expected_name)
        self.assertEqual(edit.call_args.kwargs["base"], expected_family)
        self.assertEqual(app.status.get(), f"Saved LoRA {lid}")

        # Verify -> verify_lora(selected id)
        with mock.patch.object(
            self.lora_store, "verify_lora", return_value={"verified": True}
        ) as verify:
            app._on_verify_lora()
        verify.assert_called_once_with(lid)
        self.assertEqual(app.status.get(), "Verified 1 LoRA(s)")

        # Verify unverified -> verify_unverified_loras()
        with mock.patch.object(
            self.lora_store, "verify_unverified_loras", return_value=(2, 0, [])
        ) as verify_all:
            app._on_verify_unverified()
        verify_all.assert_called_once_with()
        self.assertEqual(app.status.get(), "Verified 2 LoRA(s)")

    def test_add_lora_button_persists_the_row_and_lists_it(self) -> None:
        """The audit's H1 end to end: Add must survive a re-read of the store."""
        from salad_studio import app as app_mod

        app = self.app
        local = Path(self._td.name) / "added_from_the_ui.safetensors"
        local.write_bytes(b"lora")
        app.var_lora_ref.set(str(local))
        app.var_lora_name.set("Added From UI")
        app.var_lora_file.set("added_from_the_ui.safetensors")
        app.var_lora_family.set("Flux.2 Klein")
        app.var_lora_sm.set("0.75")
        app.var_lora_sc.set("0.75")

        with mock.patch.object(app_mod.messagebox, "showerror") as err:
            app._on_add_lora()
        self.assertFalse(err.called, "Add reported an error to the user")

        want_id = "local:added_from_the_ui.safetensors"
        self.assertIn(want_id, app._selected_lora_ids())
        self.assertEqual(app.status.get(), f"Added LoRA {want_id}")

        # Re-read through a FRESH call on the real store the app wrote to.
        stored = self.lora_store.find_lora(want_id, self.lora_store.EXTRAS_PATH)
        self.assertIsNot(stored, None, "Add did not persist the row to the extras store")
        self.assertEqual(str(stored["source"]["filename"]), "added_from_the_ui.safetensors")
        self.assertEqual(str(stored["name"]), "Added From UI")
        self.assertAlmostEqual(float(stored["strength_model"]), 0.75)
        self.assertIn(want_id, [r.get("id") for r in self.lora_store.list_loras()])

        # And it is listed in the live LoRA tree, so the next launch sees it.
        self.assertIn(want_id, list(app.lora_tree.get_children()))

    def test_prompt_boxes_put_positive_left_of_negative(self) -> None:
        app = self.app
        pos_frame = app.prompt_text.master
        neg_frame = app.negative_text.master
        self.assertEqual(str(pos_frame.cget("text")), "Positive prompt")
        self.assertEqual(str(neg_frame.cget("text")), "Negative prompt")
        self.assertIs(pos_frame.master, app._editor_prompts)
        self.assertIs(neg_frame.master, app._editor_prompts)
        pos_col = int(pos_frame.grid_info()["column"])
        neg_col = int(neg_frame.grid_info()["column"])
        self.assertLess(pos_col, neg_col, "the positive box must be the left one")
        pos_weight = int(app._editor_prompts.columnconfigure(pos_col)["weight"])
        neg_weight = int(app._editor_prompts.columnconfigure(neg_col)["weight"])
        self.assertGreater(
            pos_weight, neg_weight, "the positive box should get the wider column"
        )
        # The prompts frame sits under the JSON/diagram pane and above the buttons.
        self.assertEqual(int(app._editor_prompts.grid_info()["row"]), 1)
        self.assertEqual(int(app._editor_bar.grid_info()["row"]), 2)

    def _catalog_body(self, text: str) -> dict:
        return rj.build_request(
            prompt_text=text,
            graph="klein",
            width=832,
            height=1216,
            steps=20,
            seed=3,
            selected_ids=[],
        )

    def test_catalog_copies_the_editor_prompt_and_loads_it_back(self) -> None:
        from salad_studio import app as app_mod

        app = self.app
        body = self._catalog_body("catalog cover scene")
        app._set_editor_payload(body, remember=False)
        app.var_cat_name.set("Cover scene")
        app.var_cat_desc.set("overalls, landscape, wordmark")

        with mock.patch.object(app_mod.messagebox, "showerror") as err:
            with mock.patch.object(app_mod.messagebox, "showinfo") as info:
                app._on_catalog_add()
        self.assertFalse(err.called)
        self.assertFalse(info.called)

        rows = self.prompt_catalog.list_entries()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Cover scene")
        self.assertEqual(rows[0]["description"], "overalls, landscape, wordmark")
        self.assertEqual(rows[0]["request"], body)
        self.assertIn("832×1216", self.prompt_catalog.entry_stats(rows[0]))

        listed = list(app.catalog_tree.get_children())
        self.assertEqual(listed, [rows[0]["id"]])
        values = app.catalog_tree.item(listed[0], "values")
        self.assertEqual(values[1], "Cover scene")
        self.assertEqual(values[2], "overalls, landscape, wordmark")
        self.assertIn("catalog cover scene", str(values[3]))
        self.assertEqual(app.catalog_tree.heading("name", "text"), "Short name")
        self.assertEqual(app.catalog_tree.heading("description", "text"), "Description")

        # Wipe the editor, then load the entry back into it.
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", '{"prompt": {}}')
        app.catalog_tree.selection_set(listed[0])
        app._on_catalog_load()
        restored = json.loads(app.editor_text.get("1.0", "end"))
        self.assertEqual(restored, rows[0]["request"])
        self.assertEqual(app.nb.tab(app.nb.select(), "text"), "Prompt Editor")
        self.assertEqual(app.var_cat_name.get(), "Cover scene")

    def test_catalog_needs_a_name_and_valid_editor_json(self) -> None:
        from salad_studio import app as app_mod

        app = self.app
        app.var_cat_name.set("   ")
        with mock.patch.object(app_mod.messagebox, "showinfo") as info:
            app._on_catalog_add()
        self.assertTrue(info.called, "a blank name should be reported to the user")
        self.assertEqual(self.prompt_catalog.list_entries(), [])

        app.var_cat_name.set("Valid name")
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", "not json at all")
        with mock.patch.object(app_mod.messagebox, "showerror") as err:
            app._on_catalog_add()
        self.assertTrue(err.called, "invalid editor JSON should be reported")
        self.assertEqual(self.prompt_catalog.list_entries(), [])

    def test_catalog_refuses_a_duplicate_name(self) -> None:
        from salad_studio import app as app_mod

        app = self.app
        app._set_editor_payload(self._catalog_body("first"), remember=False)
        app.var_cat_name.set("Cover scene")
        with mock.patch.object(app_mod.messagebox, "showerror"):
            with mock.patch.object(app_mod.messagebox, "showinfo"):
                app._on_catalog_add()
        self.assertEqual(len(self.prompt_catalog.list_entries()), 1)

        app.var_cat_name.set("  cover scene ")
        with mock.patch.object(app_mod.messagebox, "showerror") as err:
            app._on_catalog_add()
        self.assertTrue(err.called, "a duplicate name should be refused")
        self.assertEqual(len(self.prompt_catalog.list_entries()), 1)
        self.assertEqual(len(app.catalog_tree.get_children()), 1)

    def test_catalog_update_json_and_metadata(self) -> None:
        from salad_studio import app as app_mod

        app = self.app
        app._set_editor_payload(self._catalog_body("v1"), remember=False)
        app.var_cat_name.set("Cover scene")
        app.var_cat_desc.set("first pass")
        with mock.patch.object(app_mod.messagebox, "showerror"):
            with mock.patch.object(app_mod.messagebox, "showinfo"):
                app._on_catalog_add()
        entry_id = self.prompt_catalog.list_entries()[0]["id"]

        # Update JSON <- a different editor payload.
        app._set_editor_payload(self._catalog_body("v2"), remember=False)
        app.catalog_tree.selection_set(entry_id)
        app._on_catalog_update_json()
        stored = self.prompt_catalog.get_entry(entry_id)
        self.assertIsNot(stored, None)
        self.assertEqual(
            stored["request"]["prompt"]["74"]["inputs"]["text"], "v2"
        )

        # Save name / description <- the form.
        app.var_cat_name.set("Cover scene v2")
        app.var_cat_desc.set("second pass")
        app._on_catalog_save_meta()
        stored = self.prompt_catalog.get_entry(entry_id)
        self.assertIsNot(stored, None)
        self.assertEqual(stored["name"], "Cover scene v2")
        self.assertEqual(stored["description"], "second pass")
        self.assertEqual(
            self.prompt_catalog.get_entry(entry_id)["request"]["prompt"]["74"]["inputs"]["text"],
            "v2",
        )
        values = app.catalog_tree.item(entry_id, "values")
        self.assertEqual(values[1], "Cover scene v2")
        self.assertEqual(values[2], "second pass")

    def test_catalog_delete_asks_first(self) -> None:
        from salad_studio import app as app_mod

        app = self.app
        app._set_editor_payload(self._catalog_body("keep or drop"), remember=False)
        app.var_cat_name.set("Cover scene")
        with mock.patch.object(app_mod.messagebox, "showerror"):
            with mock.patch.object(app_mod.messagebox, "showinfo"):
                app._on_catalog_add()
        entry_id = self.prompt_catalog.list_entries()[0]["id"]
        app.catalog_tree.selection_set(entry_id)

        with mock.patch.object(app_mod.messagebox, "askyesno", return_value=False) as ask:
            app._on_catalog_delete()
        self.assertTrue(ask.called)
        self.assertEqual(len(self.prompt_catalog.list_entries()), 1)

        with mock.patch.object(app_mod.messagebox, "askyesno", return_value=True):
            app._on_catalog_delete()
        self.assertEqual(self.prompt_catalog.list_entries(), [])
        self.assertEqual(app.catalog_tree.get_children(), ())
        self.assertIn("Deleted", app.catalog_status.get())

    def test_checkbox_state_matches_compatible_with_graph(self) -> None:
        """Every LoRA checkbox is enabled exactly for a compatible family."""
        app = self.app
        items = {str(it.get("id") or ""): it for it in self.lora_store.list_loras()}
        enabled = disabled = False
        for label in self.lora_store.GRAPH_CHOICES:
            app.var_graph.set(label)
            app.update_idletasks()
            graph = self.lora_store.graph_id(label)
            self.assertTrue(app._lora_checks, label)
            for lid, cb in app._lora_checks.items():
                ok = self.lora_store.compatible_with_graph(items[lid], graph)
                state = str(cb.cget("state"))
                if ok:
                    self.assertIn(state, ("normal", "active"), f"{lid} on {label}")
                    enabled = True
                else:
                    self.assertEqual(state, "disabled", f"{lid} on {label}")
                    disabled = True
                self.assertEqual(
                    bool(app._lora_vars[lid].get()),
                    ok and lid in app._selected_lora_ids(),
                    f"{lid} on {label}",
                )
        self.assertTrue(enabled, "no graph had a compatible LoRA")
        self.assertTrue(disabled, "no graph had an incompatible LoRA")

    def test_editor_text_has_scrollbars_wired(self) -> None:
        app = self.app
        self.assertTrue(app.editor_text.cget("yscrollcommand"))
        self.assertTrue(app.editor_text.cget("xscrollcommand"))

    def test_config_size_and_graph_rewrite_prompt_editor(self) -> None:
        app = self.app
        app.var_width.set("768")
        app.var_height.set("1216")
        app.var_steps.set("8")
        app.update_idletasks()
        self.assertEqual(
            _editor_body(app),
            self._expected(
                graph="klein",
                width=768,
                height=1216,
                steps=8,
                selected_ids=list(app._selected_lora_ids()),
            ),
        )
        body = _editor_body(app)
        self.assertEqual(body["prompt"]["66"]["inputs"]["width"], 768)
        self.assertEqual(body["prompt"]["66"]["inputs"]["height"], 1216)
        app.var_graph.set(self.lora_store.graph_label("flux1"))
        app.update_idletasks()
        got = _editor_body(app)
        self.assertEqual(
            got,
            self._expected(
                graph="flux1",
                width=768,
                height=1216,
                steps=8,
                selected_ids=list(app._selected_lora_ids()),
            ),
        )
        dumped = app.editor_text.get("1.0", "end")
        self.assertNotIn("2625692", dumped)

    def test_switching_profile_fills_config_widgets(self) -> None:
        from salad_studio.profiles import SaladProfile

        app = self.app
        tmp = Path(self._td.name)
        other = SaladProfile(
            name="flux-alt",
            gateway="https://flux.example.test/gateway",
            key_path=str(tmp / "alt-key"),
            graph="flux1",
            width=640,
            height=960,
            steps=6,
            selected_loras=[self.FLUX1_ULTRA],
        )
        self.profiles.upsert(other)
        app.profile_combo["values"] = sorted(self.profiles.load_all())
        app.var_name.set("flux-alt")
        app._on_select_profile()
        app.update_idletasks()
        self.assertEqual(app.var_gateway.get(), other.gateway)
        self.assertFalse(hasattr(app, "var_key"))
        self.assertEqual(app.var_graph.get(), self.lora_store.graph_label("flux1"))
        self.assertEqual(app.var_width.get(), "640")
        self.assertEqual(app.var_height.get(), "960")
        self.assertEqual(app.var_steps.get(), "6")
        self.assertTrue(app._lora_vars[self.FLUX1_ULTRA].get())
        self.assertEqual(
            str(app._lora_checks[self.KLEIN_DETAIL].cget("state")), "disabled"
        )
        self.assertEqual(
            _editor_body(app),
            self._expected(
                graph="flux1",
                width=640,
                height=960,
                steps=6,
                selected_ids=[self.FLUX1_ULTRA],
            ),
        )

    def test_rebuild_from_json_updates_config_prompt_and_loras(self) -> None:
        app = self.app
        aged = "civitai:1449678@2795018"
        text = "Aged art. Oil painting style.\n\nSurreal art."
        body = rj.build_request(
            prompt_text=text,
            graph="klein",
            width=1024,
            height=1024,
            steps=40,
            seed=1,
            selected_ids=[aged],
        )
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", json.dumps(body, indent=2))
        app._rebuild_from_json()
        app.update_idletasks()
        self.assertEqual(app.var_graph.get(), "Flux.2 Klein")
        self.assertEqual(app.var_width.get(), "1024")
        self.assertEqual(app.var_height.get(), "1024")
        self.assertEqual(app.var_steps.get(), "40")
        self.assertEqual(app.prompt_text.get("1.0", "end").strip(), text)
        self.assertIn(aged, app._selected_lora_ids())

    def test_positive_and_negative_sit_under_the_graph(self) -> None:
        app = self.app
        tabs = [app.nb.tab(t, "text") for t in app.nb.tabs()]
        self.assertNotIn("Prompt", tabs)
        neg = app.negative_text.master
        pos = app.prompt_text.master
        # Positive prompt is the left box, negative the right one.
        self.assertEqual(int(pos.grid_info()["column"]), 0)
        self.assertEqual(int(neg.grid_info()["column"]), 1)
        self.assertEqual(neg.master, pos.master)
        self.assertEqual(int(neg.master.grid_info()["row"]), 1)
        self.assertEqual(int(app._editor_bar.grid_info()["row"]), 2)
        self.assertEqual(int(neg.master.grid_columnconfigure(0)["weight"]), 66)
        self.assertEqual(int(neg.master.grid_columnconfigure(1)["weight"]), 34)

    def test_window_does_not_grow_after_it_is_shown(self) -> None:
        import time

        app = self.app
        app.deiconify()
        app.update()
        for _ in range(40):
            app.update()
            if app.winfo_width() > 1 and app.winfo_height() > 1:
                break
        width0 = int(app.winfo_width())
        height0 = int(app.winfo_height())
        self.assertGreater(width0, 1)
        self.assertGreater(height0, 1)
        print(f"shown {width0}x{height0}")
        app.update_idletasks()
        app._place_editor_sash()
        deadline = time.time() + 2.1
        while time.time() < deadline:
            app.update()
            time.sleep(0.05)
        width1 = int(app.winfo_width())
        height1 = int(app.winfo_height())
        print(f"later {width1}x{height1}")
        self.assertLessEqual(width1, width0 + 48)
        self.assertLessEqual(height1, height0 + 48)

    def test_editor_pane_opens_with_diagram_taking_three_quarters(self) -> None:
        app = self.app
        app._goto_tab("Prompt Editor")
        app.update_idletasks()
        pane = app._editor_pane
        # A hidden toplevel never lays out, so pane.winfo_width() stays 1 and
        # Tk clamps any sash move to the unlaid-out size. Feed the shipped
        # placement a real width and assert the position it asks Tk for: the
        # JSON box takes 25% of the pane, the diagram the other 75%.
        app._editor_sash_set = False
        with mock.patch.object(pane, "winfo_width", return_value=1000):
            with mock.patch.object(pane, "sashpos") as sashpos:
                app._place_editor_sash()
        sashpos.assert_called_once_with(0, 250)
        self.assertTrue(app._editor_sash_set)
        # The shipped geometry guard: a degenerate width must not place the
        # sash, and must leave the flag unset so the <Map> retry still runs.
        app._editor_sash_set = False
        with mock.patch.object(pane, "winfo_width", return_value=1):
            with mock.patch.object(pane, "sashpos") as sashpos:
                app._place_editor_sash()
        sashpos.assert_not_called()
        self.assertFalse(app._editor_sash_set)

    def test_editor_paste_and_copy_keep_the_widget_editable(self) -> None:
        app = self.app
        app.editor_text.delete("1.0", "end")
        pasted = '{"prompt":{"9":{"class_type":"SaveImage","inputs":{}}}}'
        app.clipboard_clear()
        app.clipboard_append(pasted)
        self.assertEqual(app._editor_paste(), "break")
        self.assertIn("SaveImage", app.editor_text.get("1.0", "end"))
        self.assertEqual(str(app.editor_text.cget("state")), "normal")
        app.editor_text.tag_add("sel", "1.0", "1.8")
        self.assertEqual(app._editor_copy(), "break")
        self.assertEqual(app.clipboard_get(), '{"prompt')
        app.editor_text.focus_force()
        app.update_idletasks()
        app._graph_stale = False
        app._refresh_graph()
        if app.focus_get() is app.editor_text:
            self.assertTrue(app._graph_stale)
        self.assertEqual(app._editor_select_all(), "break")
        self.assertEqual(
            app.editor_text.get("sel.first", "sel.last"),
            app.editor_text.get("1.0", "end-1c"),
        )
        calls: list[dict] = []
        app.graph_pane.set_prompt = lambda prompt: calls.append(prompt)
        app._graph_stale = True
        app._apply_json_chrome(refresh_graph=False)
        self.assertEqual(calls, [])
        app._on_editor_focus_out()
        self.assertEqual(len(calls), 1)
        self.assertFalse(app._graph_stale)
        app.editor_text.configure(state="disabled")
        app._on_editor_focus_in()
        self.assertEqual(str(app.editor_text.cget("state")), "normal")
        self.assertTrue(app._widget_in_graph(app.graph_pane))
        self.assertFalse(app._widget_in_graph(app.editor_text))
        released: list[str] = []
        app.graph_pane._web.focus_parent = lambda: released.append("parent")
        event = type("E", (), {"widget": app.editor_text})()
        app._on_click_outside_graph(event)
        self.assertEqual(released, ["parent"])

    def test_a_click_event_naming_a_widget_by_path_does_not_raise(self) -> None:
        """`bind_all` hands the WebView's click in as a path name, not a widget.

        The handler used to call ``focus_set`` on that string, and Tk logged an
        AttributeError and abandoned the callback.
        """
        from unittest import mock

        app = self.app
        released: list[str] = []
        app.graph_pane._web.focus_parent = lambda: released.append("parent")
        named = type("E", (), {"widget": str(app.editor_text)})()
        with mock.patch.object(app.editor_text, "focus_set") as focus:
            app._on_click_outside_graph(named)
        self.assertEqual(released, ["parent"], "the graph's keyboard was not released")
        self.assertTrue(focus.called, "the named widget must get the focus back")

        # A name that resolves to nothing (a destroyed widget) is ignored.
        stale = type("E", (), {"widget": ".!nosuchwidget"})()
        app._on_click_outside_graph(stale)
        nothing = type("E", (), {"widget": None})()
        app._on_click_outside_graph(nothing)

        # A click inside the graph pane still leaves the focus alone.
        inside = type("E", (), {"widget": app.graph_pane})()
        with mock.patch.object(app.editor_text, "focus_set") as focus2:
            app._on_click_outside_graph(inside)
        self.assertFalse(focus2.called)

    def test_prompt_edit_keeps_loaded_json_graph(self) -> None:
        app = self.app
        body = rj.build_request(
            prompt_text="original sentence",
            graph="klein",
            width=832,
            height=1216,
            steps=4,
            seed=7,
            cfg=1,
            selected_ids=[],
        )
        body["prompt"]["70"]["inputs"]["unet_name"] = (
            "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors"
        )
        body["prompt"]["marker"] = {"class_type": "Note", "inputs": {"text": "keep-me"}}
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", json.dumps(body, indent=2))
        app._rebuild_from_json()
        app.prompt_text.delete("1.0", "end")
        app.prompt_text.insert("1.0", "a 40 year old woman, completely nude")
        app._patch_editor_from_prompt()
        saved = _editor_body(app)
        self.assertEqual(saved["prompt"]["marker"]["inputs"]["text"], "keep-me")
        unet = saved["prompt"]["70"]["inputs"]["unet_name"]
        self.assertEqual(unet, "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors")
        positive = saved["prompt"]["74"]["inputs"]["text"]
        self.assertIn("completely nude", positive)
        self.assertNotIn("original sentence", positive)

    def test_ui_state_roundtrip_restores_dropdowns_and_checks(self) -> None:
        from salad_studio import profiles
        from salad_studio import ui_state

        app = self.app
        ui_state.STATE_PATH = Path(self._td.name) / "studio-ui.json"
        app.var_scheduler.set("Simple (Civitai)")
        app.var_unet.set("Distilled 9B")
        app.var_width.set("832")
        app.prompt_text.delete("1.0", "end")
        app.prompt_text.insert("1.0", "restored prompt")
        app._save_ui_state()
        app.var_scheduler.set("Flux2 (Klein)")
        app.var_unet.set("Base 9B")
        app.var_width.set("100")
        app.prompt_text.delete("1.0", "end")
        app.prompt_text.insert("1.0", "other")
        self.assertTrue(app._restore_ui_state())
        self.assertEqual(app.var_scheduler.get(), "Simple (Civitai)")
        self.assertEqual(app.var_unet.get(), "Distilled 9B")
        self.assertEqual(app.var_width.get(), "832")
        self.assertEqual(app.prompt_text.get("1.0", "end").strip(), "restored prompt")
        # The policy is not window state any more: it comes from the config.
        state = app._capture_ui_state()
        self.assertEqual([k for k in state if "policy" in k], [])
        active = app.var_name.get().strip()
        policy = (profiles.load_all()[active].policy or {}).get("image") or ""
        self.assertEqual(app.var_pol_image.get(), policy, "the fields follow the config")

    def test_action_bar_and_vertical_nav(self) -> None:
        app = self.app
        self.assertTrue(hasattr(app, "var_gen_state"))
        self.assertEqual(app.var_gen_state.get(), "Idle")
        self.assertIs(app.gen_editor_btn, app.gen_btn)
        for name in (
            "Config",
            "Tokens",
            "LoRAs",
            "Prompt Editor",
            "Import",
            "Prompt History",
            "Queue",
            "Logs",
        ):
            self.assertIn(name, app._nav_btns)
        self.assertNotIn("Policy", app._nav_btns, "the Policy page is gone")
        app._goto_tab("Import")
        app.update_idletasks()
        self.assertEqual(app.nb.tab(app.nb.select(), "text"), "Import")

    def test_clear_import_drops_stashed_workflow_json(self) -> None:
        app = self.app
        blob = '{"nodes":[{"id":1,"type":"Note"}],"links":[]}'
        app.import_meta.insert("1.0", "Sampler: Euler, Seed: 1")
        app._stash_import_workflow(blob)
        app.var_imp_cfg.set("5")
        app.var_imp_seed.set("99")
        self.assertEqual(app._import_workflow_text(), blob)
        shown = app.import_workflow.get("1.0", "end")
        self.assertIn("in memory", shown)
        self.assertNotIn('"nodes"', shown)
        app._clear_import()
        self.assertEqual(app._import_workflow_text(), "")
        self.assertEqual(app.import_meta.get("1.0", "end").strip(), "")
        self.assertEqual(app.import_workflow.get("1.0", "end").strip(), "")
        self.assertEqual(app.var_imp_cfg.get(), "")
        self.assertEqual(app.var_imp_seed.get(), "")

    def test_import_issues_panel_flags_distilled_klein(self) -> None:
        from tests.test_comfy_import import DISTILLED, DISTILLED_META

        app = self.app
        app.import_meta.insert("1.0", DISTILLED_META)
        app._stash_import_workflow(json.dumps(DISTILLED))
        issues = app._refresh_import_issues()
        shown = app.import_issues.get("1.0", "end")
        # The replica keeps ReferenceLatent / ConditioningZeroOut in the editor
        # and only warns (Generate omits them), so the panel names them under
        # "Warnings:" and the blocking list stays empty.
        self.assertEqual(issues, [])
        self.assertIn("Warnings:", shown)
        self.assertIn("ReferenceLatent", shown)
        self.assertIn("ConditioningZeroOut", shown)
        self.assertNotIn("full_encoder_small_decoder", shown)

    def test_tab_order_is_the_shipped_page_set(self) -> None:
        """The live notebook labels, not the source text (audit L15)."""
        from salad_studio import app as app_mod

        app = self.app
        labels = [app.nb.tab(t, "text") for t in app.nb.tabs()]
        self.assertEqual(
            labels,
            [
                "Config",
                "Prompt Settings",
                "Tokens",
                "LoRAs",
                "Prompt Editor",
                "Prompt Assist",
                "Prompt Catalog",
                "Import",
                "Prompt History",
                "Queue",
                "Logs",
            ],
        )
        # The notebook, the sidebar and _goto_tab all read TAB_ORDER.
        self.assertEqual(tuple(labels), app_mod.TAB_ORDER)
        # No "Prompt" tab: the prompt boxes live on the Prompt Editor tab.
        self.assertNotIn("Prompt", labels)
        self.assertEqual(app.nb.tab(app.nb.select(), "text"), labels[0])

    def test_the_images_and_vast_pages_are_folded_into_config(self) -> None:
        """One page owns the deployment: no top-level Images or Vast.ai tab."""
        from salad_studio import app as app_mod

        app = self.app
        labels = [app.nb.tab(t, "text") for t in app.nb.tabs()]
        self.assertNotIn("Images", labels)
        self.assertNotIn("Vast.ai", labels)
        self.assertNotIn("Images", app_mod.TAB_ORDER)
        self.assertNotIn("Vast.ai", app_mod.TAB_ORDER)
        # Every page the notebook shows has a sidebar button, and no button is
        # left pointing at a page that is gone.
        self.assertEqual(sorted(app._nav_btns), sorted(app_mod.TAB_ORDER))
        # The merged sections live on Config, which is where Generate reads them.
        for widget in (app.vast_tree, app.image_env_tree, app.pol_image_box):
            with self.subTest(widget=str(widget)):
                self.assertIn(
                    app._config,
                    self._ancestors(widget),
                    "the merged section must live on the Config page",
                )

    @staticmethod
    def _ancestors(widget) -> list:
        """The widget's ancestors, innermost first, ending at the toplevel."""
        out = []
        node = widget.master
        while node is not None:
            out.append(node)
            node = getattr(node, "master", None)
        return out

    def test_no_shipped_string_sends_the_user_to_a_removed_tab(self) -> None:
        """A message naming a page that no longer exists is a dead end."""
        manual = PKG / "README.md"
        sources = [
            PKG / name
            for name in ("app.py", "generator.py", "tokens.py", "vast.py", "image_deploy.py")
        ]
        for path in [*sources, manual]:
            text = path.read_text(encoding="utf-8")
            for needle in ("Vast.ai tab", "Images tab"):
                with self.subTest(path=path.name, needle=needle):
                    self.assertNotIn(
                        needle, text, f"{path.name} still points the user at {needle}"
                    )

    def test_the_config_page_holds_all_of_its_content(self) -> None:
        """The Config page itself does not scroll; each section tab holds its own."""
        from salad_studio import app as app_mod

        app = self.app
        app.update_idletasks()
        self.assertNotIn(
            app._config,
            app._scroll_canvases,
            "the Config page itself does not scroll",
        )
        self.assertEqual(
            tuple(key for key, _label, _builder in app_mod.CONFIG_SECTIONS),
            ("profile", "images", "policy", "vast"),
        )
        for key, _label, _builder in app_mod.CONFIG_SECTIONS:
            with self.subTest(section=key):
                page = app._config_section_pages[key]
                body = app._config_section_bodies[key]
                canvas = app._scroll_canvases[page]
                app._config_tabs.select(page)
                app.update_idletasks()
                bbox = canvas.bbox("all")
                self.assertIsNotNone(
                    bbox, f"{key}'s content must be in that section's scrollable canvas"
                )
                self.assertGreaterEqual(
                    int(bbox[3]),
                    body.winfo_reqheight(),
                    f"{key}'s scroll region must cover the whole section",
                )
        for name in ("checkpoint_tree", "image_env_tree", "image_script", "vast_tree"):
            with self.subTest(widget=name):
                self.assertIn(
                    app._config,
                    self._ancestors(getattr(app, name)),
                    f"{name} must still live on the Config page",
                )

    def test_the_wheel_scrolls_the_config_page(self) -> None:
        """T2: the real canvas moves, not a mocked method.

        Each Config section scrolls on its own. ``yscrollincrement`` is set so a
        wheel unit is a known number of pixels: an unmapped window is one pixel
        tall, and "units" would otherwise move the view by a tenth of that.
        """
        app = self.app
        page = app._config_section_pages["images"]
        canvas = app._scroll_canvases[page]
        body_height = 4000
        canvas.configure(yscrollincrement=40, scrollregion=(0, 0, 900, body_height))
        app._claim_wheel(page)
        app.update_idletasks()

        def wheel(delta: int) -> None:
            app._on_page_wheel(type("E", (), {"delta": delta})())

        before = canvas.yview()[0]
        self.assertEqual(before, 0.0, "the page starts at the top")
        wheel(-120)
        app.update_idletasks()
        after = canvas.yview()[0]
        self.assertGreater(after, before, "one wheel notch must scroll the page down")
        self.assertAlmostEqual(
            after - before,
            40 / body_height,
            places=4,
            msg="one notch is one unit, and a unit is the canvas's increment",
        )

        wheel(240)
        app.update_idletasks()
        self.assertAlmostEqual(
            canvas.yview()[0],
            0.0,
            places=4,
            msg="two notches up come back to the top",
        )
        wheel(0)
        app.update_idletasks()
        self.assertEqual(canvas.yview()[0], 0.0, "a wheel event with no delta moves nothing")

    def test_the_wheel_is_claimed_only_while_the_pointer_is_on_the_page(self) -> None:
        """The other pages and the history strip keep their own scrolling.

        The handler is bound once for the life of the window and gates itself on
        the pointer, so leaving the page never removes another page's binding.
        """
        app = self.app
        page = app._config_section_pages["images"]
        canvas = app._scroll_canvases[page]
        canvas.configure(yscrollincrement=40, scrollregion=(0, 0, 900, 4000))
        app.update_idletasks()

        app._release_wheel(page)
        app._on_page_wheel(type("E", (), {"delta": -120})())
        app.update_idletasks()
        self.assertEqual(
            canvas.yview()[0], 0.0, "the wheel must not scroll a page it has not claimed"
        )
        self.assertTrue(
            app.bind_all("<MouseWheel>"),
            "and the binding stays installed, so no other page loses its own",
        )

        app._claim_wheel(page)
        app._on_page_wheel(type("E", (), {"delta": -120})())
        app.update_idletasks()
        self.assertGreater(canvas.yview()[0], 0.0, "with the pointer on it, it scrolls")

        # A binding another page installed survives this page's whole cycle.
        other = mock.Mock()
        app.bind_all("<MouseWheel>", other, add="+")
        app._claim_wheel(page)
        app._release_wheel(page)
        self.assertTrue(app.bind_all("<MouseWheel>"), "the other page's binding is intact")

    def test_a_claimed_grid_routes_the_wheel_to_the_grid_not_the_page(self) -> None:
        """The class binding runs before the page's bind_all handler.

        The widget binding must take the event first, so the pointer over the
        grid scrolls the grid even when the page under it is also claimed; the
        page moves only once the pointer leaves the grid.
        """
        app = self.app
        page = app._config_section_pages["vast"]
        canvas = app._scroll_canvases[page]
        canvas.configure(yscrollincrement=40, scrollregion=(0, 0, 900, 4000))
        tree = app.vast_tree
        for index in range(40):
            tree.insert("", "end", iid=f"row-{index}", values=("",) * 6)
        tree.yview_moveto(0)
        app.update_idletasks()
        app._claim_wheel(page)
        app._claim_wheel_tree(tree)

        def wheel(delta: int = -120):
            return app._on_page_wheel(type("E", (), {"delta": delta})())

        self.assertEqual(wheel(), "break", "the handler always consumes the event")
        app.update_idletasks()
        self.assertGreater(tree.yview()[0], 0.0, "the grid under the pointer scrolls")
        self.assertEqual(canvas.yview()[0], 0.0, "the page under it does not")

        app._release_wheel_tree(tree)
        self.assertEqual(wheel(), "break")
        app.update_idletasks()
        self.assertGreater(canvas.yview()[0], 0.0, "the page scrolls once the grid hands it back")

    def test_every_grid_handles_its_own_wheel_event(self) -> None:
        """No grid may keep Tk's focus-following class wheel binding."""
        for name in (
            "vast_tree",
            "vast_offer_tree",
            "queue_tree",
            "lora_tree",
            "catalog_tree",
            "prompt_hist_tree",
            "checkpoint_tree",
            "image_env_tree",
        ):
            with self.subTest(widget=name):
                self.assertTrue(
                    getattr(self.app, name).bind("<MouseWheel>"),
                    f"{name} must claim the wheel by pointer, not focus",
                )

    def test_log_does_not_reread_tokens_once_the_cache_is_warm(self) -> None:
        """M9: log() redaction must not hit the token files per line."""
        app = self.app
        tokens = self.tokens
        real = tokens.read_token
        with mock.patch.object(tokens, "read_token", side_effect=real) as read:
            app.log("info", "warm")
            read.reset_mock()
            for _ in range(5):
                app.log("info", "warm log line")
            self.assertEqual(
                read.call_count,
                0,
                "log() re-read the token store with a warm redaction cache",
            )
            # Saving a token must invalidate the cache: the log inside
            # _save_token is the first read after it.
            app._token_entry["salad"].set("salad-test-key-1234")
            app._save_token("salad")
            self.assertGreater(read.call_count, 0)
            read.reset_mock()
            app.log("info", "after save")
            self.assertEqual(read.call_count, 0)

    def test_the_status_word_never_disables_generate(self) -> None:
        """L11, updated: the button is not the gate any more, the press is.

        Every word leaves the button live, including the empty one, so a request
        already queued or a container still coming up cannot block the next
        press; a press that cannot be dispatched is refused when it is made.
        """
        app = self.app
        for word in ("", "Ready", "Down", "Stopped", "Starting"):
            with self.subTest(word=word):
                app._set_salad_word(word)
                self.assertEqual(str(app.gen_btn.cget("state")), "normal")
        self.assertFalse(hasattr(app, "_apply_generate_gate"), "the button gate is gone")

    def test_status_probe_falls_through_on_an_empty_gateway(self) -> None:
        """L10: an empty gateway still probes the profile gateways."""
        app = self.app
        from salad_studio import salad_status

        self.tokens.write_token("salad", "salad-test-key-1234")
        app.var_gateway.set("")
        want = {gw for _pid, gw in app._status_targets()}
        with mock.patch.object(
            salad_status,
            "snapshot_gateway",
            return_value={"word": "Ready", "detail": "", "log_lines": []},
        ) as probe:
            # Must not raise: the empty-gateway branch is not an early return.
            app._check_salad_status()
            self.assertEqual(app.var_salad_status.get(), "Down")
            deadline = time.time() + 10
            while time.time() < deadline:
                if want <= {c.args[0] for c in probe.call_args_list}:
                    break
                app.update()
                time.sleep(0.02)
        # The probe reached the profile gateways (Config is empty), which is
        # what fills the dual replica badges.
        self.assertEqual({c.args[0] for c in probe.call_args_list}, want)


class _LocalAssistServer:
    """A real LM Studio-shaped server on 127.0.0.1, for the page's local path.

    It answers both APIs LM Studio serves: the native model list (with an
    embedding model, an unloaded chat model and a loaded one that reports no
    vision) and the OpenAI-compatible chat endpoint. Every request is recorded,
    so a test can assert what the shipped page actually sent.
    """

    MODELS = {
        "models": [
            {"key": "embed-nomic", "type": "embedding"},
            {"key": "chat-unloaded", "type": "llm", "loaded_instances": []},
            {
                "key": "chat-loaded",
                "type": "llm",
                "loaded_instances": [{"id": "chat-loaded"}],
                "capabilities": {"vision": False},
            },
        ]
    }
    REPLY = json.dumps(
        {
            "positive": "LOCAL POSITIVE",
            "negative": "LOCAL NEGATIVE",
            "issue": "the hand is missing",
        }
    )

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.headers: list[dict[str, str]] = []
        server = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:  # keep the test output clean
                pass

            def _answer(self, body: bytes) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                server.requests.append(("GET", self.path, {}))
                if self.path.endswith("/api/v1/models"):
                    self._answer(json.dumps(server.MODELS).encode())
                elif self.path.endswith("/v1/models"):
                    self._answer(json.dumps({"data": [{"id": "chat-loaded"}]}).encode())
                else:
                    self._answer(b"{}")

            def do_POST(self) -> None:
                server.headers.append(dict(self.headers))
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    parsed = {}
                server.requests.append(("POST", self.path, parsed))
                self._answer(
                    json.dumps(
                        {"choices": [{"message": {"role": "assistant", "content": server.REPLY}}]}
                    ).encode()
                )

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def posts(self) -> list[tuple[str, str, dict]]:
        return [row for row in self.requests if row[0] == "POST"]

    def paths(self) -> list[str]:
        return [path for _method, path, _body in self.requests]

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class NewPagesAndPlacement(unittest.TestCase):
    """Prompt Assist, the Config split, the action-bar badges and the key dots."""

    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        from salad_studio import (
            lora_store,
            profiles,
            prompt_catalog,
            prompt_history,
            tokens,
            ui_state,
        )

        self.tokens = tokens
        self.lora_store = lora_store
        saved = [
            _redirect_store(profiles, "PROFILES_PATH", self.tmp / "studio-profiles.json"),
            _redirect_store(lora_store, "EXTRAS_PATH", self.tmp / "studio-loras.json"),
            _redirect_store(tokens, "LOCAL_PATH", self.tmp / "studio-tokens.json"),
            _redirect_store(tokens, "CONFIG_HOME", self.tmp / "defaults"),
            _redirect_store(
                prompt_catalog, "CATALOG_PATH", self.tmp / "studio-prompt-catalog.json"
            ),
            _redirect_store(
                prompt_history, "HISTORY_PATH", self.tmp / "studio-prompt-history.json"
            ),
            _redirect_store(ui_state, "STATE_PATH", self.tmp / "studio-ui.json"),
        ]
        self.addCleanup(_put_stores_back, saved)
        from salad_studio.app import SaladStudio

        self.app = SaladStudio(show=False)
        self.app.withdraw()
        self.app.update_idletasks()
        self.addCleanup(self.app.destroy)

    # --- helpers ---------------------------------------------------------
    @staticmethod
    def _all_widgets(root) -> list:
        out: list = []

        def walk(widget) -> None:
            out.append(widget)
            for child in widget.winfo_children():
                walk(child)

        walk(root)
        return out

    def _label_with_var(self, root, var):
        for widget in self._all_widgets(root):
            if isinstance(widget, (ttk.Label, tk.Label)):
                try:
                    if str(widget.cget("textvariable")) == str(var):
                        return widget
                except tk.TclError:
                    continue
        return None

    def _descends_from(self, widget, ancestor) -> bool:
        cur = widget
        while cur is not None:
            if cur is ancestor:
                return True
            cur = getattr(cur, "master", None)
        return False

    def _pump(self, predicate, timeout: float = 40.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            self.app.update()
            time.sleep(0.02)
        return predicate()

    @staticmethod
    def _inline_thread():
        """A Thread stand-in that runs the worker on the calling thread.

        The shipped handlers finish by calling ``self.after(0, done)`` from the
        worker; Tk refuses that without a running main loop, so a test that
        wants to see the finished state runs the worker inline and then pumps
        ``update()`` to fire the scheduled callback.
        """

        class _Inline:
            def __init__(self, target=None, daemon=None, **_kw):
                self._target = target

            def start(self) -> None:
                if self._target is not None:
                    self._target()

        return _Inline

    def _buttons(self, root) -> dict[str, object]:
        return {
            str(w.cget("text")): w
            for w in self._all_widgets(root)
            if isinstance(w, ttk.Button)
        }

    @staticmethod
    def _widget_text(widget) -> str:
        """What a label shows: its textvariable's value, else its static text."""
        try:
            var = str(widget.cget("textvariable"))
        except tk.TclError:
            var = ""
        if var:
            return str(widget.getvar(var))
        try:
            return str(widget.cget("text"))
        except tk.TclError:
            return ""

    def _strip_text(self, app) -> str:
        """The strip's visible text, read off its own widgets in order."""
        return "".join(self._widget_text(w) for w in app._strip.winfo_children())

    @staticmethod
    def _rgb(hexcolor: str) -> tuple[int, int, int]:
        h = hexcolor.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    @staticmethod
    def _snap(replicas: int, instances: list) -> dict:
        """A probe snapshot shaped like the one salad_status.check_container builds."""
        return {"group": {"replicas": replicas}, "instances": instances}

    # --- pages exist -----------------------------------------------------
    def test_the_two_new_pages_are_in_the_notebook(self) -> None:
        labels = [self.app.nb.tab(t, "text") for t in self.app.nb.tabs()]
        self.assertIn("Prompt Assist", labels)
        self.assertIn("Prompt Settings", labels)

    # --- prompt assist ---------------------------------------------------
    def test_commit_writes_the_adjusted_prompts_into_the_prompts_and_json(self) -> None:
        app = self.app
        before = app.editor_text.get("1.0", "end")
        app.helper_adj_pos.delete("1.0", "end")
        app.helper_adj_pos.insert("1.0", "COMMITTED POSITIVE")
        app.helper_adj_neg.delete("1.0", "end")
        app.helper_adj_neg.insert("1.0", "COMMITTED NEGATIVE")

        app._on_prompt_commit()
        app.update_idletasks()

        # The real prompt boxes took the text...
        self.assertEqual(app.prompt_text.get("1.0", "end-1c").strip(), "COMMITTED POSITIVE")
        self.assertEqual(
            app.negative_text.get("1.0", "end-1c").strip(), "COMMITTED NEGATIVE"
        )
        # ...and so did the JSON's CLIP text encodes.
        dumped = app.editor_text.get("1.0", "end")
        self.assertNotEqual(dumped, before)
        payload = json.loads(dumped)
        cfg = rj.config_from_payload(payload)
        self.assertEqual(cfg["prompt_text"], "COMMITTED POSITIVE")
        self.assertEqual(cfg["negative_text"], "COMMITTED NEGATIVE")
        encode_texts = [
            str(node["inputs"].get("text") or "")
            for node in payload["prompt"].values()
            if node.get("class_type") == "CLIPTextEncode"
        ]
        self.assertIn("COMMITTED POSITIVE", encode_texts)
        self.assertIn("COMMITTED NEGATIVE", encode_texts)
        # The mirror now shows the committed text, and the page says so.
        app._refresh_prompt_helper()
        self.assertEqual(
            app.helper_editor_pos.get("1.0", "end-1c"), "COMMITTED POSITIVE"
        )
        self.assertIn("committed", app.status.get())
        self.assertIn("committed", app.helper_state.get() + app.status.get())

    def test_commit_button_is_on_the_prompt_assist_page(self) -> None:
        app = self.app
        labels = [app.nb.tab(t, "text") for t in app.nb.tabs()]
        self.assertIn("Prompt Assist", labels)
        self.assertNotIn("Prompt Helper", labels)
        self.assertEqual(
            str(app.helper_commit_btn.cget("text")), "Commit to Prompts + JSON"
        )
        self.assertTrue(
            self._descends_from(app.helper_commit_btn, app._helper),
            "the commit button must live on the Prompt Assist page",
        )
        self.assertTrue(self._descends_from(app.helper_btn, app._helper))

    def test_commit_refuses_empty_adjusted_prompts(self) -> None:
        from salad_studio import app as app_mod

        app = self.app
        before = app.editor_text.get("1.0", "end")
        app.helper_adj_pos.delete("1.0", "end")
        app.helper_adj_neg.delete("1.0", "end")
        with mock.patch.object(app_mod.messagebox, "showinfo") as info:
            app._on_prompt_commit()
        self.assertTrue(info.called, "an empty commit should be reported")
        self.assertEqual(app.editor_text.get("1.0", "end"), before)

    def test_commit_says_so_when_the_json_had_to_be_rebuilt(self) -> None:
        app = self.app
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", "not json at all")
        app.helper_adj_pos.delete("1.0", "end")
        app.helper_adj_pos.insert("1.0", "REBUILT POSITIVE")
        app._on_prompt_commit()
        app.update_idletasks()
        # _patch_editor_from_prompt falls back to rebuilding from Prompt Settings,
        # so the text still lands in the JSON, and the page says the JSON was rebuilt.
        dumped = app.editor_text.get("1.0", "end")
        self.assertIn("REBUILT POSITIVE", dumped)
        self.assertEqual(
            rj.config_from_payload(json.loads(dumped))["prompt_text"], "REBUILT POSITIVE"
        )
        self.assertIn("rebuilt", app.status.get())

    def test_commit_says_rebuilt_for_a_graph_the_patch_cannot_touch(self) -> None:
        """A parseable graph without the CFG wiring is rebuilt, not patched.

        ``patchable`` used to be decided by ``parse_request_json`` alone, so this
        graph took the "committed to the JSON" branch while the editor was
        silently replaced from Prompt Settings.
        """
        app = self.app
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert(
            "1.0",
            json.dumps(
                {
                    "prompt": {
                        "1": {
                            "class_type": "Note",
                            "inputs": {"text": "KEEP-ME-MARKER"},
                        },
                        "9": {"class_type": "SaveImage", "inputs": {}},
                    }
                }
            ),
        )
        app.helper_adj_pos.delete("1.0", "end")
        app.helper_adj_pos.insert("1.0", "UNPATCHABLE POSITIVE")
        app._on_prompt_commit()
        app.update_idletasks()
        self.assertIn("rebuilt", app.status.get())
        self.assertNotIn("committed to the prompts and the JSON", app.status.get())

    def test_rebuilding_from_json_does_not_verify_a_lora_on_the_main_thread(self) -> None:
        """Loading a graph must not run one live Civitai check per LoRA."""
        from salad_studio import app as app_mod

        app = self.app
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", json.dumps({"prompt": {}}))
        cfg = {
            "selected_ids": [],
            "unmatched_loras": [
                {"lora_name": "https://civitai.com/api/download/models/2795018"}
            ],
        }
        seen: dict = {}

        def fake_add(name, **kwargs):
            seen.update(kwargs)
            return {"id": "civitai:1@2795018"}

        with mock.patch.object(
            app_mod.request_json, "config_from_payload", return_value=cfg
        ), mock.patch.object(app_mod.lora_store, "add_lora", side_effect=fake_add):
            app._rebuild_from_json()
        self.assertFalse(
            seen.get("verify", True), "the main-thread path must not go live"
        )

    def test_switching_to_vast_does_not_keep_a_salad_gateway(self) -> None:
        """A Salad URL in vast mode POSTs the graph to the wrong host."""
        app = self.app
        app.var_profile_mode.set("salad")
        app.var_gateway.set("https://apple-gadogado-5d0vs4l8x0j51hwy.salad.cloud")
        app._on_profile_mode()
        self.assertIn("salad.cloud", app.var_gateway.get())
        app.var_profile_mode.set("vast")
        app._on_profile_mode()
        self.assertNotIn("salad.cloud", app.var_gateway.get())

    def test_selecting_a_vast_row_points_the_target_box_at_it(self) -> None:
        app = self.app
        app._vast_doc = {
            "active": "",
            "instances": [
                {"endpoint": "http://203.0.113.9:31234"},
                {"endpoint": "http://198.51.100.7:40111"},
            ],
        }
        app._refresh_vast_page()
        rows = app.vast_tree.get_children()
        app.vast_tree.selection_set(rows[1])
        app.var_profile_mode.set("vast")
        app._on_vast_select()
        self.assertEqual(app.var_gateway.get(), "http://198.51.100.7:40111")

    def test_removing_an_image_asks_first_and_honours_a_no(self) -> None:
        from salad_studio import app as app_mod

        app = self.app
        entry = {"key": "mine", "source": app_mod.image_deploy.SOURCE_SETTINGS}
        with mock.patch.object(app, "_image_entry", return_value=entry), mock.patch.object(
            app_mod.image_deploy, "remove_image"
        ) as remove, mock.patch.object(
            app_mod.messagebox, "askyesno", return_value=False
        ) as ask:
            app._on_image_remove_image()
        self.assertTrue(ask.called, "removing a stored image must ask first")
        self.assertFalse(remove.called, "a No leaves the image and its env alone")
        self.assertIn("Kept", app.status.get())

    def test_removing_a_vast_instance_asks_first_and_honours_a_no(self) -> None:
        from salad_studio import app as app_mod

        app = self.app
        app._vast_doc = {
            "active": "",
            "instances": [{"endpoint": "http://203.0.113.9:31234"}],
        }
        app._refresh_vast_page()
        rows = app.vast_tree.get_children()
        app.vast_tree.selection_set(rows[0])
        with mock.patch.object(
            app_mod.vast, "remove_instance"
        ) as remove, mock.patch.object(
            app_mod.messagebox, "askyesno", return_value=False
        ) as ask:
            app._on_vast_remove()
        self.assertTrue(ask.called)
        self.assertFalse(remove.called)
        self.assertIn("Kept", app.status.get())

    def test_a_vast_press_with_a_salad_gateway_refuses_before_dispatch(self) -> None:
        from salad_studio import app as app_mod
        from salad_studio.profiles import SaladProfile

        app = self.app
        p = SaladProfile(
            name="klein",
            gateway="https://apple-gadogado-5d0vs4l8x0j51hwy.salad.cloud",
            mode="vast",
        )
        payload = {"prompt": {"9": {"class_type": "SaveImage"}}}
        with mock.patch.object(
            app_mod.generator, "generate_from_vast"
        ) as dispatch, mock.patch.object(app_mod.messagebox, "showerror"):
            app._on_generate_vast(payload, p)
        self.assertFalse(dispatch.called, "a Salad URL must not reach vast dispatch")
        self.assertIn("Refused", app.status.get())
        self.assertIn("Salad gateway", app.status.get())

    def _plate(self, name: str = "studio_test.jpg", size: tuple[int, int] = (64, 64)) -> Path:
        """A real JPEG in a temp plate dir, so the image option is hermetic."""
        from PIL import Image

        plates = self.tmp / "plates"
        plates.mkdir(exist_ok=True)
        Image.new("RGB", size, (140, 100, 70)).save(plates / name, "JPEG", quality=90)
        return plates / name

    def test_issue_box_and_image_option_are_on_the_page(self) -> None:
        from salad_studio import app as app_mod

        app = self.app
        self.assertTrue(self._descends_from(app.helper_issue, app._helper))
        self.assertFalse(app.var_helper_image.get(), "the image option defaults off")
        self.assertIn("no image is sent", str(app.helper_image_lbl.cget("text")))

        plate = self._plate()
        with mock.patch.object(app_mod, "OUT_DIR", plate.parent):
            app.var_helper_image.set(True)
            app._refresh_helper_image_label()
            self.assertIn(f"attaching {plate.name}", str(app.helper_image_lbl.cget("text")))
            app.var_helper_image.set(False)
            app._refresh_helper_image_label()
            self.assertIn("no image is sent", str(app.helper_image_lbl.cget("text")))

    def test_every_backend_label_names_the_right_backend(self) -> None:
        """Criterion 1: no label calls a pane DeepSeek-only when both fill it.

        Read off the real window's own widgets: the reply pane's LabelFrame
        title, the image note in both checkbox states, and the dialog an empty
        commit shows.
        """
        from salad_studio import app as app_mod

        app = self.app
        reply_box = app.helper_reply.master
        title = str(reply_box.cget("text"))
        self.assertIn("local", title.lower(), f"the reply pane must name both: {title!r}")
        self.assertIn("deepseek", title.lower())
        self.assertNotEqual(title, "DeepSeek reply (raw)")

        app.var_helper_image.set(False)
        app._refresh_helper_image_label()
        off = str(app.helper_image_lbl.cget("text"))
        self.assertIn("no image is sent", off)
        self.assertNotIn("DeepSeek", off, "the note is about the box, not one backend")

        plate = self._plate("studio_assist_label.jpg")
        with mock.patch.object(app_mod, "OUT_DIR", plate.parent):
            app.var_helper_image.set(True)
            app._refresh_helper_image_label()
            on = str(app.helper_image_lbl.cget("text"))
        self.assertIn(plate.name, on)
        self.assertNotIn("DeepSeek", on, "the note is about the box, not one backend")

        app.helper_adj_pos.delete("1.0", "end")
        app.helper_adj_neg.delete("1.0", "end")
        seen: list[str] = []
        with mock.patch.object(
            app_mod.messagebox,
            "showinfo",
            lambda *a, **_k: seen.append(" ".join(str(x) for x in a)),
        ):
            app._on_prompt_commit()
        self.assertTrue(seen, "an empty commit must be reported")
        dialog = seen[0]
        self.assertIn("local", dialog.lower(), f"the dialog must name both: {dialog!r}")
        self.assertNotIn("Ask DeepSeek for help first", dialog)

        # And no DeepSeek-only claim survives in the two modules that carry the
        # page and the helper.
        pkg = Path(app_mod.__file__).resolve().parent
        for name in ("app.py", "ai_helper.py"):
            src = (pkg / name).read_text(encoding="utf-8")
            for phrase in (
                "DeepSeek reply (raw)",
                "no image is sent to DeepSeek",
                "Ask DeepSeek for help first",
                "DeepSeek-backed prompt help",
            ):
                self.assertNotIn(phrase, src, f"{name} still says {phrase!r}")

    def _drive_in_mainloop(self, app, body, predicate, seconds: float = 90.0) -> None:
        """Run ``body`` on the Tk thread inside a real main loop, then pump.

        The page's Help handlers start a worker thread and report back with
        ``after``, which Tk refuses without a running loop; ``predicate``
        says when the page has come back.
        """
        outcome: list[BaseException] = []
        deadline = time.time() + seconds

        def run() -> None:
            try:
                body()
                while not predicate() and time.time() < deadline:
                    app.update()
                    time.sleep(0.02)
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                outcome.append(exc)
            finally:
                app.quit()

        app.after(0, run)
        app.mainloop()
        if outcome:
            raise outcome[0]
        self.assertTrue(predicate(), "the page never came back")

    def _prepare_assist_press(self, app, url: str) -> None:
        """Put a parseable graph and a marked prompt in the editor, point the page at ``url``."""
        from salad_studio import profiles

        klein = profiles.load_all()["klein"]
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert(
            "1.0", json.dumps(self._graph_with_unet(klein.primary_checkpoint))
        )
        app._rebuild_from_json()
        app.prompt_text.delete("1.0", "end")
        app.prompt_text.insert("1.0", "MARKER EDITOR POSITIVE")
        app.helper_issue.delete("1.0", "end")
        app.helper_issue.insert("1.0", "MARKER ISSUE the hand is missing")
        app._refresh_prompt_helper()
        app.var_helper_local_url.set(url)
        app.log_text.delete("1.0", "end")

    def test_help_local_runs_against_a_real_local_server(self) -> None:
        """Criterion 2: the shipped page talks to a real OpenAI-compatible server."""
        from salad_studio import ref_check

        app = self.app
        server = _LocalAssistServer()
        self.addCleanup(server.stop)
        self._prepare_assist_press(app, server.url)  # a bare host:port, no scheme

        with mock.patch.object(ref_check, "online_lookup", return_value=None):
            self._drive_in_mainloop(
                app, app._on_prompt_help_local, lambda: not app._helper_busy
            )

        self.assertFalse(app._helper_busy, "the page must come back to idle")
        self.assertTrue(
            any(path.endswith("/api/v1/models") for path in server.paths()),
            f"the page must read the server's model list: {server.requests}",
        )
        posts = server.posts()
        self.assertEqual(len(posts), 1, f"exactly one chat POST: {server.requests}")
        for headers in server.headers:
            self.assertNotIn(
                "Authorization", headers, "a local request carries no key"
            )
        _method, path, body = posts[0]
        self.assertTrue(path.endswith("/v1/chat/completions"), f"posted to {path}")
        self.assertEqual(
            body.get("model"), "chat-loaded", "the loaded chat model's id, not the others"
        )
        content = body["messages"][1]["content"]
        text = content if isinstance(content, str) else content[0]["text"]
        self.assertIn("MARKER EDITOR POSITIVE", text, "the editor prompt rides along")
        self.assertIn("MARKER ISSUE", text, "and the issue box does too")

        self.assertEqual(app.helper_adj_pos.get("1.0", "end-1c"), "LOCAL POSITIVE")
        self.assertEqual(app.helper_adj_neg.get("1.0", "end-1c"), "LOCAL NEGATIVE")
        self.assertIn(
            "LOCAL POSITIVE", app.helper_reply.get("1.0", "end"), "the raw reply pane"
        )
        self.assertIn("the hand is missing", app.helper_state.get(), "what the model saw")
        self.assertIn(
            "chat-loaded", app.log_text.get("1.0", "end"), "the log names the model"
        )
        # The model reports no image support, and the note says so rather than
        # claiming a plate is going to be read.
        app.var_helper_image.set(True)
        app._refresh_helper_image_label()
        self.assertNotIn(
            "attaching",
            str(app.helper_image_lbl.cget("text")),
            "a model that cannot take an image must not be said to be reading one",
        )

    def test_help_local_reports_a_server_that_is_not_running(self) -> None:
        """Criterion 3: a dead port gives the actionable message, buttons back."""
        from salad_studio import ref_check

        app = self.app
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()  # nothing listens there now
        self._prepare_assist_press(app, f"http://127.0.0.1:{port}")

        with mock.patch.object(ref_check, "online_lookup", return_value=None):
            self._drive_in_mainloop(
                app, app._on_prompt_help_local, lambda: not app._helper_busy, 120
            )

        self.assertIn(
            "is the local model server running?", app.helper_state.get(), "the state"
        )
        self.assertIn(
            "is the local model server running?",
            app.helper_reply.get("1.0", "end"),
            "the reply pane",
        )
        self.assertFalse(app._helper_busy, "the page must come back to idle")
        for btn in (app.helper_btn, app.helper_local_btn):
            self.assertEqual(
                str(btn.cget("state")), "normal", "the buttons must be usable again"
            )
        self.assertNotIn("Traceback", app.log_text.get("1.0", "end"))

    def test_every_local_url_form_reaches_the_chat_endpoint(self) -> None:
        """Criterion 3: the native base, a pasted inference URL and host:port."""
        from salad_studio import ai_helper

        server = _LocalAssistServer()
        self.addCleanup(server.stop)
        want = f"{server.url}/v1"
        forms = (
            f"{server.url}/v1",
            f"{server.url}/api/v1",
            f"{server.url}/v1/chat/completions",
            server.url.replace("http://", ""),
        )
        for form in forms:
            with self.subTest(form=form):
                self.assertEqual(ai_helper.local_base(form), want)

        for form in forms:
            with self.subTest(call=form):
                out = ai_helper.help_with_prompts_local(
                    url=form, editor_positive="MARKER POSITIVE"
                )
                self.assertEqual(out["base"], want, "the OpenAI-compatible base")
                self.assertEqual(out["model"], "chat-loaded", "the loaded chat model")
                self.assertEqual(out["positive"], "LOCAL POSITIVE")
        posts = server.posts()
        self.assertEqual(len(posts), len(forms), f"one POST per form: {server.requests}")
        for _method, path, _body in posts:
            self.assertTrue(path.endswith("/v1/chat/completions"), path)

    def test_issue_reaches_the_help_request(self) -> None:
        from salad_studio import ai_helper, app as app_mod, ref_check

        app = self.app
        self.tokens.write_token("deepseek", "ds-app-test-key")
        app.helper_issue.delete("1.0", "end")
        app.helper_issue.insert("1.0", "the head is missing")
        seen: dict = {}

        def fake_send(request, timeout):
            seen["request"] = request
            return 200, json.dumps(
                {"choices": [{"message": {"content": '{"positive": "P", "negative": "N"}'}}]}
            ).encode()

        with mock.patch.object(ai_helper, "_http_send", side_effect=fake_send), mock.patch.object(
            ref_check, "online_lookup", return_value=None
        ), mock.patch("salad_studio.app.threading.Thread", self._inline_thread()):
            app._on_prompt_help()
            self.assertTrue(self._pump(lambda: not app._helper_busy))

        content = json.loads(seen["request"].data.decode())["messages"][1]["content"]
        self.assertIsInstance(content, str, "no image option means text-only content")
        head = content.split("=== POSITIVE PROMPT")[0]
        self.assertIn("the head is missing", head)
        self.assertIn("HIGHEST PRIORITY", head)
        self.assertEqual(app.helper_adj_pos.get("1.0", "end-1c"), "P")
        del app_mod

    def test_help_attaches_the_plate_and_surfaces_what_deepseek_saw(self) -> None:
        from salad_studio import ai_helper, app as app_mod, ref_check

        app = self.app
        self.tokens.write_token("deepseek", "ds-app-test-key")
        plate = self._plate("studio_plated.jpg", (200, 120))
        app.helper_issue.delete("1.0", "end")
        app.helper_issue.insert("1.0", "her arm is missing")
        seen: dict = {}
        reply = json.dumps(
            {
                "issue": "the left arm is missing below the shoulder",
                "positive": "ARM POSITIVE",
                "negative": "ARM NEGATIVE",
            }
        )

        def fake_send(request, timeout):
            seen["request"] = request
            return 200, json.dumps(
                {"choices": [{"message": {"content": reply}}]}
            ).encode()

        with mock.patch.object(ai_helper, "_http_send", side_effect=fake_send), mock.patch.object(
            ref_check, "online_lookup", return_value=None
        ), mock.patch.object(app_mod, "OUT_DIR", plate.parent), mock.patch(
            "salad_studio.app.threading.Thread", self._inline_thread()
        ):
            app.var_helper_image.set(True)
            app._on_prompt_help()
            self.assertTrue(self._pump(lambda: not app._helper_busy))

        content = json.loads(seen["request"].data.decode())["messages"][1]["content"]
        self.assertIsInstance(content, list, "the plate must ride along as an image part")
        self.assertEqual([part["type"] for part in content], ["text", "image_url"])
        self.assertIn("her arm is missing", content[0]["text"])
        self.assertTrue(
            content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        )
        # The model's own finding is reported back on the page.
        self.assertIn("the left arm is missing", app.helper_state.get())
        self.assertIn("the left arm is missing", app.helper_reply.get("1.0", "end"))
        self.assertEqual(app.helper_adj_pos.get("1.0", "end-1c"), "ARM POSITIVE")
        self.assertEqual(app.helper_adj_neg.get("1.0", "end-1c"), "ARM NEGATIVE")

    def test_a_reply_missing_one_prompt_keeps_what_the_artist_typed(self) -> None:
        """A partial reply must not wipe the box its answer does not cover."""
        from salad_studio import ai_helper, ref_check

        app = self.app
        self.tokens.write_token("deepseek", "ds-app-test-key")
        for widget, text in (
            (app.helper_adj_pos, "ARTIST POSITIVE"),
            (app.helper_adj_neg, "ARTIST NEGATIVE"),
        ):
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
        # A reasoning model that restarted its JSON can leave one side empty.
        reply = json.dumps({"issue": "", "positive": "MODEL POSITIVE", "negative": ""})

        def fake_send(request, timeout):
            return 200, json.dumps(
                {"choices": [{"message": {"content": reply}}]}
            ).encode()

        with mock.patch.object(ai_helper, "_http_send", side_effect=fake_send), mock.patch.object(
            ref_check, "online_lookup", return_value=None
        ), mock.patch("salad_studio.app.threading.Thread", self._inline_thread()):
            app._on_prompt_help()
            self.assertTrue(self._pump(lambda: not app._helper_busy))

        self.assertEqual(app.helper_adj_pos.get("1.0", "end-1c"), "MODEL POSITIVE")
        self.assertEqual(app.helper_adj_neg.get("1.0", "end-1c"), "ARTIST NEGATIVE")

    def _local_send(self, *, models: tuple[str, ...] = ("local-model",), reply: str | None = None):
        """A fake LM Studio server; records the URLs it was asked for."""
        seen: dict = {"urls": []}
        content = reply if reply is not None else json.dumps(
            {"positive": "LOCAL POS", "negative": "LOCAL NEG"}
        )

        def send(request, timeout):
            seen["urls"].append(request.full_url)
            if request.full_url.endswith("/models"):
                return 200, json.dumps(
                    {"data": [{"id": name} for name in models]}
                ).encode()
            seen["chat"] = request
            return 200, json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": content}}]}
            ).encode()

        return send, seen

    def test_local_url_and_button_are_on_the_page(self) -> None:
        from salad_studio import ai_helper

        app = self.app
        self.assertEqual(app.var_helper_local_url.get(), ai_helper.LOCAL_BASE_URL)
        self.assertEqual(str(app.helper_local_btn.cget("text")), "Help (local)")
        self.assertTrue(self._descends_from(app.helper_local_btn, app._helper))
        self.assertTrue(self._descends_from(app.helper_btn, app._helper))
        entries = [w for w in self._all_widgets(app._helper) if isinstance(w, ttk.Entry)]
        self.assertTrue(
            any(
                str(w.cget("textvariable")) == str(app.var_helper_local_url)
                for w in entries
            ),
            "the local URL must be editable on the page",
        )

    def test_help_local_sends_to_the_entered_url(self) -> None:
        from salad_studio import ai_helper, ref_check

        app = self.app
        app.var_helper_local_url.set("localhost:7777/v1")
        app.helper_adj_pos.delete("1.0", "end")
        app.helper_adj_pos.insert("1.0", "LOCAL ADJUSTED")
        send, seen = self._local_send()

        with mock.patch.object(ai_helper, "_http_send", side_effect=send), mock.patch.object(
            ref_check, "online_lookup", return_value=None
        ), mock.patch("salad_studio.app.threading.Thread", self._inline_thread()):
            app._on_prompt_help_local()
            self.assertTrue(self._pump(lambda: not app._helper_busy))

        self.assertIn("http://localhost:7777/v1/models", seen["urls"])
        self.assertEqual(seen["chat"].full_url, "http://localhost:7777/v1/chat/completions")
        body = json.loads(seen["chat"].data.decode())
        self.assertEqual(body["model"], "local-model", "the loaded model id is used")
        context = body["messages"][1]["content"]
        self.assertIn("LOCAL ADJUSTED", context)
        self.assertIn("LoraLoader", context)
        self.assertEqual(app.helper_adj_pos.get("1.0", "end-1c"), "LOCAL POS")
        self.assertEqual(app.helper_adj_neg.get("1.0", "end-1c"), "LOCAL NEG")
        self.assertIn("local", app.helper_state.get().lower())

    def test_help_local_does_not_need_a_deepseek_key(self) -> None:
        from salad_studio import ai_helper, ref_check

        app = self.app
        send, seen = self._local_send()
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}), mock.patch.object(
            ai_helper, "_http_send", side_effect=send
        ), mock.patch.object(ref_check, "online_lookup", return_value=None), mock.patch(
            "salad_studio.app.threading.Thread", self._inline_thread()
        ):
            app._on_prompt_help_local()
            self.assertTrue(self._pump(lambda: not app._helper_busy))
        self.assertIn("chat", seen, "the local call must run without any stored key")
        self.assertEqual(app.helper_adj_pos.get("1.0", "end-1c"), "LOCAL POS")

    def test_local_server_down_is_reported_on_the_page(self) -> None:
        from salad_studio import ai_helper, ref_check

        app = self.app

        def boom(request, timeout):
            raise ai_helper.AiError("model call failed: URLError: connection refused")

        with mock.patch.object(ai_helper, "_http_send", side_effect=boom), mock.patch.object(
            ref_check, "online_lookup", return_value=None
        ), mock.patch("salad_studio.app.threading.Thread", self._inline_thread()):
            app._on_prompt_help_local()
            self.assertTrue(self._pump(lambda: not app._helper_busy))

        reply = app.helper_reply.get("1.0", "end")
        self.assertIn("LM Studio", reply)
        self.assertIn("Start Server", reply)
        self.assertIn("failed", app.helper_state.get())
        # The DeepSeek button must still be usable afterwards.
        self.assertFalse(app._helper_busy)
        self.assertFalse(app.helper_local_btn.instate(["disabled"]))

    def test_local_url_and_issue_round_trip_through_ui_state(self) -> None:
        from salad_studio import ui_state

        app = self.app
        app.var_helper_local_url.set("http://127.0.0.1:4321/v1")
        app.helper_issue.delete("1.0", "end")
        app.helper_issue.insert("1.0", "saved issue text")
        state = app._capture_ui_state()
        self.assertEqual(state["helper_local_url"], "http://127.0.0.1:4321/v1")
        self.assertEqual(state["helper_issue"], "saved issue text")
        ui_state.save_state(state)

        app.var_helper_local_url.set("http://wrong-host/v1")
        app.helper_issue.delete("1.0", "end")
        self.assertTrue(app._restore_ui_state())
        self.assertEqual(app.var_helper_local_url.get(), "http://127.0.0.1:4321/v1")
        self.assertEqual(app.helper_issue.get("1.0", "end-1c"), "saved issue text")

    def test_helper_mirrors_the_editor_prompts_on_open(self) -> None:
        app = self.app
        app.prompt_text.delete("1.0", "end")
        app.prompt_text.insert("1.0", "MIRROR_POSITIVE")
        app.negative_text.delete("1.0", "end")
        app.negative_text.insert("1.0", "MIRROR_NEGATIVE")

        app._goto_tab("Prompt Assist")
        app._on_notebook_tab()
        app.update_idletasks()

        self.assertEqual(app.helper_editor_pos.get("1.0", "end-1c"), "MIRROR_POSITIVE")
        self.assertEqual(app.helper_editor_neg.get("1.0", "end-1c"), "MIRROR_NEGATIVE")
        # The mirror is read-only; the adjusted pair is editable.
        self.assertEqual(str(app.helper_editor_pos.cget("state")), "disabled")
        self.assertEqual(str(app.helper_editor_neg.cget("state")), "disabled")
        self.assertEqual(str(app.helper_adj_pos.cget("state")), "normal")
        self.assertEqual(str(app.helper_adj_neg.cget("state")), "normal")
        # Editing the mirror is impossible, so the editor text is authoritative.
        app.prompt_text.delete("1.0", "end")
        app.prompt_text.insert("1.0", "SECOND")
        app._refresh_prompt_helper()
        self.assertEqual(app.helper_editor_pos.get("1.0", "end-1c"), "SECOND")

    def test_adjusted_boxes_do_not_touch_the_editor_json(self) -> None:
        app = self.app
        before_json = app.editor_text.get("1.0", "end")
        before_pos = app.prompt_text.get("1.0", "end")
        app.helper_adj_pos.insert("1.0", "ADJUSTED ONLY POSITIVE")
        app.helper_adj_neg.insert("1.0", "ADJUSTED ONLY NEGATIVE")
        app.update_idletasks()
        self.assertEqual(app.editor_text.get("1.0", "end"), before_json)
        self.assertEqual(app.prompt_text.get("1.0", "end"), before_pos)
        self.assertIn("ADJUSTED ONLY POSITIVE", app.helper_adj_pos.get("1.0", "end"))
        # The helper's inputs are exactly the context pieces.
        inputs = app._helper_inputs()
        self.assertEqual(
            sorted(inputs),
            [
                "adjusted_negative",
                "adjusted_positive",
                "editor_negative",
                "editor_positive",
                "issue",
                "request_json",
            ],
        )
        self.assertIn("ADJUSTED ONLY NEGATIVE", inputs["adjusted_negative"])
        self.assertEqual(inputs["request_json"], before_json.strip())

    def test_help_writes_the_reply_into_the_adjusted_boxes(self) -> None:
        from salad_studio import ai_helper, ref_check

        app = self.app
        self.tokens.write_token("deepseek", "ds-app-test-key")
        app.prompt_text.delete("1.0", "end")
        app.prompt_text.insert("1.0", "EDITOR POS MARKER")
        app.helper_adj_pos.delete("1.0", "end")
        app.helper_adj_pos.insert("1.0", "ADJ POS MARKER")
        app.helper_adj_neg.insert("1.0", "ADJ NEG MARKER")
        seen: dict = {}

        def fake_send(request, timeout):
            seen["request"] = request
            return 200, json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"positive": "NEW POSITIVE", "negative": "NEW NEGATIVE"}'
                            }
                        }
                    ]
                }
            ).encode()

        with mock.patch.object(ai_helper, "_http_send", side_effect=fake_send), mock.patch.object(
            ref_check, "online_lookup", return_value=None
        ), mock.patch("salad_studio.app.threading.Thread", self._inline_thread()):
            app._on_prompt_help()
            self.assertTrue(self._pump(lambda: not app._helper_busy))

        self.assertFalse(app._helper_busy)
        self.assertEqual(app.helper_adj_pos.get("1.0", "end-1c"), "NEW POSITIVE")
        self.assertEqual(app.helper_adj_neg.get("1.0", "end-1c"), "NEW NEGATIVE")
        self.assertIn("NEW POSITIVE", app.helper_reply.get("1.0", "end"))
        self.assertIn("updated", app.helper_state.get())

        # The real request carried the stored key and all five inputs.
        request = seen["request"]
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer ds-app-test-key")
        context = json.loads(request.data.decode())["messages"][1]["content"]
        for needle in (
            "EDITOR POS MARKER",
            "ADJ POS MARKER",
            "ADJ NEG MARKER",
            "LoraLoader",
        ):
            self.assertIn(needle, context)

    def test_unparsable_reply_surfaces_the_raw_text_and_keeps_the_boxes(self) -> None:
        from salad_studio import ai_helper, ref_check

        app = self.app
        self.tokens.write_token("deepseek", "ds-app-test-key")
        app.helper_adj_pos.delete("1.0", "end")
        app.helper_adj_pos.insert("1.0", "KEEP ME")

        def fake_send(request, timeout):
            return 200, json.dumps(
                {"choices": [{"message": {"content": "I cannot help with that."}}]}
            ).encode()

        with mock.patch.object(ai_helper, "_http_send", side_effect=fake_send), mock.patch.object(
            ref_check, "online_lookup", return_value=None
        ), mock.patch("salad_studio.app.threading.Thread", self._inline_thread()):
            app._on_prompt_help()
            self.assertTrue(self._pump(lambda: not app._helper_busy))

        self.assertIn("cannot help", app.helper_reply.get("1.0", "end"))
        self.assertIn("not usable", app.helper_state.get())
        self.assertEqual(app.helper_adj_pos.get("1.0", "end-1c"), "KEEP ME")

    def test_help_without_a_key_explains_itself(self) -> None:
        app = self.app
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            app._on_prompt_help()
        self.assertIn("No DeepSeek key", app.helper_state.get())
        self.assertIn("Tokens tab", app.helper_reply.get("1.0", "end"))
        self.assertFalse(app._helper_busy)

    def test_failed_call_is_reported_in_the_page(self) -> None:
        from salad_studio import ai_helper, ref_check

        app = self.app
        self.tokens.write_token("deepseek", "ds-app-test-key")

        def boom(request, timeout):
            raise ai_helper.AiError("DeepSeek HTTP 402: Insufficient Balance")

        with mock.patch.object(ai_helper, "_http_send", side_effect=boom), mock.patch.object(
            ref_check, "online_lookup", return_value=None
        ), mock.patch("salad_studio.app.threading.Thread", self._inline_thread()):
            app._on_prompt_help()
            self.assertTrue(self._pump(lambda: not app._helper_busy))
        self.assertIn("402", app.helper_reply.get("1.0", "end"))
        self.assertIn("failed", app.helper_state.get())

    # --- config split ----------------------------------------------------
    def test_config_holds_only_profile_and_gateway(self) -> None:
        app = self.app
        self.assertTrue(self._descends_from(app.profile_combo, app._config))
        entries = [
            w for w in self._all_widgets(app._config) if isinstance(w, ttk.Entry)
        ]
        self.assertTrue(
            any(str(w.cget("textvariable")) == str(app.var_gateway) for w in entries),
            "the gateway entry must live on Config",
        )
        for widget in (
            app.graph_combo,
            app.sched_combo,
            app.unet_combo,
            app._lora_inner,
        ):
            self.assertFalse(
                self._descends_from(widget, app._config),
                "prompt settings must not stay on Config",
            )
        buttons = self._buttons(app._config)
        self.assertIn("Save profile", buttons)
        self.assertIn("Delete profile", buttons)
        self.assertNotIn("Check Salad status", buttons)

    # --- unet routing ----------------------------------------------------
    @staticmethod
    def _graph_with_unet(unet: str) -> dict:
        return {
            "prompt": {
                "70": {
                    "class_type": "UNETLoader",
                    "inputs": {"unet_name": unet, "weight_dtype": "default"},
                },
                "9": {
                    "class_type": "SaveImage",
                    "inputs": {"filename_prefix": "x", "images": ["65", 0]},
                },
            },
            "convert_output": {"format": "jpeg"},
        }

    def _generate_gateway(
        self, graph: dict, gateway: str, *, word: str = "Ready"
    ) -> str:
        """Drive a real _on_generate for `graph` with the form pointing at `gateway`.

        Returns the gateway the render was actually POSTed to. The status probe
        is stubbed to a snapshot consistent with ``word``, and a refusal dialog
        is recorded in ``self.refusals`` instead of opening (a modal in a test
        hangs the run).
        """
        from salad_studio import app as app_mod

        app = self.app
        self.tokens.write_token("salad", "salad-test-key-1234")
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", json.dumps(graph))
        app._rebuild_from_json()  # rewrites var_unet from the graph, as the UI does
        app.var_gateway.set(gateway)
        app.var_salad_status.set(word)
        seen: dict = {}
        self.refusals = []

        def fake_generate(**kwargs):
            seen.update(kwargs)
            raise RuntimeError("routing check only")

        with mock.patch.object(
            app_mod.generator, "generate_from_payload", side_effect=fake_generate
        ), mock.patch.object(
            app_mod.salad_status, "snapshot_gateway", side_effect=self._snapshot_for(word)
        ), mock.patch.object(app_mod.messagebox, "showerror"), mock.patch.object(
            app_mod.messagebox, "showinfo", lambda *a, **k: self.refusals.append(str(a))
        ), mock.patch("salad_studio.app.threading.Thread", self._inline_thread()):
            app._on_generate()
            self.assertTrue(self._pump(lambda: not app._busy))
        return str(seen.get("gateway") or "")

    @staticmethod
    def _snapshot_for(word: str):
        """The probe answer that goes with a badge word."""
        if word in ("Down", "Failed"):
            return lambda _gw, _key: {
                "word": word,
                "error": "probe failed",
                "group": {"status": "failed" if word == "Failed" else "running"},
                "instances": [],
            }
        if word == "Stopped":
            return lambda _gw, _key: {"word": "Stopped", "group": {"status": "stopped"}}
        if word:
            return lambda _gw, _key: {"word": word, "group": {"status": "running"}}
        return lambda _gw, _key: {"error": "offline"}

    def test_generate_dispatches_when_the_status_word_is_not_ready(self) -> None:
        """A booting or unprobed replica is dispatched, and the wait covers the boot.

        The press refuses only what cannot render at all (a gone replica, and a
        group the badge says is stopped — the test below pins both). A container
        that is still coming up is dispatched: the queue reads the group's state
        again and the generator waits for its /ready.
        """
        from salad_studio import profiles

        app = self.app
        self.tokens.write_token("salad", "salad-test-key-1234")
        klein = profiles.load_all()["klein"]
        for word in ("", "Starting", "Allocating", "Creating", "Downloading 33%"):
            with self.subTest(word=word):
                app.log_text.delete("1.0", "end")
                used = self._generate_gateway(
                    self._graph_with_unet(klein.primary_checkpoint),
                    klein.gateway,
                    word=word,
                )
                self.assertEqual(used, klein.gateway, "the request must reach the queue")
                self.assertNotIn(
                    "Generate refused",
                    app.log_text.get("1.0", "end"),
                    f"a {word!r} badge must not be refused",
                )
        self.assertFalse(app._busy)

    def test_generate_refuses_a_stopped_group_at_the_press(self) -> None:
        """C1: the press is the gate for a group the badge says is stopped.

        The queue would refuse it a moment later (this app never starts a
        container), so the press refuses it before anything is queued, and the
        Logs line, the status line and the dialog carry the same sentence.
        """
        from salad_studio import app as app_mod
        from salad_studio import profiles

        app = self.app
        self.tokens.write_token("salad", "salad-test-key-1234")
        klein = profiles.load_all()["klein"]
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert(
            "1.0", json.dumps(self._graph_with_unet(klein.primary_checkpoint))
        )
        app._rebuild_from_json()
        app.var_gateway.set(klein.gateway)
        app.var_salad_status.set("Stopped")
        app._last_snaps = {
            "klein": {"word": "Stopped", "group": {"status": "stopped"}}
        }
        app.log_text.delete("1.0", "end")
        before = len(app.gen_queue.jobs())
        seen: dict = {}

        def fake_generate(**kwargs):
            seen.update(kwargs)
            raise RuntimeError("the press must not have dispatched")

        with mock.patch.object(
            app_mod.generator, "generate_from_payload", side_effect=fake_generate
        ), mock.patch.object(app_mod.messagebox, "showinfo") as info, mock.patch(
            "salad_studio.app.threading.Thread", self._inline_thread()
        ):
            app._on_generate()
            self.assertTrue(self._pump(lambda: not app._busy))

        self.assertFalse(seen, "a stopped group must not be dispatched")
        self.assertEqual(len(app.gen_queue.jobs()), before, "nothing may be queued")
        self.assertTrue(info.called, "the press must say why")
        reason = str(info.call_args[0][1])
        self.assertIn("klein", reason, "the refusal names the profile")
        self.assertIn("is down", reason, "and says the container is down")
        log = app.log_text.get("1.0", "end")
        self.assertIn("Generate refused", log)
        self.assertEqual(
            log.count("is down"),
            1,
            f"the refusal must be logged once, not repeated: {log[-400:]}",
        )
        self.assertIn("Refused:", app.status.get(), "the status line says refused")

    def test_generate_refuses_a_replica_that_is_gone(self) -> None:
        """A down or failed replica is not something a start can fix."""
        from salad_studio import app as app_mod
        from salad_studio import profiles

        app = self.app
        self.tokens.write_token("salad", "salad-test-key-1234")
        klein = profiles.load_all()["klein"]
        for word in ("Down", "Failed"):
            with self.subTest(word=word):
                app.editor_text.delete("1.0", "end")
                app.editor_text.insert(
                    "1.0", json.dumps(self._graph_with_unet(klein.primary_checkpoint))
                )
                app._rebuild_from_json()
                app.var_gateway.set(klein.gateway)
                app.var_salad_status.set(word)
                app.log_text.delete("1.0", "end")
                seen: dict = {}

                def fake_generate(**kwargs):
                    seen.update(kwargs)
                    raise RuntimeError("routing check only")

                with mock.patch.object(
                    app_mod.generator, "generate_from_payload", side_effect=fake_generate
                ), mock.patch.object(
                    app_mod.salad_status,
                    "snapshot_gateway",
                    side_effect=self._snapshot_for(word),
                ), mock.patch.object(app_mod.messagebox, "showinfo") as info, mock.patch.object(
                    app_mod.messagebox, "showerror"
                ), mock.patch(
                    "salad_studio.app.threading.Thread", self._inline_thread()
                ):
                    app._on_generate()
                    self.assertTrue(self._pump(lambda: not app._busy))
                self.assertFalse(seen, "a gone replica must not be dispatched")
                self.assertTrue(info.called, "and must say why")
                self.assertIn("Generate refused", app.log_text.get("1.0", "end"))

    def test_generate_routes_a_snofs_graph_off_the_klein_group(self) -> None:
        """Routing must read the GATEWAY's family, not the form's unet.

        Loading a JSON into the editor rewrites var_unet from the graph, so
        comparing the graph's family to the form's unet compares the graph with
        itself and never fires, which is how a SNOFS graph was rendered on the
        klein group.
        """
        from salad_studio import profiles

        allp = profiles.load_all()
        klein, snofs = allp["klein"], allp["klein5090"]
        self.assertNotEqual(klein.gateway, snofs.gateway)
        self.assertEqual(profiles.checkpoint_family(klein.primary_checkpoint), "klein")
        self.assertEqual(profiles.checkpoint_family(snofs.primary_checkpoint), "snofs")

        used = self._generate_gateway(
            self._graph_with_unet(rj.UNET_SNOFS), klein.gateway
        )
        self.assertEqual(used, snofs.gateway)

    def test_generate_keeps_a_klein_graph_on_the_klein_group(self) -> None:
        from salad_studio import profiles

        klein = profiles.load_all()["klein"]
        used = self._generate_gateway(self._graph_with_unet(klein.primary_checkpoint), klein.gateway)
        self.assertEqual(used, klein.gateway)

    # --- Generate: pressable while queued, and the duplicate guard -------
    def _press_that_queues(
        self, graph: dict, gateway: str, *, word: str = "Starting"
    ) -> dict:
        """Drive a real _on_generate whose generator stand-in queues the request.

        The stand-in takes the generator's place at the transport seam: it
        enqueues the request the app handed it, carrying the app's own checksum,
        and leaves it in the queue, so a following press meets the shipped
        duplicate guard. Returns the kwargs the press handed down.
        """
        from salad_studio import app as app_mod
        from salad_studio import salad_queue as q

        app = self.app
        self.tokens.write_token("salad", "salad-test-key-1234")
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", json.dumps(graph))
        app._rebuild_from_json()
        app.var_gateway.set(gateway)
        app.var_salad_status.set(word)
        seen: dict = {}
        self.refusals = []

        def fake_generate(**kwargs):
            seen.update(kwargs)
            job = app.gen_queue.enqueue(
                kwargs.get("payload") or {},
                lambda _job: q.Attempt(status=200, accepted=True),
                line=str(kwargs.get("line") or ""),
                checksum=str(kwargs.get("checksum") or ""),
            )
            return Path(self.tmp) / f"plate-{job.id}.jpg"

        with mock.patch.object(
            app_mod.generator, "generate_from_payload", side_effect=fake_generate
        ), mock.patch.object(
            app_mod.salad_status, "snapshot_gateway", side_effect=self._snapshot_for(word)
        ), mock.patch.object(app_mod.messagebox, "showerror"), mock.patch.object(
            app_mod.messagebox, "showinfo", lambda *a, **k: self.refusals.append(str(a))
        ), mock.patch("salad_studio.app.threading.Thread", self._inline_thread()):
            app._on_generate()
            self.assertTrue(self._pump(lambda: not app._busy))
        return seen

    @staticmethod
    def _variant(graph: dict, prefix: str) -> dict:
        """The same graph with a different SaveImage prefix: a different request."""
        other = json.loads(json.dumps(graph))
        other["prompt"]["9"]["inputs"]["filename_prefix"] = prefix
        return other

    def test_generate_stays_pressable_while_a_request_is_queued(self) -> None:
        """A request in the queue must not disable Generate; the press queues behind.

        The button is no longer the gate: the press decides, and a press that can
        be dispatched adds a request that waits behind the one already queued.
        """
        from salad_studio import profiles
        from salad_studio import salad_queue as q

        app = self.app
        klein = profiles.load_all()["klein"]
        app.gen_queue.enqueue(
            {"gateway": klein.gateway, "profile": "klein"},
            lambda _job: q.Attempt(status=200, accepted=True),
            line="klein",
            checksum="a-different-request",
        )
        app.var_salad_status.set("Starting")  # the routed container is not Ready
        self.assertEqual(str(app.gen_btn.cget("state")), "normal")

        seen = self._press_that_queues(
            self._graph_with_unet(klein.primary_checkpoint), klein.gateway
        )
        self.assertEqual(seen.get("gateway"), klein.gateway, "the press must dispatch")
        self.assertEqual(len(app.gen_queue.jobs()), 2, "it queues behind the first")
        self.assertEqual(str(app.gen_btn.cget("state")), "normal", "still live afterwards")
        self.assertNotIn("Generate refused", app.log_text.get("1.0", "end"))

    def test_a_repeat_of_the_heads_request_is_not_queued(self) -> None:
        """A repeat of the queue's head adds nothing; behind another it is allowed."""
        from salad_studio import profiles

        app = self.app
        klein = profiles.load_all()["klein"]
        graph = self._graph_with_unet(klein.primary_checkpoint)
        self._press_that_queues(graph, klein.gateway)
        jobs = app.gen_queue.jobs()
        self.assertEqual(len(jobs), 1)
        head = jobs[0]
        self.assertEqual(head.state, "pending")

        app.log_text.delete("1.0", "end")
        self._press_that_queues(graph, klein.gateway)  # the same request again
        self.assertEqual(len(app.gen_queue.jobs()), 1, "the identical press added a job")
        shown = app.log_text.get("1.0", "end")
        self.assertIn(f"request {head.id}", shown, "the report must name the queue's head")
        self.assertIn("already queued", shown)

        # The identical request stops being the head: another request takes it.
        app.gen_queue.cancel(head)
        self._press_that_queues(self._variant(graph, "another-plate"), klein.gateway)
        self.assertEqual(len(app.gen_queue.jobs()), 2)
        self._press_that_queues(graph, klein.gateway)
        jobs = app.gen_queue.jobs()
        self.assertEqual(
            len(jobs), 3, "an identical request that is not the head is allowed"
        )
        self.assertEqual(jobs[2].checksum, head.checksum, "and it is the same request")

    def test_generate_leaves_an_unknown_gateway_alone(self) -> None:
        """Only the groups we know are policed; a hand-typed gateway is the user's."""
        from salad_studio import profiles

        custom = "https://custom.example.test/gateway"
        used = self._generate_gateway(
            self._graph_with_unet(rj.UNET_SNOFS), custom
        )
        self.assertEqual(used, custom)

    def test_a_failed_generate_reprobes_the_replica_status(self) -> None:
        """A render that dies mid-job must not leave the cached Ready word standing.

        Re-applying the cached word is what let the app keep reporting a container
        that had already gone away as up.
        """
        from salad_studio import app as app_mod
        from salad_studio import profiles

        app = self.app
        self.tokens.write_token("salad", "salad-test-key-1234")
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", json.dumps(self._graph_with_unet(rj.UNET_SNOFS)))
        app._rebuild_from_json()
        app.var_salad_status.set("Ready")

        def boom(**_kwargs):
            raise RuntimeError("524 origin timed out")

        with mock.patch.object(
            app_mod.generator, "generate_from_payload", side_effect=boom
        ), mock.patch.object(app_mod.messagebox, "showerror"), mock.patch.object(
            app_mod.SaladStudio, "_check_salad_status"
        ) as probe, mock.patch(
            "salad_studio.app.threading.Thread", self._inline_thread()
        ):
            app._on_generate()
            self.assertTrue(self._pump(lambda: not app._busy))
        self.assertTrue(probe.called, "a failed render must re-probe, not trust the cache")

    def test_prompt_settings_holds_the_prompt_knobs(self) -> None:
        app = self.app
        for widget in (app.graph_combo, app.sched_combo, app.unet_combo, app._lora_inner):
            self.assertTrue(
                self._descends_from(widget, app._settings),
                "the prompt knobs must live on Prompt Settings",
            )
        vars_on_page = {
            str(w.cget("textvariable"))
            for w in self._all_widgets(app._settings)
            if isinstance(w, ttk.Entry)
        }
        for var in (app.var_width, app.var_height, app.var_steps, app.var_cfg, app.var_seed):
            self.assertIn(str(var), vars_on_page)
        self.assertFalse(self._descends_from(app.profile_combo, app._settings))

    # --- action bar ------------------------------------------------------
    def test_the_status_strip_is_right_aligned_in_the_action_bar(self) -> None:
        """One compact strip in the cluster's place: three dot+count segments."""
        from salad_studio import salad_status

        app = self.app
        holder = app._replica_holder
        self.assertIs(holder.master, app._action_bar)
        self.assertEqual(str(holder.pack_info().get("side")), "right")
        strip = app._strip
        self.assertTrue(self._descends_from(strip, holder))
        self.assertEqual(len(app._strip_dots), 3)
        self.assertEqual(len(app._strip_vars), 3)
        for dot, var in zip(app._strip_dots, app._strip_vars):
            self.assertTrue(self._descends_from(dot, strip))
            self.assertTrue(self._descends_from(self._label_with_var(strip, var), strip))

        colors = [str(dot.cget("fg")) for dot in app._strip_dots]
        self.assertEqual(len(set(colors)), 3, f"three distinct dot colours: {colors}")
        self.assertEqual(colors[0], salad_status.WORD_COLORS["Ready"])
        self.assertEqual(colors[1], salad_status.WORD_COLORS["Creating"])
        self.assertEqual(colors[2], salad_status.WORD_COLORS["Failed"])
        green, amber, red = (self._rgb(c) for c in colors)
        self.assertTrue(green[1] > green[0] and green[1] > green[2], f"green: {green}")
        self.assertTrue(amber[0] > amber[1] > amber[2], f"amber: {amber}")
        self.assertTrue(red[0] > red[1] and red[0] > red[2], f"red: {red}")

        self.assertIn("Check Salad status", self._buttons(holder))
        # Generate / Clean gallery / the live state stay on the left.
        self.assertEqual(str(app.gen_btn.pack_info().get("side")), "left")
        self.assertEqual(str(app.gen_state_lbl.pack_info().get("side")), "left")
        self.assertFalse(self._descends_from(holder, app._config))

        # The removed detail: no per-profile word or detail row, and no
        # aggregate status word label anywhere in the bar.
        self.assertFalse(hasattr(app, "_replica_vars"), "per-profile badges are gone")
        self.assertFalse(hasattr(app, "salad_status_lbl"), "the word label is gone")
        shown = " ".join(self._widget_text(w) for w in self._all_widgets(app._action_bar))
        for gone in (
            "klein",
            "klein5090",
            "Ready",
            "Stopped",
            "Starting",
            "Down",
            "Unknown",
        ):
            self.assertNotIn(gone, shown, f"the action bar still shows {gone!r}")

    def test_the_strip_counts_the_containers_the_probe_finds(self) -> None:
        """The shipped probe-fill path writes the three counts, in this order.

        Two different snapshot sets go through the same window, so a constant
        cannot pass: profile klein ready + klein5090 stopped reads 1|0|1, then
        klein creating + klein5090 ready reads 1|1|0.
        """
        from salad_studio import app as app_mod

        app = self.app
        self.tokens.write_token("salad", "salad-test-key-1234")
        targets = dict(app._status_targets())
        self.assertEqual(sorted(targets), ["klein", "klein5090"])

        sets = (
            (
                {
                    targets["klein"]: self._snap(1, [{"state": "running", "ready": True}]),
                    targets["klein5090"]: self._snap(1, []),
                },
                "●1|●0|●1",
            ),
            (
                {
                    targets["klein"]: self._snap(1, [{"state": "creating", "ready": False}]),
                    targets["klein5090"]: self._snap(1, [{"state": "running", "ready": True}]),
                },
                "●1|●1|●0",
            ),
        )
        for snaps, want in sets:
            with self.subTest(want=want):
                probe = mock.patch.object(
                    app_mod.salad_status,
                    "snapshot_gateway",
                    side_effect=lambda gw, _key, _s=snaps: _s[gw],
                )
                # The probe's worker posts its fill through after(0, done), which
                # Tk refuses from a thread without a main loop; run it inline and
                # pump, the way the rest of this module drives the app's workers.
                with probe, mock.patch(
                    "salad_studio.app.threading.Thread", self._inline_thread()
                ):
                    app._check_salad_status()
                    self.assertTrue(
                        self._pump(lambda: self._strip_text(app) == want),
                        f"strip reads {self._strip_text(app)!r}, want {want!r}",
                    )
                self.assertEqual(self._strip_text(app), want)

        # The dots beside those numbers: green ready, amber starting, red not
        # started, three distinct colours on the three segments.
        from salad_studio import salad_status

        colors = [str(dot.cget("fg")) for dot in app._strip_dots]
        self.assertEqual(len(set(colors)), 3, f"three distinct dot colours: {colors}")
        self.assertEqual(colors[0], salad_status.WORD_COLORS["Ready"])
        self.assertEqual(colors[1], salad_status.WORD_COLORS["Creating"])
        self.assertEqual(colors[2], salad_status.WORD_COLORS["Failed"])

    def test_status_word_still_reaches_the_dispatch_decision(self) -> None:
        """The strip shows counts; the word is still what a press reads."""
        app = self.app
        for word in ("Ready", "Down", "Stopped"):
            with self.subTest(word=word):
                app._set_salad_word(word)
                self.assertEqual(app.var_salad_status.get(), word)
                self.assertEqual(str(app.gen_btn.cget("state")), "normal")

    # --- tokens page -----------------------------------------------------
    def test_tokens_page_has_no_fal_slot_and_shows_indicators(self) -> None:
        app = self.app
        boxes = [
            str(w.cget("text"))
            for w in self._all_widgets(app._tokens)
            if isinstance(w, ttk.LabelFrame)
        ]
        self.assertNotIn("fal.ai", boxes)
        self.assertEqual(
            boxes, ["Salad API", "Hugging Face", "Civitai", "DeepSeek", "Vast.ai"]
        )
        self.assertEqual(
            list(app._token_entry),
            ["salad", "huggingface", "civitai", "deepseek", "vast"],
        )
        for kind in app._token_entry:
            with self.subTest(kind=kind):
                self.assertIn(kind, app._token_valid_dot)
                self.assertTrue(self._descends_from(app._token_valid_dot[kind], app._tokens))
                self.assertIn(kind, app._token_valid_word)

    def test_indicator_colour_comes_from_the_probe_state(self) -> None:
        from salad_studio import theme

        app = self.app
        for state, key in (
            ("valid", "valid"),
            ("invalid", "invalid"),
            ("unknown", "unknown"),
            ("unchecked", "unknown"),
        ):
            with self.subTest(state=state):
                app._token_state["salad"] = state
                app._token_detail["salad"] = "HTTP 200"
                app._render_token_state("salad")
                self.assertEqual(
                    str(app._token_valid_dot["salad"].cget("fg")), theme.PALETTE[key]
                )

    def test_check_keys_renders_the_probe_result(self) -> None:
        from salad_studio import theme

        app = self.app
        self.tokens.write_token("salad", "salad-key-for-probe")
        with mock.patch.object(
            self.tokens, "_http_send", return_value=(200, b"{}")
        ), mock.patch("salad_studio.app.threading.Thread", self._inline_thread()):
            app._probe_tokens(["salad"])
            self.assertTrue(self._pump(lambda: not app._token_probe_busy))
        self.assertEqual(app._token_state["salad"], "valid")
        self.assertEqual(
            str(app._token_valid_dot["salad"].cget("fg")), theme.PALETTE["valid"]
        )
        with mock.patch.object(
            self.tokens, "_http_send", return_value=(401, b"{}")
        ), mock.patch("salad_studio.app.threading.Thread", self._inline_thread()):
            app._probe_tokens(["salad"])
            self.assertTrue(self._pump(lambda: not app._token_probe_busy))
        self.assertEqual(app._token_state["salad"], "invalid")
        self.assertEqual(
            str(app._token_valid_dot["salad"].cget("fg")), theme.PALETTE["invalid"]
        )
        with mock.patch.object(
            self.tokens, "_http_send", side_effect=OSError("offline")
        ), mock.patch("salad_studio.app.threading.Thread", self._inline_thread()):
            app._probe_tokens(["salad"])
            self.assertTrue(self._pump(lambda: not app._token_probe_busy))
        self.assertEqual(app._token_state["salad"], "unknown")
        self.assertEqual(
            str(app._token_valid_dot["salad"].cget("fg")), theme.PALETTE["unknown"]
        )


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class ListSurfacesSayWhenTheyAreEmpty(unittest.TestCase):
    """U1: a list surface says it is empty instead of showing a bare tree.

    The Queue page already did; Prompt History, Prompt Catalog and the history
    strip showed an empty tree or two arrows with nothing to explain them.
    """

    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        from salad_studio import (
            image_deploy,
            lora_store,
            profiles,
            prompt_catalog,
            prompt_history,
            tokens,
            ui_state,
            vast,
        )

        saved = [
            _redirect_store(profiles, "PROFILES_PATH", self.tmp / "studio-profiles.json"),
            _redirect_store(lora_store, "EXTRAS_PATH", self.tmp / "studio-loras.json"),
            _redirect_store(tokens, "LOCAL_PATH", self.tmp / "studio-tokens.json"),
            _redirect_store(tokens, "CONFIG_HOME", self.tmp / "defaults"),
            _redirect_store(
                prompt_catalog, "CATALOG_PATH", self.tmp / "studio-prompt-catalog.json"
            ),
            _redirect_store(
                prompt_history, "HISTORY_PATH", self.tmp / "studio-prompt-history.json"
            ),
            _redirect_store(prompt_history, "THUMBS_DIR", self.tmp / "thumbs"),
            _redirect_store(ui_state, "STATE_PATH", self.tmp / "studio-ui.json"),
            _redirect_store(vast, "INSTANCES_PATH", self.tmp / "studio-vast.json"),
            _redirect_store(
                image_deploy, "SETTINGS_PATH", self.tmp / "studio-images.json"
            ),
        ]
        self.addCleanup(_put_stores_back, saved)
        from salad_studio import app as app_mod

        # The gallery reads the real art tree by default, and this test is about
        # what the surfaces say when they are empty.
        self._old_out = app_mod.OUT_DIR
        self._old_art = app_mod.ART
        app_mod.OUT_DIR = self.tmp / "gallery"
        app_mod.ART = self.tmp / "art"
        app_mod.OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.addCleanup(setattr, app_mod, "OUT_DIR", self._old_out)
        self.addCleanup(setattr, app_mod, "ART", self._old_art)
        self.app_mod = app_mod
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.app.update_idletasks()

    def _strip_empty_text(self) -> str:
        canvas = self.app.strip.canvas
        items = canvas.find_withtag("empty")
        self.assertEqual(len(items), 1, "the strip must carry exactly one empty-state line")
        return str(canvas.itemcget(items[0], "text")).strip()

    def test_every_list_surface_states_that_it_is_empty(self) -> None:
        app = self.app
        for name, widget in (
            ("Queue", app.queue_empty_lbl),
            ("Prompt History", app.prompt_hist_empty_lbl),
            ("Prompt Catalog", app.catalog_empty_lbl),
        ):
            with self.subTest(surface=name):
                self.assertTrue(
                    str(widget.cget("text")).strip(), f"{name} says nothing about being empty"
                )
                self.assertEqual(
                    widget.winfo_manager(), "grid", f"{name}'s empty state is not shown"
                )
        self.assertTrue(self._strip_empty_text(), "the strip says nothing about being empty")

    def test_rows_hide_the_state_and_emptying_brings_it_back(self) -> None:
        """The state follows the rows, on every surface that has one."""
        app = self.app
        from salad_studio import prompt_catalog, prompt_history

        self.assertEqual(app.prompt_hist_empty_lbl.winfo_manager(), "grid")
        prompt_history.add_prompt("a probe prompt")
        app._refresh_prompt_history()
        self.assertEqual(app.prompt_hist_empty_lbl.winfo_manager(), "", "history state must go")
        prompt_history.remove_at(0)
        app._refresh_prompt_history()
        self.assertEqual(app.prompt_hist_empty_lbl.winfo_manager(), "grid", "and come back")

        self.assertEqual(app.catalog_empty_lbl.winfo_manager(), "grid")
        entry = prompt_catalog.add_entry("probe", "a description", {"prompt": {}})
        app._refresh_prompt_catalog()
        self.assertEqual(app.catalog_empty_lbl.winfo_manager(), "", "catalog state must go")
        prompt_catalog.remove_entry(str(entry["id"]))
        app._refresh_prompt_catalog()
        self.assertEqual(app.catalog_empty_lbl.winfo_manager(), "grid", "and come back")

        plate = self.tmp / "studio_1.jpg"
        plate.write_bytes(b"not really a jpeg")
        app.strip.set_paths([plate])
        self.assertEqual(
            len(app.strip.canvas.find_withtag("empty")), 0, "the strip's state must go"
        )
        app.strip.set_paths([])
        self.assertTrue(self._strip_empty_text(), "and come back")


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class ClosingReportsWhatTkWouldNotTake(unittest.TestCase):
    """C6: `_dropped_afters` has a reader, so a handoff that never ran is visible."""

    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        from salad_studio import (
            image_deploy,
            lora_store,
            profiles,
            prompt_catalog,
            prompt_history,
            tokens,
            ui_state,
            vast,
        )

        saved = [
            _redirect_store(profiles, "PROFILES_PATH", self.tmp / "studio-profiles.json"),
            _redirect_store(lora_store, "EXTRAS_PATH", self.tmp / "studio-loras.json"),
            _redirect_store(tokens, "LOCAL_PATH", self.tmp / "studio-tokens.json"),
            _redirect_store(tokens, "CONFIG_HOME", self.tmp / "defaults"),
            _redirect_store(
                prompt_catalog, "CATALOG_PATH", self.tmp / "studio-prompt-catalog.json"
            ),
            _redirect_store(
                prompt_history, "HISTORY_PATH", self.tmp / "studio-prompt-history.json"
            ),
            _redirect_store(prompt_history, "THUMBS_DIR", self.tmp / "thumbs"),
            _redirect_store(ui_state, "STATE_PATH", self.tmp / "studio-ui.json"),
            _redirect_store(vast, "INSTANCES_PATH", self.tmp / "studio-vast.json"),
            _redirect_store(
                image_deploy, "SETTINGS_PATH", self.tmp / "studio-images.json"
            ),
        ]
        self.addCleanup(_put_stores_back, saved)
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.app.update_idletasks()

    def _close_and_read(self) -> str:
        """Run the real close handler, holding the window open to read the log."""
        app = self.app
        app.log_text.delete("1.0", "end")
        with mock.patch.object(app, "destroy"):
            app._on_close()
        return app.log_text.get("1.0", "end")

    def test_a_dropped_callback_is_reported_when_the_window_closes(self) -> None:
        self.app._dropped_afters.append("after(0): the main thread is not in the Tk loop")
        log = self._close_and_read()
        self.assertIn("dropped", log, f"the drop must be reported: {log[-300:]}")
        self.assertIn("not in the Tk loop", log)

    def test_the_recorder_records_a_drop_the_loop_would_not_take(self) -> None:
        """Issue 4: the shipped recorder is driven, not an entry a test invents.

        Tk refuses a callback scheduled from a worker thread while the main
        thread is not in the loop ("main thread is not in main loop"), which is
        exactly the RuntimeError ``_later``/``_later_idle`` catch. Scheduling
        from a real thread therefore drives the shipped recorder: with the
        recording removed, ``_dropped_afters`` stays empty and the report the
        user's log would have carried is never written.
        """
        app = self.app
        self.assertEqual(app._dropped_afters, [], "this drive starts with a clean record")
        results: list = []

        def worker() -> None:
            # The main thread is blocked in join() below, so it is not in the
            # Tk loop and Tk will not take either of these.
            results.append(app._later(0, lambda: None))
            results.append(app._later_idle(lambda: None))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=30)
        self.assertFalse(thread.is_alive(), "the worker never came back")
        self.assertEqual(results, [None, None], "a refused schedule hands back no id")
        self.assertEqual(
            len(app._dropped_afters),
            2,
            f"both refused callbacks must be recorded: {app._dropped_afters}",
        )
        self.assertTrue(
            all(entry.startswith("after") for entry in app._dropped_afters),
            f"each entry names the schedule that was dropped: {app._dropped_afters}",
        )
        self.assertIn("main thread is not in main loop", app._dropped_afters[0])

        log = self._close_and_read()
        self.assertIn("2 scheduled callback(s) were dropped", log)
        self.assertIn("after_idle", log, "the report carries the last one recorded")

    def test_a_clean_session_reports_nothing(self) -> None:
        self.assertEqual(self.app._dropped_afters, [])
        self.assertNotIn("dropped", self._close_and_read())


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class BothLogPanesMaskSecrets(unittest.TestCase):
    """Issue 1: the container pane and the Studio pane mask the same values."""

    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        from salad_studio import (
            image_deploy,
            lora_store,
            profiles,
            prompt_catalog,
            prompt_history,
            tokens,
            ui_state,
            vast,
        )

        self.tokens = tokens
        saved = [
            _redirect_store(profiles, "PROFILES_PATH", self.tmp / "studio-profiles.json"),
            _redirect_store(lora_store, "EXTRAS_PATH", self.tmp / "studio-loras.json"),
            _redirect_store(tokens, "LOCAL_PATH", self.tmp / "studio-tokens.json"),
            _redirect_store(tokens, "CONFIG_HOME", self.tmp / "defaults"),
            _redirect_store(
                prompt_catalog, "CATALOG_PATH", self.tmp / "studio-prompt-catalog.json"
            ),
            _redirect_store(
                prompt_history, "HISTORY_PATH", self.tmp / "studio-prompt-history.json"
            ),
            _redirect_store(prompt_history, "THUMBS_DIR", self.tmp / "thumbs"),
            _redirect_store(ui_state, "STATE_PATH", self.tmp / "studio-ui.json"),
            _redirect_store(vast, "INSTANCES_PATH", self.tmp / "studio-vast.json"),
            _redirect_store(
                image_deploy, "SETTINGS_PATH", self.tmp / "studio-images.json"
            ),
        ]
        self.addCleanup(_put_stores_back, saved)
        from salad_studio.app import SaladStudio

        self.app = SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.app.update_idletasks()

    def _pane(self, widget) -> str:
        return widget.get("1.0", "end")

    def _container_line(self, text: str) -> None:
        """A container log line: what ``_check_salad_status`` puts in the Salad pane."""
        self.app._set_salad_logs(text)

    def test_a_container_log_line_is_masked_in_both_panes(self) -> None:
        """The same value must not be masked in one pane and clear in the other."""
        secret = "hf_FIRSTSECRETVALUE1234"
        self.tokens.write_token("huggingface", secret)
        line = f"container stdout:\nHF_TOKEN={secret}\nready"
        self._container_line(line)
        self.app.log("info", line)
        self.app.update_idletasks()

        salad = self._pane(self.app.salad_log_text)
        studio = self._pane(self.app.log_text)
        self.assertNotIn(secret, salad, f"the Salad pane leaked the token: {salad!r}")
        self.assertIn("…", salad, "the token is masked, not dropped")
        self.assertNotIn(secret, studio, f"the Studio pane leaked the token: {studio!r}")
        self.assertIn("…", studio)
        self.assertIn("ready", salad, "the rest of the container output is still shown")

    def test_a_token_written_after_the_cache_is_warm_is_masked_too(self) -> None:
        """A token that arrives any other way must not be logged in clear.

        The redaction list is cached, so a write that is not this window's own
        save used to leave the new value out of it: both panes then showed it.
        """
        first = "hf_FIRSTSECRETVALUE1234"
        second = "civitai_SECONDT0KENvalue"
        self.tokens.write_token("huggingface", first)
        self._container_line(f"HF_TOKEN={first}")
        self.app.log("info", f"HF_TOKEN={first}")
        self.app.update_idletasks()

        # A second token, after the list above was read and cached.
        self.tokens.write_token("civitai", second)
        self._container_line(f"civitai token {second}")
        self.app.log("info", f"civitai token {second}")
        self.app.update_idletasks()

        salad = self._pane(self.app.salad_log_text)
        studio = self._pane(self.app.log_text)
        self.assertNotIn(second, salad, f"the Salad pane leaked the new token: {salad!r}")
        self.assertNotIn(second, studio, f"the Studio pane leaked the new token: {studio!r}")
        self.assertIn("…", salad)
        self.assertIn("…", studio)


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class ContentBelowTheFoldIsReachable(unittest.TestCase):
    """Issue 3: at 1366x728 every page fits or scrolls, by wheel and by keyboard."""

    # The pages the issue measured as taller than the notebook with no scrollbar.
    OVER_THE_FOLD = (
        "Prompt Settings",
        "Tokens",
        "LoRAs",
        "Prompt Editor",
        "Prompt Assist",
        "Import",
        "Logs",
    )
    # The controls the issue names as hidden on the Tokens page, which is also
    # where the Vast.ai section tells the user to save that key.
    CONTROL_TYPES = (
        ttk.Button,
        ttk.Entry,
        ttk.Combobox,
        ttk.Label,
        ttk.Checkbutton,
        ttk.Radiobutton,
        ttk.Treeview,
        tk.Text,
        tk.Label,
    )

    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(self._destroy)
        self.app.update_idletasks()

    def _destroy(self) -> None:
        try:
            self.app.destroy()
        except tk.TclError:
            pass

    def _pages(self) -> dict:
        """Each notebook page by the label the notebook shows for it."""
        return {
            str(self.app.nb.tab(tab, "text")): self.app.nb.nametowidget(tab)
            for tab in self.app.nb.tabs()
        }

    def _controls(self, page) -> list:
        out: list = []

        def walk(widget) -> None:
            for child in widget.winfo_children():
                if isinstance(child, self.CONTROL_TYPES):
                    out.append(child)
                walk(child)

        walk(page)
        return out

    def _bottom_in_page(self, widget, page) -> int:
        return int(widget.winfo_rooty()) - int(page.winfo_rooty()) + int(widget.winfo_height())

    def _page_scroller(self, widget, page):
        """The page's own scroll canvas above ``widget``, or None."""
        canvases = set(self.app._scroll_canvases.values())
        node = getattr(widget, "master", None)
        while node is not None and node is not page:
            if node in canvases:
                return node
            node = getattr(node, "master", None)
        return None

    def _map_at_1366x728(self) -> None:
        app = self.app
        app.geometry("1366x728")
        app.deiconify()
        deadline = time.time() + 10.0
        while time.time() < deadline:
            app.update()
            if app.winfo_width() > 100 and app.winfo_height() > 100:
                break
            time.sleep(0.02)
        app.update_idletasks()

    def test_every_page_fits_or_scrolls_at_1366x728(self) -> None:
        """The measured page set: nothing may sit below the fold unreachable.

        The window is laid out at 1366x728, the size the issue measured, and the
        notebook it leaves is the height every page has to live in. A control
        that lands past the page's bottom edge is only allowed when the page's
        own scroll canvas can bring it into view.
        """
        app = self.app
        self._map_at_1366x728()
        notebook_height = int(app.nb.winfo_height())
        self.assertGreater(notebook_height, 1, "the window must be laid out to measure it")
        pages = self._pages()
        self.assertEqual(
            tuple(pages),
            self.app_mod.TAB_ORDER,
            "every page the notebook shows is measured, in the order it shows them",
        )
        for name, page in pages.items():
            app._goto_tab(name)
            app.update()
            scroller = app._scroll_canvases.get(page)
            content = app._scroll_bodies.get(page, page)
            if scroller is not None:
                bbox = scroller.bbox("all")
                self.assertIsNotNone(bbox, f"{name} scrolls but has no scroll region")
                self.assertGreaterEqual(
                    int(bbox[3]),
                    content.winfo_reqheight(),
                    f"{name}'s scroll region must cover all of its content",
                )
            for control in self._controls(page):
                if self._bottom_in_page(control, page) <= int(page.winfo_height()) + 1:
                    continue
                self.assertIsNotNone(
                    self._page_scroller(control, page),
                    f"{name} needs {content.winfo_reqheight()} px in a "
                    f"{notebook_height} px notebook, and {control} is below the fold "
                    "with nothing to scroll it",
                )
        for name in self.OVER_THE_FOLD:
            with self.subTest(page=name):
                self.assertIn(name, pages, "the page set changed")
                self.assertIn(
                    pages[name],
                    app._scroll_canvases,
                    f"{name} holds more than a window and must scroll",
                )

    def test_the_tokens_page_reaches_the_vast_key_box_and_check_keys_bar(self) -> None:
        """The two controls the issue names: hidden, and the section says to use them."""
        app = self.app
        self._map_at_1366x728()
        pages = self._pages()
        tokens_page = pages["Tokens"]
        app._goto_tab("Tokens")
        app.update()
        canvas = app._scroll_canvases[tokens_page]
        canvas.yview_moveto(1.0)
        app.update()
        self.assertEqual(
            round(canvas.yview()[1], 3), 1.0, "the page must scroll all the way down"
        )
        key_box = app._token_widgets["vast"]
        check_keys = next(
            w
            for w in self._controls(tokens_page)
            if isinstance(w, ttk.Button) and str(w.cget("text")) == "Check keys"
        )
        for control in (key_box, check_keys):
            with self.subTest(control=str(control)):
                self.assertLessEqual(
                    self._bottom_in_page(control, tokens_page),
                    int(tokens_page.winfo_height()) + 1,
                    "scrolled to the bottom, this control is on screen",
                )

    def test_the_wheel_scrolls_the_page_the_pointer_is_on(self) -> None:
        """One handler serves every page, and a page scrolls only while claimed."""
        app = self.app
        pages = self._pages()
        tokens_page = pages["Tokens"]
        canvas = app._scroll_canvases[tokens_page]
        canvas.configure(yscrollincrement=40, scrollregion=(0, 0, 900, 4000))
        app.update_idletasks()

        app._on_page_wheel(type("E", (), {"delta": -120})())
        app.update_idletasks()
        self.assertEqual(
            canvas.yview()[0], 0.0, "no page has claimed the wheel, so nothing moves"
        )

        app._claim_wheel(tokens_page)
        app._on_page_wheel(type("E", (), {"delta": -120})())
        app.update_idletasks()
        self.assertAlmostEqual(
            canvas.yview()[0], 40 / 4000, places=4, msg="one notch is one unit"
        )
        self.assertEqual(
            app._scroll_canvases[app._config_section_pages["images"]].yview()[0],
            0.0,
            "and the Config Images section, which the pointer is not on, stays put",
        )

        app._release_wheel(tokens_page)
        app._on_page_wheel(type("E", (), {"delta": -120})())
        app.update_idletasks()
        self.assertAlmostEqual(
            canvas.yview()[0], 40 / 4000, places=4, msg="handing the wheel back stops it"
        )

    def test_a_control_that_takes_focus_scrolls_its_page_into_view(self) -> None:
        """The keyboard must reach what the wheel can: focus scrolls the page."""
        app = self.app
        pages = self._pages()
        tokens_page = pages["Tokens"]
        canvas = app._scroll_canvases[tokens_page]
        canvas.configure(scrollregion=(0, 0, 900, 800))
        app.update_idletasks()
        key_box = app._token_widgets["vast"]
        # A real viewport and a control below the fold, without mapping the
        # window: an unmapped window is one pixel tall, so the geometry the
        # reveal maths reads is supplied.
        with mock.patch.object(canvas, "winfo_height", return_value=476), mock.patch.object(
            canvas, "winfo_rooty", return_value=100
        ), mock.patch.object(key_box, "winfo_rooty", return_value=100 + 520), mock.patch.object(
            key_box, "winfo_height", return_value=30
        ):
            app._on_page_focus(type("E", (), {"widget": key_box})())
        app.update_idletasks()
        self.assertGreater(
            canvas.yview()[0], 0.0, "the page must scroll to the control that took focus"
        )
        self.assertLessEqual(
            canvas.yview()[1], 1.0, "and never scroll past the end of the page"
        )

        # A control on a page that does not scroll is left alone.
        before = canvas.yview()[0]
        with mock.patch.object(canvas, "winfo_height", return_value=476), mock.patch.object(
            canvas, "winfo_rooty", return_value=100
        ), mock.patch.object(key_box, "winfo_rooty", return_value=100 + 10), mock.patch.object(
            key_box, "winfo_height", return_value=30
        ):
            app._on_page_focus(type("E", (), {"widget": key_box})())
        app.update_idletasks()
        self.assertLessEqual(
            canvas.yview()[0], before, "a control already in view moves nothing"
        )

    def test_a_focus_event_on_the_page_body_does_not_scroll_it(self) -> None:
        """Tk fires FocusIn on every ancestor; only the control may be revealed.

        Revealing the body frame scrolls its bottom edge into view, which is the
        Rent a machine panel below the instance list on the Vast.ai page.
        """
        app = self.app
        page = app._config_section_pages["vast"]
        body = app._scroll_bodies[page]
        with mock.patch.object(app, "_reveal") as reveal:
            app._on_page_focus(type("E", (), {"widget": body})())
        self.assertFalse(
            reveal.called, "the page body is a container, not a control taking focus"
        )

    # -- the sideways scroll -----------------
    # The lines that pass added, as (shipped text, what it replaced) pairs, so
    # the old vertical-only helper and reveal can be rebuilt from this file.
    PAGE_HELPER_EDITS = (
        (
            "    canvas.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)\n",
            "    canvas.configure(yscrollcommand=vscroll.set)\n",
        ),
        (
            '    hscroll = ttk.Scrollbar(holder, orient="horizontal", command=canvas.xview)\n',
            "",
        ),
        ('    hscroll.grid(row=1, column=0, sticky="ew")\n', ""),
        (
            "            width=max(body.winfo_reqwidth(), e.width),\n",
            "            width=e.width,\n",
        ),
    )
    REVEAL_EDITS = (
        (
            (
                "        width = int(canvas.winfo_width())\n"
                "        total_w = int(bbox[2])\n"
                "        left = int(canvas.xview()[0] * total_w)\n"
                "        x = int(widget.winfo_rootx()) - int(canvas.winfo_rootx()) + left\n"
                "        right = x + int(widget.winfo_width())\n"
            ),
            "",
        ),
        (
            (
                "    else:\n"
                "        target = None\n"
                "    if target is not None:\n"
                "        target = max(0, min(target, max(0, total - height)))\n"
                '        canvas.yview_moveto(target / total if total else 0.0)\n'
                "    if right > left + width:\n"
                "        target_w = right - width\n"
                "    elif x < left:\n"
                "        target_w = x\n"
                "    else:\n"
                "        target_w = None\n"
                "    if target_w is not None:\n"
                "        target_w = max(0, min(target_w, max(0, total_w - width)))\n"
                "        canvas.xview_moveto(target_w / total_w if total_w else 0.0)\n"
            ),
            (
                "    else:\n"
                "        return\n"
                "    target = max(0, min(target, max(0, total - height)))\n"
                '    canvas.yview_moveto(target / total if total else 0.0)\n'
            ),
        ),
    )

    def _layout_at(self, app, size: str) -> None:
        """Lay ``app`` out at a requested size and let Tk settle the geometry."""
        app.geometry(size)
        app.deiconify()
        deadline = time.time() + 10.0
        while time.time() < deadline:
            app.update()
            if app.winfo_width() > 100 and app.winfo_height() > 100:
                break
            time.sleep(0.02)
        # The Map handler re-applies the size the window opened with, so ask for
        # the measured size once more before reading any geometry.
        app.geometry(size)
        for _ in range(5):
            app.update()
            time.sleep(0.02)
        app.update_idletasks()
        want_w, want_h = (int(part) for part in size.split("x"))
        self.assertEqual(
            (int(app.winfo_width()), int(app.winfo_height())),
            (want_w, want_h),
            f"the window must be laid out at {size} for this measurement",
        )

    @staticmethod
    def _edges(widget, body) -> tuple[int, int]:
        """A widget's right and bottom edges in the content frame's own pixels."""
        return (
            int(widget.winfo_rootx())
            - int(body.winfo_rootx())
            + int(widget.winfo_width()),
            int(widget.winfo_rooty())
            - int(body.winfo_rooty())
            + int(widget.winfo_height()),
        )

    def _outside_the_region(self, app, size: str) -> list[str]:
        """Every control a scrolling page's canvas cannot bring into view.

        The canvas's scroll region has to cover the content on both axes: a
        control past its right edge is off-screen, and a canvas that only scrolls
        vertically has no way to reach it.
        """
        self._layout_at(app, size)
        out: list[str] = []
        pages = {
            str(app.nb.tab(tab, "text")): app.nb.nametowidget(tab) for tab in app.nb.tabs()
        }
        for name, page in pages.items():
            scroller = app._scroll_canvases.get(page)
            if scroller is None:
                continue
            app._goto_tab(name)
            app.update()
            body = app._scroll_bodies.get(page, page)
            bbox = scroller.bbox("all")
            if bbox is None:
                out.append(f"{name}: no scroll region")
                continue
            if int(bbox[2]) < int(body.winfo_reqwidth()):
                out.append(
                    f"{name}: the region is {int(bbox[2])} px wide and the content "
                    f"wants {body.winfo_reqwidth()} px"
                )
            for control in self._controls(page):
                right, bottom = self._edges(control, body)
                if right > int(bbox[2]) + 1:
                    out.append(
                        f"{name}: {control} is {right - int(bbox[2])} px past the "
                        "right edge of the scroll region"
                    )
                if bottom > int(bbox[3]) + 1:
                    out.append(
                        f"{name}: {control} is {bottom - int(bbox[3])} px past the "
                        "bottom of the scroll region"
                    )
        return out

    def _old_window(self):
        """A window whose pages were built by the old, vertical-only helper."""
        old_helper = _old_form(
            self.app_mod.SaladStudio._scrollable_page, self.PAGE_HELPER_EDITS
        )
        with mock.patch.object(
            self.app_mod.SaladStudio, "_scrollable_page", old_helper
        ):
            old = self.app_mod.SaladStudio(show=False)
        old.withdraw()
        return old

    def _import_height_knob(self):
        """The Import page's Height entry, found by the variable it writes."""
        want = str(self.app.var_imp_height)
        for control in self._controls(self._pages()["Import"]):
            if isinstance(control, ttk.Entry) and str(control.cget("textvariable")) == want:
                return control
        self.fail("the Import page has no Height knob")

    def test_every_page_is_inside_its_scroll_region_on_both_axes(self) -> None:
        """Issue 3: at 1024 px the Import page is wider than its canvas.

        Nothing scrolled sideways, so the right-hand controls of a page wider
        than its canvas could not be reached by any means. The old helper's
        region is narrower than its content, which is what this measures.
        """
        for size in ("1024x720", "900x700"):
            with self.subTest(size=size):
                outside = self._outside_the_region(self.app, size)
                self.assertEqual(outside, [], f"at {size}: " + "; ".join(outside))

        old = self._old_window()
        try:
            outside = self._outside_the_region(old, "1024x720")
        finally:
            try:
                old.destroy()
            except tk.TclError:
                pass
        self.assertTrue(
            outside,
            "the old vertical-only helper must leave a control past the region",
        )

    def test_focusing_the_import_height_knob_scrolls_it_into_view(self) -> None:
        """The knob the issue names sits past the right edge at 1024 px.

        Focus has to bring it in on the horizontal axis too, or the keyboard
        cannot reach a control the mouse cannot either.
        """
        app = self.app
        self._layout_at(app, "1024x720")
        pages = self._pages()
        import_page = pages["Import"]
        app._goto_tab("Import")
        app.update()
        canvas = app._scroll_canvases[import_page]
        body = app._scroll_bodies[import_page]
        knob = self._import_height_knob()
        self.assertEqual(canvas.xview()[0], 0.0, "the page starts at its left edge")
        right, _bottom = self._edges(knob, body)
        self.assertGreater(
            right,
            int(canvas.winfo_width()),
            "the Height knob must start past the right edge for this to be a drive",
        )

        app._on_page_focus(type("E", (), {"widget": knob})())
        app.update()
        self.assertGreater(canvas.xview()[0], 0.0, "focus must scroll the page sideways")
        # Where the knob now sits inside the canvas's own viewport.
        left = int(knob.winfo_rootx()) - int(canvas.winfo_rootx())
        self.assertGreaterEqual(left, -1, "the knob's left edge must be in view")
        self.assertLessEqual(
            left + int(knob.winfo_width()),
            int(canvas.winfo_width()) + 1,
            "the knob's right edge must be in view",
        )

        # The old reveal moves on Y only, so the same drive leaves it off-screen.
        old_reveal = _old_form(self.app_mod.SaladStudio._reveal, self.REVEAL_EDITS)
        canvas.xview_moveto(0.0)
        app.update_idletasks()
        with mock.patch.object(self.app_mod.SaladStudio, "_reveal", old_reveal):
            app._on_page_focus(type("E", (), {"widget": knob})())
            app.update()
        self.assertEqual(
            canvas.xview()[0],
            0.0,
            "the old Y-only reveal must leave the Height knob off-screen",
        )


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class ThePromptGridsScrollSideways(unittest.TestCase):
    """Issue 1 of `docs/issue-sweep-2026-10-16.md`, driven on the real window.

    The Prompt Catalog and Prompt History pages are plain frames that never went
    through `_scrollable_page`, and each gave its tree a vertical scrollbar and
    none horizontal. At 1024x720 the Catalog's Graph column is entirely
    off-screen and nothing could bring it back. This measures both trees' xview
    span at 1366x728 and 1024x720, then drives each tree's own horizontal
    scrollbar to the end and requires the last column to be on screen. The old
    builders, rebuilt from this file with the fix's lines taken out, leave the
    trees with no such scrollbar, so the same columns stay unreachable.
    """

    # The columns each grid shows, with the widths the page sets. The fix adds a
    # bar and must not touch either: a drag of the heading edge is the user's.
    CATALOG_COLUMNS = (
        ("when", 130),
        ("name", 180),
        ("description", 260),
        ("preview", 380),
        ("stats", 300),
    )
    HISTORY_COLUMNS = (
        ("when", 140),
        ("profile", 100),
        ("preview", 480),
        ("stats", 380),
    )
    # The tree column each grid shows; the Catalog is headings-only, so it has none.
    TREE_COLUMN = {"Prompt Catalog": 0, "Prompt History": 56}
    # The lines this pass added to each builder, as (shipped text, replaced).
    # `_old_form` dedents the source, so a method body starts at four spaces.
    CATALOG_EDITS = (
        (
            (
                "    # The columns total more than a narrow window, so the right-hand ones\n"
                "    # (the Graph column among them) are off-screen without a bar to reach\n"
                "    # them; the vertical bar alone leaves them unreachable.\n"
                "    hscroll = ttk.Scrollbar(\n"
                '        self._catalog, orient="horizontal", command=self.catalog_tree.xview\n'
                "    )\n"
            ),
            "",
        ),
        (
            (
                "    self.catalog_tree.configure(\n"
                "        yscrollcommand=yscroll.set, xscrollcommand=hscroll.set\n"
                "    )\n"
            ),
            "    self.catalog_tree.configure(yscrollcommand=yscroll.set)\n",
        ),
        (
            '    hscroll.grid(row=2, column=0, sticky="ew")\n',
            "",
        ),
        (
            '    bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))\n',
            '    bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))\n',
        ),
        (
            '    self.catalog_empty_lbl.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))\n',
            '    self.catalog_empty_lbl.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))\n',
        ),
        (
            (
                "    ttk.Label(self._catalog, textvariable=self.catalog_status).grid(\n"
                '        row=5, column=0, columnspan=2, sticky="w", pady=(6, 0)\n'
            ),
            (
                "    ttk.Label(self._catalog, textvariable=self.catalog_status).grid(\n"
                '        row=4, column=0, columnspan=2, sticky="w", pady=(6, 0)\n'
            ),
        ),
    )
    HISTORY_EDITS = (
        (
            (
                "    # The same rule the Catalog grid follows: the columns are wider than a\n"
                "    # narrow window, so the right-hand ones need a horizontal bar to reach.\n"
                "    hscroll = ttk.Scrollbar(\n"
                '        self._prompt_hist, orient="horizontal", command=self.prompt_hist_tree.xview\n'
                "    )\n"
            ),
            "",
        ),
        (
            (
                "    self.prompt_hist_tree.configure(\n"
                "        yscrollcommand=yscroll.set, xscrollcommand=hscroll.set\n"
                "    )\n"
            ),
            "    self.prompt_hist_tree.configure(yscrollcommand=yscroll.set)\n",
        ),
        (
            '    hscroll.grid(row=1, column=0, sticky="ew")\n',
            "",
        ),
        (
            '    bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))\n',
            '    bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))\n',
        ),
        (
            '    self.prompt_hist_empty_lbl.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))\n',
            '    self.prompt_hist_empty_lbl.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))\n',
        ),
    )

    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.SaladStudio(show=False)
        self.app.withdraw()
        self.addCleanup(self._destroy, self.app)
        self.app.update_idletasks()

    @staticmethod
    def _destroy(app) -> None:
        try:
            app.destroy()
        except tk.TclError:
            pass

    def _layout_at(self, app, size: str) -> None:
        """Lay ``app`` out at a requested size and let Tk settle the geometry."""
        app.geometry(size)
        app.deiconify()
        deadline = time.time() + 10.0
        while time.time() < deadline:
            app.update()
            if app.winfo_width() > 100 and app.winfo_height() > 100:
                break
            time.sleep(0.02)
        # The Map handler re-applies the size the window opened with.
        app.geometry(size)
        for _ in range(5):
            app.update()
            time.sleep(0.02)
        app.update_idletasks()
        want_w, want_h = (int(part) for part in size.split("x"))
        self.assertEqual(
            (int(app.winfo_width()), int(app.winfo_height())),
            (want_w, want_h),
            f"the window must be laid out at {size} for this measurement",
        )

    def _grids(self, app) -> tuple:
        """Each grid with the page it lives on, by the notebook's own label."""
        return (
            ("Prompt Catalog", app.catalog_tree),
            ("Prompt History", app.prompt_hist_tree),
        )

    @staticmethod
    def _horizontal_scrollbars(widget) -> list:
        out: list = []

        def walk(node) -> None:
            for child in node.winfo_children():
                if isinstance(child, ttk.Scrollbar) and str(child.cget("orient")) == "horizontal":
                    out.append(child)
                walk(child)

        walk(widget)
        return out

    def _drive(self, tree, bar, fraction: float) -> None:
        """Move the bar the way a drag does, through the bar's own command."""
        tree.tk.call(str(bar.cget("command")), "moveto", fraction)
        tree.update_idletasks()

    def _xscrollbar(self, tree):
        """The horizontal scrollbar whose command moves ``tree`` sideways, or None.

        A tree can be told to ``xview_moveto`` without any scrollbar, so the bar
        is proved by driving it: the tree has to move with it.
        """
        for bar in self._horizontal_scrollbars(tree.master):
            tree.xview_moveto(0.0)
            tree.update_idletasks()
            start = float(tree.xview()[0])
            self._drive(tree, bar, 1.0)
            end = tree.xview()
            tree.xview_moveto(0.0)
            tree.update_idletasks()
            if float(end[1]) >= 1.0 and float(end[0]) > start:
                return bar
        return None

    def _old_window(self):
        """A window whose two grids were built by the old, vertical-only builders."""
        old_catalog = _old_form(
            self.app_mod.SaladStudio._build_prompt_catalog_tab, self.CATALOG_EDITS
        )
        old_history = _old_form(
            self.app_mod.SaladStudio._build_prompt_history_tab, self.HISTORY_EDITS
        )
        with mock.patch.object(
            self.app_mod.SaladStudio, "_build_prompt_catalog_tab", old_catalog
        ), mock.patch.object(
            self.app_mod.SaladStudio, "_build_prompt_history_tab", old_history
        ):
            old = self.app_mod.SaladStudio(show=False)
        old.withdraw()
        return old

    def test_each_grid_reaches_its_right_hand_columns_at_both_sizes(self) -> None:
        """At 1366x728 and 1024x720 the whole column set must be reachable.

        The span is measured first (a grid that fits needs no drive), then the
        tree's own bar is driven to both ends: the left edge and the right-hand
        columns have to come into view, at the widths the page sets.
        """
        app = self.app
        columns = {
            "Prompt Catalog": self.CATALOG_COLUMNS,
            "Prompt History": self.HISTORY_COLUMNS,
        }
        for size in ("1366x728", "1024x720"):
            self._layout_at(app, size)
            for name, tree in self._grids(app):
                with self.subTest(size=size, grid=name):
                    app._goto_tab(name)
                    app.update()
                    self.assertEqual(
                        tuple(
                            (col, int(tree.column(col, "width")))
                            for col in tree["columns"]
                        ),
                        tuple(columns[name]),
                        f"{name}'s columns and their widths must be what the page sets",
                    )
                    if self.TREE_COLUMN[name]:
                        self.assertEqual(
                            int(tree.column("#0", "width")),
                            self.TREE_COLUMN[name],
                            f"{name}'s tree column must keep the width the page sets",
                        )
                    view = tree.xview()
                    span = float(view[1]) - float(view[0])
                    self.assertLess(
                        span,
                        1.0,
                        f"this drive needs {name} to be wider than its viewport at {size}",
                    )
                    bar = self._xscrollbar(tree)
                    self.assertIsNotNone(
                        bar,
                        f"{name} clips {int((1 - span) * tree.winfo_width() / span)} px of "
                        f"columns at {size} and nothing scrolls them sideways",
                    )
                    self._drive(tree, bar, 1.0)
                    self.assertAlmostEqual(
                        float(tree.xview()[1]),
                        1.0,
                        places=3,
                        msg=f"{name}'s last column must be reachable at {size}",
                    )
                    self._drive(tree, bar, 0.0)
                    self.assertAlmostEqual(
                        float(tree.xview()[0]),
                        0.0,
                        places=3,
                        msg=f"{name}'s first column must be reachable at {size}",
                    )

        # The old builders, rebuilt from the shipped source with the fix's lines
        # out, leave each tree with no horizontal bar at all.
        old = self._old_window()
        try:
            self._layout_at(old, "1024x720")
            for name, tree in self._grids(old):
                with self.subTest(size="1024x720", grid=name, layout="old"):
                    old._goto_tab(name)
                    old.update()
                    view = tree.xview()
                    self.assertLess(
                        float(view[1]) - float(view[0]),
                        1.0,
                        f"the old {name} grid is wider than its viewport too",
                    )
                    self.assertIsNone(
                        self._xscrollbar(tree),
                        f"the old layout gave {name} no way to reach its right-hand columns",
                    )
        finally:
            self._destroy(old)


class _StubWindow:
    """Just enough of the window for a setUp that is not about the window."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def withdraw(self) -> None:
        pass

    def update_idletasks(self) -> None:
        pass

    def destroy(self) -> None:
        pass


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class WindowClassesPutTheStoresBack(unittest.TestCase):
    """Every window class here must undo the store paths it redirects.

    The redirects are module-level, so a class that does not put them back
    outlives its own test: a later ``_TempPaths`` then saves the redirect as if
    it were the shipped path, and the leak outlives the whole run. This drives
    each class's own ``setUp`` and cleanups, which is where the undo lives.
    """

    # The classes that build a window and redirect the stores by hand.
    CLASSES = (
        "LiveFieldSync",
        "NewPagesAndPlacement",
        "ListSurfacesSayWhenTheyAreEmpty",
        "ClosingReportsWhatTkWouldNotTake",
        "BothLogPanesMaskSecrets",
        "ConfigCheckboxCompat",
    )
    # What each class redirects, as (module, attribute).
    STORES = (
        ("profiles", "PROFILES_PATH"),
        ("lora_store", "EXTRAS_PATH"),
        ("tokens", "LOCAL_PATH"),
        ("tokens", "CONFIG_HOME"),
        ("prompt_catalog", "CATALOG_PATH"),
        ("prompt_history", "HISTORY_PATH"),
        ("ui_state", "STATE_PATH"),
    )

    def _stores(self) -> dict:
        from salad_studio import (
            lora_store,
            profiles,
            prompt_catalog,
            prompt_history,
            tokens,
            ui_state,
        )

        modules = {
            "profiles": profiles,
            "lora_store": lora_store,
            "tokens": tokens,
            "prompt_catalog": prompt_catalog,
            "prompt_history": prompt_history,
            "ui_state": ui_state,
        }
        return {
            f"{name}.{attr}": getattr(modules[name], attr) for name, attr in self.STORES
        }

    def test_each_class_puts_the_store_paths_back(self) -> None:
        """The window itself is stubbed: what is under test is the redirect."""
        from salad_studio import app as app_mod

        for name in self.CLASSES:
            with self.subTest(window_class=name):
                case_cls = globals()[name]
                method = next(
                    m for m in dir(case_cls) if m.startswith("test_") and m != "test_"
                )
                before = self._stores()
                case = case_cls(method)
                with mock.patch.object(app_mod, "SaladStudio", _StubWindow):
                    try:
                        case.setUp()
                    except unittest.SkipTest as exc:
                        self.skipTest(f"Tk cannot initialize: {exc}")
                    try:
                        self.assertNotEqual(
                            self._stores(),
                            before,
                            f"{name} must redirect the stores its window reads",
                        )
                    finally:
                        case.doCleanups()
                self.assertEqual(
                    self._stores(),
                    before,
                    f"{name} left the stores redirected; the leak outlives the run",
                )


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class AGridFillsAPageWiderThanIt(unittest.TestCase):
    """The follow-up to issue 1: the grids must still grow on a wide window.

    Declaring every column ``stretch=False`` is what lets a page *narrower* than
    the grid keep the widths its table declares and scroll to the rest. It also
    stopped the columns growing on a page *wider* than the grid, which they did
    before: at 1600x900 the Catalog tree is 1366 px wide and its columns still
    totalled the 1250 they declare, leaving 116 px of dead room to the right of
    the Graph column. This measures the room the table's own columns take at a
    wide size, and the old form (the shipped re-fit with its body taken out)
    leaves that room unfilled.
    """

    # The columns each grid shows, with the widths the page sets, and the ones
    # the table marks as taking the room a wider page leaves.
    @staticmethod
    def _table(name: str):
        from salad_studio import app as app_mod

        return {
            "Prompt Catalog": app_mod.CATALOG_GRID_COLUMNS,
            "Prompt History": app_mod.HISTORY_GRID_COLUMNS,
            "Queue": app_mod.QUEUE_GRID_COLUMNS,
        }[name]

    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self._ctx = _TempPaths(self.tmp)
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.SaladStudio(show=False)
        self.addCleanup(self._destroy, self.app)

    @staticmethod
    def _destroy(app) -> None:
        try:
            app.destroy()
        except tk.TclError:
            pass

    def _layout_at(self, app, size: str) -> None:
        _layout_window(app, size)

    def _grids(self, app) -> tuple:
        return (
            ("Prompt Catalog", app.catalog_tree),
            ("Prompt History", app.prompt_hist_tree),
            ("Queue", app.queue_tree),
        )

    def _widths(self, tree) -> dict:
        return {col: int(tree.column(col, "width")) for col in tree["columns"]}

    def test_a_wider_page_hands_the_extra_room_to_the_tables_fill_columns(self) -> None:
        app = self.app
        for size in ("1600x900", "1920x1080"):
            self._layout_at(app, size)
            for name, tree in self._grids(app):
                with self.subTest(size=size, grid=name):
                    app._goto_tab(name)
                    for _ in range(10):
                        app.update()
                        time.sleep(0.01)
                    table = self._table(name)
                    declared = {col: width for col, _h, width, _f in table}
                    got = self._widths(tree)
                    room = int(tree.winfo_width()) - sum(declared.values())
                    if "tree" in str(tree.cget("show")):
                        room -= int(tree.column("#0", "width"))
                    self.assertGreater(
                        room, 0, f"this drive needs {name} to be narrower than its page"
                    )
                    for col, width, fill in (
                        (c, w, f) for c, _h, w, f in table
                    ):
                        if fill:
                            self.assertGreater(
                                got[col],
                                width,
                                f"{name}.{col} must take some of the {room} px a "
                                f"{size} page leaves",
                            )
                        else:
                            self.assertEqual(
                                got[col],
                                width,
                                f"{name}.{col} takes no extra room; the page sets it",
                            )
                    # Every px of the room is handed out, not just most of it.
                    self.assertLessEqual(
                        abs(sum(got.values()) - sum(declared.values()) - room),
                        4,
                        f"{name} left {sum(got.values())} of its page's room unfilled",
                    )

    def test_a_narrower_page_gets_the_declared_widths_back(self) -> None:
        """The growth is recomputed, not kept: a narrowed window scrolls again."""
        app = self.app
        declared = {
            name: {col: width for col, _h, width, _f in self._table(name)}
            for name, _tree in self._grids(app)
        }
        self._layout_at(app, "1600x900")
        for name, tree in self._grids(app):
            with self.subTest(size="1600x900", grid=name):
                app._goto_tab(name)
                for _ in range(10):
                    app.update()
                    time.sleep(0.01)
                self.assertNotEqual(
                    self._widths(tree),
                    declared[name],
                    "the wide page must have grown it",
                )
        self._layout_at(app, "1024x720")
        for name, tree in self._grids(app):
            with self.subTest(size="1024x720", grid=name):
                app._goto_tab(name)
                for _ in range(10):
                    app.update()
                    time.sleep(0.01)
                self.assertEqual(
                    self._widths(tree),
                    declared[name],
                    f"{name} kept the widths a wider window gave it; the page sets "
                    f"them and the tree's own bar reaches the rest",
                )

    def test_the_old_form_leaves_the_room_unfilled(self) -> None:
        """The re-fit taken out of the shipped source leaves the dead room."""
        old_fit = _old_form(self.app_mod.SaladStudio._keep_grid_filling, self.FIT_EDITS)
        with mock.patch.object(self.app_mod.SaladStudio, "_keep_grid_filling", old_fit):
            old = self.app_mod.SaladStudio(show=False)
        self.addCleanup(self._destroy, old)
        self._layout_at(old, "1600x900")
        for name, tree in self._grids(old):
            with self.subTest(grid=name):
                old._goto_tab(name)
                for _ in range(10):
                    old.update()
                    time.sleep(0.01)
                table = self._table(name)
                declared = {col: width for col, _h, width, _f in table}
                self.assertEqual(
                    self._widths(tree),
                    declared,
                    f"without the re-fit {name} keeps the widths the page declares, "
                    f"which is the dead room this pass removed",
                )

    # The shipped re-fit, with its body taken out: what the page did before it.
    # `_old_form` dedents the source, so a method body starts at four spaces.
    FIT_EDITS = (
        (
            (
                "    def refit(_event=None) -> None:\n"
                "        width = int(tree.winfo_width())\n"
                "        if width <= 1 or width == fitted[\"width\"]:\n"
                "            # Not laid out yet, or the same width the last pass fitted.\n"
                "            return\n"
                "        fitted[\"width\"] = width\n"
                "        viewport = int(canvas.winfo_width())\n"
                "        if viewport > 1:\n"
                "            # The room a wider page leaves can never be more than the page\n"
                "            # itself: a tree that somehow reports more is not grown past it.\n"
                "            width = min(width, viewport)\n"
                "        room = width - span\n"
                "        if room <= 0:\n"
                "            for col, base in declared.items():\n"
                "                tree.column(col, width=base)\n"
                "            return\n"
                "        share, rest = divmod(room, len(fills))\n"
                "        for index, col in enumerate(fills):\n"
                "            tree.column(col, width=declared[col] + share + (1 if index < rest else 0))\n"
            ),
            "    def refit(_event=None) -> None:\n        return\n",
        ),
    )


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class TheStatusLineWrapsInTheWindow(unittest.TestCase):
    """The status line must wrap, not run off a 1024 px window's right edge.

    A refusal is a whole sentence: the container-down refusal is 215 characters
    and names the action at its tail ("Start it in the Salad console, then
    Generate again."). The label had no ``wraplength``, so at 1024 px the tail
    was clipped and the action was never read. The old form (the shipped
    ``_wrap_status`` with its body taken out) leaves the label unwrapped.
    """

    def setUp(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            self.skipTest(f"Tk cannot initialize: {e}")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self._ctx = _TempPaths(Path(self._td.name))
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from salad_studio import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.SaladStudio(show=False)
        self.addCleanup(self._destroy, self.app)

    @staticmethod
    def _destroy(app) -> None:
        try:
            app.destroy()
        except tk.TclError:
            pass

    def _lay_out_at(self, app, size: str) -> None:
        _layout_window(app, size)

    def test_a_long_refusal_wraps_inside_a_narrow_window(self) -> None:
        app = self.app
        self._lay_out_at(app, "1024x720")
        sentence = (
            "Refused: the container for profile 'klein5090' (https://example.invalid/"
            "gateway) is down: its group is stopped. Start it in the Salad console, "
            "then Generate again."
        )
        app.status.set(sentence)
        for _ in range(5):
            app.update()
            time.sleep(0.02)
        wrap = int(app.status_lbl.cget("wraplength"))
        self.assertEqual(
            wrap,
            int(app.winfo_width()) - 16,
            "the status line must wrap to the room the window gives it",
        )

    def test_the_old_form_leaves_the_status_line_unwrapped(self) -> None:
        """A label with no ``wraplength`` draws the sentence as one clipped line."""
        old_wrap = _old_form(self.app_mod.SaladStudio._wrap_status, self.WRAP_EDITS)
        with mock.patch.object(self.app_mod.SaladStudio, "_wrap_status", old_wrap):
            old = self.app_mod.SaladStudio(show=False)
        self.addCleanup(self._destroy, old)
        self._lay_out_at(old, "1024x720")
        old.status.set("Refused: " + "a sentence that will not fit. " * 12)
        for _ in range(5):
            old.update()
            time.sleep(0.02)
        self.assertEqual(
            int(old.status_lbl.cget("wraplength") or 0),
            0,
            "without the wrap the label asks for the whole sentence's width",
        )
        self.assertGreater(
            int(old.status_lbl.winfo_reqwidth()),
            0,
            "the old form still lays the sentence out; it just never wraps it",
        )

    # The shipped wrap, with its body taken out.
    WRAP_EDITS = (
        (
            (
                "    width = int(self.winfo_width())\n"
                "    if width <= 1:\n"
                "        return\n"
                "    want = max(_STATUS_MIN_WRAP, width - 16)\n"
                "    if want != self._status_wrap:\n"
                "        self._status_wrap = want\n"
                "        self.status_lbl.configure(wraplength=want)\n"
            ),
            "",
        ),
    )


if __name__ == "__main__":
    unittest.main()