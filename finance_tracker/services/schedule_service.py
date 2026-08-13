from __future__ import annotations

import calendar
from datetime import date, timedelta

from finance_tracker.db.models import Schedule, ScheduleType, WeekendPolicy


class InvalidSchedule(ValueError):
    pass


def _month_offset(value: date, months: int, day: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _adjust_weekend(value: date, policy: str | None) -> date:
    policy = policy or WeekendPolicy.EXACT.value
    if policy == WeekendPolicy.EXACT.value:
        return value
    if policy == WeekendPolicy.PREVIOUS_BUSINESS_DAY.value:
        while value.weekday() >= 5:
            value -= timedelta(days=1)
        return value
    if policy == WeekendPolicy.NEXT_BUSINESS_DAY.value:
        while value.weekday() >= 5:
            value += timedelta(days=1)
        return value
    raise InvalidSchedule(f"Unsupported weekend policy: {policy}")


def occurrences(schedule: Schedule, range_start: date, range_end: date) -> list[date]:
    """Return unique actual occurrence dates within an inclusive range."""
    if range_end < range_start:
        raise ValueError("range_end must not be before range_start")
    lower = max(filter(None, (range_start, schedule.start_date)), default=range_start)
    upper = min(filter(None, (range_end, schedule.end_date)), default=range_end)
    if upper < lower:
        return []

    kind = ScheduleType(schedule.schedule_type)
    candidates: list[date] = []
    if kind == ScheduleType.SPECIFIC_DATES:
        candidates = [entry.occurrence_date for entry in schedule.dates]
    elif kind == ScheduleType.ONE_TIME:
        if schedule.anchor_date is None:
            raise InvalidSchedule("one_time requires anchor_date")
        candidates = [schedule.anchor_date]
    elif kind in (ScheduleType.WEEKLY, ScheduleType.EVERY_N_WEEKS):
        if schedule.anchor_date is None:
            raise InvalidSchedule("weekly schedules require anchor_date")
        weeks = 1 if kind == ScheduleType.WEEKLY else schedule.interval
        if weeks < 1:
            raise InvalidSchedule("interval must be positive")
        step = timedelta(weeks=weeks)
        cursor = schedule.anchor_date
        if cursor < lower:
            cursor += step * ((lower - cursor).days // step.days)
            while cursor < lower:
                cursor += step
        while cursor <= upper:
            candidates.append(cursor)
            cursor += step
    elif kind in (ScheduleType.MONTHLY, ScheduleType.EVERY_N_MONTHS):
        if schedule.day_of_month is None or not 1 <= schedule.day_of_month <= 31:
            raise InvalidSchedule("monthly schedules require day_of_month from 1 to 31")
        interval = 1 if kind == ScheduleType.MONTHLY else schedule.interval
        if interval < 1:
            raise InvalidSchedule("interval must be positive")
        anchor = schedule.anchor_date or schedule.start_date or lower.replace(day=1)
        cursor = _month_offset(anchor.replace(day=1), 0, schedule.day_of_month)
        while cursor < lower:
            cursor = _month_offset(cursor.replace(day=1), interval, schedule.day_of_month)
        while cursor <= upper:
            candidates.append(cursor)
            cursor = _month_offset(cursor.replace(day=1), interval, schedule.day_of_month)
    elif kind == ScheduleType.YEARLY:
        if schedule.month_of_year is None or not 1 <= schedule.month_of_year <= 12:
            raise InvalidSchedule("yearly schedules require month_of_year from 1 to 12")
        if schedule.day_of_month is None or not 1 <= schedule.day_of_month <= 31:
            raise InvalidSchedule("yearly schedules require day_of_month from 1 to 31")
        for year in range(lower.year, upper.year + 1):
            day = min(schedule.day_of_month, calendar.monthrange(year, schedule.month_of_year)[1])
            candidates.append(date(year, schedule.month_of_year, day))
    else:  # pragma: no cover - Enum guards this
        raise InvalidSchedule(f"Unsupported schedule type: {kind}")

    adjusted = (_adjust_weekend(item, schedule.weekend_policy) for item in candidates)
    return sorted({item for item in adjusted if lower <= item <= upper})

