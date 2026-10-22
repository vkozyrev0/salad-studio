"""A whole studio with every controller, on temp stores.

The server's tests need the same few lines in every module: a core thread, a
shell, the controllers, and every store path pointed away from the user's own
files. This builds that and puts the paths back, so a test that drives the
studio never reads or writes ``~/.config/salad``.
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
        import profiles
        import prompt_catalog
        import prompt_history
        import salad_queue
        import studio_meta
        import tokens
        import vast

        from salad_studio import salad_queue as pkg_queue

        # Both spellings of the stores the studio reads: the salting of
        # ``salad_studio`` alongside the package makes a second copy of each.
        from salad_studio import image_deploy as pkg_image_deploy
        from salad_studio import profiles as pkg_profiles
        from salad_studio import prompt_catalog as pkg_catalog
        from salad_studio import prompt_history as pkg_history
        from salad_studio import tokens as pkg_tokens
        from salad_studio import studio_meta as pkg_meta
        from salad_studio import vast as pkg_vast

        self._modules = (image_deploy, profiles, prompt_catalog, prompt_history,
                         salad_queue, pkg_queue, tokens, vast, studio_meta,
                         pkg_image_deploy, pkg_profiles, pkg_catalog, pkg_history,
                         pkg_tokens, pkg_meta, pkg_vast)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._saved: list[tuple[object, str, object]] = [
            (profiles, "PROFILES_PATH", profiles.PROFILES_PATH),
            (image_deploy, "SETTINGS_PATH", image_deploy.SETTINGS_PATH),
            (prompt_catalog, "CATALOG_PATH", prompt_catalog.CATALOG_PATH),
            (prompt_history, "HISTORY_PATH", prompt_history.HISTORY_PATH),
            (prompt_history, "THUMBS_DIR", prompt_history.THUMBS_DIR),
            (vast, "INSTANCES_PATH", vast.INSTANCES_PATH),
            (salad_queue, "LEDGER_PATH", salad_queue.LEDGER_PATH),
            (pkg_queue, "LEDGER_PATH", pkg_queue.LEDGER_PATH),
            (tokens, "LOCAL_PATH", tokens.LOCAL_PATH),
            (tokens, "default_path", tokens.default_path),
            (tokens, "read_env_token", tokens.read_env_token),
            (tokens, "seed_from_defaults", tokens.seed_from_defaults),
        ]
        for module in (pkg_image_deploy, pkg_profiles, pkg_catalog, pkg_history, pkg_tokens, pkg_meta, pkg_vast):
            for name in ("PROFILES_PATH", "SETTINGS_PATH", "CATALOG_PATH", "HISTORY_PATH",
                         "THUMBS_DIR", "INSTANCES_PATH", "LOCAL_PATH", "default_path",
                         "read_env_token", "seed_from_defaults"):
                if hasattr(module, name):
                    self._saved.append((module, name, getattr(module, name)))
        profiles.PROFILES_PATH = root / "studio-profiles.json"
        image_deploy.SETTINGS_PATH = root / "studio-images.json"
        prompt_catalog.CATALOG_PATH = root / "studio-prompt-catalog.json"
        prompt_history.HISTORY_PATH = root / "studio-prompt-history.json"
        prompt_history.THUMBS_DIR = root / "studio-prompt-thumbs"
        vast.INSTANCES_PATH = root / "studio-vast.json"
        salad_queue.LEDGER_PATH = root / "studio-queue.json"
        pkg_queue.LEDGER_PATH = root / "studio-queue.json"
        tokens.LOCAL_PATH = root / "studio-tokens.json"
        tokens.default_path = lambda _kind: root / "no-default"
        tokens.read_env_token = lambda _kind: ""
        tokens.seed_from_defaults = lambda: []
        for module in (pkg_image_deploy, pkg_profiles, pkg_catalog, pkg_history, pkg_tokens, pkg_meta, pkg_vast):
            for name, value in (("PROFILES_PATH", root / "studio-profiles.json"),
                                ("SETTINGS_PATH", root / "studio-images.json"),
                                ("CATALOG_PATH", root / "studio-prompt-catalog.json"),
                                ("HISTORY_PATH", root / "studio-prompt-history.json"),
                                ("THUMBS_DIR", root / "studio-prompt-thumbs"),
                                ("INSTANCES_PATH", root / "studio-vast.json"),
                                ("LOCAL_PATH", root / "studio-tokens.json"),
                                ("USER_PATH", root / "studio-metadata.json"),
                                ("INSTANCES_PATH", root / "studio-vast.json")):
                if hasattr(module, name):
                    setattr(module, name, value)
            if hasattr(module, "default_path"):
                module.default_path = lambda _kind, _root=root: _root / "no-default"
                module.read_env_token = lambda _kind: ""
                module.seed_from_defaults = lambda: []

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
