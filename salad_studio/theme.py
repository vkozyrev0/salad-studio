#!/usr/bin/env python3
"""Salad Studio visual chrome, one apply path the live app and tests share.

Uses stock ttk (clam) plus explicit tk widget options so Text, Canvas, and
the history-strip buttons match the ttk surfaces. No third-party theme pkg.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

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


def apply_theme(root: tk.Misc) -> ttk.Style:
    """Paint Salad Studio chrome onto `root`. Call as soon as the Tk exists.

    Switches to clam (the only stock ttk theme that honors these options on
    Windows vista/xpnative) then configures the classes the studio uses.
    """
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    _configure_styles(style)
    _configure_root(root)
    return style


def style_text(widget: tk.Text) -> None:
    p = PALETTE
    widget.configure(
        background=p["well"],
        foreground=p["fg"],
        insertbackground=p["accent"],
        selectbackground=p["select_bg"],
        selectforeground=p["select_fg"],
        highlightthickness=1,
        highlightbackground=p["border"],
        highlightcolor=p["accent"],
        relief="flat",
        borderwidth=0,
        padx=8,
        pady=8,
        insertofftime=300,
        insertontime=600,
    )


def style_canvas(widget: tk.Canvas, *, background: str | None = None) -> None:
    p = PALETTE
    widget.configure(
        background=background or p["well"],
        highlightthickness=0,
        highlightbackground=p["bg"],
        borderwidth=0,
    )


def style_tk_button(widget: tk.Button) -> None:
    p = PALETTE
    widget.configure(
        background=p["button"],
        foreground=p["fg"],
        activebackground=p["accent"],
        activeforeground=p["accent_fg"],
        disabledforeground=p["fg_muted"],
        relief="flat",
        borderwidth=0,
        highlightthickness=0,
        padx=12,
        cursor="hand2",
    )


def style_history_strip(strip: tk.Frame) -> None:
    """History strip is raw tk (Frame + Canvas + Button); ttk styles miss it."""
    strip.configure(
        background=PALETTE["bg"],
        highlightthickness=0,
        bd=0,
    )
    style_tk_button(strip.left_btn)
    style_tk_button(strip.right_btn)
    style_canvas(strip.canvas)


def _configure_styles(style: ttk.Style) -> None:
    p = PALETTE
    style.configure(
        ".",
        background=p["bg"],
        foreground=p["fg"],
        troughcolor=p["well"],
        bordercolor=p["border"],
        lightcolor=p["border"],
        darkcolor=p["border"],
        focuscolor=p["accent"],
        font=_UI_FONT,
    )
    style.configure("TFrame", background=p["bg"])
    style.configure(
        "TLabel",
        background=p["bg"],
        foreground=p["fg"],
        font=_UI_FONT,
    )
    style.configure(
        "TCheckbutton",
        background=p["bg"],
        foreground=p["fg"],
        indicatorbackground=p["well"],
        indicatorforeground=p["accent"],
        focuscolor=p["accent"],
        font=_UI_FONT,
    )
    style.map(
        "TCheckbutton",
        background=[("active", p["bg"])],
        foreground=[("active", p["fg"]), ("disabled", p["fg_muted"])],
        indicatorbackground=[
            ("selected", p["accent"]),
            ("active", p["surface_hi"]),
        ],
    )
    style.configure(
        "TLabelframe",
        background=p["bg"],
        foreground=p["fg"],
        bordercolor=p["border"],
        lightcolor=p["border"],
        darkcolor=p["border"],
        relief="groove",
    )
    style.configure(
        "TLabelframe.Label",
        background=p["bg"],
        foreground=p["fg"],
        font=_UI_FONT,
    )
    style.configure(
        "TButton",
        background=p["button"],
        foreground=p["button_fg"],
        bordercolor=p["border"],
        lightcolor=p["button"],
        darkcolor=p["button"],
        focuscolor=p["accent"],
        padding=(12, 6),
        font=_UI_FONT,
        relief="raised",
    )
    style.map(
        "TButton",
        background=[
            ("pressed", p["accent"]),
            ("active", p["surface_hi"]),
            ("disabled", p["surface"]),
        ],
        foreground=[
            ("pressed", p["accent_fg"]),
            ("active", p["fg"]),
            ("disabled", p["fg_muted"]),
        ],
        bordercolor=[("focus", p["accent"])],
    )
    style.configure(
        "Accent.TButton",
        background=p["accent"],
        foreground=p["accent_fg"],
        bordercolor=p["accent"],
        lightcolor=p["accent"],
        darkcolor=p["accent"],
        focuscolor=p["accent_hi"],
        padding=(14, 6),
        font=_UI_FONT,
    )
    style.map(
        "Accent.TButton",
        background=[
            ("pressed", p["accent_hi"]),
            ("active", p["accent_hi"]),
            ("disabled", p["surface"]),
        ],
        foreground=[
            ("pressed", p["accent_fg"]),
            ("active", p["accent_fg"]),
            ("disabled", p["fg_muted"]),
        ],
    )
    style.configure(
        "TEntry",
        fieldbackground=p["well"],
        background=p["well"],
        foreground=p["fg"],
        insertcolor=p["accent"],
        bordercolor=p["border"],
        lightcolor=p["border"],
        darkcolor=p["border"],
        padding=6,
        font=_UI_FONT,
    )
    style.map(
        "TEntry",
        fieldbackground=[("disabled", p["surface"])],
        foreground=[("disabled", p["fg_muted"])],
        bordercolor=[("focus", p["accent"])],
        lightcolor=[("focus", p["accent"])],
    )
    style.configure(
        "TCombobox",
        fieldbackground=p["well"],
        background=p["well"],
        foreground=p["fg"],
        arrowcolor=p["fg"],
        bordercolor=p["border"],
        lightcolor=p["border"],
        darkcolor=p["border"],
        padding=5,
        font=_UI_FONT,
    )
    style.map(
        "TCombobox",
        fieldbackground=[
            ("readonly", p["well"]),
            ("disabled", p["surface"]),
        ],
        foreground=[
            ("readonly", p["fg"]),
            ("disabled", p["fg_muted"]),
        ],
        background=[("readonly", p["well"]), ("active", p["surface_hi"])],
        arrowcolor=[("disabled", p["fg_muted"])],
        bordercolor=[("focus", p["accent"])],
        lightcolor=[("focus", p["accent"])],
    )
    style.configure(
        "TNotebook",
        background=p["bg"],
        borderwidth=0,
        tabmargins=(4, 8, 4, 0),
    )
    style.layout("Hidden.TNotebook.Tab", [])
    style.configure(
        "Hidden.TNotebook",
        background=p["bg"],
        borderwidth=0,
        tabmargins=(0, 0, 0, 0),
    )
    style.configure(
        "TNotebook.Tab",
        background=p["surface"],
        foreground=p["fg_muted"],
        padding=(14, 7),
        bordercolor=p["border"],
        lightcolor=p["surface"],
        darkcolor=p["bg"],
        font=_UI_FONT_TAB,
    )
    # Selected tab sits UP (raised, attached to the page). Unselected drop down.
    # expand = (left, top, right, bottom); selected grows up/sides, not down.
    style.map(
        "TNotebook.Tab",
        background=[
            ("selected", p["bg"]),
            ("active", p["surface_hi"]),
        ],
        foreground=[
            ("selected", p["fg"]),
            ("active", p["fg"]),
        ],
        lightcolor=[("selected", p["surface_hi"])],
        darkcolor=[("selected", p["bg"])],
        expand=[
            ("selected", list(NOTEBOOK_TAB_EXPAND_SELECTED)),
            ("!selected", list(NOTEBOOK_TAB_EXPAND_UNSELECTED)),
        ],
    )
    # The Config page's sub-tabs. The same tab look, with the expand map pinned
    # flat: the raised-selected-tab trick moves the strip by a pixel or two on
    # every selection, which under the pointer reads as the tab jumping away.
    style.configure(
        "Section.TNotebook",
        background=p["bg"],
        borderwidth=0,
        tabmargins=(4, 8, 4, 0),
    )
    style.configure(
        "Section.TNotebook.Tab",
        background=p["surface"],
        foreground=p["fg_muted"],
        padding=(14, 7),
        bordercolor=p["border"],
        lightcolor=p["surface"],
        darkcolor=p["bg"],
        font=_UI_FONT_TAB,
    )
    style.map(
        "Section.TNotebook.Tab",
        background=[
            ("selected", p["bg"]),
            ("active", p["surface_hi"]),
        ],
        foreground=[
            ("selected", p["fg"]),
            ("active", p["fg"]),
        ],
        lightcolor=[("selected", p["surface_hi"])],
        darkcolor=[("selected", p["bg"])],
        expand=[("selected", [0, 0, 0, 0]), ("!selected", [0, 0, 0, 0])],
    )
    style.configure(
        "Treeview",
        background=p["well"],
        fieldbackground=p["well"],
        foreground=p["fg"],
        bordercolor=p["border"],
        lightcolor=p["border"],
        darkcolor=p["border"],
        rowheight=24,
        font=_UI_FONT,
    )
    style.configure(
        "Treeview.Heading",
        background=p["surface_hi"],
        foreground=p["fg"],
        bordercolor=p["border"],
        lightcolor=p["surface_hi"],
        darkcolor=p["surface_hi"],
        relief="flat",
        font=_UI_FONT_HEAD,
        padding=(8, 6),
    )
    style.map(
        "Treeview",
        background=[("selected", p["select_bg"])],
        foreground=[("selected", p["select_fg"])],
    )
    style.map(
        "Treeview.Heading",
        background=[("active", p["button"])],
        relief=[("active", "flat")],
    )
    style.configure(
        "TScrollbar",
        background=p["surface"],
        troughcolor=p["well"],
        bordercolor=p["bg"],
        lightcolor=p["surface"],
        darkcolor=p["surface"],
        arrowcolor=p["fg"],
        relief="flat",
    )
    style.map(
        "TScrollbar",
        background=[("active", p["surface_hi"]), ("pressed", p["accent"])],
        arrowcolor=[("pressed", p["accent_fg"])],
    )
    style.configure(
        "Vertical.TScrollbar",
        background=p["surface"],
        troughcolor=p["well"],
        arrowcolor=p["fg"],
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=p["surface"],
        troughcolor=p["well"],
        arrowcolor=p["fg"],
    )
    # A note line sits on the page's own background: the darker plate it had
    # read as a second, unrelated banner under every panel.
    style.configure(
        "Status.TLabel",
        background=p["bg"],
        foreground=p["fg_muted"],
        padding=(8, 4),
        font=_UI_FONT,
    )


def _configure_root(root: tk.Misc) -> None:
    p = PALETTE
    try:
        root.configure(background=p["bg"])
    except tk.TclError:
        pass
    # Catch raw tk widgets created after apply (Text, Canvas, Listbox popdowns).
    root.option_add("*Background", p["bg"])
    root.option_add("*Foreground", p["fg"])
    root.option_add("*selectBackground", p["select_bg"])
    root.option_add("*selectForeground", p["select_fg"])
    root.option_add("*Text.Background", p["well"])
    root.option_add("*Text.Foreground", p["fg"])
    root.option_add("*Text.insertBackground", p["accent"])
    root.option_add("*Canvas.Background", p["well"])
    root.option_add("*Button.Background", p["button"])
    root.option_add("*Button.Foreground", p["fg"])
    root.option_add("*Button.activeBackground", p["accent"])
    root.option_add("*Button.activeForeground", p["accent_fg"])
    root.option_add("*TCombobox*Listbox.background", p["well"])
    root.option_add("*TCombobox*Listbox.foreground", p["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["select_bg"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["select_fg"])
    root.option_add("*Font", _UI_FONT)
