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
    "surface_container_low": PALETTE["status"],
    "surface_container": PALETTE["surface"],
    "surface_container_high": PALETTE["surface_hi"],
    "surface_container_highest": PALETTE["border"],
    "on_surface": PALETTE["fg"],
    "on_surface_variant": PALETTE["fg_muted"],
    "primary": PALETTE["accent"],
    "on_primary": PALETTE["accent_fg"],
    "primary_container": PALETTE["accent_hi"],
    "on_primary_container": PALETTE["accent_fg"],
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


def _theme(roles: dict[str, str], canvas: dict[str, str], _dark: bool) -> ft.Theme:
    return ft.Theme(
        color_scheme=_scheme(roles),
        canvas_color=canvas["well"],
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


def canvas_colors(dark: bool) -> dict[str, str]:
    return DARK_CANVAS if dark else LIGHT_CANVAS


def check_contrast() -> list[str]:
    """Rows that fail the WCAG bar in either scheme. A test asserts this is empty."""
    fails: list[str] = []
    for name, roles in (("dark", DARK), ("light", LIGHT)):
        for fg in ("on_surface", "on_surface_variant", "primary", "error", "tertiary"):
            for bg in ("surface", "surface_container", "surface_container_low"):
                if contrast(roles[fg], roles[bg]) < CONTRAST_MIN:
                    fails.append(f"{name}: {fg} on {bg}")
    return fails
