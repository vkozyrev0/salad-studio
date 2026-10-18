#!/usr/bin/env python3
"""Salad Studio Windows UI: the window, its eleven tabs and the prompt graph pane.

The tabs are **Config**, **Prompt Settings**, **Tokens**, **LoRAs**, **Prompt
Editor**, **Prompt Assist**, **Prompt Catalog**, **Import**, **Prompt History**,
**Queue** and **Logs**, plus the always-visible history strip. The **Config**
page is the deployment page, in four sub-tabs in the order a deployment runs
them: the profiles and the checkpoints each one serves, the two container
images with the settings a host needs, each config's Salad policy (image, GPU
classes, country codes and the startup/readiness probes), and the vast.ai
instances with the engine choice that decides whether Generate renders on a
Salad group or on one of them. This module is the UI layer: it holds the
widgets and the wiring and calls the other seven layers (`TAB_ORDER` is the
one list the notebook, the sidebar and the tab lookup all follow).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any
from urllib.parse import urlparse

_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from salad_studio import ai_helper, comfy_import, generator, graph_view, image_deploy, json_highlight, lora_store, profiles, prompt_catalog, prompt_history, ref_check, request_json, salad_status, studio_log, studio_meta, theme, tokens, ui_state, vast  # noqa: E402
# Top-level, like studio_log: the generator and this module must hold the same
# salad_queue object, or a job this app submits is not a job the generator's
# type checks accept.
import hostings  # noqa: E402
import salad_queue  # noqa: E402
from salad_studio.history_strip import HistoryStrip  # noqa: E402
from salad_studio.profiles import SaladProfile  # noqa: E402

# The Eldermark art output tree (generated plates). It lives outside this tool's
# repo, so it is a setting, not a relative walk-up: ELDERMARK_ART overrides it.
ART = Path(os.environ.get("ELDERMARK_ART", r"C:\Users\vkozy\repos\lifesim-design\art"))
OUT_DIR = ART / "salad_studio"
PROBE_GLOB = "salad_probe_klein_*.jpg"
TAB_ORDER = (
    "Config",
    "Prompt Settings",
    "Tokens",
    "LoRAs",
    "Prompt Editor",
    "Prompt Assist",
    "Prompt Catalog",
    "Import",
    "Prompt History",
    "Queue",
    "Logs",
)
# The Config page's sections, in the order a deployment runs them: the profile
# and the checkpoints routing reads, the image a host runs, the Salad group's
# policy for that image, and the vast.ai hosts as the other target. A section is
# a row, so reordering the page is reordering this tuple.
CONFIG_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("profile", "Profile", "_build_profile_section"),
    ("images", "Images", "_build_images_section"),
    ("policy", "Salad group", "_build_policy_section"),
    ("vast", "Vast.ai", "_build_vast_section"),
)
PAGE_OPENING_WIDTH = 1180
PAGE_OPENING_HEIGHT = 720
LORA_CHECK_COLUMNS = 3
# The Windows call that answers "where may a window be put": the desktop minus
# the taskbar (see _screen_work_area).
_SPI_GETWORKAREA = 0x0030
# The narrowest wrap the status line takes, so a window dragged almost shut does
# not fold a sentence into a column one word wide (see _wrap_status).
_STATUS_MIN_WRAP = 240
# The four grids whose page scrolls, as (column, heading, width, takes the
# room a wider page leaves). None of them is handed to the Treeview as
# stretching: the page that holds them scrolls, so it is narrower than the
# whole grid, and a stretching Treeview re-fits every column into it - which
# would take the widths the page declares away and leave the tree's own bar
# with nothing to reach (see _page_keeps_its_own_size). The columns a table
# marks as taking the room are the ones a wider page grows, by hand, in
# _keep_grid_filling: the same rule, minus the shrinking half.
CATALOG_GRID_COLUMNS: tuple[tuple[str, str, int, bool], ...] = (
    ("when", "Added", 130, False),
    ("name", "Short name", 180, False),
    ("description", "Description", 260, True),
    ("preview", "Prompt", 380, True),
    ("stats", "Graph", 300, True),
)
HISTORY_GRID_COLUMNS: tuple[tuple[str, str, int, bool], ...] = (
    ("when", "When", 140, False),
    ("profile", "Profile", 100, False),
    ("preview", "Prompt", 480, True),
    ("stats", "Graph", 380, True),
)
QUEUE_GRID_COLUMNS: tuple[tuple[str, str, int, bool], ...] = (
    ("id", "#", 40, False),
    ("profile", "Profile", 110, False),
    ("state", "State", 90, False),
    ("attempts", "Attempts", 70, False),
    ("status", "Last status", 90, False),
    ("reason", "Reason", 260, True),
    ("request", "Request", 200, True),
    ("finished", "Finished", 70, False),
)
VAST_GRID_COLUMNS: tuple[tuple[str, str, int, bool], ...] = (
    ("use", "Use", 40, False),
    ("label", "Label", 130, False),
    ("endpoint", "Address", 220, True),
    ("image", "Image", 300, True),
    ("state", "State", 90, False),
    ("gpu", "GPU", 130, True),
)
# The rent panel's result table: the ids are ``vast.offer_cells`` keys, in the
# order that function writes them, so a test can pin the two together.
VAST_OFFER_GRID_COLUMNS: tuple[tuple[str, str, int, bool], ...] = (
    ("gpu", "GPU", 120, True),
    ("price", "$/hr", 70, False),
    ("perf", "Perf", 60, False),
    ("value", "Perf/$", 75, False),
    ("vram", "VRAM GB", 70, False),
    ("disk", "Disk GB", 70, False),
    ("cuda", "CUDA", 55, False),
    ("down", "Down", 70, False),
    ("up", "Up", 60, False),
    ("reliability", "Reliability", 80, False),
    ("location", "Location", 130, True),
    ("offer", "Offer", 80, False),
)
# The LoRA grid's columns, in the order they are shown: the verified dot first,
# because that is the state a row is looked up for.
LORA_COLUMNS: tuple[str, ...] = (
    "verified",
    "id",
    "name",
    "version",
    "model",
    "source",
    "filename",
)


def lora_grid_row(item: dict) -> dict:
    """One library row as the grid shows it: the cell text per column, and the row's data.

    ``verified`` is a dot rather than the words yes/no, and the row's tag carries
    the colour, so which state a row is in is readable off the widget itself.
    """
    source = item.get("source") or {}
    lid = str(item.get("id") or "")
    name = str(item.get("name") or "")
    return {
        "id": lid,
        "name": name,
        "verified": bool(item.get("verified")),
        "item": item,
        "cells": {
            "verified": "●",
            "id": lid,
            "name": name,
            "version": lora_store.version_label(item),
            "model": lora_store.family_label(item),
            "source": str(source.get("host") or ""),
            "filename": lora_store.comfy_lora_name(item),
        },
    }


def lora_rows_matching(rows: list[dict], needle: str) -> list[dict]:
    """The rows whose name contains the typed text, anywhere in the name, any case."""
    text = str(needle or "").strip().lower()
    if not text:
        return list(rows)
    return [row for row in rows if text in row["name"].lower()]


def lora_rows_sorted(
    rows: list[dict], column: str = "", reverse: bool = False
) -> list[dict]:
    """The rows ordered by one column, the way a heading click asks for.

    Every column sorts on the text it shows, so the order matches what can be
    read off the grid; the verified column sorts on the state itself, with the
    unverified rows first in ascending order because those are the ones to look
    at. An unknown column leaves the rows as they came.
    """
    if column not in LORA_COLUMNS:
        return list(rows)

    def key(row: dict) -> tuple:
        if column == "verified":
            return (1 if row["verified"] else 0, row["name"].lower())
        return (str(row["cells"].get(column) or "").lower(),)

    return sorted(rows, key=key, reverse=bool(reverse))
QUEUE_EMPTY_TEXT = "The queue is empty. Press Generate to submit a render."
HISTORY_EMPTY_TEXT = "No prompts yet. Every Generate stores its request here."
CATALOG_EMPTY_TEXT = (
    "The catalog is empty. Copy the Prompt Editor's request in, or load one back."
)
QUEUE_CANCEL_NOTE = (
    "Cancel drops a request that has not been submitted yet. A request the "
    "container has already accepted keeps rendering."
)


def queue_request_label(request: Any) -> str:
    """One line for what a queued request will POST (never the token)."""
    if isinstance(request, dict):
        url = str(request.get("url") or request.get("gateway") or "")
        host = url.split("//", 1)[-1].split("/", 1)[0] if url else ""
        size = request.get("bytes")
        bits = [bit for bit in (host, f"{size} bytes" if size else "") if bit]
        if bits:
            return "  ".join(bits)
    return str(request or "")[:120]


def vast_refusal_note(refused: list[tuple[str, str]]) -> str:
    """What the Vast.ai page did not add, grouped by the store's reason.

    ``refused`` holds one ``(typed text, reason)`` per address the store turned
    down. Grouping by the reason keeps a phrase the user meant as one address
    from repeating the same sentence once per word, while still naming every
    word that was not added.
    """
    groups: dict[str, list[str]] = {}
    for text, reason in refused:
        groups.setdefault(reason, []).append(text)
    return " ".join(f"{', '.join(texts)}: {reason}" for reason, texts in groups.items())


class SaladStudio(tk.Tk):
    def __init__(self, *, show: bool | None = None) -> None:
        """``show=False`` (or SALAD_STUDIO_HIDDEN in the environment) builds the
        whole window but never maps it, so a test run cannot flash windows."""
        super().__init__()
        self.withdraw()
        self._show_on_open = bool(show if show is not None else True) and not os.environ.get(
            "SALAD_STUDIO_HIDDEN"
        )
        theme.apply_theme(self)
        self.title("Salad Studio")
        self._opened_size_held = False
        self._opened_width = 0
        self._opened_height = 0
        self.bind("<Map>", self._hold_opened_size, add="+")
        self._busy = False
        self._gen_jobs = 0
        # One line for every render, shared with the generator: a press while a
        # render is in flight waits its turn here instead of being dropped. The
        # lifecycle handle lets the queue read the container's state and stop it
        # once it has sat idle past the metadata document's timeout, and the
        # ledger is what lets a reopened app still know what to stop.
        self.gen_queue = salad_queue.SaladQueue(
            on_log=self._on_queue_log,
            lifecycle=salad_status.ContainerLifecycle(self._salad_api_key),
            ledger_path=salad_queue.LEDGER_PATH,
        )
        self._idle_check_busy = False
        self._helper_busy = False
        self._token_probe_busy = False
        self._vast_fetch_busy = False
        # One search lock and one create lock. The create lock is shared by the
        # rent button, Replace if destroyed now, and Generate's automatic path,
        # because all three spend money on the same account.
        self._vast_search_busy = False
        self._vast_create_busy = False
        self._vast_offers: dict[str, dict] = {}
        # The config page owns the images and the vast.ai hosts, so both stores
        # are read before it is built: its image picker offers their tags.
        self._image_settings = image_deploy.load_settings()
        self._vast_doc = vast.load_doc()
        self._token_detail: dict[str, str] = {}
        self._lora_vars: dict[str, tk.BooleanVar] = {}
        self._lora_checks: dict[str, ttk.Checkbutton] = {}
        self._pending_selected: list[str] = list(lora_store.DEFAULT_KLEIN_LORA_IDS)
        # Every callback this window schedules for itself, so Destroy can cancel
        # what is left (see _later), and the ones Tk would not take.
        self._pending_afters: set[str] = set()
        self._dropped_afters: list[str] = []
        # True from the start of destroy(), before any child <Destroy> runs.
        self._closing = False
        self._syncing_editor = False
        self._syncing_loras = False
        self._applying_profile = False
        self._json_after: str | None = None
        self._salad_poll_after: str | None = None
        self._salad_check_busy = False
        # The last key error the status check reported, so the 15 s poll logs it
        # once rather than every tick (cleared when a probe runs again).
        self._salad_key_error = ""
        self._log_secrets_cache: list[str] | None = None
        self._log_secrets_stamp: tuple[int, int] | None = None
        self._gen_poll_after: str | None = None
        self._gen_t0 = 0.0
        self._gen_last_note = ""
        self._nav_btns: dict[str, tk.Button] = {}
        # The nav button the keyboard is on, so its own state can be painted
        # beside the page it names (see _on_nav_focus).
        self._nav_focused: tk.Button | None = None
        # Every page that scrolls, the frame its content lives in, and the page
        # the pointer is over. One wheel handler and one focus handler serve
        # them all (see _scrollable_page): the pointer claims a page's wheel on
        # <Enter> and gives it back on <Leave>, so no page can take another
        # page's scrolling, and a control that takes focus is scrolled into view
        # so the keyboard follows the mouse.
        self._scroll_canvases: dict[tk.Frame, tk.Canvas] = {}
        self._scroll_bodies: dict[tk.Frame, ttk.Frame] = {}
        self._scroll_wheel_page: tk.Frame | None = None
        self.bind_all("<MouseWheel>", self._on_page_wheel, add="+")
        self.bind_all("<FocusIn>", self._on_page_focus, add="+")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=0)
        self.rowconfigure(3, weight=0)

        self._build_action_bar()

        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        nav = ttk.Frame(body, padding=(0, 0, 8, 0))
        nav.grid(row=0, column=0, sticky="nsw")
        self._nav = nav

        self._build_notebook(body)

        self._build_config_tab()
        self._build_prompt_settings_tab()
        self._build_tokens_tab()
        self._build_loras_tab()
        self._build_editor_tab()
        self._build_prompt_helper_tab()
        self._build_prompt_catalog_tab()
        self._build_import_tab()
        self._build_prompt_history_tab()
        self._build_queue_tab()
        self._build_logs_tab()
        self.nb.add(self._config, text="Config")
        self.nb.add(self._settings, text="Prompt Settings")
        self.nb.add(self._tokens, text="Tokens")
        self.nb.add(self._loras, text="LoRAs")
        self.nb.add(self._editor, text="Prompt Editor")
        self.nb.add(self._helper, text="Prompt Assist")
        self.nb.add(self._catalog_page, text="Prompt Catalog")
        self.nb.add(self._import, text="Import")
        self.nb.add(self._prompt_hist_page, text="Prompt History")
        self.nb.add(self._queue_page, text="Queue")
        self.nb.add(self._logs, text="Logs")
        self._build_nav_buttons()

        self.strip = HistoryStrip(self, on_open=self._open_path, thumb_size=(140, 140))
        self.strip.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.status = tk.StringVar(value="Ready")
        # A refusal is a whole sentence, and the window can be 1024 px wide: the
        # line wraps to the room the window gives it instead of running off the
        # right edge, where the action its tail names would be hidden.
        self._status_wrap = 0
        self.status_lbl = ttk.Label(
            self, textvariable=self.status, anchor="w", style="Status.TLabel"
        )
        self.status_lbl.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 6))
        self.bind("<Configure>", self._wrap_status, add="+")

        self._load_profiles_into_ui()
        self._refresh_lora_lists()
        restored = self._restore_ui_state()
        self._apply_restored_profile()
        if not restored:
            self._sync_editor()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._hold_opened_size()
        self._later_idle(self._place_editor_sash)
        self._refresh_history()
        if self._show_on_open:
            self.deiconify()
        self.log("info", "Salad Studio started")
        self.log("info", f"token store {tokens.LOCAL_PATH}")
        self.log("info", f"gateway {self.var_gateway.get().strip() or '(empty)'}")
        self.log(
            "info",
            f"graph {lora_store.graph_id(self.var_graph.get())}  "
            f"{self.var_width.get()}x{self.var_height.get()}  steps {self.var_steps.get()}",
        )
        self._later(500, lambda: self._check_salad_status(silent=True))
        self._schedule_salad_poll()
        self.bind("<Destroy>", self._on_destroy_cancel_poll, add="+")
        self.nb.bind("<<NotebookTabChanged>>", self._on_notebook_tab, add="+")
        self._refresh_nav()

    def _wrap_status(self, _event=None) -> None:
        """Wrap the status line to the window, so a long sentence stays readable.

        The width is read from the window, not from the event: a child's
        ``<Configure>`` reaches this binding too (Tk's default bindtags carry it
        up to the toplevel), and a child's width is not the room the line has.
        The wrap is only written when it changes, so a relayout does not loop.
        """
        width = int(self.winfo_width())
        if width <= 1:
            return
        want = max(_STATUS_MIN_WRAP, width - 16)
        if want != self._status_wrap:
            self._status_wrap = want
            self.status_lbl.configure(wraplength=want)

    def _build_action_bar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 8, 8, 6))
        bar.grid(row=0, column=0, sticky="ew")
        self._action_bar = bar
        self.gen_btn = ttk.Button(
            bar, text="Generate", command=self._on_generate, style="Accent.TButton"
        )
        self.gen_btn.pack(side="left")
        self.gen_editor_btn = self.gen_btn
        ttk.Button(bar, text="Clean gallery", command=self._on_clean_gallery).pack(
            side="left", padx=(12, 0)
        )
        self.var_gen_state = tk.StringVar(value="Idle")
        self.gen_state_lbl = ttk.Label(bar, textvariable=self.var_gen_state)
        self.gen_state_lbl.pack(side="left", padx=(12, 0))
        self._build_replica_cluster(bar)

    def _build_replica_cluster(self, bar) -> None:
        """The Salad probe and the compact container-count strip, right-aligned."""
        holder = ttk.Frame(bar)
        holder.pack(side="right")
        self._replica_holder = holder
        self.check_salad_btn = ttk.Button(
            holder, text="Check Salad status", command=self._check_salad_status
        )
        self.check_salad_btn.pack(side="left")
        self.var_salad_status = tk.StringVar(value="…")
        self._refresh_replica_strip()

    def _refresh_replica_strip(self) -> None:
        """The three dot+count segments, rebuilt whenever the profile set changes.

        One strip for every configured profile: the counts are sums, so the
        number of segments does not grow with the number of profiles. It is
        refilled from the last probe's snapshots, so adding or removing a profile
        keeps the numbers instead of blanking them.
        """
        holder = getattr(self, "_replica_holder", None)
        if holder is None:
            return
        old = getattr(self, "_strip", None)
        if old is not None:
            old.destroy()
        p = theme.PALETTE
        strip = tk.Frame(holder, bg=p["bg"])
        strip.pack(side="left", padx=(10, 0))
        self._strip = strip
        self._strip_dots: list[tk.Label] = []
        self._strip_vars: list[tk.StringVar] = []
        for i, color in enumerate(salad_status.STRIP_COLORS):
            if i:
                tk.Label(
                    strip, text="|", bg=p["bg"], fg=p["fg_muted"], font=("Segoe UI", 11)
                ).pack(side="left", padx=6)
            dot = tk.Label(strip, text="●", bg=p["bg"], fg=color, font=("Segoe UI", 11))
            dot.pack(side="left")
            var = tk.StringVar(value="0")
            tk.Label(
                strip,
                textvariable=var,
                bg=p["bg"],
                fg=p["fg"],
                font=("Segoe UI Semibold", 11),
            ).pack(side="left", padx=(3, 0))
            self._strip_dots.append(dot)
            self._strip_vars.append(var)
        self._fill_strip(getattr(self, "_last_snaps", None) or {})

    def _fill_strip(self, snaps: dict[str, dict]) -> None:
        """Write the three counts the probe's snapshots add up to."""
        counts = salad_status.strip_counts(snaps)
        for var, n in zip(getattr(self, "_strip_vars", []), counts):
            var.set(str(n))

    def _build_notebook(self, body: ttk.Frame) -> None:
        # 0 skips the hidden notebook. The string "n" is a Tcl script, and
        # tk_focusNext then dies with `invalid command name "n"`.
        self.nb = ttk.Notebook(body, style="Hidden.TNotebook", takefocus=0)
        self.nb.grid(row=0, column=1, sticky="nsew")

    def _build_nav_buttons(self) -> None:
        for child in self._nav.winfo_children():
            child.destroy()
        self._nav_btns = {}
        self._nav_focused = None
        p = theme.PALETTE
        for name in TAB_ORDER:
            btn = tk.Button(
                self._nav,
                text=name,
                anchor="w",
                command=lambda n=name: self._goto_tab(n),
                width=16,
                font=("Segoe UI", 10),
                bd=0,
                # The ring is drawn in accent_hi while the button holds focus and
                # in the button's own colour otherwise, so the keyboard can see
                # where it is without the column shifting as focus moves.
                highlightthickness=1,
                highlightbackground=p["surface"],
                highlightcolor=p["accent_hi"],
                padx=12,
                pady=6,
                cursor="hand2",
                background=p["surface"],
                foreground=p["fg"],
                activebackground=p["accent"],
                activeforeground=p["accent_fg"],
                disabledforeground=p["fg_muted"],
                relief="flat",
            )
            # theme hides the notebook's own tabs, so these buttons are the only
            # page switcher there is: the keys a button answers everywhere else
            # in the app have to work here too, or the switcher is mouse-only.
            btn.bind("<Return>", lambda _e, n=name: self._goto_tab(n))
            btn.bind("<space>", lambda _e, n=name: self._goto_tab(n))
            btn.bind("<FocusIn>", lambda _e, b=btn: self._on_nav_focus(b, True))
            btn.bind("<FocusOut>", lambda _e, b=btn: self._on_nav_focus(b, False))
            btn.pack(fill="x", pady=(0, 2))
            self._nav_btns[name] = btn

    def _on_nav_focus(self, btn: tk.Button, focused: bool) -> None:
        """Remember which nav button the keyboard is on, and repaint the column.

        The ring Tk draws from ``highlightcolor`` says focus is on a button; the
        repaint also lightens its face, so which one is readable at a glance and
        not only by looking for a one-pixel edge.
        """
        self._nav_focused = btn if focused else None
        self._refresh_nav()

    def _goto_tab(self, name: str) -> None:
        for i, label in enumerate(TAB_ORDER):
            if label == name:
                try:
                    self.nb.select(i)
                except tk.TclError:
                    return
                break
        self._refresh_nav()

    def _refresh_nav(self) -> None:
        """Repaint the sidebar: the page each button names, and where focus is."""
        current = ""
        try:
            current = str(self.nb.tab(self.nb.select(), "text") or "")
        except tk.TclError:
            pass
        p = theme.PALETTE
        for name, btn in self._nav_btns.items():
            on = name == current
            focused = self._nav_focused is btn
            if on:
                background = p["accent"]
            elif focused:
                # Focus is the only thing to see when the button is not the page
                # shown, so it lightens the face rather than hiding behind the
                # ring Tk draws from highlightcolor.
                background = p["surface_hi"]
            else:
                background = p["surface"]
            try:
                btn.configure(
                    background=background,
                    foreground=p["accent_fg"] if on else p["fg"],
                    font=("Segoe UI Semibold", 10) if on else ("Segoe UI", 10),
                    highlightbackground=p["accent_hi"] if focused else p["surface"],
                )
            except tk.TclError:
                pass

    # -- scrollable pages -------------------------------------------------
    def _scrollable_page(self, page: ttk.Frame) -> ttk.Frame:
        """Give ``page`` scrollbars, and return the frame its content belongs in.

        The Config page's pattern, shared by every page whose content can be
        taller or wider than a window: a canvas holds the page, a scrollbar on
        each axis drives it, and the wheel is claimed only while the pointer is
        over that page, so no page takes another's scrolling. The content frame
        is stretched to the canvas when it is smaller, so a grid with a weight
        still fills the window, and the canvas scrolls when the content is larger
        on either axis. Both axes matter: a page wider than its canvas puts its
        right-hand controls past the edge, and a vertical-only canvas has no way
        to bring them back. A control that takes focus is scrolled into view, so
        the keyboard reaches everything the mouse can.

        The notebook page and the frame its content lives in are two frames with
        the canvas between them, so a widget's own page relationship is
        unchanged: ``_config`` is the Config page, and the three pages whose
        content kept the attribute name it always had are
        ``_catalog``/``_catalog_page``, ``_prompt_hist``/``_prompt_hist_page``
        and ``_queue``/``_queue_page``.
        """
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        holder = ttk.Frame(page)
        holder.grid(row=0, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        # Tk's canvas default is what sizes the window, and it is smaller than any page.
        canvas = tk.Canvas(
            holder,
            highlightthickness=0,
            background=theme.PALETTE["bg"],
            width=PAGE_OPENING_WIDTH,
            height=PAGE_OPENING_HEIGHT,
        )
        vscroll = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        hscroll = ttk.Scrollbar(holder, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        body = ttk.Frame(canvas, padding=10)
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
            add="+",
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(
                window,
                width=max(body.winfo_reqwidth(), e.width),
                height=max(body.winfo_reqheight(), e.height),
            ),
            add="+",
        )
        canvas.bind("<Enter>", lambda _e: self._claim_wheel(page), add="+")
        canvas.bind("<Leave>", lambda _e: self._release_wheel(page), add="+")
        self._scroll_canvases[page] = canvas
        self._scroll_bodies[page] = body
        return body

    def _claim_wheel(self, page) -> None:
        """The pointer is on ``page``: that page owns the wheel while it is there."""
        self._scroll_wheel_page = page

    def _release_wheel(self, page) -> None:
        """The pointer left ``page``: it hands the wheel back, and only its own."""
        if self._scroll_wheel_page is page:
            self._scroll_wheel_page = None

    def _keep_grid_filling(self, page, tree, columns) -> None:
        """Grow a grid's room-taking columns to fill a page wider than the grid.

        The three grids are handed ``stretch=False`` columns so that a page
        *narrower* than the grid keeps the widths its table declares and the
        tree's own horizontal bar reaches the rest (see ``_scrollable_page``).
        That rule also stopped the columns growing on a page *wider* than the
        grid, which is what they did before, and left dead room to the right of
        the last column. This is the grow-only half of it: only the columns the
        table marks as taking the room grow, and the widths are recomputed from
        the table on every pass, so a window narrowed again gets the declared
        widths back and the bar takes over.
        """
        canvas = self._scroll_canvases.get(page)
        if canvas is None:
            return
        # The widths the table declares, read once: a re-fit recomputes from
        # these, never from the widths it just wrote, or each pass would grow
        # what the last one grew. ``#0`` is the tree column the History grid
        # shows; where it is shown it is part of the span and never takes the
        # extra room.
        declared = {col: int(tree.column(col, "width")) for col in tree["columns"]}
        if "tree" in str(tree.cget("show")):
            declared["#0"] = int(tree.column("#0", "width"))
        span = sum(declared.values())
        fills = [col for col, _head, _width, fill in columns if fill]
        if not fills:
            return
        # The width the last pass was fitted to. Growing the columns does not
        # move the tree (its width comes from the page, not from its columns),
        # so a repeat of the same width has nothing left to do - and re-fitting
        # it would undo the growth, because the grown columns leave no room.
        fitted = {"width": 0}

        def refit(_event=None) -> None:
            width = int(tree.winfo_width())
            if width <= 1 or width == fitted["width"]:
                # Not laid out yet, or the same width the last pass fitted.
                return
            fitted["width"] = width
            viewport = int(canvas.winfo_width())
            if viewport > 1:
                # The room a wider page leaves can never be more than the page
                # itself: a tree that somehow reports more is not grown past it.
                width = min(width, viewport)
            room = width - span
            if room <= 0:
                for col, base in declared.items():
                    tree.column(col, width=base)
                return
            share, rest = divmod(room, len(fills))
            for index, col in enumerate(fills):
                tree.column(col, width=declared[col] + share + (1 if index < rest else 0))

        tree.bind("<Configure>", refit, add="+")

    def _scroll_page(self, page, event) -> None:
        """Scroll ``page``'s canvas, one unit per wheel notch."""
        canvas = self._scroll_canvases.get(page)
        if canvas is None:
            return
        steps = int(-event.delta / 120) if getattr(event, "delta", 0) else 0
        if steps:
            canvas.yview_scroll(steps, "units")

    def _on_page_wheel(self, event) -> None:
        """Scroll whichever scrollable page the pointer is over, and no other."""
        page = self._scroll_wheel_page
        if page is not None:
            self._scroll_page(page, event)

    def _on_page_focus(self, event=None) -> None:
        """Scroll the page that owns the control taking focus, into view."""
        widget = getattr(event, "widget", None)
        if widget is None:
            return
        for page, canvas in self._scroll_canvases.items():
            if self._on_page(widget, page):
                self._reveal(canvas, page, widget)
                return

    @staticmethod
    def _on_page(widget, page) -> bool:
        """Whether ``widget`` is ``page`` or lives inside it."""
        node = widget
        while node is not None:
            if node is page:
                return True
            node = getattr(node, "master", None)
        return False

    def _reveal(self, canvas, page, widget) -> None:
        """Scroll ``canvas`` the least amount that brings ``widget`` into view.

        A control off an edge that takes focus (by Tab, or by the page's own
        code) must not stay off-screen: the keyboard reaches what the wheel can,
        on either axis, so a page wider than its canvas is still navigable.
        """
        if page not in self._scroll_bodies:
            return
        try:
            bbox = canvas.bbox("all")
            height = int(canvas.winfo_height())
            if bbox is None or height <= 1:
                return
            total = int(bbox[3])
            top = int(canvas.yview()[0] * total)
            y = int(widget.winfo_rooty()) - int(canvas.winfo_rooty()) + top
            bottom = y + int(widget.winfo_height())
            width = int(canvas.winfo_width())
            total_w = int(bbox[2])
            left = int(canvas.xview()[0] * total_w)
            x = int(widget.winfo_rootx()) - int(canvas.winfo_rootx()) + left
            right = x + int(widget.winfo_width())
        except tk.TclError:
            return
        if bottom > top + height:
            target = bottom - height
        elif y < top:
            target = y
        else:
            target = None
        if target is not None:
            target = max(0, min(target, max(0, total - height)))
            canvas.yview_moveto(target / total if total else 0.0)
        if right > left + width:
            target_w = right - width
        elif x < left:
            target_w = x
        else:
            target_w = None
        if target_w is not None:
            target_w = max(0, min(target_w, max(0, total_w - width)))
            canvas.xview_moveto(target_w / total_w if total_w else 0.0)

    def _build_config_tab(self) -> None:
        """The config page: profiles, images, Salad policy, and the vast.ai hosts.

        One page owns everything a render needs to be aimed. Four sub-tabs hold
        the sections in the order a deployment runs them: the profiles and the
        checkpoints each one serves, the two container images with the settings
        a host needs, each config's Salad policy, and the vast.ai instances with
        the engine choice.
        """
        self._config = ttk.Frame(self.nb)
        self._config.columnconfigure(0, weight=1)
        self._config.rowconfigure(0, weight=1)
        self._config_tabs = ttk.Notebook(self._config, style="Section.TNotebook")
        self._config_tabs.grid(row=0, column=0, sticky="nsew")
        self._config_section_pages: dict[str, ttk.Frame] = {}
        self._config_section_bodies: dict[str, ttk.Frame] = {}
        self.var_config_note = tk.StringVar(value="")
        for key, label, builder in CONFIG_SECTIONS:
            page = ttk.Frame(self._config_tabs)
            body = self._scrollable_page(page)
            # The label column keeps its natural width and the field column takes
            # the rest, as the one-page layout did.
            body.columnconfigure(1, weight=1)
            self._config_tabs.add(page, text=label)
            self._config_section_pages[key] = page
            self._config_section_bodies[key] = body
            getattr(self, builder)(body)
        ttk.Label(
            self._config, textvariable=self.var_config_note, wraplength=760
        ).grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 6))
        self._config_tabs.bind(
            "<<NotebookTabChanged>>", self._on_config_section_tab, add="+"
        )

    def _on_config_section_tab(self, _e=None) -> None:
        """Refresh the Config section that just became visible (local reads only)."""
        try:
            selected = self._config_tabs.select()
            page = self._config_tabs.nametowidget(selected)
        except tk.TclError:
            return
        key = next(
            (k for k, candidate in self._config_section_pages.items() if candidate is page),
            "",
        )
        if key == "profile":
            self._refresh_checkpoint_list()
        elif key == "images":
            self._refresh_images_page()
        elif key == "vast":
            self._refresh_vast_page()

    def _build_profile_section(self, body) -> None:
        """The active profile, its target, its URL, and the checkpoints routing reads."""
        self.var_name = tk.StringVar()
        self.var_gateway = tk.StringVar()
        self.var_profile_mode = tk.StringVar(value=hostings.DEFAULT)

        ttk.Label(body, text="Active profile").grid(
            row=0, column=0, sticky="w"
        )
        self.profile_combo = ttk.Combobox(
            body, textvariable=self.var_name, state="normal"
        )
        self.profile_combo.grid(row=0, column=1, sticky="ew", padx=6)
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_select_profile())
        btns = ttk.Frame(body)
        btns.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Button(btns, text="Save profile", command=self._save_profile).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(btns, text="Add profile", command=self._on_add_profile).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(btns, text="Delete profile", command=self._delete_profile).pack(
            side="left"
        )
        ttk.Label(body, text="Target").grid(row=2, column=0, sticky="w", pady=3)
        target = ttk.Frame(body)
        target.grid(row=2, column=1, sticky="w", pady=3)
        for adapter in hostings.ADAPTERS:
            ttk.Radiobutton(
                target,
                text=adapter.label,
                value=adapter.key,
                variable=self.var_profile_mode,
                command=self._on_profile_mode,
            ).pack(side="left", padx=(0, 16))
        self.lbl_gateway = ttk.Label(
            body, text=hostings.BY_KEY[hostings.DEFAULT].url_label
        )
        self.lbl_gateway.grid(row=3, column=0, sticky="w", pady=3)
        gw_row = ttk.Frame(body)
        gw_row.grid(row=3, column=1, sticky="ew", padx=6, pady=3)
        gw_row.columnconfigure(0, weight=1)
        ttk.Entry(gw_row, textvariable=self.var_gateway).grid(row=0, column=0, sticky="ew")
        self.btn_use_selected = ttk.Button(
            gw_row,
            text="Use the selected instance",
            command=self._on_use_selected_instance,
            state="disabled",
        )
        self.btn_use_selected.grid(row=0, column=1, padx=(6, 0))

        box = ttk.LabelFrame(
            body, text="Checkpoints this profile serves", padding=6
        )
        box.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        box.columnconfigure(0, weight=1)
        self.checkpoint_tree = ttk.Treeview(
            box, columns=("checkpoint", "family"), show="headings", height=7
        )
        for col, heading, width, stretch in (
            ("checkpoint", "Checkpoint", 420, True),
            ("family", "Family", 120, False),
        ):
            self.checkpoint_tree.heading(col, text=heading)
            self.checkpoint_tree.column(col, width=width, stretch=stretch, anchor="w")
        cscroll = ttk.Scrollbar(box, orient="vertical", command=self.checkpoint_tree.yview)
        self.checkpoint_tree.configure(yscrollcommand=cscroll.set)
        self.checkpoint_tree.grid(row=0, column=0, columnspan=2, sticky="nsew")
        cscroll.grid(row=0, column=1, sticky="ns")
        add = ttk.Frame(box)
        add.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        add.columnconfigure(1, weight=1)
        ttk.Label(add, text="Add checkpoint").grid(row=0, column=0, sticky="w")
        self.var_checkpoint = tk.StringVar()
        self.checkpoint_combo = ttk.Combobox(
            add,
            textvariable=self.var_checkpoint,
            values=request_json.UNET_LABELS,
            state="normal",
        )
        self.checkpoint_combo.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(add, text="Add", command=self._on_add_checkpoint).grid(row=0, column=2)
        ttk.Button(add, text="Remove selected", command=self._on_remove_checkpoint).grid(
            row=0, column=3, padx=(6, 0)
        )
        ttk.Label(
            body,
            text="Some images carry more than one unet, so a profile's checkpoints may "
            "span families; the page warns that the image must carry every family it "
            "lists. Routing sends a graph to the profile that lists the "
            "checkpoint it loads; the queue runs one line per profile, so two profiles "
            "render at the same time. Each profile owns its Salad policy on the Salad group sub-tab. "
            "Replica status and the Salad probe are in the top bar; size, steps, CFG, "
            "seed, graph, scheduler and LoRA selection are on Prompt Settings.",
            wraplength=760,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _profile_mode(self) -> str:
        """The hosting the Target radio names, or Salad when it names none."""
        mode = str(self.var_profile_mode.get() or "").strip().lower()
        return mode if mode in hostings.BY_KEY else hostings.DEFAULT

    def _sync_hosting_controls(self, mode: str = "") -> None:
        """Point the URL label and the pick button at the selected hosting."""
        hosting = hostings.BY_KEY.get(mode or self._profile_mode()) or hostings.BY_KEY[
            hostings.DEFAULT
        ]
        lbl = getattr(self, "lbl_gateway", None)
        if lbl is not None:
            lbl.configure(text=hosting.url_label)
        btn = getattr(self, "btn_use_selected", None)
        if btn is not None:
            btn.configure(state="normal" if hosting.can_pick else "disabled")

    def _on_profile_mode(self) -> None:
        """The Target radio: the URL label and the pick button follow."""
        mode = self._profile_mode()
        self._sync_hosting_controls(mode)
        self._repair_hosting_url(mode)

    @staticmethod
    def _is_salad_gateway(url: str) -> bool:
        """True when the URL names a Salad gateway host, not a vast instance."""
        host = (urlparse(url or "").hostname or "").lower()
        return (
            host == "salad.com"
            or host.endswith(".salad.cloud")
            or host.endswith(".salad.com")
        )

    def _vast_endpoints(self) -> set[str]:
        doc = getattr(self, "_vast_doc", None) or {}
        return {
            str(row.get("endpoint") or "").strip()
            for row in doc.get("instances") or []
            if str(row.get("endpoint") or "").strip()
        }

    def _repair_hosting_url(self, mode: str) -> None:
        """Never leave a URL that names the other hosting in the target box.

        A vast mode holding a Salad gateway POSTs to the gateway with no key;
        a Salad mode holding an instance URL sends the Salad key to it.
        """
        url = (self.var_gateway.get() or "").strip()
        if not url:
            if mode == "vast":
                row = self._vast_active()
                if row is not None:
                    self.var_gateway.set(str(row["endpoint"]))
            return
        if mode == "vast" and self._is_salad_gateway(url):
            row = self._vast_active()
            self.var_gateway.set(str(row["endpoint"]) if row is not None else "")
        elif mode != "vast" and url in self._vast_endpoints():
            self.var_gateway.set("")

    def _on_use_selected_instance(self) -> None:
        """Fill the URL from the hosting's own store, or say there is none."""
        adapter = hostings.BY_KEY.get(self._profile_mode()) or hostings.BY_KEY[
            hostings.DEFAULT
        ]
        if not adapter.can_pick:
            return
        url, reason = adapter(self).pick_url()
        if not url:
            self._config_status(reason)
            self.log("warn", reason)
            return
        self.var_gateway.set(url)
        self._config_status(f"Using {url}")

    def _config_status(self, text: str) -> None:
        self.var_config_note.set(text)
        self.status.set(text)

    def _refresh_profile_choices(self, select: str = "") -> None:
        """The combo lists every profile the store holds, so N profiles are usable."""
        try:
            names = sorted(profiles.load_all())
        except Exception:
            names = []
        self.profile_combo["values"] = names
        if select:
            self.var_name.set(select)

    def _refresh_checkpoint_list(self, profile: SaladProfile | None = None) -> None:
        """Show the selected profile's checkpoint list and the family each belongs to."""
        tree = getattr(self, "checkpoint_tree", None)
        if tree is None:
            return
        tree.delete(*tree.get_children())
        if profile is None:
            name = (self.var_name.get() or "").strip()
            profile = profiles.load_all().get(name)
        if profile is None:
            return
        for i, unet in enumerate(profile.checkpoints):
            tree.insert(
                "", "end", iid=str(i), values=(unet, profiles.checkpoint_family(unet))
            )

    def _selected_checkpoint(self) -> str:
        tree = getattr(self, "checkpoint_tree", None)
        if tree is None:
            return ""
        selection = tree.selection()
        if not selection:
            return ""
        values = tree.item(selection[0], "values")
        return str(values[0]) if values else ""

    def _on_add_profile(self) -> None:
        """Add the profile named in the box, seeded from the metadata document."""
        allp = profiles.load_all()
        base = (self.var_name.get() or "").strip() or "profile"
        name, n = base, 2
        while name in allp:
            name = f"{base}{n}"
            n += 1
        p = profiles.default_profile(name)
        p.mode = self._profile_mode()
        typed_gateway = self.var_gateway.get().strip()
        if typed_gateway:
            p.gateway = typed_gateway
        profiles.upsert(p)
        profiles.set_active(name)
        self._refresh_profile_choices(name)
        self._apply_profile(p)
        self._refresh_replica_strip()
        self.status.set(f"Added profile {name}")
        self.log(
            "ok",
            f"added profile {name}  gateway={p.gateway}  "
            f"checkpoints={len(p.checkpoints)}",
        )

    def _on_add_checkpoint(self) -> None:
        """Add the typed checkpoint to the selected profile's list and save it."""
        name = (self.var_name.get() or "").strip()
        p = profiles.load_all().get(name)
        if p is None:
            self._config_status(f"No saved profile named {name!r}; press Add profile first")
            return
        raw = (self.var_checkpoint.get() or "").strip()
        if not raw:
            self._config_status("Type a checkpoint filename or pick a label first")
            return
        unet = request_json.normalize_unet(raw)
        reason = profiles.add_checkpoint(p, unet)
        if reason:
            self._config_status(reason)
            messagebox.showinfo("Salad Studio", reason)
            return
        profiles.upsert(p)
        self.var_checkpoint.set("")
        self._refresh_checkpoint_list(p)
        warning = profiles.mixed_family_reason(p)
        if warning:
            # Allowed, not refused: an image that carries both families can serve
            # the list. The warning is what keeps a one-family image honest.
            self.status.set(f"{p.name} lists {len(p.checkpoints)} checkpoint(s)")
            self.log("warn", warning)
            messagebox.showwarning("Salad Studio", warning)
        else:
            self.status.set(f"{p.name} lists {len(p.checkpoints)} checkpoint(s)")
        self.log("ok", f"profile {p.name} checkpoint added: {unet}")

    def _on_remove_checkpoint(self) -> None:
        """Drop the selected checkpoint from the profile's list and save it."""
        name = (self.var_name.get() or "").strip()
        p = profiles.load_all().get(name)
        if p is None:
            self._config_status(f"No saved profile named {name!r}")
            return
        unet = self._selected_checkpoint()
        if not unet:
            self._config_status("Select a checkpoint in the list first")
            return
        if not profiles.remove_checkpoint(p, unet):
            return
        profiles.upsert(p)
        self._refresh_checkpoint_list(p)
        self.status.set(f"{p.name} lists {len(p.checkpoints)} checkpoint(s)")
        self.log("warn", f"profile {p.name} checkpoint removed: {unet}")

    def _build_prompt_settings_tab(self) -> None:
        """The prompt-shaping knobs split off Config, under the same attribute names."""
        self._settings = ttk.Frame(self.nb)
        body = self._scrollable_page(self._settings)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(20, weight=1)
        self.var_graph = tk.StringVar(value=lora_store.graph_label("klein"))
        self.var_width = tk.StringVar(value="1024")
        self.var_height = tk.StringVar(value="1024")
        self.var_steps = tk.StringVar(value="20")
        self.var_cfg = tk.StringVar(value="5")
        self.var_seed = tk.StringVar(value="1")
        r = 0
        for label, var in (
            ("Width", self.var_width),
            ("Height", self.var_height),
            ("Steps", self.var_steps),
            ("CFG", self.var_cfg),
            ("Seed", self.var_seed),
        ):
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(body, textvariable=var).grid(
                row=r, column=1, sticky="ew", padx=6, pady=3
            )
            r += 1
        ttk.Label(body, text="Graph").grid(row=r, column=0, sticky="w")
        self.graph_combo = ttk.Combobox(
            body,
            textvariable=self.var_graph,
            values=lora_store.GRAPH_CHOICES,
            state="readonly",
        )
        self.graph_combo.grid(row=r, column=1, sticky="w", padx=6)
        r += 1
        ttk.Label(body, text="Scheduler").grid(row=r, column=0, sticky="w")
        self.var_scheduler = tk.StringVar(value="Flux2 (Klein)")
        self.sched_combo = ttk.Combobox(
            body,
            textvariable=self.var_scheduler,
            values=("Flux2 (Klein)", "Simple (Civitai)"),
            state="readonly",
            width=22,
        )
        self.sched_combo.grid(row=r, column=1, sticky="w", padx=6)
        r += 1
        ttk.Label(body, text="Checkpoint").grid(row=r, column=0, sticky="w")
        self.var_unet = tk.StringVar(value="Base 9B")
        self.unet_combo = ttk.Combobox(
            body,
            textvariable=self.var_unet,
            values=request_json.UNET_LABELS,
            state="readonly",
            width=22,
        )
        self.unet_combo.grid(row=r, column=1, sticky="w", padx=6)
        r += 1
        ttk.Label(body, text="LoRAs").grid(row=r, column=0, sticky="nw", pady=(8, 0))
        self._lora_inner = ttk.Frame(body)
        self._lora_inner.grid(row=r, column=1, sticky="nsew", padx=6, pady=(8, 0))
        for c in range(LORA_CHECK_COLUMNS):
            self._lora_inner.columnconfigure(c, weight=1)
        for var in (
            self.var_width,
            self.var_height,
            self.var_steps,
            self.var_cfg,
            self.var_seed,
        ):
            var.trace_add("write", lambda *_a: self._sync_editor())
        self.var_graph.trace_add("write", lambda *_a: self._on_graph_change())
        self.var_scheduler.trace_add("write", lambda *_a: self._sync_editor())
        self.var_unet.trace_add("write", lambda *_a: self._sync_editor())

    def _schedule_salad_poll(self) -> None:
        if self._salad_poll_after is not None:
            try:
                self.after_cancel(self._salad_poll_after)
            except Exception:
                pass
        self._salad_poll_after = self._later(15_000, self._poll_salad_status)

    def _poll_salad_status(self) -> None:
        self._salad_poll_after = None
        self._check_salad_status(silent=True)
        # The existing tick also redraws the queue page, so a job that started
        # or finished since the last poll shows up without a manual Refresh, and
        # asks the queue to stop a container that has sat idle past the metadata
        # document's timeout. No new timer, and no new button.
        self._refresh_queue_page()
        self._run_idle_check()
        self._schedule_salad_poll()

    def _run_idle_check(self) -> None:
        """Ask the queue about idle containers, off the Tk thread.

        The check resolves a group over the API and may then POST a stop, so it
        cannot run inside the tick: the window would freeze for as long as those
        calls take. One check at a time.
        """
        if self._idle_check_busy:
            return
        self._idle_check_busy = True

        def work() -> None:
            try:
                stopped = self.gen_queue.idle_check()
                if stopped:
                    self.log("info", f"Idle stop asked for {', '.join(stopped)}")
            except Exception as e:  # noqa: BLE001 - a check must not kill the tick
                self.log("warn", f"Queue idle check failed: {e}")
            finally:
                self._idle_check_busy = False

        threading.Thread(target=work, daemon=True).start()

    def destroy(self) -> None:
        # Before any child <Destroy> binding. A binding that calls after()
        # while children are going registers a command Tk then deletes, and
        # the queued script prints "invalid command name".
        self._closing = True
        super().destroy()

    def _on_destroy_cancel_poll(self, e=None) -> None:
        # Child Destroy events bubble to the Tk root via bindtags. Ignore
        # them or LoRA/tab rebuilds cancel the 15s Salad poll forever.
        if e is not None:
            w = getattr(e, "widget", None)
            if w is not None and w is not self and str(w) != str(self):
                return
        self._closing = True
        if self._salad_poll_after is not None:
            try:
                self.after_cancel(self._salad_poll_after)
            except Exception:
                pass
            self._salad_poll_after = None
        self._cancel_gen_tick()
        # Everything else this window scheduled for itself, so nothing fires
        # against a window Tk has already torn down.
        for handle in list(self._pending_afters):
            try:
                self.after_cancel(handle)
            except Exception:
                pass
        self._pending_afters.clear()

    def after(self, ms: int, func=None, *args):
        """Tk's own scheduler, tracked so a Destroy cancels what it left pending.

        ``tkwry`` (the WebView2 embed) schedules its poll tick and its initial
        page load with ``after`` on the toplevel rather than through ``_later``,
        and the pane attaches even in a withdrawn window. A callback still
        pending when the window goes makes Tk print ``invalid command name`` for
        each one — two per window, 361 lines in one suite run — which buries a
        real teardown error. Recording the ids here lets
        ``_on_destroy_cancel_poll`` cancel them with everything else.
        """
        if func is None:
            # ``after(ms)`` with no callback is a sleep: there is nothing to cancel.
            return tk.Misc.after(self, ms)
        if self._closing:
            # Destroy has started, so the cancel pass has already run or is
            # about to delete every Tcl command. Registering one now leaves
            # its script queued and Tk prints "invalid command name".
            self._dropped_afters.append(f"after({ms}): window is closing")
            return None
        box: list[str] = []

        def run() -> None:
            if box:
                self._pending_afters.discard(box[0])
            func(*args)

        handle = tk.Misc.after(self, ms, run)
        box.append(handle)
        self._pending_afters.add(handle)
        return handle

    def _later(self, ms: int, func) -> str | None:
        """Schedule ``func`` for this window, and remember the id.

        Every callback this window schedules for itself goes through here. A
        pending ``after`` that fires after the window is gone makes Tk print
        ``invalid command name`` for each one — thousands of lines in a test run,
        which buries a real teardown error — and a worker that schedules one after
        the main loop has ended raises instead. ``_on_destroy_cancel_poll``
        cancels what is left, and a schedule that cannot be made is recorded in
        ``_dropped_afters`` rather than vanishing: a worker's handoff that never
        runs is a state reset that never happens.
        """
        box: list[str] = []

        def run() -> None:
            # A zero-delay callback can run on the main thread before the thread
            # that scheduled it gets the id back, so the id is read out of a box
            # that exists before the schedule is made.
            if box:
                self._pending_afters.discard(box[0])
            func()

        try:
            handle = self.after(ms, run)
        except RuntimeError as e:
            # The main thread is not in the Tk loop: a worker finishing during
            # teardown, or a test that pumps update() instead of running one.
            self._dropped_afters.append(f"after({ms}): {e}")
            return None
        if handle is None:
            return None
        box.append(handle)
        self._pending_afters.add(handle)
        return handle

    def _later_idle(self, func) -> str | None:
        """``_later`` with ``after_idle``: run once the window is otherwise idle."""
        box: list[str] = []

        def run() -> None:
            if box:
                self._pending_afters.discard(box[0])
            func()

        try:
            handle = self.after_idle(run)
        except RuntimeError as e:
            self._dropped_afters.append(f"after_idle: {e}")
            return None
        if handle is None:
            return None
        box.append(handle)
        self._pending_afters.add(handle)
        return handle

    def _cancel_gen_tick(self) -> None:
        if self._gen_poll_after is not None:
            try:
                self.after_cancel(self._gen_poll_after)
            except Exception:
                pass
            self._gen_poll_after = None

    def _schedule_gen_tick(self) -> None:
        self._cancel_gen_tick()
        self._gen_poll_after = self._later(2000, self._tick_gen)

    def _tick_gen(self) -> None:
        self._gen_poll_after = None
        if not self._busy:
            return
        elapsed = max(0, int(time.monotonic() - self._gen_t0))
        note = (self._gen_last_note or "").strip()
        if len(note) > 80:
            note = note[:77] + "…"
        line = f"Generating… {elapsed}s"
        if note:
            line = f"{line}  {note}"
        waiting = max(0, self._gen_jobs - 1)
        if waiting:
            line = f"{line}  (+{waiting} queued)"
        self.var_gen_state.set(line)
        # The request is in the queue from the moment it is submitted, and its
        # row has to be on the page while the container it routes to comes up:
        # a cold start is minutes, and an empty Queue page reads as "the press
        # did nothing". The 15 s tick alone is too slow for that first row.
        self._refresh_queue_page()
        self._schedule_gen_tick()

    def _set_salad_word(self, word: str) -> None:
        """The one status word the dispatch decision reads. The strip shows counts.

        Generate's button state does not follow it: the press is the gate. A
        queued or in-flight request and a booting replica both leave the button
        live, and a press that cannot be dispatched — a replica that is gone, or
        a group the badge says is stopped, because this app never starts a
        container — is refused with a reason when it is made (``_on_generate``).
        """
        self.var_salad_status.set(word)

    def _status_targets(self) -> list[tuple[str, str]]:
        """(profile name, gateway) for every configured profile.

        One probe per profile, so any number of profiles is active at once, and
        the strip counts all of their containers. A profile with no gateway falls
        back to the published one for a built-in name; anything else with no
        gateway has nothing to probe.
        """
        try:
            allp = profiles.load_all()
        except Exception:
            allp = {}
        out: list[tuple[str, str]] = []
        for name in sorted(allp):
            gw = (allp[name].gateway or "").strip() or profiles.fallback_gateway(name)
            if gw:
                out.append((name, gw))
        return out

    def _check_salad_status(self, silent: bool = False) -> None:
        gw = self.var_gateway.get().strip()
        if not gw:
            # Empty Config gateway: mark the active word Down, then fall through
            # on purpose. The probe below still counts the containers of every
            # profile gateway (see _status_targets).
            self._set_salad_word("Down")
        if self._salad_check_busy:
            if not silent:
                self.status.set("Check Salad status: a check is already running")
            return
        # The key is read here, on the main thread, so a missing one can be
        # reported at once: a worker's handoff through ``_later`` is dropped when
        # there is no main loop to take it (see ``_later``), and a missing key is
        # the one status failure the user can fix from inside the app.
        try:
            key = self._salad_api_key()
        except (OSError, FileNotFoundError) as e:
            # No key is not a container that is down. The sentence names the cause
            # and the fix, so it goes where the user already looks instead of being
            # swallowed by the probe's own error handling.
            self._report_salad_key_error(str(e))
            return
        self._salad_check_busy = True
        self._set_check_salad_enabled(False)
        # The Refresh Salad logs button reads the same probe this check owns, so
        # it goes down with it and comes back when the check is done.
        self._set_salad_logs_enabled(False)
        targets = self._status_targets()
        active_gw = gw

        def work() -> None:
            snaps: dict[str, dict] = {}
            for pid, gwx in targets:
                try:
                    snaps[pid] = salad_status.snapshot_gateway(gwx, key)
                except Exception:
                    continue

            def done() -> None:
                self._salad_check_busy = False
                self._set_check_salad_enabled(True)
                self._set_salad_logs_enabled(True)
                self._salad_key_error = ""
                active_word = "Unknown"
                first_pid = targets[0][0] if targets else ""
                self._last_snaps = dict(snaps)
                self._fill_strip(snaps)
                for pid, gwx in targets:
                    info = snaps.get(pid) or {}
                    word = str(info.get("word") or "Down")
                    # A group found running is followed, never adopted: the probe
                    # cannot tell a container this app started from one the user
                    # started by hand, and only the app's own start (or a request
                    # it dispatched) may hand a container to the idle stop.
                    if str((info.get("group") or {}).get("status") or "").lower() == "running":
                        self.gen_queue.refresh(pid, gwx)
                    if active_gw and gwx and active_gw.rstrip("/") == gwx.rstrip("/"):
                        active_word = word
                    if not active_gw and pid == first_pid:
                        active_word = word
                if active_gw:
                    for pid, gwx in targets:
                        if gwx.rstrip("/") == active_gw.rstrip("/") and pid in snaps:
                            active_word = str(snaps[pid].get("word") or active_word)
                            lines = snaps[pid].get("log_lines") or []
                            if lines:
                                self._set_salad_logs("\n".join(lines))
                            break
                self._set_salad_word(active_word)
                if not silent and snaps:
                    self.log("debug", f"Salad {active_word}")

            self._later(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _report_salad_key_error(self, message: str) -> None:
        """The status check could not run at all: there is no Salad key to probe with.

        The badge reads a word of its own instead of the checking placeholder or a
        container state, and the sentence the key reader builds — the one that
        names the Tokens tab and the file — goes to the Logs. The status line is
        left alone: it carries events ("retrying", a refusal), and a standing
        condition that rewrote it would erase the last thing the user did. The log
        line is written once per distinct message, because the poll runs every 15 s.
        """
        self._salad_check_busy = False
        self._set_check_salad_enabled(True)
        self._last_snaps = {}
        self._fill_strip({})
        self._set_salad_word("No key")
        if getattr(self, "_salad_key_error", "") != message:
            self._salad_key_error = message
            self.log("error", f"Salad status unavailable: {message}")

    def _on_notebook_tab(self, _e=None) -> None:
        try:
            tab = self.nb.tab(self.nb.select(), "text")
        except tk.TclError:
            return
        self._refresh_nav()
        if tab == "Config":
            self._refresh_checkpoint_list()
            self._refresh_images_page()
            self._refresh_vast_page()
        if tab == "Tokens":
            self._probe_tokens()
        if tab == "Prompt Assist":
            self._refresh_prompt_helper()
        if tab == "Prompt Catalog":
            self._refresh_prompt_catalog()
        if tab == "Queue":
            self._refresh_queue_page()
        if tab == "Logs":
            # Opening the page re-reads the pane. The busy guard is silent here:
            # a tab switch is not a press, and the button says why when it is.
            self._check_salad_status(silent=True)

    def _build_policy_section(self, body) -> None:
        """The selected config's Salad policy: its group's image, placement, probes.

        The policy belongs to the config (it is stored on the profile), so Load
        reads that config's live group and Apply PATCHes that config's group.
        Nothing here is window-wide: selecting another config swaps these fields.
        """
        section = ttk.LabelFrame(
            body, text="Salad policy for this config", padding=8
        )
        section.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        section.columnconfigure(1, weight=1)
        self._policy_section = section
        ttk.Label(
            section,
            text="Load reads this config's live group (portal edits included); Apply "
            "PATCHes that group in Salad, not the Docker image. Both act on the "
            "selected config, and Save profile stores these fields with it.",
            wraplength=760,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.var_pol_group = tk.StringVar(value="")
        # What the last Load read about that group; stored with the config so the
        # Group line survives a reload.
        self._pol_group_name = ""
        self._pol_group_version: Any = None
        ttk.Label(section, text="Group").grid(row=1, column=0, sticky="w")
        ttk.Label(section, textvariable=self.var_pol_group).grid(
            row=1, column=1, sticky="w", padx=6
        )
        bar = ttk.Frame(section)
        bar.grid(row=2, column=0, columnspan=4, sticky="w", pady=6)
        ttk.Button(bar, text="Load from Salad", command=self._load_salad_policy).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(bar, text="Apply to Salad", command=self._apply_salad_policy).pack(
            side="left"
        )
        self._pol_vars: dict[str, dict[str, tk.StringVar]] = {}
        self._pol_explain: dict[str, tk.StringVar] = {}
        # Side by side: the Config page carries the checkpoints too, and the two
        # probe boxes stacked made the window taller than the screen.
        probes_row = ttk.Frame(section)
        probes_row.grid(row=3, column=0, columnspan=4, sticky="ew", pady=6)
        probes_row.columnconfigure(0, weight=1, uniform="probe")
        probes_row.columnconfigure(1, weight=1, uniform="probe")
        for i, (kind, title) in enumerate(
            (("startup", "Startup probe"), ("readiness", "Readiness probe"))
        ):
            box = ttk.LabelFrame(probes_row, text=title, padding=8)
            box.grid(row=0, column=i, sticky="nsew", padx=(0, 6) if i == 0 else (6, 0))
            box.columnconfigure(1, weight=1)
            fields = {}
            for j, (key, label) in enumerate(
                (
                    ("path", "Path"),
                    ("port", "Port"),
                    ("initial_delay_seconds", "Initial delay (s)"),
                    ("period_seconds", "Period (s)"),
                    ("timeout_seconds", "Timeout (s)"),
                    ("failure_threshold", "Failure threshold (1–20)"),
                )
            ):
                ttk.Label(box, text=label).grid(row=j, column=0, sticky="w", pady=2)
                var = tk.StringVar()
                ttk.Entry(box, textvariable=var, width=18).grid(
                    row=j, column=1, sticky="ew", padx=6, pady=2
                )
                var.trace_add(
                    "write", lambda *_a, k=kind: self._refresh_probe_explain(k)
                )
                fields[key] = var
            self._pol_vars[kind] = fields
            explain = tk.StringVar()
            self._pol_explain[kind] = explain
            ttk.Label(
                box,
                textvariable=explain,
                wraplength=340,
                justify="left",
            ).grid(row=len(fields), column=0, columnspan=2, sticky="w", pady=(6, 0))
            self._refresh_probe_explain(kind)
        r = 4
        extra = ttk.LabelFrame(section, text="Placement / image", padding=8)
        extra.grid(row=r, column=0, columnspan=4, sticky="ew", pady=6)
        extra.columnconfigure(1, weight=1)
        ttk.Label(extra, text="Image").grid(row=0, column=0, sticky="w")
        self.var_pol_image = tk.StringVar()
        # A picker over the tags the Images page describes, still editable: a
        # group may run a tag this app has never been told about.
        self.pol_image_box = ttk.Combobox(extra, textvariable=self.var_pol_image)
        self.pol_image_box.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Label(
            extra,
            text="a tag from the Images sub-tab, or any other tag",
            style="Status.TLabel",
        ).grid(row=0, column=2, columnspan=2, sticky="w")
        self._refresh_image_refs()
        self.var_pol_us = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            extra, text="US-only (country_codes=['us'])", variable=self.var_pol_us
        ).grid(row=1, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(extra, text="GPU classes").grid(row=2, column=0, sticky="nw")
        self._pol_gpu_frame = ttk.Frame(extra)
        self._pol_gpu_frame.grid(row=2, column=1, sticky="w", padx=6)
        self._pol_gpu_vars: dict[str, tk.BooleanVar] = {}
        self._pol_gpu_names: dict[str, str] = {}
        ttk.Button(
            extra,
            text="Reallocate instance (new node)…",
            command=self._reallocate_instance,
        ).grid(row=3, column=1, sticky="w", padx=6, pady=(8, 0))
        r += 1

    def _refresh_probe_explain(self, kind: str) -> None:
        var = self._pol_explain.get(kind)
        fields = self._pol_vars.get(kind)
        if var is None or fields is None:
            return
        raw = {k: v.get().strip() for k, v in fields.items()}
        var.set(salad_status.explain_probe(kind, raw))

    def _policy_from_form(self) -> dict:
        """The policy the fields show, in the shape the store and Salad use."""
        out = {"startup": {}, "readiness": {}}
        for kind, fields in self._pol_vars.items():
            out[kind] = {k: v.get().strip() for k, v in fields.items()}
        out["image"] = self.var_pol_image.get().strip()
        out["country_codes"] = ["us"] if self.var_pol_us.get() else []
        out["group_name"] = self._pol_group_name
        out["version"] = self._pol_group_version
        if self._pol_gpu_vars:
            out["gpu_classes"] = [
                gid for gid, var in self._pol_gpu_vars.items() if var.get()
            ]
        return out

    def _policy_to_form(self, policy: dict) -> None:
        self._pol_group_name = str(policy.get("group_name") or "")
        self._pol_group_version = policy.get("version")
        self.var_pol_group.set(
            f"{self._pol_group_name}  v{self._pol_group_version or '?'}"
            if self._pol_group_name
            else ""
        )
        for kind in ("startup", "readiness"):
            src = policy.get(kind) or {}
            for k, var in self._pol_vars[kind].items():
                var.set(str(src.get(k, "")))
        self.var_pol_image.set(str(policy.get("image") or ""))
        codes = [str(c).lower() for c in (policy.get("country_codes") or [])]
        self.var_pol_us.set("us" in codes)
        selected = set(str(x) for x in (policy.get("gpu_classes") or []))
        for gid, var in self._pol_gpu_vars.items():
            var.set(gid in selected)

    def _show_policy(self, policy: dict) -> None:
        """Show a policy in the fields, with no network call.

        The GPU classes the policy carries are rendered by id until a Load brings
        the live list's names; that is what keeps selecting a config from
        silently dropping a class.
        """
        self._fill_gpu_checkboxes(
            [], [str(x) for x in (policy.get("gpu_classes") or [])]
        )
        self._policy_to_form(policy)

    def _policy_for_display(self, prof: SaladProfile) -> dict:
        """What the fields show for a config before its group is read.

        Every field, from the config's own stored policy where it has a value and
        the metadata document's documented settings for its family where it does
        not: a config that was never loaded — or whose group cannot be read —
        still shows an image and all twelve probe fields rather than blanks.
        """
        return salad_status.resolved_policy(
            getattr(prof, "policy", None), None, profiles.seeded_policy(prof)
        )

    def _recheck_policy(self, prof: SaladProfile) -> None:
        """Re-read the selected config's group and refill the fields from it.

        Every selection does this, the window's first one included: the fields a
        config shows are its own group's current values, not whatever the last
        config left behind. It fills the fields only — no config's stored record
        is written here — and a read that fails leaves the fields as they are.
        The read is scheduled rather than started here, so it runs after the
        selection has settled and never inside the widget work that selected it.
        """
        try:
            self._later(0, lambda: self._load_salad_policy(prof, quiet=True))
        except tk.TclError:
            return

    def _store_policy(self, policy: dict) -> None:
        """Write the fields shown onto the selected config's record.

        Applying to Salad is what makes those fields that group's policy, so the
        config keeps what it runs; Save profile writes them the same way.
        """
        name = (self.var_name.get() or "").strip()
        allp = profiles.load_all()
        prof = allp.get(name)
        if prof is None:
            return
        prof.policy = dict(policy)
        profiles.upsert(prof)

    def _fill_gpu_checkboxes(self, classes: list[dict], selected: list[str]) -> None:
        frame = self._pol_gpu_frame
        for child in frame.winfo_children():
            child.destroy()
        self._pol_gpu_vars = {}
        want = ("4090", "3090", "5090")
        shown: list[tuple[str, str]] = []
        for it in classes:
            name = str(it.get("name") or "")
            gid = str(it.get("id") or "")
            if not gid or not any(w in name for w in want):
                continue
            shown.append((gid, name))
            self._pol_gpu_names[gid] = name
        sel = set(str(x) for x in selected)
        # A class the config stores but the live list did not name still has to
        # be shown, or selecting that config would drop it on the next save.
        named = {gid for gid, _ in shown}
        for gid in sorted(sel - named):
            shown.append((gid, self._pol_gpu_names.get(gid) or gid))
        for i, (gid, name) in enumerate(shown):
            var = tk.BooleanVar(value=gid in sel)
            ttk.Checkbutton(frame, text=name, variable=var).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 12)
            )
            self._pol_gpu_vars[gid] = var
            self._pol_gpu_names[gid] = name

    def _load_salad_policy(self, prof: SaladProfile | None = None, *, quiet: bool = False) -> None:
        """Read a config's group and fill the fields from it.

        ``prof`` is the config to read (the selected one when the button is
        pressed). ``quiet`` is the switch-time re-check: a failure is a log line,
        not a status change, because the fields already show the config's stored
        policy and a missing key or a down API must not look like a blank config.
        """
        name = (prof.name if prof is not None else (self.var_name.get() or "")).strip()
        gw = (prof.gateway if prof is not None else self.var_gateway.get()).strip()
        if not gw:
            if not quiet:
                self.status.set("Gateway URL is empty.")
            return
        stored = dict(getattr(prof, "policy", None) or {}) if prof is not None else {}
        document = profiles.seeded_policy(prof) if prof is not None else {}

        def work() -> None:
            err = ""
            pol = None
            gpus: list[dict] = []
            try:
                key = self._salad_api_key()
                pol, err = salad_status.load_policy(gw, key)
                try:
                    gpus = salad_status.list_gpu_classes(key)
                except Exception:
                    gpus = []
            except Exception as e:
                err = str(e)

            def done() -> None:
                if name and (self.var_name.get() or "").strip() != name:
                    # The window moved on to another config; this read is not the
                    # one on screen, so it must not fill the fields.
                    self.log("debug", f"Policy read for {name!r} dropped: another config is selected")
                    return
                if err or pol is None:
                    if quiet:
                        self.log("warn", f"Policy re-check for {name!r}: {err or 'no group'}")
                        return
                    self.status.set(err or "Load policy failed")
                    self.log("error", f"Policy load: {err}")
                    return
                # The read wins where it answers; the config's stored policy and
                # the document's settings fill the rest, so a field the group does
                # not carry is never left blank.
                shown = salad_status.resolved_policy(stored, pol, document)
                self._fill_gpu_checkboxes(gpus, list(shown.get("gpu_classes") or []))
                self._policy_to_form(shown)
                self.status.set(f"Loaded policy {shown.get('group_name')} v{shown.get('version')}")
                self.log(
                    "ok",
                    f"Policy loaded {shown.get('group_name')} v{shown.get('version')} "
                    f"image={shown.get('image')} "
                    f"startup delay={shown['startup'].get('initial_delay_seconds')}s "
                    f"fail={shown['startup'].get('failure_threshold')}",
                )

            self._later(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _apply_salad_policy(self) -> None:
        gw = self.var_gateway.get().strip()
        if not gw:
            self.status.set("Gateway URL is empty.")
            messagebox.showerror("Salad Studio", "Gateway URL is empty.")
            return
        policy = self._policy_from_form()

        def work() -> None:
            err = ""
            code = 0
            try:
                key = self._salad_api_key()
                code, data = salad_status.apply_policy(gw, key, policy)
                if code >= 400 or (isinstance(data, dict) and data.get("error")):
                    err = str(
                        (data or {}).get("title")
                        or (data or {}).get("error")
                        or data
                        or f"HTTP {code}"
                    )
                    if isinstance(data, dict) and data.get("errors"):
                        err = json.dumps(data.get("errors"))
            except Exception as e:
                err = str(e)

            def done() -> None:
                if err:
                    self.status.set("Policy apply failed")
                    self.log("error", f"Policy apply: {err}")
                    messagebox.showerror("Salad Studio", err)
                    return
                self.status.set("Policy applied to Salad")
                self.log("ok", f"Policy applied HTTP {code}")
                # The fields that were just applied are that config's policy now.
                self._store_policy(policy)
                self._load_salad_policy()

            self._later(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _duplicate_note(self, head) -> str:
        """Why a repeated press added no job, and what the user can do about it."""
        where = f"request {head.id}"
        if head.state == salad_queue.FAILED:
            return (
                f"{where} is the same request and it failed; press Retry selected "
                "to run it again"
            )
        if head.state == salad_queue.ACCEPTED:
            return (
                f"{where} is the same request and it is done; press Clear finished "
                "to submit it again"
            )
        return f"{where} is the same request and it is already queued"

    def _reallocate_instance(self) -> None:
        gw = self.var_gateway.get().strip()
        if not gw:
            self.status.set("Gateway URL is empty.")
            messagebox.showerror("Salad Studio", "Gateway URL is empty.")
            return
        if not messagebox.askyesno(
            "Salad Studio",
            "Reallocate this group's instance onto a different Salad node?\n\n"
            "This dumps any in-flight Docker/HF download on the current machine.",
        ):
            return

        def work() -> None:
            err = ""
            code = 0
            try:
                key = self._salad_api_key()
                code, data = salad_status.reallocate_instance(gw, key)
                if code >= 400 or (isinstance(data, dict) and data.get("error")):
                    err = str(
                        (data or {}).get("error")
                        or (data or {}).get("title")
                        or data
                        or f"HTTP {code}"
                    )
            except Exception as e:
                err = str(e)

            def done() -> None:
                if err:
                    self.status.set(err)
                    self.log("error", f"Reallocate: {err}")
                    messagebox.showerror("Salad Studio", err)
                    return
                self.log("ok", f"Reallocate HTTP {code}")
                self.status.set("Reallocate requested")
                self._check_salad_status(silent=True)

            self._later(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _build_tokens_tab(self) -> None:
        self._tokens = ttk.Frame(self.nb)
        body = self._scrollable_page(self._tokens)
        body.columnconfigure(1, weight=1)
        ttk.Label(
            body,
            text="Secrets live in studio-tokens.json next to Salad Studio (not git). Empty slots are copied from ~/.config, or read from the provider's environment variable where one is configured. Generate sends the Salad key as Salad-Api-Key.",
            wraplength=760,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self._token_entry: dict[str, tk.StringVar] = {}
        self._token_widgets: dict[str, ttk.Entry] = {}
        self._token_show: dict[str, tk.BooleanVar] = {}
        self._token_valid_dot: dict[str, tk.Label] = {}
        self._token_valid_word: dict[str, tk.StringVar] = {}
        self._token_state: dict[str, str] = {}
        r = 1
        for kind, label, _rel in tokens.TOKEN_SPECS:
            box = ttk.LabelFrame(body, text=label, padding=8)
            box.grid(row=r, column=0, columnspan=5, sticky="ew", pady=4)
            box.columnconfigure(1, weight=1)
            ttk.Label(box, text="Local file").grid(row=0, column=0, sticky="w")
            ttk.Label(box, text=str(tokens.LOCAL_PATH)).grid(
                row=0, column=1, columnspan=4, sticky="w", padx=6
            )
            ttk.Label(box, text="Default").grid(row=1, column=0, sticky="w")
            ttk.Label(box, text=tokens.default_label(kind)).grid(
                row=1, column=1, columnspan=4, sticky="w", padx=6
            )
            ttk.Label(box, text="Value").grid(row=2, column=0, sticky="w")
            entry_var = tk.StringVar()
            self._token_entry[kind] = entry_var
            entry = ttk.Entry(box, textvariable=entry_var, show="*")
            entry.grid(row=2, column=1, sticky="ew", padx=6, pady=2)
            self._token_widgets[kind] = entry
            show_var = tk.BooleanVar(value=False)
            self._token_show[kind] = show_var
            ttk.Checkbutton(
                box,
                text="Show",
                variable=show_var,
                command=lambda k=kind: self._toggle_token_visible(k),
            ).grid(row=2, column=2, padx=6)
            ttk.Button(
                box, text="Save", command=lambda k=kind: self._save_token(k)
            ).grid(row=2, column=3, padx=6)
            # Validity indicator: a real provider probe decides the dot colour.
            self._token_state[kind] = "unchecked"
            word = tk.StringVar(value="unchecked")
            self._token_valid_word[kind] = word
            dot = tk.Label(
                box,
                text="●",
                font=("Segoe UI Semibold", 12),
                bg=theme.PALETTE["bg"],
                fg=theme.PALETTE["unknown"],
            )
            dot.grid(row=2, column=4, sticky="w", padx=(6, 0))
            self._token_valid_dot[kind] = dot
            ttk.Label(box, textvariable=word).grid(row=2, column=5, sticky="w", padx=(4, 0))
            r += 1
        bar = ttk.Frame(body)
        bar.grid(row=r, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        # Kept so a running check can take the button down: a press while the
        # probes are in flight changes nothing, so it must not look live.
        self.token_check_btn = ttk.Button(
            bar, text="Check keys", command=self._probe_tokens
        )
        self.token_check_btn.pack(side="left")
        ttk.Label(
            bar,
            text="green = the provider accepted the key; red = rejected; grey = not confirmed",
        ).pack(side="left", padx=(10, 0))
        self._refresh_token_fields()

    def _render_token_state(self, kind: str) -> None:
        state = self._token_state.get(kind, "unchecked")
        word = self._token_valid_word.get(kind)
        if word is not None:
            detail = self._token_detail.get(kind, "")
            word.set(f"{state} ({detail})" if detail else state)
        dot = self._token_valid_dot.get(kind)
        if dot is not None:
            try:
                dot.configure(fg=theme.PALETTE[tokens.state_color(state)])
            except (tk.TclError, KeyError):
                pass

    def _set_token_check_enabled(self, enabled: bool) -> None:
        """Take the Check keys button down while a check runs, and put it back.

        The Tokens tab starts a check as it opens, so the busy window is reached
        without pressing anything; a live-looking button that does nothing is the
        surface lying.
        """
        btn = getattr(self, "token_check_btn", None)
        if btn is None:
            return
        try:
            btn.configure(state="normal" if enabled else "disabled")
        except tk.TclError:
            pass

    def _probe_tokens(self, kinds: list[str] | None = None) -> None:
        """Check keys against their providers in the background."""
        if self._token_probe_busy:
            # The press cannot start a second check, so say why on the one
            # surface that outlives it rather than returning silently.
            self.status.set("Check keys: a key check is already running")
            return
        wanted = list(kinds or tokens.PROBE_SPECS.keys())
        self._token_probe_busy = True
        self._set_token_check_enabled(False)
        for kind in wanted:
            self._token_state[kind] = "checking"
            self._render_token_state(kind)

        def work() -> None:
            results = {kind: tokens.probe_token(kind) for kind in wanted}

            def done() -> None:
                self._token_probe_busy = False
                self._set_token_check_enabled(True)
                for kind, result in results.items():
                    self._token_state[kind] = str(result.get("state") or "unknown")
                    self._token_detail[kind] = str(result.get("detail") or "")
                    self._render_token_state(kind)
                self.log(
                    "debug",
                    "key check: "
                    + ", ".join(
                        f"{k}={results[k].get('state')}" for k in results
                    ),
                )

            self._later(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _toggle_token_visible(self, kind: str) -> None:
        show = "" if self._token_show[kind].get() else "*"
        self._token_widgets[kind].configure(show=show)

    def _refresh_token_fields(self) -> None:
        for kind, var in self._token_entry.items():
            var.set(tokens.read_token(kind))
            if kind in self._token_show:
                self._token_show[kind].set(False)
                self._toggle_token_visible(kind)

    def _save_token(self, kind: str) -> None:
        raw = self._token_entry[kind].get().strip()
        if not raw:
            messagebox.showinfo("Salad Studio", "Value is empty.")
            return
        try:
            path = tokens.write_token(kind, raw)
        except OSError as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        # The store changed, so the redaction list is re-read on the next line
        # that needs it; the fingerprint would catch it anyway, and this makes a
        # save through the page take effect without waiting for a stat to differ.
        self._log_secrets_cache = None
        self._log_secrets_stamp = None
        self._token_entry[kind].set(raw)
        self.status.set(f"Saved {tokens.token_label(kind)} to {path}")
        self.log("ok", f"saved token {kind} ({len(raw)} chars) -> {path}")
        # A freshly saved key is unverified until its provider says otherwise.
        self._token_state[kind] = "unchecked"
        self._token_detail[kind] = ""
        self._render_token_state(kind)
        self._probe_tokens([kind])

    def _build_vast_section(self, body) -> None:
        """The vast.ai half of the config page: the instances and the rental.

        The key is not here: it is the ``vast`` slot on the Tokens tab, stored in
        the gitignored token file. What this section owns is the instance list,
        the rental criteria and the offer results, all kept in
        ``~/.config/salad/studio-vast.json``, so closing and reopening the window
        keeps them.
        """
        self._vast = ttk.LabelFrame(
            body, text="Vast.ai instances", padding=8
        )
        self._vast.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._vast.columnconfigure(0, weight=1)
        ttk.Label(
            self._vast,
            text=(
                "Picture generation can run on the Salad container groups or on "
                "vast.ai instances. The Vast.ai key is the Vast.ai slot on the "
                "Tokens tab; the instances below are stored in "
                f"{vast.INSTANCES_PATH} (not git)."
            ),
            wraplength=760,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.var_vast_mode_note = tk.StringVar(value="")
        ttk.Label(
            self._vast, textvariable=self.var_vast_mode_note, style="Status.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))

        box = ttk.LabelFrame(self._vast, text="Instances", padding=8)
        box.grid(row=2, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        add = ttk.Frame(box)
        add.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(add, text="Address").pack(side="left")
        self.var_vast_new = tk.StringVar(value="")
        ttk.Entry(add, textvariable=self.var_vast_new, width=30).pack(side="left", padx=6)
        ttk.Label(add, text="Label").pack(side="left")
        self.var_vast_label = tk.StringVar(value="")
        ttk.Entry(add, textvariable=self.var_vast_label, width=16).pack(side="left", padx=6)
        ttk.Label(add, text="Image").pack(side="left")
        self.var_vast_image = tk.StringVar(value="")
        self.vast_image_box = ttk.Combobox(
            add, textvariable=self.var_vast_image, width=34
        )
        self.vast_image_box.pack(side="left", padx=6)
        ttk.Button(add, text="Add instance", command=self._on_vast_add).pack(side="left")
        ttk.Label(
            box,
            text="(one address, or several separated by commas)",
            style="Status.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self.vast_tree = ttk.Treeview(
            box, columns=("use", "label", "endpoint", "image", "state", "gpu"),
            show="headings", height=7,
        )
        for col, heading, width, _fill in VAST_GRID_COLUMNS:
            self.vast_tree.heading(col, text=heading)
            self.vast_tree.column(col, width=width, stretch=False, anchor="w")
        self._keep_grid_filling(
            self._config_section_pages["vast"], self.vast_tree, VAST_GRID_COLUMNS
        )
        self.vast_tree.tag_configure("active", foreground=theme.PALETTE["valid"])
        vscroll = ttk.Scrollbar(box, orient="vertical", command=self.vast_tree.yview)
        self.vast_tree.configure(yscrollcommand=vscroll.set)
        self.vast_tree.grid(row=2, column=0, sticky="nsew")
        vscroll.grid(row=2, column=1, sticky="ns")
        self.vast_tree.bind("<<TreeviewSelect>>", self._on_vast_select)

        bar = ttk.Frame(box)
        bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(bar, text="Remove selected", command=self._on_vast_remove).pack(
            side="left"
        )
        ttk.Button(bar, text="Save list", command=self._on_vast_save).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(bar, text="Set image for selected", command=self._on_vast_set_image).pack(
            side="left", padx=(6, 0)
        )
        self.vast_fetch_btn = ttk.Button(
            bar, text="Fetch instances from Vast.ai", command=self._on_vast_fetch
        )
        self.vast_fetch_btn.pack(side="left", padx=(6, 0))
        ttk.Button(
            bar, text="New profile for this instance", command=self._on_vast_make_profile
        ).pack(side="left", padx=(6, 0))
        self.var_vast_status = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.var_vast_status, style="Status.TLabel").pack(
            side="left", padx=(12, 0)
        )

        policy = vast.clean_replace(self._vast_doc.get("replace"))
        rent = ttk.LabelFrame(self._vast, text="Rent a machine", padding=8)
        rent.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        rent.columnconfigure(0, weight=1)

        gpu_row = ttk.Frame(rent)
        gpu_row.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(gpu_row, text="GPU models").pack(side="left")
        self.var_vast_gpus = tk.StringVar(value=", ".join(policy["gpu_names"]))
        ttk.Entry(gpu_row, textvariable=self.var_vast_gpus, width=44).pack(
            side="left", padx=6
        )
        ttk.Label(
            gpu_row,
            text=(
                "Names: RTX 5090, RTX 4090, RTX A6000, A100 PCIE. The first "
                "listed is preferred; clear the box to restore RTX 5090, RTX 4090."
            ),
            style="Status.TLabel",
            wraplength=430,
        ).pack(side="left", padx=(6, 0))

        floors = ttk.Frame(rent)
        floors.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.var_vast_price = tk.StringVar(value=f"{policy['max_price']:.2f}")
        self.var_vast_down = tk.StringVar(value=f"{policy['min_down_mbps']:.0f}")
        self.var_vast_up = tk.StringVar(value=f"{policy['min_up_mbps']:.0f}")
        self.var_vast_cuda = tk.StringVar(value=f"{policy['cuda_min']:g}")
        self.var_vast_reliability = tk.StringVar(
            value=f"{policy['min_reliability']:g}"
        )
        fields = (
            ("Max $/hr", self.var_vast_price, 6),
            ("Min down Mbps", self.var_vast_down, 6),
            ("Min up Mbps", self.var_vast_up, 6),
            ("CUDA at least", self.var_vast_cuda, 5),
            ("Reliability at least", self.var_vast_reliability, 5),
        )
        col = 0
        for label, var, width in fields:
            ttk.Label(floors, text=label).grid(
                row=0, column=col, sticky="w", padx=(0 if col == 0 else 10, 4)
            )
            ttk.Entry(floors, textvariable=var, width=width).grid(
                row=0, column=col + 1, sticky="w"
            )
            col += 2

        pick = ttk.Frame(rent)
        pick.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(pick, text="Image").pack(side="left")
        self.vast_offer_image_box = ttk.Combobox(
            pick, textvariable=self.var_vast_image, width=34
        )
        self.vast_offer_image_box.pack(side="left", padx=6)
        ttk.Label(pick, text="Label").pack(side="left")
        self.var_vast_rent_label = tk.StringVar(value="")
        ttk.Entry(pick, textvariable=self.var_vast_rent_label, width=24).pack(
            side="left", padx=6
        )
        self.vast_search_btn = ttk.Button(
            pick, text="Find offers", command=self._on_vast_search
        )
        self.vast_search_btn.pack(side="left", padx=(6, 0))
        self.var_vast_offer_status = tk.StringVar(value="")
        ttk.Label(
            pick, textvariable=self.var_vast_offer_status, style="Status.TLabel"
        ).pack(side="left", padx=(12, 0))

        self.vast_offer_tree = ttk.Treeview(
            rent,
            columns=tuple(col for col, _heading, _width, _fill in VAST_OFFER_GRID_COLUMNS),
            show="headings",
            height=8,
        )
        for col, heading, width, _fill in VAST_OFFER_GRID_COLUMNS:
            self.vast_offer_tree.heading(col, text=heading)
            self.vast_offer_tree.column(col, width=width, stretch=False, anchor="w")
        self._keep_grid_filling(
            self._config_section_pages["vast"],
            self.vast_offer_tree,
            VAST_OFFER_GRID_COLUMNS,
        )
        offer_scroll = ttk.Scrollbar(
            rent, orient="vertical", command=self.vast_offer_tree.yview
        )
        self.vast_offer_tree.configure(yscrollcommand=offer_scroll.set)
        self.vast_offer_tree.grid(row=3, column=0, sticky="nsew")
        offer_scroll.grid(row=3, column=1, sticky="ns")

        actions = ttk.Frame(rent)
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.vast_rent_btn = ttk.Button(
            actions,
            text="Create instance on selected offer",
            command=self._on_vast_rent,
        )
        self.vast_rent_btn.pack(side="left")
        ttk.Label(
            actions,
            text=(
                "Ranks by images per dollar: Perf is vast.ai's dlperf index, not a "
                "promise of images per hour for this graph; Perf/$ is Perf divided "
                "by $/hr. RTX 5090 comes before RTX 4090."
            ),
            style="Status.TLabel",
            wraplength=430,
        ).pack(side="left", padx=(10, 0))

        replace = ttk.LabelFrame(
            self._vast, text="If the selected instance is destroyed", padding=8
        )
        replace.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.var_vast_replace = tk.BooleanVar(value=bool(policy["enabled"]))
        ttk.Checkbutton(
            replace,
            text="Create a replacement automatically when Generate finds it gone",
            variable=self.var_vast_replace,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.vast_replace_btn = ttk.Button(
            replace, text="Replace if destroyed now", command=self._on_vast_replace
        )
        self.vast_replace_btn.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            replace,
            text=(
                "Uses the criteria above. Rents the best value offer that clears "
                "them; RTX 5090 before RTX 4090 on a tie. The 24 GB card and "
                "140 GB disk are fixed."
            ),
            style="Status.TLabel",
            wraplength=560,
        ).grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(8, 0))

        self._refresh_image_refs()
        self._refresh_vast_page()

    def gen_mode(self) -> str:
        """Which hosting Generate uses: the active profile's target."""
        mode = self._profile_mode()
        return mode if mode in hostings.BY_KEY else hostings.DEFAULT

    def _vast_active(self) -> dict | None:
        """The instance Generate will POST to, or None when none is selected."""
        return vast.active_row(self._vast_doc)

    def _refresh_vast_page(self) -> None:
        """Show the stored instances and mark the one Generate uses."""
        active = str(self._vast_doc.get("active") or "")
        self.vast_tree.delete(*self.vast_tree.get_children())
        for row in self._vast_doc.get("instances") or []:
            endpoint = str(row.get("endpoint") or "")
            iid = self.vast_tree.insert(
                "",
                "end",
                values=(
                    "●" if endpoint == active else "",
                    vast.row_label(row),
                    endpoint,
                    row.get("image") or "",
                    row.get("state") or "",
                    row.get("gpu") or "",
                ),
                tags=("active",) if endpoint == active else (),
            )
            if endpoint == active:
                self.vast_tree.selection_set(iid)
        count = len(self._vast_doc.get("instances") or [])
        chosen = vast.row_label(self._vast_active() or {}) or "(none selected)"
        self.var_vast_mode_note.set(
            f"{count} instance(s) saved; the active profile's target uses {chosen}"
        )

    def _store_vast_doc(self, doc: dict, note: str) -> None:
        """Keep an edited document in memory and on disk, then redraw the page."""
        self._vast_doc = doc
        try:
            path = vast.save_doc(doc)
        except OSError as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._refresh_vast_page()
        self.var_vast_status.set(note)
        self.status.set(note)
        self.log("ok", f"vast.ai: {note} -> {path}")

    def _on_vast_add(self) -> None:
        """Add one or more instances the user typed, comma- or space-separated.

        The box holds addresses, and a phrase that names no host is refused here
        rather than stored: the store's own refusal is reported, naming both what
        was added and what was not, on the status line and in the Logs, so a
        press that added three of five cannot read as five.
        """
        parts = str(self.var_vast_new.get() or "").replace(",", " ").split()
        if not parts:
            messagebox.showinfo("Salad Studio", "Type an instance address first.")
            return
        label = self.var_vast_label.get().strip()
        image = self.var_vast_image.get().strip()
        doc = self._vast_doc
        added: list[str] = []
        refused: list[tuple[str, str]] = []
        for i, part in enumerate(parts):
            doc, refusal = vast.add_instance(
                doc, part, label=label if i == 0 else "", image=image if i == 0 else ""
            )
            if refusal:
                refused.append((part, refusal))
            else:
                added.append(vast.normalize_endpoint(part))
        if not added:
            note = "Nothing was added. " + vast_refusal_note(refused)
            self.var_vast_status.set(note)
            self.status.set(note)
            self.log("warn", f"vast.ai: {note}")
            messagebox.showinfo("Salad Studio", note)
            return
        self.var_vast_new.set("")
        self.var_vast_label.set("")
        note = f"added {len(added)} instance(s): {', '.join(added)}"
        if refused:
            note += f"; refused {len(refused)}: {vast_refusal_note(refused)}"
        self._store_vast_doc(doc, note)

    def _on_vast_make_profile(self) -> None:
        """Create a profile whose target is the selected instance."""
        row = self._vast_active()
        if row is None:
            self._config_status("Select an instance first.")
            self.log("warn", "no instance is selected")
            return
        endpoint = str(row.get("endpoint") or "")
        ident = str(row.get("id") or "").strip() or endpoint.rsplit(":", 1)[-1]
        name = f"vast-{ident}"
        allp = profiles.load_all()
        if name in allp:
            profiles.set_active(name)
            self._refresh_profile_choices(name)
            self._apply_profile(allp[name])
            self._config_status(f"Profile {name} already targets {endpoint}")
            return
        p = profiles.default_profile(name)
        p.mode = "vast"
        p.gateway = endpoint
        family = self._family_for_image(str(row.get("image") or ""))
        if family:
            p.checkpoints = profiles.seed_checkpoints(family)
        profiles.upsert(p)
        profiles.set_active(name)
        self._refresh_profile_choices(name)
        self._apply_profile(p)
        self._config_status(f"Created profile {name} for {endpoint}")
        self.log("ok", f"created profile {name} targeting {endpoint}")

    def _family_for_image(self, tag: str) -> str:
        """The family a deployment image tag bakes, or "" when it names none."""
        doc = studio_meta.default()
        for family in studio_meta.families(doc):
            entry = studio_meta.deployment_for_family(family, doc)
            if str(entry.get("tag") or "") == str(tag or ""):
                return family
        return ""

    def _on_vast_remove(self) -> None:
        selection = self.vast_tree.selection()
        if not selection:
            messagebox.showinfo("Salad Studio", "Select an instance row first.")
            return
        endpoint = str(self.vast_tree.item(selection[0], "values")[2])
        if not messagebox.askyesno(
            "Salad Studio", f"Remove the vast.ai instance {endpoint}?"
        ):
            self.status.set(f"Kept {endpoint}")
            self.log("info", f"kept the vast.ai instance {endpoint}")
            return
        doc, removed = vast.remove_instance(self._vast_doc, endpoint)
        if not removed:
            return
        self._store_vast_doc(doc, f"removed {endpoint}")

    def _on_vast_select(self, _event=None) -> None:
        """Selecting a row points Generate at that instance."""
        selection = self.vast_tree.selection()
        if not selection:
            return
        endpoint = str(self.vast_tree.item(selection[0], "values")[2])
        if endpoint == str(self._vast_doc.get("active") or ""):
            return
        self._store_vast_doc(vast.set_active(self._vast_doc, endpoint), f"using {endpoint}")
        if self._profile_mode() == "vast":
            # The page says this row is Generate's target, so the target box
            # must name it too; otherwise the profile's old URL still wins.
            self.var_gateway.set(endpoint)

    def _on_vast_save(self) -> None:
        count = len(self._vast_doc.get("instances") or [])
        doc = dict(self._vast_doc)
        doc["replace"] = self._vast_criteria()
        self._store_vast_doc(doc, f"saved {count} instance(s)")

    def _vast_criteria(self) -> dict:
        """The rental criteria as the boxes and the checkbox state them."""
        return vast.clean_replace(
            {
                "enabled": bool(self.var_vast_replace.get()),
                "max_price": self.var_vast_price.get(),
                "min_down_mbps": self.var_vast_down.get(),
                "min_up_mbps": self.var_vast_up.get(),
                "cuda_min": self.var_vast_cuda.get(),
                "min_reliability": self.var_vast_reliability.get(),
                "gpu_names": self.var_vast_gpus.get(),
            }
        )

    def _vast_note(self, text: str, level: str = "info") -> None:
        """Say one thing on the section, the status line, and the Logs."""
        self.var_vast_status.set(text)
        offer_status = getattr(self, "var_vast_offer_status", None)
        if offer_status is not None:
            offer_status.set(text)
        self.status.set(text)
        self.log(level, f"vast.ai: {text}")

    def _on_vast_search(self) -> None:
        """Find offers for the rental criteria, off the Tk thread."""
        if self._vast_search_busy:
            return
        key = tokens.read_token("vast")
        if not key:
            messagebox.showinfo(
                "Salad Studio",
                "Save the Vast.ai key on the Tokens tab, then search again.",
            )
            self._vast_note("save the Vast.ai key on the Tokens tab first", "warn")
            return
        criteria = self._vast_criteria()
        # The normalized list goes back into the box, so clearing it visibly
        # restores the defaults instead of silently widening the search.
        self.var_vast_gpus.set(", ".join(criteria["gpu_names"]))
        doc = dict(self._vast_doc)
        doc["replace"] = criteria
        self._store_vast_doc(doc, "saved the rental criteria")
        self._vast_search_busy = True
        self.vast_search_btn.configure(state="disabled")
        self.vast_offer_tree.delete(*self.vast_offer_tree.get_children())
        self._vast_offers = {}
        self._vast_note("searching vast.ai offers…")

        def work() -> None:
            result = vast.search_offers(key, criteria)
            if self._later(0, lambda: self._apply_vast_search(result, criteria)) is None:
                self._vast_search_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _apply_vast_search(self, result: dict, criteria: dict) -> None:
        """Fill the results table, or say why the search came back empty."""
        self._vast_search_busy = False
        try:
            self.vast_search_btn.configure(state="normal")
        except tk.TclError:
            pass
        status = int(result.get("status") or 0)
        if status != 200:
            note = str(result.get("error") or f"HTTP {status}")
            if status in (401, 403):
                note = f"vast.ai rejected the key ({note}). Fix it on the Tokens tab."
            self._vast_note(note, "warn")
            return
        offers = vast.matching_offers(result.get("offers") or [], criteria)
        if not offers:
            self._vast_note(
                "no offer matches the GPU list and floors; widen them and search again.",
                "warn",
            )
            return
        for offer in offers:
            iid = str(offer["id"])
            cells = vast.offer_cells(offer)
            self.vast_offer_tree.insert(
                "",
                "end",
                iid=iid,
                values=tuple(cells[col] for col, _h, _w, _f in VAST_OFFER_GRID_COLUMNS),
            )
            self._vast_offers[iid] = offer
        best = vast.offer_cells(offers[0])
        self._vast_note(
            f"{len(offers)} offer(s), most images per dollar first; "
            f"best {best['gpu']} {best['price']}/hr at {best['value']} Perf/$"
        )

    def _on_vast_rent(self) -> None:
        """Create one instance on the offer the user selected, off the Tk thread."""
        if self._vast_create_busy:
            return
        selection = self.vast_offer_tree.selection()
        if not selection:
            self._vast_note("select an offer row first.", "warn")
            return
        offer = self._vast_offers.get(str(selection[0]))
        if offer is None:
            self._vast_note("select an offer row first.", "warn")
            return
        key = tokens.read_token("vast")
        if not key:
            messagebox.showinfo(
                "Salad Studio",
                "Save the Vast.ai key on the Tokens tab, then search again.",
            )
            self._vast_note("save the Vast.ai key on the Tokens tab first", "warn")
            return
        pending = (self._vast_doc.get("pending") or {}).get("contract")
        if pending:
            self._vast_note(
                f"instance {pending} was created and has not mapped an endpoint yet. "
                "Press Fetch instances from Vast.ai later.",
                "warn",
            )
            return
        image = str(self.var_vast_image.get() or "").strip()
        if not image:
            try:
                image = profiles.policy_image_for(self._profile_from_form())
            except ValueError:
                image = ""
        if not image:
            self._vast_note("set the image for the new instance first.", "warn")
            return
        label = str(self.var_vast_rent_label.get() or "").strip() or (
            f"salad-studio-{offer['id']}"
        )
        env = vast.replacement_env(
            hf_token=tokens.read_token("huggingface"),
            civitai_token=tokens.read_token("civitai"),
        )
        self._vast_create_busy = True
        self.vast_rent_btn.configure(state="disabled")
        self.vast_replace_btn.configure(state="disabled")
        gpu = str(offer.get("gpu_name") or "the selected offer")
        self._vast_note(f"creating an instance on {gpu}…")

        def work() -> None:
            try:
                result = vast.rent_offer(key, offer, image=image, label=label, env=env)
            except Exception as e:  # noqa: BLE001 - the button must come back
                result = {"action": "error", "message": f"{type(e).__name__}: {e}"}
            if self._later(0, lambda: self._apply_vast_rent(result, None)) is None:
                self._vast_create_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _apply_vast_rent(self, result: dict, old_row: dict | None = None) -> None:
        """Show what a rent or replacement check did, and keep the row it returned."""
        self._vast_create_busy = False
        buttons = (
            getattr(self, "vast_rent_btn", None),
            getattr(self, "vast_replace_btn", None),
        )
        for button in buttons:
            if button is None:
                continue
            try:
                button.configure(state="normal")
            except tk.TclError:
                pass
        action = str(result.get("action") or "")
        message = str(result.get("message") or "")
        new = result.get("row")
        if isinstance(new, dict) and old_row:
            # A live check returns the API's row fields only; keep the label and
            # image the user set, while the new endpoint and state win.
            new = {**old_row, **new}
        if isinstance(new, dict) and str(new.get("endpoint") or ""):
            rows: list[dict] = []
            old_endpoint = str((old_row or {}).get("endpoint") or "")
            old_id = (old_row or {}).get("id")
            replaced = False
            for row in self._vast_doc.get("instances") or []:
                same = bool(old_endpoint and str(row.get("endpoint") or "") == old_endpoint)
                if not same and old_id is not None:
                    same = str(row.get("id") or "") == str(old_id)
                rows.append(dict(new) if same else row)
                replaced = replaced or same
            if not replaced:
                rows.append(dict(new))
            doc = dict(self._vast_doc)
            doc["instances"] = rows
            doc["active"] = str(new["endpoint"])
            doc["replace"] = self._vast_criteria()
            doc["pending"] = {}
            self._store_vast_doc(doc, message)
            if self._profile_mode() == "vast":
                self.var_gateway.set(str(new["endpoint"]))
                name = (self.var_name.get() or "").strip()
                try:
                    allp = profiles.load_all()
                    if name in allp:
                        prof = allp[name]
                        prof.gateway = str(new["endpoint"])
                        prof.mode = "vast"
                        profiles.upsert(prof)
                        self.log("info", f"profile {name} now targets {new['endpoint']}")
                except Exception as e:  # noqa: BLE001 - a bad store must not undo the row
                    self.log("warn", f"could not update profile {name}: {e}")
        else:
            if action == "created" and result.get("contract") is not None:
                doc = dict(self._vast_doc)
                doc["pending"] = {
                    "contract": int(result["contract"]),
                    "label": str(result.get("label") or ""),
                    "image": str(result.get("image") or ""),
                }
                self._store_vast_doc(doc, message)
            else:
                self.var_vast_status.set(message)
                self.status.set(message)
        self.log("info" if action in ("alive", "created") else "error", message)

    def _on_vast_replace(self) -> None:
        """Check the selected instance, and rent a replacement if gone."""
        if self._vast_create_busy:
            self.var_vast_status.set("a replacement check is already running")
            return
        row = self._vast_active()
        if row is None:
            self.var_vast_status.set("select an instance row first")
            return
        key = tokens.read_token("vast")
        if not key:
            messagebox.showinfo(
                "Salad Studio",
                "Save the Vast.ai key on the Tokens tab, then replace again.",
            )
            return
        image = str(row.get("image") or "").strip()
        if not image:
            try:
                image = profiles.policy_image_for(self._profile_from_form())
            except ValueError:
                image = ""
        if not image:
            messagebox.showinfo(
                "Salad Studio",
                "Set an image for the selected instance first (Set image for selected).",
            )
            return
        settings = self._vast_criteria()
        label = str(row.get("label") or "").strip() or f"salad-studio-{row['endpoint']}"
        env = vast.replacement_env(
            hf_token=tokens.read_token("huggingface"),
            civitai_token=tokens.read_token("civitai"),
        )
        self._vast_create_busy = True
        self.vast_replace_btn.configure(state="disabled")
        self.vast_rent_btn.configure(state="disabled")
        self.var_vast_status.set("checking the selected instance.")

        def work() -> None:
            try:
                result = vast.replace_destroyed(
                    key=key,
                    endpoint=str(row.get("endpoint") or ""),
                    instance_id=row.get("id")
                    or (self._vast_doc.get("pending") or {}).get("contract"),
                    image=image,
                    settings=settings,
                    label=label,
                    env=env,
                )
            except Exception as e:  # noqa: BLE001 - the button must come back
                result = {"action": "error", "message": f"{type(e).__name__}: {e}"}
            if self._later(0, lambda: self._apply_vast_rent(result, row)) is None:
                self._vast_create_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _on_vast_set_image(self) -> None:
        """Record which image a listed instance runs, so the row points at one.

        The image is a reference for the reader: it is what the Container images
        section below describes, and what to run on that instance. A render does
        not depend on it, because the instance's endpoint is what Generate POSTs
        to.
        """
        selection = self.vast_tree.selection()
        if not selection:
            messagebox.showinfo("Salad Studio", "Select an instance row first.")
            return
        endpoint = str(self.vast_tree.item(selection[0], "values")[2])
        image = self.var_vast_image.get().strip()
        rows = [dict(row) for row in self._vast_doc.get("instances") or []]
        changed = False
        for row in rows:
            if str(row.get("endpoint") or "") == endpoint and str(row.get("image") or "") != image:
                row["image"] = image
                changed = True
        if not changed:
            return
        doc = dict(self._vast_doc)
        doc["instances"] = rows
        note = f"{endpoint} runs {image}" if image else f"cleared the image on {endpoint}"
        self._store_vast_doc(doc, note)

    def _on_vast_fetch(self) -> None:
        """List this account's instances with the stored key, off the Tk thread."""
        if getattr(self, "_vast_fetch_busy", False):
            return
        key = tokens.read_token("vast")
        if not key:
            messagebox.showinfo(
                "Salad Studio",
                "Save the Vast.ai key on the Tokens tab, then fetch again.",
            )
            return
        self._vast_fetch_busy = True
        self.vast_fetch_btn.configure(state="disabled")
        self.var_vast_status.set("asking vast.ai for this account's instances…")

        def work() -> None:
            result = vast.fetch_instances(key)

            def done() -> None:
                self._vast_fetch_busy = False
                self.vast_fetch_btn.configure(state="normal")
                self._apply_vast_fetch(result)

            self._later(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _apply_vast_fetch(self, result: dict) -> None:
        """Add what the vast.ai listing returned, and say what it did not."""
        status = int(result.get("status") or 0)
        rows = list(result.get("instances") or [])
        if status != 200:
            note = str(result.get("error") or f"HTTP {status}")
            if status in (401, 403):
                note = f"vast.ai rejected the key ({note}). Fix it on the Tokens tab."
            self.var_vast_status.set(note)
            self.log("warn", f"vast.ai: {note}")
            return
        doc = self._vast_doc
        added: list[str] = []
        for row in rows:
            doc, refusal = vast.add_instance(
                doc,
                row["endpoint"],
                label=row.get("label") or "",
                id=row.get("id"),
                gpu=row.get("gpu") or "",
                state=row.get("state") or "",
            )
            if not refusal:
                added.append(str(row["endpoint"]))
        pending = (doc.get("pending") or {}).get("contract")
        mapped = bool(pending) and any(
            str(row.get("id") or "") == str(pending) for row in rows
        )
        if mapped:
            doc = dict(doc)
            doc["pending"] = {}
        note = f"vast.ai listed {len(rows)} instance(s); added {len(added)}"
        if mapped:
            note += (
                f"; instance {pending} now maps an endpoint, so the pending record "
                "is cleared"
            )
        if result.get("truncated"):
            note += (
                f" — the account has more than {vast.MAX_PAGES} pages of instances, "
                "so the list stops there"
            )
        if added or mapped:
            self._store_vast_doc(doc, note)
        else:
            self.var_vast_status.set(note)
            self.log("info", f"vast.ai: {note}")

    def _build_images_section(self, body) -> None:
        """The container images: where each one lives, and what a host needs.

        The facts come from the metadata document, so a new image is a document
        edit; what the user adds — extra environment entries, and images of
        their own — is kept in ``~/.config/salad/studio-images.json``. The tags
        here are what this page's policy image field and a Vast.ai instance row
        refer to.
        """
        self._images = ttk.LabelFrame(
            body, text="Container images", padding=8
        )
        self._images.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._images.columnconfigure(0, weight=1)
        ttk.Label(
            self._images,
            text=(
                "The container images this app deploys, one per unet family. The "
                "tag, the build arg, the ports and the documented environment come "
                "from the metadata document; extra environment entries and your own "
                f"images are stored in {image_deploy.SETTINGS_PATH} (not git). The "
                "policy image field on the Salad group sub-tab and a Vast.ai instance row refer to a tag "
                "from here."
            ),
            wraplength=820,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        pick = ttk.Frame(self._images)
        pick.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(pick, text="Image").pack(side="left")
        self.var_image_key = tk.StringVar(value="")
        self.image_box = ttk.Combobox(
            pick, textvariable=self.var_image_key, state="readonly", width=28
        )
        self.image_box.pack(side="left", padx=6)
        self.image_box.bind("<<ComboboxSelected>>", self._on_image_pick, add="+")
        self.var_image_facts = tk.StringVar(value="")
        ttk.Label(pick, textvariable=self.var_image_facts, style="Status.TLabel").pack(
            side="left", padx=(12, 0)
        )

        box = ttk.LabelFrame(self._images, text="Environment", padding=8)
        box.grid(row=2, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        cols = ("name", "value", "source", "note")
        self.image_env_tree = ttk.Treeview(box, columns=cols, show="headings", height=7)
        for col, heading, width, stretch in (
            ("name", "Variable", 190, False),
            ("value", "Value", 210, False),
            ("source", "From", 90, False),
            ("note", "What it is for", 320, True),
        ):
            self.image_env_tree.heading(col, text=heading)
            self.image_env_tree.column(col, width=width, stretch=stretch, anchor="w")
        escroll = ttk.Scrollbar(box, orient="vertical", command=self.image_env_tree.yview)
        self.image_env_tree.configure(yscrollcommand=escroll.set)
        self.image_env_tree.grid(row=0, column=0, sticky="nsew")
        escroll.grid(row=0, column=1, sticky="ns")

        add = ttk.Frame(box)
        add.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(add, text="Add").pack(side="left")
        self.var_image_env_name = tk.StringVar(value="")
        ttk.Entry(add, textvariable=self.var_image_env_name, width=22).pack(side="left", padx=6)
        self.var_image_env_value = tk.StringVar(value="")
        ttk.Entry(add, textvariable=self.var_image_env_value, width=26).pack(side="left", padx=6)
        ttk.Button(add, text="Add env", command=self._on_image_add_env).pack(side="left")
        ttk.Button(add, text="Remove selected", command=self._on_image_remove_env).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(add, text="Save environment", command=self._on_image_save).pack(
            side="left", padx=(6, 0)
        )
        self.var_image_include = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            add,
            text="show token values",
            variable=self.var_image_include,
            command=self._refresh_images_page,
        ).pack(side="left", padx=(12, 0))

        dep = ttk.LabelFrame(self._images, text="Deploy", padding=8)
        dep.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        dep.columnconfigure(0, weight=1)
        self.image_script = tk.Text(dep, height=12, wrap="none", state="disabled")
        self.image_script.grid(row=0, column=0, sticky="nsew")
        theme.style_text(self.image_script)
        bar = ttk.Frame(dep)
        bar.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(bar, text="Copy commands", command=self._on_image_copy).pack(side="left")
        self.var_image_status = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.var_image_status, style="Status.TLabel").pack(
            side="left", padx=(12, 0)
        )

        mine = ttk.LabelFrame(self._images, text="Your own image", padding=8)
        mine.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        for column in (1, 3):
            mine.columnconfigure(column, weight=1)
        ttk.Label(mine, text="Name").grid(row=0, column=0, sticky="w")
        self.var_image_new_name = tk.StringVar(value="")
        ttk.Entry(mine, textvariable=self.var_image_new_name, width=18).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Label(mine, text="Tag").grid(row=0, column=2, sticky="w")
        self.var_image_new_tag = tk.StringVar(value="")
        ttk.Entry(mine, textvariable=self.var_image_new_tag).grid(
            row=0, column=3, sticky="ew", padx=6
        )
        ttk.Label(mine, text="Build arg").grid(row=1, column=0, sticky="w")
        self.var_image_new_arg = tk.StringVar(value="")
        ttk.Entry(mine, textvariable=self.var_image_new_arg).grid(
            row=1, column=1, sticky="ew", padx=6
        )
        ttk.Label(mine, text="Context").grid(row=1, column=2, sticky="w")
        self.var_image_new_context = tk.StringVar(value=image_deploy.DEFAULT_CONTEXT)
        ttk.Entry(mine, textvariable=self.var_image_new_context).grid(
            row=1, column=3, sticky="ew", padx=6
        )
        # The ports the image publishes, which its docker run and vast.ai lines
        # need: without them a user's own image deploys with no port at all.
        ttk.Label(mine, text="API port").grid(row=2, column=0, sticky="w")
        self.var_image_new_api = tk.StringVar(value="")
        ttk.Entry(mine, textvariable=self.var_image_new_api, width=8).grid(
            row=2, column=1, sticky="w", padx=6
        )
        ttk.Label(mine, text="ComfyUI port").grid(row=2, column=2, sticky="w")
        self.var_image_new_comfy = tk.StringVar(value="")
        ttk.Entry(mine, textvariable=self.var_image_new_comfy, width=8).grid(
            row=2, column=3, sticky="w", padx=6
        )
        ttk.Button(mine, text="Add image", command=self._on_image_add_image).grid(
            row=3, column=1, sticky="w", padx=6, pady=(6, 0)
        )
        ttk.Button(mine, text="Remove image", command=self._on_image_remove_image).grid(
            row=3, column=3, sticky="w", padx=6, pady=(6, 0)
        )
        self._refresh_images_page()

    def _image_entries(self) -> list[dict]:
        """Every image the page can show: the document's, then the user's own."""
        return image_deploy.entries(studio_meta.default(), self._image_settings)

    def _image_tokens(self) -> dict[str, str]:
        """The token values the document's environment entries ask for.

        The slots come from the document rather than a literal list, so an entry
        that names a new slot needs no code change here.
        """
        slots = {
            str(row.get(studio_meta.ENV_TOKEN) or "")
            for entry in self._image_entries()
            for row in entry.get("env") or []
        }
        return {slot: tokens.read_token(slot) for slot in sorted(slots) if slot}

    def _image_entry(self) -> dict | None:
        """The entry the page is showing, or the first one."""
        entries = self._image_entries()
        if not entries:
            return None
        found = image_deploy.entry_by_ref(entries, self.var_image_key.get())
        return found or entries[0]

    def _image_env_rows(self, entry: dict) -> list[dict]:
        return image_deploy.env_rows(
            entry,
            image_deploy.extra_env(self._image_settings, str(entry.get("key") or "")),
            self._image_tokens(),
        )

    def _refresh_image_refs(self) -> None:
        """Offer the known tags where a Salad policy or a vast.ai row refers to one."""
        options = image_deploy.tag_options(studio_meta.default(), self._image_settings)
        box = getattr(self, "pol_image_box", None)
        if box is not None:
            box.configure(values=options)
        vast_box = getattr(self, "vast_image_box", None)
        if vast_box is not None:
            vast_box.configure(values=[""] + options)
        rent_box = getattr(self, "vast_offer_image_box", None)
        if rent_box is not None:
            rent_box.configure(values=[""] + options)

    def _refresh_images_page(self) -> None:
        """Redraw the page: the picker, the facts, the environment and the script."""
        entries = self._image_entries()
        keys = [str(entry["key"]) for entry in entries]
        self.image_box.configure(values=keys)
        if self.var_image_key.get() not in keys:
            self.var_image_key.set(keys[0] if keys else "")
        entry = self._image_entry()
        self.image_env_tree.delete(*self.image_env_tree.get_children())
        if entry is None:
            self.var_image_facts.set("no image is configured")
            self._refresh_image_script()
            return
        ports = entry.get("ports") or {}
        self.var_image_facts.set(
            f"{entry['tag']} · {entry['source']} · {entry.get('gpu') or 'any GPU'} · "
            f"ports {ports.get(studio_meta.PORT_API) or '-'} (api) / "
            f"{ports.get(studio_meta.PORT_COMFY) or '-'} (comfy)"
        )
        include = bool(self.var_image_include.get())
        for row in self._image_env_rows(entry):
            self.image_env_tree.insert(
                "",
                "end",
                values=(
                    row.get(studio_meta.ENV_NAME) or "",
                    image_deploy.shown_value(row, include_values=include),
                    row.get("source") or "",
                    row.get(studio_meta.ENV_NOTE) or "",
                ),
            )
        self._refresh_image_script()

    def _refresh_image_script(self) -> None:
        """Refill the command pane from the selected entry and its environment."""
        entry = self._image_entry()
        include = bool(self.var_image_include.get())
        text = (
            image_deploy.deploy_script(entry, self._image_env_rows(entry), include_values=include)
            if entry is not None
            else ""
        )
        self.image_script.configure(state="normal")
        self.image_script.delete("1.0", "end")
        self.image_script.insert("1.0", text)
        self.image_script.configure(state="disabled")

    def _on_image_pick(self, _event=None) -> None:
        self._refresh_images_page()

    def _store_image_settings(self, settings: dict, note: str) -> None:
        """Keep an edited store in memory and on disk, then redraw the pages."""
        self._image_settings = settings
        try:
            path = image_deploy.save_settings(settings)
        except OSError as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._refresh_images_page()
        self._refresh_image_refs()
        self.var_image_status.set(note)
        self.status.set(note)
        self.log("ok", f"images: {note} -> {path}")

    def _on_image_add_env(self) -> None:
        entry = self._image_entry()
        if entry is None:
            return
        settings, refusal = image_deploy.add_env(
            self._image_settings,
            str(entry["key"]),
            self.var_image_env_name.get(),
            self.var_image_env_value.get(),
        )
        if refusal:
            # The dialog is the only surface that carries this, and it does not
            # outlive the dismissal; the status line keeps the last success.
            self.status.set(f"Refused: {refusal}")
            messagebox.showinfo("Salad Studio", refusal)
            return
        self.var_image_env_name.set("")
        self.var_image_env_value.set("")
        # The name only: an environment value may be a secret.
        self._store_image_settings(settings, f"added an environment entry to {entry['key']}")

    def _on_image_remove_env(self) -> None:
        entry = self._image_entry()
        selection = self.image_env_tree.selection()
        if entry is None or not selection:
            self.status.set("Refused: Select an environment row first.")
            messagebox.showinfo("Salad Studio", "Select an environment row first.")
            return
        name = str(self.image_env_tree.item(selection[0], "values")[0])
        settings, removed = image_deploy.remove_env(self._image_settings, str(entry["key"]), name)
        if not removed:
            note = f"{name} comes from the metadata document, so remove it there."
            self.status.set(f"Refused: {note}")
            messagebox.showinfo("Salad Studio", note)
            return
        self._store_image_settings(settings, f"removed {name} from {entry['key']}")

    def _on_image_save(self) -> None:
        self._store_image_settings(self._image_settings, "saved the environment")

    def _on_image_copy(self) -> None:
        """Put the shown commands on the clipboard."""
        text = self.image_script.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Salad Studio", "Nothing to copy yet.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()
        note = (
            "copied the commands with the token values"
            if self.var_image_include.get()
            else "copied the commands (tokens as placeholders)"
        )
        self.var_image_status.set(note)
        self.log("ok", f"images: {note}")

    def _on_image_add_image(self) -> None:
        settings, refusal = image_deploy.add_image(
            self._image_settings,
            self.var_image_new_name.get(),
            self.var_image_new_tag.get(),
            context=self.var_image_new_context.get(),
            build_arg=self.var_image_new_arg.get(),
            ports={
                studio_meta.PORT_API: self.var_image_new_api.get(),
                studio_meta.PORT_COMFY: self.var_image_new_comfy.get(),
            },
        )
        if refusal:
            self.status.set(f"Refused: {refusal}")
            self.log("warn", f"Refused: {refusal}")
            messagebox.showinfo("Salad Studio", refusal)
            return
        name = self.var_image_new_name.get().strip()
        self.var_image_new_name.set("")
        self.var_image_new_tag.set("")
        self.var_image_new_arg.set("")
        self.var_image_new_api.set("")
        self.var_image_new_comfy.set("")
        self._store_image_settings(settings, f"added the image {name}")
        self.var_image_key.set(name)
        self._refresh_images_page()

    def _on_image_remove_image(self) -> None:
        entry = self._image_entry()
        if entry is None or str(entry.get("source")) != image_deploy.SOURCE_SETTINGS:
            messagebox.showinfo(
                "Salad Studio",
                "Only an image you added here can be removed; the document owns the rest.",
            )
            return
        env_rows = (self._image_settings.get("env") or {}).get(str(entry["key"])) or []
        extra = f" and its {len(env_rows)} environment entry(s)" if env_rows else ""
        if not messagebox.askyesno(
            "Salad Studio", f"Remove the image '{entry['key']}'{extra}?"
        ):
            self.status.set(f"Kept the image {entry['key']}")
            self.log("info", f"kept the image {entry['key']}")
            return
        settings, removed = image_deploy.remove_image(self._image_settings, str(entry["key"]))
        if not removed:
            return
        self.var_image_key.set("")
        self._store_image_settings(settings, f"removed the image {entry['key']}")

    def _salad_api_key(self) -> str:
        return tokens.resolve_salad_key()

    def _build_loras_tab(self) -> None:
        self._loras = ttk.Frame(self.nb)
        body = self._scrollable_page(self._loras)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        find = ttk.Frame(body)
        find.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(find, text="Find by name").pack(side="left")
        self.var_lora_find = tk.StringVar()
        ttk.Entry(find, textvariable=self.var_lora_find, width=32).pack(
            side="left", padx=6
        )
        ttk.Button(find, text="Clear", command=lambda: self.var_lora_find.set("")).pack(
            side="left"
        )
        ttk.Label(find, text="a part of the name is enough").pack(side="left", padx=(8, 0))
        self._lora_sort: tuple[str, bool] = ("", False)
        self.lora_tree = ttk.Treeview(
            body, columns=LORA_COLUMNS, show="headings", height=12
        )
        for col, heading, width in (
            ("verified", "Verified", 80),
            ("id", "Id", 200),
            ("name", "Name", 160),
            ("version", "Version", 120),
            ("model", "Model", 110),
            ("source", "Source", 100),
            ("filename", "Comfy name", 180),
        ):
            # A heading click orders the grid by that column, and clicking it
            # again reverses the order.
            self.lora_tree.heading(
                col, text=heading, command=lambda c=col: self._sort_lora_tree(c)
            )
            self.lora_tree.column(col, width=width)
        # The dot's colour rides the row's tag: Treeview colours a row, not a cell.
        self.lora_tree.tag_configure("verified", foreground=theme.PALETTE["valid"])
        self.lora_tree.tag_configure("unverified", foreground=theme.PALETTE["invalid"])
        self.lora_tree.grid(row=1, column=0, sticky="nsew")
        self.lora_tree.bind("<<TreeviewSelect>>", self._on_lora_tree_select)
        self.var_lora_find.trace_add("write", lambda *_a: self._refresh_lora_tree())
        add = ttk.LabelFrame(body, text="Add / edit LoRA", padding=8)
        add.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        add.columnconfigure(1, weight=1)
        ttk.Label(add, text="Civitai / HF URL / civitai:id@version / local path").grid(
            row=0, column=0, sticky="w"
        )
        self.var_lora_ref = tk.StringVar()
        ttk.Entry(add, textvariable=self.var_lora_ref).grid(
            row=0, column=1, sticky="ew", padx=6, pady=2
        )
        ttk.Label(add, text="Name (optional)").grid(row=1, column=0, sticky="w")
        self.var_lora_name = tk.StringVar()
        ttk.Entry(add, textvariable=self.var_lora_name).grid(
            row=1, column=1, sticky="ew", padx=6, pady=2
        )
        ttk.Label(add, text="Filename (optional)").grid(row=2, column=0, sticky="w")
        self.var_lora_file = tk.StringVar()
        ttk.Entry(add, textvariable=self.var_lora_file).grid(
            row=2, column=1, sticky="ew", padx=6, pady=2
        )
        ttk.Label(add, text="Works with").grid(row=3, column=0, sticky="w")
        self.var_lora_family = tk.StringVar(value="Flux.2 Klein")
        family_box = ttk.Combobox(
            add,
            textvariable=self.var_lora_family,
            values=lora_store.FAMILY_CHOICES,
            state="readonly",
        )
        family_box.grid(row=3, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(add, text="Strength model").grid(row=4, column=0, sticky="w")
        self.var_lora_sm = tk.StringVar(value="1.0")
        ttk.Entry(add, textvariable=self.var_lora_sm, width=10).grid(
            row=4, column=1, sticky="w", padx=6, pady=2
        )
        ttk.Label(add, text="Strength clip").grid(row=5, column=0, sticky="w")
        self.var_lora_sc = tk.StringVar(value="1.0")
        ttk.Entry(add, textvariable=self.var_lora_sc, width=10).grid(
            row=5, column=1, sticky="w", padx=6, pady=2
        )
        row = ttk.Frame(add)
        row.grid(row=6, column=1, sticky="w", pady=6)
        ttk.Button(row, text="Add", command=self._on_add_lora).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Save edits", command=self._on_edit_lora).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(row, text="Verify", command=self._on_verify_lora).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(row, text="Verify unverified", command=self._on_verify_unverified).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(row, text="Remove extra", command=self._on_remove_lora).pack(side="left")

    def _build_editor_tab(self) -> None:
        self._editor = ttk.Frame(self.nb)
        body = self._scrollable_page(self._editor)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        pane = ttk.Panedwindow(body, orient=tk.HORIZONTAL)
        self._editor_pane = pane
        self._editor_sash_set = False
        pane.grid(row=0, column=0, sticky="nsew")
        pane.bind("<Map>", self._place_editor_sash)
        left = ttk.Frame(pane)
        self._editor_box = left
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.editor_text = tk.Text(left, wrap="none", height=16, font=("Consolas", 10))
        theme.style_text(self.editor_text)
        yscroll = ttk.Scrollbar(left, orient="vertical", command=self.editor_text.yview)
        xscroll = ttk.Scrollbar(left, orient="horizontal", command=self.editor_text.xview)
        self.editor_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.editor_text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.editor_text.configure(state="normal")
        self._graph_stale = False
        self.editor_text.bind("<KeyRelease>", lambda _e: self._on_editor_edited())
        self.editor_text.bind("<FocusIn>", self._on_editor_focus_in)
        self.editor_text.bind("<Button-1>", self._on_editor_focus_in)
        left.bind("<Button-1>", self._on_editor_focus_in)
        self.editor_text.bind("<FocusOut>", self._on_editor_focus_out)
        self.editor_text.bind("<Control-v>", self._editor_paste)
        self.editor_text.bind("<Control-V>", self._editor_paste)
        self.editor_text.bind("<Shift-Insert>", self._editor_paste)
        self.editor_text.bind("<Control-c>", self._editor_copy)
        self.editor_text.bind("<Control-C>", self._editor_copy)
        self.editor_text.bind("<Control-x>", self._editor_cut)
        self.editor_text.bind("<Control-X>", self._editor_cut)
        for seq in ("<Control-a>", "<Control-A>", "<Control-Key-a>", "<<SelectAll>>"):
            self.editor_text.bind(seq, self._editor_select_all)
        self.bind_all("<Button-1>", self._on_click_outside_graph, add="+")
        right = ttk.Frame(pane)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.graph_pane = graph_view.GraphPane(right, on_swap=self._on_graph_swap)
        self.graph_pane.grid(row=0, column=0, sticky="nsew")
        pane.add(left, weight=1)
        pane.add(right, weight=3)
        prompts = ttk.Frame(body)
        self._editor_prompts = prompts
        prompts.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        # Positive on the left, negative on the right; the positive box is the
        # wider one because prompt text is longer than the negative list.
        prompts.columnconfigure(0, weight=66)
        prompts.columnconfigure(1, weight=34)
        prompts.rowconfigure(0, weight=1)
        pos_box = ttk.LabelFrame(prompts, text="Positive prompt", padding=8)
        pos_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        pos_box.columnconfigure(0, weight=1)
        pos_box.rowconfigure(0, weight=1)
        self.prompt_text = tk.Text(pos_box, wrap="word", height=5)
        theme.style_text(self.prompt_text)
        self.prompt_text.grid(row=0, column=0, sticky="nsew")
        self.prompt_text.insert(
            "1.0",
            "ArsMJStyle, Impressionism, cream paper, no signature, no watermark\n",
        )
        self.prompt_text.bind("<KeyRelease>", lambda _e: self._patch_editor_from_prompt())
        neg_box = ttk.LabelFrame(prompts, text="Negative prompt", padding=8)
        neg_box.grid(row=0, column=1, sticky="nsew")
        neg_box.columnconfigure(0, weight=1)
        neg_box.rowconfigure(0, weight=1)
        self.negative_text = tk.Text(neg_box, wrap="word", height=5)
        theme.style_text(self.negative_text)
        self.negative_text.grid(row=0, column=0, sticky="nsew")
        self.negative_text.bind("<KeyRelease>", lambda _e: self._patch_editor_from_prompt())
        bar = ttk.Frame(body)
        self._editor_bar = bar
        bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="Rebuild from Config", command=self._sync_editor).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(bar, text="Rebuild from JSON", command=self._rebuild_from_json).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(bar, text="Validate", command=self._validate_editor).pack(
            side="left", padx=(0, 6)
        )
        self.json_status = tk.StringVar(value="")
        self.json_status_lbl = ttk.Label(bar, textvariable=self.json_status)
        self.json_status_lbl.pack(side="left", padx=(12, 0))

    def _build_prompt_helper_tab(self) -> None:
        """Mirror the editor's prompts, edit an adjusted pair, ask a model for help.

        Two backends fill the same boxes: DeepSeek (the key on the Tokens tab)
        and the local OpenAI-compatible server (LM Studio by default) named in
        the local URL field below. Every string here that names a backend says
        which one, and the ones both use do not name either.
        """
        self._helper = ttk.Frame(self.nb)
        body = self._scrollable_page(self._helper)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        mirror = ttk.LabelFrame(
            body, text="Current prompts (from the Prompt Editor)", padding=8
        )
        mirror.grid(row=0, column=0, sticky="ew")
        mirror.columnconfigure(0, weight=1)
        mirror.columnconfigure(1, weight=1)
        ttk.Label(mirror, text="Positive").grid(row=0, column=0, sticky="w")
        ttk.Label(mirror, text="Negative").grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.helper_editor_pos = tk.Text(mirror, wrap="word", height=4, state="disabled")
        theme.style_text(self.helper_editor_pos)
        self.helper_editor_pos.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(2, 0))
        self.helper_editor_neg = tk.Text(mirror, wrap="word", height=4, state="disabled")
        theme.style_text(self.helper_editor_neg)
        self.helper_editor_neg.grid(row=1, column=1, sticky="nsew", pady=(2, 0))

        adjusted = ttk.LabelFrame(
            body, text="Adjusted prompts (edit these; Help rewrites them)", padding=8
        )
        adjusted.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        adjusted.columnconfigure(0, weight=1)
        adjusted.columnconfigure(1, weight=1)
        adjusted.rowconfigure(1, weight=1)
        ttk.Label(adjusted, text="Adjusted positive").grid(row=0, column=0, sticky="w")
        ttk.Label(adjusted, text="Adjusted negative").grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        self.helper_adj_pos = tk.Text(adjusted, wrap="word", height=8)
        theme.style_text(self.helper_adj_pos)
        self.helper_adj_pos.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(2, 0))
        self.helper_adj_neg = tk.Text(adjusted, wrap="word", height=8)
        theme.style_text(self.helper_adj_neg)
        self.helper_adj_neg.grid(row=1, column=1, sticky="nsew", pady=(2, 0))

        issue_box = ttk.LabelFrame(
            body,
            text="Image issue / problem (highest priority, the AI must fix this first)",
            padding=8,
        )
        issue_box.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        issue_box.columnconfigure(0, weight=1)
        self.helper_issue = tk.Text(issue_box, wrap="word", height=3)
        theme.style_text(self.helper_issue)
        self.helper_issue.grid(row=0, column=0, sticky="ew")
        image_row = ttk.Frame(issue_box)
        image_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.var_helper_image = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            image_row,
            text="Send the latest generated image",
            variable=self.var_helper_image,
            command=self._refresh_helper_image_label,
        ).pack(side="left")
        self.helper_image_lbl = ttk.Label(image_row, text="")
        self.helper_image_lbl.pack(side="left", padx=(10, 0))

        bar = ttk.Frame(body)
        bar.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(
            bar, text="Refresh from Prompt Editor", command=self._refresh_prompt_helper
        ).pack(side="left", padx=(0, 6))
        self.helper_btn = ttk.Button(
            bar, text="Help (DeepSeek)", command=self._on_prompt_help
        )
        self.helper_btn.pack(side="left", padx=(0, 6))
        self.helper_local_btn = ttk.Button(
            bar, text="Help (local)", command=self._on_prompt_help_local
        )
        self.helper_local_btn.pack(side="left", padx=(0, 6))
        self.helper_commit_btn = ttk.Button(
            bar, text="Commit to Prompts + JSON", command=self._on_prompt_commit
        )
        self.helper_commit_btn.pack(side="left")
        self.helper_state = tk.StringVar(value="Idle")
        ttk.Label(bar, textvariable=self.helper_state).pack(side="left", padx=(12, 0))
        # What the local model the page last asked can do with an image, so the
        # note above can say it instead of claiming the plate will be read.
        self._helper_local_vision: bool | None = None
        self._helper_local_model = ""

        local_row = ttk.Frame(body)
        local_row.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(local_row, text="Local LLM URL (LM Studio)").pack(side="left")
        self.var_helper_local_url = tk.StringVar(value=ai_helper.LOCAL_BASE_URL)
        ttk.Entry(local_row, textvariable=self.var_helper_local_url, width=38).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(
            local_row,
            text="OpenAI-compatible base, e.g. http://localhost:1234/v1",
        ).pack(side="left", padx=(8, 0))

        reply_box = ttk.LabelFrame(
            body, text="Reply (raw, from DeepSeek or the local model)", padding=8
        )
        reply_box.grid(row=5, column=0, sticky="nsew", pady=(8, 0))
        reply_box.columnconfigure(0, weight=1)
        reply_box.rowconfigure(0, weight=1)
        self.helper_reply = tk.Text(reply_box, wrap="word", height=7, state="disabled")
        theme.style_text(self.helper_reply)
        self.helper_reply.grid(row=0, column=0, sticky="nsew")
        self._set_helper_reply("")
        self._refresh_helper_image_label()

    def _latest_generated_image(self) -> Path | None:
        """The newest plate Salad Studio wrote (the one the artist just saw)."""
        plates = generator.list_history(OUT_DIR)
        if plates:
            return plates[0]
        return None

    def _refresh_helper_image_label(self) -> None:
        """Say what the image tick will do, for the model that will answer.

        The note is about the box, so it names no backend; when the local model
        the page last asked reported that it cannot take an image, the note says
        that rather than claiming the plate is going to be read.
        """
        latest = self._latest_generated_image()
        if not self.var_helper_image.get():
            text = "off, no image is sent"
        elif latest is None:
            text = "no generated image yet, nothing will be attached"
        elif self._helper_local_vision is False:
            who = self._helper_local_model or "the local model"
            text = f"{who} cannot take an image, so {latest.name} is sent but ignored"
        else:
            text = f"attaching {latest.name}"
        try:
            self.helper_image_lbl.configure(text=text)
        except tk.TclError:
            pass

    def _set_helper_reply(self, text: str) -> None:
        widget = self.helper_reply
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if text:
            widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _set_helper_mirror(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text or "")
        widget.configure(state="disabled")

    def _refresh_prompt_helper(self) -> None:
        """Copy the Prompt Editor's current prompts into the read-only mirror."""
        self._set_helper_mirror(
            self.helper_editor_pos, self.prompt_text.get("1.0", "end-1c")
        )
        self._set_helper_mirror(
            self.helper_editor_neg, self.negative_text.get("1.0", "end-1c")
        )
        self._refresh_helper_image_label()

    def _helper_inputs(self) -> dict[str, str]:
        """The context inputs, straight from the live widgets."""
        return {
            "editor_positive": self.prompt_text.get("1.0", "end-1c").strip(),
            "editor_negative": self.negative_text.get("1.0", "end-1c").strip(),
            "adjusted_positive": self.helper_adj_pos.get("1.0", "end-1c").strip(),
            "adjusted_negative": self.helper_adj_neg.get("1.0", "end-1c").strip(),
            "request_json": self.editor_text.get("1.0", "end-1c").strip(),
            "issue": self.helper_issue.get("1.0", "end-1c").strip(),
        }

    def _helper_findings(self, inputs: dict[str, str]) -> tuple[str, list[dict]]:
        """Resolve the request's weights for the AI (local first, then online)."""
        try:
            payload = generator.parse_request_json(inputs["request_json"])
        except (ValueError, json.JSONDecodeError) as e:
            self.log("warn", f"Prompt Assist: request JSON is invalid ({e})")
            return f"(the Prompt Editor JSON could not be parsed: {e})", []
        findings = ref_check.resolve_refs(payload)
        return ref_check.format_findings(findings), findings

    def _on_prompt_help(self) -> None:
        """Help from DeepSeek (needs the key on the Tokens tab)."""
        self._start_helper_call("deepseek")

    def _on_prompt_help_local(self) -> None:
        """Help from the LLM served by the local LM Studio URL."""
        self._start_helper_call("local")

    def _start_helper_call(self, backend: str) -> None:
        if self._helper_busy:
            return
        inputs = self._helper_inputs()
        label = "DeepSeek" if backend == "deepseek" else "the local model"
        key = ""
        if backend == "deepseek":
            key = tokens.read_token("deepseek")
            if not key:
                self.helper_state.set("No DeepSeek key. Save one on the Tokens tab")
                note = (
                    "No DeepSeek key is saved. Add it on the Tokens tab, then press "
                    "Help again."
                )
                self._set_helper_reply(note)
                # The reply box is the only surface carrying this, and the next
                # reply overwrites it; the status line keeps the last success.
                self.status.set(f"Refused: {note}")
                self.log("error", "Prompt Assist: DeepSeek key is empty")
                return
        # Read the URL here: the worker thread must not touch Tk widgets.
        local_url = self.var_helper_local_url.get()
        self._helper_busy = True
        for btn in (self.helper_btn, self.helper_local_btn):
            try:
                btn.configure(state="disabled")
            except tk.TclError:
                pass
        self.helper_state.set(f"Asking {label}…")
        self.status.set(f"Prompt Assist: asking {label}…")
        image = self._latest_generated_image() if self.var_helper_image.get() else None
        if image is not None:
            self.log("info", f"Prompt Assist: attaching {image.name}")
        elif self.var_helper_image.get():
            self.log("warn", "Prompt Assist: no generated image to attach")
        self.log("info", f"Prompt Assist: {label} help requested")

        def work() -> None:
            findings_text = ""
            try:
                findings_text, findings = self._helper_findings(inputs)
                unresolved = ref_check.unresolved(findings)
                if unresolved:
                    self.log(
                        "warn",
                        "Prompt Assist: unresolved weights "
                        + ", ".join(str(f.get("name")) for f in unresolved),
                    )
                if backend == "deepseek":
                    out = ai_helper.help_with_prompts(
                        key, findings=findings_text, image_path=image, **inputs
                    )
                else:
                    # Ask the local server which model will answer first, so the
                    # page can say what that model does with an image before the
                    # request goes out, and so the id it advertises is the one
                    # sent. The helper would discover the same list itself.
                    picked: dict = {}
                    try:
                        picked = ai_helper.choose_local_model(
                            ai_helper.local_models(ai_helper.local_base(local_url))
                        )
                    except Exception as e:  # noqa: BLE001 - the call below reports it
                        self.log("warn", f"Prompt Assist: local model list failed ({e})")
                    if picked:
                        self._later(0, lambda p=picked: self._note_local_model(p))
                    out = ai_helper.help_with_prompts_local(
                        url=local_url,
                        model=str(picked.get("id") or ""),
                        findings=findings_text,
                        image_path=image,
                        **inputs,
                    )
                self._later(0, lambda: self._helper_done(out, None, backend))
            except ai_helper.ReplyError as e:
                self._later(0, lambda err=e: self._helper_done(None, err, backend))
            except Exception as e:  # noqa: BLE001 - surface every failure in the page
                self._later(0, lambda err=e: self._helper_done(None, err, backend))

        threading.Thread(target=work, daemon=True).start()

    def _on_prompt_commit(self) -> None:
        """Write the adjusted prompts into the editor's prompt boxes and its JSON."""
        positive = self.helper_adj_pos.get("1.0", "end-1c").strip()
        negative = self.helper_adj_neg.get("1.0", "end-1c").strip()
        if not positive and not negative:
            messagebox.showinfo(
                "Salad Studio",
                "The adjusted prompts are empty. Ask DeepSeek or the local model "
                "for help first.",
            )
            return
        # The prompt boxes are the live source the JSON is patched from, so
        # writing them and re-running the shipped patch does both in one step.
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", positive)
        self.negative_text.delete("1.0", "end")
        self.negative_text.insert("1.0", negative)
        patched = self._patch_editor_from_prompt()
        self._refresh_prompt_helper()
        if patched:
            self.status.set("Prompt Assist: committed to the prompts and the JSON")
            self.log("ok", "Prompt Assist: adjusted prompts committed to the editor JSON")
        else:
            # _patch_editor_from_prompt rebuilds the graph from Prompt Settings
            # when the editor JSON cannot take the text, so say that out loud.
            self.status.set("Prompt Assist: committed (the JSON was rebuilt)")
            self.log(
                "warn",
                "Prompt Assist: the editor JSON was rebuilt from Prompt Settings "
                "because it could not be patched",
            )

    def _note_local_model(self, picked: dict) -> None:
        """Record what the local model about to answer can do with an image.

        Called on the Tk thread once the worker has the server's model list, so
        the image note and the state can be honest before the reply arrives. A
        model that reports no image support still gets the plate (the page does
        not gate on capabilities), and the note says so instead of claiming the
        plate is going to be read.
        """
        self._helper_local_model = str(picked.get("id") or "")
        vision = picked.get("vision")
        self._helper_local_vision = None if vision is None else bool(vision)
        self._refresh_helper_image_label()
        if self.var_helper_image.get() and self._helper_local_vision is False:
            self.helper_state.set(
                f"{self._helper_local_model} reports no image support; the plate is "
                "sent anyway"
            )
            self.log(
                "warn",
                f"Prompt Assist: {self._helper_local_model} reports no image "
                "support; the plate is attached anyway",
            )

    def _helper_done(
        self, out: dict | None, err: Exception | None, backend: str = "deepseek"
    ) -> None:
        self._helper_busy = False
        label = "DeepSeek" if backend == "deepseek" else "the local model"
        for btn in (self.helper_btn, self.helper_local_btn):
            try:
                btn.configure(state="normal")
            except tk.TclError:
                pass
        if isinstance(err, ai_helper.ReplyError):
            # Never blank the boxes: show the model's raw words instead.
            self._set_helper_reply(err.raw or str(err))
            self.helper_state.set("Reply was not usable. Raw text shown below")
            self.status.set("Prompt Assist: reply could not be parsed")
            self.log("warn", f"Prompt Assist: unparsable reply from {label} ({err})")
            return
        if err is not None:
            self._set_helper_reply(f"{type(err).__name__}: {err}")
            self.helper_state.set(f"{label} failed: {err}")
            self.status.set(f"Prompt Assist: {label} call failed")
            self.log("error", f"Prompt Assist ({label}): {err}")
            return
        assert out is not None
        # A reply that is missing one of the two prompts. A reasoning model
        # that restarted its JSON can leave one empty. Must not wipe what the
        # artist typed in that box.
        blank: list[str] = []
        for widget, value, name in (
            (self.helper_adj_pos, out.get("positive") or "", "positive"),
            (self.helper_adj_neg, out.get("negative") or "", "negative"),
        ):
            if str(value).strip():
                widget.delete("1.0", "end")
                widget.insert("1.0", value)
            else:
                blank.append(name)
        if blank:
            self.log(
                "warn",
                f"Prompt Assist: the {label} reply carried no "
                f"{' or '.join(blank)} prompt. What you had there is kept",
            )
        self._set_helper_reply(str(out.get("raw") or ""))
        if backend == "local":
            # The reply carries what the server said about the model it used;
            # keep the note in step with it (a model picked by id is not
            # re-discovered, so this is the only place that knows).
            self._helper_local_model = str(out.get("model") or self._helper_local_model)
            vision = out.get("vision")
            if vision is not None:
                self._helper_local_vision = bool(vision)
                self._refresh_helper_image_label()
        found = str(out.get("issue") or "").strip()
        if found:
            self.helper_state.set(f"Adjusted prompts updated. Image issue: {found[:140]}")
            self.log("info", f"Prompt Assist: {label} saw, {found}")
        else:
            self.helper_state.set(f"Adjusted prompts updated from {label}")
        self.status.set("Prompt Assist: adjusted prompts updated")
        model = str(out.get("model") or ai_helper.MODEL)
        self.log("ok", f"Prompt Assist: {label} updated the adjusted prompts ({model})")
        continued = int(out.get("continued") or 0)
        if continued:
            # The API cut the answer at the token limit and the rest was asked
            # for, so the boxes hold the whole reply rather than its first part.
            self.log(
                "warn",
                f"Prompt Assist: the {label} reply hit the token limit and was "
                f"completed in {continued} continuation(s)",
            )

    @staticmethod
    def _page_keeps_its_own_size(body: ttk.Frame, scroller) -> None:
        """Keep ``scroller``'s own request out of the page's requested size.

        A Treeview asks for the sum of its columns and for every row it can
        show. A page that asked for that would size the whole window from it
        again - which is what the Prompt Catalog, Prompt History and Queue pages
        did before they scrolled, and what made the window open 1455x1238. A
        page built this way keeps the size the rest of its content needs, the
        tree is squeezed into what is left of the canvas, and the tree's own
        bars are what bring its columns and its rows back.
        """
        body.update_idletasks()
        others = [child for child in body.winfo_children() if child is not scroller]
        rest_w = max([int(child.winfo_reqwidth()) for child in others] or [1])
        rest_h = max(1, int(body.winfo_reqheight()) - int(scroller.winfo_reqheight()))
        body.grid_propagate(False)
        body.configure(width=rest_w, height=rest_h)

    def _build_prompt_catalog_tab(self) -> None:
        # Wrapped the way its eight siblings are: five columns of Treeview would
        # otherwise set the window's size for the whole layout. The frame the
        # content lives in keeps the name it always had, so every control and
        # every lookup below stays where it was.
        self._catalog_page = ttk.Frame(self.nb)
        self._catalog = self._scrollable_page(self._catalog_page)
        self._catalog.columnconfigure(0, weight=1)
        self._catalog.rowconfigure(1, weight=1)
        form = ttk.Frame(self._catalog)
        form.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=2)
        ttk.Label(form, text="Short name").grid(row=0, column=0, sticky="w")
        self.var_cat_name = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_cat_name).grid(
            row=0, column=1, sticky="ew", padx=(6, 12)
        )
        ttk.Label(form, text="Description").grid(row=0, column=2, sticky="w")
        self.var_cat_desc = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_cat_desc).grid(
            row=0, column=3, sticky="ew", padx=(6, 0)
        )
        cols = ("when", "name", "description", "preview", "stats")
        self.catalog_tree = ttk.Treeview(
            self._catalog, columns=cols, show="headings", height=16
        )
        for col, heading, width, _fill in CATALOG_GRID_COLUMNS:
            self.catalog_tree.heading(col, text=heading)
            self.catalog_tree.column(col, width=width, stretch=False)
        self._keep_grid_filling(self._catalog_page, self.catalog_tree, CATALOG_GRID_COLUMNS)
        self.catalog_tree.grid(row=1, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(
            self._catalog, orient="vertical", command=self.catalog_tree.yview
        )
        # The columns total more than a narrow window, so the right-hand ones
        # (the Graph column among them) are off-screen without a bar to reach
        # them; the vertical bar alone leaves them unreachable.
        hscroll = ttk.Scrollbar(
            self._catalog, orient="horizontal", command=self.catalog_tree.xview
        )
        self.catalog_tree.configure(
            yscrollcommand=yscroll.set, xscrollcommand=hscroll.set
        )
        yscroll.grid(row=1, column=1, sticky="ns")
        hscroll.grid(row=2, column=0, sticky="ew")
        self.catalog_tree.bind("<<TreeviewSelect>>", lambda _e: self._fill_catalog_form())
        self.catalog_tree.bind("<Double-1>", lambda _e: self._on_catalog_load())
        bar = ttk.Frame(self._catalog)
        bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(
            bar, text="Copy from Prompt Editor", command=self._on_catalog_add
        ).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Update JSON", command=self._on_catalog_update_json).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(
            bar, text="Save name / description", command=self._on_catalog_save_meta
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            bar, text="Load into Prompt Editor", command=self._on_catalog_load
        ).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Delete", command=self._on_catalog_delete).pack(side="left")
        self.catalog_empty_lbl = ttk.Label(
            self._catalog, text=CATALOG_EMPTY_TEXT, style="Status.TLabel"
        )
        self.catalog_empty_lbl.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.catalog_status = tk.StringVar(value="")
        ttk.Label(self._catalog, textvariable=self.catalog_status).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        self._page_keeps_its_own_size(self._catalog, self.catalog_tree)
        self._refresh_prompt_catalog()

    def _selected_catalog_id(self) -> str | None:
        sel = self.catalog_tree.selection()
        return str(sel[0]) if sel else None

    def _fill_catalog_form(self) -> None:
        entry = prompt_catalog.get_entry(self._selected_catalog_id() or "")
        if entry is None:
            return
        self.var_cat_name.set(str(entry.get("name") or ""))
        self.var_cat_desc.set(str(entry.get("description") or ""))

    def _editor_payload_for_catalog(self) -> dict | None:
        raw = self.editor_text.get("1.0", "end").strip()
        try:
            return generator.parse_request_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            messagebox.showerror("Salad Studio", f"Prompt Editor JSON is invalid: {e}")
            return None

    def _refresh_prompt_catalog(self) -> None:
        tree = self.catalog_tree
        keep = self._selected_catalog_id()
        for child in tree.get_children():
            tree.delete(child)
        for entry in prompt_catalog.list_entries():
            req = entry.get("request") if isinstance(entry.get("request"), dict) else None
            tree.insert(
                "",
                "end",
                iid=str(entry.get("id") or ""),
                values=(
                    time.strftime(
                        "%Y-%m-%d %H:%M", time.localtime(int(entry.get("ts") or 0))
                    ),
                    str(entry.get("name") or ""),
                    str(entry.get("description") or ""),
                    prompt_history.preview(prompt_history.prompt_text_of(req)),
                    prompt_catalog.entry_stats(entry),
                ),
            )
        if keep and keep in tree.get_children():
            tree.selection_set(keep)
        empty = getattr(self, "catalog_empty_lbl", None)
        if empty is not None:
            if tree.get_children():
                empty.grid_remove()
            else:
                empty.grid()

    def _on_catalog_add(self) -> None:
        name = self.var_cat_name.get().strip()
        if not name:
            messagebox.showinfo("Salad Studio", "Give the prompt a short name first.")
            return
        payload = self._editor_payload_for_catalog()
        if payload is None:
            return
        try:
            entry = prompt_catalog.add_entry(name, self.var_cat_desc.get(), payload)
        except ValueError as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._refresh_prompt_catalog()
        self.catalog_tree.selection_set(str(entry["id"]))
        self.catalog_status.set(f"Copied '{entry['name']}' from the Prompt Editor")
        self.status.set(f"Catalog: added {entry['name']}")
        self.log("ok", f"catalog + {entry['name']}  {prompt_catalog.entry_stats(entry)}")

    def _on_catalog_update_json(self) -> None:
        entry_id = self._selected_catalog_id()
        if not entry_id:
            messagebox.showinfo("Salad Studio", "Select a catalog entry first.")
            return
        payload = self._editor_payload_for_catalog()
        if payload is None:
            return
        try:
            entry = prompt_catalog.update_entry(entry_id, request=payload)
        except ValueError as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._refresh_prompt_catalog()
        self.catalog_status.set(f"Updated the JSON of '{entry['name']}'")
        self.status.set(f"Catalog: updated {entry['name']}")
        self.log("ok", f"catalog json <- editor  {entry['name']}")

    def _on_catalog_save_meta(self) -> None:
        entry_id = self._selected_catalog_id()
        if not entry_id:
            messagebox.showinfo("Salad Studio", "Select a catalog entry first.")
            return
        try:
            entry = prompt_catalog.update_entry(
                entry_id, name=self.var_cat_name.get(), description=self.var_cat_desc.get()
            )
        except ValueError as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._refresh_prompt_catalog()
        self.catalog_status.set(f"Saved '{entry['name']}'")
        self.status.set(f"Catalog: saved {entry['name']}")
        self.log("ok", f"catalog name/description saved  {entry['name']}")

    def _on_catalog_load(self) -> None:
        entry = prompt_catalog.get_entry(self._selected_catalog_id() or "")
        if entry is None:
            messagebox.showinfo("Salad Studio", "Select a catalog entry to load.")
            return
        self._set_editor_payload(entry["request"], remember=False)
        self.catalog_status.set(f"Loaded '{entry['name']}' into the Prompt Editor")
        self.status.set(f"Catalog: loaded {entry['name']}")
        self.log(
            "ok",
            f"catalog -> editor  {entry['name']}  {prompt_catalog.entry_stats(entry)}",
        )

    def _on_catalog_delete(self) -> None:
        entry = prompt_catalog.get_entry(self._selected_catalog_id() or "")
        if entry is None:
            messagebox.showinfo("Salad Studio", "Select a catalog entry to delete.")
            return
        if not messagebox.askyesno(
            "Salad Studio", f"Delete the catalog entry '{entry['name']}'?"
        ):
            return
        prompt_catalog.remove_entry(str(entry["id"]))
        self._refresh_prompt_catalog()
        self.catalog_status.set(f"Deleted '{entry['name']}'")
        self.status.set(f"Catalog: deleted {entry['name']}")
        self.log("warn", f"catalog - {entry['name']}")

    def _build_import_tab(self) -> None:
        self._import = ttk.Frame(self.nb)
        body = self._scrollable_page(self._import)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        body.rowconfigure(2, weight=2)
        url_box = ttk.LabelFrame(
            body,
            text="Civitai image URL (Copy All + Comfy nodes when the post has them)",
            padding=8,
        )
        url_box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        url_box.columnconfigure(1, weight=1)
        ttk.Label(url_box, text="URL").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.var_imp_image_url = tk.StringVar(value="")
        ttk.Entry(url_box, textvariable=self.var_imp_image_url).grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Button(
            url_box, text="Fetch from Civitai", command=self._on_fetch_civitai_image
        ).grid(row=0, column=2, sticky="e")
        meta_box = ttk.LabelFrame(
            body,
            text="Civitai generation data (prompt + Steps / CFG, or Sampler / Seed / Model)",
            padding=8,
        )
        meta_box.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        meta_box.columnconfigure(0, weight=1)
        meta_box.rowconfigure(0, weight=1)
        self.import_meta = tk.Text(meta_box, wrap="word", height=8, font=("Segoe UI", 10))
        theme.style_text(self.import_meta)
        self.import_meta.grid(row=0, column=0, sticky="nsew")
        wf_box = ttk.LabelFrame(
            body,
            text="Comfy workflow JSON (paste is held in memory. Clear Import if the UI crawls)",
            padding=8,
        )
        wf_box.grid(row=2, column=0, sticky="nsew")
        wf_box.columnconfigure(0, weight=1)
        wf_box.rowconfigure(0, weight=1)
        self._import_workflow_stash = ""
        self.import_workflow = tk.Text(
            wf_box, wrap="word", height=12, font=("Consolas", 9), undo=False
        )
        theme.style_text(self.import_workflow)
        yscroll = ttk.Scrollbar(
            wf_box, orient="vertical", command=self.import_workflow.yview
        )
        self.import_workflow.configure(yscrollcommand=yscroll.set)
        self.import_workflow.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        knobs = ttk.LabelFrame(
            body,
            text="Graph knobs (applied on Convert, empty = from paste; set to override)",
            padding=8,
        )
        knobs.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.var_imp_cfg = tk.StringVar(value="")
        self.var_imp_seed = tk.StringVar(value="")
        self.var_imp_steps = tk.StringVar(value="")
        self.var_imp_width = tk.StringVar(value="")
        self.var_imp_height = tk.StringVar(value="")
        self.var_imp_sched = tk.StringVar(value="Flux2 (Klein)")
        self.var_imp_unet = tk.StringVar(value="")
        fields = (
            ("CFG", self.var_imp_cfg),
            ("Seed", self.var_imp_seed),
            ("Steps", self.var_imp_steps),
            ("Width", self.var_imp_width),
            ("Height", self.var_imp_height),
        )
        for i, (lab, var) in enumerate(fields):
            ttk.Label(knobs, text=lab).grid(row=0, column=i * 2, sticky="w", padx=(0, 4))
            ttk.Entry(knobs, textvariable=var, width=14).grid(
                row=0, column=i * 2 + 1, sticky="w", padx=(0, 12)
            )
        ttk.Label(knobs, text="Scheduler").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            knobs,
            textvariable=self.var_imp_sched,
            values=("Flux2 (Klein)", "Simple (Civitai)"),
            state="readonly",
            width=20,
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(knobs, text="Checkpoint").grid(row=1, column=4, sticky="w", pady=(6, 0), padx=(12, 4))
        ttk.Combobox(
            knobs,
            textvariable=self.var_imp_unet,
            values=("",) + request_json.UNET_LABELS,
            state="readonly",
            width=16,
        ).grid(row=1, column=5, sticky="w", pady=(6, 0))
        iss_box = ttk.LabelFrame(
            body,
            text="Salad replica issues",
            padding=8,
        )
        iss_box.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        iss_box.columnconfigure(0, weight=1)
        iss_box.rowconfigure(0, weight=1)
        self.import_issues = tk.Text(
            iss_box, wrap="word", height=8, font=("Segoe UI", 10), undo=False
        )
        theme.style_text(self.import_issues)
        self.import_issues.grid(row=0, column=0, sticky="nsew")
        self.import_issues.configure(state="disabled")
        bar = ttk.Frame(body)
        bar.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="Fill knobs from paste", command=self._fill_import_knobs).pack(
            side="left"
        )
        ttk.Button(
            bar, text="Convert to Prompt Editor", command=self._on_import_civitai
        ).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Clear Import", command=self._clear_import).pack(
            side="left", padx=(8, 0)
        )
        self.import_meta.bind("<KeyRelease>", lambda _e: self._schedule_fill_import_knobs())
        # Huge Comfy JSON in a Text widget crawls the whole Tk app. Keep it
        # in memory and show a short summary; do not parse on every keystroke.
        self.import_workflow.bind("<<Paste>>", self._on_import_workflow_paste)

    def _set_editor_payload(self, payload: dict, *, remember: bool) -> None:
        dumped = json.dumps(payload, indent=2)
        self._syncing_editor = True
        try:
            self.editor_text.delete("1.0", "end")
            self.editor_text.insert("1.0", dumped)
        finally:
            self._syncing_editor = False
        self._rebuild_from_json(remember=remember)
        self._refresh_graph()
        self.nb.select(self._editor)

    def _cancel_fill_import_knobs(self) -> None:
        if getattr(self, "_imp_fill_after", None):
            try:
                self.after_cancel(self._imp_fill_after)
            except Exception:
                pass
            self._imp_fill_after = None

    def _schedule_fill_import_knobs(self) -> None:
        self._cancel_fill_import_knobs()
        self._imp_fill_after = self._later(400, lambda: self._fill_import_knobs(only_empty=True, quiet=True))

    def _on_import_workflow_paste(self, _event=None):
        try:
            clip = self.clipboard_get()
        except tk.TclError:
            return None
        raw = (clip or "").strip()
        if not raw:
            return None
        self._stash_import_workflow(raw)
        self._schedule_fill_import_knobs()
        return "break"

    def _stash_import_workflow(self, raw: str) -> None:
        text = (raw or "").strip()
        self._import_workflow_stash = text
        n = len(text)
        self.import_workflow.delete("1.0", "end")
        if not text:
            return
        self.import_workflow.insert(
            "1.0",
            f"[Comfy workflow JSON in memory, {n:,} characters]\n"
            "Not shown in this box so the UI stays fast. Convert uses this paste.\n"
            "Clear Import to drop it.",
        )

    def _import_workflow_text(self) -> str:
        stashed = (self._import_workflow_stash or "").strip()
        if stashed:
            return stashed
        text = self.import_workflow.get("1.0", "end").strip()
        if text.startswith("[Comfy workflow JSON in memory"):
            return ""
        return text

    def _set_import_issues(
        self, issues: list[str] | None, notes: list[str] | None = None
    ) -> None:
        widget = self.import_issues
        notes = notes or []
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if issues:
            lines = ["This graph cannot run on the Salad Klein replica:", ""]
            lines.extend(f"• {item}" for item in issues)
            if notes:
                lines.append("")
                lines.extend(f"• {item}" for item in notes)
            widget.insert("1.0", "\n".join(lines))
            widget.configure(foreground=theme.PALETTE["accent"])
        elif notes:
            widget.insert(
                "1.0",
                "Warnings:\n\n" + "\n".join(f"• {item}" for item in notes),
            )
            widget.configure(foreground=theme.PALETTE["fg_muted"])
        elif issues is None:
            widget.configure(foreground=theme.PALETTE["fg_muted"])
        else:
            widget.insert("1.0", "No replica issues.")
            widget.configure(foreground=theme.PALETTE["fg_muted"])
        widget.configure(state="disabled")

    def _refresh_import_issues(self) -> list[str]:
        wf = self._import_workflow_text()
        meta = self.import_meta.get("1.0", "end").strip()
        if not wf and not meta:
            self._set_import_issues(None)
            return []
        try:
            blocking, notes = comfy_import.inspect_pastes(meta, wf)
        except Exception as e:
            blocking, notes = [f"Could not inspect paste: {e}"], []
        self._set_import_issues(blocking, notes)
        return blocking

    def _clear_import(self) -> None:
        self._cancel_fill_import_knobs()
        self._import_workflow_stash = ""
        self.import_meta.delete("1.0", "end")
        self.import_workflow.delete("1.0", "end")
        self.var_imp_image_url.set("")
        self.var_imp_cfg.set("")
        self.var_imp_seed.set("")
        self.var_imp_steps.set("")
        self.var_imp_width.set("")
        self.var_imp_height.set("")
        self.var_imp_sched.set("Flux2 (Klein)")
        self.var_imp_unet.set("")
        self._set_import_issues(None)
        self.status.set("Import paste cleared")

    def _on_fetch_civitai_image(self) -> None:
        raw = (self.var_imp_image_url.get() or "").strip()
        if not raw:
            raw = self.import_meta.get("1.0", "end").strip()
        iid = comfy_import.ls.civitai_image_id(raw)
        if not iid and raw.isdigit():
            iid = raw
        if not iid:
            messagebox.showerror(
                "Salad Studio",
                "Paste a Civitai image URL like https://civitai.com/images/130704876",
            )
            return
        self.status.set(f"Fetching Civitai image {iid}…")
        self.update_idletasks()
        try:
            pastes = comfy_import.fetch_civitai_image_pastes(iid)
        except Exception as e:
            self.status.set("Civitai fetch failed")
            self.log("error", f"fetch image {iid}: {e}")
            messagebox.showerror("Salad Studio", str(e))
            return
        self.var_imp_image_url.set(f"https://civitai.com/images/{iid}")
        self.import_meta.delete("1.0", "end")
        self.import_meta.insert("1.0", pastes["metadata"])
        wf = str(pastes.get("workflow") or "").strip()
        tool = str(pastes.get("tool") or "").strip()
        if wf:
            self._stash_import_workflow(wf)
        else:
            self._import_workflow_stash = ""
            self.import_workflow.delete("1.0", "end")
        self._fill_import_knobs(only_empty=False, quiet=True)
        self._set_import_issues([])
        if "draw things" in tool.lower():
            self.status.set(f"Fetched {iid} (Draw Things)")
        elif wf:
            self.status.set(f"Fetched {iid} (Comfy)")
        else:
            self.status.set(f"Fetched {iid}")
        self.log("ok", f"fetched civitai image {iid} tool={tool or '-'}")

    def _fill_import_knobs(self, *, only_empty: bool = False, quiet: bool = False) -> None:
        wf = self._import_workflow_text()
        meta = self.import_meta.get("1.0", "end").strip()
        if not wf and not meta:
            self._set_import_issues(None)
            if not quiet:
                note = (
                    "Nothing to fill. Paste a Comfy workflow JSON and/or Civitai "
                    "generation data (prompt + Steps/CFG, or Sampler/Seed/Model)."
                )
                self.status.set(f"Refused: {note}")
                self.log("warn", "fill knobs refused: no workflow and no generation data")
                messagebox.showerror("Salad Studio", note)
            return
        try:
            knobs = comfy_import.knobs_from_sources(meta, wf)
        except Exception as e:
            self._set_import_issues([f"Could not parse paste: {e}"])
            if not quiet:
                messagebox.showerror("Salad Studio", f"Could not parse paste: {e}")
            return
        extra_notes: list[str] = []
        try:
            blocking, notes = comfy_import.inspect_pastes(meta, wf)
        except Exception as e:
            blocking, notes = [f"Could not inspect paste: {e}"], []
        self._set_import_issues(blocking, notes + extra_notes)

        def _set(var, value) -> None:
            if value in (None, ""):
                return
            if only_empty and var.get().strip():
                return
            var.set(str(value))

        _set(self.var_imp_cfg, knobs.get("cfg"))
        _set(self.var_imp_seed, knobs.get("seed"))
        _set(self.var_imp_steps, knobs.get("steps"))
        _set(self.var_imp_width, knobs.get("width"))
        _set(self.var_imp_height, knobs.get("height"))
        if knobs.get("scheduler") and (
            not only_empty
            or self.var_imp_sched.get().strip() in ("", "Flux2 (Klein)")
        ):
            self.var_imp_sched.set(self._scheduler_label(str(knobs.get("scheduler"))))
        if knobs.get("unet") and (not only_empty or not self.var_imp_unet.get().strip()):
            self.var_imp_unet.set(request_json.unet_label(str(knobs.get("unet"))))
        if not quiet:
            self.status.set("Import knobs filled from paste")

    def _import_knobs_from_form(self) -> dict:
        def _int(var, default=None):
            raw = var.get().strip()
            if not raw:
                return default
            try:
                return int(float(raw))
            except ValueError:
                return default

        def _num(var, default=None):
            raw = var.get().strip()
            if not raw:
                return default
            try:
                v = float(raw)
                return int(v) if v == int(v) else v
            except ValueError:
                return default

        return {
            "cfg": _num(self.var_imp_cfg, None),
            "seed": _int(self.var_imp_seed, None),
            "steps": _int(self.var_imp_steps, None),
            "width": _int(self.var_imp_width, None),
            "height": _int(self.var_imp_height, None),
            "scheduler": self._scheduler_id_from_label(self.var_imp_sched.get()),
            "unet": (
                request_json.normalize_unet(self.var_imp_unet.get())
                if self.var_imp_unet.get().strip()
                else None
            ),
        }

    def _scheduler_id_from_label(self, raw: str) -> str:
        return "simple" if "simple" in (raw or "").lower() else "flux2"

    def _import_generation_data(self, meta_text: str) -> bool:
        """Whether the generation-data box describes a picture on its own.

        The page's own wording for a bad paste asks for ``prompt + Steps/CFG, or
        Sampler/Seed/Model``; a Draw Things paste adds its Tools and Size. Bare
        text names no field at all, so there is nothing to build from it.
        """
        text = (meta_text or "").strip()
        if not text:
            return False
        if comfy_import.ls.civitai_image_id(text):
            return True
        parsed = comfy_import.parse_civitai_metadata(text)
        return any(
            parsed.get(field) not in (None, "", [], {})
            for field in (
                "steps",
                "cfg",
                "sampler",
                "scheduler",
                "seed",
                "model",
                "width",
                "height",
                "tools",
            )
        )

    def _on_import_civitai(self) -> None:
        wf = self._import_workflow_text()
        meta = self.import_meta.get("1.0", "end").strip()
        url = (self.var_imp_image_url.get() or "").strip()
        if url and comfy_import.ls.civitai_image_id(url) and not comfy_import.ls.civitai_image_id(meta):
            meta = url + "\n" + meta
        # Convert is a paste converter: with no workflow anywhere (split_pastes
        # also lifts a graph pasted into the generation-data box) and no
        # generation data, there is nothing to convert. Building the default
        # Klein graph from bare text would replace the graph the user wrote in
        # the Prompt Editor and report an import that never happened, so refuse
        # before anything is touched.
        _, wf_raw = comfy_import.split_pastes(meta, wf)
        if not wf_raw and not self._import_generation_data(meta):
            note = (
                "Nothing to convert. Paste a Comfy workflow JSON and/or Civitai "
                "generation data (prompt + Steps/CFG, or Sampler/Seed/Model)."
            )
            self.status.set(f"Refused: {note}")
            self.log("warn", "convert refused: no workflow and no generation data")
            messagebox.showerror("Salad Studio", note)
            return
        try:
            self._fill_import_knobs(only_empty=True, quiet=True)
            payload = comfy_import.import_to_request(
                workflow_text=wf,
                metadata_text=meta,
                knobs=self._import_knobs_from_form(),
            )
        except (ValueError, json.JSONDecodeError, TypeError) as e:
            self.status.set("Refused: cannot convert the Civitai paste")
            self.log("error", f"Import failed: {e}")
            messagebox.showerror("Salad Studio", f"Cannot convert Civitai paste: {e}")
            return
        self._stash_import_workflow("")
        census = comfy_import.comfy_convert_census_note(wf, payload)
        warn = ([census] if census else []) + list(comfy_import.replica_issues(payload))
        self._set_import_issues([], warn)
        self._set_editor_payload(payload, remember=True)
        stats = prompt_history.request_stats(payload)
        self.status.set(census or "Imported Civitai workflow to Prompt Editor")
        self.log("ok", f"imported Civitai paste  {stats}" + (f"  {census}" if census else ""))

    def _build_prompt_history_tab(self) -> None:
        # Wrapped like its siblings: the stored prompts' grid is taller than a
        # window, and the frame the content lives in keeps its own name.
        self._prompt_hist_page = ttk.Frame(self.nb)
        self._prompt_hist = self._scrollable_page(self._prompt_hist_page)
        self._prompt_hist.columnconfigure(0, weight=1)
        self._prompt_hist.rowconfigure(0, weight=1)
        cols = ("when", "profile", "preview", "stats")
        style = ttk.Style(self)
        style.configure("Hist.Treeview", rowheight=52)
        self.prompt_hist_tree = ttk.Treeview(
            self._prompt_hist,
            columns=cols,
            show="tree headings",
            height=16,
            style="Hist.Treeview",
        )
        self.prompt_hist_tree.heading("#0", text="")
        self.prompt_hist_tree.column("#0", width=56, minwidth=52, stretch=False, anchor="center")
        for col, heading, width, _fill in HISTORY_GRID_COLUMNS:
            self.prompt_hist_tree.heading(col, text=heading)
            self.prompt_hist_tree.column(col, width=width, stretch=False)
        self._keep_grid_filling(
            self._prompt_hist_page, self.prompt_hist_tree, HISTORY_GRID_COLUMNS
        )
        self._hist_photos: list = []
        yscroll = ttk.Scrollbar(
            self._prompt_hist, orient="vertical", command=self.prompt_hist_tree.yview
        )
        # The same rule the Catalog grid follows: the columns are wider than a
        # narrow window, so the right-hand ones need a horizontal bar to reach.
        hscroll = ttk.Scrollbar(
            self._prompt_hist, orient="horizontal", command=self.prompt_hist_tree.xview
        )
        self.prompt_hist_tree.configure(
            yscrollcommand=yscroll.set, xscrollcommand=hscroll.set
        )
        self.prompt_hist_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        self.prompt_hist_tree.bind("<Double-1>", lambda _e: self._reuse_prompt_history())
        bar = ttk.Frame(self._prompt_hist)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="Reuse", command=self._reuse_prompt_history).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(bar, text="Delete", command=self._delete_prompt_history).pack(
            side="left"
        )
        self.prompt_hist_empty_lbl = ttk.Label(
            self._prompt_hist, text=HISTORY_EMPTY_TEXT, style="Status.TLabel"
        )
        self.prompt_hist_empty_lbl.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._page_keeps_its_own_size(self._prompt_hist, self.prompt_hist_tree)
        self._refresh_prompt_history()

    def _refresh_prompt_history(self) -> None:
        tree = self.prompt_hist_tree
        for child in tree.get_children():
            tree.delete(child)
        self._hist_photos = []
        try:
            from PIL import Image, ImageTk
        except ImportError:
            Image = ImageTk = None  # type: ignore[misc, assignment]
        for i, row in enumerate(prompt_history.list_prompts()):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(row.get("ts") or 0)))
            req = row.get("request") if isinstance(row.get("request"), dict) else None
            stats = prompt_history.request_stats(req) if req else ""
            photo = None
            raw = str(row.get("image") or "").strip()
            if raw and Image is not None and Path(raw).is_file():
                try:
                    im = Image.open(raw)
                    # The image belongs to this tree's interpreter: without an
                    # explicit master Tkinter binds it to the process's default
                    # root, which is a different (or already destroyed) window as
                    # soon as a second window exists in the same process.
                    photo = ImageTk.PhotoImage(im, master=tree)
                    self._hist_photos.append(photo)
                except OSError:
                    photo = None
            tree.insert(
                "",
                "end",
                iid=str(i),
                image=photo or "",
                values=(
                    when,
                    str(row.get("profile") or ""),
                    prompt_history.preview(str(row.get("text") or "")),
                    stats,
                ),
            )
        # After the rows: the state is shown only while there is nothing to show,
        # like the Queue page's.
        empty = getattr(self, "prompt_hist_empty_lbl", None)
        if empty is not None:
            if tree.get_children():
                empty.grid_remove()
            else:
                empty.grid()

    def _selected_history_index(self) -> int | None:
        sel = self.prompt_hist_tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def _reuse_prompt_history(self) -> None:
        idx = self._selected_history_index()
        rows = prompt_history.list_prompts()
        if idx is None or idx < 0 or idx >= len(rows):
            messagebox.showinfo("Salad Studio", "Select a prompt to reuse.")
            return
        row = rows[idx]
        req = row.get("request") if isinstance(row.get("request"), dict) else None
        if req is not None:
            self._set_editor_payload(req, remember=False)
            self.status.set("Reused request JSON from history")
            self.log(
                "ok",
                f"reused prompt history #{idx}  {prompt_history.request_stats(req)}",
            )
            return
        text = str(row.get("text") or "")
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", text)
        self._sync_editor()
        self.nb.select(self._editor)
        self.status.set("Reused prompt from history")
        self.log("ok", f"reused prompt history #{idx} ({len(text)} chars)")

    def _delete_prompt_history(self) -> None:
        idx = self._selected_history_index()
        if idx is None:
            messagebox.showinfo("Salad Studio", "Select a prompt to delete.")
            return
        rows = prompt_history.list_prompts()
        if idx < 0 or idx >= len(rows):
            self.status.set("No prompt history entry to delete")
            self.log("warn", f"no prompt history entry #{idx}; nothing was deleted")
            return
        label = prompt_history.preview(str(rows[idx].get("text") or ""), 60) or f"#{idx}"
        # A delete here drops a stored prompt and its thumbnail, so it asks
        # first the way the Catalog's Delete and the profile Delete do.
        if not messagebox.askyesno(
            "Salad Studio",
            f"Delete prompt history entry #{idx}?\n\n{label}\n\n"
            "Its stored prompt and thumbnail are removed, and this cannot be undone.",
        ):
            self.status.set(f"Kept prompt history #{idx}")
            self.log("info", f"kept prompt history #{idx}")
            return
        prompt_history.remove_at(idx)
        self._refresh_prompt_history()
        self.status.set(f"Deleted prompt history #{idx}: {label}")
        self.log("info", f"deleted prompt history #{idx}  {label}")

    def _remember_request(self, payload: dict | None = None) -> None:
        body = payload
        if body is None:
            raw = self.editor_text.get("1.0", "end").strip()
            try:
                body = generator.parse_request_json(raw)
            except (ValueError, json.JSONDecodeError, TypeError):
                body = None
        if isinstance(body, dict) and prompt_history.add_request(
            body,
            profile=self.var_name.get().strip(),
            gateway=self.var_gateway.get().strip(),
        ):
            self._refresh_prompt_history()
            return
        text = self.prompt_text.get("1.0", "end").strip()
        if prompt_history.add_prompt(text):
            self._refresh_prompt_history()

    def _on_queue_log(self, level: str, message: str) -> None:
        """Every queue event reaches the log and redraws the queue page.

        Called from whichever thread is running the job, so the redraw is
        scheduled on the Tk thread the way ``log`` already does it.
        """
        self.log(level, message)
        if getattr(self, "queue_tree", None) is not None:
            try:
                self._later(0, self._refresh_queue_page)
            except Exception:  # noqa: BLE001 - no main loop (a test), or a dead window
                pass

    def _build_queue_tab(self) -> None:
        """The Salad request queue, rendered from the queue's own records.

        The page keeps no copy of job state: every row is read back out of
        ``self.gen_queue`` on a refresh, so what the page shows is what the
        queue will act on. It is wrapped like its siblings, so the request grid
        cannot set the window's size for the whole layout.
        """
        self._queue_page = ttk.Frame(self.nb)
        self._queue = self._scrollable_page(self._queue_page)
        self._queue.columnconfigure(0, weight=1)
        self._queue.rowconfigure(1, weight=1)
        bar = ttk.Frame(self._queue)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(bar, text="Refresh", command=self._refresh_queue_page).pack(side="left")
        self.queue_cancel_btn = ttk.Button(
            bar, text="Cancel selected", command=self._on_queue_cancel
        )
        self.queue_cancel_btn.pack(side="left", padx=(6, 0))
        self.queue_retry_btn = ttk.Button(
            bar, text="Retry selected", command=self._on_queue_retry
        )
        self.queue_retry_btn.pack(side="left", padx=(6, 0))
        self.queue_clear_btn = ttk.Button(
            bar, text="Clear finished", command=self._on_queue_clear
        )
        self.queue_clear_btn.pack(side="left", padx=(6, 0))
        self.var_queue_summary = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.var_queue_summary, style="Status.TLabel").pack(
            side="left", padx=(12, 0)
        )
        cols = ("id", "profile", "state", "attempts", "status", "reason", "request", "finished")
        self.queue_tree = ttk.Treeview(self._queue, columns=cols, show="headings", height=14)
        for col, heading, width, _fill in QUEUE_GRID_COLUMNS:
            self.queue_tree.heading(col, text=heading)
            self.queue_tree.column(col, width=width, stretch=False, anchor="w")
        self._keep_grid_filling(self._queue_page, self.queue_tree, QUEUE_GRID_COLUMNS)
        qscroll = ttk.Scrollbar(self._queue, orient="vertical", command=self.queue_tree.yview)
        # The row is wider than a narrow window, so the right-hand columns
        # (Reason and Request among them) need a bar of their own to reach them.
        qhscroll = ttk.Scrollbar(self._queue, orient="horizontal", command=self.queue_tree.xview)
        self.queue_tree.configure(yscrollcommand=qscroll.set, xscrollcommand=qhscroll.set)
        self.queue_tree.grid(row=1, column=0, sticky="nsew")
        qscroll.grid(row=1, column=1, sticky="ns")
        qhscroll.grid(row=2, column=0, sticky="ew")
        self.queue_empty_lbl = ttk.Label(
            self._queue, text=QUEUE_EMPTY_TEXT, style="Status.TLabel"
        )
        self.queue_empty_lbl.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.var_queue_note = tk.StringVar(value=QUEUE_CANCEL_NOTE)
        ttk.Label(
            self._queue, textvariable=self.var_queue_note, style="Status.TLabel"
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self._page_keeps_its_own_size(self._queue, self.queue_tree)
        self._refresh_queue_page()

    @staticmethod
    def _finished_label(stamp: Any) -> str:
        """The finish time a row shows, or "" while a request has not finished."""
        try:
            seconds = float(stamp or 0)
        except (TypeError, ValueError):
            return ""
        if seconds <= 0:
            return ""
        return time.strftime("%H:%M", time.localtime(seconds))

    def _queue_rows(self) -> list[tuple[str, tuple[str, ...]]]:
        """One (row key, cells) per request: the queue's records, then the finished ones it kept.

        Each row's state cell is the human word for the request's stage, so the
        page says what is happening rather than naming an internal state. A
        finished request the queue still holds a record for is shown once, with
        the time it finished; a request from an earlier session - the queue keeps
        those for the retention window - is shown from its record, because this
        session has no job for it.
        """
        kept = self.gen_queue.finished()
        finished_at = {
            int(record.get("id") or 0): record.get("finished_at") for record in kept
        }
        rows: list[tuple[str, tuple[str, ...]]] = []
        live: set[int] = set()
        for job in self.gen_queue.jobs():
            live.add(int(job.id))
            rows.append(
                (
                    str(job.id),
                    (
                        str(job.id),
                        job.line or "(default)",
                        salad_queue.status_word(job.state),
                        str(job.attempts),
                        str(job.status) if job.status else "",
                        job.reason or "",
                        queue_request_label(job.request),
                        self._finished_label(finished_at.get(int(job.id))),
                    ),
                )
            )
        for record in kept:
            rid = int(record.get("id") or 0)
            if rid in live:
                continue
            rows.append(
                (
                    f"kept-{rid}",
                    (
                        str(rid),
                        str(record.get("profile") or "(default)"),
                        salad_queue.status_word(str(record.get("state") or "")),
                        "",
                        str(record.get("status") or ""),
                        str(record.get("reason") or ""),
                        "(earlier session)",
                        self._finished_label(record.get("finished_at")),
                    ),
                )
            )
        return rows

    def _refresh_queue_page(self) -> None:
        tree = getattr(self, "queue_tree", None)
        if tree is None:
            return
        selected = tuple(tree.selection())
        tree.delete(*tree.get_children())
        rows = self._queue_rows()
        for key, values in rows:
            tree.insert("", "end", iid=key, values=values)
        for iid in selected:
            if tree.exists(iid):
                tree.selection_add(iid)
        if rows:
            self.queue_empty_lbl.grid_remove()
        else:
            self.queue_empty_lbl.grid()
        counts: dict[str, int] = {}
        for job in self.gen_queue.jobs():
            word = salad_queue.status_word(job.state)
            counts[word] = counts.get(word, 0) + 1
        pending = self.gen_queue.pending()
        summary = f"{len(rows)} request(s)"
        if pending:
            summary += f", {pending} not finished"
        busy_lines = self.gen_queue.lines()
        if len(busy_lines) > 1:
            summary += f", {len(busy_lines)} profiles in flight"
        if counts:
            summary += "   " + "   ".join(f"{state}: {n}" for state, n in sorted(counts.items()))
        self.var_queue_summary.set(summary)

    def _queue_status(self, text: str) -> None:
        self.var_queue_note.set(text)
        self.status.set(text)

    def _selected_queue_job(self):
        tree = getattr(self, "queue_tree", None)
        if tree is None:
            return None
        selection = tree.selection()
        if not selection:
            return None
        try:
            job_id = int(selection[0])
        except (TypeError, ValueError):
            return None
        return self.gen_queue.job_by_id(job_id)

    def _selected_kept_note(self, word: str) -> str:
        """The sentence for a selected row whose request the queue kept, or "".

        The Queue page keeps a finished record for the retention window, and a
        row restored from an earlier session is keyed ``kept-<id>``: the key is
        not the id, so the id is read off the row's own first cell, and the queue
        holds no job for it. A row whose job is still here is not this case.
        """
        tree = getattr(self, "queue_tree", None)
        if tree is None:
            return ""
        selection = tree.selection()
        if not selection:
            return ""
        values = tree.item(selection[0], "values")
        if not values:
            return ""
        rid = str(values[0]).strip()
        if not rid:
            return ""
        for record in self.gen_queue.finished():
            if str(record.get("id") or "") == rid:
                return (
                    f"Queue: request {rid} finished in an earlier session, so it "
                    f"cannot be {word}"
                )
        return ""

    def _on_queue_cancel(self) -> None:
        job = self._selected_queue_job()
        if job is None:
            note = self._selected_kept_note("cancelled")
            if note:
                self._queue_status(note)
                return
            self._queue_status("Queue: select a request first")
            return
        if self.gen_queue.cancel(job):
            self._queue_status(
                f"Queue: request {job.id} cancelled before it was submitted"
            )
        else:
            self._queue_status(
                f"Queue: request {job.id} is {job.state} and has already been sent, "
                "so it cannot be cancelled"
            )
        self._refresh_queue_page()

    def _on_queue_retry(self) -> None:
        job = self._selected_queue_job()
        if job is None:
            note = self._selected_kept_note("retried")
            if note:
                self._queue_status(note)
                return
            self._queue_status("Queue: select a request first")
            return
        if not job.retryable:
            self._queue_status(
                f"Queue: request {job.id} cannot be retried ({job.reason or job.state})"
            )
            self._refresh_queue_page()
            return
        self._queue_status(f"Queue: retrying request {job.id}…")

        def work() -> None:
            # Off the Tk thread: retry() runs the request and blocks until it is
            # terminal again, which is what would freeze the window here.
            try:
                self.gen_queue.retry(job)
            except Exception as e:
                self.log("error", f"Queue retry failed: {e}")
            self._later(0, self._refresh_queue_page)

        threading.Thread(target=work, daemon=True).start()

    def _on_queue_clear(self) -> None:
        removed = self.gen_queue.clear_finished()
        self._queue_status(f"Queue: cleared {removed} finished request(s)")
        self._refresh_queue_page()

    def _build_logs_tab(self) -> None:
        self._logs = ttk.Frame(self.nb)
        body = self._scrollable_page(self._logs)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        paned = ttk.Panedwindow(body, orient="vertical")
        paned.grid(row=0, column=0, sticky="nsew")
        salad_box = ttk.LabelFrame(paned, text="Salad container logs (active gateway)", padding=4)
        salad_box.columnconfigure(0, weight=1)
        salad_box.rowconfigure(0, weight=1)
        self.salad_log_text = tk.Text(salad_box, wrap="word", height=10, state="disabled")
        theme.style_text(self.salad_log_text)
        sscroll = ttk.Scrollbar(
            salad_box, orient="vertical", command=self.salad_log_text.yview
        )
        self.salad_log_text.configure(yscrollcommand=sscroll.set)
        self.salad_log_text.grid(row=0, column=0, sticky="nsew")
        sscroll.grid(row=0, column=1, sticky="ns")
        self.refresh_salad_logs_btn = ttk.Button(
            salad_box, text="Refresh Salad logs", command=self._refresh_salad_logs
        )
        self.refresh_salad_logs_btn.grid(row=1, column=0, sticky="w", pady=(4, 0))
        paned.add(salad_box, weight=1)
        studio_box = ttk.LabelFrame(paned, text="Studio / HTTP", padding=4)
        studio_box.columnconfigure(0, weight=1)
        studio_box.rowconfigure(0, weight=1)
        self.log_text = tk.Text(studio_box, wrap="word", height=10, state="disabled")
        theme.style_text(self.log_text)
        yscroll = ttk.Scrollbar(studio_box, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=yscroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        for level, color in studio_log.LEVEL_COLORS.items():
            self.log_text.tag_configure(f"log_{level}", foreground=color)
        bar = ttk.Frame(studio_box)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Button(bar, text="Clear Studio logs", command=self._clear_logs).pack(
            side="left"
        )
        paned.add(studio_box, weight=1)

    def _set_salad_logs(self, text: str) -> None:
        """Show the container's own stdout, with the secrets masked.

        The same value reaches both panes, so it is redacted the same way
        ``log`` redacts: a container that echoes an ``HF_TOKEN`` must not put it
        on screen in clear here while the Studio pane masks it.
        """
        widget = self.salad_log_text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", studio_log.redact(text, self._log_secrets()))
        widget.configure(state="disabled")

    def _set_check_salad_enabled(self, enabled: bool) -> None:
        """The top-bar check goes down while a probe runs, like its siblings."""
        btn = getattr(self, "check_salad_btn", None)
        if btn is None:
            return
        try:
            btn.configure(state="normal" if enabled else "disabled")
        except tk.TclError:
            pass

    def _set_salad_logs_enabled(self, enabled: bool) -> None:
        """Take the Refresh Salad logs button down while a status check runs.

        The probe that fetches the pane is one at a time, so a live-looking
        button that cannot refresh anything is the surface lying (the same rule
        the Tokens page's Check keys button follows).
        """
        btn = getattr(self, "refresh_salad_logs_btn", None)
        if btn is None:
            return
        try:
            btn.configure(state="normal" if enabled else "disabled")
        except tk.TclError:
            pass

    def _refresh_salad_logs(self) -> None:
        """Re-read the container's own log pane, or say why it cannot right now."""
        if self._salad_check_busy:
            self.status.set("Refresh Salad logs: a status check is already running")
            return
        self._check_salad_status(silent=True)

    def _token_stamp(self) -> tuple[int, int] | None:
        """A cheap fingerprint of the token store: its mtime and size.

        The redaction list must follow any write to the store, not only the ones
        this window makes: the file can be edited by hand, seeded from
        ``~/.config``, or written by another tool. A stat per log line is far
        cheaper than re-reading the tokens, and it changes exactly when the
        tokens do.
        """
        try:
            st = tokens.LOCAL_PATH.stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _log_secrets(self) -> list[str]:
        """Values to redact from log lines, cached until the token store changes.

        ``tokens.read_token`` re-seeds from ``~/.config`` and can write on every
        call, so this must not run once per log line. The cache is keyed on the
        store's fingerprint rather than cleared by one save path, so a token that
        arrives any other way is masked too.
        """
        stamp = self._token_stamp()
        if self._log_secrets_cache is None or stamp != self._log_secrets_stamp:
            self._log_secrets_cache = self._read_log_secrets()
            self._log_secrets_stamp = self._token_stamp()
        return self._log_secrets_cache

    def _read_log_secrets(self) -> list[str]:
        out: list[str] = []
        for kind, _label, _rel in tokens.TOKEN_SPECS:
            val = tokens.read_token(kind)
            if val:
                out.append(val)
        try:
            out.append(self._salad_api_key())
        except Exception:
            pass
        return out

    def log(self, level: str, message: str) -> None:
        cleaned = studio_log.redact(message, self._log_secrets())
        line = studio_log.format_line(level, cleaned)

        def append() -> None:
            widget = self.log_text
            widget.configure(state="normal")
            widget.insert("end", line + "\n", (f"log_{level}",))
            widget.see("end")
            widget.configure(state="disabled")
            if self._busy:
                self._gen_last_note = cleaned.strip()

        try:
            if threading.current_thread() is threading.main_thread():
                append()
            else:
                self._later(0, append)
        except Exception:
            append()

    def _clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.log("info", "Logs cleared")

    def _selected_lora_ids(self) -> list[str]:
        return list(self._pending_selected)

    def _set_selected_lora_ids(self, ids: list[str]) -> None:
        self._pending_selected = list(ids)
        want = set(ids)
        self._syncing_loras = True
        try:
            for lid, var in self._lora_vars.items():
                var.set(lid in want)
        finally:
            self._syncing_loras = False

    def _refresh_lora_lists(self) -> None:
        selected = set(self._pending_selected)
        graph = lora_store.graph_id(self.var_graph.get())
        rows = lora_store.list_loras()
        self._syncing_loras = True
        try:
            for child in self._lora_inner.winfo_children():
                child.destroy()
            self._lora_vars = {}
            self._lora_checks = {}
            col = 0
            row_i = 0
            for item in rows:
                lid = str(item.get("id") or "")
                if not lid:
                    continue
                ok = lora_store.compatible_with_graph(item, graph)
                var = tk.BooleanVar(value=ok and lid in selected)
                self._lora_vars[lid] = var
                cb = ttk.Checkbutton(
                    self._lora_inner,
                    text=lora_store.config_label(item),
                    variable=var,
                    command=self._schedule_lora_sync,
                    state=("normal" if ok else "disabled"),
                )
                cb.grid(row=row_i, column=col, sticky="nw", padx=(0, 10), pady=1)
                self._lora_checks[lid] = cb
                var.trace_add("write", lambda *_a: self._schedule_lora_sync())
                cb.bind("<ButtonRelease-1>", lambda _e: self._later_idle(self._on_lora_toggle))
                col += 1
                if col >= LORA_CHECK_COLUMNS:
                    col = 0
                    row_i += 1
        finally:
            self._syncing_loras = False
        self._refresh_lora_tree(rows)

    def _sort_lora_tree(self, column: str) -> None:
        """Order the grid by a heading's column; the same heading again reverses it."""
        current, reverse = self._lora_sort
        self._lora_sort = (column, not reverse if current == column else False)
        self._refresh_lora_tree()
        self.log(
            "debug",
            f"LoRA grid sorted by {column} "
            f"({'descending' if self._lora_sort[1] else 'ascending'})",
        )

    def _refresh_lora_tree(self, rows: list[dict] | None = None) -> None:
        """Fill the grid: the find box narrows the rows, the last heading click orders them.

        ``rows`` is the library's own list when a caller already has it; without
        one the store is read, which is what the find box and a heading click do.
        """
        items = lora_store.list_loras() if rows is None else rows
        shown = lora_rows_sorted(
            lora_rows_matching(
                [lora_grid_row(item) for item in items], self.var_lora_find.get()
            ),
            *self._lora_sort,
        )
        tree = self.lora_tree
        for child in tree.get_children():
            tree.delete(child)
        for row in shown:
            tree.insert(
                "",
                "end",
                iid=row["id"],
                values=tuple(row["cells"][column] for column in LORA_COLUMNS),
                tags=("verified" if row["verified"] else "unverified",),
            )

    def _fill_lora_form(self, item: dict) -> None:
        """Copy a library row into the add/edit entries (LoRAs-tab selection)."""
        src = item.get("source") or {}
        self.var_lora_name.set(str(item.get("name") or ""))
        fname = str(src.get("filename") or "") or lora_store.comfy_lora_name(item)
        self.var_lora_file.set(fname)
        self.var_lora_family.set(lora_store.family_label(item))
        sm, sc = lora_store.strengths_for(item)
        self.var_lora_sm.set(str(sm))
        self.var_lora_sc.set(str(sc))
        self.var_lora_ref.set(str(src.get("page") or src.get("download") or item.get("id") or ""))

    def _on_graph_change(self, *_a) -> None:
        if self._applying_profile:
            return
        gid = lora_store.graph_id(self.var_graph.get())
        self.log("info", f"graph -> {gid} ({lora_store.graph_label(gid)})")
        self._refresh_lora_lists()
        self._sync_editor()

    def _schedule_lora_sync(self, *_a) -> None:
        if self._syncing_loras or self._applying_profile:
            return
        self._on_lora_toggle()
        self._later_idle(self._on_lora_toggle)

    def _on_lora_toggle(self) -> None:
        if self._syncing_loras or self._applying_profile:
            return
        graph = lora_store.graph_id(self.var_graph.get())
        by_id = {str(it.get("id") or ""): it for it in lora_store.list_loras()}
        shown: list[str] = []
        for lid in self._lora_vars:
            item = by_id.get(lid)
            if item is not None and lora_store.compatible_with_graph(item, graph):
                shown.append(lid)
        shown_set = set(shown)
        kept = [lid for lid in self._pending_selected if lid not in shown_set]
        for lid in shown:
            if self._lora_vars[lid].get() and lid not in kept:
                kept.append(lid)
        self._pending_selected = kept
        self.log("info", f"LoRA selection {kept}")
        self._sync_editor()

    def _on_add_lora(self) -> None:
        ref = self.var_lora_ref.get().strip()
        if not ref:
            messagebox.showinfo("Salad Studio", "Paste a Civitai/HF URL, civitai:id@version, or a local path.")
            return
        try:
            item = lora_store.add_lora(
                ref,
                name=self.var_lora_name.get().strip() or None,
                filename=self.var_lora_file.get().strip() or None,
                strength_model=self._parse_strength(self.var_lora_sm.get(), 1.0),
                strength_clip=self._parse_strength(self.var_lora_sc.get(), 1.0),
                base=self.var_lora_family.get(),
            )
        except (Exception, SystemExit) as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        lid = str(item.get("id") or "")
        if lid and lid not in self._pending_selected:
            self._pending_selected.append(lid)
        self._refresh_lora_lists()
        self.var_lora_ref.set("")
        self.status.set(f"Added LoRA {lid}")
        self.log("ok", f"added LoRA {lid}")
        self._sync_editor()

    def _on_verify_lora(self) -> None:
        sel = self.lora_tree.selection()
        if not sel:
            messagebox.showinfo("Salad Studio", "Select a LoRA in the list to verify.")
            return
        ok_n = 0
        fail: list[str] = []
        for lid in sel:
            try:
                item = lora_store.verify_lora(lid)
            except Exception as e:
                fail.append(f"{lid}: {e}")
                self.log("error", f"verify LoRA {lid}: {e}")
                continue
            if item.get("verified"):
                ok_n += 1
                self.log("ok", f"verified LoRA {lid}")
            else:
                fail.append(lid)
                self.log("warn", f"LoRA {lid} did not verify")
        self._refresh_lora_lists()
        self._sync_editor()
        if fail:
            msg = f"Verified {ok_n}; failed: " + ", ".join(fail)
            self.status.set(msg)
            messagebox.showerror("Salad Studio", msg)
            return
        self.status.set(f"Verified {ok_n} LoRA(s)")

    def _on_verify_unverified(self) -> None:
        try:
            ok_n, fail_n, failed = lora_store.verify_unverified_loras()
        except Exception as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._refresh_lora_lists()
        self._sync_editor()
        if fail_n:
            msg = f"Verified {ok_n}; {fail_n} still unverified: " + ", ".join(failed[:8])
            self.status.set(msg)
            self.log("warn", msg)
            messagebox.showerror("Salad Studio", msg)
            return
        msg = f"Verified {ok_n} LoRA(s)" if ok_n else "Nothing unverified"
        self.status.set(msg)
        self.log("ok", msg)

    def _on_remove_lora(self) -> None:
        sel = self.lora_tree.selection()
        if not sel:
            messagebox.showinfo("Salad Studio", "Select a user extra in the list.")
            return
        # The neighbouring Verify acts on every selected row, so this one does
        # too: a selection of two extras is two removals, and the report says
        # how many, because a row that stays behind must not read as removed.
        removed: list[str] = []
        refused: list[str] = []
        for lid in sel:
            if lora_store.remove_lora(lid):
                removed.append(lid)
                self.log("ok", f"removed extra LoRA {lid}")
            else:
                refused.append(lid)
        if not removed:
            note = "Known catalog LoRAs stay in the list; only extras added here can be removed."
            self.status.set(f"Refused: {note}")
            messagebox.showinfo("Salad Studio", note)
            return
        self._refresh_lora_lists()
        note = f"Removed {len(removed)} extra LoRA(s): " + ", ".join(removed)
        if refused:
            note += f" ({len(refused)} known catalog LoRA(s) kept)"
        self.status.set(note)
        self._sync_editor()

    def _parse_strength(self, raw: str, default: float) -> float:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def _on_lora_tree_select(self, _e=None) -> None:
        sel = self.lora_tree.selection()
        if not sel:
            return
        item = lora_store.find_lora(sel[0])
        if item is None:
            return
        self._fill_lora_form(item)

    def _on_edit_lora(self) -> None:
        sel = self.lora_tree.selection()
        if not sel:
            messagebox.showinfo("Salad Studio", "Select a LoRA in the list to edit.")
            return
        lid = sel[0]
        try:
            lora_store.edit_lora(
                lid,
                name=self.var_lora_name.get().strip() or None,
                filename=self.var_lora_file.get().strip() or None,
                strength_model=self._parse_strength(self.var_lora_sm.get(), 1.0),
                strength_clip=self._parse_strength(self.var_lora_sc.get(), 1.0),
                base=self.var_lora_family.get(),
            )
        except Exception as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._refresh_lora_lists()
        if lid in self.lora_tree.get_children():
            self.lora_tree.selection_set(lid)
        self.status.set(f"Saved LoRA {lid}")
        self.log("ok", f"saved LoRA edits {lid}")
        self._sync_editor()

    def _on_close(self) -> None:
        """Closing the window: report a callback Tk would not take, then save.

        ``_dropped_afters`` is the record of a worker's handoff that never ran, so
        this is where it is read: a state reset that never happened is worth one
        line in the log the user is about to lose.
        """
        if self._dropped_afters:
            self.log(
                "warn",
                f"{len(self._dropped_afters)} scheduled callback(s) were dropped; "
                f"last: {self._dropped_afters[-1]}",
            )
        try:
            self._save_ui_state()
        except Exception as e:
            self.log("warn", f"Could not save window state: {e}")
        self.destroy()

    def _capture_ui_state(self) -> dict:
        tab = ""
        try:
            tab = str(self.nb.tab(self.nb.select(), "text"))
        except tk.TclError:
            pass
        editor = self.editor_text.get("1.0", "end-1c")
        try:
            parsed = json.loads(editor)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            editor = json.dumps(prompt_history.redact_request(parsed), indent=2)
        return {
            "tab": tab,
            "profile": self.var_name.get(),
            "gateway": self.var_gateway.get(),
            "graph": self.var_graph.get(),
            "width": self.var_width.get(),
            "height": self.var_height.get(),
            "steps": self.var_steps.get(),
            "cfg": self.var_cfg.get(),
            "seed": self.var_seed.get(),
            "scheduler": self.var_scheduler.get(),
            "unet": self.var_unet.get(),
            "selected_loras": self._selected_lora_ids(),
            "prompt": self.prompt_text.get("1.0", "end-1c"),
            "negative": self.negative_text.get("1.0", "end-1c"),
            "editor": editor,
            "helper_issue": self.helper_issue.get("1.0", "end-1c"),
            "helper_local_url": self.var_helper_local_url.get(),
            "helper_image": bool(self.var_helper_image.get()),
            "lora_ref": self.var_lora_ref.get(),
            "lora_name": self.var_lora_name.get(),
            "lora_file": self.var_lora_file.get(),
            "lora_family": self.var_lora_family.get(),
            "lora_sm": self.var_lora_sm.get(),
            "lora_sc": self.var_lora_sc.get(),
            "import_url": self.var_imp_image_url.get(),
            "import_cfg": self.var_imp_cfg.get(),
            "import_seed": self.var_imp_seed.get(),
            "import_steps": self.var_imp_steps.get(),
            "import_width": self.var_imp_width.get(),
            "import_height": self.var_imp_height.get(),
            "import_sched": self.var_imp_sched.get(),
            "import_unet": self.var_imp_unet.get(),
            "import_workflow": self._import_workflow_stash or "",
        }

    def _save_ui_state(self) -> None:
        ui_state.save_state(self._capture_ui_state())

    def _restore_ui_state(self) -> bool:
        isolated = profiles.PROFILES_PATH != (
            Path.home() / ".config" / "salad" / "studio-profiles.json"
        )
        default_ui = Path.home() / ".config" / "salad" / "studio-ui.json"
        if isolated and ui_state.STATE_PATH == default_ui:
            return False
        state = ui_state.load_state()
        if not state:
            return False
        self._applying_profile = True
        try:
            if state.get("profile"):
                self.var_name.set(str(state["profile"]))
            if "gateway" in state:
                self.var_gateway.set(str(state.get("gateway") or ""))
            if state.get("graph"):
                self.var_graph.set(str(state["graph"]))
            for attr, key in (
                ("var_width", "width"),
                ("var_height", "height"),
                ("var_steps", "steps"),
                ("var_cfg", "cfg"),
                ("var_seed", "seed"),
                ("var_scheduler", "scheduler"),
                ("var_unet", "unet"),
            ):
                if key in state:
                    getattr(self, attr).set(str(state.get(key) or ""))
            ids = state.get("selected_loras")
            if isinstance(ids, list):
                self._set_selected_lora_ids([str(x) for x in ids])
            self.prompt_text.delete("1.0", "end")
            self.prompt_text.insert("1.0", str(state.get("prompt") or ""))
            self.negative_text.delete("1.0", "end")
            self.negative_text.insert("1.0", str(state.get("negative") or ""))
            editor = state.get("editor")
            has_editor = isinstance(editor, str) and editor.strip()
            if has_editor:
                self.editor_text.delete("1.0", "end")
                self.editor_text.insert("1.0", editor)
            if "helper_issue" in state:
                self.helper_issue.delete("1.0", "end")
                self.helper_issue.insert("1.0", str(state.get("helper_issue") or ""))
            if state.get("helper_local_url"):
                self.var_helper_local_url.set(str(state["helper_local_url"]))
            if "helper_image" in state:
                self.var_helper_image.set(bool(state.get("helper_image")))
                self._refresh_helper_image_label()
            for attr, key in (
                ("var_lora_ref", "lora_ref"),
                ("var_lora_name", "lora_name"),
                ("var_lora_file", "lora_file"),
                ("var_lora_family", "lora_family"),
                ("var_lora_sm", "lora_sm"),
                ("var_lora_sc", "lora_sc"),
                ("var_imp_image_url", "import_url"),
                ("var_imp_cfg", "import_cfg"),
                ("var_imp_seed", "import_seed"),
                ("var_imp_steps", "import_steps"),
                ("var_imp_width", "import_width"),
                ("var_imp_height", "import_height"),
                ("var_imp_sched", "import_sched"),
                ("var_imp_unet", "import_unet"),
            ):
                if key in state:
                    getattr(self, attr).set(str(state.get(key) or ""))
            stash = str(state.get("import_workflow") or "")
            if stash:
                self._stash_import_workflow(stash)
            tab = str(state.get("tab") or "")
            if tab == "Prompt":
                tab = "Prompt Editor"
            if tab:
                self._goto_tab(tab)
        finally:
            self._applying_profile = False
        if isinstance(state.get("editor"), str) and str(state.get("editor")).strip():
            self._apply_json_chrome()
            return True
        return False

    def _patch_editor_from_prompt(self) -> bool:
        """Keep the loaded graph. Only the positive and negative CLIP text change.

        Returns True when the loaded graph took the text. False means the
        editor was rebuilt from Prompt Settings instead, which the Prompt Assist
        commit reports as a rebuild rather than as a patch.
        """
        if self._syncing_editor or self._applying_profile:
            return False
        raw = self.editor_text.get("1.0", "end").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._sync_editor()
            return False
        if not isinstance(payload, dict):
            self._sync_editor()
            return False
        text = self.prompt_text.get("1.0", "end").strip()
        neg = self.negative_text.get("1.0", "end").strip()
        if not request_json.apply_prompt_texts(payload, text, neg):
            self._sync_editor()
            return False
        dumped = json.dumps(payload, indent=2)
        self._syncing_editor = True
        try:
            self.editor_text.delete("1.0", "end")
            self.editor_text.insert("1.0", dumped)
        finally:
            self._syncing_editor = False
        self._apply_json_chrome()
        return True

    def _sync_editor(self) -> None:
        if self._syncing_editor or self._applying_profile:
            return
        self._syncing_editor = True
        try:
            try:
                width = int(self.var_width.get() or 1024)
                height = int(self.var_height.get() or 1024)
                steps = int(self.var_steps.get() or 20)
                cfg = float(self.var_cfg.get() or 5)
                seed = int(float(self.var_seed.get() or 1))
            except ValueError:
                return
            text = self.prompt_text.get("1.0", "end").strip()
            neg = self.negative_text.get("1.0", "end").strip()
            body = request_json.build_request(
                prompt_text=text,
                negative_text=neg,
                graph=lora_store.graph_id(self.var_graph.get()),
                width=width,
                height=height,
                steps=steps,
                seed=seed,
                cfg=cfg,
                unet=request_json.normalize_unet(self.var_unet.get()),
                selected_ids=self._selected_lora_ids(),
            )
            request_json.apply_scheduler(body, self._scheduler_id())
            dumped = json.dumps(body, indent=2)
            self.editor_text.configure(state="normal")
            self.editor_text.delete("1.0", "end")
            self.editor_text.insert("1.0", dumped)
            self._apply_json_chrome()
            self._refresh_graph()
            self.log(
                "debug",
                f"rebuilt editor from Config  graph={lora_store.graph_id(self.var_graph.get())}  "
                f"{width}x{height}  steps={steps}  loras={self._selected_lora_ids()}",
            )
        except Exception as e:
            self.status.set(f"JSON build failed: {e}")
            self.log("error", f"JSON build failed: {e}")
        finally:
            self._syncing_editor = False

    def _rebuild_from_json(self, *, remember: bool = True) -> None:
        raw = self.editor_text.get("1.0", "end").strip()
        try:
            payload = generator.parse_request_json(raw)
            cfg = request_json.config_from_payload(payload)
        except (ValueError, json.JSONDecodeError, TypeError) as e:
            self.log("error", f"Rebuild from JSON failed: {e}")
            messagebox.showerror("Salad Studio", f"Cannot parse Prompt Editor JSON: {e}")
            return
        ids = list(cfg.get("selected_ids") or [])
        for spec in cfg.get("unmatched_loras") or []:
            name = str(spec.get("lora_name") or "")
            if not name:
                continue
            try:
                item = lora_store.add_lora(
                    name,
                    strength_model=float(spec.get("strength_model") or 1),
                    strength_clip=float(spec.get("strength_clip") or 1),
                    base=lora_store.graph_label(str(cfg.get("graph") or "klein")),
                    # No live Civitai/HTTP check here: this runs on the Tk thread
                    # when a graph is loaded, and one 15-20 s round trip per
                    # unmatched LoRA freezes the window. Verify is a button.
                    verify=False,
                )
            except (Exception, SystemExit) as e:
                # A LoRA the store cannot register (a local filename that is not
                # on Civitai) stays in the JSON and in the Import issues list;
                # Generate omits it from the POST. Warning, not a dialog: a
                # pasted graph can carry several of them.
                self.log("warn", f"Could not add LoRA {name}: {e}")
                continue
            lid = str(item.get("id") or "")
            if lid and lid not in ids:
                ids.append(lid)
        self._applying_profile = True
        try:
            self._set_selected_lora_ids(ids)
            self.var_graph.set(lora_store.graph_label(str(cfg.get("graph") or "klein")))
            self.var_width.set(str(int(cfg.get("width") or 1024)))
            self.var_height.set(str(int(cfg.get("height") or 1024)))
            self.var_steps.set(str(int(cfg.get("steps") or 20)))
            if hasattr(self, "var_cfg") and cfg.get("cfg") not in (None, ""):
                v = cfg.get("cfg")
                self.var_cfg.set(str(int(v) if float(v) == int(float(v)) else v))
            seed = None
            for node in (payload.get("prompt") or {}).values():
                if isinstance(node, dict) and node.get("class_type") == "RandomNoise":
                    seed = (node.get("inputs") or {}).get("noise_seed")
                    break
            if hasattr(self, "var_seed") and seed is not None:
                self.var_seed.set(str(seed))
            if hasattr(self, "var_scheduler"):
                self.var_scheduler.set(
                    self._scheduler_label(str(cfg.get("scheduler") or "flux2"))
                )
            if hasattr(self, "var_unet"):
                self.var_unet.set(request_json.unet_label(str(cfg.get("unet") or "")))
            text = str(cfg.get("prompt_text") or "")
            self.prompt_text.delete("1.0", "end")
            if text:
                self.prompt_text.insert("1.0", text)
            self.negative_text.delete("1.0", "end")
            neg = str(cfg.get("negative_text") or "")
            if neg:
                self.negative_text.insert("1.0", neg)
            self._refresh_lora_lists()
        finally:
            self._applying_profile = False
        self._apply_json_chrome()
        if remember:
            self._remember_request(payload)
        self.status.set("Config updated from Prompt Editor JSON")
        self.log(
            "ok",
            f"rebuilt Config from JSON  graph={cfg.get('graph')}  "
            f"{cfg.get('width')}x{cfg.get('height')}  steps={cfg.get('steps')}  "
            f"loras={ids}",
        )

    def _screen_work_area(self) -> tuple[int, int]:
        """The area a window can be seen in: the desktop minus the taskbar.

        Tk reports the whole screen (``winfo_screenwidth``/``winfo_screenheight``),
        which is not the same thing: a window as tall as the screen puts its last
        rows - the status line every refusal is written to among them - behind
        the taskbar. Windows knows the work area, so it is asked directly there,
        and anywhere else the screen is the best answer available.
        """
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            ok = ctypes.windll.user32.SystemParametersInfoW(
                _SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
            )
            if ok and int(rect.right) > int(rect.left) and int(rect.bottom) > int(rect.top):
                return int(rect.right) - int(rect.left), int(rect.bottom) - int(rect.top)
        except Exception:  # noqa: BLE001 - no ctypes, no windll, no Windows
            pass
        try:
            return int(self.winfo_screenwidth()), int(self.winfo_screenheight())
        except tk.TclError:
            return 0, 0

    def _fitted_size(self, width: int, height: int) -> tuple[int, int]:
        """``width``x``height``, cut down to what the screen can show.

        The whole layout asks for more than a laptop screen has (the three
        pages that used to size it do not any more, but the chrome and the
        widest page still can), and a window that opens past the bottom edge
        hides the surfaces that report what the app is doing.
        """
        screen_w, screen_h = self._screen_work_area()
        fit_w = min(width, screen_w) if screen_w > 0 else width
        fit_h = min(height, screen_h) if screen_h > 0 else height
        return max(1, fit_w), max(1, fit_h)

    def _hold_opened_size(self, event=None) -> None:
        """Open at the layout size, then refuse a later startup growth.

        The diagram host finishes a second or two after the window appears and
        would otherwise stretch the toplevel. Position is left unset so
        Windows places the window. The size is not written to studio-ui.json.
        """
        if event is not None and getattr(event, "widget", None) not in (None, self):
            return
        if self._opened_size_held:
            self._reapply_opened_size()
            return
        try:
            self.update_idletasks()
            width = max(int(self.winfo_reqwidth()), 1)
            height = max(int(self.winfo_reqheight()), 1)
        except tk.TclError:
            return
        self._opened_width, self._opened_height = self._fitted_size(width, height)
        self._opened_size_held = True
        self.geometry(f"{self._opened_width}x{self._opened_height}")
        for delay in (100, 400, 900, 1600, 2200):
            try:
                self._later(delay, self._reapply_opened_size)
            except tk.TclError:
                return

    def _reapply_opened_size(self) -> None:
        if not self._opened_size_held:
            self._hold_opened_size()
            return
        try:
            width = int(self.winfo_width())
            height = int(self.winfo_height())
        except tk.TclError:
            return
        if width <= 1 or height <= 1:
            return
        if width > self._opened_width + 48 or height > self._opened_height + 48:
            self.geometry(f"{self._opened_width}x{self._opened_height}")

    def _place_editor_sash(self, _e=None) -> None:
        """Open the Prompt Editor with the JSON box at 25% and the diagram at 75%."""
        if self._editor_sash_set:
            return
        # Hold the size only once the window has been laid out at least once:
        # the graph pane embeds its web view from inside a builder, and that
        # embedding pumps the event loop (tkwry calls ``update_idletasks`` while
        # it attaches), so this handler can run while half the pages are still
        # being built. Latching the open size then would record a size from a
        # half-built window and open the app that small; __init__ latches it
        # after the last page exists.
        if self._opened_size_held:
            self._hold_opened_size()
        pane = self._editor_pane
        try:
            pane.update_idletasks()
            width = int(pane.winfo_width())
        except tk.TclError:
            return
        if width <= 1:
            return
        try:
            pane.sashpos(0, max(1, int(width * 0.25)))
        except tk.TclError:
            return
        self._editor_sash_set = True

    def _on_editor_edited(self, _e=None) -> None:
        if self._syncing_editor:
            return
        self.editor_text.configure(state="normal")
        self._graph_stale = True
        self._schedule_json_chrome(refresh_graph=False)

    def _editor_copy(self, _e=None):
        widget = self.editor_text
        widget.configure(state="normal")
        try:
            text = widget.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self.clipboard_clear()
        self.clipboard_append(text)
        return "break"

    def _editor_paste(self, _e=None):
        widget = self.editor_text
        widget.configure(state="normal")
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return "break"
        try:
            widget.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        widget.insert("insert", text)
        widget.focus_set()
        self._on_editor_edited()
        return "break"

    def _editor_cut(self, _e=None):
        self._editor_copy()
        widget = self.editor_text
        try:
            widget.delete("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self._on_editor_edited()
        return "break"

    def _editor_select_all(self, _e=None):
        widget = self.editor_text
        widget.configure(state="normal")
        widget.focus_set()
        widget.tag_remove("sel", "1.0", "end")
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "end-1c")
        widget.tag_raise("sel")
        widget.see("insert")
        return "break"

    def _lift_editor_over_webview(self) -> None:
        """Keep the JSON box above the graph's native window.

        WebView2 is raised after every diagram update and otherwise covers
        the editor, so the next click never reaches the text.
        """
        widget = getattr(self, "editor_text", None)
        if widget is None:
            return
        try:
            widget.configure(state="normal")
        except tk.TclError:
            return
        if sys.platform != "win32":
            try:
                widget.lift()
            except tk.TclError:
                pass
            return
        import ctypes
        from ctypes import wintypes

        flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
        user32 = ctypes.windll.user32
        for target in (widget, getattr(self, "_editor_box", None)):
            if target is None:
                continue
            try:
                hwnd = int(target.winfo_id())
            except (tk.TclError, ValueError):
                continue
            user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(0), 0, 0, 0, 0, flags)

    def _lift_editor_soon(self) -> None:
        self._lift_editor_over_webview()
        try:
            self._later_idle(self._lift_editor_over_webview)
            self._later(50, self._lift_editor_over_webview)
            self._later(200, self._lift_editor_over_webview)
        except tk.TclError:
            pass

    def _widget_in_graph(self, widget) -> bool:
        pane = getattr(self, "graph_pane", None)
        if pane is None or widget is None:
            return False
        host = getattr(pane, "_host", None)
        current = widget
        while current is not None:
            if current is pane or current is host:
                return True
            current = getattr(current, "master", None)
        return False

    def _release_graph_keyboard(self) -> None:
        """Hand the keyboard back to Tk after the graph's WebView2 held it."""
        pane = getattr(self, "graph_pane", None)
        web = getattr(pane, "_web", None) if pane is not None else None
        if web is not None:
            try:
                web.focus_parent()
            except Exception:
                pass
        self._lift_editor_soon()

    def _event_widget(self, event):
        """The widget an event came from, as an object rather than a name.

        ``bind_all`` delivers a click on the WebView2 child window (and a click
        on a widget Tk no longer holds an object for) with ``event.widget`` set
        to the widget's **path name**, and a name has no ``focus_set``: the
        handler raised ``AttributeError`` inside a Tk callback, which Tk logs
        and abandons. A name is resolved back to its widget here, and anything
        unresolvable is None, so a stray event is ignored.
        """
        raw = getattr(event, "widget", None)
        if raw is None or hasattr(raw, "focus_set"):
            return raw
        if isinstance(raw, str):
            try:
                return self.nametowidget(raw)
            except (tk.TclError, KeyError):
                return None
        return None

    def _on_click_outside_graph(self, event) -> None:
        widget = self._event_widget(event)
        if widget is None or self._widget_in_graph(widget):
            return
        self._release_graph_keyboard()
        try:
            widget.focus_set()
        except tk.TclError:
            pass

    def _on_editor_focus_in(self, _e=None) -> None:
        self._release_graph_keyboard()

    def _on_editor_focus_out(self, _e=None) -> None:
        if not getattr(self, "_graph_stale", False):
            return
        self._graph_stale = False
        self._refresh_graph(force=True)

    def _schedule_json_chrome(self, *, refresh_graph: bool = True) -> None:
        if self._json_after is not None:
            try:
                self.after_cancel(self._json_after)
            except Exception:
                pass
        self._json_after = self._later(
            60, lambda: self._apply_json_chrome(refresh_graph=refresh_graph)
        )

    def _apply_json_chrome(self, *, refresh_graph: bool = True) -> None:
        """Color-code the Prompt Editor and verify with parse_request_json."""
        self._json_after = None
        widget = getattr(self, "editor_text", None)
        if widget is None:
            return
        json_highlight.apply_to_text(widget)
        raw = widget.get("1.0", "end-1c").strip()
        ok, msg = json_highlight.verify_request_json(raw)
        self.json_status.set(msg)
        style_name = "JsonOk.TLabel" if ok else "JsonBad.TLabel"
        try:
            st = ttk.Style(self)
            st.configure(
                "JsonOk.TLabel",
                background=theme.PALETTE["bg"],
                foreground="#8FBF9A",
            )
            st.configure(
                "JsonBad.TLabel",
                background=theme.PALETTE["bg"],
                foreground=theme.PALETTE["accent"],
            )
            self.json_status_lbl.configure(style=style_name)
        except tk.TclError:
            pass
        if refresh_graph:
            self._refresh_graph()

    def _refresh_graph(self, *, force: bool = False) -> None:
        pane = getattr(self, "graph_pane", None)
        if pane is None:
            return
        # A graph refresh moves keyboard focus into the WebView. While the
        # JSON editor is focused, defer it so copy and paste keep working.
        if not force:
            try:
                if self.focus_get() is self.editor_text:
                    self._graph_stale = True
                    return
            except tk.TclError:
                pass
        raw = self.editor_text.get("1.0", "end-1c").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        prompt = payload.get("prompt") if isinstance(payload, dict) else None
        if isinstance(prompt, dict):
            pane.set_prompt(prompt)
            self._lift_editor_soon()

    def _on_graph_swap(self, prompt: dict) -> None:
        raw = self.editor_text.get("1.0", "end-1c").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"prompt": {}, "convert_output": dict(comfy_import.CONVERT_OUTPUT)}
        if not isinstance(payload, dict):
            payload = {}
        payload["prompt"] = prompt
        request_json.stamp_weight_refs(payload)
        dumped = json.dumps(payload, indent=2)
        self._syncing_editor = True
        try:
            self.editor_text.delete("1.0", "end")
            self.editor_text.insert("1.0", dumped)
        finally:
            self._syncing_editor = False
        self._apply_json_chrome()
        self.status.set("Swapped nodes in Prompt Editor JSON")
        self.log("ok", "swapped graph nodes")

    def _validate_editor(self, *, popup: bool = True) -> bool:
        """Run parse_request_json plus graph checks. Same gate Generate uses."""
        self._apply_json_chrome()
        widget = getattr(self, "editor_text", None)
        if widget is None:
            return False
        raw = widget.get("1.0", "end-1c").strip()
        ok, msg = json_highlight.verify_request_json(raw)
        extra: list[str] = []
        if ok:
            payload = generator.parse_request_json(raw)
            extra.append(studio_log.summarize_payload(payload))
            extra.append(f"POST {studio_log.prompt_url(self.var_gateway.get())}")
            unverified = lora_store.unverified_payload_refs(payload)
            if unverified:
                extra.append("unverified: " + ", ".join(unverified[:6]))
                ok = False
                msg = "JSON valid, but weight URL is not verified"
            if request_json.payload_has_civitai_download(payload):
                if tokens.read_token("civitai"):
                    extra.append("Civitai LoRA URLs: token will be attached on Generate")
                else:
                    extra.append("Civitai LoRA URLs: no token on Tokens tab (Generate would 401)")
                    ok = False
                    msg = "JSON valid, but Civitai token is missing"
        line = msg
        if extra:
            line = msg + ", " + "; ".join(extra)
        self.json_status.set(msg if ok else line)
        self.log("ok" if ok else "error", f"Validate: {line}")
        if popup and not ok:
            messagebox.showerror("Salad Studio", line)
        return ok

    def _scheduler_id(self) -> str:
        raw = (self.var_scheduler.get() if hasattr(self, "var_scheduler") else "") or ""
        return "simple" if "simple" in raw.lower() or "civitai" in raw.lower() else "flux2"

    def _scheduler_label(self, kind: str) -> str:
        return "Simple (Civitai)" if str(kind).lower() == "simple" else "Flux2 (Klein)"

    def _form_checkpoints(self, name: str) -> list[str]:
        """The checkpoint list to save with the form: the stored profile's own.

        The list is edited through the Config page's checkpoint controls, which
        persist as they go, so the store is the authority here. A name with no
        stored record starts from the metadata document's seed for it.
        """
        stored = profiles.load_all().get(name)
        if stored is not None:
            return list(stored.checkpoints)
        return profiles.seed_checkpoints(name)

    @staticmethod
    def _whole_number(field: str, raw: str, default: int) -> int:
        """One whole-number knob off the form, refusing with the knob's own name.

        ``int()`` names the literal it was handed and nothing else, so a typo in
        one of the five numeric fields reached the user as the interpreter's
        words with no way to tell which knob to fix. The field's name goes into
        the sentence instead, and an empty knob still takes the default.
        """
        text = str(raw or "").strip()
        if not text:
            return default
        try:
            return int(text)
        except ValueError:
            raise ValueError(f"{field} must be a whole number (got {text!r})") from None

    @staticmethod
    def _number(field: str, raw: str, default: float) -> float:
        """One decimal knob off the form, refusing with the knob's own name."""
        text = str(raw or "").strip()
        if not text:
            return default
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"{field} must be a number (got {text!r})") from None

    def _profile_from_form(self) -> SaladProfile:
        name = (self.var_name.get() or "klein").strip()
        selected = self._selected_lora_ids()
        return SaladProfile(
            name=name,
            gateway=self.var_gateway.get().strip(),
            mode=self._profile_mode(),
            key_path=profiles.DEFAULT_KEY_PATH,
            graph=lora_store.graph_id(self.var_graph.get()),
            width=self._whole_number("Width", self.var_width.get(), 1024),
            height=self._whole_number("Height", self.var_height.get(), 1024),
            steps=self._whole_number("Steps", self.var_steps.get(), 20),
            cfg=self._number("CFG", self.var_cfg.get(), 5),
            seed=int(self._number("Seed", self.var_seed.get(), 1)),
            scheduler=self._scheduler_id(),
            checkpoints=self._form_checkpoints(name),
            use_loras=bool(selected),
            selected_loras=selected,
            policy=self._policy_from_form(),
        )

    def _apply_profile(self, p: SaladProfile) -> None:
        self._applying_profile = True
        try:
            self._set_selected_lora_ids(list(p.selected_loras))
            self.var_name.set(p.name)
            self.var_gateway.set(p.gateway)
            mode = p.mode if p.mode in hostings.BY_KEY else hostings.DEFAULT
            self.var_profile_mode.set(mode)
            self._sync_hosting_controls(mode)
            self._repair_hosting_url(mode)
            self.var_width.set(str(p.width))
            self.var_height.set(str(p.height))
            self.var_steps.set(str(p.steps))
            if hasattr(self, "var_cfg"):
                self.var_cfg.set(str(getattr(p, "cfg", 5)))
            if hasattr(self, "var_seed"):
                self.var_seed.set(str(getattr(p, "seed", 1)))
            self.var_graph.set(lora_store.graph_label(p.graph))
            if hasattr(self, "var_scheduler"):
                self.var_scheduler.set(self._scheduler_label(getattr(p, "scheduler", "flux2")))
            if hasattr(self, "var_unet"):
                self.var_unet.set(request_json.unet_label(p.primary_checkpoint))
        finally:
            self._applying_profile = False
        if getattr(self, "_lora_inner", None) is not None:
            self._refresh_lora_lists()
        self._refresh_checkpoint_list(p)
        # This config's own policy, not a window-wide copy: selecting another
        # config swaps these fields with that config's policy, then re-reads that
        # config's group so what is shown is the group's current values.
        self._show_policy(self._policy_for_display(p))
        self._recheck_policy(p)
        self._sync_editor()
        self.log(
            "info",
            f"loaded profile {p.name}  gateway={p.gateway}  graph={p.graph}  "
            f"{p.width}x{p.height}  steps={p.steps}  "
            f"checkpoints={len(p.checkpoints)}",
        )

    def _load_profiles_into_ui(self) -> None:
        allp = profiles.ensure_builtin_profiles()
        if not allp:
            p = profiles.default_profile("klein")
            profiles.upsert(p)
            profiles.set_active(p.name)
            allp = {p.name: p}
        names = sorted(allp)
        self.profile_combo["values"] = names
        active = profiles.get_active()
        if active not in allp:
            active = names[0]
        self._apply_profile(allp[active])
        self._refresh_replica_strip()

    def _apply_restored_profile(self) -> None:
        """Make the profile box, the checkpoints and the policy agree after a restore.

        The saved window state names the config the window was last on, and the
        store's active config can be a different one. The fields must belong to
        the config the box names, so that config's own parts are re-applied here;
        the knobs (size, steps, seed, graph) are what the restore just put back.
        """
        name = (self.var_name.get() or "").strip()
        prof = profiles.load_all().get(name)
        if prof is None:
            return
        self._refresh_checkpoint_list(prof)
        self._show_policy(self._policy_for_display(prof))
        self._recheck_policy(prof)
        mode = prof.mode if prof.mode in hostings.BY_KEY else hostings.DEFAULT
        self.var_profile_mode.set(mode)
        self._sync_hosting_controls(mode)
        if prof.gateway:
            # The target belongs to the profile, not to the window. A restored URL
            # from before the target changed would pair a vast mode with a Salad
            # gateway, and the press would POST the graph to the wrong host.
            self.var_gateway.set(prof.gateway)

    def _on_select_profile(self) -> None:
        name = self.var_name.get().strip()
        allp = profiles.load_all()
        if name in allp:
            self._apply_profile(allp[name])
            profiles.set_active(name)

    def _save_profile(self) -> None:
        try:
            p = self._profile_from_form()
        except ValueError as e:
            messagebox.showerror("Salad Studio", f"Invalid size/steps: {e}")
            return
        profiles.upsert(p)
        profiles.set_active(p.name)
        self._refresh_profile_choices(p.name)
        self._refresh_checkpoint_list(p)
        self._refresh_replica_strip()
        self.status.set(f"Saved profile {p.name}")
        self.log(
            "ok",
            f"saved profile {p.name}  gateway={p.gateway}  graph={p.graph}  "
            f"checkpoints={len(p.checkpoints)}",
        )

    def _delete_profile(self) -> None:
        name = self.var_name.get().strip()
        if not name:
            return
        # A delete this destructive asks first, the way the Catalog's Delete and
        # Clean gallery do, and it reports what it actually did: the button is one
        # click away from losing a saved gateway, its checkpoints and its policy.
        if name not in profiles.load_all():
            self.status.set(f"No saved profile named {name}")
            self.log("warn", f"no saved profile named {name}; nothing was deleted")
            return
        if not messagebox.askyesno(
            "Salad Studio",
            f"Delete the saved profile {name!r}?\n\nIts gateway, checkpoints and "
            "policy are removed, and this cannot be undone.",
        ):
            self.status.set(f"Kept {name}")
            self.log("info", f"kept profile {name}")
            return
        profiles.delete(name)
        remaining = profiles.load_all()
        if remaining:
            nxt = next(iter(remaining))
            profiles.set_active(nxt)
            self._apply_profile(remaining[nxt])
        else:
            p = profiles.default_profile("klein")
            profiles.upsert(p)
            profiles.set_active(p.name)
            self._apply_profile(p)
        self._refresh_profile_choices()
        self._refresh_checkpoint_list()
        self._refresh_replica_strip()
        self.status.set(f"Deleted {name}")
        self.log("warn", f"deleted profile {name}")

    def _history_paths(self) -> list[Path]:
        studio = generator.list_history(OUT_DIR)
        probes = []
        if ART.is_dir():
            probes = sorted(
                ART.glob(PROBE_GLOB),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        seen: set[str] = set()
        out: list[Path] = []
        for p in studio + probes:
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out

    def _refresh_history(self) -> None:
        self.strip.set_paths(self._history_paths())

    def _on_clean_gallery(self) -> None:
        paths = self._history_paths()
        if not paths:
            messagebox.showinfo("Salad Studio", "Gallery is already empty.")
            return
        n = len(paths)
        if not messagebox.askyesno(
            "Salad Studio",
            f"Delete {n} image(s) from disk and clear the gallery? This cannot be undone.",
        ):
            return
        deleted = 0
        for path in paths:
            try:
                path.unlink()
                deleted += 1
            except OSError as e:
                self.log("warn", f"could not delete {path}: {e}")
        thumbs = prompt_history.clear_thumbs()
        self._refresh_history()
        self._refresh_prompt_history()
        self.status.set(f"Deleted {deleted} gallery image(s)")
        self.log("ok", f"cleaned gallery ({deleted} plates, {thumbs} thumbs)")

    def _open_path(self, path: Path) -> None:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as e:
            messagebox.showerror("Salad Studio", str(e))

    def _on_generate(self) -> None:
        """Generate: parse the editor JSON, then dispatch on the profile's hosting."""
        raw = self.editor_text.get("1.0", "end").strip()
        try:
            payload = generator.parse_request_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            # Every refusal writes the status line as well as the dialog: the
            # dialog is dismissed, the status line stays, and a stale "Generating…"
            # beside a refused press is the surface that lies.
            self.status.set("Refused: the Prompt Editor JSON is invalid")
            self.log("error", f"Generate aborted: invalid JSON: {e}")
            messagebox.showerror("Salad Studio", f"Prompt Editor JSON is invalid: {e}")
            return
        try:
            p = self._profile_from_form()
        except ValueError as e:
            self.status.set(f"Refused: {e}")
            self.log("error", f"Generate aborted: {e}")
            messagebox.showerror("Salad Studio", str(e))
            return
        adapter = hostings.BY_KEY.get(p.mode)
        if adapter is None:
            note = f"Refused: unknown hosting {p.mode!r}"
            self.status.set(note)
            self.log("error", note)
            messagebox.showerror("Salad Studio", note)
            return
        adapter(self).generate(payload, p)

    def _generate_salad(self, payload: dict, p: SaladProfile) -> None:
        """Salad half of Generate: route, key, badge gate, then queue the POST."""
        # No early return on a render already in flight: the press is queued and
        # starts when the container is free, which is what salad_queue is for.
        # Route by the unet the graph loads. One container group serves one unet
        # family: a second ~9 GB unet cannot fit in VRAM beside the 8.66 GB text
        # encoder, so Comfy streams weights from host memory and a seconds-long
        # render becomes minutes, which the gateway then cuts off with a 524.
        #
        # The table that decides this lives in the metadata document, not here:
        # profiles.plan_route compares the graph's family to the family the group
        # the form's GATEWAY points at serves. The comparison cannot use the
        # form's unet, because loading a JSON into the editor rewrites that field
        # from the graph, so it would compare the graph with itself and never
        # fire, which is how a SNOFS graph reached the klein group. (2026-09-22)
        loaded = profiles.payload_unets(payload)
        try:
            allp = profiles.load_all()
        except Exception:
            allp = {}
        route, refusal = profiles.plan_route(payload, p, allp)
        if refusal:
            self.status.set(f"Refused: {refusal}")
            self.log("error", f"Generate blocked: {refusal}")
            messagebox.showerror("Salad Studio", refusal)
            return
        if route is not None:
            note = f" (image {route.image})" if route.image else ""
            self.log(
                "info",
                f"Routed to profile {route.name!r} (gateway {route.profile.gateway}). "
                f"This graph loads {loaded[0]}, so it belongs on the {route.family} "
                f"group{note}.",
            )
            mixed = profiles.mixed_family_reason(route.profile)
            if mixed:
                self.log("warn", mixed)
            p = route.profile
        if (p.gateway or "").strip() in self._vast_endpoints():
            note = (
                "Refused: the Salad target holds a vast.ai instance URL, so the "
                "Salad key would be sent to that machine. Pick the Salad gateway "
                "on the Config page, then Generate again."
            )
            self.status.set(note)
            self.log("error", note)
            messagebox.showerror("Salad Studio", note)
            return
        try:
            key = self._salad_api_key()
        except (OSError, FileNotFoundError) as e:
            note = f"Refused: {e}"
            self.status.set(note)
            self.log("error", note)
            messagebox.showerror("Salad Studio", note)
            return
        if not p.gateway:
            note = "Refused: the gateway URL is empty"
            self.status.set(note)
            self.log("error", note)
            messagebox.showerror("Salad Studio", note)
            return
        word = (self.var_salad_status.get() or "").strip()
        if (word or "").split()[:1] != ["Ready"]:
            # The press is the gate for the two states that cannot render: a
            # replica that is gone, and a group the badge says is stopped, which
            # the queue would refuse anyway (this app never starts a container).
            # Both are refused here, with the reason, before anything is queued.
            # A replica that is still coming up is dispatched: the queue reads
            # the group's state again and the generator waits for its /ready.
            snap = (getattr(self, "_last_snaps", None) or {}).get(p.name) or {}
            reason = salad_status.generate_dispatch_reason(
                snap, word=word, profile=p.name, gateway=p.gateway
            )
            if reason:
                # Probe once, the way the queue's own refusal path does: the badge
                # is up to a tick old, so a user who has just started the
                # container would otherwise be refused again on the next press.
                self._check_salad_status(silent=True)
                self.log("warn", f"Generate refused: {reason}")
                self.status.set(f"Refused: {reason}")
                messagebox.showinfo("Salad Studio", reason)
                return
            self.log(
                "info",
                f"{p.name} reads {word or 'unknown'}; the request waits for the "
                "container's /ready before it POSTs",
            )
        # A press that repeats the request at the head of the queue adds nothing:
        # that one is about to be submitted (or is being submitted) already. The
        # digest is over the request, so an edited prompt is a different request,
        # and an identical request that is not the head is allowed.
        digest = salad_queue.request_checksum(payload)
        head = self.gen_queue.duplicate_of_head(line=p.name, checksum=digest)
        if head is not None:
            note = self._duplicate_note(head)
            self.log("warn", f"Generate: {note}")
            self.status.set(note)
            return
        self._gen_jobs += 1
        first = self._gen_jobs == 1
        self._busy = True
        if first:
            self._gen_t0 = time.monotonic()
        self._gen_last_note = "queued"
        self.var_gen_state.set("Starting…" if first else "Queued…")
        self.status.set("Generating…")
        self._schedule_gen_tick()
        self._remember_request(payload)
        self.log("info", f"Generate  gateway={p.gateway}  graph={p.graph}")
        if not first:
            self.log(
                "info",
                f"Queued behind {self._gen_jobs - 1} render(s); it starts when the "
                "container is free",
            )
        self.log("debug", studio_log.summarize_payload(payload))

        def work() -> None:
            err = ""
            refused = ""
            out: Path | None = None
            try:
                out = generator.generate_from_payload(
                    gateway=p.gateway,
                    key=key,
                    payload=payload,
                    out_dir=OUT_DIR,
                    on_log=self.log,
                    queue=self.gen_queue,
                    line=p.name,
                    checksum=digest,
                )
            except generator.ContainerDown as e:
                # The group went down between the badge read and the dispatch, so
                # the queue refused the request before any POST. Its own line in
                # the Logs already carries this sentence; the press reports it
                # without repeating it, and without calling it a failed render.
                refused = str(e)
            except Exception as e:
                err = str(e)
                self.log("error", err)

            def done() -> None:
                self._gen_jobs = max(0, self._gen_jobs - 1)
                elapsed = max(0, int(time.monotonic() - self._gen_t0))
                if refused:
                    self._check_salad_status(silent=True)
                    self.var_gen_state.set("Refused")
                    self.status.set(f"Refused: {refused}")
                    messagebox.showinfo("Salad Studio", refused)
                elif err:
                    # Probe rather than re-apply the cached word. A failed render
                    # usually means the replica went away mid-job, and the cache
                    # still says Ready from before it did, which is how the app
                    # kept reporting a container that had already restarted as up.
                    self._check_salad_status(silent=True)
                    self.var_gen_state.set(f"Failed after {elapsed}s")
                    self.status.set("Failed. See Logs")
                    messagebox.showerror("Salad Studio", err)
                else:
                    self.var_gen_state.set(f"Done in {elapsed}s")
                    self.status.set(f"Wrote {out}")
                    self.log("ok", f"Generate finished  {out}")
                    if out:
                        try:
                            prompt_history.attach_image(Path(out))
                        except Exception as e:
                            self.log("warn", f"history thumb skipped: {e}")
                        self._refresh_prompt_history()
                    self._refresh_history()
                if self._gen_jobs <= 0:
                    self._busy = False
                    self._cancel_gen_tick()
                else:
                    self.var_gen_state.set(f"{self._gen_jobs} render(s) still queued")
                self._refresh_queue_page()

            self._later(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _on_generate_vast(self, payload=None, p: SaladProfile | None = None) -> None:
        """Generate against the profile's vast.ai URL, or the selected instance.

        The vast half of the press: the same editor JSON, POSTed to the
        instance's own ComfyUI instead of a Salad gateway. Unet routing, the
        Salad key, the badge gate and the container checks are Salad's; this
        path skips them. The POST still goes through the queue on this
        profile's line, so the request appears on the Queue page and a busy
        instance is retried there. The key is not required here: it
        authenticates the vast.ai control API (the Config page's Vast.ai
        instances section and the Tokens tab's check), while the render goes
        straight to the instance.
        """
        if payload is None:
            raw = self.editor_text.get("1.0", "end").strip()
            try:
                payload = generator.parse_request_json(raw)
            except (ValueError, json.JSONDecodeError) as e:
                # Both refusals write the status line as well as the dialog, the way
                # the Salad path does: the dialog is dismissed, the status line
                # stays, and a stale "Wrote …" beside a refused press is the surface
                # that lies.
                self.status.set("Refused: the Prompt Editor JSON is invalid")
                self.log("error", f"Generate aborted: invalid JSON: {e}")
                messagebox.showerror("Salad Studio", f"Prompt Editor JSON is invalid: {e}")
                return
        if p is None:
            try:
                p = self._profile_from_form()
            except ValueError as e:
                self.status.set(f"Refused: {e}")
                self.log("error", f"Generate aborted: {e}")
                messagebox.showerror("Salad Studio", str(e))
                return
        endpoint = (p.gateway or "").strip()
        row = self._vast_active()
        if not endpoint:
            if row is None:
                self.status.set("Refused: no vast.ai instance is selected")
                self.log("error", "Generate aborted: no vast.ai instance is selected")
                messagebox.showinfo(
                    "Salad Studio",
                    "No vast.ai instance is selected. Add one under Vast.ai instances "
                    "on the Config page and select it, then Generate again.",
                )
                return
            endpoint = str(row["endpoint"])
            self.log(
                "info",
                f"profile {p.name} has no instance URL; using the selected "
                f"{vast.row_label(row)}",
            )
        if self._is_salad_gateway(endpoint):
            note = (
                "Refused: the vast.ai target holds a Salad gateway URL, so the "
                "graph would go to the wrong host. Pick the instance on the "
                "Config page, then Generate again."
            )
            self.status.set(note)
            self.log("error", note)
            messagebox.showerror("Salad Studio", note)
            return
        digest = salad_queue.request_checksum(payload)
        head = self.gen_queue.duplicate_of_head(line=p.name, checksum=digest)
        if head is not None:
            note = self._duplicate_note(head)
            self.log("warn", f"Generate: {note}")
            self.status.set(note)
            return
        who = vast.row_label(row) if row is not None else endpoint
        replace_policy = (
            self._vast_criteria() if self._profile_mode() == "vast" else {}
        )
        replacing = bool(replace_policy.get("enabled"))
        pending_contract = (self._vast_doc.get("pending") or {}).get("contract")
        replace_key = ""
        replace_env = ""
        replace_image = ""
        replace_label = ""
        if replacing:
            if self._vast_create_busy:
                note = "Refused: a replacement check is already running"
                self.status.set(note)
                self.log("warn", note)
                return
            replace_key = tokens.read_token("vast")
            replace_image = str((row or {}).get("image") or "").strip()
            if not replace_image:
                try:
                    replace_image = profiles.policy_image_for(p)
                except Exception:  # noqa: BLE001 - a broken document is not a crash
                    replace_image = ""
            if not replace_key or not replace_image:
                note = (
                    "Refused: automatic replacement needs the Vast.ai key and an "
                    "image. Set both, then Generate again."
                )
                self.status.set(note)
                self.log("error", note)
                messagebox.showerror("Salad Studio", note)
                return
            replace_env = vast.replacement_env(
                hf_token=tokens.read_token("huggingface"),
                civitai_token=tokens.read_token("civitai"),
            )
            replace_label = str((row or {}).get("label") or "").strip() or (
                f"salad-studio-{p.name}"
            )
            self._vast_create_busy = True
            self.vast_replace_btn.configure(state="disabled")
            self.vast_rent_btn.configure(state="disabled")
        self._gen_jobs += 1
        first = self._gen_jobs == 1
        self._busy = True
        if first:
            self._gen_t0 = time.monotonic()
        self._gen_last_note = "queued"
        self.var_gen_state.set("Starting…" if first else "Queued…")
        self.status.set("Generating…")
        self._schedule_gen_tick()
        self._remember_request(payload)
        self.log("info", f"Generate  vast.ai {endpoint}  {who}")
        self.log("debug", studio_log.summarize_payload(payload))

        def work() -> None:
            nonlocal endpoint
            err = ""
            stop = ""
            out: Path | None = None
            if replacing:
                self._later(0, lambda: self.var_gen_state.set("Checking instance."))
                try:
                    result = vast.replace_destroyed(
                        key=replace_key,
                        endpoint=endpoint,
                        instance_id=(row or {}).get("id") or pending_contract,
                        image=replace_image,
                        settings=replace_policy,
                        label=replace_label,
                        env=replace_env,
                    )
                except Exception as e:  # noqa: BLE001 - end the press, not the app
                    result = {"action": "error", "message": f"{type(e).__name__}: {e}"}
                action = str(result.get("action") or "")
                self._later(0, lambda: self._apply_vast_rent(result, row))
                if action == "alive":
                    endpoint = str(
                        (result.get("row") or {}).get("endpoint") or endpoint
                    )
                elif action == "created":
                    stop = str(result.get("message") or "") + (
                        " Generate again when it is ready."
                    )
                else:
                    err = str(result.get("message") or "the instance check failed")
            if not err and not stop:
                try:
                    out = generator.generate_from_vast(
                        endpoint=endpoint,
                        payload=payload,
                        out_dir=OUT_DIR,
                        on_log=self.log,
                        queue=self.gen_queue,
                        line=p.name,
                        checksum=digest,
                    )
                except Exception as e:
                    err = str(e)
                    self.log("error", err)

            def done() -> None:
                self._gen_jobs = max(0, self._gen_jobs - 1)
                elapsed = max(0, int(time.monotonic() - self._gen_t0))
                if stop:
                    self.var_gen_state.set("Replacement created")
                    self.status.set(stop)
                    self.log("info", stop)
                elif err:
                    self.var_gen_state.set(f"Failed after {elapsed}s")
                    self.status.set("Failed. See Logs")
                    messagebox.showerror("Salad Studio", err)
                else:
                    self.var_gen_state.set(f"Done in {elapsed}s")
                    self.status.set(f"Wrote {out}")
                    self.log("ok", f"Generate finished  {out}")
                    if out:
                        try:
                            prompt_history.attach_image(Path(out))
                        except Exception as e:
                            self.log("warn", f"history thumb skipped: {e}")
                        self._refresh_prompt_history()
                    self._refresh_history()
                if self._gen_jobs <= 0:
                    self._busy = False
                    self._cancel_gen_tick()
                else:
                    self.var_gen_state.set(f"{self._gen_jobs} render(s) still queued")
                self._refresh_queue_page()

            self._later(0, done)

        threading.Thread(target=work, daemon=True).start()


def main() -> None:
    app = SaladStudio()
    app.mainloop()


if __name__ == "__main__":
    main()
