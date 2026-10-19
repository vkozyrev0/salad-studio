"""Small controls every page composes from, so a page never styles a bare widget.

A page builds these, not ``ft.TextField`` directly: the density, the sizes and
the scroll behaviour are the same on all eleven pages, and a test can drive a
page without a client by reading the fields back.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

import flet as ft

from salad_studio import flet_theme

GAP = flet_theme.GAP


def heading(text: str, colors: dict[str, str]) -> ft.Text:
    return ft.Text(text, size=13, weight=ft.FontWeight.W_600, color=colors["muted"])


def label(text: str, colors: dict[str, str], *, size: int = 12) -> ft.Text:
    return ft.Text(text, size=size, color=colors["on_surface"])


def note_text(text: str, colors: dict[str, str], *, level: str = "muted") -> ft.Text:
    return ft.Text(text, size=12, color=colors.get(level, colors["muted"]), selectable=True)


def field(
    value: str = "",
    *,
    label_text: str = "",
    width: float | None = None,
    multiline: bool = False,
    on_change: Callable[[Any], Any] | None = None,
    on_submit: Callable[[Any], Any] | None = None,
    password: bool = False,
    can_reveal: bool = False,
    hint: str = "",
    expand: bool | None = None,
    dense: bool = True,
) -> ft.TextField:
    return ft.TextField(
        value=value,
        label=label_text or None,
        hint_text=hint or None,
        width=width,
        expand=expand,
        multiline=multiline,
        min_lines=3 if multiline else 1,
        max_lines=10 if multiline else 1,
        text_size=13,
        dense=dense,
        password=password,
        can_reveal_password=can_reveal,
        on_change=on_change,
        on_submit=on_submit,
        border_radius=flet_theme.CONTROL_RADIUS,
        content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
    )


def combo(
    options: Sequence[str],
    *,
    value: str = "",
    label_text: str = "",
    width: float | None = 220,
    on_change: Callable[[Any], Any] | None = None,
) -> ft.Dropdown:
    return ft.Dropdown(
        label=label_text or None,
        value=value or None,
        width=width,
        dense=True,
        text_size=13,
        options=[ft.DropdownOption(text=str(o), key=str(o)) for o in options],
        on_select=on_change,
        border_radius=flet_theme.CONTROL_RADIUS,
    )


def button(text: str, on_click: Callable[[Any], Any] | None = None, *, primary: bool = False,
           icon: Any = None, tooltip: str = "") -> ft.Control:
    cls = ft.Button if primary else ft.OutlinedButton
    return cls(text, on_click=on_click, icon=icon, tooltip=tooltip or None)


def flat(text: str, on_click: Callable[[Any], Any], *, tooltip: str = "") -> ft.TextButton:
    return ft.TextButton(text, on_click=on_click, tooltip=tooltip or None)


def check(text: str, value: bool = False, on_change: Callable[[Any], Any] | None = None) -> ft.Checkbox:
    return ft.Checkbox(label=text, value=value, on_change=on_change, visual_density=ft.VisualDensity.COMPACT)


def card(content: ft.Control, colors: dict[str, str], *, title: str = "") -> ft.Container:
    children: list[ft.Control] = []
    if title:
        children.append(heading(title, colors))
    children.append(content)
    return ft.Container(
        content=ft.Column(children, spacing=GAP["sm"], tight=True),
        padding=GAP["md"],
        border_radius=flet_theme.CARD_RADIUS,
        bgcolor=colors["surface_container"],
        expand=True,
    )


def panel(controls: list[ft.Control], *, spacing: int | None = None, scroll: bool = True) -> ft.Column:
    """A page section that scrolls on its own, the way each Config section does."""
    column = ft.Column(controls, spacing=GAP["sm"] if spacing is None else spacing, tight=True)
    if scroll:
        column.scroll = ft.ScrollMode.ALWAYS
    return column


def table(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    on_row: Callable[[int], None] | None = None,
    selected: int | None = None,
    heading_height: int = 36,
) -> ft.DataTable:
    """A grid of text cells. ``on_row`` receives the index of the row clicked."""
    controls = [ft.DataColumn(ft.Text(c, size=12, weight=ft.FontWeight.W_600)) for c in columns]
    data_rows: list[ft.DataRow] = []
    for index, row in enumerate(rows):
        cells: list[ft.DataCell] = []
        for value in row:
            content = value if isinstance(value, ft.Control) else ft.Text(
                "" if value is None else str(value), size=12, selectable=True)
            cells.append(
                ft.DataCell(content, on_tap=(lambda _e, i=index: on_row(i)) if on_row else None,
                            on_double_tap=(lambda _e, i=index: on_row(i)) if on_row else None)
            )
        data_rows.append(ft.DataRow(cells=cells, selected=index == selected))
    return ft.DataTable(
        columns=controls,
        rows=data_rows,
        heading_row_height=heading_height,
        data_row_min_height=28,
        data_row_max_height=34,
        horizontal_margin=8,
        column_spacing=12,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=flet_theme.CONTROL_RADIUS,
    )


def row(controls: list[ft.Control], *, spacing: int | None = None, wrap: bool = False) -> ft.Control:
    """Controls side by side. Wrapping is opt-in: a wrapped Row asks its children to
    lay out unconstrained and the client draws nothing for the line."""
    return ft.Row(controls, spacing=GAP["sm"] if spacing is None else spacing, wrap=wrap,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)


def status_label(text: str = "", colors: dict[str, str] | None = None) -> ft.Text:
    colors = colors or flet_theme.canvas_colors(True)
    return ft.Text(text, size=12, color=colors["muted"])


def split(pairs: list[tuple[str, ft.Control]], *, label_width: int = 150) -> ft.Column:
    """Label-and-control lines, labels in one column so the fields line up."""
    return ft.Column(
        [ft.Row([ft.Container(ft.Text(a, size=12), width=label_width), b],
                vertical_alignment=ft.CrossAxisAlignment.CENTER)
         for a, b in pairs],
        spacing=GAP["xs"],
        tight=True,
    )
