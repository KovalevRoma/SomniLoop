from __future__ import annotations

import os
import sys
from pathlib import Path

from platformdirs import user_data_dir
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from somniloop.core.database import Repository
from somniloop.ui.main_window import MainWindow


def data_directory() -> Path:
    override = os.environ.get("SOMNILOOP_DATA_DIR")
    return Path(override).expanduser() if override else Path(user_data_dir("SomniLoop"))


def icon_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "somniloop.svg"


def run() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("SomniLoop")
    application.setOrganizationName("SomniLoop")
    application.setApplicationDisplayName("SomniLoop")
    application.setDesktopFileName("somniloop")
    application.setWindowIcon(QIcon(str(icon_path())))
    repository = Repository(data_directory() / "somniloop.db")
    window = MainWindow(repository, icon_path())
    window.show()
    return application.exec()
