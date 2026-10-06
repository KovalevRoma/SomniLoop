"""Successful writes notify optional observers without changing persistence."""

from datetime import date

import pytest

from somniloop.core.activity import ActivityEvents
from somniloop.core.database import Repository
from somniloop.core.models import ScheduleType, TaskState, TrackerMode


def test_notifications_follow_successful_planner_writes(tmp_path):
    repo = Repository(tmp_path / "events.db")
    events = []
    unsubscribe = repo.activity.subscribe(events.append)
    try:
        with pytest.raises(ValueError):
            repo.save_planner_task("", date.today())
        assert events == []
        task = repo.save_planner_task("Task", date.today())
        assert events == ["created"]
        repo.save_planner_task("Edited", date.today(), task_id=task)
        repo.set_planner_task_state(task, TaskState.UNSET)
        assert events == ["created"]
        repo.set_planner_task_state(task, TaskState.NOT_DONE)
        assert events[-1] == "not_done"
        repo.archive_planner_task(task)
        assert events[-1] == "archived"
        before = list(events)
        repo.archive_planner_task(task, False)
        assert events == before
        unsubscribe()
        repo.save_planner_task("Another", date.today())
        assert events == before
    finally:
        repo.close()


def test_failing_optional_observer_does_not_block_other_observers():
    bus = ActivityEvents()
    received = []

    def broken(event):
        raise RuntimeError("Optional animation failed")

    bus.subscribe(broken)
    bus.subscribe(received.append)
    bus.emit("created")
    assert received == ["created"]


def test_habit_rollover_does_not_emit_failure_but_explicit_mark_does(tmp_path):
    repo = Repository(tmp_path / "habit.db")
    events = []
    repo.activity.subscribe(events.append)
    try:
        tracker_id = repo.create_tracker("Habit", "", TrackerMode.REGULAR,
                                         ScheduleType.DAILY, {}, ["Item"])
        tracker = repo.get_tracker(tracker_id)
        task = repo.list_tasks(tracker_id)[0]
        assert events == ["created"]
        repo.day_summary(tracker, date.today())
        repo.set_task_state(tracker_id, task.id, date.today(), TaskState.UNSET)
        assert events == ["created"]
        repo.set_task_state(tracker_id, task.id, date.today(), TaskState.NOT_DONE)
        assert events == ["created", "not_done"]
    finally:
        repo.close()
