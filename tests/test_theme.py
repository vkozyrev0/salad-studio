"""The palette and the Flet theme built from it.

Nothing here starts a window. The palette is held to the WCAG bar on every
pair the app draws, and the Flet theme in both schemes is held to the same bar,
seeded from the same roles, and given to the page by ``flet_theme.apply``.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from salad_studio import flet_theme  # noqa: E402
from salad_studio.theme import (  # noqa: E402
    CONTRAST_MIN,
    FONT_HEAD,
    FONT_MONO,
    FONT_MONO_SMALL,
    FONT_TITLE,
    FONT_UI,
    FONT_UI_BOLD,
    PALETTE,
    SPACE,
    TEXT_PAIRS,
    contrast,
)

HEX = re.compile(r"#[0-9A-Fa-f]{6}")


class Palette(unittest.TestCase):
    def test_every_drawn_text_pair_clears_wcag_aa(self) -> None:
        for fg, bg in TEXT_PAIRS:
            with self.subTest(text=fg, on=bg):
                ratio = contrast(PALETTE[fg], PALETTE[bg])
                self.assertGreaterEqual(ratio, CONTRAST_MIN, f"{fg} on {bg} reads at {ratio:.2f}:1")

    def test_the_type_scale_is_segoe_ui_and_consolas(self) -> None:
        self.assertEqual(FONT_UI, ("Segoe UI", 10))
        self.assertEqual(FONT_UI_BOLD, ("Segoe UI Semibold", 10))
        self.assertEqual(FONT_TITLE, ("Segoe UI Semibold", 12))
        self.assertEqual(FONT_HEAD, ("Segoe UI Semibold", 9))
        self.assertEqual(FONT_MONO, ("Consolas", 10))
        self.assertEqual(FONT_MONO_SMALL, ("Consolas", 9))

    def test_spacing_scale_has_four_steps(self) -> None:
        self.assertEqual(SPACE, {"xs": 4, "sm": 8, "md": 12, "lg": 16})


class FletTheme(unittest.TestCase):
    def test_no_text_role_falls_below_the_contrast_bar(self) -> None:
        self.assertEqual(flet_theme.check_contrast(), [])

    def test_both_schemes_are_material_3_and_seeded_from_the_palette(self) -> None:
        for name, roles in (("dark", flet_theme.DARK), ("light", flet_theme.LIGHT)):
            theme = flet_theme._theme(roles, flet_theme.DARK_CANVAS, name == "dark")
            with self.subTest(scheme=name):
                self.assertTrue(theme.use_material3)
                self.assertEqual(theme.color_scheme.surface, roles["surface"])
                self.assertEqual(theme.color_scheme.primary, roles["primary"])
        self.assertEqual(flet_theme.DARK["surface"], PALETTE["bg"])
        self.assertEqual(flet_theme.DARK["primary"], PALETTE["accent"])
        self.assertEqual(flet_theme.DARK["on_surface"], PALETTE["fg"])
        self.assertNotEqual(flet_theme.LIGHT["surface"], flet_theme.DARK["surface"])

    def test_apply_hands_the_page_both_schemes_and_opens_dark(self) -> None:
        import flet as ft

        page = type("Page", (), {})()
        flet_theme.apply(page)
        self.assertTrue(page.theme.use_material3)
        self.assertTrue(page.dark_theme.use_material3)
        self.assertEqual(page.theme.color_scheme.surface, flet_theme.LIGHT["surface"])
        self.assertEqual(page.dark_theme.color_scheme.surface, flet_theme.DARK["surface"])
        self.assertEqual(page.theme_mode, ft.ThemeMode.DARK)

    def test_gap_names_the_shared_spacing_steps(self) -> None:
        self.assertEqual(flet_theme.GAP, {"xs": SPACE["xs"], "sm": SPACE["sm"], "md": SPACE["md"], "lg": SPACE["lg"]})
        self.assertEqual(flet_theme.PAGE_PAD, SPACE["lg"])

    def test_the_widget_palette_reads_its_roles_from_the_scheme(self) -> None:
        for dark in (True, False):
            colors, roles = flet_theme.canvas_colors(dark), flet_theme.DARK if dark else flet_theme.LIGHT
            with self.subTest(dark=dark):
                self.assertEqual(colors["on_surface"], roles["on_surface"])
                self.assertEqual(colors["muted"], roles["on_surface_variant"])
                self.assertEqual(colors["error"], roles["error"])
                self.assertEqual(colors["accent"], PALETTE["accent"])

    def test_the_pages_carry_no_colour_of_their_own(self) -> None:
        """A hex outside the theme is a colour the theme cannot change."""
        pages = ROOT / "salad_studio" / "pages"
        for path in sorted(pages.glob("*.py")):
            with self.subTest(module=path.name):
                self.assertEqual(HEX.findall(path.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
