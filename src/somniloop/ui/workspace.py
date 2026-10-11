"""Task lists, project views and quick capture."""

from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from .dashboard_cards import WrapLabel
from .planner import PlannerDialog
from .project_tile import ProjectGrid, ProjectTile, project_accent
from .task_actions import TaskActions
from .task_timeline import TaskTimeline
from .work_row import WorkRow
from .workspace_data import order_work, work_entries
from .workspace_forms import CaptureScheduleDialog, ProjectDialog, text


class WorkSpace(TaskActions, QWidget):
    changed = Signal()
    view_changed = Signal(int)

    def __init__(self, repository, i18n, parent=None):
        super().__init__(parent)
        self.repository, self.i18n = repository, i18n
        self.entries, self.projects, self.rows = [], {}, {}
        self.selected_tasks = set()
        self.held_completed = {}
        self.held_completion_snapshots = {}
        self.held_order = []
        self.visible_entries = []
        self.undo_completion = None
        self.snapshot = None
        self.setObjectName("workSpace")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        self.capture = QLineEdit()
        self.capture.setObjectName("workCapture")
        self.capture.setPlaceholderText(self.tr("Записать дело на разбор…  Enter · Ctrl+K", "Capture something to sort…  Enter · Ctrl+K"))
        self.capture.setClearButtonEnabled(True)
        self.capture.returnPressed.connect(self.capture_task)
        self.capture_layout = QHBoxLayout()
        self.capture_layout.addWidget(self.capture, 1)
        root.addLayout(self.capture_layout)
        self.capture_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.capture_shortcut.activated.connect(self.capture.setFocus)
        self.tabs = QTabBar()
        self.tabs.setObjectName("workspaceTabs")
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(True)
        for ru, en in (("Задачи", "Tasks"),
                       ("Привычки", "Habits"), ("Проекты", "Projects"), ("На разбор", "To sort"),
                       ("График", "Chart")):
            self.tabs.addTab(self.tr(ru, en))
        self.tabs.currentChanged.connect(self.change_view)
        self.tabs.tabBarClicked.connect(self.change_view)
        self.tabs.currentChanged.connect(self.view_changed)
        root.addWidget(self.tabs)
        self.timeline = TaskTimeline(self)
        root.addWidget(self.timeline)
        self.timeline.hide()
        self.summary = WrapLabel()
        self.summary.setObjectName("workSummary")
        root.addWidget(self.summary)
        self.undo_panel = QWidget()
        self.undo_panel.setObjectName("workControls")
        undo_layout = QHBoxLayout(self.undo_panel)
        self.undo_label = WrapLabel()
        self.undo_button = QPushButton(self.tr("Отменить", "Undo"))
        self.undo_button.clicked.connect(self.undo_task_completion)
        undo_layout.addWidget(self.undo_label, 1)
        undo_layout.addWidget(self.undo_button)
        root.addWidget(self.undo_panel)
        self.undo_panel.hide()
        self.filters = QWidget()
        self.filters.setObjectName("workFilters")
        filter_layout = QHBoxLayout(self.filters)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Поиск по задачам и шагам", "Search tasks and next actions"))
        self.search.textChanged.connect(self.render)
        filter_layout.addWidget(self.search, 1)
        self.project_filter = QComboBox()
        self.project_filter.setMinimumWidth(160)
        self.project_filter.setMaximumWidth(300)
        self.project_filter.currentIndexChanged.connect(self.render)
        filter_layout.addWidget(self.project_filter)
        self.scope = QComboBox()
        for ru, en in (("Все сроки", "All dates"), ("Просроченные", "Overdue"),
                       ("Ближайшие 7 дней", "Next 7 days"), ("Сегодня", "Today")):
            self.scope.addItem(self.tr(ru, en))
        self.scope.currentIndexChanged.connect(self.render)
        filter_layout.addWidget(self.scope)
        self.add_project_task = QPushButton(self.tr("+ Добавить задачу", "+ Add task"))
        self.add_project_task.clicked.connect(
            lambda: self.new_project_task(self.projects[self.project_filter.currentData()])
        )
        filter_layout.addWidget(self.add_project_task)
        self.add_project = QPushButton("+")
        self.add_project.setObjectName("newProject")
        self.add_project.setFixedSize(40, 40)
        self.add_project.setAccessibleName(self.tr("Добавить проект", "Add project"))
        self.add_project.setToolTip(self.tr("Добавить проект", "Add project"))
        self.add_project.clicked.connect(lambda: self.edit_project())
        self.selection_mode = QPushButton(self.tr("Выбрать", "Select"))
        self.selection_mode.setCheckable(True)
        self.selection_mode.toggled.connect(self.render)
        filter_layout.addWidget(self.selection_mode)
        root.addWidget(self.filters)
        self.bulk_panel = QWidget()
        self.bulk_panel.setObjectName("workControls")
        bulk = QHBoxLayout(self.bulk_panel)
        self.selection_label = QLabel()
        bulk.addWidget(self.selection_label)
        select_all = QPushButton(self.tr("Выбрать все", "Select all"))
        select_all.clicked.connect(self.select_visible)
        bulk.addWidget(select_all)
        for label, action in ((self.tr("Проект", "Project"), "project"),
                              (self.tr("Срок", "Date"), "date"), (self.tr("В архив", "Archive"), "archive")):
            button = QPushButton(label)
            button.clicked.connect(lambda _, value=action: self.bulk_action(value))
            bulk.addWidget(button)
        bulk.addStretch()
        root.addWidget(self.bulk_panel)
        self.bulk_panel.hide()
        self.columns_header = QWidget()
        self.columns_header.setObjectName("workControls")
        header = QHBoxLayout(self.columns_header)
        header.setContentsMargins(40, 0, 10, 0)
        header.setSpacing(8)
        header.addWidget(QLabel(self.tr("Задача", "Task")), 1)
        for label, width in ((self.tr("Проект", "Project"), 150), (self.tr("Срок", "Date"), 180)):
            column = QLabel(label)
            column.setFixedWidth(width)
            header.addWidget(column)
        root.addWidget(self.columns_header)
        self.list_widget = QWidget()
        self.list_widget.setObjectName("workList")
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(4)
        self.message = WrapLabel()
        self.message.setObjectName("muted")
        self.list_layout.addWidget(self.message)
        root.addWidget(self.list_widget)
        root.addWidget(self.add_project, 0, Qt.AlignmentFlag.AlignHCenter)
        self.extra_widgets = []

    def tr(self, ru, en):
        return text(self.i18n, ru, en)

    def select_visible(self):
        self.selected_tasks = {e.key for e in self.visible_entries if e.kind == "planner" and not e.done}
        self._task_render_key = None
        self.render()

    def change_view(self, index):
        if index == 0:
            for control in (self.project_filter, self.scope):
                control.blockSignals(True)
                control.setCurrentIndex(0)
                control.blockSignals(False)
        self.render()

    def project_signature(self):
        return (tuple(tuple(sorted(project.items())) for project in self.projects.values()),
                tuple(self.entries), tuple(tuple(row.items()) for row in self.project_counts.values()))

    def refresh(self, data):
        self.snapshot = data
        self.timeline.refresh()
        self.entries = work_entries(data, self.repository.work_metadata())
        self.projects = {p["id"]: p for p in self.repository.work_projects(True)}
        self.project_counts = {row["project_id"]: dict(row) for row in self.repository.connection.execute(
            "SELECT w.project_id,COUNT(*) AS total,SUM(p.completed) AS done FROM work_items w "
            "JOIN planner_tasks p ON w.kind='planner' AND p.id=w.item_id GROUP BY w.project_id ORDER BY w.project_id"
        )}
        selected = self.project_filter.currentData()
        self.project_filter.blockSignals(True)
        self.project_filter.clear()
        self.project_filter.addItem(self.tr("Все проекты", "All projects"), None)
        for project in self.projects.values():
            self.project_filter.addItem(project["name"], project["id"])
        self.project_filter.setCurrentIndex(max(0, self.project_filter.findData(selected)))
        self.project_filter.blockSignals(False)
        self.tabs.setTabText(3, self.tr("На разбор", "To sort") + f" ({len(self.repository.work_inbox())})")
        self.render()

    def render(self, *_):
        if self.snapshot is None:
            return
        if any(isinstance(w, ProjectGrid) and w.drag_id is not None for w in self.extra_widgets):
            return
        view = self.tabs.currentIndex()
        if view == 0:
            key = (tuple(self.entries), tuple(tuple(sorted(p.items())) for p in self.projects.values()),
                   self.search.text(), self.project_filter.currentData(), self.scope.currentIndex(),
                   self.selection_mode.isChecked(), tuple(self.held_completed),
                   datetime.now().strftime("%Y-%m-%d %H:%M"))
            if getattr(self, "_task_render_key", None) == key:
                return
            self._task_render_key = key
        else:
            self._task_render_key = None
        if (view == 2 and any(isinstance(w, ProjectGrid) for w in self.extra_widgets)
                and getattr(self, "_project_signature", None) == self.project_signature()):
            return
        section = ("task", "habit", "project", "inbox", "chart")[view]
        if self.tabs.property("section") != section:
            self.tabs.setProperty("section", section)
            self.tabs.style().unpolish(self.tabs)
            self.tabs.style().polish(self.tabs)
            self.tabs.update()
        if view != 0:
            for row in self.rows.values():
                self.list_layout.removeWidget(row)
                row.hide()
        active_keys = {entry.key for entry in self.entries} | set(self.held_completed)
        for key in set(self.rows) - active_keys:
            self.rows.pop(key).deleteLater()
        for widget in self.extra_widgets:
            self.list_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self.extra_widgets.clear()
        self.add_project.setVisible(view == 2)
        self.add_project_task.setVisible(view == 0 and self.project_filter.currentData() is not None)
        self.timeline.setVisible(view == 4)
        self.summary.setVisible(view not in (1, 4))
        self.columns_header.setVisible(view == 0)
        self.selection_mode.setVisible(view == 0)
        self.selected_tasks.intersection_update(active_keys - set(self.held_completed))
        if not self.selection_mode.isChecked() or view != 0:
            self.selected_tasks.clear()
        self.selection_label.setText(self.tr("Выбрано: ", "Selected: ") + str(len(self.selected_tasks)))
        self.bulk_panel.setVisible(view == 0 and self.selection_mode.isChecked())
        self.search.setVisible(view == 0)
        self.project_filter.setVisible(view == 0)
        self.scope.setVisible(view == 0)
        self.filters.setVisible(view == 0)
        self.list_widget.setVisible(view not in (1, 4))
        if view == 4:
            return
        self.message.show()
        today = date.today().isoformat()
        pending = [e for e in self.entries if not e.done]
        overdue = sum(bool(e.due and e.due < today and not e.habit) for e in pending)
        self.summary.setText(self.tr(
            f"Активных задач: {sum(not e.habit for e in pending)} · Просрочено: {overdue}",
            f"Active tasks: {sum(not e.habit for e in pending)} · Overdue: {overdue}",
        ))
        now = datetime.now()
        reminders = [e for e in pending if e.time and e.due == today
                     and datetime.fromisoformat(e.due + "T" + e.time) <= now + timedelta(minutes=15)]
        if reminders:
            reminder = min(reminders, key=lambda e: e.time)
            self.summary.setText(self.tr("По времени: ", "Scheduled: ") + reminder.time + " · " + reminder.title)
        if view == 2:
            self.render_projects()
            return
        if view == 3:
            self.render_inbox()
            return
        if view == 1:
            self.summary.hide()
            return
        self.summary.show()
        project = self.project_filter.currentData()
        query = self.search.text().casefold().strip()
        entries = [e for e in self.entries if (project is None or e.project_id == project)
                   and query in (e.title + " " + e.next_action).casefold()]
        entries = order_work([e for e in entries if not e.habit or project is not None])
        scope = self.scope.currentIndex()
        if scope == 1:
            entries = [e for e in entries if e.due and e.due < today and not e.done]
        elif scope == 2:
            end = (date.today() + timedelta(days=7)).isoformat()
            entries = [e for e in entries if e.due and today <= e.due <= end]
        elif scope == 3:
            entries = [e for e in entries if e.due == today]
        if self.held_completed:
            entries = [e for e in entries if e.key not in self.held_completed] + list(self.held_completed.values())
            rank = {key: index for index, key in enumerate(self.held_order)}
            entries.sort(key=lambda e: rank.get(e.key, len(rank)))
        self.visible_entries = entries
        self.selected_tasks.intersection_update({e.key for e in entries if not e.done})
        self.selection_label.setText(self.tr("Выбрано: ", "Selected: ") + str(len(self.selected_tasks)))
        self.message.setText(self.tr("Нет задач по этому фильтру.", "No tasks match."))
        self.message.setVisible(not entries)
        visible_keys = {entry.key for entry in entries}
        for key, row in self.rows.items():
            if key not in visible_keys:
                self.list_layout.removeWidget(row)
                row.hide()
        for index, entry in enumerate(entries):
            row = self.rows.get(entry.key)
            if row is None:
                row = WorkRow(self)
                self.rows[entry.key] = row
            row.update_entry(entry)
            if self.list_layout.indexOf(row) != index + 1:
                self.list_layout.insertWidget(index + 1, row)
            if row.isHidden():
                row.show()

    def capture_task(self):
        if not self.capture.text().strip():
            return
        self.repository.capture_work(self.capture.text())
        self.capture.clear()
        self.tabs.setCurrentIndex(3)
        self.changed.emit()

    def organize(self, entry):
        if entry.kind == "planner":
            task = next((t for t in self.snapshot.planner if t.id == entry.identifier), None)
            if task and PlannerDialog(self.repository, self.i18n, task, self).exec():
                self.changed.emit()
            return
        from .dialogs import EditTrackerDialog
        tracker = self.repository.get_tracker(entry.identifier)
        dialog = EditTrackerDialog(self.i18n, tracker, self)
        project = QComboBox()
        project.addItem(self.tr("Без проекта", "No project"), None)
        for value in self.projects.values():
            project.addItem(value["name"], value["id"])
        project.setCurrentIndex(max(0, project.findData(entry.project_id)))
        dialog.layout().insertWidget(0, project)
        if dialog.exec():
            values = dialog.values()
            self.repository.update_tracker(entry.identifier, values["name"], values["description"],
                                           values["schedule_type"], values["schedule"])
            self.repository.save_work_item(entry.kind, entry.identifier, project_id=project.currentData(),
                                           priority=entry.priority, planned_on=entry.planned_on,
                                           next_action=entry.next_action)
            self.changed.emit()

    def edit_project(self, project=None):
        if ProjectDialog(self.repository, self.i18n, self, project).exec():
            self.changed.emit()

    def project_view(self, identifier):
        self.tabs.setCurrentIndex(0)
        self.search.clear()
        self.scope.setCurrentIndex(0)
        self.project_filter.setCurrentIndex(self.project_filter.findData(identifier))

    def render_projects(self):
        self.message.hide()
        counts = self.project_counts
        if not self.projects:
            self.message.setText(self.tr("Нет проектов", "No projects"))
            self.message.show()
        grid = ProjectGrid(self)
        self.extra_widgets.append(grid)
        for project in self.projects.values():
            frame = ProjectTile(self, project["id"])
            frame.setObjectName("workRow")
            frame.setProperty("category", "project")
            project_accent(frame, project.get("color", "#3778bd"),
                           self.repository.get_setting("theme", "light") == "dark")
            layout = QVBoxLayout(frame)
            heading = QHBoxLayout()
            label = WrapLabel(project["name"] + (self.tr(" · Архив", " · Archived") if project["archived"] else ""))
            label.setObjectName("cardTitle")
            heading.addWidget(label, 1)
            layout.addLayout(heading)
            count = counts.get(project["id"], {"done": 0, "total": 0})
            layout.addWidget(WrapLabel(self.tr(
                f"Задачи: {count['done']} из {count['total']} выполнено",
                f"Tasks: {count['done']} of {count['total']} done",
            )))
            if count["total"]:
                progress = QProgressBar()
                progress.setRange(0, count["total"])
                progress.setValue(count["done"])
                progress.setTextVisible(False)
                progress.setFixedHeight(6)
                layout.addWidget(progress)
            next_items = order_work([e for e in self.entries if e.project_id == project["id"] and not e.done])
            if next_items:
                layout.addWidget(WrapLabel(self.tr("Следующее: ", "Next: ") + next_items[0].title))
            layout.addStretch()
            from PySide6.QtWidgets import QGridLayout
            actions = QGridLayout()
            for title, callback in (
                (self.tr("+ Задача", "+ Task"), lambda _, p=project: self.new_project_task(p)),
                (self.tr("Все дела", "All actions"), lambda _, p=project: self.project_view(p["id"])),
                (self.tr("Изменить", "Edit"), lambda _, p=project: self.edit_project(p)),
            ):
                button = QPushButton(title)
                button.clicked.connect(callback)
                index = actions.count()
                if index == 2:
                    actions.addWidget(button, 1, 0, 1, 2)
                else:
                    actions.addWidget(button, 0, index)
            layout.addLayout(actions)
            for text_label in frame.findChildren(QLabel):
                if not text_label.objectName():
                    text_label.setObjectName("projectText")
                text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            grid.add_tile(frame)
        grid.arrange()
        self.list_layout.addWidget(grid)
        self._project_signature = self.project_signature()

    def move_project(self, source, target, after=False):
        identifiers = list(self.projects)
        if source == target or source not in identifiers or target not in identifiers:
            return
        identifiers.remove(source)
        identifiers.insert(identifiers.index(target) + int(after), source)
        self.repository.reorder_work_projects(identifiers)
        self.changed.emit()

    def new_project_task(self, project):
        dialog = PlannerDialog(self.repository, self.i18n, parent=self)
        dialog.project.setCurrentIndex(dialog.project.findData(project["id"]))
        if dialog.exec():
            self.changed.emit()

    def render_inbox(self):
        captures = self.repository.work_inbox()
        self.message.hide()
        if not captures:
            self.message.setText(self.tr("Всё разобрано", "Nothing to sort"))
            self.message.show()
        for capture in captures:
            frame = QFrame()
            frame.setObjectName("workRow")
            frame.setProperty("category", "inbox")
            layout = QHBoxLayout(frame)
            layout.addWidget(WrapLabel(capture["title"]), 1)
            button = QPushButton(self.tr("Запланировать", "Schedule"))
            button.clicked.connect(lambda _, c=capture: self.schedule_capture(c))
            layout.addWidget(button)
            self.extra_widgets.append(frame)
            self.list_layout.addWidget(frame)

    def schedule_capture(self, capture):
        if CaptureScheduleDialog(self.repository, self.i18n, capture, self).exec():
            self.tabs.setCurrentIndex(0)
            self.changed.emit()
