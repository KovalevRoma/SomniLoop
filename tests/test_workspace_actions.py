"""Task edits preserve checklist state, metadata and reversible completion."""

from datetime import date

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.core.models import TaskState
from somniloop.live2d.overlay import Live2DOverlay
from somniloop.live2d.resources import CharacterConfig
from somniloop.ui.dashboard import Dashboard
from somniloop.ui.planner import PlannerDialog
from somniloop.ui.project_tile import ProjectGrid


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def repo(tmp_path):
    value = Repository(tmp_path / "actions.db")
    yield value
    value.close()


def test_project_task_form_has_no_invented_date_or_checklist(app, repo, monkeypatch):
    project = repo.save_work_project("Home")
    page = Dashboard(repo, I18n("en"), productivity=True)
    try:
        def save(dialog):
            assert dialog.project.currentData() == project
            dialog.title_edit.setText("Repair lamp")
            dialog._save()
            return dialog.DialogCode.Accepted
        monkeypatch.setattr(PlannerDialog, "exec", save)
        page.workspace.new_project_task({"id": project})
        task = repo.list_planner_tasks()[0]
        assert task.title == "Repair lamp" and task.due_date == "" and task.items == []
        assert repo.work_metadata()[("planner", task.id)]["project_id"] == project
        page.refresh()
        assert page.workspace.rows[("planner", task.id)].date_button.text() == "No date"
    finally:
        page.close()


def test_bulk_edits_keep_time_checklist_and_metadata(app, repo):
    first = repo.save_planner_task("First", date.today(), items=["A", "B"], due_time="12:30")
    second = repo.save_planner_task("Second", date.today(), due_time="18:00")
    task = repo.list_planner_tasks()[0]
    repo.set_planner_item_done(task.items[0]["id"], True)
    repo.save_work_item("planner", first, priority=2, next_action="Keep me")
    items = repo.completion_snapshot(first)[1]
    project = repo.save_work_project("Teaching")
    page = Dashboard(repo, I18n("en"), productivity=True)
    try:
        work = page.workspace
        row = work.rows[("planner", first)]
        assert not isinstance(row.title, QLineEdit)
        repo.assign_tasks([first, second], project)
        repo.update_task_fields([first, second], due_date="2030-01-02")
        assert repo.completion_snapshot(first)[0]["due_time"] == "12:30"
        assert repo.completion_snapshot(second)[0]["due_time"] == "18:00"
        assert repo.completion_snapshot(first)[1] == items
        assert repo.work_metadata()[("planner", first)]["next_action"] == "Keep me"
        work.selection_mode.setChecked(True)
        work.select_visible()
        work.bulk_action("archive")
        assert repo.list_planner_tasks() == []
        assert len(repo.list_planner_tasks(True)) == 2
    finally:
        page.close()


def test_completion_undo_restores_partial_items_and_stable_row(app, repo):
    identifier = repo.save_planner_task("Task", date.today(), items=["A", "B"])
    item = repo.list_planner_tasks()[0].items[0]
    repo.set_planner_item_state(item["id"], TaskState.PARTIAL)
    before = repo.completion_snapshot(identifier)
    page = Dashboard(repo, I18n("en"), productivity=True)
    try:
        work = page.workspace
        row = work.rows[("planner", identifier)]
        work.complete_task(work.entries[0])
        assert repo.list_planner_tasks() == []
        assert work.rows[("planner", identifier)] is row and row.entry.done
        work.undo_task_completion()
        assert repo.completion_snapshot(identifier) == before
        assert not row.entry.done
        work.complete_task(work.entries[0])
        work.release_completed(("planner", identifier))
        work.undo_task_completion()
        assert repo.completion_snapshot(identifier) == before
    finally:
        page.close()


def test_undo_does_not_overwrite_later_edits(repo):
    identifier = repo.save_planner_task("Original", date.today())
    before = repo.completion_snapshot(identifier)
    repo.complete_planner_task(identifier)
    expected = repo.completion_snapshot(identifier)
    repo.update_task_fields([identifier], title="Later edit")
    assert not repo.restore_completion(before, expected)
    assert repo.completion_snapshot(identifier)[0]["title"] == "Later edit"


def test_completed_row_stays_under_cursor_and_can_be_unchecked(app, repo, monkeypatch):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QCursor

    identifier = repo.save_planner_task("Task", date.today(), items=["A", "B"])
    repo.save_planner_task("Other", date.today())
    before = repo.completion_snapshot(identifier)
    page = Dashboard(repo, I18n("en"), productivity=True)
    page.resize(1100, 700)
    page.show()
    app.processEvents()
    work = page.workspace
    key = ("planner", identifier)
    row = work.rows[key]
    cursor = row.complete.mapToGlobal(row.complete.rect().center())
    monkeypatch.setattr(QCursor, "pos", lambda: cursor)
    try:
        position = row.mapToGlobal(QPoint(0, 0))
        row.complete.click()
        QTest.qWait(2300)
        assert row.isVisible() and row.complete.isEnabled() and row.complete.isChecked()
        assert row.mapToGlobal(QPoint(0, 0)) == position
        row.complete.click()
        assert repo.completion_snapshot(identifier) == before
        assert not row.entry.done and not row.complete.isChecked()
        assert key not in work.held_completed
        row.complete.click()
        cursor = row.title.mapToGlobal(row.title.rect().center())
        work.release_completed_when_unhovered(key)
        assert key in work.held_completed
        cursor = page.mapToGlobal(QPoint(0, 0))
        QApplication.sendEvent(row, QEvent(QEvent.Type.Leave))
        app.processEvents()
        assert key not in work.held_completed
        assert key not in {entry.key for entry in work.visible_entries}
        assert repo.list_planner_tasks(True)[0].completed
    finally:
        page.close()


def test_project_button_does_not_start_drag_and_legacy_size_is_ignored(app, repo, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    from somniloop.ui import project_tile
    repo.save_work_project("Home")
    repo.set_setting("project_tile_detail", "1")
    page = Dashboard(repo, I18n("en"), productivity=True)
    page.resize(1280, 790)
    page.show()
    page.workspace.tabs.setCurrentIndex(2)
    QTest.qWait(40)
    try:
        grid = next(w for w in page.workspace.extra_widgets if isinstance(w, ProjectGrid))
        started = []
        monkeypatch.setattr(project_tile, "start_project_drag", lambda *args: started.append(args))
        opened = []
        monkeypatch.setattr(page.workspace, "new_project_task", lambda project: opened.append(project["id"]))
        button = next(b for b in grid.tiles[0].findChildren(QPushButton) if b.text() == "+ Task")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert not started
        assert opened == [grid.tiles[0].identifier]
        assert not grid.tiles[0].findChildren(QLineEdit)
        assert not hasattr(page.workspace, "project_size")
        assert grid.cell_height < grid.cell_size
    finally:
        page.close()


def test_project_add_button_is_after_all_tiles_and_scrolls_with_content(app, repo, monkeypatch):
    for index in range(24):
        repo.save_work_project(f"Project {index}")
    page = Dashboard(repo, I18n("en"), productivity=True)
    page.resize(980, 700)
    page.show()
    page.workspace.tabs.setCurrentIndex(2)
    QTest.qWait(80)
    try:
        work = page.workspace
        button = work.add_project
        viewport = page.scroll.viewport()
        assert button.text() == "+" and button.width() == button.height() == 40
        assert not viewport.rect().contains(button.mapTo(viewport, button.rect().center()))
        bar = page.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        QTest.qWait(30)
        assert viewport.rect().contains(button.mapTo(viewport, button.rect().center()))
        opened = []
        monkeypatch.setattr(work, "edit_project", lambda: opened.append(True))
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert opened == [True]
        work.tabs.setCurrentIndex(0)
        assert button.isHidden()
    finally:
        page.close()


def test_status_drag_moves_character_and_saves_bounded_position(app, repo):
    from types import SimpleNamespace
    host = QWidget()
    host.repository = repo
    host.resize(1280, 790)
    character = Live2DOverlay(host, CharacterConfig(enabled=False))
    try:
        character.content_bottom = .9
        character.content_bounds = (.15, .08, .85, .9)
        character._arrange()
        badge = character.status
        metrics = QFontMetrics(badge.label_font())
        for key, labels in badge.LABELS.items():
            if key != "Preview":
                assert all(metrics.horizontalAdvance(label) <= badge.width() - 46 for label in labels[:2])
        assert badge.y() - (character.y() + round(character.height() * .9)) == 4
        start = character.pos()
        badge.mousePressEvent(SimpleNamespace(button=lambda: Qt.MouseButton.LeftButton,
            globalPosition=lambda: QPointF(500, 500), accept=lambda: None))
        badge.mouseMoveEvent(SimpleNamespace(buttons=lambda: Qt.MouseButton.LeftButton,
            globalPosition=lambda: QPointF(400, 450), accept=lambda: None))
        badge.mouseReleaseEvent(SimpleNamespace(button=lambda: Qt.MouseButton.LeftButton, accept=lambda: None))
        assert character.pos() == start + QPoint(-100, -50)
        saved = CharacterConfig.load(repo)
        assert saved.offset_x == character.config.offset_x and saved.offset_y == character.config.offset_y
        character._drag_character(QPoint(-10000, -10000))
        assert character.x() + round(character.width() * .15) == 0
        assert character.y() + round(character.height() * .08) == 0
        assert host.rect().contains(badge.geometry())
        character._drag_character(QPoint(10000, 10000))
        assert character.x() + round(character.width() * .85) == host.width()
        assert badge.geometry().bottom() == host.height() - 1
        character._save_position()
        character.config = CharacterConfig.load(repo)
        character._arrange()
        assert badge.geometry().bottom() == host.height() - 1
        host.resize(980, 600)
        character._arrange()
        assert host.rect().contains(badge.geometry())
    finally:
        character.dispose()
        host.close()
