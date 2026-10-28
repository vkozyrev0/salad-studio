"""The form the window holds: what Config and Prompt Settings both edit.

Moved from the old page factory unchanged in behaviour. The fields are text because
they are typed into; ``profile`` is the one place that turns them into a
``SaladProfile`` and refuses a bad value by name, which is the message a page
puts under the control that caused it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import lora_store
import profiles


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
    # "on" or "". Not a profile field: the profile describes the request, and
    # the cutout runs after the plate is already on disk.
    remove_bg: str = ""

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
