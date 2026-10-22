#!/usr/bin/env python3
"""Salad Studio's palette, role maps, type scale and contrast helpers.

No UI toolkit is imported here. The page reads these values through
``/api/theme`` when it needs one the stylesheet does not define, and the
contrast helpers are what a test holds every text pair to.
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
    # The page area under the rail and the bar. A shade above bg so the rail and
    # the action bar read as chrome, a shade below surface so a card still lifts.
    "ground": "#1F2C3B",
    # A tinted fill for the page that is open on the rail. The accent at low
    # opacity would read as a new colour; this is the surface blended toward it.
    "select_tint": "#4A3544",
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
    ("fg_muted", "ground"),
    ("fg", "select_tint"),
    ("fg_muted", "select_tint"),
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


DARK = {
    "surface": PALETTE["bg"],
    "surface_dim": PALETTE["bg"],
    "surface_bright": PALETTE["ground"],
    "surface_container_low": PALETTE["status"],
    "surface_container": PALETTE["surface"],
    "surface_container_high": PALETTE["surface_hi"],
    "surface_container_highest": PALETTE["border"],
    "on_surface": PALETTE["fg"],
    "on_surface_variant": PALETTE["fg_muted"],
    "primary": PALETTE["accent"],
    # A primary fill is the rose with the chrome's own ink on it: black text on
    # a light rose reads as a button, not as disabled text. accent_hi is too
    # close to accent to be a container.
    "on_primary": PALETTE["accent_fg"],
    "primary_container": PALETTE["select_tint"],
    "on_primary_container": PALETTE["fg"],
    "secondary": PALETTE["select_bg"],
    "on_secondary": PALETTE["select_fg"],
    "secondary_container": PALETTE["surface_hi"],
    "on_secondary_container": PALETTE["fg"],
    "tertiary": PALETTE["info"],
    "error": PALETTE["invalid"],
    "on_error": PALETTE["accent_fg"],
    "error_container": "#4A2630",
    "on_error_container": PALETTE["fg"],
    "outline": PALETTE["border"],
    "outline_variant": PALETTE["border"],
}

LIGHT = {
    "surface": "#F6F2EA",
    "surface_bright": "#FBF8F2",
    "surface_container_low": "#FFFFFF",
    "surface_container": "#EFE8DC",
    "surface_container_high": "#E6DDCE",
    "surface_container_highest": "#D9CEBC",
    "on_surface": "#1B2836",
    "on_surface_variant": "#4A5766",
    "primary": "#9B4F61",
    "on_primary": "#FFFFFF",
    "primary_container": "#F3CDD4",
    "on_primary_container": "#3B1820",
    "secondary": "#3A5C4A",
    "on_secondary": "#FFFFFF",
    "secondary_container": "#CFE3D6",
    "on_secondary_container": "#14251B",
    "tertiary": "#2C6A8A",
    "error": "#A63C4E",
    "on_error": "#FFFFFF",
    "error_container": "#F7D7DC",
    "on_error_container": "#3B1820",
    "outline": "#8A96A4",
    "outline_variant": "#C9D0D8",
}

# Canvas colours by role, so a graph or a plate does not carry its own copy.
DARK_CANVAS = {
    "well": PALETTE["well"],
    "card": PALETTE["surface"],
    "card_stroke": PALETTE["border"],
    "text": PALETTE["fg"],
    "muted": PALETTE["fg_muted"],
    "accent": PALETTE["accent"],
    "select": PALETTE["select_bg"],
}

LIGHT_CANVAS = {
    "well": "#FFFFFF",
    "card": "#FFFFFF",
    "card_stroke": "#C9D0D8",
    "text": "#1B2836",
    "muted": "#4A5766",
    "accent": "#9B4F61",
    "select": "#CFE3D6",
}
def _control_colors(roles: dict[str, str]) -> dict[str, str]:
    """Every role a widget reads, so a page never takes a hex from anywhere else."""
    return {
        "on_surface": roles["on_surface"],
        "muted": roles["on_surface_variant"],
        "chrome": roles["surface"],
        "page": roles["surface_bright"],
        "primary_container": roles["primary_container"],
        "on_primary_container": roles["on_primary_container"],
        "on_primary": roles["on_primary"],
        "surface_container": roles["surface_container"],
        "outline": roles["outline"],
        "error": roles["error"],
        "ok": PALETTE["valid"] if roles["surface"] == PALETTE["bg"] else "#2F6B44",
        "warn": PALETTE["warn"] if roles["surface"] == PALETTE["bg"] else "#8A5A12",
    }


def canvas_colors(dark: bool, _dark: bool | None = None) -> dict[str, str]:
    """The page palette. The second argument is kept so ``canvas_colors(True, dark=…)`` still reads."""
    base = DARK_CANVAS if dark else LIGHT_CANVAS
    return {
        **base,
        **_control_colors(DARK if dark else LIGHT),
        "info": PALETTE["info"],
        "unknown": PALETTE["unknown"],
        "valid": PALETTE["valid"],
        "invalid": PALETTE["invalid"],
        "accent": PALETTE["accent"],
        "accent_fg": PALETTE["accent_fg"],
        "surface_hi": PALETTE["surface_hi"],
        "button": PALETTE["button"],
        "select_fg": PALETTE["select_fg"],
    }


def check_contrast() -> list[str]:
    """Rows that fail the WCAG bar in either scheme. A test asserts this is empty."""
    fails: list[str] = []
    for name, roles in (("dark", DARK), ("light", LIGHT)):
        for fg in ("on_surface", "on_surface_variant", "primary", "error", "tertiary"):
            for bg in ("surface", "surface_container", "surface_container_low"):
                if contrast(roles[fg], roles[bg]) < CONTRAST_MIN:
                    fails.append(f"{name}: {fg} on {bg}")
    return fails


def rgb(key: str) -> tuple[int, int, int]:
    """Palette hex → RGB tuple for Pillow (history-strip placeholders)."""
    h = PALETTE[key].lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
