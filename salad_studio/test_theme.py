"""Theme tests: drive the live apply_theme path on a real Tk root.

Does not mock theme.apply_theme. Isolates profile/LoRA file I/O when the
full SaladStudio window is constructed.
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

APP = HERE / "app.py"

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError as _tk_err:  # pragma: no cover - host without Tcl
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = _tk_err
else:
    _TK_IMPORT_ERROR = None

_DEFAULTS: dict[tuple[str, str], str] = {}
_TK_OK = tk is not None
_TK_ERROR: object = _TK_IMPORT_ERROR


def setUpModule() -> None:
    """Snapshot unthemed ttk lookups before any test calls apply_theme."""
    global _TK_OK, _TK_ERROR
    if tk is None:
        return
    try:
        root = tk.Tk()
    except tk.TclError as e:
        _TK_OK = False
        _TK_ERROR = e
        return
    root.withdraw()
    try:
        from salad_studio.theme import STYLE_LOOKUPS

        style = ttk.Style(root)
        for cls_name, option, _key in STYLE_LOOKUPS:
            _DEFAULTS[(cls_name, option)] = style.lookup(cls_name, option) or ""
    finally:
        root.destroy()


def _hex(root: tk.Misc, color: str) -> str:
    if not color:
        return ""
    r, g, b = root.winfo_rgb(color)
    return f"#{r >> 8:02x}{g >> 8:02x}{b >> 8:02x}"


def _init_calls_apply_theme(src: str) -> bool:
    tree = ast.parse(src)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SaladStudio":
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name != "__init__":
                continue
            for n in ast.walk(item):
                if not isinstance(n, ast.Call):
                    continue
                func = n.func
                if isinstance(func, ast.Name) and func.id == "apply_theme":
                    return True
                if isinstance(func, ast.Attribute) and func.attr == "apply_theme":
                    return True
    return False


class StartupCallsTheme(unittest.TestCase):
    def test_salad_studio_init_calls_apply_theme(self) -> None:
        src = APP.read_text(encoding="utf-8")
        self.assertIn("theme.apply_theme", src)
        self.assertTrue(_init_calls_apply_theme(src), "SaladStudio.__init__ must call apply_theme")
        # Apply happens immediately after Tk construction, before widgets.
        init_src = src.split("class SaladStudio", 1)[1]
        init_src = init_src.split("def _build_config_tab", 1)[0]
        self.assertLess(
            init_src.find("apply_theme"),
            init_src.find("ttk.Notebook"),
        )


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class ThemeOnBareRoot(unittest.TestCase):
    """Call the live apply_theme on a withdrawn Tk; assert Style.lookup."""

    @classmethod
    def setUpClass(cls) -> None:
        if not _TK_OK:
            raise unittest.SkipTest(f"Tk cannot initialize: {_TK_ERROR}")
        from salad_studio.theme import PALETTE, STYLE_LOOKUPS, apply_theme, style_text
        from salad_studio.history_strip import HistoryStrip

        cls.PALETTE = PALETTE
        cls.STYLE_LOOKUPS = STYLE_LOOKUPS
        cls.root = tk.Tk()
        cls.root.withdraw()
        apply_theme(cls.root)
        cls.style = ttk.Style(cls.root)
        cls.strip = HistoryStrip(cls.root, thumb_size=(64, 64))
        cls.text = tk.Text(cls.root)
        style_text(cls.text)
        cls.root.update_idletasks()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:
            pass

    def test_lookups_match_palette_and_differ_from_defaults(self) -> None:
        palette = self.PALETTE
        for cls_name, option, key in self.STYLE_LOOKUPS:
            raw = self.style.lookup(cls_name, option) or ""
            self.assertTrue(
                raw,
                f"{cls_name}.{option} is empty after apply_theme",
            )
            got = _hex(self.root, raw)
            want = _hex(self.root, palette[key])
            self.assertEqual(
                got,
                want,
                f"{cls_name}.{option} -> {got!r} != palette[{key!r}] {want!r} (raw={raw!r})",
            )
            before = _DEFAULTS.get((cls_name, option), "")
            if before:
                self.assertNotEqual(
                    got,
                    _hex(self.root, before),
                    f"{cls_name}.{option} still stock default {before!r}",
                )

    def test_root_background_is_palette_bg(self) -> None:
        got = _hex(self.root, str(self.root.cget("background")))
        want = _hex(self.root, self.PALETTE["bg"])
        self.assertEqual(got, want)

    def test_history_strip_canvas_and_chevrons_use_palette(self) -> None:
        strip = self.strip
        well = _hex(self.root, self.PALETTE["well"])
        button = _hex(self.root, self.PALETTE["button"])
        fg = _hex(self.root, self.PALETTE["fg"])
        bg = _hex(self.root, self.PALETTE["bg"])
        self.assertEqual(_hex(self.root, str(strip.canvas.cget("background"))), well)
        self.assertEqual(_hex(self.root, str(strip.cget("background"))), bg)
        self.assertEqual(_hex(self.root, str(strip.left_btn.cget("background"))), button)
        self.assertEqual(_hex(self.root, str(strip.right_btn.cget("background"))), button)
        self.assertEqual(_hex(self.root, str(strip.left_btn.cget("foreground"))), fg)
        self.assertEqual(_hex(self.root, str(strip.right_btn.cget("foreground"))), fg)
        self.assertEqual(str(strip.left_btn.cget("text")), "◀")
        self.assertEqual(str(strip.right_btn.cget("text")), "▶")

    def test_text_widget_uses_well_and_accent_caret(self) -> None:
        well = _hex(self.root, self.PALETTE["well"])
        fg = _hex(self.root, self.PALETTE["fg"])
        accent = _hex(self.root, self.PALETTE["accent"])
        self.assertEqual(_hex(self.root, str(self.text.cget("background"))), well)
        self.assertEqual(_hex(self.root, str(self.text.cget("foreground"))), fg)
        self.assertEqual(_hex(self.root, str(self.text.cget("insertbackground"))), accent)


def _isolate_studio_io(tmp: Path) -> None:
    from salad_studio import lora_store, profiles, prompt_history, tokens, ui_state

    profiles.PROFILES_PATH = tmp / "studio-profiles.json"
    lora_store.EXTRAS_PATH = tmp / "studio-loras.json"
    # Constructing the window reads the token store (log redaction), the
    # prompt history, and the saved UI state. Keep all three off the real files.
    tokens.LOCAL_PATH = tmp / "studio-tokens.json"
    tokens.CONFIG_HOME = tmp / "defaults"
    prompt_history.HISTORY_PATH = tmp / "studio-prompt-history.json"
    prompt_history.THUMBS_DIR = tmp / "studio-prompt-thumbs"
    ui_state.STATE_PATH = tmp / "studio-ui.json"


def _tab_texts(nb: ttk.Notebook) -> list[str]:
    return [nb.tab(tab_id, "text") for tab_id in nb.tabs()]


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class LiveSaladStudioWindow(unittest.TestCase):
    """Construct the real window with config I/O pointed at a temp dir."""

    def setUp(self) -> None:
        if not _TK_OK:
            self.skipTest(f"Tk cannot initialize: {_TK_ERROR}")

    def _make_app(self):
        from salad_studio.app import SaladStudio
        from salad_studio.theme import PALETTE, STYLE_LOOKUPS, apply_theme

        # apply_theme is the live function, constructing SaladStudio must call it.
        self.assertTrue(callable(apply_theme))
        app = SaladStudio(show=False)
        app.withdraw()
        app.update_idletasks()
        return app, PALETTE, STYLE_LOOKUPS

    def test_window_title_tabs_and_style_lookups(self) -> None:
        from salad_studio.theme import PALETTE

        with tempfile.TemporaryDirectory() as td:
            _isolate_studio_io(Path(td))
            if not _TK_OK:
                raise unittest.SkipTest(f"Tk cannot initialize: {_TK_ERROR}")
            app, palette, lookups = self._make_app()
            try:
                from salad_studio import app as app_mod

                self.assertEqual(app.title(), "Salad Studio")
                # The live notebook must expose exactly the shipped page set.
                self.assertEqual(_tab_texts(app.nb), list(app_mod.TAB_ORDER))
                style = ttk.Style(app)
                for cls_name, option, key in lookups:
                    raw = style.lookup(cls_name, option) or ""
                    self.assertTrue(raw, f"{cls_name}.{option} empty on live window")
                    self.assertEqual(
                        _hex(app, raw),
                        _hex(app, palette[key]),
                        f"live {cls_name}.{option}",
                    )
                self.assertEqual(
                    _hex(app, str(app.strip.canvas.cget("background"))),
                    _hex(app, PALETTE["well"]),
                )
                self.assertEqual(
                    _hex(app, str(app.strip.left_btn.cget("background"))),
                    _hex(app, PALETTE["button"]),
                )
                self.assertEqual(
                    _hex(app, str(app.editor_text.cget("background"))),
                    _hex(app, PALETTE["well"]),
                )
                self.assertEqual(
                    _hex(app, str(app.prompt_text.cget("background"))),
                    _hex(app, PALETTE["well"]),
                )
                shot = os.environ.get("SALAD_STUDIO_SHOT")
                if shot:
                    self._grab(app, Path(shot))
            finally:
                app.destroy()

    def test_second_construct_still_themed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _isolate_studio_io(Path(td))
            app, palette, lookups = self._make_app()
            try:
                self.assertEqual(app.title(), "Salad Studio")
                style = ttk.Style(app)
                raw = style.lookup("TFrame", "background") or ""
                self.assertEqual(_hex(app, raw), _hex(app, palette["bg"]))
            finally:
                app.destroy()

    @staticmethod
    def _grab(app: tk.Tk, dest: Path) -> None:
        import time

        app.deiconify()
        app.lift()
        try:
            app.attributes("-topmost", True)
        except tk.TclError:
            pass
        app.geometry("1100x720")
        app.update()
        app.update_idletasks()
        time.sleep(0.4)
        app.update()
        from PIL import ImageGrab

        x = int(app.winfo_rootx())
        y = int(app.winfo_rooty())
        w = int(app.winfo_width())
        h = int(app.winfo_height())
        box = (x, y, x + max(w, 1), y + max(h, 1))
        img = ImageGrab.grab(bbox=box)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest)


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class WindowVisibility(unittest.TestCase):
    """A test run must not flash windows; the shipped default must still show one."""

    def _build(self, *, env: dict[str, str], **kwargs):
        from unittest import mock

        from salad_studio.app import SaladStudio

        with mock.patch.dict(os.environ, env):
            with mock.patch.object(SaladStudio, "deiconify") as deiconify:
                app = SaladStudio(**kwargs)
        return app, deiconify

    def test_show_false_builds_but_never_maps(self) -> None:
        if not _TK_OK:
            raise unittest.SkipTest(f"Tk cannot initialize: {_TK_ERROR}")
        with tempfile.TemporaryDirectory() as td:
            _isolate_studio_io(Path(td))
            app, deiconify = self._build(env={"SALAD_STUDIO_HIDDEN": ""}, show=False)
            try:
                app.update_idletasks()
                self.assertFalse(deiconify.called, "show=False still mapped the window")
                self.assertEqual(app.state(), "withdrawn")
                self.assertEqual(int(app.winfo_ismapped()), 0)
                # The window is still fully built and usable while hidden.
                self.assertEqual(app.title(), "Salad Studio")
                self.assertEqual(len(app.nb.tabs()), len(_tab_texts(app.nb)))
            finally:
                app.destroy()

    def test_env_var_hides_the_default_window(self) -> None:
        if not _TK_OK:
            raise unittest.SkipTest(f"Tk cannot initialize: {_TK_ERROR}")
        with tempfile.TemporaryDirectory() as td:
            _isolate_studio_io(Path(td))
            app, deiconify = self._build(env={"SALAD_STUDIO_HIDDEN": "1"})
            try:
                app.update_idletasks()
                self.assertFalse(deiconify.called, "SALAD_STUDIO_HIDDEN did not hide the window")
                self.assertEqual(int(app.winfo_ismapped()), 0)
            finally:
                app.destroy()

    def test_default_still_shows_the_window(self) -> None:
        if not _TK_OK:
            raise unittest.SkipTest(f"Tk cannot initialize: {_TK_ERROR}")
        with tempfile.TemporaryDirectory() as td:
            _isolate_studio_io(Path(td))
            app, deiconify = self._build(env={"SALAD_STUDIO_HIDDEN": ""})
            try:
                self.assertTrue(deiconify.called, "the default build no longer shows the window")
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
