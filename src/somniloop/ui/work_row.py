"""Task rows open one editor; property controls handle their own clicks."""

from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QPushButton, QSizePolicy

from .dashboard_cards import WrapLabel
from .project_tile import project_accent


def readable_due(entry, tr):
    if not entry.due:
        return tr("Без срока", "No date")
    day = date.fromisoformat(entry.due)
    delta = (day - date.today()).days
    if delta == 0:
        stamp = tr("Сегодня", "Today")
    elif delta == 1:
        stamp = tr("Завтра", "Tomorrow")
    elif delta < 0 and not entry.done:
        stamp = tr(f"Просрочено: {abs(delta)} дн.", f"Overdue: {abs(delta)}d")
    else:
        stamp = day.strftime("%d.%m.%Y")
    return stamp + (", " + entry.time if entry.time else "")


class WorkRow(QFrame):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.owner = workspace
        self.setObjectName("workRow")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.press_position = None
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(8)
        self.select = QCheckBox()
        self.select.setAccessibleName(workspace.tr("Выбрать задачу", "Select task"))
        self.select.setToolTip(self.select.accessibleName())
        self.select.toggled.connect(lambda checked: workspace.update_selection(self.entry.key, checked))
        self.select.hide()
        root.addWidget(self.select)
        self.complete = QCheckBox()
        self.complete.setAccessibleName(workspace.tr("Выполнить задачу", "Complete task"))
        self.complete.setToolTip(self.complete.accessibleName())
        self.complete.clicked.connect(lambda checked: workspace.complete_task(self.entry)
                                      if checked else workspace.uncomplete_held_task(self.entry.key))
        root.addWidget(self.complete)
        self.title = WrapLabel()
        self.title.setObjectName("taskTitle")
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        root.addWidget(self.title, 1)
        self.project_button = QPushButton()
        self.project_button.setObjectName("projectChip")
        self.project_button.setFixedWidth(150)
        self.project_button.clicked.connect(lambda: workspace.choose_project([self.entry.identifier]))
        root.addWidget(self.project_button)
        self.date_button = QPushButton()
        self.date_button.setFixedWidth(180)
        self.date_button.clicked.connect(lambda: workspace.choose_date([self.entry.identifier], self.date_button))
        root.addWidget(self.date_button)

    def activate(self):
        if not self.entry.done:
            self.owner.organize(self.entry)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_position = event.position().toPoint()
            self.setFocus()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        origin, self.press_position = self.press_position, None
        if (event.button() == Qt.MouseButton.LeftButton and origin is not None
                and self.rect().contains(event.position().toPoint())
                and (event.position().toPoint() - origin).manhattanLength() < 10):
            event.accept()
            self.activate()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activate()
            event.accept()
        else:
            super().keyPressEvent(event)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if hasattr(self, 'entry') and self.entry.key in self.owner.held_completed:
            QTimer.singleShot(0, self.owner,
                              lambda key=self.entry.key: self.owner.release_completed_when_unhovered(key))

    def update_entry(self, entry):
        project = self.owner.projects.get(entry.project_id)
        signature = (entry, tuple(sorted(project.items())) if project else (), date.today())
        self.select.blockSignals(True)
        self.select.setChecked(entry.key in self.owner.selected_tasks)
        self.select.blockSignals(False)
        self.select.setVisible(self.owner.selection_mode.isChecked() and entry.kind == "planner")
        if getattr(self, "_entry_signature", None) == signature:
            return
        self._entry_signature = signature
        self.entry = entry
        self.title.setText(entry.title)
        self.title.setToolTip(entry.title)
        self.setAccessibleName(entry.title)
        font = self.title.font()
        font.setStrikeOut(entry.done)
        self.title.setFont(font)
        dark = self.owner.repository.get_setting("theme", "light") == "dark"
        project_accent(self, project.get("color", "#3778bd"), dark) if project else self.setStyleSheet("")
        self.setProperty("category", "habit" if entry.habit else "task")
        self.complete.setVisible(entry.kind == "planner")
        self.complete.setChecked(entry.done)
        self.complete.setEnabled(not entry.done or entry.key in self.owner.held_completed)
        name = project["name"] if project else self.owner.tr("Без проекта", "No project")
        self.project_button.setToolTip(name)
        self.project_button.setText(self.project_button.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, 125))
        stamp = readable_due(entry, self.owner.tr)
        self.date_button.setText(self.date_button.fontMetrics().elidedText(stamp, Qt.TextElideMode.ElideRight, 158))
        self.date_button.setToolTip(stamp + "\n" + (entry.due + " " + entry.time).strip())
        overdue = bool(entry.due and entry.due < date.today().isoformat() and not entry.done)
        self.date_button.setStyleSheet("color: " + ("#ffb1bf" if dark else "#a32c40") + ";" if overdue else "")
        for button in (self.project_button, self.date_button):
            button.setEnabled(entry.kind == "planner" and not entry.done)
