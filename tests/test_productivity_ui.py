"""Daily workspace behavior and bounded layouts."""

from dataclasses import replace
from datetime import date, timedelta

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.ui.dashboard import Dashboard
from somniloop.ui.planner import PlannerDialog
from somniloop.ui.project_tile import ProjectGrid
from somniloop.ui.theme import stylesheet
from somniloop.ui.workspace import WorkRow
from somniloop.ui.workspace_data import WorkEntry, order_work
from somniloop.ui.workspace_forms import (
    CaptureScheduleDialog,
    DeleteProjectDialog,
    ProjectDialog,
)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def repo(tmp_path):
    repo = Repository(tmp_path / "work.db")
    yield repo
    repo.close()


def test_order_is_explicit_and_stable():
    normal = WorkEntry("planner", 1, "Late", "2020-01-01")
    important = WorkEntry("planner", 2, "Important", "2030-01-01", priority=1)
    critical = WorkEntry("planner", 3, "Critical", "2030-01-01", priority=2)
    assert order_work([normal, critical, important]) == [normal, critical, important]


def test_semantic_badges_update_without_recreating_row(app, repo):
    page = Dashboard(repo, I18n("en"), productivity=True)
    row = WorkRow(page.workspace)
    try:
        entry = WorkEntry("planner", 1, "Task", "2020-01-01", priority=2)
        row.update_entry(entry)
        assert not hasattr(row, "priority_badge")
        assert "Overdue" in row.date_button.text()
        row.update_entry(replace(entry, priority=1, habit=True))
        assert row.property("category") == "habit"
        row.update_entry(replace(entry, priority=0, done=True))
        assert "Overdue" not in row.date_button.text()
        for index, category in ((1, "habit"), (2, "project"), (3, "inbox")):
            page.workspace.tabs.setCurrentIndex(index)
            assert page.workspace.tabs.property("section") == category
    finally:
        page.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width", [980, 1280, 1920])
def test_workspace_views_wrap_and_have_no_horizontal_scroll(app, repo, theme, width):
    app.setStyleSheet(stylesheet(theme))
    identifier = repo.save_planner_task("Long title " * 35, date.today())
    project = repo.save_work_project("Teaching " * 20, "Eight lessons")
    repo.save_work_item("planner", identifier, project_id=project, priority=2)
    page = Dashboard(repo, I18n("ru"), productivity=True)
    page.resize(width, 790)
    page.show()
    try:
        for view in range(4):
            page.workspace.tabs.setCurrentIndex(view)
            app.processEvents()
            assert page.scroll.horizontalScrollBar().maximum() == 0
            assert page.container.width() <= page.scroll.viewport().width()
            assert page.workspace.width() <= page.scroll.viewport().width()
    finally:
        page.close()


def test_empty_day_is_compact_and_capture_survives_refresh(app, repo):
    page = Dashboard(repo, I18n("en"), productivity=True)
    page.resize(980, 700)
    page.show()
    try:
        QTest.qWait(50)
        assert page.scroll.verticalScrollBar().maximum() == 0
        page.workspace.capture.setText("Remember this")
        page.workspace.capture_task()
        assert repo.work_inbox()[0]["title"] == "Remember this"
        assert repo.list_planner_tasks() == []
        assert page.workspace.tabs.currentIndex() == 3
    finally:
        page.close()


def test_legacy_day_metadata_does_not_restore_removed_day_action(app, repo):
    identifier = repo.save_planner_task("Action", date.today() + timedelta(days=2))
    repo.save_work_item("planner", identifier, planned_on=date.today().isoformat())
    page = Dashboard(repo, I18n("en"), productivity=True)
    try:
        work = page.workspace
        assert not hasattr(work, "pin")
        assert repo.work_metadata()[("planner", identifier)]["planned_on"] == date.today().isoformat()
        assert len(repo.list_planner_tasks()) == 1
        assert repo.list_planner_tasks()[0].due_date == (date.today() + timedelta(days=2)).isoformat()
    finally:
        page.close()


def test_cancel_does_not_save_project_or_metadata(app, repo):
    identifier = repo.save_planner_task("Task", date.today())
    page = Dashboard(repo, I18n("en"), productivity=True)
    try:
        dialog = ProjectDialog(repo, page.i18n, page)
        dialog.name.setText("Not saved")
        dialog.reject()
        assert repo.work_projects() == []
        details = PlannerDialog(repo, page.i18n, repo.list_planner_tasks()[0], page)
        details.title_edit.setText("Not saved")
        details.reject()
        assert ("planner", identifier) not in repo.work_metadata()
        capture = repo.capture_work("Idea")
        schedule = CaptureScheduleDialog(repo, page.i18n, repo.work_inbox()[0], page)
        schedule.reject()
        assert repo.work_inbox()[0]["id"] == capture
        assert len(repo.list_planner_tasks()) == 1
    finally:
        page.close()


def test_project_form_save_and_capture_assignment(app, repo):
    page = Dashboard(repo, I18n("ru"), productivity=True)
    try:
        project_form = ProjectDialog(repo, page.i18n, page)
        project_form.name.setText("Преподавание")
        assert not hasattr(project_form, "outcome")
        project_form.color_value = "#a45db2"
        project_form.save()
        project = repo.work_projects()[0]
        assert project["color"] == "#a45db2"
        repo.capture_work("Подготовить занятие")
        schedule = CaptureScheduleDialog(repo, page.i18n, repo.work_inbox()[0], page)
        schedule.project.setCurrentIndex(schedule.project.findData(project["id"]))
        assert not hasattr(schedule, "priority")
        schedule.save()
        task = repo.list_planner_tasks()[0]
        assert repo.work_metadata()[("planner", task.id)]["project_id"] == project["id"]
        assert repo.work_metadata()[("planner", task.id)]["priority"] == 0
        assert repo.work_inbox() == []
    finally:
        page.close()


def test_project_move_and_task_accent(app, repo):
    first = repo.save_work_project("First", color="#a45db2")
    second = repo.save_work_project("Second")
    task = repo.save_planner_task("Task", date.today())
    repo.save_work_item("planner", task, project_id=first)
    page = Dashboard(repo, I18n("en"), productivity=True)
    try:
        page.workspace.move_project(first, second, after=True)
        assert list(page.workspace.projects) == [second, first]
        page.workspace.move_project(first, second)
        assert list(page.workspace.projects) == [first, second]
        page.workspace.tabs.setCurrentIndex(2)
        grid = next(w for w in page.workspace.extra_widgets if isinstance(w, ProjectGrid))
        grid.begin(first)
        assert not grid.placeholder.isHidden()
        grid.preview(QPoint(0, 10000))
        assert grid.preview_ids == [second, first]
        assert list(page.workspace.projects) == [first, second]
        grid.cancel()
        assert grid.placeholder.isHidden()
        grid.begin(first)
        grid.preview(QPoint(0, 10000))
        grid.commit()
        assert [tile.identifier for tile in grid.tiles] == [second, first]
        grid.cancel()
        assert [tile.identifier for tile in grid.tiles] == [second, first]
        app.processEvents()
        assert list(page.workspace.projects) == [second, first]
        assert grid in page.workspace.extra_widgets
        page.workspace.render()
        assert grid in page.workspace.extra_widgets
        page.workspace.tabs.setCurrentIndex(0)
        row = page.workspace.rows[("planner", task)]
        assert "#a45db2" in row.styleSheet()
        repo.save_work_project("First", project_id=first, color="#278b71")
        page.refresh()
        assert page.workspace.rows[("planner", task)] is row
        assert "#278b71" in row.styleSheet()
    finally:
        page.close()


def test_task_editor_has_project_and_optional_checklist(app, repo):
    project = repo.save_work_project("Life")
    dialog = PlannerDialog(repo, I18n("en"))
    assert not dialog.has_items.isChecked()
    assert dialog.items_edit.isHidden()
    dialog.title_edit.setText("Simple task")
    dialog.project.setCurrentIndex(dialog.project.findData(project))
    dialog._save()
    task = repo.list_planner_tasks()[0]
    assert task.items == []
    assert repo.work_metadata()[("planner", task.id)]["project_id"] == project


def test_grid_positions_have_one_owner_and_settle_after_fast_previews(app, repo):
    for index in range(12):
        repo.save_work_project(f"Project {index}")
    page = Dashboard(repo, I18n("en"), productivity=True)
    page.resize(1280, 790)
    page.show()
    page.workspace.tabs.setCurrentIndex(2)
    QTest.qWait(40)
    grid = next(w for w in page.workspace.extra_widgets if isinstance(w, ProjectGrid))
    try:
        assert grid.layout() is None
        grid.begin(grid.tiles[0].identifier)
        for index in range(40):
            grid.preview(QPoint((index % grid.columns) * (grid.cell_size + 12) + 10, 10))
            app.processEvents()
        ids = grid.preview_ids[:]
        grid.commit()
        QTest.qWait(220)
        assert [tile.identifier for tile in grid.tiles] == ids
        for index, tile in enumerate(grid.tiles):
            assert tile.pos() == QPoint(index % grid.columns * (grid.cell_size + 12),
                                        index // grid.columns * (grid.cell_height + 12))
        assert grid.motion.state() == grid.motion.State.Stopped
        assert not grid.scroll_timer.isActive()
        queries = []
        repo.connection.set_trace_callback(queries.append)
        for _ in range(20):
            page.workspace.render()
        repo.connection.set_trace_callback(None)
        assert queries == []
        assert grid in page.workspace.extra_widgets
    finally:
        page.close()


def test_project_delete_requires_confirmation_and_archive_lives_in_editor(app, repo, monkeypatch):
    identifier = repo.save_work_project("Home")
    page = Dashboard(repo, I18n("en"), productivity=True)
    try:
        project = repo.work_projects()[0]
        editor = ProjectDialog(repo, page.i18n, page, project)
        assert editor.archive_button.text() == "Archive"
        monkeypatch.setattr(DeleteProjectDialog, "exec", lambda self: self.DialogCode.Rejected)
        editor.delete()
        assert repo.work_projects()[0]["id"] == identifier
        editor.archive()
        assert repo.work_projects() == []
        project = repo.work_projects(True)[0]
        editor = ProjectDialog(repo, page.i18n, page, project)
        assert editor.archive_button.text() == "Restore from archive"
        monkeypatch.setattr(DeleteProjectDialog, "exec", lambda self: self.DialogCode.Accepted)
        editor.delete()
        assert repo.work_projects(True) == []
    finally:
        page.close()


def test_task_tab_resets_filters_but_project_link_selects_project(app, repo):
    project = repo.save_work_project("Work")
    page = Dashboard(repo, I18n("en"), productivity=True)
    try:
        work = page.workspace
        work.project_filter.setCurrentIndex(work.project_filter.findData(project))
        work.scope.setCurrentIndex(2)
        work.tabs.setCurrentIndex(1)
        work.tabs.setCurrentIndex(0)
        assert work.project_filter.currentData() is None
        assert work.scope.currentIndex() == 0
        work.tabs.setCurrentIndex(2)
        work.project_view(project)
        assert work.project_filter.currentData() == project
        work.tabs.tabBarClicked.emit(0)
        assert work.project_filter.currentData() is None
    finally:
        page.close()


def test_delete_confirmation_uses_embedded_modal(app, repo):
    from PySide6.QtWidgets import QDialogButtonBox

    from somniloop.ui.main_window import MainWindow

    repo.set_setting("live2d_config", '{"enabled":false}')
    window = MainWindow(repo)
    window.show()
    confirmation = DeleteProjectDialog(I18n("en"), "Home", window)
    observed = []

    def inspect_and_cancel():
        overlay = getattr(confirmation, "_modal_overlay", None)
        observed.append(overlay is not None and overlay.isVisible())
        buttons = confirmation.findChild(QDialogButtonBox) if overlay is None else overlay.buttons
        observed.append(buttons.button(QDialogButtonBox.StandardButton.Cancel).isDefault())
        confirmation.reject()

    try:
        QTimer.singleShot(40, inspect_and_cancel)
        assert confirmation.exec() == confirmation.DialogCode.Rejected
        assert observed == [True, True]
    finally:
        window.close()


def test_grid_shrinks_and_drag_uses_full_tile_image(app, repo, monkeypatch):
    from types import SimpleNamespace

    from somniloop.ui import project_tile

    for index in range(7):
        repo.save_work_project(f"Project {index}")
    page = Dashboard(repo, I18n("en"), productivity=True)
    page.workspace.tabs.setCurrentIndex(2)
    page.show()
    try:
        for width in (1920, 980, 1280, 980):
            page.resize(width, 790)
            QTest.qWait(30)
            assert page.scroll.horizontalScrollBar().maximum() == 0
        grid = next(w for w in page.workspace.extra_widgets if isinstance(w, ProjectGrid))
        handle = grid.tiles[0]
        captured = {}

        class Drag:
            def __init__(self, source):
                assert source is handle

            def setMimeData(self, data):
                captured["mime"] = data

            def setPixmap(self, pixmap):
                captured["size"] = pixmap.deviceIndependentSize().toSize()

            def setHotSpot(self, point):
                captured["hotspot"] = point

            def deleteLater(self):
                captured["disposed"] = True

            def exec(self, action):
                assert action == Qt.DropAction.MoveAction
                assert grid.drag_id == handle.identifier
                assert not grid.placeholder.isHidden()

        monkeypatch.setattr(project_tile, "QDrag", Drag)
        handle.origin = QPoint(5, 5)
        handle.mouseMoveEvent(SimpleNamespace(buttons=lambda: Qt.MouseButton.LeftButton,
                                              position=lambda: QPointF(100, 100)))
        assert captured["size"] == handle.size()
        assert captured["hotspot"] == QPoint(5, 5)
        assert captured["disposed"]
        assert grid.drag_id is None
        assert [p["id"] for p in repo.work_projects()] == [t.identifier for t in grid.tiles]
    finally:
        page.close()
