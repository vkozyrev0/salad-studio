"""The Angular page's palette, read from the stylesheet it ships.

Nothing here starts a browser or imports a UI toolkit. The page owns its
tokens in ``ui/src/styles.css``; this module reads that block, holds every
text pair the page draws to the WCAG bar, and checks that the AG Grid theme
does not invent a colour the page cannot repaint.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CSS = ROOT / "ui" / "src" / "styles.css"
GRID_THEME = ROOT / "ui" / "src" / "app" / "core" / "studio-grid-theme.ts"

HEX = re.compile(r"#[0-9A-Fa-f]{6}")
TOKEN = re.compile(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6});")

# WCAG AA for normal-size text.
CONTRAST_MIN = 4.5

# Every pair here is text drawn on that background in the shipped page: body
# and muted ink on each surface it appears on, the rose as a label and as a
# fill, the plate caption, and the two state colours on their wells.
TEXT_PAIRS: tuple[tuple[str, str], ...] = (
    ("fg", "bg"),
    ("fg", "surface-hi"),
    ("fg", "well"),
    ("fg", "select-bg"),
    ("fg-muted", "bg"),
    ("fg-muted", "surface"),
    ("fg-muted", "surface-hi"),
    ("fg-muted", "well"),
    ("fg-muted", "ground"),
    ("fg", "select-tint"),
    ("fg-muted", "select-tint"),
    ("accent", "bg"),
    ("accent", "surface"),
    ("accent-hi", "surface-hi"),
    ("accent-fg", "accent"),
    ("accent-fg", "accent-hi"),
    ("button-fg", "button"),
    ("valid", "well"),
    ("invalid", "well"),
)

LOAD_BEARING = (
    "bg", "surface", "surface-hi", "well", "fg", "fg-muted", "accent",
    "accent-hi", "accent-fg", "valid", "invalid", "warn", "info", "rule",
    "hairline", "field",
)


def stylesheet() -> str:
    return CSS.read_text(encoding="utf-8")


def token_block(css: str | None = None) -> str:
    """The ``:root { … }`` block, which is the only place a colour may live."""
    text = stylesheet() if css is None else css
    start = text.index(":root {")
    return text[start : text.index("}", start) + 1]


def tokens(css: str | None = None) -> dict[str, str]:
    return {name: value.lower() for name, value in TOKEN.findall(token_block(css))}


def luminance(hex_color: str) -> float:
    """WCAG relative luminance of ``#rrggbb``."""
    h = hex_color.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two ``#rrggbb`` colours, 1.0 to 21.0."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class Palette(unittest.TestCase):
    def test_every_drawn_text_pair_clears_wcag_aa(self) -> None:
        colors = tokens()
        for fg, bg in TEXT_PAIRS:
            with self.subTest(text=fg, on=bg):
                ratio = contrast(colors[fg], colors[bg])
                self.assertGreaterEqual(ratio, CONTRAST_MIN, f"{fg} on {bg} reads at {ratio:.2f}:1")

    def test_the_page_declares_every_token_it_spends(self) -> None:
        colors = tokens()
        for name in LOAD_BEARING:
            with self.subTest(token=name):
                self.assertIn(name, colors, f"--{name} is missing from the :root block")

    def test_no_colour_literal_lives_outside_the_token_block(self) -> None:
        """A hex outside ``:root`` is a colour the palette cannot repaint."""
        css = stylesheet()
        outside = css.replace(token_block(css), "")
        self.assertEqual(HEX.findall(outside), [])

    def test_the_grid_theme_spends_the_page_tokens(self) -> None:
        """AG Grid's theme is a copy; a copy must not introduce a new colour."""
        declared = set(tokens().values())
        for value in HEX.findall(GRID_THEME.read_text(encoding="utf-8")):
            with self.subTest(value=value):
                self.assertIn(value.lower(), declared)


if __name__ == "__main__":
    unittest.main()
