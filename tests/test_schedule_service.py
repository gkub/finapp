from datetime import date

from finance_tracker.db.models import Schedule, ScheduleDate, ScheduleType
from finance_tracker.services.schedule_service import occurrences


def test_biweekly_is_not_twice_monthly():
    schedule = Schedule(schedule_type=ScheduleType.EVERY_N_WEEKS.value, interval=2, anchor_date=date(2026, 8, 14))
    assert occurrences(schedule, date(2026, 8, 1), date(2026, 10, 10)) == [
        date(2026, 8, 14), date(2026, 8, 28), date(2026, 9, 11),
        date(2026, 9, 25), date(2026, 10, 9),
    ]


def test_month_end_clamps_and_handles_leap_year():
    schedule = Schedule(schedule_type=ScheduleType.MONTHLY.value, day_of_month=31)
    assert occurrences(schedule, date(2024, 1, 1), date(2024, 4, 30)) == [
        date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31), date(2024, 4, 30),
    ]


def test_yearly_and_boundaries():
    schedule = Schedule(schedule_type=ScheduleType.YEARLY.value, month_of_year=11, day_of_month=17,
                        start_date=date(2026, 12, 1), end_date=date(2028, 1, 1))
    assert occurrences(schedule, date(2025, 1, 1), date(2030, 1, 1)) == [date(2027, 11, 17)]


def test_specific_dates_are_sorted_unique_and_bounded():
    schedule = Schedule(schedule_type=ScheduleType.SPECIFIC_DATES.value)
    schedule.dates = [ScheduleDate(occurrence_date=date(2026, 10, 4)), ScheduleDate(occurrence_date=date(2026, 9, 12))]
    assert occurrences(schedule, date(2026, 9, 1), date(2026, 10, 31)) == [date(2026, 9, 12), date(2026, 10, 4)]

