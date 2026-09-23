"""Incremental dashboard snapshots; history remains in the repository's month cache."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from PySide6.QtCore import QDate, QLocale

from somniloop.core.models import (
    DashboardMeta,
    DayTask,
    ScheduleType,
    TaskState,
    Tracker,
    TrackerMode,
)
from somniloop.core.scheduling import is_due


def local_date(day, i18n, *, full=False):
    if isinstance(day, str):
        day = date.fromisoformat(day)
    locale = QLocale("ru_RU" if i18n.language == "ru" else "en_GB")
    return locale.toString(
        QDate(day.year, day.month, day.day), "dddd, d MMMM yyyy" if full else "d MMM yyyy"
    )


def planner_in_next_24_hours(task, now: datetime) -> bool:
    """Include overdue tasks and the next 24 elapsed hours in local time.

    A date without a time means the start of that day. Timestamps keep the
    window at 24 hours even across local daylight-saving transitions.
    """
    due = datetime.fromisoformat(f"{task.due_date}T{task.due_time or '00:00'}")
    return due.timestamp() <= now.timestamp() + 24 * 60 * 60


@dataclass(eq=True)
class TrackerSnapshot:
    tracker: Tracker
    meta: DashboardMeta
    tasks: list[DayTask]
    occurrences: list[tuple[date, list[DayTask]]]
    next_date: date | None


def tracker_snapshot(repository, tracker, today):
    meta = repository.dashboard_meta(tracker, today)
    tasks = repository.day_summary(tracker, today).tasks
    if (
        tracker.schedule_type == ScheduleType.WEEKLY_QUOTA
        and not tasks
        and today >= tracker.created_on
    ):
        if (meta.quota_done or 0) < (meta.quota_target or 1):
            tasks = [DayTask(task) for task in repository.list_tasks(tracker.id)]
    occurrences = [(today, tasks)] if tasks else []
    next_date = today if tasks else None
    if tracker.mode == TrackerMode.MANUAL:
        dates = repository.list_manual_dates(tracker.id)
        for day in dates:
            if day < today:
                pending = repository.day_summary(tracker, day).tasks
                if any(item.state in (TaskState.UNSET, TaskState.PARTIAL) for item in pending):
                    occurrences.append((day, pending))
        next_date = min(
            (
                day
                for day, items in occurrences
                if any(item.state != TaskState.DONE for item in items)
            ),
            default=meta.next_date,
        )
    elif next_date is None:
        # Only the next occurrence is needed for sorting, not a full future calendar.
        candidates = (
            repository.list_tasks(tracker.id)
            if tracker.schedule_type == ScheduleType.ITEM_DATES
            else [None]
        )
        for offset in range(367):
            day = today + timedelta(days=offset)
            if any(
                is_due(
                    item.schedule_type if item else tracker.schedule_type,
                    item.schedule if item else tracker.schedule,
                    day,
                    tracker.created_on,
                )
                for item in candidates
                if item is None or item.schedule_type
            ):
                next_date = day
                break
    return TrackerSnapshot(tracker, meta, tasks, sorted(occurrences), next_date)


class DashboardData:
    def __init__(self, repository):
        self.repository = repository
        self.trackers = {}
        self.planner = []
        self.completed = []
        self.generation = -1
        self.today = date.today()

    def refresh(self, changed_tracker=None, planner_only=False):
        today = date.today()
        changed = self.generation != self.repository.connection.total_changes or today != self.today
        if not changed:
            return
        records = self.repository.list_trackers()
        current = {}
        for tracker in records:
            previous = self.trackers.get(tracker.id)
            reuse = (
                previous is not None
                and previous.tracker == tracker
                and today == self.today
                and (planner_only or changed_tracker is not None and tracker.id != changed_tracker)
            )
            current[tracker.id] = (
                previous if reuse else tracker_snapshot(self.repository, tracker, today)
            )
        self.trackers = current
        self.planner = self.repository.list_planner_tasks()
        self.completed = self.repository.list_planner_tasks(True, completed_on=today)
        self.today = today
        self.generation = self.repository.connection.total_changes

    def filtered(self, category="all", query="", order="attention"):
        words = query.casefold().replace("ё", "е").split()
        records = [
            record
            for record in self.trackers.values()
            if (category == "all" or record.tracker.mode.value == category)
            and all(
                word
                in (record.tracker.name + " " + record.tracker.description)
                .casefold()
                .replace("ё", "е")
                for word in words
            )
        ]

        def key(record):
            name = record.tracker.name.casefold()
            if order == "date":
                return (record.next_date or date.max, name)
            if order == "streak":
                return (-record.meta.streak, name)
            if order == "name":
                return (name,)
            return (not record.meta.needs_attention, record.next_date or date.max, name)

        return sorted(records, key=key)
