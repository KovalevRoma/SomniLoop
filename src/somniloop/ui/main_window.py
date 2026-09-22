from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.core.models import TrackerMode
from somniloop.reminders import show_desktop_notifications

from .calendar_dialog import CalendarDialog
from .controls import RoundedMainWindow as QMainWindow
from .controls import show_saved
from .dashboard import Dashboard
from .dialogs import CreateTrackerDialog, EditTrackerDialog, SettingsDialog
from .knowledge_graph import KnowledgeGraphPage
from .personal_dialogs import BioDialog, DiaryDialog, PeopleDialog
from .planner import ArchiveDialog, NotificationDrawer
from .theme import stylesheet
from .tracker_detail import TrackerDetailDialog


class MainWindow(QMainWindow):
    def __init__(self, repository: Repository, icon_path: Path | None = None) -> None:
        super().__init__()
        self.repository = repository
        self.icon_path = icon_path
        if icon_path and icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1280, 790)
        self.setMinimumSize(980, 650)
        self._rebuild_ui()
        self._current_day = date.today()
        self.day_timer = QTimer(self)
        self.day_timer.setInterval(60000)
        self.day_timer.timeout.connect(self._check_day)
        self.day_timer.start()

    def _rebuild_ui(self) -> None:
        if hasattr(self, "graph_page"):
            self.graph_page.graph_view.save_state()
            self.graph_page.graph_view.state.repository = None
        language = self.repository.get_setting("language", "ru")
        self.i18n = I18n(language)
        QApplication.instance().setProperty("language", language)
        self.setWindowTitle(self.i18n.t("app_name"))
        theme = self.repository.get_setting("theme", "dark")
        if theme == "system":
            theme = (
                "light"
                if QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.LightColor
                else "dark"
            )
        QApplication.instance().setStyleSheet(stylesheet(theme))
        QApplication.instance().setProperty("somniloopTheme", theme)

        root_widget = QWidget()
        root_widget.setObjectName("windowContent")
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(12)
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top = QHBoxLayout(top_bar)
        logo = QLabel()
        logo.setFixedSize(38, 38)
        if self.icon_path and self.icon_path.exists():
            logo.setPixmap(
                QPixmap(str(self.icon_path)).scaled(
                    QSize(36, 36),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            logo.setText("∞")
        title = QLabel(self.i18n.t("app_name"))
        title.setObjectName("appTitle")
        self.dashboard_button = QPushButton(self.i18n.t("dashboard"))
        self.dashboard_button.setCheckable(True)
        self.dashboard_button.setChecked(True)
        self.dashboard_button.clicked.connect(lambda: self._show_page(0))
        self.graph_button = QPushButton(self.i18n.t("knowledge"))
        self.graph_button.setCheckable(True)
        self.graph_button.clicked.connect(lambda: self._show_page(1))
        settings = QPushButton("⚙")
        settings.setFixedSize(36, 36)
        settings.setStyleSheet("padding:0;")
        settings.setToolTip(self.i18n.t("settings"))
        settings.setAccessibleName(self.i18n.t("settings"))
        settings.clicked.connect(self._settings)
        archive = QPushButton(self.i18n.t("archive"))
        archive.setToolTip(self.i18n.t("archive"))
        archive.clicked.connect(self._archive)
        self.notifications_button = QPushButton("🎂 0")
        self.notifications_button.setToolTip(self.i18n.t("birthday_reminders"))
        self.notifications_button.clicked.connect(
            lambda: self.notification_drawer.setVisible(not self.notification_drawer.isVisible())
        )
        top.addWidget(logo)
        top.addWidget(title)
        top.addSpacing(20)
        top.addWidget(self.dashboard_button)
        top.addWidget(self.graph_button)
        top.addStretch()
        top.addWidget(self.notifications_button)
        top.addWidget(archive)
        top.addWidget(settings)
        root.addWidget(top_bar)
        self.notification_drawer = NotificationDrawer(self.repository, self.i18n)
        self.notification_drawer.count_changed.connect(
            lambda count: self.notifications_button.setText(f"🎂 {count}")
        )
        self.notification_drawer.refresh()
        if QApplication.instance().platformName() != "offscreen":
            show_desktop_notifications(self.repository)
        root.addWidget(self.notification_drawer)

        self.pages = QStackedWidget()
        self.dashboard = Dashboard(self.repository, self.i18n)
        self.dashboard.new_requested.connect(self._new_tracker)
        self.dashboard.create_requested.connect(self._new_tracker)
        self.dashboard.open_requested.connect(self._open_tracker)
        self.dashboard.edit_requested.connect(self._edit_tracker)
        self.dashboard.calendar_requested.connect(self._calendar)
        self.dashboard.data_changed.connect(self._data_changed)
        self.dashboard.archive_requested.connect(self._archive)
        self.graph_page = KnowledgeGraphPage(self.repository, self.i18n)
        self.graph_page.bio_requested.connect(self._bio)
        self.graph_page.people_requested.connect(self._people)
        self.graph_page.source_requested.connect(self._graph_source)
        self.graph_page.graph_updated.connect(self.notification_drawer.refresh)
        self.pages.addWidget(self.dashboard)
        self.pages.addWidget(self.graph_page)
        self.pages.currentChanged.connect(self._sync_navigation)
        root.addWidget(self.pages, 1)
        old = self.centralWidget()
        self.setCentralWidget(root_widget)
        if old:
            old.deleteLater()

    def _show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self._sync_navigation(index)

    def _sync_navigation(self, index: int) -> None:
        self.dashboard_button.setChecked(index == 0)
        self.graph_button.setChecked(index == 1)

    def _new_tracker(self, kind="habit") -> None:
        dialog = CreateTrackerDialog(self.i18n, self)
        dialog.mode_combo.setCurrentIndex(
            dialog.mode_combo.findData(
                TrackerMode.MANUAL if kind == "plan" else TrackerMode.REGULAR
            )
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.repository.create_tracker(**dialog.values())
        except Exception as exc:
            QMessageBox.critical(
                self,
                self.i18n.t("new_tracker"),
                self.i18n.t("tracker_create_error", error=exc),
            )
            return
        self.dashboard.refresh()
        show_saved(self, self.i18n.t("saved"))
        self.graph_page.mark_stale()

    def _open_tracker(self, tracker_id: int) -> None:
        dialog = TrackerDetailDialog(self.repository, tracker_id, self.i18n, self)
        dialog.data_changed.connect(self._data_changed)
        dialog.tracker_deleted.connect(self._data_changed)
        dialog.exec()
        self._data_changed()

    def _edit_tracker(self, tracker_id: int) -> None:
        dialog = EditTrackerDialog(self.i18n, self.repository.get_tracker(tracker_id), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.repository.update_tracker(
            tracker_id,
            values["name"],
            values["description"],
            values["schedule_type"],
            values["schedule"],
        )
        self.dashboard.refresh(changed_tracker=tracker_id)
        self.graph_page.mark_stale()
        show_saved(self, self.i18n.t("saved"))

    def _calendar(self, tracker_id: int) -> None:
        dialog = CalendarDialog(self.repository, tracker_id, self.i18n, self)
        dialog.data_changed.connect(self._data_changed)
        dialog.exec()

    def _bio(self) -> None:
        dialog = BioDialog(self.repository, self.i18n, self)
        dialog.data_changed.connect(self._knowledge_source_changed)
        dialog.exec()

    def _people(self, target=None) -> None:
        if self.graph_page.worker and self.graph_page.worker.isRunning():
            QMessageBox.information(self, self.i18n.t("knowledge"), self.i18n.t("wait_for_graph"))
            return
        person_id, clarification_index = target if isinstance(target, tuple) else (None, None)
        dialog = PeopleDialog(
            self.repository,
            self.i18n,
            self,
            select_person_id=person_id,
            clarification_index=clarification_index,
        )
        dialog.data_changed.connect(self._knowledge_source_changed)
        dialog.exec()

    def _knowledge_source_changed(self) -> None:
        self.graph_page.refresh()
        self.graph_page.mark_stale()
        self.notification_drawer.refresh()

    def _graph_source(self, identifier: str) -> None:
        # Only legacy notes already in the database are opened; no note nodes are created.
        if self.graph_page.worker and self.graph_page.worker.isRunning():
            QMessageBox.information(self, self.i18n.t("knowledge"), self.i18n.t("wait_for_graph"))
            return
        try:
            note_id = int(identifier.removeprefix("note:"))
        except ValueError:
            return
        if not any(note.id == note_id for note in self.repository.list_notes()):
            QMessageBox.information(self, "Источник", "Исходная запись больше не доступна в базе.")
            return
        dialog = DiaryDialog(self.repository, self.i18n, self)
        for index in range(dialog.entry_list.count()):
            item = dialog.entry_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == note_id:
                dialog.entry_list.setCurrentItem(item)
                break
        dialog.data_changed.connect(self._knowledge_source_changed)
        dialog.exec()

    def _archive(self) -> None:
        dialog = ArchiveDialog(self.repository, self.i18n, self)
        dialog.data_changed.connect(self._data_changed)
        dialog.exec()

    def _check_day(self) -> None:
        if date.today() != self._current_day:
            self._current_day = date.today()
            self.dashboard.refresh()
            self.notification_drawer.refresh()

    def _settings(self) -> None:
        if self.graph_page.worker and self.graph_page.worker.isRunning():
            QMessageBox.information(self, self.i18n.t("knowledge"), self.i18n.t("wait_for_graph"))
            return
        self.graph_page.graph_view.save_state()
        dialog = SettingsDialog(self.repository, self.i18n, self)
        dialog.settings_saved.connect(self._rebuild_ui)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            show_saved(self, self.i18n.t("saved"))

    def _data_changed(self) -> None:
        self.dashboard.refresh()

    def closeEvent(self, event) -> None:
        if self.graph_page.worker and self.graph_page.worker.isRunning():
            QMessageBox.information(self, self.i18n.t("knowledge"), self.i18n.t("wait_for_graph"))
            event.ignore()
            return
        self.day_timer.stop()
        self.graph_page.graph_view.save_state()
        self.graph_page.graph_view.state.repository = None
        self.repository.close()
        super().closeEvent(event)
