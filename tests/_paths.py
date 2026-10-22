"""Temp store paths, so a module that reads the user's files can be pointed elsewhere.

``_TempPaths`` moves every store constant a module-level import reaches, and
puts them back on exit. Both spellings of each store are moved: the app imports
some modules top-level and some through the package, and those are two module
objects with two path constants. A test that builds a studio uses
``tests/_studio.py`` instead; this one is for modules that only need the paths.
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
        from salad_studio import image_deploy as pkg_image_deploy
        from salad_studio import profiles as pkg_profiles
        from salad_studio import prompt_catalog as pkg_prompt_catalog
        from salad_studio import prompt_history as pkg_prompt_history
        from salad_studio import salad_queue as pkg_salad_queue
        from salad_studio import studio_meta as pkg_studio_meta
        from salad_studio import tokens as pkg_tokens
        from salad_studio import vast as pkg_vast

        self.root.mkdir(parents=True, exist_ok=True)
        pairs = (
            (profiles, pkg_profiles, "PROFILES_PATH", "studio-profiles.json"),
            (image_deploy, pkg_image_deploy, "SETTINGS_PATH", "studio-images.json"),
            (prompt_catalog, pkg_prompt_catalog, "CATALOG_PATH", "studio-prompt-catalog.json"),
            (prompt_history, pkg_prompt_history, "HISTORY_PATH", "studio-prompt-history.json"),
            (prompt_history, pkg_prompt_history, "THUMBS_DIR", "studio-prompt-thumbs"),
            (vast, pkg_vast, "INSTANCES_PATH", "studio-vast.json"),
            (salad_queue, pkg_salad_queue, "LEDGER_PATH", "studio-queue.json"),
            (studio_meta, pkg_studio_meta, "USER_PATH", "studio-metadata.json"),
            (tokens, pkg_tokens, "LOCAL_PATH", "studio-tokens.json"),
        )
        for top, package, name, leaf in pairs:
            for module in (top, package):
                if hasattr(module, name):
                    self._saved.append((module, name, getattr(module, name)))
                    setattr(module, name, self.root / leaf)
        for module in (tokens, pkg_tokens):
            for name in ("default_path", "read_env_token", "seed_from_defaults"):
                self._saved.append((module, name, getattr(module, name)))
            module.default_path = lambda _kind: self.root / "no-default"
            module.read_env_token = lambda _kind: ""
            module.seed_from_defaults = lambda: []
        return self

    def __exit__(self, *_exc: object) -> None:
        for module, name, value in reversed(self._saved):
            setattr(module, name, value)
        self._saved.clear()
