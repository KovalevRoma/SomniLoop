from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from somniloop.core.database import Repository
from somniloop.core.dates import display_date
from somniloop.core.i18n import I18n
from somniloop.core.models import DayStatus, DayTask, ScheduleType, TaskState

from .calendar_widgets import RoundCalendar
from .controls import RoundedDialog as QDialog
from .controls import link_label, polish_dialog_buttons
from .widgets import StateSelector

STATUS_COLORS = {
    DayStatus.DONE: ("#286f55", "#f2fff9"),
    DayStatus.PARTIAL: ("#8a6d24", "#fff9df"),
    DayStatus.MISSED: ("#81394a", "#fff0f3"),
}


class DayEditorDialog(QDialog):
    changed = Signal()

    def __init__(
        self,
        repository: Repository,
        tracker_id: int,
        day: date,
        i18n: I18n,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.tracker = repository.get_tracker(tracker_id)
        self.day = day
        self.i18n = i18n
        self.setWindowTitle(display_date(day))
        self.setMinimumWidth(620)
        root = QVBoxLayout(self)
        self.status_label = QLabel()
        self.status_label.setObjectName("sectionTitle")
        root.addWidget(self.status_label)
        self.tasks_layout = QVBoxLayout()
        root.addLayout(self.tasks_layout)
        self._build_tasks()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(i18n.t("close"))
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _summary_for_edit(self):
        summary = self.repository.day_summary(self.tracker, self.day)
        if self.tracker.schedule_type == ScheduleType.WEEKLY_QUOTA and not summary.tasks:
            return [
                DayTask(task, TaskState.UNSET)
                for task in self.repository.list_tasks(self.tracker.id)
            ]
        return summary.tasks

    def _build_tasks(self) -> None:
        tasks = self._summary_for_edit()
        if not tasks:
            message = QLabel(self.i18n.t("not_scheduled"))
            message.setObjectName("muted")
            self.tasks_layout.addWidget(message)
        for day_task in tasks:
            frame = QFrame()
            frame.setObjectName("card")
            row = QHBoxLayout(frame)
            name = link_label(day_task.task.name)
            name.setObjectName("cardTitle")
            selector = StateSelector(self.i18n, day_task.state)
            selector.state_changed.connect(
                lambda state, task_id=day_task.task.id: self._set_state(task_id, state)
            )
            row.addWidget(name, 1)
            row.addWidget(selector)
            self.tasks_layout.addWidget(frame)
        self._refresh_status()

    def _set_state(self, task_id: int, state: TaskState) -> None:
        self.repository.set_task_state(self.tracker.id, task_id, self.day, state)
        self._refresh_status()
        self.changed.emit()

    def _refresh_status(self) -> None:
        summary = self.repository.day_summary(self.tracker, self.day)
        label_key = {
            DayStatus.DONE: "done",
            DayStatus.PARTIAL: "partial",
            DayStatus.MISSED: "missed",
            DayStatus.UNSET: "unset",
            DayStatus.UNSCHEDULED: "unset",
        }[summary.status]
        self.status_label.setText(self.i18n.t(label_key))


class CalendarDialog(QDialog):
    data_changed = Signal()

    def __init__(self, repository: Repository, tracker_id: int, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.tracker_id = tracker_id
        self.i18n = i18n
        tracker = repository.get_tracker(tracker_id)
        self.setWindowTitle(f"{i18n.t('calendar')} — {tracker.name}")
        self.setMinimumSize(520, 460)
        root = QVBoxLayout(self)
        self.calendar = RoundCalendar()
        self.calendar.currentPageChanged.connect(self._paint_month)
        self.calendar.clicked.connect(self._edit_day)
        root.addWidget(self.calendar, 1)

        legend = QHBoxLayout()
        for key, status in (
            ("done", DayStatus.DONE),
            ("partial", DayStatus.PARTIAL),
            ("missed", DayStatus.MISSED),
        ):
            dot = QLabel("● " + i18n.t(key))
            dot.setStyleSheet(f"color: {STATUS_COLORS[status][0]};")
            legend.addWidget(dot)
        legend.addStretch()
        root.addLayout(legend)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(i18n.t("close"))
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._paint_month(self.calendar.yearShown(), self.calendar.monthShown())

    def _paint_month(self, year: int, month: int) -> None:
        first = date(year, month, 1)
        first -= timedelta(days=first.weekday())
        last = first + timedelta(days=41)
        statuses = self.repository.calendar_statuses(self.tracker_id, first, last)
        self.calendar.set_statuses(statuses)

    def _edit_day(self, qdate: QDate) -> None:
        day = date(qdate.year(), qdate.month(), qdate.day())
        dialog = DayEditorDialog(self.repository, self.tracker_id, day, self.i18n, self)
        dialog.changed.connect(self._child_changed)
        dialog.exec()

    def _child_changed(self) -> None:
        self._paint_month(self.calendar.yearShown(), self.calendar.monthShown())
        self.data_changed.emit()
