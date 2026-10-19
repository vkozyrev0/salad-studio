"""The studio's state for the Flet window: the one queue, the log, the two timers.

Every page reads and writes through this object. It owns what the Tk window
owned: the shared ``SaladQueue`` (one per process, as ``salad_queue.shared()``
does), the Studio log lines with their secrets masked, the 15 s Salad probe
with the idle check, the 2 s generation tick, the last probe snapshots the
replica strip counts, and the busy flags that keep a second press from
starting a second network call.

Threads. A network call runs on a worker thread and hands its result back
through ``background``, which puts it on the UI thread during the next frame.
Nothing here touches a control; the pages do.

State on disk stays in the modules this wraps (``profiles``, ``vast``,
``tokens``, ``lora_store``, ``prompt_history``, ``prompt_catalog``,
``salad_queue``); this object holds only what one run of the window knows.
"""
from __future__ import annotations

import asyncio
import io
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import hostings  # noqa: E402  the top-level module the queue and the generator share
import salad_queue as queue_mod
from PIL import Image

from salad_studio import ai_helper, generator, lora_store, profiles, salad_status, studio_log, tokens
from salad_studio.flet_pump import Pump

ART = Path(os.environ.get("ELDERMARK_ART", r"C:\Users\vkozy\repos\lifesim-design\art"))
OUT_DIR = ART / "salad_studio"
PROBE_GLOB = "salad_probe_klein_*.jpg"

SALAD_POLL_MS = 15000
GEN_TICK_MS = 2000
STRIP_COLORS = salad_status.STRIP_COLORS
THUMB = 140
PLATE_LIMIT = 60


@dataclass(frozen=True)
class GenOutcome:
    """What one Generate press ended as: a plate, a refusal, or a failure."""

    kind: str  # "done" | "refused" | "failed"
    out: Path | None = None
    message: str = ""
    elapsed_s: int = 0


class AppServices:
    """What the pages share: the queue, the log, the probe, the timers and the flags."""

    def __init__(self, pump: Pump) -> None:
        self.pump = pump
        self.log_lines: list[tuple[str, str]] = []
        self.salad_logs: str = ""
        self.salad_logs_version = 0
        self.on_log: Callable[[str, str], None] | None = None
        self.on_timer: Callable[[str], None] | None = None
        self.on_generated: Callable[[Any], None] | None = None
        self.salad_word = ""
        self._closing = False
        self._secrets: list[str] | None = None
        self._secrets_stamp: Any = None
        self._log_lock = threading.Lock()
        # One queue per process, the one the generator also submits to, so a
        # job this window queues is the job the generator's type checks accept.
        self.gen_queue = queue_mod.shared()
        self.gen_queue.on_log = self.log
        if getattr(self.gen_queue, "lifecycle", None) is None:
            self.gen_queue.lifecycle = salad_status.ContainerLifecycle(self.salad_key)
        self.snaps: dict[str, Any] = {}
        self.salad_key_error = ""
        self.gen_jobs = 0
        self.busy = False
        self.gen_started = 0.0
        self.busy_flags: dict[str, bool] = {
            "help": False, "tokens": False, "vast_fetch": False,
            "vast_search": False, "vast_create": False, "salad": False, "idle": False,
        }
        # The offers a rent press would spend money on, and the one selected.
        self.offers: dict[str, dict[str, Any]] = {}
        self.selected_offer: dict[str, Any] | None = None
        self._salad_poll = 0
        self._gen_tick = 0

    # -- keys and log

    def salad_key(self) -> str:
        return tokens.read_token("salad")

    def token(self, kind: str) -> str:
        return tokens.read_token(kind)

    def log_secrets(self) -> list[str]:
        """Every saved key, so a log line can mask it. Cached until the token store changes."""
        try:
            st = tokens.LOCAL_PATH.stat()
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = None
        if self._secrets is None or stamp != self._secrets_stamp:
            found: list[str] = []
            for kind, _label, _rel in tokens.TOKEN_SPECS:
                try:
                    value = tokens.read_token(kind)
                except (OSError, AttributeError):
                    value = ""
                if value:
                    found.append(value)
            self._secrets = found
            self._secrets_stamp = stamp
        return self._secrets

    def log(self, level: str, text: str) -> None:
        """One Studio line, secrets masked. Safe from a worker thread."""
        line = (level, studio_log.format_line(level, studio_log.redact(text, self.log_secrets())))
        with self._log_lock:
            self.log_lines.append(line)
            del self.log_lines[:-2000]
        if self.on_log is not None:
            self.on_log(level, text)

    def set_salad_logs(self, text: str) -> None:
        self.salad_logs = studio_log.redact(text, self.log_secrets())
        self.salad_logs_version += 1

    def clear_logs(self) -> None:
        with self._log_lock:
            self.log_lines.clear()
        self.set_salad_logs("")

    # -- threads

    def post(self, fn: Callable[..., None], *args: Any, **kwargs: Any) -> None:
        """Run ``fn`` on the UI thread during the next frame."""
        self.pump.schedule(fn, *args, **kwargs)

    def background(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Run ``work`` on a worker thread and hand its result to ``done`` on the UI thread.

        The thread starts and ends inside the running loop's executor, which
        Flet owns: a thread started any other way has no event loop to hand its
        result to.
        """
        loop = asyncio.get_running_loop()

        def finish(result: Any) -> None:
            if not self._closing:
                done(result)

        async def run() -> None:
            try:
                result = await loop.run_in_executor(None, work)
            except Exception as exc:  # noqa: BLE001 - a worker's failure is shown, not raised
                result = exc
            finish(result)

        loop.create_task(run())

    # -- the Salad probe

    def check_salad(self, *, silent: bool = False) -> None:
        if self.busy_flags["salad"]:
            return
        self.busy_flags["salad"] = True
        gateways = [(name, p.gateway) for name, p in profiles.load_all().items() if p.gateway]

        def work() -> Any:
            out: dict[str, Any] = {}
            key = self.salad_key()
            for name, gateway in gateways:
                try:
                    out[name] = salad_status.snapshot_gateway(gateway, key)
                except Exception as exc:  # noqa: BLE001
                    out[name] = {"error": str(exc)}
            return out

        def done(result: Any) -> None:
            self.busy_flags["salad"] = False
            if isinstance(result, Exception):
                if not silent:
                    self.log("bad", f"Salad status check failed: {result}")
                return
            self.snaps = result
            self.salad_word = _status_word(result)
            error = next((str(s["error"]) for s in result.values()
                          if isinstance(s, dict) and s.get("error")), "")
            if error and error != self.salad_key_error:
                self.log("bad", f"Salad key: {error}")
            self.salad_key_error = error
            if not silent:
                self.log("info", f"Salad status checked for {len(result)} profile(s)")
            if self.on_timer is not None:
                self.on_timer("salad")

        self.background(work, done)

    def refresh_salad_logs(self) -> None:
        key = self.salad_key()
        gateway = next((p.gateway for p in profiles.load_all().values() if p.gateway), "")

        def work() -> Any:
            if not gateway:
                return "no gateway configured"
            try:
                return salad_status.recent_log_lines(gateway, key)
            except Exception as exc:  # noqa: BLE001
                return f"refused: {exc}"

        def done(result: Any) -> None:
            self.set_salad_logs(str(result))
            if self.on_timer is not None:
                self.on_timer("logs")

        self.background(work, done)

    # -- the two timers, as one loop

    def start_timers(self) -> None:
        """A first silent probe after 500 ms, the 15 s probe with its idle check, the 2 s gen tick."""
        self.pump.call_later(500, lambda: self.check_salad(silent=True))
        self._salad_poll = self.pump.every(SALAD_POLL_MS, self._salad_tick)
        self._gen_tick = self.pump.every(GEN_TICK_MS, self._gen_tick_fn)

    def _salad_tick(self) -> None:
        if self._closing:
            return
        self.check_salad(silent=True)
        self.run_idle_check()
        if self.on_timer is not None:
            self.on_timer("queue")

    def _gen_tick_fn(self) -> None:
        if self._closing or self.gen_jobs <= 0:
            return
        if self.on_timer is not None:
            self.on_timer("gen")
            self.on_timer("queue")

    def stop(self) -> None:
        """Close: cancel both timers and refuse work that lands after this."""
        self._closing = True
        self.pump.cancel(self._salad_poll)
        self.pump.cancel(self._gen_tick)

    @property
    def closing(self) -> bool:
        return self._closing

    def run_idle_check(self) -> None:
        if self.busy_flags["idle"]:
            return
        self.busy_flags["idle"] = True

        def work() -> Any:
            return self.gen_queue.idle_check()

        def done(result: Any) -> None:
            self.busy_flags["idle"] = False
            if isinstance(result, Exception):
                self.log("warn", f"Idle check failed: {result}")
            elif result:
                self.log("info", f"Stopped idle container(s): {', '.join(result)}")

        self.background(work, done)

    # -- Generate

    def generate(self, payload: dict[str, Any], profile: profiles.SaladProfile, key: str,
                 checksum: str) -> None:
        """Queue one render and answer with a GenOutcome, on a worker thread."""
        self.gen_jobs += 1
        if self.gen_jobs == 1:
            self.gen_started = time.monotonic()
        self.busy = True
        started = time.monotonic()

        def work() -> Any:
            try:
                if profile.mode == "vast":
                    out = generator.generate_from_vast(
                        endpoint=profile.gateway, payload=payload, out_dir=OUT_DIR,
                        on_log=self.log, queue=self.gen_queue, line=profile.name, checksum=checksum)
                else:
                    out = generator.generate_from_payload(
                        gateway=profile.gateway, key=key, payload=payload, out_dir=OUT_DIR,
                        on_log=self.log, queue=self.gen_queue, line=profile.name, checksum=checksum)
            except generator.ContainerDown as exc:
                return GenOutcome("refused", message=str(exc))
            except Exception as exc:  # noqa: BLE001 - the render's own failure is shown
                return GenOutcome("failed", message=str(exc), elapsed_s=int(time.monotonic() - started))
            return GenOutcome("done", out=Path(out), elapsed_s=int(time.monotonic() - started))

        self.background(work, self.finish_generate)

    def finish_generate(self, outcome: Any) -> None:
        self.gen_jobs = max(0, self.gen_jobs - 1)
        if self.gen_jobs <= 0:
            self.busy = False
        if self.on_generated is not None:
            self.on_generated(outcome)
        if self.on_timer is not None:
            self.on_timer("gen")
            self.on_timer("queue")

    def remember_request(self, payload: dict[str, Any], profile: profiles.SaladProfile) -> None:
        from salad_studio import prompt_history

        prompt_history.add_request(payload, profile=profile.name, gateway=profile.gateway)

    # -- the history strip

    def plates(self, limit: int = PLATE_LIMIT) -> list[Path]:
        """The newest plates in the output tree, newest first."""
        try:
            found = [p for p in OUT_DIR.glob("*.jpg") if p.is_file()]
        except OSError:
            return []
        found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return found[:limit]

    def thumbnail(self, path: Path, size: int = THUMB) -> bytes | None:
        try:
            with Image.open(path) as img:
                img.thumbnail((size, size))
                out = io.BytesIO()
                img.convert("RGB").save(out, "PNG")
                return out.getvalue()
        except (OSError, ValueError):
            return None

    def open_path(self, path: Path) -> None:
        os.startfile(str(path))  # type: ignore[attr-defined]


def _status_word(snaps: dict[str, Any]) -> str:
    """The gate's status word: the most urgent of the profiles' short statuses."""
    words = [str(s.get("word") or "") for s in snaps.values() if isinstance(s, dict)]
    words = [w for w in words if w]
    for wanted in ("Down", "Starting", "Not started"):
        if any(w.startswith(wanted) for w in words):
            return wanted
    return words[0] if words else ""


def level_color(level: str) -> str:
    """The palette hex the Studio pane draws one level in, as the Tk pane did."""
    return studio_log.LEVEL_COLORS.get(level, studio_log.LEVEL_COLORS["info"])


def help_round(api_key: str, *, local: bool, local_url: str = "", **inputs: Any) -> dict[str, Any]:
    """One Prompt Assist round trip: build, ask, parse. Raises ``ai_helper.AiError``."""
    if local:
        return ai_helper.help_with_prompts_local(url=local_url or ai_helper.LOCAL_BASE_URL, **inputs)
    return ai_helper.help_with_prompts(api_key, **inputs)


def loras_for(graph: str) -> list[dict[str, Any]]:
    return [item for item in lora_store.list_loras() if lora_store.compatible_with_graph(item, graph)]
