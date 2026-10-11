"""Small task editors and reversible completion for the workspace."""

from dataclasses import replace

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QVBoxLayout,
)

from .controls import RoundedDialog, polish_dialog_buttons
from .task_date_picker import TaskDatePopup


class TaskActions:
    def choose_project(self, identifiers):
        dialog = RoundedDialog(self)
        dialog.setWindowTitle(self.tr("Проект", "Project"))
        layout = QVBoxLayout(dialog)
        project = QComboBox()
        project.addItem(self.tr("Без проекта", "No project"), None)
        for value in self.projects.values():
            if not value["archived"]:
                project.addItem(value["name"], value["id"])
        if len(identifiers) == 1:
            entry = next(e for e in self.entries if e.key == ("planner", identifiers[0]))
            project.setCurrentIndex(max(0, project.findData(entry.project_id)))
        layout.addWidget(project)
        self._editor_buttons(dialog, layout)
        if dialog.exec():
            self.repository.assign_tasks(identifiers, project.currentData())
            self.changed.emit()

    def choose_date(self, identifiers, anchor=None):
        day, clock = "", ""
        project_id = self.project_filter.currentData()
        if len(identifiers) == 1:
            entry = next(e for e in self.entries if e.key == ("planner", identifiers[0]))
            day, clock = entry.due, entry.time
            project_id = entry.project_id
        self.date_popup = TaskDatePopup(anchor or self.bulk_panel, self.i18n.language,
                                        day, clock, preserve_time=len(identifiers) > 1,
                                        project_days=self.repository.project_calendar_days(project_id))
        def selected(day, clock):
            values = {"due_date": day}
            if clock is not None:
                values["due_time"] = clock
            self.repository.update_task_fields(identifiers, **values)
            self.date_popup.project_days = self.repository.project_calendar_days(project_id)
            self.date_popup.render_month()
            self.changed.emit()
        self.date_popup.chosen.connect(selected)
        self.date_popup.show_at_anchor()

    def _editor_buttons(self, dialog, layout):
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        polish_dialog_buttons(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(self.i18n.t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.i18n.t("cancel"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

    def complete_task(self, entry):
        if entry.done:
            return
        hovered = self.task_under_cursor(entry.key)
        before = self.repository.completion_snapshot(entry.identifier)
        self.repository.complete_planner_task(entry.identifier)
        self.undo_completion = (before, self.repository.completion_snapshot(entry.identifier))
        self.held_completion_snapshots[entry.key] = self.undo_completion
        self.held_completed[entry.key] = replace(entry, done=True)
        self.held_order = [e.key for e in self.visible_entries]
        self.undo_label.setText(self.tr("Выполнено: ", "Completed: ") + entry.title)
        self.undo_button.setEnabled(True)
        # Do not move the clicked row by inserting an undo banner above it.
        if not hovered:
            self.undo_panel.show()
        self.changed.emit()
        QTimer.singleShot(2200, self, lambda key=entry.key: self.release_completed_when_unhovered(key))

    def task_under_cursor(self, key):
        row = self.rows.get(key)
        return bool(row and row.isVisible() and row.rect().contains(row.mapFromGlobal(QCursor.pos())))

    def release_completed_when_unhovered(self, key):
        if not self.task_under_cursor(key):
            self.release_completed(key)

    def uncomplete_held_task(self, key):
        snapshot = self.held_completion_snapshots.get(key)
        if snapshot is None:
            return
        before, expected = snapshot
        restored = self.repository.restore_completion(before, expected)
        self.held_completed.pop(key, None)
        self.held_completion_snapshots.pop(key, None)
        if self.undo_completion == snapshot:
            self.undo_completion = None
            self.undo_panel.hide()
        if not restored:
            self.undo_label.setText(self.tr("Задача уже изменена — отмена недоступна.",
                                            "Task changed since completion; undo is unavailable."))
            self.undo_button.setEnabled(False)
            self.undo_panel.show()
        self._task_render_key = None
        self.changed.emit()

    def release_completed(self, key):
        self.held_completion_snapshots.pop(key, None)
        if self.held_completed.pop(key, None) is not None:
            self._task_render_key = None
            self.render()

    def undo_task_completion(self):
        if not self.undo_completion:
            return
        before, expected = self.undo_completion
        restored = self.repository.restore_completion(before, expected)
        self.held_completed.pop(("planner", before[0]["id"]), None)
        self.held_completion_snapshots.pop(("planner", before[0]["id"]), None)
        self.undo_completion = None
        if restored:
            self.undo_panel.hide()
        else:
            self.undo_label.setText(self.tr("Задача уже изменена — отмена недоступна.", "Task changed since completion; undo is unavailable."))
            self.undo_button.setEnabled(False)
        self.changed.emit()

    def update_selection(self, key, checked):
        if checked:
            self.selected_tasks.add(key)
        else:
            self.selected_tasks.discard(key)
        self.selection_label.setText(self.tr("Выбрано: ", "Selected: ") + str(len(self.selected_tasks)))
        self.bulk_panel.setVisible(self.selection_mode.isChecked() and self.tabs.currentIndex() == 0)

    def bulk_action(self, action):
        identifiers = [key[1] for key in self.selected_tasks]
        if not identifiers:
            return
        if action == "project":
            self.choose_project(identifiers)
        elif action == "date":
            self.choose_date(identifiers)
        else:
            self.repository.update_task_fields(identifiers, archived=1)
            self.selected_tasks.clear()
            self.changed.emit()
