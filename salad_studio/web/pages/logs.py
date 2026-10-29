"""Logs: the container's own log beside the Studio's lines, secrets already masked.

Every line carries its level as text, so the page can mark it as well as colour
it. The container's log is a whole text block with a version: the page fetches
it again only when the version changes.
"""
from __future__ import annotations

from typing import Any

import profiles
from salad_studio import salad_status

EMPTY_SALAD_TEXT = "(nothing fetched yet)"


class LogsController:
    page = "logs"

    def __init__(self, studio: Any) -> None:
        self.studio = studio
        self.salad_state = ""

    def register(self, table: Any) -> None:
        table.action("logs.view")(self.view)
        table.action("logs.clear")(self.clear)
        table.action("logs.refresh_salad_logs")(self.refresh_salad_logs)
        table.action("logs.check_salad")(self.check_salad)

    def view(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        return self.state()

    def state(self) -> dict[str, Any]:
        services = self.studio.services
        return {
            "lines": [{"level": level, "text": text} for level, text in services.log_lines],
            "salad": {
                "version": services.salad_logs_version,
                "text": services.salad_logs or "",
                "empty_text": "" if services.salad_logs else EMPTY_SALAD_TEXT,
            },
            "salad_state": self.salad_state,
            "token_states": [],
        }

    # -- actions

    def clear(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        self.studio.services.clear_studio_logs()
        ctx.note("Studio logs cleared")
        return self.state()

    def refresh_salad_logs(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        services = self.studio.services

        def work() -> Any:
            return _recent_salad_log(services)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self.salad_state = f"The container log could not be read: {result}"
                ctx.note(self.salad_state, level="error")
                return
            if result is None:
                self.salad_state = "No profile has a gateway, so there is no container log to read."
                ctx.note(self.salad_state, level="warn")
                return
            services.set_salad_logs(str(result))
            self.salad_state = "" if str(result).strip() else "The container has logged nothing in the last 20 minutes."
            ctx.note("Refreshed the Salad container log")

        ctx.note("Refreshing the Salad logs…")
        ctx.background(work, done)
        return self.state()

    def check_salad(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        services = self.studio.services

        def work() -> Any:
            return _probe_salad(services)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self.salad_state = f"Salad status could not be read: {result}"
                ctx.note(self.salad_state, level="error")
                return
            if not result:
                self.salad_state = "No profile has a gateway, so there is no container to check."
                ctx.note(self.salad_state, level="warn")
                return
            self.salad_state = "; ".join(f"{name}: {word}" for name, word in result)
            ctx.note(self.salad_state, level="ok")

        ctx.note("Checking Salad status…")
        ctx.background(work, done)
        return self.state()


def _recent_salad_log(services: Any) -> str | None:
    """The gateway's recent lines, or None when no profile has a gateway."""
    profile = next((p for p in profiles.load_all().values() if p.gateway), None)
    if profile is None:
        return None
    try:
        return salad_status.recent_log_lines(
            services.salad_key(), group_name=getattr(profile, "name", ""))
    except Exception as exc:  # noqa: BLE001 - the refusal is what the page shows
        return f"refused: {exc}"


def _probe_salad(services: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for profile in profiles.load_all().values():
        if not profile.gateway:
            continue
        try:
            snap = salad_status.snapshot_gateway(profile.gateway, services.salad_key())
            out.append((str(profile.name), str((snap or {}).get("word") or "no status")))
        except Exception as exc:  # noqa: BLE001 - one gateway's refusal is one line
            out.append((str(profile.name), str(exc)))
    return out
