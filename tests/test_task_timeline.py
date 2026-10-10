"""Timeline date semantics, archive history, bounded drawing and interaction."""

from datetime import date, datetime, timedelta

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidget

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.ui.controls import RoundedDialog
from somniloop.ui.dashboard import Dashboard
from somniloop.ui.task_timeline import TimelineCanvas, TimelineTask, timeline_tasks
from somniloop.ui.theme import stylesheet


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def repo(tmp_path):
    repository = Repository(tmp_path / "timeline.db")
    yield repository
    repository.close()


def test_history_uses_due_date_and_excludes_unfinished_archive(repo):
    project = repo.save_work_project("Teaching", color="#12ab34")
    due = date(2026, 2, 10)
    completed = repo.save_planner_task("Done early", due)
    repo.save_work_item("planner", completed, project_id=project)
    repo.complete_planner_task(completed)
    archived = repo.save_planner_task("Discarded", due)
    repo.archive_planner_task(archived)
    undated = repo.save_planner_task("Later", None)
    tasks = {t.identifier: t for t in timeline_tasks(repo)}
    assert set(tasks) == {completed, undated}
    assert tasks[completed].due == due
    assert tasks[completed].done
    assert tasks[completed].color == "#12ab34"
    assert tasks[completed].project == "Teaching"
    assert tasks[undated].due is None


def test_project_table_counts_only_pending_in_visible_range(app, repo):
    first = repo.save_work_project("Same name", color="#ed35ac")
    second = repo.save_work_project("Same name", color="#35aced")
    today = date.today()
    for project, day, done in (
        (first, today, False),
        (second, today, False),
        (first, today, True),
        (first, None, False),
        (first, today + timedelta(days=200), False),
    ):
        identifier = repo.save_planner_task("Task", day)
        repo.save_work_item("planner", identifier, project_id=project)
        if done:
            repo.complete_planner_task(identifier)
    repo.save_planner_task("No project", today)
    page = Dashboard(repo, I18n("en"), productivity=True)
    page.resize(1280, 790)
    page.show()
    page.workspace.tabs.setCurrentIndex(4)
    app.processEvents()
    chart = page.workspace.timeline
    assert len(chart.project_rows) == 3
    assert sum(row[2] for row in chart.project_rows) == 3
    assert chart.table_layout.columnCount() == 2
    before = list(chart.project_rows)
    chart.completed.setChecked(False)
    assert chart.project_rows == before
    chart.scroll.setValue(round(chart.canvas.day_x(today + timedelta(days=190))))
    assert chart.project_rows == [["Same name", "#ed35ac", 1]]
    chart.scroll.setValue(round(chart.canvas.day_x(today + timedelta(days=240))))
    assert chart.project_rows == []
    page.close()


def test_birthdays_repeat_and_follow_visible_period(app, repo, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QToolTip

    today = date.today()
    people = [
        SimpleNamespace(name=name, birth_date=f"--{today:%m-%d}", conflicts=[])
        for name in ("Alice", "Bob <test>")
    ]
    people.append(SimpleNamespace(name="Unknown", birth_date="", conflicts=[]))
    monkeypatch.setattr(repo, "list_people", lambda: people)
    page = Dashboard(repo, I18n("en"), productivity=True)
    page.resize(1280, 790)
    page.show()
    page.workspace.tabs.setCurrentIndex(4)
    app.processEvents()
    chart = page.workspace.timeline
    assert chart.canvas.birthday_names(today) == ["Alice", "Bob <test>"]
    assert chart.visible_birthdays == ((today, "Alice"), (today, "Bob <test>"))
    assert "Bob &lt;test&gt;" in chart.canvas.birthday_tooltip(today)
    shown = []
    monkeypatch.setattr(QToolTip, "showText", lambda position, text, widget: shown.append(text))
    point = chart.canvas.crown_rect(today).center()
    chart.canvas.mouseMoveEvent(
        SimpleNamespace(position=lambda: point, globalPosition=lambda: point)
    )
    assert "Alice" in shown[-1]
    chart.scroll.setValue(round(chart.canvas.day_x(today + timedelta(days=50))))
    assert chart.visible_birthdays == ()
    leap = SimpleNamespace(name="Leap", birth_date="--02-29")
    chart.canvas.people = (leap,)
    chart.canvas._birthday_years.clear()
    assert chart.canvas.birthday_names(date(2028, 2, 29)) == ["Leap"]
    assert chart.canvas.birthday_names(date(2027, 2, 28)) == ["Leap"]
    page.close()


def test_sidebar_overdue_is_independent_of_visible_month_and_capture_links(app, repo, monkeypatch):
    today = date.today()
    identifier = repo.save_planner_task("Overdue", today - timedelta(days=80))
    done = repo.save_planner_task("Done", today - timedelta(days=90))
    repo.complete_planner_task(done)
    repo.capture_work("Unsorted idea")
    page = Dashboard(repo, I18n("en"), productivity=True)
    page.resize(1280, 790)
    page.show()
    page.workspace.tabs.setCurrentIndex(4)
    app.processEvents()
    chart = page.workspace.timeline
    assert chart.overdue_ids == [identifier]
    chart.scroll.setValue(round(chart.canvas.day_x(today + timedelta(days=60))))
    assert chart.overdue_ids == [identifier]
    assert chart.project_rows == []
    assert page.workspace.tabs.tabText(3).startswith("To sort")
    opened = []
    monkeypatch.setattr(chart, "edit_task", lambda key, parent: opened.append(key))
    monkeypatch.setattr(
        page.workspace, "schedule_capture", lambda value: opened.append(value["title"])
    )
    from PySide6.QtWidgets import QLabel

    links = [label for label in chart.sidebar.findChildren(QLabel) if "href=" in label.text()]
    assert len(links) == 2
    for label in links:
        label.linkActivated.emit("open")
    assert opened == [identifier, "Unsorted idea"]
    for width in (980, 1280):
        page.resize(width, 790)
        app.processEvents()
        ratio = chart.table_panel.width() / (chart.table_panel.width() + chart.sidebar.width())
        assert abs(ratio - 5 / 7) < 0.04
        assert page.scroll.horizontalScrollBar().maximum() == 0
    page.close()


def test_overdue_respects_time_and_completion():
    now = datetime(2026, 10, 8, 12)

    def task(day, time="", done=False):
        return TimelineTask(1, "Task", day, time, done, "", "#123456")

    assert task(date(2026, 10, 7)).overdue(now)
    assert task(date(2026, 10, 8), "11:59").overdue(now)
    assert not task(date(2026, 10, 8)).overdue(now)
    assert not task(date(2026, 10, 8), "12:01").overdue(now)
    assert not task(date(2026, 10, 7), done=True).overdue(now)
    assert not task(None).overdue(now)


def test_date_coordinates_include_leap_day_and_month_gap(app):
    canvas = TimelineCanvas("en")
    canvas.resize(650, 112)
    canvas.start, canvas.end = date(2024, 2, 1), date(2025, 2, 28)
    for day in (date(2024, 2, 29), date(2024, 3, 1), date(2025, 1, 1)):
        assert canvas.day_at(canvas.day_x(day) + canvas.cell / 2) == day
    assert canvas.day_at(canvas.day_x(date(2024, 3, 1)) - 2) is None
    assert len(list(canvas.visible_days())) < 40
    canvas.close()


def test_refresh_resize_and_completion_preserve_month(app, repo):
    due = date.today() + timedelta(days=40)
    identifier = repo.save_planner_task("Future", due)
    page = Dashboard(repo, I18n("ru"), productivity=True)
    page.resize(1280, 790)
    page.show()
    page.workspace.tabs.setCurrentIndex(4)
    app.processEvents()
    chart = page.workspace.timeline
    assert chart.canvas.day_at(2) == date.today()
    chart.scroll.setValue(round(chart.canvas.day_x(due.replace(day=1))))
    repo.complete_planner_task(identifier)
    page.refresh()
    assert chart.canvas.tasks[due][0].done
    assert chart.canvas.day_at(2) == due.replace(day=1)
    page.resize(980, 790)
    app.processEvents()
    assert chart.canvas.day_at(2) == due.replace(day=1)
    assert page.scroll.horizontalScrollBar().maximum() == 0
    chart.completed.setChecked(False)
    assert chart.canvas.entries(due) == []
    chart.completed.setChecked(True)
    assert len(chart.canvas.entries(due)) == 1
    assert not chart.grab().isNull()
    statements = []
    repo.connection.set_trace_callback(statements.append)
    chart.refresh()
    chart.scroll.setValue(chart.scroll.value() + 12)
    app.processEvents()
    repo.connection.set_trace_callback(None)
    assert not statements
    page.close()


def test_day_click_keyboard_and_undated_dialog(app, repo):
    repo.save_planner_task("Undated idea", None)
    page = Dashboard(repo, I18n("en"), productivity=True)
    page.resize(1280, 790)
    page.show()
    page.workspace.tabs.setCurrentIndex(4)
    app.processEvents()
    chart = page.workspace.timeline
    canvas = chart.canvas
    canvas.day_clicked.disconnect()
    clicked = []
    canvas.day_clicked.connect(clicked.append)
    day = date.today()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(4, 60))
    assert clicked == [day]
    QTest.keyClick(canvas, Qt.Key.Key_Right)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert clicked[-1] == day + timedelta(days=1)
    seen = []

    def inspect_dialog():
        dialog = next(w for w in app.allWidgets() if isinstance(w, RoundedDialog) and w.isVisible())
        try:
            seen.append(dialog.findChild(QListWidget).item(0).text())
        finally:
            dialog.reject()

    QTimer.singleShot(0, inspect_dialog)
    chart.undated.click()
    assert "Undated idea" in seen[0]
    page.close()


def test_chart_is_exclusive_tab_and_opens_at_earliest_overdue(app, repo):
    oldest = date.today() - timedelta(days=80)
    first = repo.save_planner_task("Oldest pending", oldest)
    repo.save_planner_task("Recent pending", date.today() - timedelta(days=2))
    completed = repo.save_planner_task("Old completion", oldest - timedelta(days=20))
    repo.complete_planner_task(completed)
    page = Dashboard(repo, I18n("en"), productivity=True)
    page.resize(1280, 790)
    page.show()
    workspace = page.workspace
    chart = workspace.timeline
    for index in range(4):
        workspace.tabs.setCurrentIndex(index)
        app.processEvents()
        assert not chart.isVisible()
    workspace.tabs.setCurrentIndex(4)
    app.processEvents()
    assert chart.isVisible()
    assert chart.canvas.day_at(0) == oldest
    assert workspace.list_widget.isHidden()
    assert workspace.filters.isHidden()
    assert workspace.summary.isHidden()
    assert not hasattr(chart, "expand")
    chart.go_today()
    assert chart.canvas.day_at(0) == date.today()
    repo.complete_planner_task(first)
    page.refresh()
    workspace.tabs.setCurrentIndex(0)
    workspace.tabs.setCurrentIndex(4)
    app.processEvents()
    assert chart.canvas.day_at(0) == date.today() - timedelta(days=2)
    page.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_day_list_project_surface_survives_selection(app, repo, theme):
    old_style = app.styleSheet()
    app.setStyleSheet(stylesheet(theme))
    repo.set_setting("theme", theme)
    project = repo.save_work_project("Project", color="#ed35ac")
    identifier = repo.save_planner_task("Task", date.today())
    repo.save_work_item("planner", identifier, project_id=project)
    page = Dashboard(repo, I18n("en"), productivity=True)
    page.resize(1280, 790)
    page.show()
    page.workspace.tabs.setCurrentIndex(4)
    app.processEvents()
    samples = []

    def inspect():
        dialog = next(w for w in app.allWidgets() if isinstance(w, RoundedDialog) and w.isVisible())
        try:
            listing = dialog.findChild(QListWidget)
            item = listing.item(0)
            expected = item.background().color()
            for selected in (False, True):
                item.setSelected(selected)
                app.processEvents()
                rect = listing.visualItemRect(item)
                image = listing.viewport().grab().toImage()
                scale = image.devicePixelRatio()
                actual = image.pixelColor(
                    round((rect.right() - 18) * scale), round(rect.center().y() * scale)
                )
                samples.append((actual.name(), expected.name()))
        finally:
            dialog.reject()

    try:
        QTimer.singleShot(20, inspect)
        page.workspace.timeline.open_details(date.today())
        assert len(samples) == 2
        assert all(actual == expected for actual, expected in samples)
    finally:
        page.close()
        app.setStyleSheet(old_style)
