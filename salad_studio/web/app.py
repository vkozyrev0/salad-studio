"""Start the studio: the core thread, the pages, the server, and the browser.

``python -m salad_studio`` calls ``run``. A test calls ``build`` and stops the
studio itself. The pieces are assembled in one place so the entry point, the
tests and the dev script all start the same studio, in the same order.
"""
from __future__ import annotations

import webbrowser
from pathlib import Path

from salad_studio.web.core import Core
from salad_studio.web.engine import WebEngine
from salad_studio.web.events import Hub
from salad_studio.web.registry import Controllers
from salad_studio.web.server import StudioServer
from salad_studio.web.shell import Shell

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "ui" / "dist" / "ui" / "browser"
START_PAGE = "tokens"


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
        return f"http://127.0.0.1:{self.port}/#/{START_PAGE}"

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
        """Bind and serve until ``stop``. Returns the port actually bound."""
        port = self.server.start(port=port)
        self._serving = True
        return port


def build(*, dist: Path | None = DIST, timers: bool = True) -> Studio:
    """Assemble a studio without serving it yet. Timers off keeps a test off the network."""
    core = Core().start()
    hub = Hub()
    shell = Shell(core, hub)
    shell.controllers = Controllers(shell)
    shell.services.start(timers=timers)

    from salad_studio.web import controllers, pages

    controllers.install(shell.controllers)
    install = getattr(pages, "install", None) or getattr(pages, "add_all")
    install(shell.controllers)

    engine = WebEngine(shell)
    shell.engine = engine
    server = StudioServer(shell.controllers.table, dist=dist, log=shell.services.log,
                          engine=engine, hub=hub)
    return Studio(core, hub, shell, server)


def run(port: int = 0, *, open_browser: bool = True, dist: Path | None = DIST) -> None:
    """Serve until interrupted, then stop the timers and the thread."""
    studio = build(dist=dist)
    actual = studio.serve(port=port)
    print(f"Salad Studio: http://127.0.0.1:{actual}/#/{START_PAGE}", flush=True)
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{actual}/#/{START_PAGE}")
    try:
        studio.server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        studio.stop()
