from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class TrackerMode(StrEnum):
    REGULAR = "regular"
    MANUAL = "manual"


class ScheduleType(StrEnum):
    DAILY = "daily"
    INTERVAL = "interval"
    WEEKDAYS = "weekdays"
    WEEKLY_QUOTA = "weekly_quota"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    ITEM_DATES = "item_dates"
    MANUAL = "manual"


class TaskState(StrEnum):
    UNSET = "unset"
    DONE = "done"
    PARTIAL = "partial"
    NOT_DONE = "not_done"


class DayStatus(StrEnum):
    UNSCHEDULED = "unscheduled"
    UNSET = "unset"
    DONE = "done"
    PARTIAL = "partial"
    MISSED = "missed"


@dataclass(slots=True)
class Tracker:
    id: int
    name: str
    description: str
    mode: TrackerMode
    schedule_type: ScheduleType
    schedule: dict[str, Any]
    created_on: date
    color: str = "#8267e8"
    archived: bool = False


@dataclass(slots=True)
class Task:
    id: int
    tracker_id: int
    name: str
    details: str = ""
    position: int = 0
    schedule_type: ScheduleType | None = None
    schedule: dict[str, Any] = field(default_factory=dict)
    occurrence_date: str | None = None


@dataclass(slots=True)
class DayTask:
    task: Task
    state: TaskState = TaskState.UNSET


@dataclass(slots=True)
class DaySummary:
    day: date
    status: DayStatus
    tasks: list[DayTask]


@dataclass(slots=True)
class DashboardMeta:
    streak: int
    streak_unit: str
    needs_attention: bool
    schedule_label: str
    quota_done: int | None = None
    quota_target: int | None = None
    next_date: date | None = None


@dataclass(slots=True)
class Note:
    id: int
    title: str
    content: str
    entry_date: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class Person:
    id: int
    name: str
    relationship: str
    raw_notes: str
    biography: str
    birth_date: str
    education: str
    occupation: str
    facts: list[str]
    updated_at: str
    analyzed_at: str
    interests: str = ""
    birth_date_input: str = ""
    interests_input: str = ""
    history: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    managed: bool = True
    contact: str = ""
    group_name: str = ""
    clarifications: list[dict[str, Any]] = field(default_factory=list)
    manual_overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgeNode:
    id: str
    label: str
    category: str
    details: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgeEdge:
    source: str
    target: str
    relation: str


@dataclass(slots=True)
class PlannerTask:
    id: int
    title: str
    due_date: str
    description: str
    completed: bool
    archived: bool
    updated_at: str
    items: list[dict[str, Any]] = field(default_factory=list)
    state: TaskState = TaskState.UNSET
