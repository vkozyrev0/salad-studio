"""A whole studio with every controller, on temp stores.

The server's tests need the same few lines in every module: a core thread, a
shell, the controllers, and every store path pointed away from the user's own
files. This builds that and puts the paths back, so a test that drives the
studio never reads or writes ``~/.config/salad``.

Each store is one module object. The package binds its short name and its
package name to the same object when it loads, so moving the object the app
holds moves every spelling of it.
"""
from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class Studio:
    """A studio whose stores all live under one temporary directory."""

    def __init__(self) -> None:
        # Imported here so a module that patches a store at import time still
        # gets the object this fixture moves.
        import image_deploy
        import lora_store
        import profiles
        import prompt_catalog
        import prompt_history
        import salad_queue
        import studio_meta
        import tokens
        import vast

        self._modules = (image_deploy, lora_store, profiles, prompt_catalog, prompt_history,
                         salad_queue, studio_meta, tokens, vast)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        moves = {
            "PROFILES_PATH": root / "studio-profiles.json",
            "SETTINGS_PATH": root / "studio-images.json",
            "CATALOG_PATH": root / "studio-prompt-catalog.json",
            "HISTORY_PATH": root / "studio-prompt-history.json",
            "THUMBS_DIR": root / "studio-prompt-thumbs",
            "INSTANCES_PATH": root / "studio-vast.json",
            "LEDGER_PATH": root / "studio-queue.json",
            "LOCAL_PATH": root / "studio-tokens.json",
            "EXTRAS_PATH": root / "studio-loras.json",
        }
        self._saved: list[tuple[object, str, object]] = []
        for module in self._modules:
            for name, value in moves.items():
                if hasattr(module, name):
                    self._saved.append((module, name, getattr(module, name)))
                    setattr(module, name, value)
        for name in ("default_path", "read_env_token", "seed_from_defaults"):
            self._saved.append((tokens, name, getattr(tokens, name)))
        tokens.default_path = lambda _kind: root / "no-default"
        tokens.read_env_token = lambda _kind: ""
        tokens.seed_from_defaults = lambda: []

        from salad_studio.web import app

        self.app = app.build(dist=None, timers=False)
        # The gallery delete and a render's plate both write here, never to the
        # art folder the user renders into.
        self.app.shell.services.out_dir = root / "art"

    @property
    def shell(self) -> object:
        return self.app.shell

    @property
    def engine(self) -> object:
        return self.app.shell.engine

    @property
    def studio(self) -> object:
        return self.app.shell

    def act(self, page: str, action: str, args: dict | None = None) -> tuple[int, dict]:
        return self.engine.handle({"page": page, "action": action, "args": args or {}})

    def state(self, page: str) -> dict:
        return self.engine.page(page)["state"]

    def stop(self) -> None:
        self.app.stop()
        for module, name, value in self._saved:
            setattr(module, name, value)
        self.tmp.cleanup()


@contextmanager
def studio() -> Iterator[Studio]:
    """One studio for the body, stopped and its stores put back afterwards."""
    made = Studio()
    try:
        yield made
    finally:
        made.stop()
