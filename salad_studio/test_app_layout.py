"""Behaviour tests for the live Salad Studio window: tabs, LoRA tab, JSON reflection."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TOOLS))

import request_json as rj  # noqa: E402
from lora_store import DEFAULT_KLEIN_LORA_IDS  # noqa: E402


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
        assert klein is not None and ultra is not None
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


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class ConfigCheckboxCompat(unittest.TestCase):
    def test_mismatched_checkboxes_disabled_for_graph(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            raise unittest.SkipTest(f"Tk cannot initialize: {e}") from e

        from salad_studio.app import SaladStudio
        from salad_studio import lora_store, profiles

        klein_id = "civitai:2334190@2625692"
        ultra_id = "civitai:796382@1026423"
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profiles.PROFILES_PATH = tmp / "studio-profiles.json"
            lora_store.EXTRAS_PATH = tmp / "studio-loras.json"
            app = SaladStudio(show=False)
            app.withdraw()
            try:
                app.update_idletasks()
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
            finally:
                app.destroy()

    def test_graph_combo_uses_family_labels_and_loras_do_not_vscroll(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            raise unittest.SkipTest(f"Tk cannot initialize: {e}") from e

        from salad_studio.app import LORA_CHECK_COLUMNS, SaladStudio
        from salad_studio import lora_store, profiles, theme

        klein_id = "civitai:2334190@2625692"
        ultra_id = "civitai:796382@1026423"
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profiles.PROFILES_PATH = tmp / "studio-profiles.json"
            lora_store.EXTRAS_PATH = tmp / "studio-loras.json"
            app = SaladStudio(show=False)
            app.withdraw()
            try:
                app.update_idletasks()
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
            finally:
                app.destroy()


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
        profiles.PROFILES_PATH = tmp / "studio-profiles.json"
        lora_store.EXTRAS_PATH = tmp / "studio-loras.json"
        # The app's own log() reads the token store; keep it off the real files.
        tokens.LOCAL_PATH = tmp / "studio-tokens.json"
        tokens.CONFIG_HOME = tmp / "defaults"
        prompt_catalog.CATALOG_PATH = tmp / "studio-prompt-catalog.json"
        prompt_history.HISTORY_PATH = tmp / "studio-prompt-history.json"
        prompt_history.THUMBS_DIR = tmp / "studio-prompt-thumbs"
        from salad_studio import ui_state
        ui_state.STATE_PATH = tmp / "studio-ui.json"
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
        assert item0 is not None
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
        assert item1 is not None
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
        if (item0.get("name") or "") != (item1.get("name") or ""):
            self.assertNotEqual(str(item0.get("name") or ""), app.var_lora_name.get())

    @staticmethod
    def _button_texts(widget) -> set[str]:
        """Every Button label in the widget tree under ``widget``."""
        out: set[str] = set()
        for child in widget.winfo_children():
            if isinstance(child, (tk.Button, ttk.Button)):
                out.add(str(child.cget("text")))
            out |= LiveFieldSync._button_texts(child)
        return out

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
        assert stored is not None, "Add did not persist the row to the extras store"
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
        assert stored is not None
        self.assertEqual(
            stored["request"]["prompt"]["74"]["inputs"]["text"], "v2"
        )

        # Save name / description <- the form.
        app.var_cat_name.set("Cover scene v2")
        app.var_cat_desc.set("second pass")
        app._on_catalog_save_meta()
        stored = self.prompt_catalog.get_entry(entry_id)
        assert stored is not None
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
        from salad_studio import ui_state

        app = self.app
        ui_state.STATE_PATH = Path(self._td.name) / "studio-ui.json"
        app.var_scheduler.set("Simple (Civitai)")
        app.var_unet.set("Distilled 9B")
        app.var_width.set("832")
        app.var_pol_us.set(True)
        app.prompt_text.delete("1.0", "end")
        app.prompt_text.insert("1.0", "restored prompt")
        app._save_ui_state()
        app.var_scheduler.set("Flux2 (Klein)")
        app.var_unet.set("Base 9B")
        app.var_width.set("100")
        app.var_pol_us.set(False)
        app.prompt_text.delete("1.0", "end")
        app.prompt_text.insert("1.0", "other")
        self.assertTrue(app._restore_ui_state())
        self.assertEqual(app.var_scheduler.get(), "Simple (Civitai)")
        self.assertEqual(app.var_unet.get(), "Distilled 9B")
        self.assertEqual(app.var_width.get(), "832")
        self.assertTrue(app.var_pol_us.get())
        self.assertEqual(app.prompt_text.get("1.0", "end").strip(), "restored prompt")

    def test_action_bar_and_vertical_nav(self) -> None:
        app = self.app
        self.assertTrue(hasattr(app, "var_gen_state"))
        self.assertEqual(app.var_gen_state.get(), "Idle")
        self.assertIs(app.gen_editor_btn, app.gen_btn)
        for name in (
            "Config",
            "Policy",
            "Tokens",
            "LoRAs",
            "Prompt Editor",
            "Import",
            "Prompt History",
            "Queue",
            "Logs",
        ):
            self.assertIn(name, app._nav_btns)
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
        from salad_studio.test_comfy_import import DISTILLED, DISTILLED_META

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
                "Policy",
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

    def test_generate_gate_handles_an_empty_status_word(self) -> None:
        """L11: the gate indexes [0] of a possibly empty status word."""
        app = self.app
        app._apply_generate_gate("")
        self.assertEqual(str(app.gen_btn.cget("state")), "disabled")
        app._apply_generate_gate("Ready")
        self.assertEqual(str(app.gen_btn.cget("state")), "normal")
        app._apply_generate_gate("Down")
        self.assertEqual(str(app.gen_btn.cget("state")), "disabled")

    def test_generate_blocks_on_an_empty_status_word(self) -> None:
        """L11: _on_generate must report, not raise, on an empty status word."""
        app = self.app
        self.tokens.write_token("salad", "salad-test-key-1234")
        app.var_salad_status.set("")
        from salad_studio import salad_status

        with mock.patch.object(
            salad_status, "snapshot_gateway", side_effect=OSError("offline")
        ), mock.patch.object(messagebox, "showinfo") as info:
            app._on_generate()
        self.assertTrue(info.called)
        self.assertFalse(app._busy)

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
        profiles.PROFILES_PATH = self.tmp / "studio-profiles.json"
        lora_store.EXTRAS_PATH = self.tmp / "studio-loras.json"
        tokens.LOCAL_PATH = self.tmp / "studio-tokens.json"
        tokens.CONFIG_HOME = self.tmp / "defaults"
        prompt_catalog.CATALOG_PATH = self.tmp / "studio-prompt-catalog.json"
        prompt_history.HISTORY_PATH = self.tmp / "studio-prompt-history.json"
        ui_state.STATE_PATH = self.tmp / "studio-ui.json"
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

    def _generate_gateway(self, graph: dict, gateway: str) -> str:
        """Drive a real _on_generate for `graph` with the form pointing at `gateway`.

        Returns the gateway the render was actually POSTed to.
        """
        from salad_studio import app as app_mod

        app = self.app
        self.tokens.write_token("salad", "salad-test-key-1234")
        app.editor_text.delete("1.0", "end")
        app.editor_text.insert("1.0", json.dumps(graph))
        app._rebuild_from_json()  # rewrites var_unet from the graph, as the UI does
        app.var_gateway.set(gateway)
        app.var_salad_status.set("Ready")
        seen: dict = {}

        def fake_generate(**kwargs):
            seen.update(kwargs)
            raise RuntimeError("routing check only")

        with mock.patch.object(
            app_mod.generator, "generate_from_payload", side_effect=fake_generate
        ), mock.patch.object(app_mod.messagebox, "showerror"), mock.patch(
            "salad_studio.app.threading.Thread", self._inline_thread()
        ):
            app._on_generate()
            self.assertTrue(self._pump(lambda: not app._busy))
        return str(seen.get("gateway") or "")

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
            self._graph_with_unet(profiles.SNOFS_UNET), klein.gateway
        )
        self.assertEqual(used, snofs.gateway)

    def test_generate_keeps_a_klein_graph_on_the_klein_group(self) -> None:
        from salad_studio import profiles

        klein = profiles.load_all()["klein"]
        used = self._generate_gateway(self._graph_with_unet(klein.primary_checkpoint), klein.gateway)
        self.assertEqual(used, klein.gateway)

    def test_generate_leaves_an_unknown_gateway_alone(self) -> None:
        """Only the groups we know are policed; a hand-typed gateway is the user's."""
        from salad_studio import profiles

        custom = "https://custom.example.test/gateway"
        used = self._generate_gateway(
            self._graph_with_unet(profiles.SNOFS_UNET), custom
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
        app.editor_text.insert("1.0", json.dumps(self._graph_with_unet(profiles.SNOFS_UNET)))
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
    def test_replica_badges_are_right_aligned_in_the_action_bar(self) -> None:
        app = self.app
        holder = app._replica_holder
        self.assertIs(holder.master, app._action_bar)
        self.assertEqual(str(holder.pack_info().get("side")), "right")
        self.assertEqual(set(app._replica_vars), {"klein", "klein5090"})
        for pid, (word, detail, lbl) in app._replica_vars.items():
            with self.subTest(replica=pid):
                self.assertTrue(self._descends_from(lbl, holder))
                detail_lbl = self._label_with_var(holder, detail)
                assert detail_lbl is not None, f"no detail label for {pid}"
                self.assertTrue(self._descends_from(detail_lbl, holder))
                # The badge label is bound to the word var the probe writes.
                self.assertEqual(str(lbl.cget("textvariable")), str(word))
        self.assertTrue(self._descends_from(app.salad_status_lbl, holder))
        self.assertIn("Check Salad status", self._buttons(holder))
        # Generate / Clean gallery / the live state stay on the left.
        self.assertEqual(str(app.gen_btn.pack_info().get("side")), "left")
        self.assertEqual(str(app.gen_state_lbl.pack_info().get("side")), "left")
        self.assertFalse(self._descends_from(holder, app._config))

    def test_status_word_still_reaches_the_badge_labels(self) -> None:
        app = self.app
        app._set_salad_word("Ready")
        self.assertEqual(app.var_salad_status.get(), "Ready")
        self.assertEqual(str(app.gen_btn.cget("state")), "normal")
        app._set_salad_word("Down")
        self.assertEqual(str(app.gen_btn.cget("state")), "disabled")

    # --- tokens page -----------------------------------------------------
    def test_tokens_page_has_no_fal_slot_and_shows_indicators(self) -> None:
        app = self.app
        boxes = [
            str(w.cget("text"))
            for w in self._all_widgets(app._tokens)
            if isinstance(w, ttk.LabelFrame)
        ]
        self.assertNotIn("fal.ai", boxes)
        self.assertEqual(boxes, ["Salad API", "Hugging Face", "Civitai", "DeepSeek"])
        self.assertEqual(list(app._token_entry), ["salad", "huggingface", "civitai", "deepseek"])
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


if __name__ == "__main__":
    unittest.main()
