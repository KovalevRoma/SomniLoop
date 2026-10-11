from __future__ import annotations

from datetime import date

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from somniloop.core.dates import birthday_in_year, display_date

from .activity_scrollbar import ActivityScrollBar
from .controls import RoundedDialog, link_label, polish_dialog_buttons, show_saved
from .rich_text import RichTextEditor, RichTextView
from .task_date_picker import TaskDateField
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
        self.setWindowTitle(("Изменить задачу" if task else "Новая задача") if i18n.language == "ru" else ("Edit task" if task else "New task"))
        self.setObjectName("taskEditor")
        self.resize(620, 440)
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.title_edit = QLineEdit(task.title if task else "")
        self.title_edit.setPlaceholderText("Название задачи" if i18n.language == "ru" else "Task title")
        self.validation_message = QLabel(i18n.t("name_required"))
        self.validation_message.setObjectName("attention")
        self.validation_message.setWordWrap(True)
        self.validation_message.hide()
        self.title_edit.textChanged.connect(lambda: self.validation_message.hide())
        self.date_field = TaskDateField(i18n.language, task.due_date if task else "",
                                        task.due_time if task else "")
        self.description_edit = RichTextEditor(task.description if task else "")
        self.legacy_images = []
        for name, data in repository.task_images(task.id) if task else []:
            try:
                self.description_edit.active.moveCursor(QTextCursor.MoveOperation.End)
                self.description_edit.insert_image(data)
            except ValueError:
                self.legacy_images.append((name, data))
        self.description_edit.setMinimumHeight(300)
        self.description_edit.setMaximumHeight(360)
        form.addRow(i18n.t("name"), self.title_edit)
        form.addRow("", self.validation_message)
        form.addRow("Срок" if i18n.language == "ru" else "Date", self.date_field)
        form.addRow(i18n.t("description"), self.description_edit)
        self.project = QComboBox()
        self.project.addItem("Без проекта" if i18n.language == "ru" else "No project", None)
        for project in repository.work_projects(True):
            self.project.addItem(project["name"], project["id"])
        self.work_values = repository.work_metadata().get(("planner", task.id), {}) if task else {}
        self.project.setCurrentIndex(max(0, self.project.findData(self.work_values.get("project_id"))))
        self.date_field.project_days_provider = lambda: repository.project_calendar_days(
            self.project.currentData()
        )
        form.addRow("Проект" if i18n.language == "ru" else "Project", self.project)
        form.setVerticalSpacing(12)
        root.addLayout(form)
        self.has_items = QCheckBox("Добавить подпункты" if i18n.language == "ru" else "Add checklist")
        self.has_items.setChecked(bool(task and task.items))
        root.addWidget(self.has_items)
        self.items_edit = SmartPlainTextEdit(
            "\n".join(item["title"] for item in task.items) if task else ""
        )
        self.items_edit.setPlaceholderText(i18n.t("one_task_per_line"))
        root.addWidget(self.items_edit, 1)
        self.items_edit.setVisible(self.has_items.isChecked())
        self.has_items.toggled.connect(self.items_edit.setVisible)
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
        self.saved_task_id = self.repository.save_planner_task(
            self.title_edit.text(),
            date.fromisoformat(self.date_field.day) if self.date_field.day else None,
            self.description_edit.source(),
            self.items_edit.toPlainText().splitlines() if self.has_items.isChecked() else [],
            self.task.id if self.task else None,
            due_time=self.date_field.clock if self.date_field.day else "",
        )
        self.repository.save_work_item("planner", self.saved_task_id,
                                       project_id=self.project.currentData(),
                                       priority=self.work_values.get("priority", 0),
                                       planned_on=self.work_values.get("planned_on", ""),
                                       next_action=self.work_values.get("next_action", ""))
        self.repository.save_task_images(self.saved_task_id, self.legacy_images)
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
            date_label = QLabel(display_date(task.due_date) + (" · " + task.due_time if task.due_time else ""))
            date_label.setObjectName(
                "attention" if task.due_date and date.fromisoformat(task.due_date) < date.today() else "muted"
            )
            layout.addWidget(date_label)
            if task.description:
                layout.addWidget(RichTextView(task.description))
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
        self.anchor = None
        self.repository, self.i18n = repository, i18n
        self.setObjectName("notificationDrawer")
        self.setFixedSize(420, 360)
        root = QVBoxLayout(self)
        title = QLabel(i18n.t("birthday_reminders"))
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBar(ActivityScrollBar(self.list))
        root.addWidget(self.list)
        self.refresh()
        self.hide()

    def toggle_at(self, anchor):
        if self.isVisible():
            self.hide()
            return
        self.refresh()
        self.anchor = anchor
        if self.parentWidget() is not anchor.window():
            self.setParent(anchor.window())
        point = anchor.mapTo(self.parentWidget(), QPoint(anchor.width() - self.width(), anchor.height() + 6))
        point.setX(max(0, min(point.x(), self.parentWidget().width() - self.width())))
        point.setY(max(0, min(point.y(), self.parentWidget().height() - self.height())))
        self.move(point)
        self.show()
        self.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.hide()
            return True
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            if watched is not self and not self.isAncestorOf(watched) and watched is not self.anchor:
                self.hide()
        if watched is self.parentWidget() and event.type() in (QEvent.Type.Resize, QEvent.Type.Close):
            self.hide()
        return False

    def refresh(self) -> None:
        from somniloop.knowledge.people import has_birth_conflict

        today = date.today()
        upcoming = []
        for person in self.repository.list_people():
            if has_birth_conflict({"conflicts": person.conflicts}):
                continue
            birthday = birthday_in_year(person.birth_date, today.year)
            if birthday is not None and birthday < today:
                birthday = birthday_in_year(person.birth_date, today.year + 1)
            if birthday is not None:
                upcoming.append((birthday, person.name))
        upcoming.sort(key=lambda item: (item[0], item[1].casefold()))
        self.list.clear()
        for birthday, name in upcoming:
            delta = (birthday - today).days
            when = ("Сегодня" if self.i18n.language == "ru" else "Today") if delta == 0 else display_date(birthday)
            item = QListWidgetItem(f"♛  {name}\n{when}")
            item.setToolTip(f"{name}\n{when}")
            item.setSizeHint(QSize(0, self.list.fontMetrics().height() * 2 + 20))
            self.list.addItem(item)
        if not upcoming:
            self.list.addItem(self.i18n.t("notifications_empty"))
        self.count_changed.emit(sum((birthday - today).days <= 30 for birthday, _ in upcoming))
