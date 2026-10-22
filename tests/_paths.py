"""Temp store paths, so a module that reads the user's files can be pointed elsewhere.

``_TempPaths`` moves every store constant a module-level import reaches, and
puts them back on exit. A test that builds a studio uses ``tests/_studio.py``
instead; this one is for modules that only need the paths.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class _TempPaths:
    """Every store path under one directory, for the life of the ``with`` block."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._saved: list[tuple[object, str, object]] = []

    def __enter__(self) -> "_TempPaths":
        import image_deploy
        import profiles
        import prompt_catalog
        import prompt_history
        import salad_queue
        import studio_meta
        import tokens
        import vast

        self.root.mkdir(parents=True, exist_ok=True)
        pairs = ((profiles, "PROFILES_PATH", "studio-profiles.json"),
                 (image_deploy, "SETTINGS_PATH", "studio-images.json"),
                 (prompt_catalog, "CATALOG_PATH", "studio-prompt-catalog.json"),
                 (prompt_history, "HISTORY_PATH", "studio-prompt-history.json"),
                 (prompt_history, "THUMBS_DIR", "studio-prompt-thumbs"),
                 (vast, "INSTANCES_PATH", "studio-vast.json"),
                 (salad_queue, "LEDGER_PATH", "studio-queue.json"),
                 (studio_meta, "USER_PATH", "studio-metadata.json"),
                 (tokens, "LOCAL_PATH", "studio-tokens.json"))
        for module, name, leaf in pairs:
            if hasattr(module, name):
                self._saved.append((module, name, getattr(module, name)))
                setattr(module, name, self.root / leaf)
        self._saved.append((tokens, "default_path", tokens.default_path))
        self._saved.append((tokens, "read_env_token", tokens.read_env_token))
        self._saved.append((tokens, "seed_from_defaults", tokens.seed_from_defaults))
        tokens.default_path = lambda _kind: self.root / "no-default"
        tokens.read_env_token = lambda _kind: ""
        tokens.seed_from_defaults = lambda: []
        return self

    def __exit__(self, *_exc: object) -> None:
        for module, name, value in reversed(self._saved):
            setattr(module, name, value)
        self._saved.clear()
