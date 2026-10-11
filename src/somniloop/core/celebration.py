"""Completion-only celebration rules, independent of rendering and audio."""

from datetime import date, timedelta

from .models import DayStatus


def pending_today(repository):
    return {
        row[0] for row in repository.connection.execute(
            "SELECT id FROM planner_tasks WHERE due_date=? AND completed=0 AND archived=0",
            (date.today().isoformat(),),
        )
    }


def celebrate_task(repository, task_id, before):
    if task_id in before and not pending_today(repository):
        repository.celebrations.emit(1.0)


def habit_fraction(repository, tracker, today):
    days = 0
    while days < 30 and today - timedelta(days=days) >= tracker.created_on:
        day = today - timedelta(days=days)
        if repository.day_summary(tracker, day).status != DayStatus.DONE:
            break
        days += 1
    return days / 30
