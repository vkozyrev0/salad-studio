"""The page factories and the form the pages share, without a window.

``flet_app`` keeps the window: its dialogs, its action bar, Generate and the
page cache. The page list, the factory each rail entry calls, and the ``Form``
the Config and Prompt Settings pages read and write live here, so a page can be
built and driven in a test with a stand-in host.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from salad_studio import lora_store, profiles


@dataclass
class Form:
    """The Config and Prompt Settings values the window shows, and the profile they describe."""

    name: str = "klein"
    gateway: str = ""
    mode: str = "salad"
    graph: str = "klein"
    width: str = "1024"
    height: str = "1024"
    steps: str = "20"
    cfg: str = "1"
    seed: str = "1"
    scheduler: str = "flux2"
    selected_loras: list[str] = field(default_factory=list)

    def from_profile(self, p: profiles.SaladProfile) -> "Form":
        return Form(
            name=p.name,
            gateway=p.gateway,
            mode=p.mode,
            graph=p.graph,
            width=str(p.width),
            height=str(p.height),
            steps=str(p.steps),
            cfg=str(p.cfg),
            seed=str(p.seed),
            scheduler=p.scheduler,
            selected_loras=list(p.selected_loras),
        )

    def profile(self, stored: profiles.SaladProfile | None = None) -> profiles.SaladProfile:
        """The profile this form describes. Raises ValueError naming the bad knob."""

        def whole(field: str, raw: str, default: int) -> int:
            text = str(raw or "").strip()
            if not text:
                return default
            try:
                return int(text)
            except ValueError:
                raise ValueError(f"{field} must be a whole number (got {text!r})") from None

        def number(field: str, raw: str, default: float) -> float:
            text = str(raw or "").strip()
            if not text:
                return default
            try:
                return float(text)
            except ValueError:
                raise ValueError(f"{field} must be a number (got {text!r})") from None

        checkpoints = list(stored.checkpoints) if stored is not None else profiles.seed_checkpoints(self.name)
        return profiles.SaladProfile(
            name=self.name,
            gateway=self.gateway.strip(),
            mode=self.mode,
            key_path=profiles.DEFAULT_KEY_PATH,
            graph=lora_store.graph_id(self.graph),
            width=whole("Width", self.width, 1024),
            height=whole("Height", self.height, 1024),
            steps=whole("Steps", self.steps, 20),
            cfg=number("CFG", self.cfg, profiles.FORM_CFG),
            seed=int(number("Seed", self.seed, 1)),
            scheduler=self.scheduler,
            checkpoints=checkpoints,
            use_loras=bool(self.selected_loras),
            selected_loras=list(self.selected_loras),
            policy=dict(stored.policy) if stored is not None else {},
        )


def page(host: Any, name: str) -> Any:
    """Build the page a rail entry names, against the host window."""
    from salad_studio.pages import (
        assist, catalog, config, editor, history, import_page, logs_page, loras, prompt_settings,
        queue_page, tokens_page,
    )

    builders = {
        "Config": config.ConfigPage,
        "Prompt Settings": prompt_settings.SettingsPage,
        "Tokens": tokens_page.TokensPage,
        "LoRAs": loras.LorasPage,
        "Prompt Editor": editor.EditorPage,
        "Prompt Assist": assist.AssistPage,
        "Prompt Catalog": catalog.CatalogPage,
        "Import": import_page.ImportPage,
        "Prompt History": history.HistoryPage,
        "Queue": queue_page.QueuePage,
        "Logs": logs_page.LogsPage,
    }
    return builders[name](host)
