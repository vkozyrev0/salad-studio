"""What the pages share: the queue, the log, the two timers, the plates.

The Flet app's ``AppServices`` ran on the window's event loop. This one runs on
the core thread: a worker's result comes back through ``core.background``,
which hands it to ``done`` on that thread, so a handler never sees a half
written counter.

Every line the studio logs is published as one ``log`` event, already masked,
and the container's own log is announced by version so the Logs page fetches
it only when it changed.
"""
from __future__ import annotations

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

from salad_studio import generator, profiles, salad_status, studio_log, tokens
from salad_studio.web.shell import GenWord

ART = Path(os.environ.get("ELDERMARK_ART", r"C:\Users\vkozy\repos\lifesim-design\art"))
OUT_DIR = ART / "salad_studio"

SALAD_POLL_MS = 15000
GEN_TICK_MS = 2000
THUMB = 140
PLATE_LIMIT = 60
LOG_CAP = 2000


@dataclass(frozen=True)
class GenOutcome:
    """What one Generate press ended as: a plate, a refusal, or a failure."""

    kind: str  # "done" | "refused" | "failed"
    out: Path | None = None
    message: str = ""
    elapsed_s: int = 0


class WebServices:
    """The queue, the log, the probe, the timers and the plate cache."""

    def __init__(self, shell: Any) -> None:
        self.shell = shell
        self.core = shell.core
        self.hub = shell.hub
        self.log_lines: list[tuple[str, str]] = []
        self.salad_logs = ""
        self.salad_logs_version = 0
        self.snaps: dict[str, Any] = {}
        self.salad_key_error = ""
        self.salad_word = ""
        self._secrets: list[str] | None = None
        self._secrets_stamp: Any = None
        self._log_lock = threading.Lock()
        self._thumb_cache: dict[Path, tuple[Any, bytes | None]] = {}
        self._timers: list[int] = []
        self.gen_queue = queue_mod.shared()

    def bind(self) -> None:
        """Point the shared queue's log at this object; called once, on the core thread."""
        self.gen_queue.on_log = self.log
        if getattr(self.gen_queue, "lifecycle", None) is None:
            self.gen_queue.lifecycle = salad_status.ContainerLifecycle(self.salad_key)

    # -- keys and log

    def salad_key(self) -> str:
        return tokens.read_token("salad")

    def token(self, kind: str) -> str:
        return tokens.read_token(kind)

    def log_secrets(self) -> list[str]:
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
            del self.log_lines[:-LOG_CAP]
        self.hub.publish("log", {"level": level, "text": line[1]})

    def say_hello(self) -> None:
        """The first event of every stream: the shell state and the lines so far."""
        with self._log_lock:
            lines = [{"level": level, "text": text} for level, text in self.log_lines[-200:]]
        self.hub.publish("hello", {"shell": self.shell.state_dict(), "logs": lines})

    def set_salad_logs(self, text: str) -> None:
        self.salad_logs = studio_log.redact(text, self.log_secrets())
        self.salad_logs_version += 1
        self.hub.publish("salad_logs", {"version": self.salad_logs_version})

    def clear_logs(self) -> None:
        self.clear_studio_logs()
        self.set_salad_logs("")

    def clear_studio_logs(self) -> None:
        with self._log_lock:
            self.log_lines.clear()

    # -- timers

    def start(self, *, timers: bool = True) -> None:
        """Bind the queue, and start the probe and generation timers unless a test asks not to."""
        self.bind()
        if not timers:
            return
        self._timers = [
            self.core.call_later(500, lambda: self.check_salad(silent=True)),
            self.core.every(SALAD_POLL_MS, self._salad_tick),
            self.core.every(GEN_TICK_MS, self._gen_tick),
        ]

    def stop(self) -> None:
        for token in self._timers:
            self.core.cancel(token)
        self._timers.clear()

    def _salad_tick(self) -> None:
        if self.core.closing:
            return
        self.check_salad(silent=True)
        self.run_idle_check()
        self.shell.publish()

    def _gen_tick(self) -> None:
        """Tell the Queue page to read the job ledger again, so a running job is never a still picture."""
        if self.core.closing:
            return
        self.hub.publish("queue_changed", {})

    # -- the Salad probe

    def check_salad(self, *, silent: bool = False) -> None:
        if self.shell.busy.get("probe"):
            return
        self.shell.busy["probe"] = True
        gateways = [(name, p.gateway) for name, p in profiles.load_all().items() if p.gateway]
        key = self.salad_key()

        def work() -> Any:
            out: dict[str, Any] = {}
            for name, gateway in gateways:
                try:
                    out[name] = salad_status.snapshot_gateway(gateway, key)
                except Exception as exc:  # noqa: BLE001
                    out[name] = {"error": str(exc)}
            return out

        def done(result: Any) -> None:
            self.shell.busy.pop("probe", None)
            if isinstance(result, Exception):
                if not silent:
                    self.log("warn", f"Salad status check failed: {result}")
                return
            self.snaps = result
            self.salad_word = _status_word(result)
            error = next((str(s["error"]) for s in result.values()
                          if isinstance(s, dict) and s.get("error")), "")
            if error and error != self.salad_key_error:
                self.log("warn", f"Salad key: {error}")
            self.salad_key_error = error
            if not silent:
                self.log("info", f"Salad status checked for {len(result)} profile(s)")
            self.shell.refresh_counts()
            self.shell.publish()

        self.core.background(work, done)

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

        self.core.background(work, done)

    def run_idle_check(self) -> None:
        if self.shell.busy.get("idle"):
            return
        self.shell.busy["idle"] = True

        def work() -> Any:
            return self.gen_queue.idle_check()

        def done(result: Any) -> None:
            self.shell.busy.pop("idle", None)
            if isinstance(result, Exception):
                self.log("warn", f"Idle check failed: {result}")
            elif result:
                self.log("info", f"Stopped idle container(s): {', '.join(result)}")

        self.core.background(work, done)

    # -- Generate

    def generate_sync(self, payload: dict[str, Any], profile: profiles.SaladProfile, key: str,
                      checksum: str) -> GenOutcome:
        """Run one render and return its outcome. Runs on a worker thread; touches no studio state."""
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
            return GenOutcome("failed", message=str(exc))
        return GenOutcome("done", out=Path(out))

    def clean_gallery(self) -> int:
        """Delete every plate in the output folder and return how many went."""
        removed = 0
        for path in self.plates(limit=10_000):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        self._thumb_cache.clear()
        return removed

    # -- the plates

    def plates(self, limit: int = PLATE_LIMIT) -> list[Path]:
        try:
            found = [p for p in OUT_DIR.glob("*.jpg") if p.is_file()]
        except OSError:
            return []
        found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return found[:limit]

    def plate_path(self, name: str) -> Path | None:
        """The file a plate name refers to, refused when it names anything but one plate."""
        if not name or Path(name).name != name:
            return None
        path = OUT_DIR / name
        return path if path.is_file() else None

    def picture_path(self, name: str) -> Path | None:
        """A plate in the output folder, else a history row's own image.

        Only a bare file name is accepted, so a request can never walk out of
        either directory.
        """
        if not name or Path(name).name != name:
            return None
        plate = self.plate_path(name)
        if plate is not None:
            return plate
        from salad_studio import prompt_history

        row_image = prompt_history.THUMBS_DIR / name
        return row_image if row_image.is_file() else None

    def thumbnail(self, path: Path, size: int = THUMB) -> bytes | None:
        """A PNG no larger than ``size``, decoded once per file version."""
        stamp = _stamp(path)
        cached = self._thumb_cache.get(path)
        if cached is not None and cached[0] == stamp and stamp is not None:
            return cached[1]
        try:
            with Image.open(path) as img:
                img.thumbnail((size, size))
                out = io.BytesIO()
                img.convert("RGB").save(out, "PNG")
                png = out.getvalue()
        except (OSError, ValueError):
            png = None
        self._thumb_cache[path] = (stamp, png)
        return png

    def open_path(self, path: Path) -> None:
        os.startfile(str(path))  # type: ignore[attr-defined]


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _status_word(snaps: dict[str, Any]) -> str:
    """The gate's status word: the most urgent of the profiles' short statuses."""
    words = [str(s.get("word") or "") for s in snaps.values() if isinstance(s, dict)]
    words = [w for w in words if w]
    for wanted in ("Down", "Starting", "Not started"):
        if any(w.startswith(wanted) for w in words):
            return wanted
    return words[0] if words else ""


def level_color(level: str) -> str:
    return studio_log.LEVEL_COLORS.get(level, studio_log.LEVEL_COLORS["info"])
