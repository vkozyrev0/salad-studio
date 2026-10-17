"""Keep a window-building test off the user's own queue ledger.

``SaladStudio`` builds a ``SaladQueue``, and the queue persists its container
ledger to ``salad_queue.LEDGER_PATH``. A module that constructs a window without
redirecting that path reads and writes the user's own
``~/.config/salad/studio-queue.json`` in a discover run. Two copies of
``salad_queue`` live in a test process - the app imports it top-level, and some
tests import it as ``salad_studio.salad_queue`` - so both are redirected.

A module wires this as its own module-level pair::

    from tests import _stores

    def setUpModule() -> None:
        _stores.keep_queue_ledger_off_the_user_store()

    def tearDownModule() -> None:
        _stores.restore_queue_ledger()

``tests/test_app_layout.py`` keeps its own redirect (it names every store it
moves), and puts the shipped paths back when its module ends, so a module that
builds a window and does *not* redirect reads whatever the last module left.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

# What to hand back to restore_queue_ledger: (module, the path it shipped with).
_SAVED: list[tuple[object, Path]] = []
_TMP: tempfile.TemporaryDirectory | None = None


def keep_queue_ledger_off_the_user_store() -> Path:
    """Point both ``salad_queue.LEDGER_PATH``s at one fresh temp file."""
    global _TMP
    import salad_queue as top_queue

    from salad_studio import salad_queue as pkg_queue

    if _TMP is None:
        _TMP = tempfile.TemporaryDirectory()
    ledger = Path(_TMP.name) / "studio-queue.json"
    for module in (top_queue, pkg_queue):
        _SAVED.append((module, module.LEDGER_PATH))
        module.LEDGER_PATH = ledger
    return ledger


def restore_queue_ledger() -> None:
    """Put the shipped ledger paths back and drop the temp directory."""
    global _TMP
    for module, saved in reversed(_SAVED):
        module.LEDGER_PATH = saved
    _SAVED.clear()
    if _TMP is not None:
        _TMP.cleanup()
        _TMP = None
