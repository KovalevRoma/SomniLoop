"""Date property edits work in rows and inside embedded task forms."""

from datetime import date

import pytest
from PySide6.QtCore import QDate, QPoint, Qt, QTime, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

from somniloop.core.database import Repository
from somniloop.ui.main_window import MainWindow
from somniloop.ui.planner import PlannerDialog
from somniloop.ui.project_tile import ProjectGrid


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "task-form.db")
    repo.set_setting("live2d_config", '{"enabled":false}')
    repo.save_planner_task("Original", None)
    value = MainWindow(repo)
    value.resize(980, 790)
    value.show()
    QTest.qWait(30)
    yield value, app
    value.close()


def test_row_title_and_space_open_editor_but_controls_do_not(window, monkeypatch):
    host, app = window
    workspace = host.dashboard.workspace
    row = next(iter(workspace.rows.values()))
    opened = []
    monkeypatch.setattr(workspace, "organize", lambda entry: opened.append(entry.identifier))
    assert isinstance(row.title, QLabel) and not isinstance(row.title, QLineEdit)
    assert not any(button.text() in ("Open", "Открыть") for button in row.findChildren(QPushButton))
    QTest.mouseClick(row, Qt.MouseButton.LeftButton, pos=QPoint(row.title.x() + 10, row.height() // 2))
    assert opened == [row.entry.identifier]
    row.setFocus()
    QTest.keyClick(row, Qt.Key.Key_Return)
    assert len(opened) == 2
    QTest.mouseClick(row.date_button, Qt.MouseButton.LeftButton)
    assert workspace.date_popup.isVisible()
    assert not getattr(host, "_modal_overlays", [])
    assert len(opened) == 2
    workspace.date_popup.close()


def test_undated_row_calendar_saves_time_clears_and_rejects_invalid_input(window):
    host, app = window
    workspace = host.dashboard.workspace
    row = next(iter(workspace.rows.values()))
    identifier = row.entry.identifier
    QTest.mouseClick(row.date_button, Qt.MouseButton.LeftButton)
    popup = workspace.date_popup
    target = QDate.currentDate().addDays(1)
    if target.month() != popup.month.month():
        popup.move_month(1)
    button = next(b for b in popup.days if b.property("date") == target)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert host.repository.list_planner_tasks()[0].due_date == target.toString("yyyy-MM-dd")
    popup.include_time.setChecked(True)
    popup.clock.setTime(QTime(19, 45))
    popup.clock.editingFinished.emit()
    assert host.repository.list_planner_tasks()[0].due_time == "19:45"
    popup.input.setText("31.02.2030")
    popup.commit_input()
    assert not popup.error.isHidden()
    assert host.repository.list_planner_tasks()[0].due_date == target.toString("yyyy-MM-dd")
    popup.input.setText("12.03.2030")
    QTest.keyClick(popup.input, Qt.Key.Key_Return)
    assert host.repository.list_planner_tasks()[0].due_date == "2030-03-12"
    QTest.mouseClick(popup.clear_button, Qt.MouseButton.LeftButton)
    task = host.repository.list_planner_tasks()[0]
    assert task.id == identifier and task.due_date == "" and task.due_time == ""


def test_new_project_task_uses_dimmed_form_and_cancel_preserves_data(window):
    host, app = window
    repo = host.repository
    project = repo.save_work_project("Home")
    host.dashboard.refresh()
    workspace = host.dashboard.workspace
    workspace.tabs.setCurrentIndex(2)
    QTest.qWait(50)
    grid = next(w for w in workspace.extra_widgets if isinstance(w, ProjectGrid))
    button = next(b for b in grid.tiles[0].findChildren(QPushButton) if b.text() in ("+ Task", "+ Задача"))
    observed = []
    def inspect():
        overlay = host._modal_overlays[-1]
        dialog = overlay.dialog
        observed.append(isinstance(dialog, PlannerDialog) and overlay.isVisible())
        observed.append(dialog.project.currentData() == project)
        QTest.mouseClick(dialog.date_field, Qt.MouseButton.LeftButton)
        popup = dialog.date_field.popup
        observed.append(popup.isVisible())
        target = next(b for b in popup.days if b.property("date") == QDate.currentDate())
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)
        observed.append(dialog.date_field.day == date.today().isoformat())
        popup.close()
        dialog.title_edit.setText("Not saved")
        dialog.reject()
    QTimer.singleShot(80, inspect)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert observed == [True, True, True, True]
    assert len(repo.list_planner_tasks()) == 1


def test_bulk_date_preserves_times_until_explicitly_changed(window):
    host, app = window
    repo = host.repository
    first = repo.save_planner_task("A", date.today(), due_time="08:00")
    second = repo.save_planner_task("B", date.today(), due_time="17:00")
    host.dashboard.refresh()
    workspace = host.dashboard.workspace
    workspace.choose_date([first, second], workspace.scope)
    popup = workspace.date_popup
    popup.select_day(QDate(2030, 5, 10))
    assert repo.completion_snapshot(first)[0]["due_time"] == "08:00"
    assert repo.completion_snapshot(second)[0]["due_time"] == "17:00"
    popup.close()
