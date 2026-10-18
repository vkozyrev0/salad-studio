#!/usr/bin/env python3
"""Always-visible bottom history strip for Salad Studio.

Three-pane layout: tall ◀ button | horizontally scrolling thumbnail
canvas | tall ▶ button. Click a thumb to open; missing files render as
a themed placeholder. No generate or network I/O.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence, Union

from PIL import Image, ImageTk

from salad_studio.theme import PALETTE, FONT_UI, rgb, style_history_strip

PathLike = Union[str, Path]
OpenCallback = Callable[[Path], None]

_PLACEHOLDER_RGB = rgb("border")
_LETTERBOX_RGB = rgb("well")
_GAP = 8
_PAD = 8
# The ring around the thumbnail the keyboard is on, and the mark drawn inside
# it so "current" does not rest on colour alone.
_RING = 3
_MARK_RGB = rgb("accent")
# What the strip says when there is nothing in it: two arrows over a blank band
# reads as a broken strip rather than an empty one.
EMPTY_TEXT = "No plates yet. A finished render appears here."


class HistoryStrip(tk.Frame):
    """Horizontal thumbnail history: [◀] [canvas] [▶]."""

    def __init__(
        self,
        master,
        *,
        on_open: Optional[OpenCallback] = None,
        thumb_size: Sequence[int] = (160, 160),
    ) -> None:
        super().__init__(master)
        self.on_open = on_open
        tw, th = int(thumb_size[0]), int(thumb_size[1])
        self.thumb_size: tuple[int, int] = (max(1, tw), max(1, th))
        self._paths: list[Path] = []
        self._thumbs: list[ImageTk.PhotoImage] = []
        self._rings: list[ImageTk.PhotoImage] = []
        self._item_ids: list[int] = []
        # The index the keyboard is on. A click moves it too, so the ring always
        # says which thumb Enter would open.
        self._selected: int | None = None
        self._empty_id: int | None = None

        self.left_btn = tk.Button(
            self,
            text="◀",
            command=self._scroll_left,
            repeatdelay=300,
            repeatinterval=60,
            takefocus=0,
        )
        self.canvas = tk.Canvas(
            self,
            height=self.thumb_size[1] + _PAD * 2,
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["accent"],
            borderwidth=0,
            takefocus=1,
        )
        self.canvas.configure(xscrollincrement=1)
        self.right_btn = tk.Button(
            self,
            text="▶",
            command=self._scroll_right,
            repeatdelay=300,
            repeatinterval=60,
            takefocus=0,
        )

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.left_btn.grid(row=0, column=0, sticky="ns")
        self.canvas.grid(row=0, column=1, sticky="nsew")
        self.right_btn.grid(row=0, column=2, sticky="ns")
        style_history_strip(self)

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_wheel(self.canvas)
        self.canvas.tag_bind("thumb", "<Enter>", self._on_thumb_enter)
        self.canvas.tag_bind("thumb", "<Leave>", self._on_thumb_leave)
        for key in ("Left", "Right", "Home", "End"):
            self.canvas.bind(f"<{key}>", lambda e, k=key: self._on_key(e, k))
        self.canvas.bind("<Return>", lambda _e: self._open_selected())
        self.canvas.bind("<space>", lambda _e: self._open_selected())

    def set_paths(self, paths: Iterable[PathLike]) -> None:
        """Replace the strip. Order is kept (oldest-left or newest-first)."""
        self._paths = [Path(p) for p in (paths or [])]
        self._rebuild()

    def _rebuild(self) -> None:
        self.canvas.delete("thumb")
        self._thumbs.clear()
        self._rings.clear()
        self._item_ids.clear()
        if self._selected is not None and self._selected >= len(self._paths):
            self._selected = None
        for index, path in enumerate(self._paths):
            photo = self._photo_for(path)
            # PhotoImage must stay referenced or Tk drops the pixels.
            self._thumbs.append(photo)
            iid = self.canvas.create_image(
                0,
                0,
                image=photo,
                anchor="nw",
                tags=("thumb",),
            )
            self._item_ids.append(iid)
            self.canvas.tag_bind(
                iid, "<Button-1>", lambda _e, i=index: self._click(i)
            )
        self._layout_thumbs()
        self._paint_selection()
        self.canvas.xview_moveto(0)

    def _photo_for(self, path: Path) -> ImageTk.PhotoImage:
        im = self._load_thumb(path)
        try:
            return ImageTk.PhotoImage(im, master=self)
        except Exception:
            fallback = Image.new("RGB", self.thumb_size, _PLACEHOLDER_RGB)
            return ImageTk.PhotoImage(fallback, master=self)

    def _load_thumb(self, path: Path) -> Image.Image:
        tw, th = self.thumb_size
        placeholder = Image.new("RGB", (tw, th), _PLACEHOLDER_RGB)
        try:
            if not path.is_file():
                return placeholder
            with Image.open(path) as src:
                work = src.convert("RGB")
            work.thumbnail((tw, th), Image.Resampling.LANCZOS)
            bg = Image.new("RGB", (tw, th), _LETTERBOX_RGB)
            bg.paste(work, ((tw - work.width) // 2, (th - work.height) // 2))
            return bg
        except Exception:
            return placeholder

    def _layout_thumbs(self) -> None:
        tw, th = self.thumb_size
        canvas_h = max(int(self.canvas.winfo_height()), th + _PAD * 2)
        y = max(_PAD, (canvas_h - th) // 2)
        x = _PAD
        for iid in self._item_ids:
            self.canvas.coords(iid, x, y)
            x += tw + _GAP
        content_w = x - _GAP + _PAD if self._item_ids else _PAD
        self.canvas.configure(scrollregion=(0, 0, content_w, canvas_h))
        self._place_empty_state(canvas_h)
        self._paint_selection()

    # -- selection -------------------------------------------------------
    def selected_index(self) -> int | None:
        """The thumb the keyboard is on, or None while the strip is untouched."""
        return self._selected

    def _select(self, index: int) -> None:
        if not self._paths:
            return
        self._selected = max(0, min(index, len(self._paths) - 1))
        self._paint_selection()
        self._reveal(self._selected)

    def _click(self, index: int) -> None:
        self._select(index)
        self.canvas.focus_set()
        self._emit_open(self._paths[index])

    def _open_selected(self) -> str:
        if self._selected is not None and 0 <= self._selected < len(self._paths):
            self._emit_open(self._paths[self._selected])
        return "break"

    def _on_key(self, _event: tk.Event, key: str) -> str:
        # The first key press only puts the ring on the first thumb; it does
        # not also step, or the strip would skip an image on the way in.
        if self._selected is None:
            self._select(0)
            return "break"
        start = self._selected
        if key == "Left":
            self._select(start - 1)
        elif key == "Right":
            self._select(start + 1)
        elif key == "Home":
            self._select(0)
        else:
            self._select(len(self._paths) - 1)
        return "break"

    def _paint_selection(self) -> None:
        """Ring the selected thumb in the accent, and draw a mark inside it."""
        self._rings.clear()
        self.canvas.delete("ring")
        if self._selected is None or not (0 <= self._selected < len(self._item_ids)):
            return
        tw, th = self.thumb_size
        x, y = self.canvas.coords(self._item_ids[self._selected])
        # The rectangle is drawn inside the image's edge, so the tiles keep
        # their gap and the strip does not reflow when the selection moves.
        area = max(6, int((tw - _RING * 2) * 0.18))
        mark = Image.new("RGB", (area, area), _MARK_RGB)
        self._rings.append(ImageTk.PhotoImage(mark, master=self))
        self.canvas.create_image(
            x + _RING, y + _RING, image=self._rings[-1], anchor="nw", tags=("ring",)
        )
        self.canvas.create_rectangle(
            x,
            y,
            x + tw - 1,
            y + th - 1,
            outline=PALETTE["accent_hi"],
            width=_RING,
            tags=("ring",),
        )

    def _reveal(self, index: int) -> None:
        """Scroll the strip the least amount that shows thumb ``index`` whole."""
        if not self._item_ids:
            return
        bbox = self.canvas.bbox("all")
        if bbox is None:
            return
        total = max(1, int(bbox[2]))
        tw = self.thumb_size[0]
        x = _PAD + index * (tw + _GAP)
        left = int(self.canvas.canvasx(0))
        width = int(self.canvas.winfo_width())
        if width <= 1:
            return
        if x < left:
            self.canvas.xview_moveto(max(0, x - _PAD) / total)
        elif x + tw > left + width:
            self.canvas.xview_moveto(max(0, x + tw + _PAD - width) / total)

    def _place_empty_state(self, canvas_h: int) -> None:
        """Draw, move or drop the empty-state line, so it follows the strip's height."""
        if self._empty_id is not None:
            self.canvas.delete(self._empty_id)
            self._empty_id = None
        if self._paths:
            return
        self._empty_id = self.canvas.create_text(
            _PAD * 2,
            max(1, canvas_h // 2),
            text=EMPTY_TEXT,
            anchor="w",
            fill=PALETTE["fg_muted"],
            font=FONT_UI,
            tags=("empty",),
        )

    def _on_canvas_configure(self, _event: tk.Event | None = None) -> None:
        self._layout_thumbs()

    def _scroll_left(self) -> None:
        self._scroll_pixels(-self._page_pixels())

    def _scroll_right(self) -> None:
        self._scroll_pixels(self._page_pixels())

    def _page_pixels(self) -> int:
        return self.thumb_size[0] + _GAP

    def _scroll_pixels(self, pixels: int) -> None:
        if pixels:
            self.canvas.xview_scroll(int(pixels), "units")

    def _bind_wheel(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel)
        widget.bind("<Shift-MouseWheel>", self._on_mousewheel)
        widget.bind("<Button-4>", self._on_linux_scroll)
        widget.bind("<Button-5>", self._on_linux_scroll)

    def _on_mousewheel(self, event: tk.Event) -> str:
        delta = int(getattr(event, "delta", 0) or 0)
        if delta:
            if abs(delta) < 40:
                self._scroll_pixels(-delta * 10)
            else:
                notches = -delta / 120.0
                self._scroll_pixels(int(notches * max(self._page_pixels() // 2, 40)))
        return "break"

    def _on_linux_scroll(self, event: tk.Event) -> str:
        step = max(self._page_pixels() // 2, 40)
        num = getattr(event, "num", 0)
        if num == 4:
            self._scroll_pixels(-step)
        elif num == 5:
            self._scroll_pixels(step)
        return "break"

    def _on_thumb_enter(self, _event: tk.Event) -> None:
        self.canvas.configure(cursor="hand2")

    def _on_thumb_leave(self, _event: tk.Event) -> None:
        self.canvas.configure(cursor="")

    def _emit_open(self, path: Path) -> None:
        if self.on_open is not None:
            self.on_open(path)
