"""The palette, the role maps built from it, and the page's own stylesheet.

Nothing here starts a window or a browser. The palette is held to the WCAG bar
on every pair the app draws, the two role maps are held to the same bar, and
``ui/src/styles.css`` must spend the palette rather than inventing a colour the
theme cannot change.
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

from salad_studio import theme  # noqa: E402
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


class RoleMaps(unittest.TestCase):
    def test_no_text_role_falls_below_the_contrast_bar(self) -> None:
        self.assertEqual(theme.check_contrast(), [])

    def test_both_maps_share_the_palette(self) -> None:
        self.assertEqual(theme.DARK["surface"], PALETTE["bg"])
        self.assertEqual(theme.DARK["primary"], PALETTE["accent"])
        self.assertEqual(theme.DARK["on_surface"], PALETTE["fg"])
        self.assertNotEqual(theme.LIGHT["surface"], theme.DARK["surface"])

    def test_a_role_map_reads_the_palette_by_name(self) -> None:
        for dark in (True, False):
            colors, roles = theme.canvas_colors(dark), theme.DARK if dark else theme.LIGHT
            with self.subTest(dark=dark):
                self.assertEqual(colors["on_surface"], roles["on_surface"])
                self.assertEqual(colors["muted"], roles["on_surface_variant"])
                self.assertEqual(colors["error"], roles["error"])
                self.assertEqual(colors["accent"], PALETTE["accent"])

    def test_the_stylesheet_spends_the_palette(self) -> None:
        """A hex in the page is a colour the theme cannot change."""
        css = (ROOT / "ui" / "src" / "styles.css").read_text(encoding="utf-8")
        root_block = css[css.index(":root {"):css.index("}", css.index(":root {"))]
        declared = set(HEX.findall(root_block))
        for value in (PALETTE["bg"], PALETTE["accent"], PALETTE["fg"], PALETTE["surface"]):
            self.assertIn(value.upper(), {v.upper() for v in declared},
                          f"{value} is not one of the page's own tokens")


if __name__ == "__main__":
    unittest.main()
