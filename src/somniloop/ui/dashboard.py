"""Daily workspace with one scroll surface and incremental, keyed widget updates."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from somniloop.core.models import TaskState, TrackerMode

from .activity_scrollbar import ActivityScrollBar
from .dashboard_cards import TrackerCard, WrapLabel
from .dashboard_data import DashboardData, local_date
from .dashboard_sections import DashboardFilters, PlannerAgenda, TodayBlock
from .planner import PlannerDialog


class ResponsiveColumns(QWidget):
    """Preserve widget identity when changing between equal columns and a stack."""

    def __init__(self, primary, secondary):
        super().__init__()
        self.setObjectName("flat")
        self.primary, self.secondary = primary, secondary
        self.wide = None
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(16)
        self._arrange(False)

    def _arrange(self, wide):
        if wide == self.wide:
            return
        self.wide = wide
        self.grid.removeWidget(self.primary)
        self.grid.removeWidget(self.secondary)
        self.grid.addWidget(self.primary, 0, 0, alignment=Qt.AlignmentFlag.AlignTop)
        self.grid.addWidget(
            self.secondary, 0 if wide else 1, 1 if wide else 0, alignment=Qt.AlignmentFlag.AlignTop
        )
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1 if wide else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange(self.width() >= 900)


class Dashboard(QWidget):
    data_changed = Signal()
    new_requested = Signal()
    create_requested = Signal(str)
    open_requested = Signal(int)
    edit_requested = Signal(int)
    calendar_requested = Signal(int)
    archive_requested = Signal()

    def __init__(self, repository, i18n, parent=None):
        super().__init__(parent)
        self.repository, self.i18n = repository, i18n
        self.setObjectName("dashboard")
        self.data = DashboardData(repository)
        self.cards = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setVerticalScrollBar(ActivityScrollBar(self.scroll))
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll)
        self.container = QWidget()
        self.container.setMinimumWidth(0)
        self.container.setObjectName("dashboardSurface")
        self.container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QHBoxLayout(self.container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.body = QWidget()
        self.body.setObjectName("flat")
        self.body.setMaximumWidth(1680)
        self.body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addStretch(1)
        outer.addWidget(self.body, 1000, Qt.AlignmentFlag.AlignTop)
        outer.addStretch(1)
        content = QVBoxLayout(self.body)
        content.setContentsMargins(8, 8, 8, 12)
        content.setSpacing(12)
        header = QHBoxLayout()
        self.date_label = QLabel()
        self.date_label.setObjectName("dashboardDate")
        self.date_label.setWordWrap(True)
        header.addWidget(self.date_label, 1)
        self.add = QPushButton("+ " + i18n.t("home_add"))
        self.add.setObjectName("primary")
        menu = QMenu(self.add)
        for kind, title_key in (
            ("habit", "home_habit"),
            ("plan", "home_plan"),
            ("task", "planner_task"),
        ):
            menu.addAction(i18n.t(title_key), lambda key=kind: self._create(key))
        self.add.setMenu(menu)
        header.addWidget(self.add)
        content.addLayout(header)
        self.today = TodayBlock(repository, i18n)
        self.today.tracker_changed.connect(self._tracker_changed)
        self.today.planner_changed.connect(self._planner_changed)
        self.today.edit_planner.connect(self._edit_planner)
        content.addWidget(self.today)
        self.library = QFrame()
        self.library.setObjectName("panel")
        self.library.setMinimumWidth(0)
        library_layout = QVBoxLayout(self.library)
        library_layout.setContentsMargins(12, 12, 12, 12)
        library_layout.setSpacing(8)
        title = QLabel(i18n.t("home_library"))
        title.setObjectName("sectionTitle")
        library_layout.addWidget(title)
        self.filters = DashboardFilters(i18n)
        self.filters.changed.connect(self._render_library)
        library_layout.addWidget(self.filters)
        self.empty = WrapLabel(i18n.t("home_empty"))
        self.empty.setObjectName("muted")
        library_layout.addWidget(self.empty)
        self.card_layout = QVBoxLayout()
        self.card_layout.setSpacing(8)
        library_layout.addLayout(self.card_layout)
        self.planner = PlannerAgenda(repository, i18n)
        self.planner.changed.connect(self._planner_changed)
        self.planner.edit_requested.connect(self._edit_planner)
        self.planner.open_plan.connect(self.open_requested)
        self.planner.edit_plan.connect(self.edit_requested)
        self.planner.calendar_plan.connect(self.calendar_requested)
        self.planner.plan_changed.connect(self._tracker_changed)
        self.columns = ResponsiveColumns(self.library, self.planner)
        content.addWidget(self.columns)
        self.scroll.setWidget(self.container)
        self.refresh()

    def _create(self, kind):
        if kind == "task":
            self._edit_planner(None)
        else:
            self.create_requested.emit(kind)

    def _edit_planner(self, task):
        dialog = PlannerDialog(self.repository, self.i18n, task, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self._planner_changed()

    def _tracker_changed(self, identifier):
        self.refresh(changed_tracker=identifier)
        self.data_changed.emit()

    def _planner_changed(self):
        self.refresh(planner_only=True)
        self.data_changed.emit()

    def _quick_changed(self):
        self.refresh()

    def refresh(self, changed_tracker=None, planner_only=False):
        self.data.refresh(changed_tracker, planner_only)
        self.date_label.setText(local_date(self.data.today, self.i18n, full=True))
        self.today.set_data(self.data)
        self.planner.set_tasks(
            self.data.planner,
            [record for record in self.data.trackers.values() if record.tracker.mode == TrackerMode.MANUAL],
        )
        self._render_library()

    def _render_library(self):
        records = self.data.filtered(
            "regular", self.filters.search.text(), self.filters.order.currentData()
        )
        before_hiding = records
        if self.filters.hide_done.isChecked():
            records = [record for record in records if not (
                bool(record.tasks) and all(item.state == TaskState.DONE for item in record.tasks)
                or record.meta.quota_target is not None
                and (record.meta.quota_done or 0) >= record.meta.quota_target
            )]
        visible = {record.tracker.id for record in records}
        for identifier in list(self.cards):
            card = self.cards[identifier]
            if identifier not in self.data.trackers:
                self.card_layout.removeWidget(card)
                card.hide()
                card.deleteLater()
                del self.cards[identifier]
            elif identifier not in visible:
                self.card_layout.removeWidget(card)
                card.hide()
        self.empty.setVisible(not records)
        self.empty.setText(self.i18n.t(
            "home_all_done" if before_hiding and not records else
            "home_no_matches" if self.filters.search.text() else "home_empty"
        ))
        for position, record in enumerate(records):
            identifier = record.tracker.id
            card = self.cards.get(identifier)
            if card is None:
                card = TrackerCard(
                    self.repository, record.tracker, self.i18n, self.library, snapshot=record
                )
                card.open_requested.connect(self.open_requested)
                card.edit_requested.connect(self.edit_requested)
                card.calendar_requested.connect(self.calendar_requested)
                card.tracker_changed.connect(self._tracker_changed)
                self.cards[identifier] = card
            card.update_snapshot(record, self.filters.hide_done.isChecked())
            card.set_compact(bool(record.occurrences))
            card.show()
            if self.card_layout.indexOf(card) != position:
                self.card_layout.insertWidget(position, card)
