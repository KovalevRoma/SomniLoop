from datetime import date

from somniloop.core.models import ScheduleType
from somniloop.core.scheduling import is_due, week_bounds


def test_interval_schedule_uses_anchor():
    anchor = date(2026, 8, 1)
    payload = {"days": 2, "anchor": anchor.isoformat()}
    assert is_due(ScheduleType.INTERVAL, payload, date(2026, 8, 1), anchor)
    assert not is_due(ScheduleType.INTERVAL, payload, date(2026, 8, 2), anchor)
    assert is_due(ScheduleType.INTERVAL, payload, date(2026, 8, 3), anchor)


def test_weekdays_schedule():
    anchor = date(2026, 8, 1)
    payload = {"weekdays": [0, 4]}
    assert is_due(ScheduleType.WEEKDAYS, payload, date(2026, 8, 24), anchor)
    assert is_due(ScheduleType.WEEKDAYS, payload, date(2026, 8, 28), anchor)
    assert not is_due(ScheduleType.WEEKDAYS, payload, date(2026, 8, 27), anchor)


def test_monthly_and_yearly_clamp_to_last_day():
    anchor = date(2020, 1, 1)
    assert is_due(ScheduleType.MONTHLY, {"day": 31}, date(2026, 4, 30), anchor)
    assert is_due(ScheduleType.YEARLY, {"month": 2, "day": 29}, date(2025, 2, 28), anchor)


def test_week_bounds_are_monday_to_sunday():
    assert week_bounds(date(2026, 8, 27)) == (date(2026, 8, 24), date(2026, 8, 30))
