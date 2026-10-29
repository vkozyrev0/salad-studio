"""Start the studio: the core thread, the pages, the server, and the browser.

``python -m salad_studio`` calls ``run``. A test calls ``build`` and stops the
studio itself. The pieces are assembled in one place so the entry point, the
tests and the dev script all start the same studio, in the same order.
"""
from __future__ import annotations

import hashlib
import subprocess
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

from salad_studio.web.core import Core
from salad_studio.web.engine import WebEngine
from salad_studio.web.events import Hub
from salad_studio.web.registry import Controllers
from salad_studio.web.server import StudioServer
from salad_studio.web.shell import Shell

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "ui" / "dist" / "ui"
SOURCE = ROOT / "ui" / "src"
START_PAGE = "config"
# A driven page is examined for well under a minute, so a probe due this late
# never fires inside such a test. A person starting the studio waits for the
# first poll two minutes later instead of this one.
DRIVEN_PROBE_AFTER_MS = 60_000


class Studio:
    """A running studio: its thread, its services, its server and its controllers."""

    def __init__(self, core: Core, hub: Hub, shell: Shell, server: StudioServer) -> None:
        self.core = core
        self.hub = hub
        self.shell = shell
        self.server = server

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    @property
    def url(self) -> str:
        """The page's address, with the run token where the page finds it and before the route."""
        return f"http://127.0.0.1:{self.port}/?token={self.server.run_token or ''}#/{START_PAGE}"

    def stop(self) -> None:
        # ``shutdown`` waits for ``serve_forever``, so it is only called on a
        # server that is serving. A studio built and never started closes its
        # socket and stops its thread directly.
        self.shell.services.stop()
        if self._serving:
            self.server.shutdown()
        self.server.server_close()
        self.core.stop()

    _serving = False

    def serve(self, port: int = 0) -> int:
        """Bind, send a background thread's answers, and hand the loop to the caller.

        ``stop`` can only wait out a ``serve_forever`` that runs, so the thread
        starts here, as it does for every server but ``run``'s own loop.
        """
        port = self.server.start(port=port)
        self.shell.run_token = self.server.run_token
        self._serving = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return port


def build(*, dist: Path | None = DIST, timers: bool = True, probe_after_ms: int = 500) -> Studio:
    """Assemble a studio without serving it yet. Timers off keeps a test off the network.

    ``probe_after_ms`` is how long after start the studio asks Salad and
    vast.ai about its gateways. Those probes are background work on the worker
    pool, which holds four threads, so a test that drives the page with fakes
    sets the delay high and its unmocked calls are never made.
    """
    core = Core().start()
    hub = Hub()
    shell = Shell(core, hub)
    core.on_error = lambda exc: shell.services.log("error", f"core: {type(exc).__name__}: {exc}")
    shell.controllers = Controllers(shell)
    shell.services.start(timers=timers, probe_after_ms=probe_after_ms)

    from salad_studio.web import controllers, pages

    controllers.install(shell.controllers)
    install = getattr(pages, "install", None) or getattr(pages, "add_all")
    install(shell.controllers)

    engine = WebEngine(shell)
    shell.engine = engine
    server = StudioServer(shell.controllers.table, dist=dist, log=shell.services.log,
                          engine=engine, hub=hub)
    return Studio(core, hub, shell, server)


def build_page(source: Path | None = None, dist: Path | None = None,
               run: Callable[[], bool] | None = None) -> bool:
    """Build the page when it is missing or was built from other source.

    ``ui/dist`` is not committed. Every build writes the digest of everything
    under ``src`` and ``public`` (with its ``angular.json`` settings) into
    ``.stamp`` beside its ``index.html``. A missing page, or a stamp that does
    not describe the tree now, builds; a match keeps the page it has. A
    checkout restamps files without changing them, so a clock cannot answer
    this question and a digest can.
    """
    source = SOURCE if source is None else source
    dist = DIST if dist is None else dist
    stamp = dist / ".stamp"
    if not (dist / "index.html").is_file():
        return bool((run or _ng_build)())
    try:
        current = stamp.is_file() and stamp.read_text().strip() == _source_digest(source)
    except OSError:
        current = False
    if current:
        return False
    return bool((run or _ng_build)())


def _source_digest(source: Path) -> str:
    """A digest of the page's inputs: its sources, public files and build settings.

    ``package.json`` and its lockfile stay out: installing a package rewrites
    both without changing the page.
    """
    digest = hashlib.sha256()
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        digest.update(path.relative_to(source).as_posix().encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
    for name in ("angular.json", "tsconfig.json", "tsconfig.app.json", "public"):
        extra = source.parent / name
        if extra.is_file():
            digest.update(name.encode() + b"=" + extra.read_bytes())
        elif extra.is_dir():
            for path in sorted(p for p in extra.rglob("*") if p.is_file()):
                digest.update(f"{name}/".encode() + path.relative_to(extra).as_posix().encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def _ng_build() -> bool:
    """Run the page's build once. False when there is no toolchain or it fails."""
    ui = ROOT / "ui"
    if not (ui / "node_modules").is_dir():
        return False
    # The digest is taken first: a source typed while the build runs is newer
    # than what the build read, so its page is marked out of date, not fresh.
    source = _source_digest(SOURCE)
    try:
        done = subprocess.run(["npx", "ng", "build"], cwd=ui, shell=True, timeout=600,
                              check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if done.returncode != 0 or not (DIST / "index.html").is_file():
            return False
        # A file on disk is not a file the server can see yet: the write that
        # made it may still be in the OS cache. The stamp is last, and the
        # server answers from an empty build until it is there.
        (DIST / "index.html").open("rb").close()
        (DIST / ".stamp").write_text(source)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def run(port: int = 0, *, open_browser: bool = True, dist: Path | None = DIST) -> None:
    """Serve until interrupted, then stop the timers and the thread."""
    # A page opened without the token asks for its first state at once, so a
    # missing build would otherwise answer that request instead of the page.
    if dist is not None and build_page():
        print("Salad Studio: built the page in ui/dist", flush=True)
    studio = build(dist=dist)
    studio.serve(port=port)
    # The URL carries the run token; a page opened without it reaches nothing.
    print(f"Salad Studio: {studio.url}", flush=True)
    if open_browser:
        webbrowser.open(studio.url)
    try:
        studio.server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        studio.stop()
