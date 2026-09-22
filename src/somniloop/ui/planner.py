from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from somniloop.core.dates import display_date

from .controls import RoundedDialog, ScrollDateEdit, link_label, polish_dialog_buttons, show_saved
from .widgets import SmartPlainTextEdit


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()


class PlannerDialog(RoundedDialog):
    def __init__(self, repository, i18n, task=None, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QLineEdit

        self.repository, self.i18n, self.task = repository, i18n, task
        self.setWindowTitle(i18n.t("planner_task"))
        self.resize(620, 490)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.title_edit = QLineEdit(task.title if task else "")
        self.validation_message = QLabel(i18n.t("name_required"))
        self.validation_message.setObjectName("attention")
        self.validation_message.setWordWrap(True)
        self.validation_message.hide()
        self.title_edit.textChanged.connect(lambda: self.validation_message.hide())
        self.date_edit = ScrollDateEdit(
            QDate.fromString(task.due_date, "yyyy-MM-dd") if task else QDate.currentDate()
        )
        self.description_edit = SmartPlainTextEdit(task.description if task else "")
        self.description_edit.setMaximumHeight(90)
        form.addRow(i18n.t("name"), self.title_edit)
        form.addRow("", self.validation_message)
        form.addRow(i18n.t("selected_date"), self.date_edit)
        form.addRow(i18n.t("description"), self.description_edit)
        root.addLayout(form)
        root.addWidget(QLabel(i18n.t("tasks")))
        self.items_edit = SmartPlainTextEdit(
            "\n".join(item["title"] for item in task.items) if task else ""
        )
        self.items_edit.setPlaceholderText(i18n.t("one_task_per_line"))
        root.addWidget(self.items_edit, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("cancel"))
        polish_dialog_buttons(buttons)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _save(self) -> None:
        if not self.title_edit.text().strip():
            self.validation_message.show()
            self.title_edit.setFocus()
            return
        self.repository.save_planner_task(
            self.title_edit.text(),
            self.date_edit.date().toPython(),
            self.description_edit.toPlainText(),
            self.items_edit.toPlainText().splitlines(),
            self.task.id if self.task else None,
        )
        if self.parentWidget():
            show_saved(self.parentWidget(), self.i18n.t("saved"))
        self.accept()


class PlannerColumn(QFrame):
    data_changed = Signal()

    def __init__(self, repository, i18n, parent=None) -> None:
        super().__init__(parent)
        self.repository, self.i18n = repository, i18n
        self.setObjectName("panel")
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel(i18n.t("planner"))
        title.setObjectName("sectionTitle")
        add = QPushButton("+")
        add.setToolTip(i18n.t("new_one_off"))
        add.clicked.connect(self._add)
        header.addWidget(title, 1)
        header.addWidget(add)
        root.addLayout(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.cards = QVBoxLayout(container)
        self.cards.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(container)
        root.addWidget(scroll)
        self.refresh()

    def _add(self) -> None:
        if (
            PlannerDialog(self.repository, self.i18n, parent=self).exec()
            == RoundedDialog.DialogCode.Accepted
        ):
            self._changed()

    def _edit(self, task) -> None:
        if (
            PlannerDialog(self.repository, self.i18n, task, self).exec()
            == RoundedDialog.DialogCode.Accepted
        ):
            self._changed()

    def _changed(self) -> None:
        self.refresh()
        self.data_changed.emit()

    def _complete(self, task_id: int) -> None:
        self.repository.complete_planner_task(task_id)
        self._changed()
        show_saved(self, self.i18n.t("completed_archived"))

    def _set_item(self, item_id: int, checked: bool) -> None:
        self.repository.set_planner_item_done(item_id, checked)
        self._changed()

    def _archive(self, task_id: int) -> None:
        self.repository.archive_planner_task(task_id)
        self._changed()

    def refresh(self) -> None:
        clear_layout(self.cards)
        tasks = self.repository.list_planner_tasks()
        if not tasks:
            empty = QLabel(self.i18n.t("planner_empty"))
            empty.setWordWrap(True)
            empty.setObjectName("muted")
            self.cards.addWidget(empty)
        for task in tasks:
            card = QFrame()
            card.setObjectName("card")
            layout = QVBoxLayout(card)
            title = link_label(task.title)
            title.setObjectName("cardTitle")
            layout.addWidget(title)
            date_label = QLabel(display_date(task.due_date))
            date_label.setObjectName(
                "attention" if date.fromisoformat(task.due_date) < date.today() else "muted"
            )
            layout.addWidget(date_label)
            if task.description:
                layout.addWidget(link_label(task.description))
            for item in task.items:
                row = QHBoxLayout()
                checkbox = QCheckBox()
                checkbox.setChecked(bool(item["done"]))
                checkbox.toggled.connect(
                    lambda checked, item_id=item["id"]: self._set_item(item_id, checked)
                )
                row.addWidget(checkbox)
                row.addWidget(link_label(item["title"]), 1)
                layout.addLayout(row)
            actions = QHBoxLayout()
            edit = QPushButton(self.i18n.t("edit"))
            edit.clicked.connect(lambda checked=False, current=task: self._edit(current))
            archive = QPushButton(self.i18n.t("archive_action"))
            archive.clicked.connect(lambda checked=False, task_id=task.id: self._archive(task_id))
            complete = QPushButton("✓")
            complete.setObjectName("primary")
            complete.setToolTip(self.i18n.t("done"))
            complete.clicked.connect(lambda checked=False, task_id=task.id: self._complete(task_id))
            actions.addWidget(edit)
            actions.addWidget(archive)
            actions.addStretch()
            actions.addWidget(complete)
            layout.addLayout(actions)
            self.cards.addWidget(card)


class ArchiveDialog(RoundedDialog):
    data_changed = Signal()

    def __init__(self, repository, i18n, parent=None) -> None:
        super().__init__(parent)
        self.repository, self.i18n = repository, i18n
        self.setWindowTitle(i18n.t("archive"))
        self.resize(740, 520)
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self._render()

    def _restore(self, kind: str, item_id: int) -> None:
        if kind == "planner":
            self.repository.archive_planner_task(item_id, False)
        else:
            self.repository.archive_tracker(item_id, False)
        self._render()
        self.data_changed.emit()
        show_saved(self, self.i18n.t("restored"))

    def _render(self) -> None:
        selected = max(0, self.tabs.currentIndex())
        while self.tabs.count():
            old = self.tabs.widget(0)
            self.tabs.removeTab(0)
            old.deleteLater()
        groups = (
            ("planner", self.i18n.t("planner"), self.repository.list_planner_tasks(True)),
            (
                "tracker",
                self.i18n.t("habits"),
                [tracker for tracker in self.repository.list_trackers(True) if tracker.archived],
            ),
        )
        for kind, label, items in groups:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            container = QWidget()
            rows = QVBoxLayout(container)
            rows.setAlignment(Qt.AlignmentFlag.AlignTop)
            if not items:
                rows.addWidget(QLabel(self.i18n.t("archive_empty")))
            for item in items:
                frame = QFrame()
                frame.setObjectName("card")
                row = QHBoxLayout(frame)
                row.addWidget(QLabel(item.title if kind == "planner" else item.name), 1)
                restore = QPushButton(self.i18n.t("restore"))
                restore.clicked.connect(
                    lambda checked=False, k=kind, identifier=item.id: self._restore(k, identifier)
                )
                row.addWidget(restore)
                rows.addWidget(frame)
            scroll.setWidget(container)
            self.tabs.addTab(scroll, label)
        self.tabs.setCurrentIndex(selected)


class NotificationDrawer(QFrame):
    count_changed = Signal(int)

    def __init__(self, repository, i18n, parent=None) -> None:
        super().__init__(parent)
        self.repository, self.i18n = repository, i18n
        self.setObjectName("notificationDrawer")
        self.setMaximumHeight(220)
        root = QVBoxLayout(self)
        title = QLabel(i18n.t("birthday_reminders"))
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.rows = QVBoxLayout(container)
        self.rows.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(container)
        root.addWidget(scroll)
        self.refresh()
        self.hide()

    def _dismiss(self, identifier: int) -> None:
        self.repository.dismiss_notification(identifier)
        self.refresh()

    def refresh(self) -> None:
        self.repository.sync_birthday_notifications()
        notifications = self.repository.list_notifications()
        clear_layout(self.rows)
        for notice in notifications:
            frame = QWidget()
            row = QHBoxLayout(frame)
            label = QLabel("🎂  " + notice["title"])
            label.setWordWrap(True)
            row.addWidget(label, 1)
            dismiss = QPushButton(self.i18n.t("dismiss"))
            dismiss.clicked.connect(
                lambda checked=False, identifier=notice["id"]: self._dismiss(identifier)
            )
            row.addWidget(dismiss)
            self.rows.addWidget(frame)
        if not notifications:
            self.rows.addWidget(QLabel(self.i18n.t("notifications_empty")))
        self.count_changed.emit(len(notifications))
