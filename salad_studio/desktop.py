"""Where the window opens, and what the screen under it can show.

Windows only. A Flet window takes its place from ``page.window.left`` and
``top`` in the same virtual-desktop pixels this module reads, so it can be put
on a chosen monitor before its first frame. Every function degrades to a safe
answer on a machine without the Win32 calls, which is also what the tests use.

DPI awareness is per process, and the coordinates here are only the same ones
Flet's client uses once the process is aware. ``app_main`` calls
``make_dpi_aware`` before Flet starts, so a 150% desktop does not report the
work area in one scale and place the window in another.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

# SystemParametersInfoW's "primary monitor minus the taskbar".
_SPI_GETWORKAREA = 0x0030
# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
_PER_MONITOR_AWARE_V2 = -4


@dataclass(frozen=True)
class Monitor:
    """One display in virtual-desktop pixels. ``primary`` is the one with the taskbar."""

    left: int
    top: int
    right: int
    bottom: int
    work: tuple[int, int, int, int]
    primary: bool

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def make_dpi_aware() -> bool:
    """Tell Windows this process places its own windows. False when already aware."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except (AttributeError, OSError):
        pass
    try:
        return bool(ctypes.windll.user32.SetProcessDPIAware())
    except (AttributeError, OSError):
        return False


def _monitor_info(handle: int) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], bool]:
    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not ctypes.windll.user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        raise OSError("GetMonitorInfoW failed")
    full = (info.rcMonitor.left, info.rcMonitor.top, info.rcMonitor.right, info.rcMonitor.bottom)
    work = (info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom)
    return full, work, bool(info.dwFlags & 1)


def monitors() -> list[Monitor]:
    """Every display, the primary one first, then left to right."""
    found: list[Monitor] = []
    proc = ctypes.WINFUNCTYPE(
        ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
    )

    def collect(handle, _hdc, _rect, _lparam) -> int:
        try:
            full, work, primary = _monitor_info(handle)
        except OSError:
            return 1
        if full[2] > full[0] and full[3] > full[1]:
            found.append(Monitor(*full, work=work, primary=primary))
        return 1

    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, proc(collect), 0)
    except (AttributeError, OSError):
        return []
    return sorted(found, key=lambda m: (not m.primary, m.left, m.top))


def primary_work_area() -> tuple[int, int, int, int]:
    """The primary display's work area as (left, top, right, bottom); zeros when unknown."""
    try:
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(_SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            out = (rect.left, rect.top, rect.right, rect.bottom)
            if out[2] > out[0] and out[3] > out[1]:
                return out
    except (AttributeError, OSError):
        pass
    return (0, 0, 0, 0)


def fitting_monitor(found: list[Monitor], want: tuple[int, int]) -> Monitor | None:
    """The first display in preference order whose work area holds ``want``, else None."""
    width, height = want
    for monitor in found:
        left, top, right, bottom = monitor.work
        if right - left >= width and bottom - top >= height:
            return monitor
    return None


def fitted_size(want: tuple[int, int], work: tuple[int, int, int, int]) -> tuple[int, int]:
    """``want`` cut down to the work area, never smaller than 1x1."""
    width, height = want
    left, top, right, bottom = work
    if right <= left or bottom <= top:
        return max(1, width), max(1, height)
    return max(1, min(width, right - left)), max(1, min(height, bottom - top))


def centred(want: tuple[int, int], work: tuple[int, int, int, int]) -> tuple[int, int]:
    """Top-left that centres a ``want``-sized window in ``work``."""
    width, height = fitted_size(want, work)
    left, top, right, bottom = work
    if right <= left or bottom <= top:
        return 0, 0
    return left + (right - left - width) // 2, top + (bottom - top - height) // 2


def preferred_monitor(want: tuple[int, int]) -> Monitor | None:
    """The display a new window belongs on: not the primary one when there is another.

    Reads "secondary" as every display that is not the taskbar's. The first
    such display, left to right, that can hold the window wins; when none can,
    the first one that can. Without an extra display, or without the Win32
    calls, the answer is None and the caller lets Windows place the window.
    """
    found = monitors()
    extra = [m for m in found if not m.primary]
    return fitting_monitor(extra, want) or fitting_monitor(found, want)


def placement(want: tuple[int, int], found: list[Monitor] | None = None) -> tuple[int, int, int, int]:
    """(left, top, width, height) for a new window, on the secondary display when there is one."""
    if found is None:
        found = monitors()
    target = fitting_monitor([m for m in found if not m.primary], want)
    if target is None:
        target = fitting_monitor(found, want)
    work = target.work if target is not None else primary_work_area()
    left, top = centred(want, work)
    width, height = fitted_size(want, work)
    return left, top, width, height
