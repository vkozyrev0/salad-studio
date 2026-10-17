"""Where a profile renders: one adapter per hosting.

An adapter is the contract the app codes against: its labels for the Config page,
the URL it can fill from an existing store, and the render itself. Adding a
hosting is a class here and one row in ADAPTERS. The profile stores the key.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Hosting(Protocol):
    key: str
    label: str
    url_label: str
    can_pick: bool

    def pick_url(self) -> tuple[str, str]:
        """The URL to prefill and a refusal ("" when the store has a row)."""

    def generate(self, payload: dict, profile: Any) -> None:
        """Render this profile's graph on this hosting."""


class SaladAdapter:
    key = "salad"
    label = "Salad gateway"
    url_label = "Gateway URL"
    can_pick = False

    def __init__(self, app: Any) -> None:
        self._app = app

    def pick_url(self) -> tuple[str, str]:
        return "", "This hosting has no saved instance list."

    def generate(self, payload: dict, profile: Any) -> None:
        self._app._generate_salad(payload, profile)


class VastAdapter:
    key = "vast"
    label = "Vast.ai instance"
    url_label = "Instance URL"
    can_pick = True

    def __init__(self, app: Any) -> None:
        self._app = app

    def pick_url(self) -> tuple[str, str]:
        row = self._app._vast_active()
        if row is None:
            return "", "No vast.ai instance is selected."
        return str(row.get("endpoint") or ""), ""

    def generate(self, payload: dict, profile: Any) -> None:
        self._app._on_generate_vast(payload, profile)


ADAPTERS: tuple[type[Hosting], ...] = (SaladAdapter, VastAdapter)
DEFAULT = "salad"
BY_KEY = {cls.key: cls for cls in ADAPTERS}
