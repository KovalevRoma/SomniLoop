from __future__ import annotations

import calendar
import re
from datetime import date, datetime

MONTHS = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
ENGLISH_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def display_date(value: date | str, *, include_year: bool = True) -> str:
    if isinstance(value, str):
        parsed = parse_birth_date(value)
        if parsed is None:
            return value or "—"
        year, month, day = parsed
    else:
        year, month, day = value.year, value.month, value.day
    suffix = f" {year}" if include_year and year else ""
    return f"{day:02d} {MONTHS[month - 1]}{suffix}"


def display_timestamp(value: str) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value)
        return f"{display_date(parsed.date())}, {parsed:%H:%M}"
    except ValueError:
        return value


def parse_birth_date(value: str) -> tuple[int | None, int, int] | None:
    value = value.strip()
    if not value:
        return None
    if value.startswith("--"):
        try:
            parsed = date.fromisoformat("2000" + value[1:])
            return None, parsed.month, parsed.day
        except ValueError:
            return None
    english_date = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3})(?:\s+(\d{4}))?", value)
    if english_date:
        day, month, year = english_date.groups()
        try:
            month_number = [item.casefold() for item in ENGLISH_MONTHS].index(month.casefold()) + 1
            parsed = date(int(year or 2000), month_number, int(day))
            return int(year) if year else None, parsed.month, parsed.day
        except ValueError:
            return None
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m"):
        try:
            # A leap year keeps 29 February valid when the year is unknown.
            has_year = "%Y" in pattern
            parsed = datetime.strptime(
                value if has_year else value + " 2000", pattern if has_year else pattern + " %Y"
            )
            return parsed.year if has_year else None, parsed.month, parsed.day
        except ValueError:
            continue
    return None


def normalize_birth_date(value: str) -> str:
    parsed = parse_birth_date(value)
    if parsed is None:
        return ""
    year, month, day = parsed
    return f"{year:04d}-{month:02d}-{day:02d}" if year else f"--{month:02d}-{day:02d}"


def age_on(birth_date: str, as_of: date) -> int | None:
    parsed = parse_birth_date(birth_date)
    if parsed is None or parsed[0] is None:
        return None
    year, _, _ = parsed
    birthday = birthday_in_year(birth_date, as_of.year)
    age = as_of.year - year - (as_of < birthday)
    return age if age >= 0 else None


def birthday_in_year(birth_date: str, year: int) -> date | None:
    parsed = parse_birth_date(birth_date)
    if parsed is None:
        return None
    _, month, day = parsed
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def one_month_before(day: date) -> date:
    year, month = (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
