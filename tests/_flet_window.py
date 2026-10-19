"""A real Flet ``Page`` with a stub session, and a hidden window on it, for a test.

No client is available to a test, so the page records what would have been sent:
``Page.update`` is patched on the instance to count repaints, a control's
``update()`` raises ``RuntimeError`` until the page that holds it has been
repainted, which is how flet answers a control the client has not seen.

The store redirects are the Tk layout suite's, moved here: every window built
in a test reads and writes temp files, never the user's own stores.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any, Callable
from unittest import mock

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "salad_studio"
for _p in (PKG, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import flet as ft  # noqa: E402

from salad_studio import flet_app  # noqa: E402

# A key in the environment reads as a saved one; a test never depends on the user's own.
TOKEN_ENV_VARS: tuple[str, ...] = ("SALAD_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN", "CIVITAI_TOKEN",
                                   "DEEPSEEK_API_KEY", "VAST_API_KEY")


class Session:
    """The fields a ``Page`` reads from its session."""

    def __init__(self) -> None:
        self.patched: list[Any] = []

    def patch_control(self, control: Any) -> None:
        self.patched.append(control)

    def error(self, message: str) -> None:
        pass


def new_page() -> Any:
    """A ``Page`` whose repaints are recorded rather than sent."""
    page = ft.Page(Session())
    page.updates = 0

    def update(*controls: Any) -> None:
        page.updates += 1

    page.update = update  # type: ignore[method-assign]
    page._mounted = set()

    def mounts(control: Any) -> bool:
        return id(control) in page._mounted

    def mount(control: Any) -> None:
        page._mounted.update(id(node) for node in _all(control))

    page._mounts = mounts
    page._mount = mount
    _STUB_PAGES.append(page)
    mount(page)
    return page


def _all(control: Any) -> list[Any]:
    """Every control a tree holds, through the fields that hold children."""
    from flet.controls.base_control import BaseControl

    out: list[Any] = []
    seen: set[int] = set()

    def visit(node: Any, depth: int = 0) -> None:
        if (node is None or depth > 60 or isinstance(node, (str, bytes, int, float, bool))
                or id(node) in seen):
            return
        seen.add(id(node))
        if isinstance(node, dict):
            for value in node.values():
                visit(value, depth + 1)
        elif isinstance(node, (list, tuple, set)):
            for value in node:
                visit(value, depth + 1)
        elif isinstance(node, BaseControl):
            # A page's own ``page`` field is itself (``Page.__init__``): its
            # update() would no-op against it, which the client never does.
            out.append(node)
            for attr in ("content", "controls", "actions", "rows", "columns", "cells",
                         "segments", "options", "shapes", "spans", "selected"):
                visit(getattr(node, attr, None), depth + 1)

    visit(control)
    return out


# The stub pages a test has made; a page held by one of these is a page too.
_STUB_PAGES: list = []


def _install_stub_update() -> None:
    from flet.controls.base_control import BaseControl

    if getattr(BaseControl.update, "_stub_aware", False):
        return

    real = BaseControl.__dict__["update"]

    def stub_page(control: Any) -> Any:
        """The stub page that would carry ``control``, or None."""
        try:
            page = control.page
        except RuntimeError:
            page = None
        if page is None:
            return None
        if callable(getattr(page, "_mounts", None)):
            return page
        # A page held by the shell reads its own ``page`` field as itself; the
        # window lists it, and the window's page is the stub.
        if callable(getattr(page.__dict__.get("window"), "_mounts", None)):
            return None
        for found in _STUB_PAGES:
            shell = found.window.shell
            if any(held is page for held in shell.pages.values()):
                return found
        return None

    def update(self: Any, *args: Any, **kwargs: Any) -> None:
        page = stub_page(self)
        if page is not None and not page._mounts(self):
            raise RuntimeError(f"{type(self).__name__} Control must be added to the page first")
        return real(self)

    update._stub_aware = True  # type: ignore[attr-defined]
    BaseControl.update = update


_install_stub_update()


_MODULE_STORES: list["TempStores"] = []


def setUpModule() -> None:
    """The module's tests share one set of temporary stores, the queue ledger too."""
    stores = TempStores()
    stores.__enter__()
    _MODULE_STORES.append(stores)


def tearDownModule() -> None:
    while _MODULE_STORES:
        _MODULE_STORES.pop().__exit__(None, None, None)


class TempStores:
    """Every store a window reads or writes, pointed at one temp directory."""

    PATHS = (
        ("profiles", "PROFILES_PATH", "studio-profiles.json"),
        ("lora_store", "EXTRAS_PATH", "studio-loras.json"),
        ("tokens", "LOCAL_PATH", "studio-tokens.json"),
        ("prompt_catalog", "CATALOG_PATH", "studio-prompt-catalog.json"),
        ("prompt_history", "HISTORY_PATH", "studio-prompt-history.json"),
        ("ui_state", "STATE_PATH", "studio-ui.json"),
        ("vast", "INSTANCES_PATH", "studio-vast.json"),
        ("image_deploy", "SETTINGS_PATH", "studio-images.json"),
    )

    def __init__(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.saved: list[tuple[Any, str, Path]] = []
        self.env = mock.patch.dict("os.environ", {name: "" for name in TOKEN_ENV_VARS})

    def __enter__(self) -> "TempStores":
        import salad_queue as top_queue
        import hostings

        from salad_studio import (image_deploy, lora_store, profiles, prompt_catalog, prompt_history,
                                  salad_queue, tokens, ui_state, vast)

        self.env.start()

        ledger = self.root / "studio-queue.json"
        for module in (top_queue, salad_queue):
            self.saved.append((module, "LEDGER_PATH", module.LEDGER_PATH))
            module.LEDGER_PATH = ledger
        for module in (tokens, ui_state):
            if hasattr(module, "CONFIG_HOME"):
                self.saved.append((module, "CONFIG_HOME", module.CONFIG_HOME))
                module.CONFIG_HOME = self.root / "defaults"
        if hasattr(prompt_history, "THUMBS_DIR"):
            self.saved.append((prompt_history, "THUMBS_DIR", prompt_history.THUMBS_DIR))
            prompt_history.THUMBS_DIR = self.root / "thumbs"
        modules = {"hostings": hostings, "profiles": profiles, "lora_store": lora_store,
                   "tokens": tokens, "prompt_catalog": prompt_catalog,
                   "prompt_history": prompt_history, "ui_state": ui_state, "vast": vast,
                   "image_deploy": image_deploy}
        for name, attr, filename in self.PATHS:
            module = modules[name]
            if hasattr(module, attr):
                self.saved.append((module, attr, getattr(module, attr)))
                setattr(module, attr, self.root / filename)
        return self

    def __exit__(self, *exc: Any) -> None:
        for module, attr, value in reversed(self.saved):
            setattr(module, attr, value)
        self.saved.clear()
        self.env.stop()
        self.dir.cleanup()


def mount_opened(win: Any) -> None:
    """Let a page opened after the build repaint, as it would once the client has it.

    The stub sends nothing, so the client holds only the first page and any
    other control's repaint raises. The shell already treats "the page lost the
    name" as "not on the client yet" and skips; this wraps the shell's ``open``
    the same way, for tests that open a page through the rail or ``open_page``.
    """
    page = win.page
    shell = win.shell
    real_open = shell.open

    def open_and_mount(name: str, **kwargs: Any) -> Any:
        found = real_open(name, refresh_now=False, **kwargs)
        if found is not None:
            page._mount(found)
        shell.refresh()
        return found

    shell.open = open_and_mount  # type: ignore[method-assign]


def hidden_window(page: Any | None = None) -> tuple[Any, Any]:
    """A window built hidden on ``page`` (a fresh one by default): (window, page)."""
    page = page if page is not None else new_page()
    with mock.patch.dict("os.environ", {"SALAD_STUDIO_HIDDEN": "1"}):
        win = flet_app.build_hidden(page)
    return win, page
    # A page class that stores a Text under ``note`` or ``say`` shadows the
    # note method a window writes a line through; the window then raises while
    # it reports. A line must be writable on every page a user can open.
    for name, found in win.shell.pages.items():
        assert callable(getattr(found, "note", None)), (
            f"the {name} page has no usable note(); a line to it would raise")
    return win, page


def contains(control: Any, needle: Any) -> bool:
    """True when ``needle`` is ``control`` or sits under it."""
    return needle in walk(control)


def texts(control: Any) -> list[str]:
    """Every string a control shows, in tree order."""
    out: list[str] = []
    for node in walk(control):
        if isinstance(node, BUTTONS):
            out.append(label_of(node))
            continue
        content = node.__dict__.get("content")
        if isinstance(content, str) and content:
            out.append(content)
        for attr in ("value", "label", "text"):
            found = getattr(node, attr, None)
            if isinstance(found, str) and found:
                out.append(found)
    return out


BUTTONS = (ft.Button, ft.FilledButton, ft.OutlinedButton, ft.TextButton, ft.IconButton)


def label_of(control: Any) -> str:
    """A button's visible label: its text, or the text it wraps."""
    text = control.__dict__.get("text")
    if not isinstance(text, str):
        text = getattr(control, "text", None)
    if not isinstance(text, str):
        content = getattr(control, "content", None)
        if isinstance(content, str):
            text = content
        else:
            value = getattr(content, "value", None) if content is not None else None
            text = value if isinstance(value, str) else ""
    return text


def buttons(control: Any) -> dict[str, Any]:
    """Every button under ``control`` by its label."""
    found: dict[str, Any] = {}
    for node in walk(control):
        if isinstance(node, BUTTONS):
            label = label_of(node)
            if label:
                found.setdefault(label, node)
    return found


def shown_texts(control: Any) -> list[str]:
    """The text of every ``ft.Text`` under ``control``, in tree order."""
    return [node.value for node in walk(control)
            if isinstance(node, ft.Text) and isinstance(node.value, str) and node.value]


def click(control: Any) -> None:
    """Press a button the way Flet does: its handler gets an event naming it."""
    control.on_click(mock.Mock(control=control))


def walk(control: Any) -> list[Any]:
    """Every control under ``control``, the control itself first.

    Only the fields that hold children are followed: a control's own dict can
    reach the page that holds it, and a mock's child attributes go on forever.
    """
    from flet.controls.base_control import BaseControl

    out: list[Any] = []
    seen: set[int] = set()

    def visit(node: Any, depth: int = 0) -> None:
        if (node is None or depth > 60 or isinstance(node, (str, bytes, int, float, bool))
                or id(node) in seen):
            return
        seen.add(id(node))
        if isinstance(node, dict):
            for value in node.values():
                visit(value, depth + 1)
        elif isinstance(node, (list, tuple, set)):
            for value in node:
                visit(value, depth + 1)
        elif isinstance(node, BaseControl):
            # A page's own ``page`` field is itself (``Page.__init__``): its
            # update() would no-op against it, which the client never does.
            out.append(node)
            for attr in ("content", "controls", "actions", "rows", "columns", "cells",
                         "segments", "options", "shapes", "spans", "selected"):
                visit(getattr(node, attr, None), depth + 1)

    visit(control)
    return out


def find_text(control: Any, value: str) -> Any:
    """The first ``ft.Text`` under ``control`` whose value is ``value``."""
    return next((node for node in walk(control)
                 if isinstance(node, ft.Text) and node.value == value), None)


def dialog_body(box: Any) -> str:
    return str(getattr(box.content, "value", ""))


def dialog_buttons(box: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for action in box.actions:
        label = getattr(action, "text", None) or getattr(action, "content", None)
        if isinstance(label, str):
            found[label] = action
    return found
