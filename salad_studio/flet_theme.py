"""The studio's palette as an Flet Material 3 theme, in light and dark.

The dark scheme keeps ``theme.PALETTE``'s values where a Material 3 role
maps onto one. The light scheme is the same hue family with the text and
surface roles swapped and re-checked against WCAG contrast, so ``TEXT_PAIRS``
can be held to the same 4.5:1 bar in both modes.
"""
from __future__ import annotations

import flet as ft

from salad_studio.theme import PALETTE, SPACE, contrast

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

# Canvas colours by role, so the graph does not carry its own copy of the hex.
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

CONTRAST_MIN = 4.5


def _scheme(roles: dict[str, str]) -> ft.ColorScheme:
    return ft.ColorScheme(**roles)


def _typography(roles: dict[str, str]) -> dict[str, ft.TextStyle]:
    """Material 3 text styles at the studio's type scale."""
    ink, muted = roles["on_surface"], roles["on_surface_variant"]
    return {
        "body": ft.TextStyle(size=13, color=ink),
        "body_small": ft.TextStyle(size=12, color=muted),
        "body_strong": ft.TextStyle(size=13, color=ink, weight=ft.FontWeight.W_600),
        "title": ft.TextStyle(size=17, color=ink, weight=ft.FontWeight.W_600),
        "section": ft.TextStyle(size=13, color=muted, weight=ft.FontWeight.W_600),
        "mono": ft.TextStyle(size=13, color=ink, font_family="Consolas"),
        "mono_small": ft.TextStyle(size=12, color=muted, font_family="Consolas"),
    }


# The title capsule. A condensed heavy face at display size does more than a
# bigger weight of the body face: the title reads as a masthead, and the
# number beside it as a plate number. Bahnschrift ships with Windows; the
# fallbacks print the same words if it is ever missing.
TITLE_STYLE = dict(size=30, weight=ft.FontWeight.W_800, font_family="Bahnschrift",
                   font_family_fallback=["Segoe UI Semibold", "Segoe UI"])
PLATE_STYLE = dict(size=26, weight=ft.FontWeight.W_600, font_family="Consolas",
                   font_family_fallback=["Courier New"])


def title_type(roles: dict[str, str]) -> ft.TextStyle:
    """The page name on its capsule: heavy, condensed, the ink of the page."""
    return ft.TextStyle(color=roles["on_surface"], height=1.1, **TITLE_STYLE)


def plate_type(roles: dict[str, str]) -> ft.TextStyle:
    """The page's number: the rose, monospaced, so numbers of equal width align."""
    return ft.TextStyle(color=roles["accent"], height=1.0, **PLATE_STYLE)


def _theme(roles: dict[str, str], canvas: dict[str, str], _dark: bool) -> ft.Theme:
    return ft.Theme(
        color_scheme=_scheme(roles),
        # The canvas is the page area, not the ink: the rail and bar keep bg.
        canvas_color=roles["surface_bright"],
        use_material3=True,
        font_family="Segoe UI",
        text_theme=ft.TextTheme(body_medium=_typography(roles)["body"]),
        card_theme=ft.CardTheme(
            color=canvas["card"],
            elevation=0,
            shape=ft.RoundedRectangleBorder(radius=12),
            margin=0,
        ),
        divider_theme=ft.DividerTheme(color=roles["outline_variant"], thickness=1),
        # The bar at the foot of the window is a bar to Flet, and Flet paints a
        # bar with the primary colour unless told otherwise. It is chrome.
        bottom_appbar_theme=ft.BottomAppBarTheme(
            bgcolor=roles["surface"],
            elevation=0,
        ),
        scrollbar_theme=ft.ScrollbarTheme(
            thumb_color={ft.ControlState.DEFAULT: roles["outline"]},
            track_color={ft.ControlState.DEFAULT: "transparent"},
        ),
        visual_density=ft.VisualDensity.COMPACT,
    )


# Spacing step names the widgets use, so a padding is never a bare number.
GAP = {"xs": SPACE["xs"], "sm": SPACE["sm"], "md": SPACE["md"], "lg": SPACE["lg"]}
PAGE_PAD = GAP["lg"]
CARD_RADIUS = 12
CONTROL_RADIUS = 8


def apply(page: ft.Page) -> None:
    page.theme = _theme(LIGHT, LIGHT_CANVAS, False)
    page.dark_theme = _theme(DARK, DARK_CANVAS, True)
    page.theme_mode = ft.ThemeMode.DARK


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
