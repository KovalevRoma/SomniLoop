"""Projects extend existing databases without changing schedules or losing exports."""

import sqlite3
from datetime import date, timedelta

import pytest

from somniloop.core.database import Repository
from somniloop.core.models import ScheduleType, TrackerMode


@pytest.fixture
def repo(tmp_path):
    repository = Repository(tmp_path / "work.db")
    yield repository
    repository.close()


def test_work_day_is_not_the_deadline_and_metadata_survives_restart(repo):
    deadline = date.today() + timedelta(days=10)
    task = repo.save_planner_task("Prepare lesson", deadline)
    project = repo.save_work_project("Teaching", "Deliver 8 lessons")
    repo.save_work_item("planner", task, project_id=project, priority=2,
                        planned_on=date.today().isoformat(), next_action="Open lesson notes")
    assert repo.list_planner_tasks()[0].due_date == deadline.isoformat()
    second = Repository(repo.path)
    try:
        assert second.work_metadata()[("planner", task)]["project_id"] == project
        assert second.work_metadata()[("planner", task)]["priority"] == 2
    finally:
        second.close()


def test_project_archiving_does_not_archive_linked_work(repo):
    task = repo.save_planner_task("Book trip", date.today())
    tracker = repo.create_tracker("Vocabulary", "", TrackerMode.REGULAR, ScheduleType.DAILY, {})
    project = repo.save_work_project("Vacation")
    for kind, identifier in (("planner", task), ("tracker", tracker)):
        repo.save_work_item(kind, identifier, project_id=project)
    repo.archive_work_project(project)
    assert repo.work_projects() == []
    assert len(repo.list_planner_tasks()) == len(repo.list_trackers()) == 1
    repo.archive_work_project(project, False)
    assert repo.work_projects()[0]["name"] == "Vacation"


def test_inbox_conversion_is_explicit_and_atomic(repo):
    capture = repo.capture_work("  An idea  ")
    assert repo.list_planner_tasks() == []
    identifier = repo.schedule_capture(capture, date.today())
    assert repo.work_inbox() == []
    assert repo.list_planner_tasks()[0].id == identifier
    with pytest.raises(ValueError):
        repo.schedule_capture(capture, date.today())
    assert len(repo.list_planner_tasks()) == 1


def test_export_roundtrip_and_older_export(repo):
    project = repo.save_work_project("Home")
    task = repo.save_planner_task("Clean", date.today())
    repo.save_work_item("planner", task, project_id=project)
    repo.capture_work("New thought")
    payload = repo.export_payload()
    repo.restore_payload(payload)
    assert repo.work_projects()[0]["name"] == "Home"
    assert len(repo.work_inbox()) == 1
    assert repo.work_metadata()[("planner", task)]["project_id"] == project
    for table in ("work_projects", "work_items", "work_inbox"):
        del payload["tables"][table]
    repo.restore_payload(payload)
    assert repo.work_projects() == repo.work_inbox() == []
    assert repo.work_metadata() == {}
    assert len(repo.list_planner_tasks()) == 1


def test_invalid_metadata_and_removed_task(repo):
    task = repo.save_planner_task("Work", date.today())
    with pytest.raises(ValueError):
        repo.save_work_item("planner", task, priority=4)
    with pytest.raises(ValueError):
        repo.save_work_item("planner", task, planned_on="bad")
    repo.save_work_item("planner", task, priority=1)
    with repo.connection:
        repo.connection.execute("DELETE FROM planner_tasks WHERE id=?", (task,))
    assert repo.work_metadata() == {}


def test_project_colors_and_order_roundtrip(repo):
    first = repo.save_work_project("Z project", color="#a45db2")
    second = repo.save_work_project("A project", color="#278b71")
    repo.reorder_work_projects([second, first])
    repo.save_work_project("Renamed", project_id=first)
    payload = repo.export_payload()
    repo.restore_payload(payload)
    assert [p["id"] for p in repo.work_projects()] == [second, first]
    assert repo.work_projects()[1]["color"] == "#a45db2"
    reopened = Repository(repo.path)
    try:
        assert [p["id"] for p in reopened.work_projects()] == [second, first]
    finally:
        reopened.close()
    with pytest.raises(ValueError):
        repo.reorder_work_projects([first, first])
    with pytest.raises(ValueError):
        repo.save_work_project("Bad", color="red; background: black")
    for row in payload["tables"]["work_projects"]:
        row.pop("color")
        row.pop("sort_order")
    repo.restore_payload(payload)
    assert all(p["color"] == "#3778bd" for p in repo.work_projects())


def test_existing_project_schema_is_extended_without_losing_data(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE work_projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                           "outcome TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0)")
        connection.execute("INSERT INTO work_projects(name) VALUES ('Existing')")
    repository = Repository(path)
    try:
        assert repository.work_projects()[0]["name"] == "Existing"
        assert repository.work_projects()[0]["color"] == "#3778bd"
    finally:
        repository.close()


def test_new_project_colors_are_distinct_and_manual_colors_survive(repo):
    for index in range(8):
        repo.save_work_project(f"Project {index}")
    colors = [p["color"] for p in repo.work_projects()]
    assert len(set(colors)) == 8
    project = repo.save_work_project("Custom", color="#123456")
    repo.save_work_project("Renamed", project_id=project)
    assert next(p for p in repo.work_projects() if p["id"] == project)["color"] == "#123456"
    assert repo.next_project_color() not in colors + ["#123456"]


def test_delete_project_preserves_tasks_and_metadata(repo):
    project = repo.save_work_project("Home")
    task = repo.save_planner_task("Clean", date.today(), items=["Kitchen"])
    tracker = repo.create_tracker("Exercise", "", TrackerMode.REGULAR, ScheduleType.DAILY, {})
    for kind, identifier in (("planner", task), ("tracker", tracker)):
        repo.save_work_item(kind, identifier, project_id=project, next_action="Keep me")
    repo.delete_work_project(project)
    assert repo.work_projects(True) == []
    assert repo.list_planner_tasks()[0].items[0]["title"] == "Kitchen"
    assert len(repo.list_trackers()) == 1
    assert all(value["project_id"] is None and value["next_action"] == "Keep me"
               for value in repo.work_metadata().values())
