"""One module per ported page, and the list of controllers the server installs."""
from __future__ import annotations

from typing import Any

from salad_studio.web.pages.assist import AssistController
from salad_studio.web.pages.catalog import CatalogController
from salad_studio.web.pages.config import ConfigController
from salad_studio.web.pages.editor import EditorController
from salad_studio.web.pages.history import HistoryController
from salad_studio.web.pages.import_page import ImportController
from salad_studio.web.pages.logs import LogsController
from salad_studio.web.pages.loras import LorasController
from salad_studio.web.pages.queue import QueueController
from salad_studio.web.pages.settings import SettingsController

# The rail's order, so a fresh studio installs them in the order a person meets them.
CONTROLLERS: tuple[type, ...] = (
    ConfigController,
    SettingsController,
    LorasController,
    EditorController,
    AssistController,
    CatalogController,
    ImportController,
    HistoryController,
    QueueController,
    LogsController,
)


def add_all(controllers: Any) -> None:
    """Put every page in this package on the table. Call twice only for a fresh studio."""
    for kind in CONTROLLERS:
        if controllers.get(kind.page) is None:
            controllers.add(kind(controllers.studio))


def install(controllers: Any) -> None:
    """The server's name for ``add_all``."""
    add_all(controllers)
