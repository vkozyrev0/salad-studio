#!/usr/bin/env python3
"""Salad Studio visual chrome, one apply path the live app and tests share.

The palette, the contrast helpers, the type scale and the spacing scale. No UI
toolkit is imported here: the Flet theme in ``flet_theme`` reads these values.
"""
from __future__ import annotations


# Prussian watercolor-tin workspace: ink chrome, recessed wells, dusty-rose
# accent (catalog halo), olive selection. Not cream-paper, not neon-on-black.
PALETTE: dict[str, str] = {
    "bg": "#1B2836",
    "surface": "#243344",
    "surface_hi": "#2E4458",
    "well": "#141E28",
    "fg": "#E8DCC8",
    # Muted text clears 4.5:1 on every surface it is drawn on (bg, surface,
    # surface_hi, well, button); the old #8A9AAB read at 3.5:1 on a raised panel.
    "fg_muted": "#A6B0C0",
    # The dusty rose keeps its hue; as text it clears 4.5:1 on the lightest
    # surface (surface_hi), and as a fill it carries the near-black accent_fg.
    # Theme tests hold every TEXT_PAIRS entry to CONTRAST_MIN.
    "accent": "#E39AA9",
    "accent_hi": "#E0A4B0",
    "accent_fg": "#1B2836",
    "select_bg": "#3A5C4A",
    "select_fg": "#E8DCC8",
    "border": "#3A4F63",
    "button": "#2E4458",
    "button_fg": "#E8DCC8",
    "status": "#16202B",
    # Key-check indicator dots (tokens.state_color maps a probe state here),
    # the log level colours and the JSON syntax colours (see SEMANTIC below).
    "valid": "#8FBF9A",
    "invalid": "#D48A9A",
    "unknown": "#94A5B7",
    "warn": "#E0A04A",
    "info": "#7EB8D4",
}

# Names for code that paints without drawing a widget: log levels, JSON
# syntax, instance state words. It reads the palette by role rather than
# carrying its own copy of the hex.
SEMANTIC: dict[str, str] = {
    "ok": PALETTE["valid"],
    "warn": PALETTE["warn"],
    "bad": PALETTE["invalid"],
    "info": PALETTE["info"],
    "neutral": PALETTE["fg_muted"],
    "ink": PALETTE["fg"],
}

# Every pair here is text drawn on that background in the shipped window.
# Muted text is held to 4.5:1 on the lightest surface it appears on.
TEXT_PAIRS: tuple[tuple[str, str], ...] = (
    ("fg", "bg"),
    ("fg", "surface_hi"),
    ("fg", "well"),
    ("fg", "select_bg"),
    ("fg_muted", "bg"),
    ("fg_muted", "surface"),
    ("fg_muted", "surface_hi"),
    ("fg_muted", "well"),
    ("accent", "bg"),
    ("accent", "surface"),
    ("accent_hi", "surface_hi"),
    ("accent_fg", "accent"),
    ("accent_fg", "accent_hi"),
    ("button_fg", "button"),
    ("valid", "well"),
    ("invalid", "well"),
)


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

# ttk class → option → palette key. Tests assert Style.lookup against this
# after calling apply_theme, it is the same mapping apply_theme writes.
STYLE_LOOKUPS: tuple[tuple[str, str, str], ...] = (
    ("TFrame", "background", "bg"),
    ("TLabel", "background", "bg"),
    ("TLabel", "foreground", "fg"),
    ("TButton", "background", "button"),
    ("TButton", "foreground", "button_fg"),
    ("TEntry", "fieldbackground", "well"),
    ("TEntry", "foreground", "fg"),
    ("TCombobox", "fieldbackground", "well"),
    ("TCombobox", "foreground", "fg"),
    ("TNotebook", "background", "bg"),
    ("TNotebook.Tab", "background", "surface"),
    ("TNotebook.Tab", "foreground", "fg_muted"),
    ("Treeview", "background", "well"),
    ("Treeview", "foreground", "fg"),
    ("Treeview", "fieldbackground", "well"),
    ("Treeview.Heading", "background", "surface_hi"),
    ("Treeview.Heading", "foreground", "fg"),
    ("TScrollbar", "background", "surface"),
    ("TScrollbar", "troughcolor", "well"),
    ("TCheckbutton", "background", "bg"),
    ("TCheckbutton", "foreground", "fg"),
    ("TLabelframe", "background", "bg"),
    ("TLabelframe.Label", "background", "bg"),
    ("TLabelframe.Label", "foreground", "fg"),
    ("Status.TLabel", "background", "bg"),
    ("Status.TLabel", "foreground", "fg_muted"),
    ("Accent.TButton", "background", "accent"),
    ("Accent.TButton", "foreground", "accent_fg"),
)

_UI_FONT = ("Segoe UI", 10)
_UI_FONT_TAB = ("Segoe UI", 10)
_UI_FONT_HEAD = ("Segoe UI Semibold", 9)
_UI_FONT_TITLE = ("Segoe UI Semibold", 12)
_UI_FONT_UI_BOLD = ("Segoe UI Semibold", 10)
_UI_FONT_MONO = ("Consolas", 10)
_UI_FONT_MONO_SMALL = ("Consolas", 9)

# The widget layer names fonts through these; a new size is added here, not
# inline, so one place owns the type scale (10 body, 12 title, mono 10/9).
FONT_UI = _UI_FONT
FONT_UI_BOLD = _UI_FONT_UI_BOLD
FONT_TITLE = _UI_FONT_TITLE
FONT_HEAD = _UI_FONT_HEAD
FONT_MONO = _UI_FONT_MONO
FONT_MONO_SMALL = _UI_FONT_MONO_SMALL

# One spacing step for the pads that separate a block from its neighbour. The
# window is a fixed desktop surface, so four steps cover it: tight inside a
# control row (4), between a label and its field (8), between blocks (12), and
# around a whole page (16).
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16}

# WCAG AA for normal-size text. Theme tests assert every TEXT_PAIRS entry.
CONTRAST_MIN = 4.5
# Selected tab grows up/sides (raised, attached to the page); unselected drop down.
NOTEBOOK_TAB_EXPAND_SELECTED = (1, 2, 1, 0)
NOTEBOOK_TAB_EXPAND_UNSELECTED = (0, 0, 0, 2)


def rgb(key: str) -> tuple[int, int, int]:
    """Palette hex → RGB tuple for Pillow (history-strip placeholders)."""
    h = PALETTE[key].lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
