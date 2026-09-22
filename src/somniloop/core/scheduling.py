from __future__ import annotations

import calendar
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from .models import ScheduleType


def _as_schedule_type(value: str | ScheduleType) -> ScheduleType:
    return value if isinstance(value, ScheduleType) else ScheduleType(value)


def week_bounds(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def clamped_date(year: int, month: int, day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def is_due(
    schedule_type: str | ScheduleType,
    payload: dict[str, Any],
    day: date,
    anchor: date,
) -> bool:
    kind = _as_schedule_type(schedule_type)
    if day < anchor:
        return False
    if kind == ScheduleType.DAILY:
        return True
    if kind == ScheduleType.INTERVAL:
        interval = max(1, int(payload.get("days", 1)))
        schedule_anchor = date.fromisoformat(payload.get("anchor", anchor.isoformat()))
        return day >= schedule_anchor and (day - schedule_anchor).days % interval == 0
    if kind == ScheduleType.WEEKDAYS:
        weekdays = {int(x) for x in payload.get("weekdays", [])}
        return day.weekday() in weekdays
    if kind == ScheduleType.MONTHLY:
        target = clamped_date(day.year, day.month, int(payload.get("day", 1)))
        return day == target
    if kind == ScheduleType.YEARLY:
        target = clamped_date(
            day.year,
            int(payload.get("month", 1)),
            int(payload.get("day", 1)),
        )
        return day == target
    # Weekly quota has flexible days; the repository handles it by week.
    return False


def due_dates_between(
    schedule_type: str | ScheduleType,
    payload: dict[str, Any],
    start: date,
    end: date,
    anchor: date,
) -> list[date]:
    if end < start:
        return []
    return [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if is_due(schedule_type, payload, start + timedelta(days=offset), anchor)
    ]


def merge_dates(groups: Iterable[Iterable[date]]) -> list[date]:
    return sorted({day for group in groups for day in group})
