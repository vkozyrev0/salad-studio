"""No test may raise a real dialog.

A Tk message box blocks until someone clicks it. The suite builds the real
window, so one unmocked ``messagebox.showinfo`` in a test is a modal on the
desktop and a run that has to be killed by hand — which has happened, twice: once
from a Generate refusal and once from the Queue page's own controls.

``install()`` replaces the dialog entry points with recorders, so a call is
captured in :data:`CALLS` instead of shown. ``tests/__init__.py`` calls it, so
importing any test module installs it. A test that wants to assert on a dialog
keeps using ``mock.patch.object`` on the same attribute: the patch shadows the
recorder and the recorder comes back when the patch is undone.

The default answers are a contract: ``askyesno``, ``askokcancel``,
``askretrycancel`` and ``askyesnocancel`` answer **True**, and every other dialog
(``showinfo``, ``showwarning``, ``showerror``) answers ``"ok"``. A destructive
confirmation answers :data:`DESTRUCTIVE_ANSWER`, which is **False** until the
test sets it. A drive that presses Clean gallery, Delete, or Reallocate must
not unlink files or drop a profile just because nobody patched the dialog.
"""
from __future__ import annotations

CALLS: list[tuple[str, str, str]] = []
_INSTALLED = False

# What a recorded dialog answers when it is asked a question. Tests that care
# about the answer patch the function; this is only a default that cannot block.
_ANSWERS = {
    "askyesno": True,
    "askokcancel": True,
    "askretrycancel": True,
    "askyesnocancel": True,
}

# A destructive question has its own answer. It stays False unless the test
# opts in, so the default cannot delete real files.
DESTRUCTIVE_ANSWER = False

# Phrases the app's own confirmations use when the yes branch deletes or dumps.
_DESTRUCTIVE_MARKS = ("delete ", "cannot be undone", "from disk", "dumps ")


def _is_destructive(message) -> bool:
    text = str(message or "").lower()
    return any(mark in text for mark in _DESTRUCTIVE_MARKS)


def _recorder(kind: str):
    def call(title=None, message=None, **_kwargs):
        CALLS.append((kind, str(title), str(message)))
        if kind in _ANSWERS and _is_destructive(message):
            return DESTRUCTIVE_ANSWER
        return _ANSWERS.get(kind, "ok")

    call.__name__ = kind
    return call


def install() -> bool:
    """Make the dialogs record instead of showing. Idempotent.

    Returns True when the dialogs are guarded. A run without tkinter (no Tk
    available at all) has nothing to guard and returns False.
    """
    global _INSTALLED
    if _INSTALLED:
        return True
    try:
        from tkinter import messagebox
    except ImportError:
        return False
    for kind in (
        "showinfo",
        "showwarning",
        "showerror",
        "askyesno",
        "askokcancel",
        "askretrycancel",
        "askyesnocancel",
    ):
        if hasattr(messagebox, kind):
            setattr(messagebox, kind, _recorder(kind))
    _INSTALLED = True
    return True


def reset() -> None:
    """Forget the dialogs recorded so far."""
    CALLS.clear()
