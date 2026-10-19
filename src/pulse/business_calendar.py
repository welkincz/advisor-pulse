"""Business calendar shared by the generator and the DQ031 volume check.

The generator scales each weekday's activity by these factors. DQ031 divides weekly volume
by the same expectation, so a statutory-holiday week or the February lift is compared like
for like instead of warning. At real scale the factors would be estimated from prior years.
"""

from __future__ import annotations

from datetime import date, timedelta

WEEKDAY_WEIGHTS = (1.08, 1.12, 1.04, 0.98, 0.78)  # Monday to Friday
HOLIDAY_FACTOR = 0.65
FEBRUARY_FACTOR = 1.10


def is_holiday(day: date) -> bool:
    """Common national/bank holidays; this is a synthetic weekday volume pattern."""
    if (day.month, day.day) in {(1, 1), (7, 1), (9, 30), (11, 11), (12, 25), (12, 26)}:
        return True
    monday_number = (day.day - 1) // 7 + 1
    return day.weekday() == 0 and (
        (day.month, monday_number) in {(2, 3), (9, 1), (10, 2)}
        or (day.month == 5 and 18 <= day.day <= 24)
    )


def seasonal_factor(day: date) -> float:
    return FEBRUARY_FACTOR if day.month == 2 else 1.0


def holiday_factor(day: date) -> float:
    return HOLIDAY_FACTOR if is_holiday(day) else 1.0


def week_factor(iso_week_id: str) -> float:
    """Expected weekly volume relative to an ordinary week: 1.0 with no holiday or season."""
    year, week = iso_week_id.split("-W")
    monday = date.fromisocalendar(int(year), int(week), 1)
    expected = sum(
        weight * seasonal_factor(day) * holiday_factor(day)
        for weight, day in zip(
            WEEKDAY_WEIGHTS, (monday + timedelta(days=i) for i in range(5)), strict=True
        )
    )
    return expected / sum(WEEKDAY_WEIGHTS)
