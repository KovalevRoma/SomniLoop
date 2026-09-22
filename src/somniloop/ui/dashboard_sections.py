"""Today's unified queue, reusable library filters and the compact upcoming agenda."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from somniloop.core.models import TaskState, TrackerMode

from .dashboard_cards import PlannerCard, TaskRows, VisibleCheckBox, WrapLabel
from .dashboard_data import local_date


class DashboardFilters(QFrame):
    changed = Signal()

    def __init__(self, i18n):
        super().__init__()
        self.setObjectName("flat")
        self.category = "all"
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        categories = QHBoxLayout()
        categories.setSpacing(8)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for key, title in (
            ("all", "all"),
            ("regular", "regular_trackers"),
            ("manual", "home_date_plans"),
        ):
            button = QPushButton(i18n.t(title))
            button.setCheckable(True)
            button.setChecked(key == "all")
            button.clicked.connect(lambda checked=False, value=key: self._category(value))
            self.group.addButton(button)
            self.buttons[key] = button
            categories.addWidget(button)
        categories.addStretch()
        root.addLayout(categories)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText(i18n.t("home_search"))
        self.search.setAccessibleName(i18n.t("home_search"))
        self.search.textChanged.connect(self.changed)
        row = QHBoxLayout()
        row.addWidget(self.search, 1)
        self.order = QComboBox()
        self.order.setAccessibleName(i18n.t("home_sort"))
        for key in ("attention", "date", "streak", "name"):
            self.order.addItem(i18n.t("home_sort_" + key), key)
        self.order.currentIndexChanged.connect(self.changed)
        self.hide_done = VisibleCheckBox(i18n.t("home_hide_done"))
        self.hide_done.toggled.connect(self.changed)
        row.addWidget(self.order, 1)
        row.addWidget(self.hide_done)
        root.addLayout(row)

    def _category(self, value):
        self.category = value
        self.changed.emit()


class TodayOccurrence(QFrame):
    changed = Signal(int)

    def __init__(self, repository, record, day, items, i18n, parent=None):
        super().__init__(parent)
        self.repository, self.i18n, self.tracker_id, self.day = (
            repository,
            i18n,
            record.tracker.id,
            day,
        )
        self.setObjectName("card")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        self.title = WrapLabel()
        self.title.setObjectName("cardTitle")
        self.caption = WrapLabel()
        self.caption.setObjectName("muted")
        heading = QHBoxLayout()
        heading.addWidget(self.title, 2)
        heading.addWidget(self.caption, 1)
        root.addLayout(heading)
        self.rows = TaskRows(i18n)
        self.rows.changed.connect(self._mark)
        root.addWidget(self.rows)
        self._signature = None
        self.update_occurrence(record, items, False)

    def update_occurrence(self, record, items, hide_done):
        signature = (record.tracker.name, record.tracker.mode, items, hide_done)
        if self._signature == signature:
            return
        self._signature = signature
        self.title.setText(record.tracker.name)
        caption = self.i18n.t(
            "home_habit" if record.tracker.mode == TrackerMode.REGULAR else "home_plan"
        )
        overdue = self.day < date.today()
        if overdue:
            caption += " · " + self.i18n.t("home_overdue", date=local_date(self.day, self.i18n))
        self.caption.setText(caption)
        accent = (
            "#bd7981"
            if overdue
            else "#7f6ac6"
            if record.tracker.mode == TrackerMode.REGULAR
            else "#538ebd"
        )
        self.setStyleSheet(f"QFrame#card {{ border-left: 3px solid {accent}; }}")
        self.rows.update_rows(
            [(item.task.id, item.task.name, item.state) for item in items], hide_done
        )

    def _mark(self, identifier, state):
        self.repository.set_task_state(self.tracker_id, identifier, self.day, state)
        self.changed.emit(self.tracker_id)


class TodayBlock(QFrame):
    tracker_changed = Signal(int)
    planner_changed = Signal()
    edit_planner = Signal(object)

    def __init__(self, repository, i18n):
        super().__init__()
        self.repository, self.i18n = repository, i18n
        self.setObjectName("panel")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel(i18n.t("today"))
        title.setObjectName("sectionTitle")
        header.addWidget(title, 1)
        self.counter = QLabel()
        self.counter.setObjectName("muted")
        header.addWidget(self.counter)
        self.hide_done = VisibleCheckBox(i18n.t("home_hide_done"))
        self.hide_done.setChecked(True)
        self.hide_done.toggled.connect(lambda: self.set_data(self.data) if self.data else None)
        header.addWidget(self.hide_done)
        root.addLayout(header)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setMinimumHeight(4)
        self.progress.setStyleSheet(
            "QProgressBar {border:0; min-height:4px; max-height:4px; padding:0; border-radius:2px; background:#51576a;} QProgressBar::chunk {background:#9082cf; border-radius:2px;}"
        )
        root.addWidget(self.progress)
        self.empty = WrapLabel(i18n.t("home_today_empty"))
        self.empty.setObjectName("muted")
        root.addWidget(self.empty)
        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        root.addLayout(self.grid)
        self.more = QPushButton(i18n.t("home_more"))
        self.more.clicked.connect(self._more)
        root.addWidget(self.more)
        self.limit = 6
        self.widgets = {}
        self.visible_keys = []
        self.data = None
        self.columns = 1

    def _more(self):
        self.limit += 6
        self.set_data(self.data)

    def set_data(self, data):
        self.data = data
        hide = self.hide_done.isChecked()
        definitions, states = [], []
        for record in data.filtered(order="attention"):
            for day, items in record.occurrences:
                states.extend(item.state for item in items)
                definitions.append((("tracker", record.tracker.id, day), record, day, items))
        for task in [*data.planner, *data.completed]:
            if date.fromisoformat(task.due_date) > data.today:
                continue
            states.extend(
                [
                    TaskState.DONE if item["done"] else TaskState(item.get("state", "unset"))
                    for item in task.items
                ]
                or [task.state]
            )
            definitions.append((("planner", task.id), task, None, None))
        definitions.sort(
            key=lambda item: (
                item[2] if item[2] else date.fromisoformat(item[1].due_date),
                0 if item[0][0] == "planner" else 1,
                item[1].tracker.name.casefold() if item[2] else item[1].title.casefold(),
            )
        )
        done = sum(state == TaskState.DONE for state in states)
        self.counter.setText(self.i18n.t("home_progress", done=done, total=len(states)))
        partial = sum(state == TaskState.PARTIAL for state in states)
        if partial:
            self.counter.setText(
                self.counter.text() + " · " + self.i18n.t("home_partial_count", count=partial)
            )
        self.progress.setRange(0, max(1, len(states)))
        self.progress.setValue(done)
        self.progress.setVisible(bool(states))
        visible = []
        wanted = set()
        for key, record, day, items in definitions:
            completed = (
                all(item.state == TaskState.DONE for item in items)
                if items is not None
                else record.completed
            )
            if hide and completed:
                continue
            visible.append((key, record, day, items))
        self.more.setVisible(len(visible) > self.limit)
        for key, record, day, items in visible[: self.limit]:
            wanted.add(key)
            widget = self.widgets.get(key)
            if widget is None:
                if items is not None:
                    widget = TodayOccurrence(self.repository, record, day, items, self.i18n, self)
                    widget.changed.connect(self.tracker_changed)
                else:
                    widget = PlannerCard(self.repository, record, self.i18n, self)
                    widget.changed.connect(self.planner_changed)
                    widget.edit_requested.connect(self.edit_planner)
                self.widgets[key] = widget
            if items is not None:
                widget.update_occurrence(record, items, hide)
            else:
                widget.update_task(record, hide)
            widget.show()
        for key, widget in self.widgets.items():
            if key not in wanted:
                self.grid.removeWidget(widget)
                widget.hide()
        self.visible_keys = [key for key, *_ in visible[: self.limit]]
        self._arrange()
        self.empty.setVisible(not visible)
        self.empty.setText(
            self.i18n.t("home_all_done" if states and done == len(states) else "home_today_empty")
        )

    def _arrange(self):
        self.columns = 2 if self.width() >= 760 and len(self.visible_keys) > 1 else 1
        for index, key in enumerate(self.visible_keys):
            widget = self.widgets[key]
            row, column = divmod(index, self.columns)
            span = self.columns if index == len(self.visible_keys) - 1 and column == 0 else 1
            if self.grid.indexOf(widget) < 0 or self.grid.getItemPosition(
                self.grid.indexOf(widget)
            ) != (row, column, 1, span):
                self.grid.addWidget(
                    widget, row, column, 1, span, alignment=Qt.AlignmentFlag.AlignTop
                )
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1 if self.columns == 2 else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()


class PlannerAgenda(QFrame):
    changed = Signal()
    edit_requested = Signal(object)

    def __init__(self, repository, i18n):
        super().__init__()
        self.repository, self.i18n = repository, i18n
        self.setObjectName("panel")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 16, 16, 16)
        self.root.setSpacing(12)
        title = QLabel(i18n.t("home_upcoming"))
        title.setObjectName("sectionTitle")
        self.root.addWidget(title)
        self.empty = WrapLabel(i18n.t("home_upcoming_empty"))
        self.empty.setObjectName("muted")
        self.root.addWidget(self.empty)
        self.cards = QVBoxLayout()
        self.cards.setSpacing(8)
        self.root.addLayout(self.cards)
        self.widgets, self.headers = {}, {}
        self.limit = 8
        self.more = QPushButton(i18n.t("home_more"))
        self.more.clicked.connect(self._more)
        self.root.addWidget(self.more)
        self.tasks = []

    def _more(self):
        self.limit += 8
        self.set_tasks(self.tasks)

    def set_tasks(self, tasks):
        self.tasks = tasks
        upcoming = [task for task in tasks if date.fromisoformat(task.due_date) > date.today()]
        self.empty.setVisible(not upcoming)
        self.more.setVisible(len(upcoming) > self.limit)
        active, dates = set(), set()
        position = 0
        for task in upcoming[: self.limit]:
            if task.due_date not in dates:
                header = self.headers.get(task.due_date)
                if header is None:
                    header = QLabel(local_date(task.due_date, self.i18n), self)
                    header.setObjectName("muted")
                    self.headers[task.due_date] = header
                header.show()
                if self.cards.indexOf(header) != position:
                    self.cards.insertWidget(position, header)
                position += 1
                dates.add(task.due_date)
            widget = self.widgets.get(task.id)
            if widget is None:
                widget = PlannerCard(self.repository, task, self.i18n, self)
                widget.changed.connect(self.changed)
                widget.edit_requested.connect(self.edit_requested)
                self.widgets[task.id] = widget
            widget.update_task(task)
            widget.show()
            if self.cards.indexOf(widget) != position:
                self.cards.insertWidget(position, widget)
            position += 1
            active.add(task.id)
        for key, widget in self.widgets.items():
            if key not in active:
                self.cards.removeWidget(widget)
                widget.hide()
        for key, header in self.headers.items():
            if key not in dates:
                self.cards.removeWidget(header)
                header.hide()
