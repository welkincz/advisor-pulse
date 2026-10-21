"""The fiscal calendar (PLAN.md §6): the year starts on 1 November, as at Canadian banks.

FY26 runs from 2025-11-01 to 2026-10-31; Q1 is Nov–Jan, Q2 Feb–Apr, Q3 May–Jul, Q4 Aug–Oct.
A weekly figure counts in the quarter that holds its ISO week's Sunday. dbt has the same
rules as macros (dbt/macros/dates.sql); this module serves Python (fixtures, tests).
"""

from __future__ import annotations

from datetime import date, timedelta

FIRST_MONTH = 11


def fiscal_month(day: date) -> int:
    """1 for November … 12 for October."""
    return (day.month - FIRST_MONTH) % 12 + 1


def fiscal_year(day: date) -> int:
    return day.year + (1 if day.month >= FIRST_MONTH else 0)


def fiscal_quarter(day: date) -> int:
    return (fiscal_month(day) - 1) // 3 + 1


def fiscal_quarter_id(day: date) -> str:
    """'FY26-Q1' for 2025-11-01."""
    return f"FY{fiscal_year(day) % 100:02d}-Q{fiscal_quarter(day)}"


def quarter_bounds(day: date) -> tuple[date, date]:
    """First and last calendar day of the fiscal quarter holding ``day``."""
    offset = (fiscal_month(day) - 1) % 3
    month = (day.month - offset - 1) % 12 + 1
    year = day.year if month <= day.month else day.year - 1
    start = date(year, month, 1)
    end_month = month + 3
    end = date(year + (end_month - 1) // 12, (end_month - 1) % 12 + 1, 1) - timedelta(days=1)
    return start, end


def week_sunday(iso_week_id: str) -> date:
    return date.fromisocalendar(int(iso_week_id[:4]), int(iso_week_id[6:]), 7)


def week_fiscal_quarter_id(iso_week_id: str) -> str:
    """The quarter a week reports in: the one holding its Sunday."""
    return fiscal_quarter_id(week_sunday(iso_week_id))


def weeks_in_quarter(quarter_id: str) -> int:
    """ISO weeks whose Sunday falls in the quarter (13 or 14)."""
    year = 2000 + int(quarter_id[2:4])
    q = int(quarter_id[-1])
    # Step to the quarter's first month, then count Sundays up to its last day.
    month = (FIRST_MONTH - 1 + 3 * (q - 1)) % 12 + 1
    start = date(year - 1 if month >= FIRST_MONTH else year, month, 1)
    first, last = quarter_bounds(start)
    sunday = first + timedelta(days=(6 - first.weekday()) % 7)
    return (last - sunday).days // 7 + 1
