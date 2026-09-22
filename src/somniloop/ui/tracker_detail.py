from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from somniloop.core.database import Repository
from somniloop.core.dates import display_date
from somniloop.core.i18n import I18n
from somniloop.core.models import DayTask, ScheduleType, TaskState, TrackerMode

from .calendar_dialog import CalendarDialog
from .controls import RoundedDialog as QDialog
from .controls import ScrollDateEdit as QDateEdit
from .controls import link_label, linked_text, polish_dialog_buttons, show_saved
from .dialogs import EditTrackerDialog, TaskEditDialog
from .widgets import SmartPlainTextEdit, StateSelector


class TrackerDetailDialog(QDialog):
    data_changed = Signal()
    tracker_deleted = Signal()

    def __init__(self, repository: Repository, tracker_id: int, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.tracker_id = tracker_id
        self.i18n = i18n
        self.tracker = repository.get_tracker(tracker_id)
        self.setWindowTitle(self.tracker.name)
        self.resize(850, 680)
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        self.title_label = QLabel(self.tracker.name)
        self.title_label.setObjectName("pageTitle")
        edit = QPushButton(i18n.t("edit"))
        edit.clicked.connect(self._edit_tracker)
        calendar_button = QPushButton(i18n.t("calendar"))
        calendar_button.clicked.connect(self._calendar)
        delete = QPushButton(i18n.t("delete_tracker"))
        delete.setObjectName("danger")
        delete.clicked.connect(self._delete_tracker)
        archive = QPushButton(i18n.t("archive_action"))
        archive.clicked.connect(self._archive_tracker)
        header.addWidget(self.title_label, 1)
        header.addWidget(edit)
        header.addWidget(calendar_button)
        header.addWidget(archive)
        header.addWidget(delete)
        root.addLayout(header)
        self.description_label = link_label(self.tracker.description)
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName("muted")
        root.addWidget(self.description_label)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel(i18n.t("selected_date")))
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.dateChanged.connect(self._render_day)
        date_row.addWidget(self.date_edit)
        date_row.addStretch()
        root.addLayout(date_row)

        if self.tracker.mode == TrackerMode.MANUAL:
            manual_frame = QFrame()
            manual_frame.setObjectName("panel")
            manual_layout = QVBoxLayout(manual_frame)
            manual_title = QLabel(i18n.t("manual_dates"))
            manual_title.setObjectName("sectionTitle")
            manual_layout.addWidget(manual_title)
            self.manual_dates_list = QListWidget()
            self.manual_dates_list.setMaximumHeight(115)
            self.manual_dates_list.itemClicked.connect(
                lambda item: self.date_edit.setDate(
                    QDate.fromString(item.data(Qt.ItemDataRole.UserRole).isoformat(), "yyyy-MM-dd")
                )
            )
            buttons = QHBoxLayout()
            add_date = QPushButton(i18n.t("add_date"))
            add_date.clicked.connect(self._add_manual_date)
            remove_date = QPushButton(i18n.t("remove_date"))
            remove_date.clicked.connect(self._remove_manual_date)
            buttons.addWidget(add_date)
            buttons.addWidget(remove_date)
            buttons.addStretch()
            manual_layout.addWidget(self.manual_dates_list)
            manual_layout.addLayout(buttons)
            root.addWidget(manual_frame)
            self._load_manual_dates()

        task_header = QHBoxLayout()
        task_title = QLabel(i18n.t("tasks"))
        task_title.setObjectName("sectionTitle")
        add_task = QPushButton(i18n.t("add_task"))
        add_task.clicked.connect(self._add_task)
        task_header.addWidget(task_title)
        task_header.addStretch()
        task_header.addWidget(add_task)
        root.addLayout(task_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.tasks_container = QWidget()
        self.tasks_layout = QVBoxLayout(self.tasks_container)
        self.tasks_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.tasks_container)
        root.addWidget(scroll, 1)
        self._render_day()

    def _selected_day(self) -> date:
        qday = self.date_edit.date()
        return date(qday.year(), qday.month(), qday.day())

    def _clear_tasks(self) -> None:
        while self.tasks_layout.count():
            item = self.tasks_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _tasks_for_edit(self) -> list[DayTask]:
        day = self._selected_day()
        summary = self.repository.day_summary(self.tracker, day)
        if self.tracker.schedule_type == ScheduleType.WEEKLY_QUOTA and not summary.tasks:
            return [
                DayTask(task, TaskState.UNSET)
                for task in self.repository.list_tasks(self.tracker.id)
            ]
        return summary.tasks

    def _render_day(self) -> None:
        self._clear_tasks()
        tasks = self._tasks_for_edit()
        if not tasks and self.tracker.schedule_type == ScheduleType.ITEM_DATES:
            collection_tasks = self.repository.list_tasks(self.tracker_id)
            for task in collection_tasks:
                frame = QFrame()
                frame.setObjectName("card")
                row = QHBoxLayout(frame)
                name = link_label(task.name)
                name.setObjectName("cardTitle")
                if task.schedule_type == ScheduleType.YEARLY:
                    schedule = display_date(
                        f"--{int(task.schedule.get('month', 1)):02d}-{int(task.schedule.get('day', 1)):02d}"
                    )
                elif task.schedule_type == ScheduleType.MONTHLY:
                    schedule = self.i18n.t("monthly", day=task.schedule.get("day", 1))
                else:
                    schedule = self.i18n.t("unset")
                schedule_label = QLabel(schedule)
                schedule_label.setObjectName("muted")
                edit = QPushButton(self.i18n.t("edit"))
                edit.clicked.connect(lambda checked=False, current=task: self._edit_task(current))
                remove = QPushButton("×")
                remove.setObjectName("danger")
                remove.clicked.connect(
                    lambda checked=False, task_id=task.id: self._delete_task(task_id)
                )
                row.addWidget(name, 1)
                row.addWidget(schedule_label)
                row.addWidget(edit)
                row.addWidget(remove)
                self.tasks_layout.addWidget(frame)
            if collection_tasks:
                return
        if not tasks:
            label = QLabel(self.i18n.t("not_scheduled"))
            label.setObjectName("muted")
            self.tasks_layout.addWidget(label)
        for day_task in tasks:
            frame = QFrame()
            frame.setObjectName("card")
            layout = QVBoxLayout(frame)
            top = QHBoxLayout()
            name = link_label(day_task.task.name)
            name.setObjectName("cardTitle")
            edit = QPushButton(self.i18n.t("edit"))
            edit.clicked.connect(lambda checked=False, task=day_task.task: self._edit_task(task))
            remove = QPushButton("×")
            remove.setObjectName("danger")
            remove.clicked.connect(
                lambda checked=False, task_id=day_task.task.id: self._delete_task(task_id)
            )
            top.addWidget(name, 1)
            top.addWidget(edit)
            top.addWidget(remove)
            layout.addLayout(top)
            if day_task.task.details and self.tracker.mode != TrackerMode.MANUAL:
                details = link_label(day_task.task.details)
                details.setObjectName("muted")
                details.setWordWrap(True)
                layout.addWidget(details)
            selector = StateSelector(self.i18n, day_task.state)
            selector.state_changed.connect(
                lambda state, task_id=day_task.task.id: self._set_state(task_id, state)
            )
            layout.addWidget(selector)
            self.tasks_layout.addWidget(frame)

    def _set_state(self, task_id: int, state: TaskState) -> None:
        self.repository.set_task_state(self.tracker_id, task_id, self._selected_day(), state)
        self.data_changed.emit()

    def _add_task(self) -> None:
        collection = self.tracker.schedule_type == ScheduleType.ITEM_DATES
        manual = self.tracker.mode == TrackerMode.MANUAL
        if manual and self._selected_day() not in self.repository.list_manual_dates(
            self.tracker_id
        ):
            QMessageBox.information(
                self, self.i18n.t("add_task"), self.i18n.t("choose_scheduled_date")
            )
            return
        dialog = TaskEditDialog(self.i18n, collection, parent=self, allow_details=not manual)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.repository.add_task(
            self.tracker_id,
            *dialog.values(),
            occurrence_date=self._selected_day() if manual else None,
        )
        self._render_day()
        self.data_changed.emit()
        show_saved(self, self.i18n.t("saved"))

    def _edit_task(self, task) -> None:
        collection = self.tracker.schedule_type == ScheduleType.ITEM_DATES
        dialog = TaskEditDialog(
            self.i18n, collection, task, self, allow_details=self.tracker.mode != TrackerMode.MANUAL
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.repository.update_task(task.id, *dialog.values())
        self._render_day()
        self.data_changed.emit()
        show_saved(self, self.i18n.t("saved"))

    def _delete_task(self, task_id: int) -> None:
        if (
            QMessageBox.question(self, self.i18n.t("delete"), self.i18n.t("delete"))
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.repository.delete_task(task_id)
        self._render_day()
        self.data_changed.emit()

    def _load_manual_dates(self) -> None:
        self.manual_dates_list.clear()
        for day in self.repository.list_manual_dates(self.tracker_id):
            item = QListWidgetItem(display_date(day))
            item.setData(Qt.ItemDataRole.UserRole, day)
            self.manual_dates_list.addItem(item)

    def _add_manual_date(self) -> None:
        picker = QDateEdit(QDate.currentDate(), self)
        picker.setCalendarPopup(True)
        dialog = QDialog(self)
        dialog.setWindowTitle(self.i18n.t("choose_date"))
        layout = QVBoxLayout(dialog)
        layout.addWidget(picker)
        layout.addWidget(QLabel(self.i18n.t("date_subtasks")))
        tasks_edit = SmartPlainTextEdit()
        tasks_edit.setPlaceholderText(self.i18n.t("one_task_per_line"))
        layout.addWidget(tasks_edit)
        dialog.resize(520, 350)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(self.i18n.t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.i18n.t("cancel"))
        polish_dialog_buttons(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        qday = picker.date()
        day = date(qday.year(), qday.month(), qday.day())
        task_names = [name for name in tasks_edit.toPlainText().splitlines() if name.strip()]
        common_tasks = [
            task
            for task in self.repository.list_tasks(self.tracker_id)
            if task.occurrence_date is None
        ]
        if not task_names and not common_tasks:
            QMessageBox.information(
                self, self.i18n.t("add_date"), self.i18n.t("manual_task_required")
            )
            return
        if not self.repository.add_manual_occurrence(self.tracker_id, day, task_names):
            QMessageBox.information(self, self.i18n.t("add_date"), self.i18n.t("date_exists"))
            return
        self._load_manual_dates()
        self.date_edit.setDate(qday)
        self._render_day()
        self.data_changed.emit()
        show_saved(self, self.i18n.t("saved"))

    def _remove_manual_date(self) -> None:
        item = self.manual_dates_list.currentItem()
        if item is None:
            return
        if (
            QMessageBox.question(
                self, self.i18n.t("remove_date"), self.i18n.t("remove_date_confirm")
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.repository.remove_manual_date(self.tracker_id, item.data(Qt.ItemDataRole.UserRole))
        self._load_manual_dates()
        self._render_day()
        self.data_changed.emit()

    def _archive_tracker(self) -> None:
        self.repository.archive_tracker(self.tracker_id)
        self.data_changed.emit()
        self.accept()

    def _edit_tracker(self) -> None:
        dialog = EditTrackerDialog(self.i18n, self.tracker, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.repository.update_tracker(
            self.tracker_id,
            values["name"],
            values["description"],
            values["schedule_type"],
            values["schedule"],
        )
        self.tracker = self.repository.get_tracker(self.tracker_id)
        self.title_label.setText(self.tracker.name)
        self.description_label.setText(linked_text(self.tracker.description))
        self.setWindowTitle(self.tracker.name)
        self._render_day()
        self.data_changed.emit()
        show_saved(self, self.i18n.t("saved"))

    def _calendar(self) -> None:
        dialog = CalendarDialog(self.repository, self.tracker_id, self.i18n, self)
        dialog.data_changed.connect(lambda: (self._render_day(), self.data_changed.emit()))
        dialog.exec()

    def _delete_tracker(self) -> None:
        if (
            QMessageBox.question(
                self,
                self.i18n.t("delete_tracker"),
                self.i18n.t("confirm_delete", name=self.tracker.name),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.repository.delete_tracker(self.tracker_id)
        self.tracker_deleted.emit()
        self.accept()
